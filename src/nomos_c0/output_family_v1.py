"""Expand finite owner-field templates into the existing checked output graph."""

from __future__ import annotations

from collections.abc import Mapping

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame, C0SourceContext
from .condition_source_v0 import lower_author_expression

_MAX_FAMILIES = 32
_MAX_OWNERS = 64
_MAX_FIELDS = 64
_MAX_OUTPUTS = 1024
_MAX_NODES = 131072


def _name(value: object, path: str) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or not value.isidentifier()
        or value.startswith("_")
    ):
        raise C0LawError(f"{path}: expected a public ASCII identifier")
    return value


def _instantiate(
    value: object, alias: str, owner: str, path: str, budget: list[int], locals=None
) -> object:
    budget[0] -= 1
    if budget[0] < 0:
        raise C0LawError("output families exceed the finite expansion node limit")
    operation, operand = next(iter(value.items()))

    def child(expression):
        return _instantiate(expression, alias, owner, path, budget, locals)

    if operation == "const":
        return value.copy()
    if operation == "ref":
        if locals and type(operand) is str and operand.split(".")[0] in locals:
            head, *tail = operand.split(".", 1)
            return {"ref": locals[head] + ("." + tail[0] if tail else "")}
        if type(operand) is str and (operand == alias or operand.startswith(f"{alias}.")):
            return {"ref": owner + operand[len(alias) :]}
        return value.copy()
    if type(operand) is list:
        return {operation: [child(item) for item in operand]}
    if operation in ("not", "is_none", "not_none", "die_next_seed"):
        return {operation: child(operand)}
    if operation == "call":
        return {
            "call": {
                "ref": operand["ref"],
                "args": {key: child(item) for key, item in operand["args"].items()},
            }
        }
    if operation in ("record", "copy"):
        key = "fields" if operation == "record" else "changes"
        result = {key: {field: child(item) for field, item in operand[key].items()}}
        if operation == "record":
            result["type"] = operand["type"]
        else:
            result["from"] = child(operand["from"])
        return {operation: result}
    if (
        operation == "let"
        and operand["name"] in {alias, *(locals or {})}
        or (
            operation
            in (
                "none_matching",
                "exists",
                "exactly_one",
                "unique_by",
                "count_matching",
                "collect_matching",
            )
            and operand["as"] in {alias, *(locals or {})}
        )
    ):
        raise C0LawError(f"{path}: output family alias is shadowed by a local declaration")
    return {
        operation: {
            key: item if key in ("as", "key", "name") else child(item)
            for key, item in operand.items()
        }
    }


