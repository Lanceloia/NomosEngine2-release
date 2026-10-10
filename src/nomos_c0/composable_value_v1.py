"""Typed, data-only value expressions for authored C0 laws."""

from __future__ import annotations

import json
from collections.abc import Callable, Container, Mapping
from dataclasses import _FIELD, dataclass, replace
from functools import lru_cache
from types import MappingProxyType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError, _unique_object
from .author_document_v1 import C0OriginFrame, C0SourceContext, C0SourceIndex, named_source_paths
from .compile_budget_v1 import COMPILE_BUDGET
from .condition_source_v0 import lower_author_expression
from .expression_ir_v1 import C0Expression, C0ValueType, _ExpressionDraft, closed_value_type
from .generated_record_v1 import is_sealed_nominal_record
from .guard_ir_v0 import C0GuardIR, lower_checked_guard
from .nominal_fields_v1 import _OPAQUE_REFERENCES
from .output_family_v1 import expand_output_families
from .pure_definition_v1 import C0PureDefinition
from .replayable_die_v1 import next_seed as _die_next_seed
from .replayable_die_v1 import roll as _die_roll
from .value_effect_ir_v0 import (
    C0ValueEffectIR,
    effect_output_paths,
    read_value_effects,
    with_effect_checks,
)
from .variant_types_v1 import (
    construct_variant,
    validate_variant,
    variant_cases,
    variant_common_fields,
)

_MAX_INT = (1 << 63) - 1
_MAX_BINDINGS = 64
_UNEVALUATED = object()
_CONSTRUCTION_CONTEXT = object()
_EMPTY_FIELDS = frozenset()


@lru_cache(maxsize=256)
def _resolved_fields(carrier: type) -> dict[str, object]:
    return get_type_hints(carrier)


class C0ValueStateError(ValueError):
    """A checked expression met a malformed current owner state."""


class C0ValueRangeError(C0ValueStateError):
    """A bounded integer expression exceeded its declared value domain."""


@dataclass
class _LazyValue:
    """A compiler-owned cell scoped to one evaluation and one lexical environment."""

    expression: C0Expression
    context: dict[str, object]
    env: dict[str, object]
    ports: C0ValuePorts
    cached: object = _UNEVALUATED

    def resolve(self) -> object:
        if self.cached is _UNEVALUATED:
            result = _eval(self.expression, self.context, self.env, self.ports)
            if not _value_matches(result, self.expression.result_type):
                raise C0ValueStateError("local computation produced a foreign nominal type")
            self.cached = result
        return self.cached


@dataclass(frozen=True)
class C0GuardAlternative:
    path: str
    index: int
    identity: str


@dataclass(frozen=True)
class C0GuardFailure:
    """A false authored predicate on the current, trusted author view."""

    path: str
    expression: str
    names: tuple[str, ...] = ()
    branches: tuple[str, ...] = ()
    provenance: tuple[C0OriginFrame, ...] = ()
    alternatives: tuple[C0GuardAlternative, ...] = ()


@dataclass(frozen=True)
class C0ValuePorts:
    roots: dict[str, type]
    readable_paths: frozenset[str]
    admission_readable_paths: frozenset[str]
    readable_fields: dict[type, frozenset[str]]
    admission_readable_fields: dict[type, frozenset[str]]
    writable_fields: dict[type, frozenset[str]]
    record_types: dict[str, type]
    tuple_fields: dict[object, dict[str, int]]
    admission_tuple_fields: dict[object, dict[str, int]]
    collection_keys: dict[str, str]
    outputs: dict[str, object]
    pure_definitions: tuple[C0PureDefinition, ...] = ()
    source_context: C0SourceContext | None = None
    construction: bool = False
    participant_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    writable_paths: frozenset[str] = frozenset()


def runtime_value_ports(ports: C0ValuePorts) -> C0ValuePorts:
    """Remove diagnostic origins without changing executable authority or definitions."""
    return replace(
        ports,
        source_context=None,
        pure_definitions=tuple(
            replace(item, source_context=None) for item in ports.pure_definitions
        ),
    )


def admission_value_ports(ports: C0ValuePorts) -> C0ValuePorts:
    return replace(
        ports,
        readable_paths=ports.admission_readable_paths,
        readable_fields=ports.admission_readable_fields,
        tuple_fields=ports.admission_tuple_fields,
    )


@dataclass(frozen=True)
class _LocalType:
    """Compile-only alias provenance; a new name cannot enlarge read permissions."""

    annotation: object
    expression: Mapping[str, Any]
    env: dict[str, object]
    ports: C0ValuePorts
    proofs: frozenset[str]
    occurrence: bool = False


def _check_local_projection(local: _LocalType, suffix: str, alias: str, proofs: set[str]) -> None:
    def check(node, remaining, env, current_proofs, case_proof=None):
        if not remaining and "_case_payload" not in node:
            return
        if "ref" in node:
            path = node["ref"]
            inherited = {
                path + proof[len(alias) :]
                for proof in proofs
                if proof == alias or proof.startswith(f"{alias}.")
            }
            if case_proof is not None:
                inherited.add(f"{path}.{case_proof}")
            _ref_type(f"{path}.{remaining}", env, local.ports, current_proofs | inherited)
        elif "_case_payload" in node:
            declaration = node["_case_payload"]
            if not remaining and local.annotation is type(None):
                return
            path = declaration["case"] + (f".{remaining}" if remaining else "")
            check(
                declaration["value"],
                path,
                env,
                current_proofs,
                declaration["case"],
            )
        elif "if" in node:
            declaration = node["if"]
            check(
                declaration["then"],
                remaining,
                env,
                current_proofs
                | _guard_proofs(declaration["when"], env, local.ports, current_proofs),
                case_proof,
            )
            check(declaration["else"], remaining, env, current_proofs, case_proof)
        elif "let" in node:
            declaration = node["let"]
            annotation = _expr_type(
                declaration["value"], env, local.ports, current_proofs, occurrence=local.occurrence
            )
            nested = _LocalType(
                annotation,
                declaration["value"],
                env,
                local.ports,
                frozenset(current_proofs),
                local.occurrence,
            )
            check(
                declaration["in"],
                remaining,
                {**env, declaration["name"]: nested},
                current_proofs,
                case_proof,
            )
        elif "call" in node:
            declaration = node["call"]
            parameters = {
                name: _LocalType(
                    annotation,
                    declaration["args"][name],
                    env,
                    local.ports,
                    frozenset(current_proofs),
                    local.occurrence,
                )
                for name, annotation in declaration["definition"].parameters
            }
            check(declaration["body"], remaining, parameters, set(), case_proof)
        elif "tuple_at" in node:
            collection = node["tuple_at"]["collection"]
            annotation = _expr_type(
                collection, env, local.ports, current_proofs, occurrence=local.occurrence
            )
            member = "_tuple_at_member"
            inherited = {
                member + proof[len(alias) :]
                for proof in proofs
                if proof == alias or proof.startswith(f"{alias}.")
            }
            if case_proof is not None:
                inherited.add(f"{member}.{case_proof}")
            _ref_type(
                f"{member}.{remaining}",
                {**env, member: _tuple_item(annotation)},
                local.ports,
                current_proofs | inherited,
            )
        elif "match" in node:
            declaration = node["match"]
            carrier = (
                declaration["value"].result_type
                if type(declaration["value"]) is C0Expression
                else _expr_type(
                    declaration["value"],
                    env,
                    local.ports,
                    current_proofs,
                    occurrence=local.occurrence,
                )
            )
            for case, arm in declaration["cases"].items():
                nested = _case_local(
                    carrier,
                    declaration["value"],
                    case,
                    env,
                    local.ports,
                    current_proofs,
                    local.occurrence,
                )
                check(
                    arm["then"], remaining, {**env, arm["as"]: nested}, current_proofs, case_proof
                )
        elif "variant" in node:
            declaration = node["variant"]
            first, _, rest = remaining.partition(".")
            if first in declaration["fields"]:
                check(declaration["fields"][first], rest, env, current_proofs)
            elif first == declaration["case"]:
                check(declaration["value"], rest, env, current_proofs)
        elif "record" in node or "copy" in node:
            first, _, rest = remaining.partition(".")
            if "record" in node:
                check(node["record"]["fields"][first], rest, env, current_proofs)
            elif first in node["copy"]["changes"]:
                check(node["copy"]["changes"][first], rest, env, current_proofs)
            else:
                check(node["copy"]["from"], remaining, env, current_proofs)

    check(local.expression, suffix, local.env, set(local.proofs))


def _case_local(carrier, value, case, env, ports, proofs, occurrence):
    return _LocalType(
        variant_cases(carrier)[case],
        {"_case_payload": {"value": value, "case": case}},
        dict(env),
        ports,
        frozenset(proofs),
        occurrence,
    )


def _check_discriminator(carrier, value, env, ports, proofs, occurrence):
    if not variant_cases(carrier):
        raise C0LawError("case selection needs a nonoptional nominal variant")
    _check_local_projection(
        _LocalType(carrier, value, dict(env), ports, frozenset(proofs), occurrence),
        "case",
        "variant_input",
        proofs,
    )


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise C0LawError(f"{label} must be an object with string keys")
    return value


def _exact(value: Mapping[str, Any], names: set[str], label: str) -> None:
    if set(value) != names:
        raise C0LawError(f"{label} has missing or unknown fields")


def _tuple_item(annotation: object) -> object:
    args = get_args(annotation)
    if get_origin(annotation) is not tuple or len(args) != 2 or args[1] is not Ellipsis:
        raise C0LawError("collection must be a homogeneous typed tuple")
    return args[0]


def _variants(annotation: object) -> tuple[object, ...]:
    return get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)


def _nonnull(annotation: object) -> object | None:
    if isinstance(annotation, type):
        return None
    variants = _variants(annotation)
    rest = tuple(value for value in variants if value is not type(None))
    return rest[0] if len(variants) == 2 and len(rest) == 1 else None


def _assignable(actual: object, expected: object) -> bool:
    if actual == expected or actual == tuple[()] and get_origin(expected) is tuple:
        return True
    return all(value in _variants(expected) for value in _variants(actual))


def _frozen_record(carrier: object) -> bool:
    # Generated reflection metadata and descriptors were finalized at Bind.
    # Native records still require the complete current shape check below.
    if is_sealed_nominal_record(carrier):
        return True
    if not (
        isinstance(carrier, type)
        # Kernel references are scalar handles, not author-constructible records.
        and carrier not in _OPAQUE_REFERENCES
        and hasattr(carrier, "__dataclass_fields__")
        and carrier.__dataclass_params__.frozen
    ):
        return False
    # Match dataclasses.fields' real-field filter without allocating a tuple.
    for item in carrier.__dataclass_fields__.values():
        if item._field_type is _FIELD and not item.init:
            return False
    return True


def _complete_value_fields(annotation: object) -> dict[type, frozenset[str]]:
    visible: dict[type, set[str]] = {}
    visited: set[object] = set()

    def expose(current: object) -> None:
        if current in visited:
            return
        visited.add(current)
        if _frozen_record(current):
            hints = _resolved_fields(current)
            visible.setdefault(current, set()).update(hints)
            for field_type in hints.values():
                expose(field_type)
        else:
            for item in get_args(current):
                if item is not Ellipsis and item is not type(None):
                    expose(item)

    expose(annotation)
    return {carrier: frozenset(fields) for carrier, fields in visible.items()}


def _complete_record_paths(root: str, annotation: object) -> frozenset[str]:
    """Exact paths for a compiler-owned full-state check, never a seat grant."""
    paths = {root}

    def visit(prefix, current, active):
        current = _nonnull(current) or current
        if not _frozen_record(current) or current in active:
            return
        for name, field_type in _resolved_fields(current).items():
            path = f"{prefix}.{name}"
            paths.add(path)
            visit(path, field_type, active | {current})

    visit(root, annotation, set())
    return frozenset(paths)


def _field_type(
    annotation: object,
    name: str,
    ports: C0ValuePorts,
    *,
    frozen_record: bool | None = None,
) -> object:
    is_record = _frozen_record(annotation) if frozen_record is None else frozen_record
    if is_record:
        if name not in ports.readable_fields.get(annotation, _EMPTY_FIELDS):
            raise C0LawError("record field is not a declared read port")
        result = _resolved_fields(annotation).get(name)
        if result is None:
            raise C0LawError("record field has no resolved type")
        return result
    projection = ports.tuple_fields.get(annotation)
    if projection is None or name not in projection:
        raise C0LawError("tuple field is not a declared projection")
    return get_args(annotation)[projection[name]]


def _ref_type(
    ref: str,
    env: dict[str, object],
    ports: C0ValuePorts,
    nonnull: set[str],
    *,
    declaring_port: bool = False,
) -> object:
    if ref == "occurrence":
        return K0OccurrenceRef
    parts = ref.split(".")
    root = parts[0]
    if root not in env:
        raise C0LawError("reference has no declared root")
    if (
        root in ports.roots
        and type(env[root]) is not _LocalType
        and ref not in ports.readable_paths
    ):
        raise C0LawError("reference crosses a declared read boundary")
    current: object = env[root]
    local = current if type(current) is _LocalType else None
    if type(current) is _LocalType:
        current = current.annotation
    prefix = root
    for part in parts[1:]:
        if prefix in nonnull or declaring_port:
            current = _nonnull(current) or current
        elif _nonnull(current) is not None:
            raise C0LawError("nullable value was read without a short-circuit guard")
        current = _field_type(current, part, ports)
        prefix = f"{prefix}.{part}"
    if local is not None and (len(parts) > 1 or "_case_payload" in local.expression):
        _check_local_projection(local, ".".join(parts[1:]), root, nonnull)
    return _nonnull(current) if ref in nonnull and _nonnull(current) is not None else current


