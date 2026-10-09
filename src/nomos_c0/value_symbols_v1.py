"""Replace checked value carriers with nominal symbols; bind without recompiling."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame
from .composable_value_v1 import C0ValuePorts, C0ValueProgram, _check_ports
from .expression_ir_v1 import C0Expression, C0ValueType, closed_value_type
from .guard_ir_v0 import C0ClauseSource, C0GuardIR
from .pure_definition_v1 import C0PureDefinition
from .value_effect_ir_v0 import C0ValueEffectIR
from .variant_types_v1 import variant_cases

_BUILTINS = {
    "bool": bool,
    "int": int,
    "str": str,
    "none": type(None),
    "occurrence_ref": K0OccurrenceRef,
    "individual_ref": _K0IndividualRef,
    "actor_ref": _K0ActorRef,
}


@dataclass(frozen=True)
class C0SymbolicType:
    kind: str
    symbol: str = ""
    arguments: tuple[C0SymbolicType, ...] = ()


@dataclass(frozen=True)
class C0SymbolicExpression:
    operation: str
    operand: object
    value_type: C0SymbolicType
    stage: str
    origin: str
    provenance: tuple[C0OriginFrame, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class C0SymbolicPureDefinition:
    name: str
    parameters: tuple[tuple[str, C0SymbolicType], ...]
    result: C0SymbolicType
    stage: str
    body: Mapping[str, object]
    source_paths: Mapping[str, str]


@dataclass(frozen=True)
class C0SymbolicValuePorts:
    roots: tuple[tuple[str, C0SymbolicType], ...]
    readable_paths: frozenset[str]
    admission_readable_paths: frozenset[str]
    readable_fields: tuple[tuple[C0SymbolicType, frozenset[str]], ...]
    admission_readable_fields: tuple[tuple[C0SymbolicType, frozenset[str]], ...]
    writable_fields: tuple[tuple[C0SymbolicType, frozenset[str]], ...]
    record_types: tuple[tuple[str, C0SymbolicType], ...]
    tuple_fields: tuple[tuple[C0SymbolicType, tuple[tuple[str, int], ...]], ...]
    admission_tuple_fields: tuple[tuple[C0SymbolicType, tuple[tuple[str, int], ...]], ...]
    collection_keys: tuple[tuple[str, str], ...]
    outputs: tuple[tuple[str, C0SymbolicType], ...]
    pure_definitions: tuple[C0SymbolicPureDefinition, ...]


@dataclass(frozen=True)
class C0SymbolicValueEffect:
    name: str
    operation: str
    endpoints: tuple[tuple[str, str], ...]
    writes: tuple[tuple[str, str], ...]
    activation: C0SymbolicExpression
    checks: C0SymbolicExpression | None
    results: tuple[tuple[str, C0SymbolicExpression], ...]
    source_path: str


@dataclass(frozen=True)
class C0SymbolicValueProgram:
    guard: C0SymbolicExpression
    clauses: tuple[C0ClauseSource, ...]
    source_paths: Mapping[str, str]
    tree: Mapping[str, object]
    ports: C0SymbolicValuePorts
    admission_outputs: frozenset[str]
    binding_types: tuple[C0SymbolicType, ...]
    effects: tuple[C0SymbolicValueEffect, ...]


class _ValueSymbolTranslation:
    def __init__(
        self,
        records: Mapping[str, type],
        *,
        binding: bool,
        intrinsics: Mapping[str, type] | None = None,
    ) -> None:
        intrinsics = {} if intrinsics is None else dict(intrinsics)
        if (
            any(type(name) is not str for name in records)
            or any(not isinstance(carrier, type) for carrier in records.values())
            or len(set(records.values())) != len(records)
            or set(records.values()) & set(_BUILTINS.values())
            or any(type(name) is not str for name in intrinsics)
            or any(not isinstance(carrier, type) for carrier in intrinsics.values())
            or len(set(intrinsics.values())) != len(intrinsics)
            or set(intrinsics.values()) & (set(records.values()) | set(_BUILTINS.values()))
        ):
            raise C0LawError("value nominal layout has malformed or aliased records")
        self.records = dict(records)
        self.names = {carrier: name for name, carrier in records.items()}
        self.builtins = {carrier: name for name, carrier in _BUILTINS.items()}
        self.binding = binding
        self.intrinsics = intrinsics
        self.intrinsic_names = {carrier: name for name, carrier in intrinsics.items()}
        self.memo: dict[int, tuple[object, object]] = {}

    def symbolize_type(self, annotation: object) -> C0SymbolicType:
        return self.symbolize_value_type(closed_value_type(annotation))

    def symbolize_value_type(self, value: C0ValueType) -> C0SymbolicType:
        if value.kind == "nominal":
            if value.carrier in self.builtins:
                return C0SymbolicType("builtin", self.builtins[value.carrier])
            if value.carrier in self.intrinsic_names:
                return C0SymbolicType("intrinsic", self.intrinsic_names[value.carrier])
            if value.carrier not in self.names:
                raise C0LawError("checked value carrier has no nominal declaration")
            return C0SymbolicType(
                "variant" if variant_cases(value.carrier) else "record", self.names[value.carrier]
            )
        return C0SymbolicType(
            value.kind, arguments=tuple(self.symbolize_value_type(x) for x in value.arguments)
        )

    def bind_type(self, value: C0SymbolicType) -> C0ValueType:
        if value.kind in ("builtin", "record", "variant", "intrinsic"):
            table = {
                "builtin": _BUILTINS,
                "record": self.records,
                "variant": self.records,
                "intrinsic": self.intrinsics,
            }[value.kind]
            if value.arguments or value.symbol not in table:
                raise C0LawError("value nominal symbol has no backend binding")
            if value.kind in ("record", "variant") and bool(variant_cases(table[value.symbol])) != (
                value.kind == "variant"
            ):
                raise C0LawError("value record/variant symbol has the wrong backend kind")
            return C0ValueType("nominal", table[value.symbol])
        if value.symbol or value.kind not in ("tuple", "union", "variadic"):
            raise C0LawError("value symbolic type is malformed")
        return C0ValueType(value.kind, arguments=tuple(self.bind_type(x) for x in value.arguments))

    def pure(self, value: C0PureDefinition | C0SymbolicPureDefinition):
        if self.binding:
            return C0PureDefinition(
                value.name,
                tuple((name, self.bind_type(item)) for name, item in value.parameters),
                self.bind_type(value.result),
                value.stage,
                self.tree(value.body),
                value.source_paths,
            )
        return C0SymbolicPureDefinition(
            value.name,
            tuple((name, self.symbolize_value_type(item)) for name, item in value.parameter_types),
            self.symbolize_value_type(value.result_type),
            value.stage,
            self.tree(value.body),
            value.source_paths,
        )

    def tree(self, value: object) -> object:
        if type(value) in (str, int, bool, type(None)):
            return value
        if id(value) in self.memo:
            return self.memo[id(value)][1]
        if type(value) is (C0SymbolicExpression if self.binding else C0Expression):
            result = (C0Expression if self.binding else C0SymbolicExpression)(
                value.operation,
                self.tree(value.operand),
                self.bind_type(value.value_type)
                if self.binding
                else self.symbolize_value_type(value.value_type),
                value.stage,
                value.origin,
                value.provenance,
            )
        elif type(value) is (C0SymbolicPureDefinition if self.binding else C0PureDefinition):
            result = self.pure(value)
        elif isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise C0LawError("checked value tree has a non-symbolic key")
            translated = {key: self.tree(item) for key, item in value.items()}
            if self.binding:
                from .expression_ir_v1 import freeze_value_tree

                result = freeze_value_tree(translated)
            else:
                result = MappingProxyType(translated)
        elif type(value) is tuple:
            result = tuple(self.tree(item) for item in value)
        else:
            raise C0LawError("checked value tree contains an unsupported backend object")
        # Keep the input alive: one batch may visit several independent input graphs.
        self.memo[id(value)] = value, result
        return result

    def ports(self, ports: C0ValuePorts | C0SymbolicValuePorts):
        if self.binding:

            def annotation(value):
                return self.bind_type(value).annotation

            def fields(rows):
                return MappingProxyType({annotation(t): names for t, names in rows})

            def tuples(rows):
                return MappingProxyType(
                    {annotation(t): MappingProxyType(dict(offsets)) for t, offsets in rows}
                )

            return C0ValuePorts(
                MappingProxyType({name: annotation(t) for name, t in ports.roots}),
                ports.readable_paths,
                ports.admission_readable_paths,
                fields(ports.readable_fields),
                fields(ports.admission_readable_fields),
                fields(ports.writable_fields),
                MappingProxyType({name: annotation(t) for name, t in ports.record_types}),
                tuples(ports.tuple_fields),
                tuples(ports.admission_tuple_fields),
                MappingProxyType(dict(ports.collection_keys)),
                MappingProxyType({name: annotation(t) for name, t in ports.outputs}),
                tuple(self.tree(item) for item in ports.pure_definitions),
            )

        def fields(rows):
            return tuple((self.symbolize_type(t), names) for t, names in rows.items())

        def tuples(rows):
            return tuple(
                (self.symbolize_type(t), tuple(offsets.items())) for t, offsets in rows.items()
            )

        return C0SymbolicValuePorts(
            tuple((name, self.symbolize_type(t)) for name, t in ports.roots.items()),
            ports.readable_paths,
            ports.admission_readable_paths,
            fields(ports.readable_fields),
            fields(ports.admission_readable_fields),
            fields(ports.writable_fields),
            tuple((name, self.symbolize_type(t)) for name, t in ports.record_types.items()),
            tuples(ports.tuple_fields),
            tuples(ports.admission_tuple_fields),
            tuple(ports.collection_keys.items()),
            tuple((name, self.symbolize_type(t)) for name, t in ports.outputs.items()),
            tuple(self.tree(item) for item in ports.pure_definitions),
        )


def symbolize_value_program(
    program: C0ValueProgram,
    records: Mapping[str, type],
    *,
    intrinsics: Mapping[str, type] | None = None,
) -> C0SymbolicValueProgram:
    return symbolize_value_programs((program,), records, intrinsics=intrinsics)[0]


def symbolize_value_programs(
    programs: tuple[C0ValueProgram, ...],
    records: Mapping[str, type],
    *,
    intrinsics: Mapping[str, type] | None = None,
) -> tuple[C0SymbolicValueProgram, ...]:
    translation = _ValueSymbolTranslation(records, binding=False, intrinsics=intrinsics)
    return tuple(_symbolize_value_program(program, translation) for program in programs)


def _symbolize_value_program(
    program: C0ValueProgram, translation: _ValueSymbolTranslation
) -> C0SymbolicValueProgram:
    _check_ports(program._ports)
    return C0SymbolicValueProgram(
        translation.tree(program.guard_ir.expression),
        program.guard_ir.clauses,
        program.guard_ir.source_paths,
        translation.tree(program._tree),
        translation.ports(program._ports),
        program._admission_outputs,
        tuple(translation.symbolize_type(item) for item in program._binding_types),
        tuple(
            C0SymbolicValueEffect(
                item.name,
                item.operation,
                item.endpoints,
                item.writes,
                translation.tree(item.activation),
                translation.tree(item.checks),
                tuple((name, translation.tree(value)) for name, value in item.results),
                item.source_path,
            )
            for item in program.effects
        ),
    )


def bind_value_program(
    program: C0SymbolicValueProgram,
    records: Mapping[str, type],
    *,
    intrinsics: Mapping[str, type] | None = None,
) -> C0ValueProgram:
    """Mechanical realization of checked symbols; no parser, checker or evaluator."""
    return bind_value_programs((program,), records, intrinsics=intrinsics)[0]


def bind_value_programs(
    programs: tuple[C0SymbolicValueProgram, ...],
    records: Mapping[str, type],
    *,
    intrinsics: Mapping[str, type] | None = None,
) -> tuple[C0ValueProgram, ...]:
    translation = _ValueSymbolTranslation(records, binding=True, intrinsics=intrinsics)
    return tuple(_bind_value_program(program, translation) for program in programs)


def _bind_value_program(
    program: C0SymbolicValueProgram, translation: _ValueSymbolTranslation
) -> C0ValueProgram:
    return C0ValueProgram(
        C0GuardIR(translation.tree(program.guard), program.clauses, program.source_paths),
        translation.tree(program.tree),
        _check_ports(translation.ports(program.ports)),
        program.admission_outputs,
        tuple(translation.bind_type(item).annotation for item in program.binding_types),
        tuple(
            C0ValueEffectIR(
                item.name,
                item.operation,
                item.endpoints,
                item.writes,
                translation.tree(item.activation),
                translation.tree(item.checks),
                tuple((name, translation.tree(value)) for name, value in item.results),
                item.source_path,
            )
            for item in program.effects
        ),
    )


def symbolize_pure_definitions(
    definitions: tuple[C0PureDefinition, ...], records: Mapping[str, type]
) -> tuple[C0SymbolicPureDefinition, ...]:
    translation = _ValueSymbolTranslation(records, binding=False)
    return tuple(translation.tree(item) for item in definitions)


def bind_pure_definitions(
    definitions: tuple[C0SymbolicPureDefinition, ...], records: Mapping[str, type]
) -> tuple[C0PureDefinition, ...]:
    translation = _ValueSymbolTranslation(records, binding=True)
    return tuple(translation.tree(item) for item in definitions)
