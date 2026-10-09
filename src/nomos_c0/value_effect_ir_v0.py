"""Checked state-output compositions, without an independent runtime evaluator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .author_contract_v1 import C0LawError
from .condition_source_v0 import lower_author_expression
from .expression_ir_v1 import C0Expression


@dataclass(frozen=True)
class C0ValueEffectIR:
    name: str
    operation: str
    endpoints: tuple[tuple[str, str], ...]
    writes: tuple[tuple[str, str], ...]
    activation: C0Expression
    checks: C0Expression | None
    results: tuple[tuple[str, C0Expression], ...]
    source_path: str


@dataclass(frozen=True)
class _EffectSource:
    name: str
    operation: str
    endpoints: tuple[tuple[str, str], ...]
    writes: tuple[tuple[str, str], ...]
    activation: dict
    conditional: bool
    inputs: tuple[tuple[dict, type], ...]
    checks: dict | None
    labels: tuple[str, ...]
    results: tuple[tuple[str, dict], ...]
    activation_paths: dict[str, str]
    result_paths: dict[str, dict[str, str]] = field(default_factory=dict)


def read_value_effects(
    declarations: object,
    state_outputs: Mapping[str, str],
    explicit_outputs: Mapping[str, object],
    *,
    max_integer: int,
) -> tuple[_EffectSource, ...]:
    """Resolve author endpoints only through the adapter's checked write graph."""
    if type(declarations) is not list or not 1 <= len(declarations) <= 32:
        raise C0LawError("effects need a nonempty finite ordered list")
    names: set[str] = set()
    used = set(explicit_outputs)
    effects = []
    for entry in declarations:
        if type(entry) is not dict or len(entry) != 1:
            raise C0LawError("each effect needs exactly one name")
        name, body = next(iter(entry.items()))
        if (
            type(name) is not str
            or not name.isascii()
            or not name.isidentifier()
            or name.startswith("_")
            or name in names
        ):
            raise C0LawError("effect name is malformed or repeated")
        names.add(name)
        path = f"effects.{name}"
        kinds = (
            set(body) & {"debit", "transfer", "consume", "assign"} if type(body) is dict else set()
        )
        if len(kinds) != 1:
            raise C0LawError(f"{path}: effect needs exactly one operation")
        operation = next(iter(kinds))
        if operation == "assign":
            effects.append(_read_assignment(name, body, state_outputs, used))
            continue
        required = {operation} if operation == "consume" else {operation, "amount", "floor"}
        if operation == "transfer":
            required.add("capacity")
        if not required <= set(body) or set(body) - required - {"when", "mirror"}:
            raise C0LawError(f"{path}: {operation} has missing or unknown fields")

        def expression(field):
            return lower_author_expression(body[field], path=f"{path}.{field}")[0]

        conditional = "when" in body
        activation, activation_paths = lower_author_expression(
            body.get("when", True), path=f"{path}.when"
        )

        def mirrors(value):
            if type(value) is not list or len(value) > 32:
                raise C0LawError(f"{path}: mirror must be a finite endpoint list")
            return value

        if operation == "transfer":
            target = body["transfer"]
            mirror = body.get("mirror", {})
            if (
                type(target) is not dict
                or set(target) != {"from", "to"}
                or type(mirror) is not dict
                or set(mirror) - {"from", "to"}
            ):
                raise C0LawError(f"{path}: transfer needs exact from/to endpoints and mirrors")
            endpoints = (("from", target["from"]), ("to", target["to"]))
            groups = [
                (role, [target[role], *mirrors(mirror.get(role, []))]) for role in ("from", "to")
            ]
        else:
            endpoints = (("target", body[operation]),)
            groups = [("target", [body[operation], *mirrors(body.get("mirror", []))])]
        writes, roles = [], []
        for role, group in groups:
            for endpoint in group:
                if type(endpoint) is not str or endpoint not in state_outputs:
                    raise C0LawError(f"{path}: endpoint has no checked state write port")
                output = state_outputs[endpoint]
                if output in used:
                    raise C0LawError(f"{path}: effect output overlaps another write")
                used.add(output)
                writes.append((endpoint, output))
                roles.append(role)
        current = {"ref": endpoints[0][1]}
        if operation == "consume":
            inputs = ((current, bool),)
            tests = [("available", current)]
            values = {"target": {"const": False}}
        else:
            amount, floor = expression("amount"), expression("floor")
            inputs = ((current, int), (amount, int), (floor, int))
            tests = [
                ("positive_amount", {"lt": [{"const": 0}, amount]}),
                ("nonnegative_floor", {"le": [{"const": 0}, floor]}),
                ("bounded_balance", {"le": [current, {"const": max_integer}]}),
                ("above_floor", {"le": [floor, current]}),
            ]
            values = {"target": {"sub": [current, amount]}}
            if operation == "transfer":
                # Both subtractions must be safe before they test sufficient resources.
                source, destination = {"ref": target["from"]}, {"ref": target["to"]}
                current = source
                capacity = expression("capacity")
                inputs = (
                    (source, int),
                    (destination, int),
                    (amount, int),
                    (floor, int),
                    (capacity, int),
                )
                tests = [
                    ("positive_amount", {"lt": [{"const": 0}, amount]}),
                    ("bounded_amount", {"le": [amount, {"const": max_integer}]}),
                    ("nonnegative_floor", {"le": [{"const": 0}, floor]}),
                    ("above_floor", {"le": [floor, source]}),
                    ("bounded_balance", {"le": [source, {"const": max_integer}]}),
                    ("nonnegative_destination", {"le": [{"const": 0}, destination]}),
                    ("within_capacity", {"le": [destination, capacity]}),
                    ("bounded_capacity", {"le": [capacity, {"const": max_integer}]}),
                ]
                values = {"from": {"sub": [source, amount]}, "to": {"add": [destination, amount]}}
            tests.append(("sufficient", {"le": [amount, {"sub": [current, floor]}]}))
            if operation == "transfer":
                tests.append(("capacity", {"le": [amount, {"sub": [capacity, destination]}]}))
        active_checks = {"all": [test for _, test in tests]}
        checks = (
            {"if": {"when": activation, "then": active_checks, "else": {"const": True}}}
            if conditional
            else {"all": [activation, *active_checks["all"]]}
        )
        results = tuple(
            (
                output,
                {"if": {"when": activation, "then": values[role], "else": {"ref": endpoint}}}
                if conditional
                else values[role],
            )
            for (endpoint, output), role in zip(writes, roles, strict=True)
        )
        effects.append(
            _EffectSource(
                name,
                operation,
                endpoints,
                tuple(writes),
                activation,
                conditional,
                inputs,
                checks,
                tuple(label for label, _ in tests),
                results,
                activation_paths,
            )
        )
    return tuple(effects)