def _record_field_types(carrier: type) -> dict[str, object]:
    if not _frozen_record(carrier):
        raise C0LawError("record constructor needs a frozen nominal dataclass")
    return _resolved_fields(carrier)


def _contains_tuple_selection(node, env):
    if isinstance(node, Mapping):
        expression = type(node) in (C0Expression, _ExpressionDraft) or (
            set(node) == {"ref"} and type(node["ref"]) is str
        )
        if expression and "tuple_at" in node:
            return True
        if expression and "ref" in node:
            local = env.get(node["ref"].split(".")[0])
            return type(local) is _LocalType and _contains_tuple_selection(
                local.expression, local.env
            )
        if expression and "let" in node:
            declaration = node["let"]
            return _contains_tuple_selection(
                declaration["value"], env
            ) or _contains_tuple_selection(declaration["in"], {**env, declaration["name"]: None})
        if expression and "call" in node:
            declaration = node["call"]
            return _contains_tuple_selection(declaration["args"], env) or _contains_tuple_selection(
                declaration["body"],
                {name: None for name, _ in declaration["definition"].parameters},
            )
        return any(_contains_tuple_selection(value, env) for value in node.values())
    if type(node) in (list, tuple):
        return any(_contains_tuple_selection(value, env) for value in node)
    return False


def _check_materialization(node, annotation, env, ports, proofs, *, selected_only=False):
    """Exporting an aggregate checks its fields, not merely its opaque reference."""
    if not _complete_value_fields(annotation):
        return
    if selected_only and not _contains_tuple_selection(node, env):
        return

    def check(child, kind, child_env, child_ports, child_proofs):
        _check_materialization(
            child, kind, child_env, child_ports, child_proofs, selected_only=selected_only
        )

    if "empty_like" in node:
        return
    if "ref" in node:
        path = node["ref"]
        local = env.get(path)
        if type(local) is _LocalType and "_case_payload" not in local.expression:
            check(local.expression, annotation, local.env, local.ports, set(local.proofs))
            return

        def visit(current, suffix, current_proofs, active=frozenset()):
            if _nonnull(current) is not None:
                current_proofs = current_proofs | {suffix}
            current = _nonnull(current) or current
            if get_origin(current) in (Union, UnionType):
                raise C0LawError("aggregate union materialization needs explicit branches")
            if _frozen_record(current):
                if current in active:
                    raise C0LawError("aggregate materialization needs a finite record shape")
                for name, kind in _resolved_fields(current).items():
                    child = f"{suffix}.{name}"
                    _ref_type(child, env, ports, current_proofs, declaring_port=True)
                    visit(kind, child, current_proofs, active | {current})
            elif get_origin(current) is tuple:
                # Tuple element fields have type-level ports, not indexed root paths.
                for carrier, names in _complete_value_fields(current).items():
                    if not names <= ports.readable_fields.get(carrier, frozenset()):
                        raise C0LawError("collection materialization crosses a declared read port")

        visit(annotation, path, proofs)
    elif "call" in node:
        declaration = node["call"]
        parameters = {
            name: _LocalType(kind, declaration["args"][name], dict(env), ports, frozenset(proofs))
            for name, kind in declaration["definition"].parameters
        }
        check(declaration["body"], annotation, parameters, ports, set())
    elif "let" in node:
        declaration = node["let"]
        kind = _expr_type(declaration["value"], env, ports, proofs, occurrence=True)
        local = _LocalType(kind, declaration["value"], dict(env), ports, frozenset(proofs), True)
        check(declaration["in"], annotation, {**env, declaration["name"]: local}, ports, proofs)
    elif "if" in node:
        declaration = node["if"]
        check(
            declaration["then"],
            _expr_type(
                declaration["then"],
                env,
                ports,
                proofs | _guard_proofs(declaration["when"], env, ports, proofs),
                occurrence=True,
            ),
            env,
            ports,
            proofs | _guard_proofs(declaration["when"], env, ports, proofs),
        )
        check(
            declaration["else"],
            _expr_type(declaration["else"], env, ports, proofs, occurrence=True),
            env,
            ports,
            proofs,
        )
    elif "record" in node or "copy" in node:
        op = "record" if "record" in node else "copy"
        declaration = node[op]
        carrier = _nonnull(annotation) or annotation
        fields = _resolved_fields(carrier)
        selected = declaration["fields" if op == "record" else "changes"]
        for name, kind in fields.items():
            if name in selected:
                check(selected[name], kind, env, ports, proofs)
            elif not selected_only or _contains_tuple_selection(declaration["from"], env):
                original = _LocalType(
                    carrier, declaration["from"], dict(env), ports, frozenset(proofs), True
                )
                _check_local_projection(original, name, "materialized", proofs)
                check(
                    {"ref": f"_materialized.{name}"},
                    kind,
                    {**env, "_materialized": original},
                    ports,
                    proofs,
                )
    elif "const" in node and node["const"] is None and _nonnull(annotation) is not None:
        return
    elif "append" in node:
        check(node["append"][0], annotation, env, ports, proofs)
        check(node["append"][1], _tuple_item(annotation), env, ports, proofs)
    elif "replace_unique" in node:
        declaration = node["replace_unique"]
        check(declaration["collection"], annotation, env, ports, proofs)
        check(declaration["new"], _tuple_item(annotation), env, ports, proofs)
    elif "collect_matching" in node:
        declaration = node["collect_matching"]
        collection = _expr_type(declaration["collection"], env, ports, proofs, occurrence=True)
        item_env = {**env, declaration["as"]: _tuple_item(collection)}
        check(
            declaration["value"],
            _tuple_item(annotation),
            item_env,
            ports,
            proofs | _guard_proofs(declaration["where"], item_env, ports, proofs),
        )
    elif "participant_query" in node:
        check(node["participant_query"]["collection"], annotation, env, ports, proofs)
    elif "collection_query" in node:
        check(node["collection_query"]["collection"], annotation, env, ports, proofs)
    elif "participant_collect" in node:
        declaration = node["participant_collect"]
        for predicate, value in zip(declaration["predicates"], declaration["values"], strict=True):
            check(
                value,
                _tuple_item(annotation),
                env,
                ports,
                proofs | _guard_proofs(predicate, env, ports, proofs),
            )
    elif "insert_missing" in node:
        for name in ("collection", "candidates"):
            check(node["insert_missing"][name], annotation, env, ports, proofs)
    elif "update_matching" in node:
        declaration = node["update_matching"]
        check(declaration["collection"], annotation, env, ports, proofs)
        local_env = {**env, declaration["as"]: _tuple_item(annotation)}
        fields = _record_field_types(_tuple_item(annotation))
        for name, value in declaration["set"].items():
            check(value, fields[name], local_env, ports, proofs)
    elif "tuple_at" in node:
        collection = node["tuple_at"]["collection"]
        kind = _expr_type(collection, env, ports, proofs, occurrence=True)
        _check_materialization(collection, kind, env, ports, proofs)
    elif "variant" in node:
        declaration = node["variant"]
        for name, value in declaration["fields"].items():
            check(value, _resolved_fields(annotation)[name], env, ports, proofs)
        check(
            declaration["value"],
            variant_cases(annotation)[declaration["case"]],
            env,
            ports,
            proofs,
        )
    elif "match" in node:
        declaration = node["match"]
        carrier = _expr_type(declaration["value"], env, ports, proofs, occurrence=True)
        for case, arm in declaration["cases"].items():
            local = _case_local(carrier, declaration["value"], case, env, ports, proofs, True)
            arm_env = {**env, arm["as"]: local}
            check(
                arm["then"],
                _expr_type(arm["then"], arm_env, ports, proofs, occurrence=True),
                arm_env,
                ports,
                proofs,
            )
    else:
        raise C0LawError("aggregate materialization has no checked projection")


def _check_ports(ports: C0ValuePorts) -> C0ValuePorts:
    if type(ports) is not C0ValuePorts or not ports.roots or not ports.outputs:
        raise C0LawError("value ports are not a trusted closed declaration")
    if ports.construction:
        raise C0LawError("opening construction ports cannot authorize live value effects")
    if ports.source_context is not None and type(ports.source_context) is not C0SourceContext:
        raise C0LawError("value source context is malformed")
    COMPILE_BUDGET.check(
        "value_read_paths", len(ports.readable_paths), stage="Value readable paths"
    )
    COMPILE_BUDGET.check(
        "value_read_paths",
        len(ports.admission_readable_paths),
        stage="Value admission readable paths",
    )
    if any(
        type(name) is not str
        or not name
        or (carrier is not _K0IndividualRef and not _frozen_record(_nonnull(carrier) or carrier))
        for name, carrier in ports.roots.items()
    ):
        raise C0LawError("value root is not a frozen nominal record")
    if (
        any(type(path) is not str or not path for path in ports.readable_paths)
        or not ports.admission_readable_paths <= ports.readable_paths
    ):
        raise C0LawError("value read port is malformed")
    if any(
        not _frozen_record(carrier) or not set(names) <= _resolved_fields(carrier).keys()
        for carrier, names in ports.readable_fields.items()
    ):
        raise C0LawError("value record read port is malformed")
    if any(
        not set(names) <= ports.readable_fields.get(carrier, frozenset())
        for carrier, names in ports.admission_readable_fields.items()
    ):
        raise C0LawError("value admission read port exceeds its effect port")
    if any(
        not _frozen_record(carrier) or not set(names) <= _resolved_fields(carrier).keys()
        for carrier, names in ports.writable_fields.items()
    ):
        raise C0LawError("value record write port is malformed")
    if type(ports.writable_paths) is not frozenset:
        raise C0LawError("value owner write paths are not closed")
    from .endpoint_signature_v1 import endpoint_field

    for path in ports.writable_paths:
        carrier, field, _ = endpoint_field(ports.roots, path)
        if field not in ports.writable_fields.get(carrier, frozenset()):
            raise C0LawError("value owner write path lacks its record field port")
    if any(
        type(name) is not str or not name or not _frozen_record(carrier)
        for name, carrier in ports.record_types.items()
    ):
        raise C0LawError("value constructor port is malformed")
    if (
        type(ports.pure_definitions) is not tuple
        or any(type(item) is not C0PureDefinition for item in ports.pure_definitions)
        or len({item.name for item in ports.pure_definitions}) != len(ports.pure_definitions)
    ):
        raise C0LawError("pure definition table is malformed")
    for annotation, projection in ports.tuple_fields.items():
        args = get_args(annotation)
        if (
            get_origin(annotation) is not tuple
            or len(args) < 1
            or args[-1] is Ellipsis
            or not isinstance(projection, Mapping)
            or any(
                type(name) is not str or type(index) is not int or index < 0 or index >= len(args)
                for name, index in projection.items()
            )
            or len(set(projection.values())) != len(projection)
        ):
            raise C0LawError("value tuple projection is malformed")
    if any(
        any(
            ports.tuple_fields.get(annotation, {}).get(name) != index
            for name, index in projection.items()
        )
        for annotation, projection in ports.admission_tuple_fields.items()
    ):
        raise C0LawError("value admission tuple projection exceeds its effect port")
    groups = ports.participant_groups
    if type(groups) is not tuple or len(groups) > 64:
        raise C0LawError("value participant groups are malformed")
    group_names = set()
    for declaration in groups:
        if type(declaration) is not tuple or len(declaration) != 2:
            raise C0LawError("value participant group is malformed")
        name, members = declaration
        if (
            type(name) is not str
            or not name.isascii()
            or not name.isidentifier()
            or name.startswith("_")
            or name in group_names
            or type(members) is not tuple
            or not 1 <= len(members) <= 64
            or any(
                type(member) is not str
                or member not in ports.roots
                or member in {"actor", "scene", "payload", "occurrence", "target"}
                for member in members
            )
            or len(set(members)) != len(members)
            or len({ports.roots[member] for member in members}) != 1
        ):
            raise C0LawError("value participant group needs distinct compatible declared roots")
        group_names.add(name)
    snapshot = C0ValuePorts(
        MappingProxyType(dict(ports.roots)),
        frozenset(ports.readable_paths),
        frozenset(ports.admission_readable_paths),
        MappingProxyType({key: frozenset(value) for key, value in ports.readable_fields.items()}),
        MappingProxyType(
            {key: frozenset(value) for key, value in ports.admission_readable_fields.items()}
        ),
        MappingProxyType({key: frozenset(value) for key, value in ports.writable_fields.items()}),
        MappingProxyType(dict(ports.record_types)),
        MappingProxyType(
            {key: MappingProxyType(dict(value)) for key, value in ports.tuple_fields.items()}
        ),
        MappingProxyType(
            {
                key: MappingProxyType(dict(value))
                for key, value in ports.admission_tuple_fields.items()
            }
        ),
        MappingProxyType(dict(ports.collection_keys)),
        MappingProxyType(dict(ports.outputs)),
        ports.pure_definitions,
        ports.source_context,
        participant_groups=groups,
        writable_paths=frozenset(ports.writable_paths),
    )
    for path, key in snapshot.collection_keys.items():
        if type(path) is not str or path not in snapshot.readable_paths or type(key) is not str:
            raise C0LawError("collection key lacks a declared read port")
        item = _tuple_item(
            _ref_type(path, dict(snapshot.roots), snapshot, set(), declaring_port=True)
        )
        key_type = _field_type(item, key, snapshot)
        if not set(_variants(key_type)) <= {str, int, bool, type(None), K0OccurrenceRef}:
            raise C0LawError("collection key must be a scalar identity value")
    for path in snapshot.readable_paths:
        _ref_type(path, dict(snapshot.roots), snapshot, set(), declaring_port=True)
    return snapshot