def expand_output_families(
    declarations: object,
    *,
    roots: Mapping[str, type],
    binding_names: set[str],
    state_outputs: Mapping[str, str],
    explicit_outputs: Mapping[str, object],
    source_context: C0SourceContext | None = None,
    origins: dict[str, C0SourceContext] | None = None,
    computations: list[dict] | None = None,
    computation_paths: dict[str, dict[str, str]] | None = None,
    computation_origins: dict[str, C0SourceContext] | None = None,
) -> tuple[dict[str, dict], dict[str, dict[str, str]]]:
    """Resolve only declared endpoints; no owner discovery or runtime interpretation."""
    if type(declarations) is not list or not 1 <= len(declarations) <= _MAX_FAMILIES:
        raise C0LawError("output_families needs 1..32 finite declarations")
    names: set[str] = set()
    used = set(explicit_outputs)
    outputs: dict[str, dict] = {}
    locations: dict[str, dict[str, str]] = {}
    authored_templates: list[object] = []
    generated_names: set[str] = set()
    budget = [_MAX_NODES]
    for declaration in declarations:
        if (
            type(declaration) is not dict
            or not {"name", "owners", "as", "fields"} <= set(declaration)
            or set(declaration) - {"name", "owners", "as", "fields", "bindings"}
        ):
            raise C0LawError("output family has missing or unknown fields")
        name = _name(declaration["name"], "output family name")
        path = f"output_families.{name}"
        if name in names:
            raise C0LawError(f"{path}: repeated family name")
        names.add(name)
        alias = _name(declaration["as"], f"{path}.as")
        if alias in roots or alias in binding_names or alias == "occurrence":
            raise C0LawError(f"{path}: output family alias shadows a root or binding")
        owners, fields = declaration["owners"], declaration["fields"]
        if type(owners) is not list or not 1 <= len(owners) <= _MAX_OWNERS:
            raise C0LawError(f"{path}: owners needs 1..64 explicit roots")
        selected = []
        for owner in owners:
            owner = _name(owner, f"{path}.owners")
            if owner not in roots or owner in selected:
                raise C0LawError(f"{path}: unknown or repeated owner root")
            selected.append(owner)
        if type(fields) is not dict or not 1 <= len(fields) <= _MAX_FIELDS:
            raise C0LawError(f"{path}: fields needs 1..64 explicit fields")
        if len(outputs) + len(selected) * len(fields) > _MAX_OUTPUTS:
            raise C0LawError("output families exceed the finite output limit of 1024")
        local_declarations = declaration.get("bindings", {})
        if type(local_declarations) is not dict or len(local_declarations) > 64:
            raise C0LawError(f"{path}: bindings needs a finite ordered mapping")
        if local_declarations and computations is None:
            raise C0LawError(f"{path}: member computations need a checked binding consumer")
        local_templates = {}
        for local, expression in local_declarations.items():
            _name(local, f"{path}.bindings")
            if local in roots or local in binding_names or local in (alias, "occurrence"):
                raise C0LawError(f"{path}: member binding shadows a root or binding")
            origin = f"{path}.bindings.{local}"
            local_templates[local] = (origin, *lower_author_expression(expression, path=origin))
        templates = {}
        for field, expression in fields.items():
            _name(field, f"{path}.fields")
            origin = f"{path}.fields.{field}"
            templates[field] = (origin, *lower_author_expression(expression, path=origin))
        for owner in selected:
            local_names = {local: f"{name}_{owner}_{local}" for local in local_templates}
            generated_names.update(local_names.values())
            for local, (origin, expression, paths) in local_templates.items():
                generated = local_names[local]
                if generated in roots or generated in binding_names:
                    raise C0LawError(f"{path}: expanded member binding name collides")
                binding_names.add(generated)
                if len(computations) >= 64:
                    raise C0LawError("member computations exceed the finite binding limit of 64")
                index = len(computations)
                computations.append(
                    {
                        "name": generated,
                        "stage": "effect",
                        "let": _instantiate(expression, alias, owner, origin, budget, local_names),
                    }
                )
                concrete = f"{path}.owners.{owner}.bindings.{local}"
                if computation_paths is not None:
                    computation_paths[generated] = {
                        f"bindings[{index}].let" + key[len(origin) :]: concrete
                        + authored[len(origin) :]
                        for key, authored in paths.items()
                    }
                if source_context is not None and computation_origins is not None:
                    frame = C0OriginFrame(
                        "output_member_binding",
                        generated,
                        concrete,
                        source_context.locate(origin),
                        (("family", name), ("owner", owner), ("binding", local)),
                    )
                    computation_origins[generated] = C0SourceContext(
                        source_context.index,
                        (*source_context.aliases, (concrete, source_context.indexed_path(origin)))
                        if frame.span
                        else source_context.aliases,
                        (*source_context.frames_for(origin), frame),
                    )
            for field, (origin, expression, paths) in templates.items():
                concrete = f"{path}.owners.{owner}.fields.{field}"
                endpoint = f"{owner}.{field}"
                if endpoint not in state_outputs:
                    raise C0LawError(f"{concrete}: endpoint has no checked state write port")
                output = state_outputs[endpoint]
                if output in used:
                    raise C0LawError(f"{concrete}: output overlaps another write")
                used.add(output)
                outputs[output] = _instantiate(
                    expression, alias, owner, concrete, budget, local_names
                )
                internal = f"outputs.{output}"
                locations[output] = {
                    internal + key[len(origin) :]: concrete + authored[len(origin) :]
                    for key, authored in paths.items()
                }
                if source_context is not None and origins is not None:
                    span = source_context.locate(origin)
                    frame = C0OriginFrame(
                        "output_instance",
                        output,
                        concrete,
                        span,
                        (("family", name), ("owner", owner), ("field", field)),
                    )
                    origins[output] = C0SourceContext(
                        source_context.index,
                        (*source_context.aliases, (concrete, source_context.indexed_path(origin)))
                        if span
                        else source_context.aliases,
                        (*source_context.frames_for(origin), frame),
                    )
        authored_templates.extend(expression for _, expression, _ in local_templates.values())
        authored_templates.extend(expression for _, expression, _ in templates.values())

    def references_generated(value):
        if isinstance(value, dict):
            if set(value) == {"ref"} and isinstance(value["ref"], str):
                return value["ref"].split(".")[0] in generated_names
            return any(references_generated(item) for item in value.values())
        if isinstance(value, list):
            return any(references_generated(item) for item in value)
        return False

    if any(references_generated(template) for template in authored_templates):
        raise C0LawError("member bindings cannot escape their output family via generated names")
    return outputs, locations