def _read_assignment(name, body, state_outputs, used):
    path = f"effects.{name}"
    assignments = body["assign"]
    if (
        set(body) - {"assign", "when"}
        or type(assignments) is not dict
        or not 1 <= len(assignments) <= 32
    ):
        raise C0LawError(f"{path}: assign needs a finite nonempty endpoint mapping")
    activation, activation_paths = lower_author_expression(
        body.get("when", True), path=f"{path}.when"
    )
    writes, results, result_paths = [], [], {}
    for endpoint, value in assignments.items():
        if type(endpoint) is not str or endpoint not in state_outputs:
            raise C0LawError(f"{path}: endpoint has no checked state write port")
        output = state_outputs[endpoint]
        if output in used:
            raise C0LawError(f"{path}: effect output overlaps another write")
        used.add(output)
        expression, paths = lower_author_expression(value, path=f"{path}.assign.{endpoint}")
        writes.append((endpoint, output))
        results.append(
            (
                output,
                {"if": {"when": activation, "then": expression, "else": {"ref": endpoint}}}
                if "when" in body
                else expression,
            )
        )
        result_paths[output] = paths
    return _EffectSource(
        name,
        "assign",
        tuple(("target", endpoint) for endpoint, _ in writes),
        tuple(writes),
        activation,
        "when" in body,
        (),
        None,
        (),
        tuple(results),
        activation_paths,
        result_paths,
    )


def with_effect_checks(
    guard: dict, paths: dict[str, str], effects: tuple[_EffectSource, ...]
) -> tuple[dict, dict[str, str]]:
    """Keep author guard order, then check all effects on the same pre-state."""
    effects = tuple(effect for effect in effects if effect.checks is not None)
    if not effects:
        return guard, paths
    locations = {
        f"guard.all[0]{path[len('guard') :]}": authored for path, authored in paths.items()
    }
    locations["guard"] = "guard"
    locations["guard.all[1]"] = "effects"

    for index, effect in enumerate(effects):
        internal = f"guard.all[1].all[{index}]"
        effect_path = f"effects.{effect.name}"
        locations.update(_locations(effect.checks, internal, effect_path))
        activation_path = f"{internal}.if.when" if effect.conditional else f"{internal}.all[0]"
        prefix = f"{effect_path}.when"
        locations.update(
            {
                activation_path + key[len(prefix) :]: authored
                for key, authored in effect.activation_paths.items()
            }
        )
        for check, label in enumerate(effect.labels):
            target = (
                f"{internal}.if.then.all[{check}]"
                if effect.conditional
                else f"{internal}.all[{check + 1}]"
            )
            test = (
                effect.checks["if"]["then"]["all"][check]
                if effect.conditional
                else effect.checks["all"][check + 1]
            )
            locations.update(
                _locations(
                    test,
                    target,
                    f"effects.{effect.name}.{label}",
                )
            )
    return {"all": [guard, {"all": [effect.checks for effect in effects]}]}, locations


def _locations(value: object, internal: str, authored: str) -> dict[str, str]:
    result = {internal: authored}
    if type(value) is dict:
        for key, child in value.items():
            result.update(_locations(child, f"{internal}.{key}", authored))
    elif type(value) is list:
        for index, child in enumerate(value):
            result.update(_locations(child, f"{internal}[{index}]", authored))
    return result


def effect_output_paths(effects: tuple[_EffectSource, ...]) -> dict[str, dict[str, str]]:
    """Normalized generated expressions must not be parsed as author text again."""
    paths = {}
    for effect in effects:
        for (endpoint, output), (_, result) in zip(effect.writes, effect.results, strict=True):
            internal = f"outputs.{output}"
            authored = (
                f"effects.{effect.name}.assign.{endpoint}"
                if effect.operation == "assign"
                else f"effects.{effect.name}.writes.{endpoint}"
            )
            paths[output] = _locations(result, internal, authored)
            prefix = internal + ".if.then" if effect.conditional else internal
            paths[output].update(
                {
                    prefix + key[len(authored) :]: value
                    for key, value in effect.result_paths.get(output, {}).items()
                }
            )
            if effect.conditional:
                prefix = f"effects.{effect.name}.when"
                paths[output].update(
                    {
                        f"{internal}.if.when" + key[len(prefix) :]: authored
                        for key, authored in effect.activation_paths.items()
                    }
                )
    return paths