def _prepare_expression(
    value: object,
    path: str,
    depth: int = 0,
    *,
    definitions: tuple[C0PureDefinition, ...] = (),
    budget: list[int] | None = None,
    locations: dict[str, str] | None = None,
    source_context: C0SourceContext | None = None,
) -> _ExpressionDraft:
    if budget is None:
        budget = [8192]
    budget[0] -= 1
    if budget[0] < 0:
        raise C0LawError("expanded expression exceeds the finite node limit")
    if depth > 64:
        raise C0LawError("value expression is too deep")
    row = _object(value, "value expression")
    if len(row) != 1:
        raise C0LawError("value expression needs exactly one operation")
    operation, operand = next(iter(row.items()))

    def child(item: object, location: str, context=source_context) -> _ExpressionDraft:
        return _prepare_expression(
            item,
            location,
            depth + 1,
            definitions=definitions,
            budget=budget,
            locations=locations,
            source_context=context,
        )

    location = f"{path}.{operation}"
    if operation == "call":
        declaration = _object(operand, "pure call")
        if type(value) in (C0Expression, _ExpressionDraft):
            declaration = {"ref": declaration["definition"].name, "args": declaration["args"]}
        else:
            _exact(declaration, {"ref", "args"}, "pure call")
        definition = next((item for item in definitions if item.name == declaration["ref"]), None)
        if definition is None:
            raise C0LawError("pure call names an undeclared definition")
        arguments = _object(declaration["args"], "pure arguments")
        _exact(arguments, {name for name, _ in definition.parameters}, "pure arguments")
        if locations is not None:
            prefix = f"pure_definitions.{definition.name}.body"
            locations.update(
                {
                    f"{location}.body{internal[len(prefix) :]}": authored
                    for internal, authored in definition.source_paths.items()
                }
            )
        body_context = definition.source_context
        if source_context is not None or body_context is not None:
            call_path = (locations or {}).get(path, path)
            call_frame = C0OriginFrame(
                "pure_call",
                definition.name,
                call_path,
                source_context.locate(call_path) if source_context is not None else None,
            )
            definition_path = f"pure_definitions.{definition.name}.body"
            definition_frame = C0OriginFrame(
                "pure_definition",
                definition.name,
                definition_path,
                body_context.locate(definition_path) if body_context is not None else None,
            )
            body_context = C0SourceContext(
                body_context.index if body_context is not None else C0SourceIndex({}),
                body_context.aliases if body_context is not None else (),
                (
                    *(source_context.frames_for(call_path) if source_context is not None else ()),
                    call_frame,
                    *(body_context.frames if body_context is not None else ()),
                    definition_frame,
                ),
                body_context.scoped_frames if body_context is not None else (),
            )
        operand = MappingProxyType(
            {
                "definition": replace(definition, source_context=None),
                "args": MappingProxyType(
                    {
                        name: child(item, f"{location}.args.{name}")
                        for name, item in arguments.items()
                    }
                ),
                "body": child(definition.body, f"{location}.body", body_context),
            }
        )
    elif operation in {"not", "is_none", "not_none", "die_next_seed"}:
        operand = child(operand, location)
    elif operation == "match":
        declaration = _object(operand, "variant match")
        _exact(declaration, {"value", "cases"}, "variant match")
        cases = _object(declaration["cases"], "match cases")
        arms = {}
        for case, raw in cases.items():
            arm = _object(raw, "match arm")
            _exact(arm, {"as", "then"}, "match arm")
            arms[case] = {
                "as": arm["as"],
                "then": child(arm["then"], f"{location}.cases.{case}.then"),
            }
        operand = _freeze_tree(
            {"value": child(declaration["value"], f"{location}.value"), "cases": arms}
        )
    elif operation in {"eq", "le", "lt", "add", "sub", "mul", "ceil_div", "append", "all", "any"}:
        if type(operand) not in (list, tuple):
            raise C0LawError("value operation needs an expression sequence")
        operand = tuple(child(item, f"{location}[{index}]") for index, item in enumerate(operand))
    elif operation == "participant_collect":
        operand = _freeze_tree(
            {
                name: tuple(
                    child(item, f"{location}.{name}[{index}]")
                    for index, item in enumerate(operand[name])
                )
                for name in ("predicates", "values")
            }
        )
    elif operation == "collection_query":
        operand = _freeze_tree(
            {
                "collection": child(operand["collection"], location + ".collection"),
                "as": operand["as"],
                "key": operand["key"],
                "right_collection": child(
                    operand["right_collection"], location + ".right_collection"
                ),
                "right_as": operand["right_as"],
                "right_key": operand["right_key"],
                "where": child(operand["where"], location + ".where"),
            }
        )
    elif operation == "participant_query":
        operand = _freeze_tree(
            {
                "collection": child(operand["collection"], location + ".collection"),
                "as": operand["as"],
                "key": operand["key"],
                "right_keys": tuple(
                    child(item, f"{location}.right_keys[{index}]")
                    for index, item in enumerate(operand["right_keys"])
                ),
                "predicates": tuple(
                    child(item, f"{location}.predicates[{index}]")
                    for index, item in enumerate(operand["predicates"])
                ),
            }
        )
    elif operation == "unique_by":
        operand = _freeze_tree(
            {
                "collection": child(operand["collection"], location + ".collection"),
                "as": operand["as"],
                "keys": tuple(
                    child(key, f"{location}.keys[{index}]")
                    for index, key in enumerate(operand["keys"])
                ),
            }
        )
    elif operation in {
        "clause",
        "die_roll",
        "if",
        "record",
        "copy",
        "replace_unique",
        "none_matching",
        "exists",
        "exactly_one",
        "count_matching",
        "collect_matching",
        "tuple_at",
        "let",
        "variant",
        "is_case",
        "update_matching",
        "insert_missing",
    }:
        declaration = dict(_object(operand, "value operation operands"))
        expression_fields = {
            "clause": ("test",),
            "die_roll": ("seed", "sides"),
            "if": ("when", "then", "else"),
            "record": (),
            "copy": ("from",),
            "replace_unique": ("collection", "old", "new"),
            "none_matching": ("collection", "where"),
            "exists": ("collection", "where"),
            "exactly_one": ("collection", "where"),
            "count_matching": ("collection", "where"),
            "collect_matching": ("collection", "where", "value"),
            "tuple_at": ("collection", "index"),
            "let": ("value", "in"),
            "variant": ("value",),
            "is_case": ("value",),
            "update_matching": ("collection", "matching"),
            "insert_missing": ("collection", "candidates"),
        }[operation]
        for name in expression_fields:
            if name in declaration:
                declaration[name] = child(declaration[name], f"{location}.{name}")
        fields_name = {
            "record": "fields",
            "variant": "fields",
            "copy": "changes",
            "update_matching": "set",
        }.get(operation)
        if fields_name in declaration:
            values = _object(declaration[fields_name], "value record fields")
            declaration[fields_name] = {
                name: child(item, f"{location}.{fields_name}.{name}")
                for name, item in values.items()
            }
        operand = _freeze_tree(declaration)
    else:
        operand = _freeze_tree(operand)
    return _ExpressionDraft(
        operation,
        operand,
        path,
        source_context.trace((locations or {}).get(path, path))
        if source_context is not None
        else (),
    )


def _compile_expression(
    node: object,
    env: dict[str, object],
    ports: C0ValuePorts,
    nonnull: set[str],
    *,
    occurrence: bool = False,
    origin: str = "expression",
    source_paths: Mapping[str, str] | None = None,
) -> C0Expression:
    if ports.construction and occurrence:
        raise C0LawError("opening construction cannot borrow occurrence effect permission")
    locations = dict(source_paths or {})
    draft = _prepare_expression(
        node,
        origin,
        definitions=ports.pure_definitions,
        locations=locations,
        source_context=ports.source_context,
    )
    annotations: dict[int, object] = {}

    def check(current, local_env, local_ports, proofs, *, occurrence=False, depth=0):
        if type(current) is not _ExpressionDraft:
            raise C0LawError("type checking needs a prepared expression")
        inferred = _infer_expr_type(
            current,
            local_env,
            local_ports,
            proofs,
            occurrence=occurrence,
            depth=depth,
            _check=check,
        )
        annotations[id(current)] = inferred
        return inferred

    check(draft, env, ports, nonnull, occurrence=occurrence)

    def finish(value):
        if type(value) is _ExpressionDraft:
            return C0Expression(
                value.operation,
                finish(value.operand),
                closed_value_type(annotations[id(value)]),
                "construction" if ports.construction else "effect" if occurrence else "admission",
                locations.get(value.origin, value.origin),
                value.provenance,
            )
        if isinstance(value, Mapping):
            return MappingProxyType({key: finish(item) for key, item in value.items()})
        if type(value) is tuple:
            return tuple(finish(item) for item in value)
        return value

    return finish(draft)


def _expr_type(
    node: object,
    env: dict[str, object],
    ports: C0ValuePorts,
    nonnull: set[str],
    *,
    occurrence: bool = False,
) -> object:
    """Compile-time type query; runtime uses the checked node annotation."""
    return _compile_expression(node, env, ports, nonnull, occurrence=occurrence).result_type


