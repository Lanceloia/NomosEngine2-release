"""Finite checked construction plans, separate from live-world effects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import get_args, get_type_hints

from nomos_kernel import K0OwnerKey
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0BindingError, C0LawError
from .composable_value_v1 import (
    _CONSTRUCTION_CONTEXT,
    C0ValuePorts,
    _assignable,
    _compile_expression,
    _complete_value_fields,
    _eval,
    _infer_expr_type,
)
from .expression_ir_v1 import C0Expression
from .nominal_fields_v1 import _OPAQUE_REFERENCES
from .nominal_signatures_v1 import C0NominalSignatures
from .replayable_die_v1 import MAX_SEED, next_seed
from .value_symbols_v1 import C0SymbolicExpression, C0SymbolicType, _ValueSymbolTranslation

ALGORITHM = "nomos.c0.die.roll.v1/next.v1"


def _name(value: object) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or not value.isidentifier()
        or value.startswith("_")
        or value in {"seed", "occurrence"}
    ):
        raise C0LawError("opening construction name is malformed or reserved")
    return value


def _finite(raw: object, label: str, *, nonempty: bool = False) -> list:
    if type(raw) is not list or not int(nonempty) <= len(raw) <= 64:
        raise C0LawError(f"opening construction {label} must be a finite list")
    return raw


def _row(raw: object, names: set[str]) -> dict:
    if type(raw) is not dict or set(raw) != names:
        raise C0LawError("opening construction has missing or unknown fields")
    return raw


def _data_type(annotation: object, active: tuple = ()) -> None:
    if annotation in _OPAQUE_REFERENCES:
        raise C0LawError("opening construction cannot carry an occurrence or instance ref")
    if annotation in (str, int, bool, type(None)):
        return
    if annotation in active:
        raise C0LawError("opening construction type is recursive")
    if get_args(annotation):
        for item in get_args(annotation):
            if item is not Ellipsis:
                _data_type(item, (*active, annotation))
        return
    if isinstance(annotation, type) and is_dataclass(annotation):
        for item in get_type_hints(annotation).values():
            _data_type(item, (*active, annotation))
        return
    raise C0LawError("opening construction type is not closed nominal data")


@dataclass(frozen=True)
class C0OpeningConstructionPort:
    symbol: str
    kind: str
    read: tuple[str, ...]
    fields: tuple[str, ...]
    construct: tuple[str, ...]


def check_construction_ports(raw, checked) -> tuple[C0OpeningConstructionPort, ...]:
    kinds = {item.symbol: item for item in checked.object_kinds}
    records = dict(checked.records)
    result = []
    for declaration in _finite(raw, "ports"):
        item = _row(declaration, {"symbol", "kind", "read", "fields", "construct"})
        symbol = _name(item["symbol"])
        kind = kinds.get(item["kind"]) if type(item["kind"]) is str else None
        if kind is None or any(port.symbol == symbol for port in result):
            raise C0LawError("opening construction port kind is unknown or name repeated")
        hints = get_type_hints(kind.k0_kind.state_type)
        read = tuple(_name(name) for name in _finite(item["read"], "read fields"))
        outputs = tuple(
            _name(name) for name in _finite(item["fields"], "output fields", nonempty=True)
        )
        if (
            len(set(read)) != len(read)
            or len(set(outputs)) != len(outputs)
            or set(read) & set(outputs)
            or not set(read + outputs) <= hints.keys()
        ):
            raise C0LawError("opening construction fields are unknown, repeated or conflicting")
        for name in read + outputs:
            _data_type(hints[name])
        construct = tuple(_name(name) for name in _finite(item["construct"], "constructors"))
        if len(set(construct)) != len(construct) or not set(construct) <= records.keys():
            raise C0LawError("opening construction constructor is unknown or repeated")
        for name in construct:
            _data_type(records[name])
        result.append(C0OpeningConstructionPort(symbol, kind.symbol, read, outputs, construct))
    return tuple(result)


def _ports(records, read_types, output_types, constructors, pure_definitions=()) -> C0ValuePorts:
    readable = {}
    for annotation in read_types.values():
        for carrier, names in _complete_value_fields(annotation).items():
            readable.setdefault(carrier, set()).update(names)
    selected = MappingProxyType({carrier: frozenset(names) for carrier, names in readable.items()})
    empty = MappingProxyType({})
    return C0ValuePorts(
        roots=empty,
        readable_paths=frozenset(),
        admission_readable_paths=frozenset(),
        readable_fields=selected,
        admission_readable_fields=selected,
        writable_fields=empty,
        record_types=MappingProxyType({name: records[name] for name in constructors}),
        tuple_fields=empty,
        admission_tuple_fields=empty,
        collection_keys=empty,
        outputs=MappingProxyType(output_types),
        pure_definitions=pure_definitions,
        construction=True,
    )


def _no_draw(value) -> None:
    if type(value) in (C0Expression, C0SymbolicExpression):
        if value.operation in {"die_roll", "die_next_seed"}:
            raise C0LawError("opening dice must be explicit draw bindings")
        _no_draw(value.operand)
    elif isinstance(value, Mapping):
        for item in value.values():
            _no_draw(item)
    elif type(value) is tuple:
        for item in value:
            _no_draw(item)


def _draw_shape(expression) -> None:
    if (
        expression.operation != "die_roll"
        or not isinstance(expression.operand, Mapping)
        or set(expression.operand) != {"seed", "sides"}
    ):
        raise C0LawError("opening draw binding needs one explicit die roll")
    seed = expression.operand["seed"]
    if type(seed) is not type(expression) or seed.operation != "ref" or seed.operand != "seed":
        raise C0LawError("opening draw must consume the current declared seed")
    _no_draw(expression.operand)


def _check_bound_expression(expression, env, ports):
    def check(node, local_env, local_ports, proofs, *, occurrence=False, depth=0):
        if type(node) is not C0Expression or node.stage != "construction" or occurrence:
            raise C0LawError("opening IR contains an unchecked or non-construction expression")
        inferred = _infer_expr_type(
            node, local_env, local_ports, proofs, occurrence=False, depth=depth, _check=check
        )
        if inferred != node.result_type:
            raise C0LawError("opening IR expression annotation differs from its checked type")
        _data_type(inferred)
        return inferred

    return check(expression, env, ports, set())


@dataclass(frozen=True)
class C0OpeningBindingIR:
    name: str
    draw: bool
    expression: C0SymbolicExpression


@dataclass(frozen=True)
class C0OpeningConstructionIR:
    port: C0OpeningConstructionPort
    state_record: str
    seed: str
    source_digest: str
    rule_digest: str
    inputs: tuple[tuple[str, C0SymbolicType], ...]
    bindings: tuple[C0OpeningBindingIR, ...]
    outputs: tuple[tuple[str, C0SymbolicExpression], ...]

    def __post_init__(self) -> None:
        if (
            type(self.port) is not C0OpeningConstructionPort
            or type(self.inputs) is not tuple
            or type(self.bindings) is not tuple
            or type(self.outputs) is not tuple
            or tuple(name for name, _ in self.inputs) != self.port.read
            or tuple(name for name, _ in self.outputs) != self.port.fields
            or len(set(self.port.fields)) != len(self.port.fields)
            or set(self.port.read) & set(self.port.fields)
            or not self.port.fields
        ):
            raise C0LawError("opening construction IR has malformed field coverage")
        _name(self.seed)
        declared = {"seed", *self.port.read}
        for binding in self.bindings:
            if (
                type(binding) is not C0OpeningBindingIR
                or type(binding.draw) is not bool
                or _name(binding.name) in declared
            ):
                raise C0LawError("opening construction IR bindings alias or are malformed")
            declared.add(binding.name)
        if any(type(annotation) is not C0SymbolicType for _, annotation in self.inputs) or any(
            type(expression) is not C0SymbolicExpression or expression.stage != "construction"
            for expression in (
                *(binding.expression for binding in self.bindings),
                *(expression for _, expression in self.outputs),
            )
        ):
            raise C0LawError("opening construction IR needs checked symbolic construction values")
        for binding in self.bindings:
            if binding.draw:
                _draw_shape(binding.expression)
            else:
                _no_draw(binding.expression)
        for _, expression in self.outputs:
            _no_draw(expression)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _symbolic_data(value):
    if is_dataclass(value):
        return {field.name: _symbolic_data(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {name: _symbolic_data(item) for name, item in value.items()}
    if type(value) in (tuple, list):
        return [_symbolic_data(item) for item in value]
    return value


def compile_constructions(raw, ports, selected_kinds, backend, pure_definitions, source):
    selections = _finite(raw, "selection")
    if not selections:
        return ()
    available = {port.symbol: port for port in ports}
    kinds = {kind.symbol: kind for kind in selected_kinds}
    records = dict(backend.layout.records)
    translation = _ValueSymbolTranslation(records, binding=False)
    result = []
    try:
        source_digest = sha256(canonical_json(source).encode()).hexdigest()
    except (TypeError, ValueError, RecursionError) as error:
        raise C0LawError("opening construction Source must be finite JSON data") from error
    for declaration in selections:
        row = _row(declaration, {"kind", "using", "seed", "bindings", "outputs"})
        port = available.get(row["using"]) if type(row["using"]) is str else None
        kind = kinds.get(row["kind"]) if type(row["kind"]) is str else None
        if (
            port is None
            or kind is None
            or port.kind != kind.symbol
            or any(plan.port.kind == kind.symbol for plan in result)
        ):
            raise C0LawError(
                "opening construction selects an unknown, mismatched or repeated kind/port"
            )
        seed = _name(row["seed"])
        hints = get_type_hints(kind.k0_kind.state_type)
        if not set(port.read + port.fields) <= hints.keys():
            raise C0LawError("opening construction port has an undeclared field")
        for name in port.read + port.fields:
            _data_type(hints[name])
        inputs = {name: hints[name] for name in port.read}
        ports_value = _ports(
            records,
            inputs,
            {name: hints[name] for name in port.fields},
            port.construct,
            pure_definitions,
        )
        env = {**inputs, "seed": int}
        bindings = []
        for raw_binding in _finite(row["bindings"], "bindings"):
            if type(raw_binding) is not dict or set(raw_binding) not in (
                {"name", "value"},
                {"name", "draw"},
            ):
                raise C0LawError("opening construction binding must be value or draw")
            name = _name(raw_binding["name"])
            if name in env:
                raise C0LawError("opening construction binding repeats or shadows an input")
            draw = "draw" in raw_binding
            expression = _compile_expression(
                raw_binding["draw" if draw else "value"],
                env,
                ports_value,
                set(),
                origin=f"opening_constructions.{kind.symbol}.bindings.{name}",
            )
            _no_draw(expression)
            if draw:
                if expression.result_type is not int:
                    raise C0LawError("opening construction draw sides must be integer")
                expression = _compile_expression(
                    {"die_roll": {"seed": {"ref": "seed"}, "sides": expression}},
                    env,
                    ports_value,
                    set(),
                    origin=f"opening_constructions.{kind.symbol}.draw.{name}",
                )
            _data_type(expression.result_type)
            env[name] = expression.result_type
            bindings.append(
                C0OpeningBindingIR(
                    name, draw, _ValueSymbolTranslation(records, binding=False).tree(expression)
                )
            )
        outputs = row["outputs"]
        if type(outputs) is not dict or set(outputs) != set(port.fields):
            raise C0LawError("opening construction outputs differ from the declared fields")
        checked_outputs = []
        for name in port.fields:
            expression = _compile_expression(
                outputs[name],
                env,
                ports_value,
                set(),
                origin=f"opening_constructions.{kind.symbol}.outputs.{name}",
            )
            _no_draw(expression)
            if not _assignable(expression.result_type, hints[name]):
                raise C0LawError("opening construction output has the wrong nominal type")
            checked_outputs.append(
                (name, _ValueSymbolTranslation(records, binding=False).tree(expression))
            )
        rule_digest = sha256(
            canonical_json(
                {
                    "selection": row,
                    "port": {field.name: getattr(port, field.name) for field in fields(port)},
                    "bindings": _symbolic_data(tuple(bindings)),
                    "outputs": _symbolic_data(tuple(checked_outputs)),
                }
            ).encode()
        ).hexdigest()
        result.append(
            C0OpeningConstructionIR(
                port,
                kind.state_record,
                seed,
                source_digest,
                rule_digest,
                tuple(
                    (name, translation.symbolize_type(annotation))
                    for name, annotation in inputs.items()
                ),
                tuple(bindings),
                tuple(checked_outputs),
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class C0BoundOpeningConstruction:
    ir: C0OpeningConstructionIR
    ports: C0ValuePorts
    inputs: tuple[tuple[str, object], ...]
    bindings: tuple[tuple[str, bool, C0Expression], ...]
    outputs: tuple[tuple[str, C0Expression], ...]


def bind_constructions(plans, records, selected_kinds):
    translation = _ValueSymbolTranslation(records, binding=True)
    kinds = {kind.symbol: kind for kind in selected_kinds}
    result = []
    for plan in plans:
        plan.__post_init__()
        kind = kinds.get(plan.port.kind)
        if kind is None or records.get(plan.state_record) is not kind.k0_kind.state_type:
            raise C0LawError("opening construction differs from the generated Object layout")
        inputs = tuple(
            (name, translation.bind_type(annotation).annotation) for name, annotation in plan.inputs
        )
        outputs = tuple((name, translation.tree(expression)) for name, expression in plan.outputs)
        hints = get_type_hints(kind.k0_kind.state_type)
        if (
            tuple(name for name, _ in inputs) != plan.port.read
            or any(hints.get(name) != annotation for name, annotation in inputs)
            or tuple(name for name, _ in outputs) != plan.port.fields
            or any(
                not _assignable(expression.result_type, hints.get(name))
                for name, expression in outputs
            )
        ):
            raise C0LawError("opening construction field types differ from the selected Object")
        ports = _ports(
            records,
            dict(inputs),
            {name: hints[name] for name in plan.port.fields},
            plan.port.construct,
        )
        bindings = tuple(
            (item.name, item.draw, translation.tree(item.expression)) for item in plan.bindings
        )
        env = {**dict(inputs), "seed": int}
        for name, draw, expression in bindings:
            if draw:
                _draw_shape(expression)
            else:
                _no_draw(expression)
            env[name] = _check_bound_expression(expression, env, ports)
        for _, expression in outputs:
            _no_draw(expression)
            _check_bound_expression(expression, env, ports)
        result.append(
            C0BoundOpeningConstruction(
                plan,
                ports,
                inputs,
                bindings,
                outputs,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class C0OpeningDraw:
    binding: str
    input_seed: int
    sides: int
    result: int
    output_seed: int


@dataclass(frozen=True)
class C0OpeningConstructionSlot:
    slot: int
    kind: str
    rule_digest: str
    seed: str
    input_seed: int
    output_seed: int
    draws: tuple[C0OpeningDraw, ...]
    state: object
    individual: _K0IndividualRef | None = None
    owner: K0OwnerKey | None = None


@dataclass(frozen=True)
class C0OpeningConstructionReceipt:
    input_json: str
    source_digest: str
    plans: tuple[C0OpeningConstructionIR, ...]
    seeds: tuple[tuple[str, int], ...]
    final_seeds: tuple[tuple[str, int], ...]
    slots: tuple[C0OpeningConstructionSlot, ...]
    signatures: C0NominalSignatures
    algorithm: str = ALGORITHM


def construct_opening(plans, seeds, raw_objects, opening_value):
    expected = {plan.ir.seed for plan in plans}
    if (
        type(seeds) is not dict
        or set(seeds) != expected
        or any(type(seed) is not int or not 0 <= seed <= MAX_SEED for seed in seeds.values())
    ):
        raise C0BindingError("opening seeds do not fill the exact bounded construction inputs")
    current = {name: seeds[name] for name in dict.fromkeys(plan.ir.seed for plan in plans)}
    objects = [dict(raw) if type(raw) is dict else raw for raw in raw_objects]
    slots = []
    for plan in plans:
        for slot, raw in enumerate(objects):
            if type(raw) is not dict or raw.get("kind") != plan.ir.port.kind:
                continue
            if set(raw) != {"kind", "state"} or type(raw["state"]) is not dict:
                raise C0BindingError("opening construction Object row is malformed")
            literal = raw["state"]
            if set(literal) & set(plan.ir.port.fields):
                raise C0BindingError("opening construction output conflicts with a literal field")
            if not set(plan.ir.port.read) <= set(literal):
                raise C0BindingError("opening construction is missing a declared literal input")
            context = {
                name: opening_value(annotation, literal[name]) for name, annotation in plan.inputs
            }
            context["_construction"] = _CONSTRUCTION_CONTEXT
            initial_seed = current[plan.ir.seed]
            context["seed"] = initial_seed
            env = {**dict(plan.inputs), "seed": int}
            draws = []
            for name, draw, expression in plan.bindings:
                if draw:
                    value = _eval(expression, context, env, plan.ports)
                    input_seed, sides, _ = context.pop("_construction_draw")
                    output_seed = next_seed(context["seed"])
                    draws.append(C0OpeningDraw(name, input_seed, sides, value, output_seed))
                    context["seed"] = output_seed
                else:
                    value = _eval(expression, context, env, plan.ports)
                context[name] = value
                env[name] = expression.result_type
            generated = {
                name: _eval(expression, context, env, plan.ports)
                for name, expression in plan.outputs
            }
            current[plan.ir.seed] = context["seed"]
            # Typed generated values are joined later with literal values, never exposed partially.
            objects[slot] = {"kind": raw["kind"], "state": literal, "generated": generated}
            slots.append(
                C0OpeningConstructionSlot(
                    slot,
                    raw["kind"],
                    plan.ir.rule_digest,
                    plan.ir.seed,
                    initial_seed,
                    context["seed"],
                    tuple(draws),
                    None,
                )
            )
    return objects, tuple(slots), tuple(current.items())