def _infer_expr_type(
    node: object,
    env: dict[str, object],
    ports: C0ValuePorts,
    nonnull: set[str],
    *,
    occurrence: bool = False,
    depth: int = 0,
    _check: Callable[..., object],
) -> object:
    if depth > 64:
        raise C0LawError("value expression is too deep")
    row = _object(node, "value expression")
    if set(row) == {"call"}:
        declaration = row["call"]
        definition = declaration["definition"]
        if definition.stage == "effect" and not occurrence:
            raise C0LawError("effect pure call is unavailable before admission")
        local_env = {}
        for name, annotation in definition.parameters:
            argument = declaration["args"][name]
            actual = _check(argument, env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
            if not _assignable(actual, annotation):
                raise C0LawError("pure argument has the wrong nominal type")
            local_env[name] = _LocalType(
                annotation, argument, dict(env), ports, frozenset(nonnull), occurrence
            )
        actual = _check(
            declaration["body"],
            local_env,
            ports,
            set(),
            occurrence=definition.stage == "effect",
            depth=depth + 1,
        )
        if not _assignable(actual, definition.result):
            raise C0LawError("pure body has the wrong result type")
        return definition.result
    if set(row) == {"let"}:
        declaration = _object(row["let"], "local expression")
        _exact(declaration, {"name", "value", "in"}, "local expression")
        name = declaration["name"]
        if (
            type(name) is not str
            or not name.isascii()
            or not name.isidentifier()
            or name.startswith("_")
            or name == "occurrence"
            or name in env
        ):
            raise C0LawError("local expression name repeats or shadows a root")
        annotation = _check(
            declaration["value"],
            env,
            ports,
            nonnull,
            occurrence=occurrence,
            depth=depth + 1,
        )
        return _check(
            declaration["in"],
            {
                **env,
                name: _LocalType(
                    annotation,
                    declaration["value"],
                    dict(env),
                    ports,
                    frozenset(nonnull),
                    occurrence,
                ),
            },
            ports,
            nonnull,
            occurrence=occurrence,
            depth=depth + 1,
        )
    if set(row) == {"clause"}:
        clause = _object(row["clause"], "named clause")
        _exact(clause, {"name", "test"}, "named clause")
        name = clause["name"]
        if (
            type(name) is not str
            or not name.isascii()
            or not name.isidentifier()
            or name.startswith("_")
        ):
            raise C0LawError("clause name must be a public ASCII identifier")
        if (
            _check(clause["test"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
            is not bool
        ):
            raise C0LawError("named clause test must be boolean")
        return bool
    if set(row) == {"const"}:
        value = row["const"]
        if type(value) in (bool, str, type(None)):
            return type(value)
        if type(value) is int and 0 <= value <= _MAX_INT:
            return int
    if set(row) == {"ref"} and type(row["ref"]) is str:
        if row["ref"] == "occurrence" and not occurrence:
            raise C0LawError("occurrence is unavailable before admission")
        return _ref_type(row["ref"], env, ports, nonnull)
    if set(row) == {"empty_like"}:
        path = row["empty_like"]
        if (
            type(path) is not str
            or path.split(".")[0] not in ports.roots
            or type(env.get(path.split(".")[0])) is _LocalType
        ):
            raise C0LawError("empty collection needs a declared input path")
        # Query the declared shape; nullable parents are never evaluated here.
        annotation = _ref_type(path, env, ports, nonnull, declaring_port=True)
        _tuple_item(annotation)
        return annotation
    if set(row) == {"die_roll"}:
        if not occurrence and not ports.construction:
            raise C0LawError("die draw is unavailable before Action admission")
        declaration = _object(row["die_roll"], "die draw")
        _exact(declaration, {"seed", "sides"}, "die draw")
        if any(
            _check(declaration[name], env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
            is not int
            for name in ("seed", "sides")
        ):
            raise C0LawError("die draw needs integer seed and sides")
        return int
    if set(row) == {"die_next_seed"}:
        if not occurrence and not ports.construction:
            raise C0LawError("die state advance is unavailable before Action admission")
        if (
            _check(
                row["die_next_seed"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
            )
            is not int
        ):
            raise C0LawError("die state advance needs an integer seed")
        return int
    for op in ("eq", "le", "lt", "add", "sub", "mul", "ceil_div", "append"):
        if set(row) == {op} and type(row[op]) in (list, tuple) and len(row[op]) == 2:
            left, right = (
                _check(item, env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
                for item in row[op]
            )
            if op == "eq":
                # Whole-value equality would observe fields hidden from admission.
                scalar = {
                    str,
                    int,
                    bool,
                    type(None),
                    K0OccurrenceRef,
                    _K0IndividualRef,
                    _K0ActorRef,
                }
                if not set((*_variants(left), *_variants(right))) <= scalar:
                    raise C0LawError("value equality requires scalar or identity references")
                if set(_variants(left)) & set(_variants(right)):
                    return bool
            if op in ("le", "lt", "add", "sub", "mul", "ceil_div") and left is right is int:
                return int if op in ("add", "sub", "mul", "ceil_div") else bool
            if (
                op == "append"
                and get_origin(left) is tuple
                and _assignable(right, _tuple_item(left))
            ):
                return left
    if set(row) in ({"is_none"}, {"not_none"}, {"not"}):
        op = next(iter(row))
        item_type = _check(row[op], env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
        if op != "not" or item_type is bool:
            return bool
    if set(row) in ({"all"}, {"any"}) and type(next(iter(row.values()))) in (list, tuple):
        op = next(iter(row))
        items = row[op]
        if not items:
            raise C0LawError("boolean collection cannot be empty")
        current_nonnull = set(nonnull)
        for item in items:
            if (
                _check(item, env, ports, current_nonnull, occurrence=occurrence, depth=depth + 1)
                is not bool
            ):
                raise C0LawError("boolean collection has a non-boolean member")
            if op == "all":
                current_nonnull.update(_guard_proofs(item, env, ports, current_nonnull))
        return bool
    if set(row) == {"if"}:
        declaration = _object(row["if"], "conditional value")
        _exact(declaration, {"when", "then", "else"}, "conditional value")
        if (
            _check(declaration["when"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
            is not bool
        ):
            raise C0LawError("conditional value guard is not boolean")
        then_type = _check(
            declaration["then"],
            env,
            ports,
            nonnull | _guard_proofs(declaration["when"], env, ports, nonnull),
            occurrence=occurrence,
            depth=depth + 1,
        )
        else_type = _check(
            declaration["else"],
            env,
            ports,
            nonnull,
            occurrence=occurrence,
            depth=depth + 1,
        )
        return then_type if then_type == else_type else then_type | else_type
    if set(row) == {"variant"}:
        declaration = _object(row["variant"], "variant constructor")
        _exact(declaration, {"type", "case", "value", "fields"}, "variant constructor")
        carrier = (
            ports.record_types.get(declaration["type"])
            if type(declaration["type"]) is str
            else None
        )
        cases = variant_cases(carrier)
        if type(declaration["case"]) is not str or declaration["case"] not in cases:
            raise C0LawError("variant constructor names an undeclared type or case")
        actual = _check(
            declaration["value"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        if not _assignable(actual, cases[declaration["case"]]):
            raise C0LawError("variant payload has the wrong nominal type")
        values = _object(declaration["fields"], "variant common fields")
        _exact(values, set(variant_common_fields(carrier)), "variant common fields")
        declared = _record_field_types(carrier)
        for name, item in values.items():
            if not _assignable(
                _check(item, env, ports, nonnull, occurrence=occurrence, depth=depth + 1),
                declared[name],
            ):
                raise C0LawError("variant common field has the wrong type")
        return carrier
    if set(row) in ({"match"}, {"is_case"}):
        operation = next(iter(row))
        declaration = _object(row[operation], "variant selection")
        _exact(
            declaration, {"value", "cases" if operation == "match" else "case"}, "variant selection"
        )
        carrier = _check(
            declaration["value"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        _check_discriminator(carrier, declaration["value"], env, ports, nonnull, occurrence)
        cases = variant_cases(carrier)
        if operation == "is_case":
            if type(declaration["case"]) is not str or declaration["case"] not in cases:
                raise C0LawError("is_case names an undeclared case")
            return bool
        arms = _object(declaration["cases"], "match cases")
        _exact(arms, set(cases), "exhaustive match cases")
        result = None
        for case, arm in arms.items():
            _exact(arm, {"as", "then"}, "match arm")
            name = _binding_name({"name": arm["as"]}, env)
            local = _case_local(
                carrier, declaration["value"], case, env, ports, nonnull, occurrence
            )
            actual = _check(
                arm["then"],
                {**env, name: local},
                ports,
                set(nonnull),
                occurrence=occurrence,
                depth=depth + 1,
            )
            result = actual if result is None or result == actual else result | actual
        return result
    if set(row) == {"record"}:
        declaration = _object(row["record"], "record constructor")
        _exact(declaration, {"type", "fields"}, "record constructor")
        carrier = (
            ports.record_types.get(declaration["type"])
            if type(declaration["type"]) is str
            else None
        )
        if carrier is None:
            raise C0LawError("record constructor is not declared by the library")
        if variant_cases(carrier):
            raise C0LawError("nominal variant requires a variant constructor")
        declared = _record_field_types(carrier)
        values = _object(declaration["fields"], "record fields")
        _exact(values, set(declared), "record fields")
        for name, item in values.items():
            actual = _check(item, env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
            if not _assignable(actual, declared[name]):
                raise C0LawError("record constructor field has the wrong type")
        return carrier
    if set(row) == {"copy"}:
        declaration = _object(row["copy"], "record copy")
        _exact(declaration, {"from", "changes"}, "record copy")
        carrier = _check(
            declaration["from"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        changes = _object(declaration["changes"], "record changes")
        if (
            not _frozen_record(carrier)
            or variant_cases(carrier)
            or not changes
            or not set(changes) <= ports.writable_fields.get(carrier, frozenset())
        ):
            raise C0LawError("record copy writes an undeclared field")
        declared = _record_field_types(carrier)
        for name, item in changes.items():
            actual = _check(item, env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
            if not _assignable(actual, declared[name]):
                raise C0LawError("record copy field has the wrong type")
        return carrier
    if set(row) == {"participant_collect"}:
        declaration = row["participant_collect"]
        item_type = None
        for predicate, value in zip(declaration["predicates"], declaration["values"], strict=True):
            if (
                _check(predicate, env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
                is not bool
            ):
                raise C0LawError("participant collection predicate must be boolean")
            actual = _check(
                value,
                env,
                ports,
                nonnull | _guard_proofs(predicate, env, ports, nonnull),
                occurrence=occurrence,
                depth=depth + 1,
            )
            if item_type is not None and actual != item_type:
                raise C0LawError("participant collection values need one exact nominal type")
            item_type = actual
        if item_type is None:
            raise C0LawError("participant collection needs a nonempty declared group")
        return tuple[item_type, ...]
    if set(row) == {"insert_missing"}:
        declaration = _object(row["insert_missing"], "keyed insertion")
        _exact(declaration, {"collection", "candidates", "key"}, "keyed insertion")
        collection = _check(
            declaration["collection"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        candidates = _check(
            declaration["candidates"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        carrier, key = _tuple_item(collection), declaration["key"]
        if (
            collection != candidates
            or not _frozen_record(carrier)
            or variant_cases(carrier)
            or type(key) is not str
            or not key.isascii()
            or not key.isidentifier()
            or key.startswith("_")
        ):
            raise C0LawError("keyed insertion needs matching nominal rows and a public key")
        key_type = _field_type(carrier, key, ports)
        if key_type not in (str, int, K0OccurrenceRef, _K0IndividualRef, _K0ActorRef):
            raise C0LawError("keyed insertion needs a non-null scalar/reference key")
        return collection
    if set(row) == {"update_matching"}:
        declaration = _object(row["update_matching"], "keyed update")
        _exact(declaration, {"collection", "matching", "key", "as", "set"}, "keyed update")
        collection = _check(
            declaration["collection"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        matching = _check(
            declaration["matching"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        carrier = _tuple_item(collection)
        alias = declaration["as"]
        _binding_name({"name": alias}, env)
        local_env = {**env, alias: carrier}
        key = declaration["key"]
        if (
            type(key) is not str
            or not key.isascii()
            or not key.isidentifier()
            or key.startswith("_")
        ):
            raise C0LawError("keyed update needs a public field key")
        key_type = _ref_type(alias + "." + key, local_env, ports, nonnull)
        if key_type not in (str, int, K0OccurrenceRef, _K0IndividualRef, _K0ActorRef):
            raise C0LawError("keyed update needs a non-null scalar/reference key")
        changes = _object(declaration["set"], "keyed update fields")
        declared = _record_field_types(carrier) if _frozen_record(carrier) else {}
        permitted = (
            frozenset(declared)
            if carrier in ports.record_types.values()
            else ports.writable_fields.get(carrier, frozenset())
        )
        if (
            matching != collection
            or not _frozen_record(carrier)
            or variant_cases(carrier)
            or not changes
            or key in changes
            or not set(changes) <= permitted
        ):
            raise C0LawError("keyed update has foreign rows or unauthorized fields")
        for name, value in changes.items():
            actual = _check(
                value, local_env, ports, nonnull, occurrence=occurrence, depth=depth + 1
            )
            if not _assignable(actual, declared[name]):
                raise C0LawError("keyed update field has the wrong type")
        return collection
    if set(row) == {"replace_unique"}:
        declaration = _object(row["replace_unique"], "unique replacement")
        _exact(declaration, {"collection", "old", "new", "key"}, "unique replacement")
        collection = declaration["collection"]
        if not isinstance(collection, Mapping) or set(collection) != {"ref"}:
            raise C0LawError("unique replacement needs an exact collection port")
        path = collection["ref"]
        if type(path) is not str or ports.collection_keys.get(path) != declaration["key"]:
            raise C0LawError("unique replacement uses a foreign key")
        collection_type = _check(
            collection, env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        item_type = _tuple_item(collection_type)
        for name in ("old", "new"):
            actual = _check(
                declaration[name], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
            )
            if actual != item_type:
                raise C0LawError("unique replacement changed element type")
        return collection_type
    if set(row) == {"tuple_at"}:
        declaration = _object(row["tuple_at"], "tuple selection")
        _exact(declaration, {"collection", "index"}, "tuple selection")
        collection = _check(
            declaration["collection"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        if (
            _check(
                declaration["index"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
            )
            is not int
        ):
            raise C0LawError("tuple selection index must have exact integer type")
        return _tuple_item(collection)
    if set(row) == {"collection_query"}:
        declaration = row["collection_query"]
        collection = _check(
            declaration["collection"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        right = _check(
            declaration["right_collection"],
            env,
            ports,
            nonnull,
            occurrence=occurrence,
            depth=depth + 1,
        )
        left_alias, right_alias = declaration["as"], declaration["right_as"]
        _binding_name({"name": left_alias}, env)
        local_env = {
            **env,
            left_alias: _LocalType(
                _tuple_item(collection),
                {"tuple_at": {"collection": declaration["collection"]}},
                dict(env),
                ports,
                frozenset(nonnull),
                occurrence,
            ),
        }
        _binding_name({"name": right_alias}, local_env)
        local_env[right_alias] = _LocalType(
            _tuple_item(right),
            {"tuple_at": {"collection": declaration["right_collection"]}},
            dict(env),
            ports,
            frozenset(nonnull),
            occurrence,
        )
        left_key = _ref_type(left_alias + "." + declaration["key"], local_env, ports, nonnull)
        right_key = _ref_type(
            right_alias + "." + declaration["right_key"], local_env, ports, nonnull
        )
        if left_key not in (str, int, K0OccurrenceRef, _K0IndividualRef, _K0ActorRef):
            raise C0LawError("query key needs a non-null exact scalar/reference type")
        if left_key != right_key:
            raise C0LawError("query join keys have different nominal types")
        if (
            _check(
                declaration["where"],
                local_env,
                ports,
                nonnull,
                occurrence=occurrence,
                depth=depth + 1,
            )
            is not bool
        ):
            raise C0LawError("query predicate must be boolean")
        return collection
    if set(row) == {"participant_query"}:
        declaration = row["participant_query"]
        collection = _check(
            declaration["collection"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        item = _tuple_item(collection)
        alias = declaration["as"]
        _binding_name({"name": alias}, env)
        local_env = {**env, alias: item}
        key_type = _ref_type(alias + "." + declaration["key"], local_env, ports, nonnull)
        if key_type not in (str, int, K0OccurrenceRef, _K0IndividualRef, _K0ActorRef):
            raise C0LawError("query key needs a non-null exact scalar/reference type")
        for key, predicate in zip(
            declaration["right_keys"], declaration["predicates"], strict=True
        ):
            if _check(key, env, ports, nonnull, occurrence=occurrence, depth=depth + 1) != key_type:
                raise C0LawError("query join keys have different nominal types")
            if (
                _check(predicate, local_env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
                is not bool
            ):
                raise C0LawError("query predicate must be boolean")
        return collection
    if set(row) == {"unique_by"}:
        declaration = _object(row["unique_by"], "unique key predicate")
        _exact(declaration, {"collection", "as", "keys"}, "unique key predicate")
        name = _binding_name({"name": declaration["as"]}, env)
        collection = _check(
            declaration["collection"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        item_env = {**env, name: _tuple_item(collection)}
        keys = declaration["keys"]
        if type(keys) not in (list, tuple) or not 1 <= len(keys) <= 8:
            raise C0LawError("unique_by needs one to eight key expressions")
        for key in keys:
            key_type = _check(key, item_env, ports, nonnull, occurrence=occurrence, depth=depth + 1)
            if key_type not in (bool, int, str, K0OccurrenceRef, _K0IndividualRef, _K0ActorRef):
                raise C0LawError("unique_by key needs a non-null exact scalar/reference type")
        return bool
    if set(row) in (
        {"none_matching"},
        {"exists"},
        {"exactly_one"},
        {"count_matching"},
        {"collect_matching"},
    ):
        op = next(iter(row))
        declaration = _object(row[op], "bounded quantifier")
        expected = {"collection", "as", "where"}
        if op == "collect_matching":
            expected.add("value")
        _exact(declaration, expected, "bounded quantifier")
        name = declaration["as"]
        if type(name) is not str or not name or name in env:
            raise C0LawError("bounded quantifier has a shadowing alias")
        if op == "collect_matching":
            _binding_name({"name": name}, env)
        collection = _check(
            declaration["collection"], env, ports, nonnull, occurrence=occurrence, depth=depth + 1
        )
        item_env = {**env, name: _tuple_item(collection)}
        if (
            _check(
                declaration["where"],
                item_env,
                ports,
                nonnull,
                occurrence=occurrence,
                depth=depth + 1,
            )
            is not bool
        ):
            raise C0LawError("bounded quantifier predicate is not boolean")
        if op == "collect_matching":
            item_proofs = nonnull | _guard_proofs(declaration["where"], item_env, ports, nonnull)
            item = _check(
                declaration["value"],
                item_env,
                ports,
                item_proofs,
                occurrence=occurrence,
                depth=depth + 1,
            )
            _check_materialization(declaration["value"], item, item_env, ports, item_proofs)
            return tuple[item, ...]
        return bool if op in {"none_matching", "exists", "exactly_one"} else int
    raise C0LawError("value expression has an unknown or mistyped operation")


def _nonnull_proof(
    node: object, env: dict[str, object], ports: C0ValuePorts, nonnull: set[str]
) -> set[str]:
    if isinstance(node, Mapping) and set(node) == {"clause"}:
        return _nonnull_proof(node["clause"]["test"], env, ports, nonnull)
    if not isinstance(node, Mapping) or set(node) != {"not_none"}:
        return set()
    operand = node["not_none"]
    if not isinstance(operand, Mapping) or set(operand) != {"ref"}:
        return set()
    ref = operand["ref"]
    if type(ref) is not str:
        return set()
    return {ref} if _nonnull(_ref_type(ref, env, ports, nonnull)) is not None else set()


def _guard_proofs(
    node: object,
    env: dict[str, object],
    ports: C0ValuePorts,
    nonnull: set[str] | None = None,
) -> set[str]:
    incoming = set() if nonnull is None else set(nonnull)
    if isinstance(node, Mapping) and set(node) == {"clause"}:
        return _guard_proofs(node["clause"]["test"], env, ports, incoming)
    if isinstance(node, Mapping) and set(node) == {"all"}:
        for part in node["all"]:
            incoming.update(_guard_proofs(part, env, ports, incoming))
        return incoming - (nonnull or set())
    if isinstance(node, Mapping) and set(node) == {"is_case"}:
        declaration = node["is_case"]
        if set(declaration["value"]) == {"ref"}:
            path = declaration["value"]["ref"]
            return {f"{path}.{declaration['case']}"}
    return _nonnull_proof(node, env, ports, incoming)


def _binding_name(binding: Mapping[str, Any], declared: Container[str]) -> str:
    name = binding.get("name")
    if (
        type(name) is not str
        or not name.isascii()
        or not name.isidentifier()
        or name.startswith("_")
        or name in declared
        or name == "occurrence"
    ):
        raise C0LawError("value binding repeats or shadows a root")
    return name


def _check_binding(
    row: object,
    env: dict[str, object],
    ports: C0ValuePorts,
    *,
    nonnull: set[str] | None = None,
    occurrence: bool = False,
) -> tuple[str, object]:
    binding = _object(row, "value binding")
    name = _binding_name(binding, env)
    if set(binding) == {"name", "const"}:
        return name, _expr_type({"const": binding["const"]}, env, ports, set())
    if "let" in binding:
        _exact(binding, {"name", "let", "stage"}, "local computation")
        if binding["stage"] not in ("admission", "effect"):
            raise C0LawError("local computation stage is unknown")
        if (binding["stage"] == "effect") != occurrence:
            raise C0LawError("local computation is checked in the wrong stage")
        return name, _expr_type(
            binding["let"],
            env,
            ports,
            nonnull or set(),
            occurrence=occurrence,
        )
    if set(binding) == {"name", "collection", "as", "where", "required"}:
        path, item_name = binding["collection"], binding["as"]
        if (
            type(path) is not str
            or path not in ports.readable_paths
            or type(item_name) is not str
            or not item_name.isidentifier()
            or item_name.startswith("_")
        ):
            raise C0LawError("predicate lookup needs a declared collection and item name")
        if item_name in env or item_name in (name, "occurrence"):
            raise C0LawError("predicate lookup item shadows a root or binding")
        if type(binding["required"]) is not bool:
            raise C0LawError("predicate lookup required flag must be boolean")
        item_type = _tuple_item(_ref_type(path, env, ports, set()))
        if path in ports.collection_keys:
            _field_type(item_type, ports.collection_keys[path], ports)
        if _expr_type(binding["where"], {**env, item_name: item_type}, ports, set()) is not bool:
            raise C0LawError("predicate lookup condition must be boolean")
        return name, item_type if binding["required"] else item_type | None
    _exact(binding, {"name", "collection", "key", "value", "required"}, "value binding")
    path, key = binding["collection"], binding["key"]
    if type(path) is not str or ports.collection_keys.get(path) != key:
        raise C0LawError("value binding has no declared collection key")
    if type(binding["required"]) is not bool:
        raise C0LawError("value binding required flag must be boolean")
    item_type = _tuple_item(_ref_type(path, env, ports, set()))
    key_type = _field_type(item_type, key, ports)
    actual = _expr_type(binding["value"], env, ports, set())
    if not (
        _assignable(actual, key_type) or (not binding["required"] and _nonnull(actual) == key_type)
    ):
        raise C0LawError("value binding key has the wrong type")
    return name, item_type if binding["required"] else item_type | None


def _value_matches(value: object, annotation: object) -> bool:
    if isinstance(annotation, type):
        return type(value) is annotation
    variants = _variants(annotation)
    if len(variants) > 1:
        return any(_value_matches(value, item) for item in variants)
    if get_origin(annotation) is tuple:
        try:
            item = _tuple_item(annotation)
        except C0LawError:
            args = get_args(annotation)
            return (
                type(value) is tuple
                and len(value) == len(args)
                and all(
                    _value_matches(actual, expected)
                    for actual, expected in zip(value, args, strict=True)
                )
            )
        return type(value) is tuple and all(_value_matches(part, item) for part in value)
    return isinstance(annotation, type) and type(value) is annotation


def _require_unique(
    collection: tuple[object, ...],
    key: str,
    item_type: object,
    ports: C0ValuePorts,
) -> None:
    seen: set[object] = set()
    for item in collection:
        member_key = _read_ref(f"item.{key}", {"item": item}, {"item": item_type}, ports)
        try:
            if member_key in seen:
                raise C0ValueStateError("declared collection key is not unique")
            seen.add(member_key)
        except TypeError as error:
            raise C0ValueStateError("declared collection key is not hashable") from error


def _collection_key(node: C0Expression, ports: C0ValuePorts) -> str | None:
    if node.operation == "ref":
        return ports.collection_keys.get(node.operand)
    if node.operation == "append":
        return _collection_key(node.operand[0], ports)
    if node.operation == "replace_unique":
        return ports.collection_keys.get(node.operand["collection"]["ref"])
    return None


def _read_ref(
    ref: str,
    context: dict[str, object],
    env: dict[str, object],
    ports: C0ValuePorts,
) -> object:
    return _read_reference(tuple(ref.split(".")), context, env, ports)


def _read_reference(
    parts: tuple[str, ...],
    context: dict[str, object],
    env: dict[str, object],
    ports: C0ValuePorts,
) -> object:
    if parts == ("occurrence",):
        return context["occurrence"]
    value = context[parts[0]]
    if type(value) is _LazyValue:
        value = value.resolve()
    annotation = env[parts[0]]
    for part in parts[1:]:
        if value is None:
            raise C0ValueStateError("nullable value was used without its guard")
        if not isinstance(annotation, type):
            annotation = _nonnull(annotation) or annotation
        frozen_record = _frozen_record(annotation)
        if frozen_record:
            value = getattr(value, part)
        else:
            value = value[ports.tuple_fields[annotation][part]]
        annotation = _field_type(annotation, part, ports, frozen_record=frozen_record)
    return value


def _eval_reference(node, context, env, ports):
    value = _read_reference(node.reference_path, context, env, ports)
    key = (
        ports.collection_keys.get(node.operand)
        if node.operation == "ref"
        else _collection_key(node, ports)
    )
    if key is not None:
        item_type = _tuple_item(node.result_type)
        _require_unique(value, key, item_type, ports)
    return value


def _match_context(declaration, context, env, ports):
    value = _eval(declaration["value"], context, env, ports)
    carrier = declaration["value"].result_type
    if type(value) is not carrier:
        raise C0ValueStateError("match input has a foreign nominal type")
    # An invariant may itself match this value; do not recursively re-enter it.
    validate_variant(value)
    case = value.case
    arm = declaration["cases"][case]
    annotation = variant_cases(carrier)[case]
    payload = None if annotation is type(None) else getattr(value, case)
    return {**context, arm["as"]: payload}, {**env, arm["as"]: annotation}, arm, case


def _call_context(declaration, context, env, ports):
    local_env = dict(declaration["definition"].parameters)
    local_context = {
        name: _LazyValue(declaration["args"][name], dict(context), dict(env), ports)
        for name in local_env
    }
    # The marker gates effect evaluation; closed bodies cannot capture it.
    if "occurrence" in context:
        local_context["occurrence"] = context["occurrence"]
    if context.get("_construction") is _CONSTRUCTION_CONTEXT:
        local_context["_construction"] = _CONSTRUCTION_CONTEXT
    return local_context, local_env


def _eval(
    node: C0Expression,
    context: dict[str, object],
    env: dict[str, object],
    ports: C0ValuePorts,
) -> object:
    if type(node) is not C0Expression:
        raise C0ValueStateError("evaluation requires a checked expression")
    if node.stage == "effect" and "occurrence" not in context:
        raise C0ValueStateError("effect expression is unavailable before admission")
    if node.stage == "construction" and (
        not ports.construction or context.get("_construction") is not _CONSTRUCTION_CONTEXT
    ):
        raise C0ValueStateError("construction expression needs a checked opening context")
    operation = node.operation
    operand = node.operand
    if operation == "call":
        declaration = operand
        local_context, local_env = _call_context(declaration, context, env, ports)
        return _eval(declaration["body"], local_context, local_env, ports)
    if operation == "let":
        declaration = operand
        local = _LazyValue(declaration["value"], dict(context), dict(env), ports)
        return _eval(
            declaration["in"],
            {**context, declaration["name"]: local},
            {**env, declaration["name"]: declaration["value"].result_type},
            ports,
        )
    if operation == "clause":
        return _eval(operand["test"], context, env, ports)
    if operation == "const":
        return operand
    if operation == "empty_like":
        return ()
    if operation == "ref":
        return _eval_reference(node, context, env, ports)
    if operation == "die_roll":
        declaration = operand
        try:
            seed = _eval(declaration["seed"], context, env, ports)
            sides = _eval(declaration["sides"], context, env, ports)
            result = _die_roll(seed, sides)
            if node.stage == "construction":
                context["_construction_draw"] = (seed, sides, result)
            return result
        except ValueError as error:
            raise C0ValueRangeError("die draw has an invalid current range") from error
    if operation == "die_next_seed":
        try:
            return _die_next_seed(_eval(operand, context, env, ports))
        except ValueError as error:
            raise C0ValueRangeError("die state advance has an invalid current seed") from error
    if operation == "eq":
        left = _eval(operand[0], context, env, ports)
        right = _eval(operand[1], context, env, ports)
        return type(left) is type(right) and left == right
    if operation == "le":
        return _eval(operand[0], context, env, ports) <= _eval(operand[1], context, env, ports)
    if operation == "lt":
        return _eval(operand[0], context, env, ports) < _eval(operand[1], context, env, ports)
    if operation == "add":
        value = _eval(operand[0], context, env, ports) + _eval(operand[1], context, env, ports)
        if type(value) is not int or not 0 <= value <= _MAX_INT:
            raise C0ValueRangeError("bounded integer addition exceeded its domain")
        return value
    if operation == "sub":
        value = _eval(operand[0], context, env, ports) - _eval(operand[1], context, env, ports)
        if type(value) is not int or not 0 <= value <= _MAX_INT:
            raise C0ValueRangeError("bounded integer subtraction exceeded its domain")
        return value
    if operation == "mul":
        value = _eval(operand[0], context, env, ports) * _eval(operand[1], context, env, ports)
        if type(value) is not int or not 0 <= value <= _MAX_INT:
            raise C0ValueRangeError("bounded integer multiplication exceeded its domain")
        return value
    if operation == "ceil_div":
        numerator = _eval(operand[0], context, env, ports)
        denominator = _eval(operand[1], context, env, ports)
        if (
            type(numerator) is not int
            or not 0 <= numerator <= _MAX_INT
            or type(denominator) is not int
            or denominator <= 0
        ):
            raise C0ValueRangeError("bounded ceiling division has an invalid current range")
        return (numerator + denominator - 1) // denominator
    if operation == "is_none":
        return _eval(operand, context, env, ports) is None
    if operation == "not_none":
        return _eval(operand, context, env, ports) is not None
    if operation == "not":
        return not _eval(operand, context, env, ports)
    if operation == "all":
        for part in operand:
            if _eval(part, context, env, ports) is not True:
                return False
        return True
    if operation == "any":
        for part in operand:
            if _eval(part, context, env, ports) is True:
                return True
        return False
    if operation == "if":
        branch = operand
        selected = (
            branch["then"] if _eval(branch["when"], context, env, ports) is True else branch["else"]
        )
        return _eval(selected, context, env, ports)
    if operation == "variant":
        declaration = operand
        return construct_variant(
            ports.record_types[declaration["type"]],
            declaration["case"],
            _eval(declaration["value"], context, env, ports),
            {
                name: _eval(item, context, env, ports)
                for name, item in declaration["fields"].items()
            },
        )
    if operation == "is_case":
        declaration = operand
        value = _eval(declaration["value"], context, env, ports)
        if type(value) is not declaration["value"].result_type:
            raise C0ValueStateError("is_case input has a foreign nominal type")
        validate_variant(value)
        return value.case == declaration["case"]
    if operation == "match":
        local_context, local_env, arm, _ = _match_context(operand, context, env, ports)
        return _eval(arm["then"], local_context, local_env, ports)
    if operation == "append":
        collection = _eval(operand[0], context, env, ports)
        result = collection + (_eval(operand[1], context, env, ports),)
        key = _collection_key(node, ports)
        if key is not None:
            item_type = _tuple_item(operand[0].result_type)
            _require_unique(result, key, item_type, ports)
        return result
    if operation == "record":
        declaration = operand
        carrier = ports.record_types[declaration["type"]]
        return carrier(
            **{
                name: _eval(item, context, env, ports)
                for name, item in declaration["fields"].items()
            }
        )
    if operation == "copy":
        declaration = operand
        original = _eval(declaration["from"], context, env, ports)
        return replace(
            original,
            **{
                name: _eval(item, context, env, ports)
                for name, item in declaration["changes"].items()
            },
        )
    if operation == "participant_collect":
        return tuple(
            _eval(value, context, env, ports)
            for predicate, value in zip(operand["predicates"], operand["values"], strict=True)
            if _eval(predicate, context, env, ports) is True
        )
    if operation == "insert_missing":
        collection = _eval(operand["collection"], context, env, ports)
        candidates = _eval(operand["candidates"], context, env, ports)
        kind = operand["collection"].result_type
        if not _value_matches(collection, kind) or not _value_matches(candidates, kind):
            raise C0ValueStateError("keyed insertion needs exact nominal tuples")
        carrier, key = _tuple_item(kind), operand["key"]
        _require_unique(collection, key, carrier, ports)
        _require_unique(candidates, key, carrier, ports)
        key_type = _field_type(carrier, key, ports)

        def key_of(item):
            value = _read_ref("item." + key, {"item": item}, {"item": carrier}, ports)
            if not _value_matches(value, key_type):
                raise C0ValueStateError("keyed insertion has a foreign key type")
            return value

        existing = {key_of(item) for item in collection}
        additions = tuple(item for item in candidates if key_of(item) not in existing)
        return collection + additions
    if operation == "update_matching":
        collection = _eval(operand["collection"], context, env, ports)
        matching = _eval(operand["matching"], context, env, ports)
        collection_type = operand["collection"].result_type
        if not _value_matches(collection, collection_type) or not _value_matches(
            matching, collection_type
        ):
            raise C0ValueStateError("keyed update needs exact nominal tuples")
        carrier = _tuple_item(collection_type)
        key, alias = operand["key"], operand["as"]
        _require_unique(collection, key, carrier, ports)
        _require_unique(matching, key, carrier, ports)
        key_type = _field_type(carrier, key, ports)

        def key_of(item):
            value = _read_ref(alias + "." + key, {alias: item}, {alias: carrier}, ports)
            if not _value_matches(value, key_type):
                raise C0ValueStateError("keyed update has a foreign key type")
            return value

        originals = {key_of(item): item for item in collection}
        selected = {key_of(item): item for item in matching}
        if any(key not in originals or originals[key] != item for key, item in selected.items()):
            raise C0ValueStateError("keyed update matching rows are missing or stale")
        result = []
        local_env = {**env, alias: carrier}
        for item in collection:
            if key_of(item) in selected:
                local_context = {**context, alias: item}
                item = replace(
                    item,
                    **{
                        name: _eval(value, local_context, local_env, ports)
                        for name, value in operand["set"].items()
                    },
                )
            result.append(item)
        return tuple(result)
    if operation == "replace_unique":
        declaration = operand
        collection = _eval(declaration["collection"], context, env, ports)
        old = _eval(declaration["old"], context, env, ports)
        new = _eval(declaration["new"], context, env, ports)
        key = declaration["key"]
        item_type = _tuple_item(declaration["collection"].result_type)
        old_key = _read_ref(f"item.{key}", {"item": old}, {"item": item_type}, ports)
        new_key = _read_ref(f"item.{key}", {"item": new}, {"item": item_type}, ports)
        _require_unique(collection, key, item_type, ports)
        if old_key != new_key:
            raise C0ValueStateError("unique replacement changed member identity")
        matches = tuple(
            index
            for index, item in enumerate(collection)
            if _read_ref(f"item.{key}", {"item": item}, {"item": item_type}, ports) == old_key
        )
        if len(matches) != 1 or collection[matches[0]] != old:
            raise C0ValueStateError("unique replacement lost its current member")
        return tuple(new if index == matches[0] else item for index, item in enumerate(collection))
    if operation == "tuple_at":
        collection = _eval(operand["collection"], context, env, ports)
        index = _eval(operand["index"], context, env, ports)
        if type(collection) is not tuple or not _value_matches(
            collection, operand["collection"].result_type
        ):
            raise C0ValueStateError("tuple selection needs an exact nominal tuple")
        if type(index) is not int or not 0 <= index < len(collection):
            raise C0ValueStateError("tuple selection index is outside the current tuple")
        return collection[index]
    if operation == "collection_query":
        collection = _eval(operand["collection"], context, env, ports)
        right = _eval(operand["right_collection"], context, env, ports)
        left_type, right_type = (
            operand["collection"].result_type,
            operand["right_collection"].result_type,
        )
        if not _value_matches(collection, left_type) or not _value_matches(right, right_type):
            raise C0ValueStateError("query needs exact nominal tuples")
        left_item, right_item = _tuple_item(left_type), _tuple_item(right_type)
        _require_unique(collection, operand["key"], left_item, ports)
        _require_unique(right, operand["right_key"], right_item, ports)
        left_alias, right_alias = operand["as"], operand["right_as"]
        local_env = {**env, left_alias: left_item, right_alias: right_item}
        # Aliases are lexical record members, not caller root ports.
        key_type = _field_type(left_item, operand["key"], ports)

        def key_of(item, alias, field, item_type):
            key = _read_ref(alias + "." + field, {alias: item}, {alias: item_type}, ports)
            if not _value_matches(key, key_type):
                raise C0ValueStateError("query record key has a foreign nominal type")
            return key

        index = {
            key_of(item, right_alias, operand["right_key"], right_item): item for item in right
        }
        result = []
        for item in collection:
            key = key_of(item, left_alias, operand["key"], left_item)
            if (
                key in index
                and _eval(
                    operand["where"],
                    {**context, left_alias: item, right_alias: index[key]},
                    local_env,
                    ports,
                )
                is True
            ):
                result.append(item)
        return tuple(result)
    if operation == "participant_query":
        collection = _eval(operand["collection"], context, env, ports)
        if not _value_matches(collection, operand["collection"].result_type):
            raise C0ValueStateError("query needs an exact nominal tuple")
        item_type = _tuple_item(operand["collection"].result_type)
        _require_unique(collection, operand["key"], item_type, ports)
        keys = tuple(_eval(key, context, env, ports) for key in operand["right_keys"])
        key_type = operand["right_keys"][0].result_type
        if any(not _value_matches(key, key_type) for key in keys):
            raise C0ValueStateError("query participant key has a foreign nominal type")
        if len(set(keys)) != len(keys):
            raise C0ValueStateError("query participant key is not unique")
        predicates = dict(zip(keys, operand["predicates"], strict=True))
        alias = operand["as"]
        result = []
        for item in collection:
            key = _read_ref(alias + "." + operand["key"], {alias: item}, {alias: item_type}, ports)
            if not _value_matches(key, key_type):
                raise C0ValueStateError("query record key has a foreign nominal type")
            if (
                key in predicates
                and _eval(
                    predicates[key], {**context, alias: item}, {**env, alias: item_type}, ports
                )
                is True
            ):
                result.append(item)
        return tuple(result)
    if operation == "unique_by":
        collection = _eval(operand["collection"], context, env, ports)
        if type(collection) is not tuple or len(collection) > _MAX_INT:
            raise C0ValueStateError("unique_by needs an exact bounded tuple")
        name = operand["as"]
        item_env = {**env, name: _tuple_item(operand["collection"].result_type)}
        seen = set()
        for item in collection:
            if not _value_matches(item, item_env[name]):
                raise C0ValueStateError("unique_by met a foreign element type")
            local = {**context, name: item}
            key = tuple(_eval(part, local, item_env, ports) for part in operand["keys"])
            if any(
                not _value_matches(value, part.result_type)
                for value, part in zip(key, operand["keys"], strict=True)
            ):
                raise C0ValueStateError("unique_by met a foreign key type")
            if key in seen:
                return False
            seen.add(key)
        return True
    if operation in {
        "none_matching",
        "exists",
        "exactly_one",
        "count_matching",
        "collect_matching",
    }:
        op = operation
        declaration = operand
        if op != "collect_matching":
            return _eval_quantifier(op, declaration, context, env, ports, _eval)
        collection = _eval(declaration["collection"], context, env, ports)
        if op != "none_matching" and (type(collection) is not tuple or len(collection) > _MAX_INT):
            raise C0ValueStateError("bounded quantifier needs an exact bounded tuple")
        name = declaration["as"]
        item_type = _tuple_item(declaration["collection"].result_type)
        if op == "collect_matching":
            if not _value_matches(collection, declaration["collection"].result_type):
                raise C0ValueStateError("collection projection met a foreign nominal element")
            item_env = {**env, name: item_type}
            # Only selected values run; order and multiplicity belong to the input tuple.
            return tuple(
                _eval(declaration["value"], {**context, name: item}, item_env, ports)
                for item in collection
                if _eval(declaration["where"], {**context, name: item}, item_env, ports) is True
            )
    raise C0ValueStateError("compiled value expression has no operation")


def _reduce_quantifier(
    operation, declaration, collection, context, env, ports, predicate, item_plan=None
):
    name = declaration["as"]
    collection_node = declaration["collection"]
    item_type = (
        item_plan[1]
        if item_plan is not None and collection_node.value_type is item_plan[0]
        else _tuple_item(collection_node.result_type)
    )
    if operation == "none_matching":
        for item in collection:
            if (
                predicate(
                    declaration["where"], {**context, name: item}, {**env, name: item_type}, ports
                )
                is True
            ):
                return False
        return True
    if operation == "exists":
        for item in collection:
            if (
                predicate(
                    declaration["where"], {**context, name: item}, {**env, name: item_type}, ports
                )
                is True
            ):
                return True
        return False
    if operation == "exactly_one":
        found = False
        for item in collection:
            if (
                predicate(
                    declaration["where"], {**context, name: item}, {**env, name: item_type}, ports
                )
                is True
            ):
                if found:
                    return False
                found = True
        return found
    count = 0
    for item in collection:
        if (
            predicate(
                declaration["where"], {**context, name: item}, {**env, name: item_type}, ports
            )
            is True
        ):
            count += 1
    return count


def _eval_quantifier(
    operation, declaration, context, env, ports, predicate, collection_executor=None, item_plan=None
):
    evaluate_collection = _eval if collection_executor is None else collection_executor
    collection = evaluate_collection(declaration["collection"], context, env, ports)
    if operation != "none_matching" and (
        type(collection) is not tuple or len(collection) > _MAX_INT
    ):
        raise C0ValueStateError("bounded quantifier needs an exact bounded tuple")
    return _reduce_quantifier(
        operation, declaration, collection, context, env, ports, predicate, item_plan
    )


def _false_guard_clauses(
    node: Mapping[str, Any],
    context: dict[str, object],
    env: dict[str, object],
    ports: C0ValuePorts,
    path: str,
    names: tuple[str, ...] = (),
    branches: tuple[str, ...] = (),
    alternatives: tuple[C0GuardAlternative, ...] = (),
) -> tuple[C0GuardFailure, ...]:
    if "match" in node:
        local_context, local_env, arm, case = _match_context(node["match"], context, env, ports)
        return _false_guard_clauses(
            arm["then"],
            local_context,
            local_env,
            ports,
            f"{path}.match.cases.{case}.then",
            names,
            (*branches, f"{path}.match.cases.{case}.then"),
            alternatives,
        )
    if "call" in node:
        local_context, local_env = _call_context(node["call"], context, env, ports)
        return _false_guard_clauses(
            node["call"]["body"],
            local_context,
            local_env,
            ports,
            f"{path}.call.body",
            names,
            branches,
            alternatives,
        )
    if "let" in node:
        declaration = node["let"]
        local = _LazyValue(declaration["value"], dict(context), dict(env), ports)
        return _false_guard_clauses(
            declaration["in"],
            {**context, declaration["name"]: local},
            {**env, declaration["name"]: declaration["value"].result_type},
            ports,
            f"{path}.let.in",
            names,
            branches,
            alternatives,
        )
    if "clause" in node:
        return _false_guard_clauses(
            node["clause"]["test"],
            context,
            env,
            ports,
            f"{path}.clause.test",
            (*names, node["clause"]["name"]),
            branches,
            alternatives,
        )
    if "all" in node:
        for index, part in enumerate(node["all"]):
            if _eval(part, context, env, ports) is not True:
                return _false_guard_clauses(
                    part, context, env, ports, f"{path}.all[{index}]", names, branches, alternatives
                )
    elif "any" in node:
        return tuple(
            failure
            for index, part in enumerate(node["any"])
            for failure in _false_guard_clauses(
                part,
                context,
                env,
                ports,
                f"{path}.any[{index}]",
                names,
                branches,
                (
                    *alternatives,
                    C0GuardAlternative(f"{path}.any[{index}]", index, f"{path}.any[{index}]"),
                ),
            )
        )
    elif "if" in node:
        branch = "then" if _eval(node["if"]["when"], context, env, ports) is True else "else"
        location = f"{path}.if.{branch}"
        return _false_guard_clauses(
            node["if"][branch],
            context,
            env,
            ports,
            location,
            names,
            (*branches, location),
            alternatives,
        )
    return (
        C0GuardFailure(
            path,
            json.dumps(_plain_tree(node), sort_keys=True, separators=(",", ":")),
            names,
            branches,
            node.provenance,
            alternatives,
        ),
    )


def _freeze_tree(value: object) -> object:
    from .expression_ir_v1 import freeze_value_tree

    return freeze_value_tree(value)


def _plain_tree(value: object) -> object:
    if type(value) is C0Expression and "call" in value:
        return {
            "call": {
                "ref": value["call"]["definition"].name,
                "args": {key: _plain_tree(item) for key, item in value["call"]["args"].items()},
            }
        }
    if isinstance(value, Mapping):
        return {key: _plain_tree(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain_tree(item) for item in value]
    return value


def verify_pure_definition_types(
    definitions: tuple[C0PureDefinition, ...], records: Mapping[str, type]
) -> None:
    """Check every definition structurally; actual calls recheck narrower owner permissions."""
    visible = {}
    for definition in definitions:
        for annotation in (definition.result, *(value for _, value in definition.parameters)):
            for carrier, names in _complete_value_fields(annotation).items():
                visible.setdefault(carrier, set()).update(names)
    for carrier in records.values():
        for nested, names in _complete_value_fields(carrier).items():
            visible.setdefault(nested, set()).update(names)
    fields = {carrier: frozenset(names) for carrier, names in visible.items()}
    abstract = C0ValuePorts(
        {},
        frozenset(),
        frozenset(),
        fields,
        fields,
        fields,
        dict(records),
        {},
        {},
        {},
        {"valid": bool},
        definitions,
    )
    for definition in definitions:
        expression = _compile_expression(
            definition.body,
            dict(definition.parameters),
            abstract,
            set(),
            occurrence=definition.stage == "effect",
            origin=f"pure_definitions.{definition.name}.body",
            source_paths=definition.source_paths,
        )
        if not _assignable(expression.result_type, definition.result):
            raise C0LawError("pure body has the wrong declared result type")


@dataclass(frozen=True, eq=False)
class _AnnotationValues(Mapping):
    """Expose annotations without storing generic aliases in K0 configuration."""

    entries: Mapping[str, C0ValueType]

    def __getitem__(self, key):
        return self.entries[key].annotation

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)


@dataclass(frozen=True, eq=False)
class _AnnotationKeys(Mapping):
    entries: Mapping[C0ValueType, object]

    def __getitem__(self, key):
        try:
            closed = closed_value_type(key)
        except TypeError:
            raise KeyError(key) from None
        if closed in self.entries:
            return self.entries[closed]
        # Union argument order differs in closed metadata, not in annotation equality.
        for declared, value in self.entries.items():
            if declared.annotation == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key.annotation for key in self.entries)

    def __len__(self):
        return len(self.entries)


@dataclass(frozen=True)
class C0ClosedValuePorts:
    authority: C0ValuePorts
    roots: tuple[tuple[str, C0ValueType], ...]
    outputs: tuple[tuple[str, C0ValueType], ...]
    records: tuple[tuple[str, C0ValueType], ...]
    fields: tuple[tuple[str, tuple[tuple[C0ValueType, object], ...]], ...]

    @classmethod
    def capture(cls, ports: C0ValuePorts) -> C0ClosedValuePorts:
        names = (
            "readable_fields",
            "admission_readable_fields",
            "writable_fields",
            "tuple_fields",
            "admission_tuple_fields",
        )
        return cls(
            replace(
                ports,
                roots=MappingProxyType({}),
                outputs=MappingProxyType({}),
                record_types=MappingProxyType({}),
                readable_paths=frozenset(ports.readable_paths),
                admission_readable_paths=frozenset(ports.admission_readable_paths),
                writable_paths=frozenset(ports.writable_paths),
                collection_keys=MappingProxyType(dict(ports.collection_keys)),
                pure_definitions=tuple(ports.pure_definitions),
                participant_groups=tuple(
                    (name, tuple(members)) for name, members in ports.participant_groups
                ),
                **{name: MappingProxyType({}) for name in names},
            ),
            tuple((name, closed_value_type(value)) for name, value in ports.roots.items()),
            tuple((name, closed_value_type(value)) for name, value in ports.outputs.items()),
            tuple((name, closed_value_type(value)) for name, value in ports.record_types.items()),
            tuple(
                (
                    name,
                    tuple(
                        (
                            closed_value_type(key),
                            _freeze_tree(value)
                            if name in ("tuple_fields", "admission_tuple_fields")
                            else frozenset(value),
                        )
                        for key, value in getattr(ports, name).items()
                    ),
                )
                for name in names
            ),
        )

    def annotations(self) -> C0ValuePorts:
        def values(items):
            if all(value.kind == "nominal" for _, value in items):
                return MappingProxyType({name: value.carrier for name, value in items})
            return _AnnotationValues(MappingProxyType(dict(items)))

        def keys(items):
            if all(key.kind == "nominal" for key, _ in items):
                return MappingProxyType({key.carrier: value for key, value in items})
            return _AnnotationKeys(MappingProxyType(dict(items)))

        return replace(
            self.authority,
            roots=values(self.roots),
            outputs=values(self.outputs),
            record_types=values(self.records),
            **{name: keys(items) for name, items in self.fields},
        )


@dataclass(frozen=True, init=False)
class C0ValueProgram:
    guard_ir: C0GuardIR
    _tree: Mapping[str, Any]
    _closed_ports: C0ClosedValuePorts
    _runtime_ports: C0ValuePorts
    _runtime_admission_ports: C0ValuePorts
    _admission_outputs: frozenset[str]
    _closed_binding_types: tuple[C0ValueType, ...]
    effects: tuple[C0ValueEffectIR, ...] = ()

    def __init__(self, guard_ir, _tree, _ports, _admission_outputs, _binding_types, effects=()):
        object.__setattr__(self, "guard_ir", guard_ir)
        object.__setattr__(self, "_tree", _freeze_tree(_tree))
        closed_ports = C0ClosedValuePorts.capture(_ports)
        runtime_ports = closed_ports.annotations()
        object.__setattr__(self, "_closed_ports", closed_ports)
        object.__setattr__(self, "_runtime_ports", runtime_ports)
        object.__setattr__(self, "_runtime_admission_ports", admission_value_ports(runtime_ports))
        object.__setattr__(self, "_admission_outputs", frozenset(_admission_outputs))
        object.__setattr__(
            self,
            "_closed_binding_types",
            tuple(closed_value_type(value) for value in _binding_types),
        )
        object.__setattr__(self, "effects", tuple(effects))

    @property
    def _ports(self) -> C0ValuePorts:
        return self._runtime_ports

    @property
    def _binding_types(self) -> tuple[object, ...]:
        return tuple(value.annotation for value in self._closed_binding_types)

    @property
    def _admission_ports(self) -> C0ValuePorts:
        return self._runtime_admission_ports

    def _check_roots(self, roots: dict[str, object], ports: C0ValuePorts) -> None:
        if type(roots) is not dict or set(roots) != set(ports.roots):
            raise C0ValueStateError("value evaluation has the wrong owner roots")
        if any(not _value_matches(value, ports.roots[name]) for name, value in roots.items()):
            raise C0ValueStateError("value evaluation has a foreign nominal root")

    def _admitted_context(
        self,
        roots: dict[str, object],
        guard_failures: list[C0GuardFailure] | None = None,
    ) -> tuple[dict[str, Any], dict[str, object], dict[str, object]] | None:
        ports = self._ports
        self._check_roots(roots, ports)
        source = self._tree
        context = dict(roots)
        env: dict[str, object] = dict(ports.roots)
        admission_ports = self._admission_ports
        try:
            for binding, annotation in zip(source["bindings"], self._binding_types, strict=True):
                if "let" in binding:
                    if binding["stage"] == "admission":
                        context[binding["name"]] = _LazyValue(
                            binding["let"],
                            dict(context),
                            dict(env),
                            admission_ports,
                        )
                        env[binding["name"]] = annotation
                    continue
                if set(binding) == {"name", "const"}:
                    context[binding["name"]] = binding["const"]
                    env[binding["name"]] = annotation
                    continue
                if "where" in binding:
                    path, item_name = binding["collection"], binding["as"]
                    collection = _read_ref(path, context, env, admission_ports)
                    item_type = _nonnull(annotation) or annotation
                    if path in admission_ports.collection_keys:
                        _require_unique(
                            collection,
                            admission_ports.collection_keys[path],
                            item_type,
                            admission_ports,
                        )
                    matches = tuple(
                        item
                        for item in collection
                        if _eval(
                            binding["where"],
                            {**context, item_name: item},
                            {**env, item_name: item_type},
                            admission_ports,
                        )
                        is True
                    )
                    if len(matches) > 1 or not matches and binding["required"]:
                        return None
                    context[binding["name"]] = matches[0] if matches else None
                    env[binding["name"]] = annotation
                    continue
                path, key = binding["collection"], binding["key"]
                collection = _read_ref(path, context, env, admission_ports)
                item_type = _nonnull(annotation) or annotation
                _require_unique(collection, key, item_type, admission_ports)
                key_value = _eval(binding["value"], context, env, admission_ports)
                matches = tuple(
                    item
                    for item in collection
                    if _read_ref(
                        f"item.{key}", {"item": item}, {"item": item_type}, admission_ports
                    )
                    == key_value
                )
                if len(matches) > 1 or not matches and binding["required"]:
                    raise C0ValueStateError("required or unique lookup failed")
                context[binding["name"]] = matches[0] if matches else None
                env[binding["name"]] = annotation
            if _eval(self.guard_ir.expression, context, env, admission_ports) is not True:
                if guard_failures is not None:
                    guard_failures.extend(
                        _false_guard_clauses(
                            self.guard_ir.expression, context, env, admission_ports, "guard"
                        )
                    )
                return None
            return source, context, env
        except (AttributeError, IndexError, KeyError, TypeError) as error:
            raise C0ValueStateError("compiled value met malformed current state") from error

    def admits(self, roots: dict[str, object]) -> bool:
        """Check the current guard without predicting K0's future occurrence ref."""
        if self._tree["bindings"]:
            return self._admitted_context(roots) is not None
        # A closed guard has no context to extend or return; still recheck every input.
        ports = self._ports
        self._check_roots(roots, ports)
        try:
            return (
                _eval(self.guard_ir.expression, roots, ports.roots, self._admission_ports) is True
            )
        except (AttributeError, IndexError, KeyError, TypeError) as error:
            raise C0ValueStateError("compiled value met malformed current state") from error

    def false_guard_clauses(self, roots: dict[str, object]) -> tuple[C0GuardFailure, ...]:
        """Explain only false authored predicates, not the complete K0 refusal."""
        failures: list[C0GuardFailure] = []
        self._admitted_context(roots, failures)
        paths = self.guard_ir.source_paths
        return tuple(
            replace(
                failure,
                path=paths[failure.path],
                branches=tuple(paths[path] for path in failure.branches),
                alternatives=tuple(
                    replace(alternative, path=paths[alternative.identity])
                    for alternative in failure.alternatives
                ),
            )
            for failure in failures
        )

    def evaluate_admission_outputs(self, roots: dict[str, object]) -> dict[str, object] | None:
        """Evaluate only outputs proven to use admission-visible inputs."""
        admitted = self._admitted_context(roots)
        if admitted is None:
            return None
        source, context, env = admitted
        ports = self._admission_ports
        try:
            result = {
                name: _eval(expression, context, env, ports)
                for name, expression in source["outputs"].items()
                if name in self._admission_outputs
            }
            if any(
                not _value_matches(value, ports.outputs[name]) for name, value in result.items()
            ):
                raise C0ValueStateError("admission output has a foreign type")
            return result
        except (AttributeError, IndexError, KeyError, TypeError) as error:
            raise C0ValueStateError("admission output met malformed current state") from error

    def evaluate(
        self,
        roots: dict[str, object],
        *,
        occurrence: K0OccurrenceRef | None = None,
    ) -> dict[str, object] | None:
        if occurrence is not None and type(occurrence) is not K0OccurrenceRef:
            raise C0ValueStateError("value evaluation has a foreign occurrence")
        admitted = self._admitted_context(roots)
        if admitted is None:
            return None
        if occurrence is None:
            raise C0ValueStateError("effect evaluation needs an actual occurrence")
        source, context, env = admitted
        context["occurrence"] = occurrence
        for binding, annotation in zip(source["bindings"], self._binding_types, strict=True):
            if "let" in binding and binding["stage"] == "effect":
                context[binding["name"]] = _LazyValue(
                    binding["let"],
                    dict(context),
                    dict(env),
                    self._ports,
                )
                env[binding["name"]] = annotation
        try:
            result = {
                name: _eval(expression, context, env, self._ports)
                for name, expression in source["outputs"].items()
            }
            if any(
                not _value_matches(value, self._ports.outputs[name])
                for name, value in result.items()
            ):
                raise C0ValueStateError("compiled value result has a foreign type")
            return result
        except (AttributeError, IndexError, KeyError, TypeError) as error:
            raise C0ValueStateError("compiled value met malformed current state") from error


def compile_value_program(
    source: str,
    ports: C0ValuePorts,
    *,
    admission_outputs: frozenset[str] = frozenset(),
    state_outputs: Mapping[str, str] | None = None,
) -> C0ValueProgram:
    """Compile pure author expressions against a frozen nominal read/write contract."""
    if type(source) is not str or not source or len(source) > 65536:
        raise C0LawError("value source is empty or too large")
    try:
        row = _object(json.loads(source, object_pairs_hook=_unique_object), "value source")
    except (ValueError, RecursionError) as error:
        raise C0LawError("value source is not valid JSON") from error
    required = {"schema", "bindings", "guard", "outputs"}
    if not required <= set(row) or set(row) - required - {"effects", "output_families"}:
        raise C0LawError("value source has missing or unknown fields")
    if row["schema"] != "c0.value.v1" or type(row["bindings"]) is not list:
        raise C0LawError("value source schema or bindings are malformed")
    if len(row["bindings"]) > _MAX_BINDINGS:
        raise C0LawError("value binding count exceeds the finite limit of 64")
    if ports.source_context is not None:
        ports = replace(ports, source_context=named_source_paths(ports.source_context, row))
    expression_names = {
        *ports.roots,
        "occurrence",
        *(
            binding.get("name")
            for binding in row["bindings"]
            if type(binding) is dict and type(binding.get("name")) is str
        ),
    }
    expression_options = dict(
        participant_groups=ports.participant_groups, reserved_names=expression_names
    )
    row["guard"], guard_paths = lower_author_expression(row["guard"], **expression_options)
    binding_paths = {}
    for index, binding in enumerate(row["bindings"]):
        if type(binding) is dict:
            for key in ("where", "value", "let"):
                if key in binding:
                    binding[key], binding_paths[index, key] = lower_author_expression(
                        binding[key], path=f"bindings[{index}].{key}", **expression_options
                    )
    checked = _check_ports(ports)
    admission_ports = replace(
        checked,
        readable_paths=checked.admission_readable_paths,
        readable_fields=checked.admission_readable_fields,
        tuple_fields=checked.admission_tuple_fields,
    )
    env: dict[str, object] = dict(checked.roots)
    binding_types = [None] * len(row["bindings"])
    effect_bindings = []
    declared = set(env)
    for index, binding in enumerate(row["bindings"]):
        name = _binding_name(_object(binding, "value binding"), declared)
        declared.add(name)
        if binding.get("stage") == "effect":
            _exact(binding, {"name", "let", "stage"}, "effect computation")
            effect_bindings.append((index, binding))
            continue
        if effect_bindings:
            raise C0LawError("admission bindings must precede effect computations")
        name, annotation = _check_binding(binding, env, admission_ports)
        binding_types[index] = annotation
        if "let" in binding:
            binding["let"] = _compile_expression(
                binding["let"],
                env,
                admission_ports,
                set(),
                origin=f"bindings[{index}].let",
                source_paths=binding_paths[index, "let"],
            )
        elif "where" in binding:
            binding["where"] = _compile_expression(
                binding["where"],
                {
                    **env,
                    binding["as"]: _tuple_item(
                        _ref_type(binding["collection"], env, admission_ports, set())
                    ),
                },
                admission_ports,
                set(),
                origin=f"bindings[{index}].where",
                source_paths=binding_paths[index, "where"],
            )
        elif "value" in binding:
            binding["value"] = _compile_expression(
                binding["value"],
                env,
                admission_ports,
                set(),
                origin=f"bindings[{index}].value",
                source_paths=binding_paths[index, "value"],
            )
        env[name] = (
            _LocalType(annotation, binding["let"], dict(env), admission_ports, frozenset())
            if "let" in binding
            else annotation
        )
    if _expr_type(row["guard"], env, admission_ports, set()) is not bool:
        raise C0LawError("value guard must be boolean")
    outputs = _object(row["outputs"], "value outputs")
    proven = _guard_proofs(row["guard"], env, admission_ports)
    effects = ()
    generated_paths = {}
    family_outputs = {}
    output_contexts = {}
    computation_contexts = {}
    member_names = set()
    if "effects" in row or "output_families" in row:
        write_map = _object(state_outputs, "effect state write graph")
        for path, output in write_map.items():
            parts = path.split(".")
            carrier = checked.roots.get(parts[0])
            carrier = _nonnull(carrier) or carrier
            if (
                len(parts) != 2
                or parts[0] not in checked.roots
                or parts[1] not in checked.writable_fields.get(carrier, frozenset())
                or path not in checked.writable_paths
                or type(output) is not str
                or output not in checked.outputs
                or not _assignable(checked.outputs[output], _resolved_fields(carrier)[parts[1]])
            ):
                raise C0LawError("effect state write graph crosses a typed write port")
        if len(set(write_map.values())) != len(write_map):
            raise C0LawError("effect state write graph has aliased outputs")
    if "output_families" in row:
        before_bindings = len(row["bindings"])
        computation_paths = {}
        family_outputs, generated_paths = expand_output_families(
            row.pop("output_families"),
            roots=checked.roots,
            binding_names=declared - checked.roots.keys(),
            state_outputs=write_map,
            explicit_outputs=outputs,
            source_context=checked.source_context,
            origins=output_contexts,
            computations=row["bindings"],
            computation_paths=computation_paths,
            computation_origins=computation_contexts,
        )
        for index in range(before_bindings, len(row["bindings"])):
            binding = row["bindings"][index]
            declared.add(binding["name"])
            member_names.add(binding["name"])
            binding_types.append(None)
            effect_bindings.append((index, binding))
            binding_paths[index, "let"] = computation_paths[binding["name"]]
        outputs.update(family_outputs)
    if "effects" in row:
        effects = read_value_effects(row.pop("effects"), write_map, outputs, max_integer=_MAX_INT)
        for effect in effects:
            if effect.operation == "assign":
                outputs.update(effect.results)
                continue
            if _expr_type(effect.activation, env, admission_ports, proven) is not bool:
                raise C0LawError(f"effects.{effect.name}: activation must be an admission boolean")
            active_proofs = proven | _guard_proofs(effect.activation, env, admission_ports, proven)
            for expression, expected in effect.inputs:
                if _expr_type(expression, env, admission_ports, active_proofs) is not expected:
                    raise C0LawError(
                        f"effects.{effect.name}: {effect.operation} inputs must be admission "
                        + ("integers" if expected is int else "booleans")
                    )
            expected = bool if effect.operation == "consume" else int
            for _, output in effect.writes:
                if not _assignable(expected, checked.outputs[output]) or not set(
                    _variants(checked.outputs[output])
                ) <= {expected, type(None)}:
                    raise C0LawError(
                        f"effects.{effect.name}: effect outputs have the wrong scalar type"
                    )
            outputs.update(effect.results)
        generated_paths.update(effect_output_paths(effects))
        row["guard"], guard_paths = with_effect_checks(row["guard"], guard_paths, effects)
        if _expr_type(row["guard"], env, admission_ports, set()) is not bool:
            raise C0LawError("effect guard must be boolean")
    _exact(outputs, set(checked.outputs), "value outputs")
    if type(admission_outputs) is not frozenset or not admission_outputs <= outputs.keys():
        raise C0LawError("admission outputs lack declared value ports")
    proven = _guard_proofs(row["guard"], env, admission_ports)
    admission_env = dict(env)
    guard_ir = lower_checked_guard(
        _compile_expression(
            row.pop("guard"),
            env,
            admission_ports,
            set(),
            origin="guard",
            source_paths=guard_paths,
        ),
        guard_paths,
    )
    for index, binding in effect_bindings:
        binding_ports = (
            replace(checked, source_context=computation_contexts[binding["name"]])
            if binding["name"] in computation_contexts
            else checked
        )
        name, annotation = _check_binding(
            binding,
            env,
            binding_ports,
            nonnull=proven,
            occurrence=True,
        )
        binding_types[index] = annotation
        binding["let"] = _compile_expression(
            binding["let"],
            env,
            binding_ports,
            proven,
            occurrence=True,
            origin=f"bindings[{index}].let",
            source_paths=binding_paths[index, "let"],
        )
        env[name] = _LocalType(
            annotation, binding["let"], dict(env), binding_ports, frozenset(proven), True
        )
    for name, expression in outputs.items():
        output_ports = (
            replace(checked, source_context=output_contexts[name])
            if name in output_contexts
            else checked
        )
        if name in generated_paths:
            output_paths = generated_paths[name]
        else:
            expression, output_paths = lower_author_expression(
                expression, path=f"outputs.{name}", **expression_options
            )

        def member_reference(value):
            if isinstance(value, dict):
                if set(value) == {"ref"} and isinstance(value["ref"], str):
                    return value["ref"].split(".")[0] in member_names
                return any(member_reference(item) for item in value.values())
            if isinstance(value, list):
                return any(member_reference(item) for item in value)
            return False

        if name not in family_outputs and member_reference(expression):
            raise C0LawError("member bindings cannot escape their output family")
        try:
            compiled = _compile_expression(
                expression,
                env,
                output_ports,
                proven,
                occurrence=True,
                origin=f"outputs.{name}",
                source_paths=output_paths,
            )
            if not _assignable(compiled.result_type, checked.outputs[name]):
                raise C0LawError("value output has a wrong nominal type")
            _check_materialization(
                compiled, compiled.result_type, env, output_ports, proven, selected_only=True
            )
            if name in admission_outputs:
                compiled = _compile_expression(
                    expression,
                    admission_env,
                    replace(admission_ports, source_context=output_ports.source_context),
                    proven,
                    origin=f"outputs.{name}",
                    source_paths=output_paths,
                )
                _check_materialization(
                    compiled,
                    compiled.result_type,
                    admission_env,
                    replace(admission_ports, source_context=output_ports.source_context),
                    proven,
                    selected_only=True,
                )
        except C0LawError as error:
            if name in generated_paths:
                raise C0LawError(f"{output_paths[f'outputs.{name}']}: {error}") from error
            raise
        outputs[name] = compiled
    tree = _freeze_tree(row)
    effect_ir = []
    check_index = 0
    for effect in effects:
        if effect.checks is None:
            first = tree["outputs"][effect.writes[0][1]]
            activation = (
                first["if"]["when"]
                if effect.conditional
                else _compile_expression(
                    effect.activation,
                    env,
                    checked,
                    proven,
                    occurrence=True,
                    origin=f"effects.{effect.name}.when",
                    source_paths=effect.activation_paths,
                )
            )
            checks = None
        else:
            checks = guard_ir.expression["all"][1]["all"][check_index]
            activation = checks["if"]["when"] if effect.conditional else checks["all"][0]
            check_index += 1
        effect_ir.append(
            C0ValueEffectIR(
                effect.name,
                effect.operation,
                effect.endpoints,
                effect.writes,
                activation,
                checks,
                tuple((output, tree["outputs"][output]) for _, output in effect.writes),
                f"effects.{effect.name}",
            )
        )
    return C0ValueProgram(
        guard_ir,
        tree,
        runtime_value_ports(checked),
        admission_outputs,
        tuple(binding_types),
        tuple(effect_ir),
    )
