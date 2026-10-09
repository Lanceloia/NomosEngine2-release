"""Build nominal K0 records and replacement owners from a checked Lib declaration."""

from __future__ import annotations

import json
import keyword
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, make_dataclass, replace
from dataclasses import field as dataclass_field
from hashlib import sha256
from typing import get_type_hints

from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OccurrenceContribution

from .appraisal_definition_v1 import C0AppraisalDefinitions
from .author_contract_v1 import C0LawError, _unique_object
from .author_document_v1 import C0AuthorDocument, C0OriginFrame, C0SourceContext, named_source_paths
from .compile_budget_v1 import COMPILE_BUDGET
from .composable_value_v1 import (
    C0ValuePorts,
    C0ValueStateError,
    _complete_record_paths,
    _complete_value_fields,
    compile_value_program,
    verify_pure_definition_types,
)
from .generated_record_v1 import make_nominal_record, seal_nominal_record
from .graph_contracts_v1 import C0GraphObjectKind, C0GraphOwner
from .invariant_execution_v1 import compile_invariant_admission
from .lawdef_binding_v1 import C0LawDefinitions
from .nominal_fields_v1 import _leaf_type
from .nominal_owner_layout_v1 import C0NominalOwnerLayout, bind_nominal_owners
from .nominal_signatures_v1 import (
    C0ActorKindSignature,
    C0NominalField,
    C0NominalFieldType,
    C0NominalSignatures,
    C0ObjectKindSignature,
    C0OwnerSignature,
    C0RecordSignature,
    C0VariantCase,
)
from .nominal_types_v1 import (
    IRValidationError,
    ObjectSortHierarchy,
    ObjectSortRef,
    ObjectSortSpecialization,
    SemanticIdentity,
)
from .nominal_validation_execution_v1 import compile_nominal_validation_block
from .pure_definition_v1 import C0PureDefinition, check_pure_definitions
from .validation_operation_v1 import (
    check_owner_boundary,
    issue_validation_contracts,
    validation_operation,
    wrap_generated_validator,
)
from .value_symbols_v1 import (
    C0SymbolicExpression,
    C0SymbolicPureDefinition,
    bind_pure_definitions,
    bind_value_program,
    symbolize_pure_definitions,
    symbolize_value_program,
)
from .variant_types_v1 import (
    construct_variant,
    validate_variant,
    variant_cases,
    variant_common_fields,
)


@dataclass(frozen=True)
class _TypeSpec:
    kind: str
    annotation: object
    item: _TypeSpec | None = None
    minimum: int = 0
    maximum: int = 0
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FieldSpec:
    name: str
    value: _TypeSpec


@dataclass(frozen=True)
class _DeclaredOwner:
    key: K0OwnerKey
    owner_version: str
    state_type: type
    view_type: type
    contribution_type: type
    local_identity_families: tuple[str, ...] = ()

    def validation_operation(self):
        if type(self) is not _DeclaredOwner or any(
            _DeclaredOwner.__dict__.get(name) is not callback
            for name, callback in _DECLARED_OWNER_OPERATIONS
        ):
            return validation_operation(None, self)
        return validation_operation(self.state_type, self)

    def validate_state(self, state: object) -> None:
        check_owner_boundary(self)
        if type(state) is not self.state_type:
            raise K0ProfileError("declared owner state has the wrong nominal type")
        state.validate_for_k0()

    def read_view(self, state: object) -> object:
        self.validate_state(state)
        return state

    def validate_contribution(self, contribution: object) -> None:
        if (
            type(contribution) is not self.contribution_type
            or contribution.owner != self.key
            or type(contribution.state) is not self.state_type
        ):
            raise K0ProfileError("declared owner contribution has the wrong owner or state")
        contribution.validate_for_k0()

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]:
        if type(contributions) is not tuple or len(contributions) != 1:
            raise K0ProfileError("replace-one owner requires one contribution")
        self.validate_contribution(contributions[0].contribution)
        return contributions

    def apply_contributions(
        self, state: object, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> object:
        self.validate_state(state)
        self.merge_contributions(contributions)
        return contributions[0].contribution.state

    def allocate_local_identity(self, state: object, slot: object, occurrence: object) -> object:
        raise K0ProfileError("declared replace-one owner has no local identity allocator")

    def preserved_occurrences(self, state: object) -> tuple[K0OccurrenceRef, ...]:
        self.validate_state(state)
        return _references(_TypeSpec("record", self.state_type), state)

    def encode_state(self, state: object) -> tuple[object, ...]:
        self.validate_state(state)
        return (self.owner_version, _encode(_TypeSpec("record", self.state_type), state))

    def decode_state(self, wire: object) -> object:
        if type(wire) is not tuple or len(wire) != 2 or wire[0] != self.owner_version:
            raise K0ProfileError("declared owner wire has the wrong version or shape")
        try:
            state = _decode(_TypeSpec("record", self.state_type), wire[1])
        except (AttributeError, TypeError, ValueError) as error:
            raise K0ProfileError("declared owner wire is malformed") from error
        self.validate_state(state)
        return state

_DECLARED_OWNER_OPERATIONS = tuple(
    (name, _DeclaredOwner.__dict__[name])
    for name in (
        "validate_state",
        "read_view",
        "encode_state",
        "decode_state",
    )
)


@dataclass(frozen=True)
class _DeclaredDynamicOwnerFactory:
    capability_ref: _K0CapabilityRef
    owner_version: str
    state_type: type
    contribution_type: type

    def build(self, key: K0OwnerKey) -> _DeclaredOwner:
        return _DeclaredOwner(
            key,
            self.owner_version,
            self.state_type,
            self.state_type,
            self.contribution_type,
        )


@dataclass(frozen=True)
class C0CheckedNominalLib:
    records: tuple[tuple[str, type], ...]
    owners: tuple[C0GraphOwner, ...]
    contribution_type: type
    signatures: C0NominalSignatures
    record_layout: C0NominalRecordLayout
    owner_layout: C0NominalOwnerLayout
    owner_templates: tuple[tuple[str, tuple[str, ...]], ...] = ()
    lawdefs: tuple[str, ...] = ()
    object_kinds: tuple[C0GraphObjectKind, ...] = ()
    pure_definitions: tuple[C0PureDefinition, ...] = ()
    source_context: C0SourceContext | None = None
    pure_source_contexts: tuple[tuple[str, C0SourceContext], ...] = ()
    appraisal_definitions: tuple[str, ...] = dataclass_field(default=(), kw_only=True)

    def check_record_layout(self) -> None:
        self.record_layout.check(self.signatures)
        if self.records != self.record_layout.records or self.pure_definitions != (
            self.record_layout.pure_definitions
        ):
            raise C0LawError("nominal Lib substituted its generated record bindings")
        self.owner_layout.check(self.signatures)
        if (
            self.owner_layout.record_layout is not self.record_layout
            or self.owners != self.owner_layout.owners
            or self.object_kinds != self.owner_layout.object_kinds
            or self.contribution_type is not self.owner_layout.contribution_type
        ):
            raise C0LawError("nominal Lib substituted its generated owner bindings")

    def record(self, name: str) -> type:
        for symbol, carrier in self.records:
            if symbol == name:
                return carrier
        raise C0LawError("Lib record is not declared")

    @property
    def actor_kinds(self):
        return self.owner_layout.actor_kinds

    def attributed_pure_definitions(self) -> tuple[C0PureDefinition, ...]:
        """Attach compile locations without altering the generated nominal signatures."""
        contexts = dict(self.pure_source_contexts)
        return tuple(
            replace(item, source_context=contexts.get(item.name)) for item in self.pure_definitions
        )

    def owner(self, symbol: str) -> C0GraphOwner:
        for item in self.owners:
            if item.symbol == symbol:
                return item
        raise C0LawError("Lib owner is not declared")


@dataclass(frozen=True, init=False)
class C0NominalRecordLayout:
    """Generated backend bindings, not a qualification of arbitrary native types."""

    signatures: C0NominalSignatures
    records: tuple[tuple[str, type], ...]
    pure_definitions: tuple[C0PureDefinition, ...]
    _fields: tuple[tuple[_FieldSpec, ...], ...]
    _validators: tuple[Callable[[object], None], ...]
    _invariants: tuple[object, ...]

    def __init__(self, *args, **kwargs) -> None:
        raise C0LawError("nominal layouts must be generated from checked signatures")

    def record(self, symbol: str) -> type:
        for name, carrier in self.records:
            if name == symbol:
                return carrier
        raise C0LawError("nominal layout record is not declared")

    def check(self, signatures: C0NominalSignatures) -> None:
        if (
            signatures is not self.signatures
            or tuple(name for name, _ in self.records)
            != tuple(item.symbol for item in signatures.records)
            or len({carrier for _, carrier in self.records}) != len(self.records)
            or any(
                len(items) != len(self.records)
                for items in (
                    self._fields,
                    self._validators,
                    self._invariants,
                )
            )
        ):
            raise C0LawError("nominal layout does not implement the selected signatures")
        for (_, carrier), declared, validator, invariant in zip(
            self.records, self._fields, self._validators, self._invariants, strict=True
        ):
            # Generated carriers have resolved annotations; recheck them, not a cached proof.
            if (
                getattr(carrier, "validate_for_k0", None) is not validator
                or getattr(carrier, "__nomos_fields__", None) != declared
                or getattr(carrier, "__nomos_invariant__", None) is not invariant
                or carrier.__bases__ != (object,)
                or getattr(carrier, "__annotations__", None)
                != {item.name: item.value.annotation for item in declared}
            ):
                raise C0LawError("nominal layout carrier or generated validator was replaced")
        names = {carrier: symbol for symbol, carrier in self.records}
        for signature, declared, (_, carrier) in zip(
            signatures.records, self._fields, self.records, strict=True
        ):
            if (
                not isinstance(signature.fields, tuple)
                or len(signature.fields) != len(declared)
                or any(
                    type(field) is not C0NominalField
                    or field.name != item.name
                    or not _realizes_field(item.value, field.value, names)
                    for field, item in zip(signature.fields, declared, strict=True)
                )
            ):
                raise C0LawError("nominal layout fields do not realize the selected signature")
            if signature.cases != _case_signatures(carrier, names):
                raise C0LawError("nominal layout variant cases do not realize the signature")


def _realizes_field(spec: _TypeSpec, field: C0NominalFieldType, names: dict[type, str]) -> bool:
    # Compare current metadata without allocating a second symbolic declaration tree.
    return (
        type(field) is C0NominalFieldType
        and spec.kind == field.kind
        and (names[spec.annotation] if spec.kind in ("record", "variant") else "") == field.record
        and spec.minimum == field.minimum
        and spec.maximum == field.maximum
        and spec.choices == field.choices
        and (
            field.item is None
            if spec.item is None
            else field.item is not None and _realizes_field(spec.item, field.item, names)
        )
    )


def _symbolic_field(spec: _TypeSpec, names: dict[type, str]) -> C0NominalFieldType:
    return C0NominalFieldType(
        spec.kind,
        names[spec.annotation] if spec.kind in ("record", "variant") else "",
        _symbolic_field(spec.item, names) if spec.item is not None else None,
        spec.minimum,
        spec.maximum,
        spec.choices,
    )


def _case_signatures(carrier: type, names: dict[type, str]) -> tuple[C0VariantCase, ...]:
    fields_by_name = {item.name: item.value for item in carrier.__nomos_fields__}
    return tuple(
        C0VariantCase(
            name,
            None if annotation is type(None) else _symbolic_field(fields_by_name[name].item, names),
        )
        for name, annotation in variant_cases(carrier).items()
    )


def _nominal_signatures(
    records: dict[str, type], pure_definitions: tuple[C0PureDefinition, ...]
) -> C0NominalSignatures:
    names = {carrier: name for name, carrier in records.items()}
    return C0NominalSignatures(
        tuple(
            C0RecordSignature(
                name,
                tuple(
                    C0NominalField(item.name, _symbolic_field(item.value, names))
                    for item in carrier.__nomos_fields__
                ),
                None
                if carrier.__nomos_invariant__ is None
                else symbolize_value_program(carrier.__nomos_invariant__, records),
                _case_signatures(carrier, names),
            )
            for name, carrier in records.items()
        ),
        symbolize_pure_definitions(pure_definitions, records),
    )


def _invariant_pure_names(signatures: C0NominalSignatures) -> frozenset[str]:
    used: set[str] = set()
    seen: set[int] = set()

    def visit(node: object) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        if type(node) is C0SymbolicPureDefinition:
            used.add(node.name)
        elif type(node) is C0SymbolicExpression:
            visit(node.operand)
        elif isinstance(node, Mapping):
            for item in node.values():
                visit(item)
        elif type(node) is tuple:
            for item in node:
                visit(item)

    for record in signatures.records:
        if record.invariant is not None:
            visit(record.invariant.guard)
            visit(record.invariant.tree)
    return frozenset(used)


def bind_nominal_records(signatures: C0NominalSignatures) -> C0NominalRecordLayout:
    """Realize the checked signature again, without Source or frontend checks."""
    compiled: dict[str, type] = {}
    declared_fields: dict[str, tuple[_FieldSpec, ...]] = {}
    validators: dict[str, Callable[[object], None]] = {}
    invariant_installers: dict[str, Callable] = {}
    invariants: dict[str, object] = {}
    visiting: set[str] = set()

    def bind_field(spec: C0NominalFieldType) -> _TypeSpec:
        annotations = {
            "bool": bool,
            "str": str,
            "int": int,
            "enum": str,
            "ref": K0OccurrenceRef,
            "individual_ref": _K0IndividualRef,
            "actor_ref": _K0ActorRef,
        }
        if spec.kind in ("record", "variant"):
            annotation = build(spec.record)
            if (spec.kind == "variant") != bool(variant_cases(annotation)):
                raise C0LawError("nominal field record/variant kind differs from its declaration")
        elif spec.kind in ("optional", "tuple") and spec.item is not None:
            item = bind_field(spec.item)
            annotation = (
                item.annotation | None if spec.kind == "optional" else tuple[item.annotation, ...]
            )
            return _TypeSpec(spec.kind, annotation, item, spec.minimum, spec.maximum, spec.choices)
        elif spec.kind in annotations:
            annotation = annotations[spec.kind]
        else:
            raise C0LawError("nominal field signature has no backend realization")
        return _TypeSpec(spec.kind, annotation, None, spec.minimum, spec.maximum, spec.choices)

    def build(name: str) -> type:
        if name in compiled:
            return compiled[name]
        if name in visiting:
            raise C0LawError("nominal signature records are recursive")
        visiting.add(name)
        signature = signatures.record(name)
        declared = tuple(_FieldSpec(item.name, bind_field(item.value)) for item in signature.fields)
        cases = tuple(
            (item.name, type(None) if item.payload is None else bind_field(item.payload).annotation)
            for item in signature.cases
        )
        carrier = make_nominal_record(
            name,
            [(item.name, item.value.annotation) for item in declared],
            namespace={},
        )
        carrier.__nomos_fields__ = declared
        carrier.__nomos_invariant__ = None
        carrier.__nomos_cases__ = cases
        validate, bind_invariant = compile_nominal_validation_block(
            carrier, declared, _compile_value_validator
        )

        def install_invariant(invariant):
            bind_invariant(None if invariant is None else compile_invariant_admission(invariant))

        validate = wrap_generated_validator(carrier, validate)
        carrier.validate_for_k0 = validate
        compiled[name] = carrier
        declared_fields[name] = declared
        validators[name] = validate
        invariant_installers[name] = install_invariant
        visiting.remove(name)
        return carrier

    for signature in signatures.records:
        build(signature.symbol)
    for signature in signatures.records:
        invariant = (
            None
            if signature.invariant is None
            else bind_value_program(signature.invariant, compiled)
        )
        invariants[signature.symbol] = invariant
        invariant_installers[signature.symbol](invariant)
        compiled[signature.symbol].__nomos_invariant__ = invariant
    # Assembly callbacks never enter the published layout or validator closures.
    invariant_installers.clear()
    issue_validation_contracts(
        tuple(compiled.values()), (K0OccurrenceRef, _K0IndividualRef, _K0ActorRef)
    )
    for carrier in compiled.values():
        seal_nominal_record(carrier)
    names = tuple(item.symbol for item in signatures.records)
    # Only this generator issues a layout; native validators cannot self-qualify.
    layout = object.__new__(C0NominalRecordLayout)
    generated = {
        "signatures": signatures,
        "records": tuple((name, compiled[name]) for name in names),
        "pure_definitions": bind_pure_definitions(signatures.pure_definitions, compiled),
        "_fields": tuple(declared_fields[name] for name in names),
        "_validators": tuple(validators[name] for name in names),
        "_invariants": tuple(invariants[name] for name in names),
    }
    for field, value in generated.items():
        object.__setattr__(layout, field, value)
    layout.check(signatures)
    return layout


def _object_contribution_type(carrier: type) -> type:
    def validate_contribution(value: object) -> None:
        if type(value.owner) is not K0OwnerKey or type(value.state) is not carrier:
            raise K0ProfileError("declared Object contribution has a foreign owner or state")
        value.state.validate_for_k0()

    return seal_nominal_record(
        make_nominal_record(
            f"{carrier.__name__}ObjectContribution",
            [("owner", K0OwnerKey), ("state", carrier)],
            namespace={"validate_for_k0": validate_contribution},
        )
    )


def _name(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.isidentifier()
        or keyword.iskeyword(value)
        or value.startswith("_")
        or len(value) > 64
    ):
        raise C0LawError(f"{label} must be a finite public identifier")
    return value


def _row(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise C0LawError(f"{label} has missing or unknown fields")
    return value


def _compile_value_validator(spec: _TypeSpec) -> Callable[[object], None]:
    """Specialize immutable field metadata, never cache validation of a value."""
    if spec.kind == "optional":
        validate_item = _compile_value_validator(spec.item)

        def validate(value: object) -> None:
            if value is not None:
                validate_item(value)

    elif spec.kind == "tuple":
        validate_item = _compile_value_validator(spec.item)
        maximum = spec.maximum

        def validate(value: object) -> None:
            if type(value) is not tuple or len(value) > maximum:
                raise K0ProfileError("declared collection is malformed or too large")
            for item in value:
                validate_item(item)

    elif spec.kind in ("str", "int"):
        carrier = str if spec.kind == "str" else int
        minimum, maximum = spec.minimum, spec.maximum
        if carrier is str:

            def validate(value: object) -> None:
                if type(value) is not str or not minimum <= len(value) <= maximum:
                    raise K0ProfileError("declared nominal value is malformed")

        else:

            def validate(value: object) -> None:
                if type(value) is not int or not minimum <= value <= maximum:
                    raise K0ProfileError("declared nominal value is malformed")

    elif spec.kind == "enum":
        choices = frozenset(spec.choices)

        def validate(value: object) -> None:
            if type(value) is not str or value not in choices:
                raise K0ProfileError("declared nominal value is malformed")

    elif spec.kind == "bool":

        def validate(value: object) -> None:
            if type(value) is not bool:
                raise K0ProfileError("declared nominal value is malformed")

    elif spec.kind in ("ref", "individual_ref", "actor_ref"):
        carrier = {
            "ref": K0OccurrenceRef,
            "individual_ref": _K0IndividualRef,
            "actor_ref": _K0ActorRef,
        }[spec.kind]

        def validate(value: object) -> None:
            if type(value) is not carrier:
                raise K0ProfileError("declared nominal value is malformed")
            carrier.__post_init__(value)

    else:
        carrier = spec.annotation

        def validate(value: object) -> None:
            if type(value) is not carrier:
                raise K0ProfileError("declared nominal value is malformed")
            value.validate_for_k0()

    return validate


def _value(spec: _TypeSpec, value: object) -> None:
    if spec.kind == "str":
        valid = type(value) is str and spec.minimum <= len(value) <= spec.maximum
    elif spec.kind == "enum":
        valid = type(value) is str and value in spec.choices
    elif spec.kind == "int":
        valid = type(value) is int and spec.minimum <= value <= spec.maximum
    elif spec.kind == "bool":
        valid = type(value) is bool
    elif spec.kind == "ref":
        valid = type(value) is K0OccurrenceRef
        if valid:
            K0OccurrenceRef.__post_init__(value)
    elif spec.kind == "individual_ref":
        valid = type(value) is _K0IndividualRef
        if valid:
            _K0IndividualRef.__post_init__(value)
    elif spec.kind == "actor_ref":
        valid = type(value) is _K0ActorRef
        if valid:
            _K0ActorRef.__post_init__(value)
    elif spec.kind == "optional":
        if value is None:
            return
        _value(spec.item, value)
        return
    elif spec.kind == "tuple":
        if type(value) is not tuple or len(value) > spec.maximum:
            raise K0ProfileError("declared collection is malformed or too large")
        for item in value:
            _value(spec.item, item)
        return
    else:
        valid = type(value) is spec.annotation
        if valid:
            value.validate_for_k0()
    if not valid:
        raise K0ProfileError("declared nominal value is malformed")


def _validate_record(value: object) -> None:
    for item in type(value).__nomos_fields__:
        _value(item.value, getattr(value, item.name))
    validate_variant(value)
    invariant = type(value).__nomos_invariant__
    if invariant is not None:
        try:
            if not invariant.admits({"state": value}):
                raise K0ProfileError("declared state invariant is false")
        except C0ValueStateError as error:
            raise K0ProfileError("declared state invariant met malformed state") from error


def _references(spec: _TypeSpec, value: object) -> tuple[K0OccurrenceRef, ...]:
    if spec.kind == "ref":
        return (value,)
    if spec.kind == "optional":
        return () if value is None else _references(spec.item, value)
    if spec.kind == "tuple":
        return tuple(ref for item in value for ref in _references(spec.item, item))
    if spec.kind in ("record", "variant"):
        return tuple(
            ref
            for field in spec.annotation.__nomos_fields__
            for ref in _references(field.value, getattr(value, field.name))
        )
    return ()


def _encode(spec: _TypeSpec, value: object) -> object:
    if spec.kind == "ref":
        return value.value
    if spec.kind in ("individual_ref", "actor_ref"):
        return (value.scope, value.ordinal, value.family)
    if spec.kind == "optional":
        return None if value is None else _encode(spec.item, value)
    if spec.kind == "tuple":
        return tuple(_encode(spec.item, item) for item in value)
    if spec.kind in ("record", "variant"):
        if variant_cases(spec.annotation):
            definitions = {field.name: field.value for field in spec.annotation.__nomos_fields__}
            payload_type = definitions.get(value.case)
            return (
                value.case,
                None
                if payload_type is None
                else _encode(payload_type.item, getattr(value, value.case)),
                tuple(
                    _encode(definitions[name], getattr(value, name))
                    for name in variant_common_fields(spec.annotation)
                ),
            )
        return tuple(
            _encode(field.value, getattr(value, field.name))
            for field in spec.annotation.__nomos_fields__
        )
    return value


def _decode(spec: _TypeSpec, wire: object) -> object:
    if spec.kind == "ref":
        if type(wire) is not int:
            raise K0ProfileError("declared occurrence wire is malformed")
        return K0OccurrenceRef(wire)
    if spec.kind in ("individual_ref", "actor_ref"):
        if (
            type(wire) is not tuple
            or len(wire) != 3
            or type(wire[0]) is not str
            or type(wire[1]) is not int
            or type(wire[2]) is not str
        ):
            raise K0ProfileError("declared individual wire is malformed")
        return (_K0IndividualRef if spec.kind == "individual_ref" else _K0ActorRef)(*wire)
    if spec.kind == "optional":
        return None if wire is None else _decode(spec.item, wire)
    if spec.kind == "tuple":
        if type(wire) is not tuple or len(wire) > spec.maximum:
            raise K0ProfileError("declared collection wire is malformed")
        return tuple(_decode(spec.item, item) for item in wire)
    if spec.kind in ("record", "variant"):
        cases = variant_cases(spec.annotation)
        if cases:
            common = variant_common_fields(spec.annotation)
            if (
                type(wire) is not tuple
                or len(wire) != 3
                or type(wire[0]) is not str
                or wire[0] not in cases
                or type(wire[2]) is not tuple
                or len(wire[2]) != len(common)
            ):
                raise K0ProfileError("declared variant wire is malformed")
            definitions = {field.name: field.value for field in spec.annotation.__nomos_fields__}
            payload_type = definitions.get(wire[0])
            if payload_type is None and wire[1] is not None:
                raise K0ProfileError("unit variant wire must have no payload")
            payload = None if payload_type is None else _decode(payload_type.item, wire[1])
            return construct_variant(
                spec.annotation,
                wire[0],
                payload,
                {
                    name: _decode(definitions[name], item)
                    for name, item in zip(common, wire[2], strict=True)
                },
            )
        definitions = spec.annotation.__nomos_fields__
        if type(wire) is not tuple or len(wire) != len(definitions):
            raise K0ProfileError("declared record wire is malformed")
        result = spec.annotation(
            *(_decode(field.value, item) for field, item in zip(definitions, wire, strict=True))
        )
        result.validate_for_k0()
        return result
    _value(spec, wire)
    return wire


def _type_spec(
    raw: object,
    definitions: dict[str, dict[str, object]],
    compile_record: Callable[[str], type],
    depth: int = 0,
) -> _TypeSpec:
    if depth > 12:
        raise C0LawError("Lib type nesting is too deep")
    if type(raw) is str:
        if raw == "bool":
            return _TypeSpec("bool", bool)
        if raw == "occurrence_ref":
            return _TypeSpec("ref", K0OccurrenceRef)
        if raw == "individual_ref":
            return _TypeSpec("individual_ref", _K0IndividualRef)
        if raw == "actor_ref":
            return _TypeSpec("actor_ref", _K0ActorRef)
        if raw in definitions:
            return _TypeSpec(
                "variant" if "variants" in definitions[raw] else "record", compile_record(raw)
            )
        raise C0LawError("Lib field has an unknown type")
    if type(raw) is not dict or len(raw) != 1:
        raise C0LawError("Lib type expression is malformed")
    kind, argument = next(iter(raw.items()))
    if kind in ("str", "int"):
        if (
            type(argument) is not list
            or len(argument) != 2
            or any(type(bound) is not int for bound in argument)
            or not 0 <= argument[0] <= argument[1] <= (1 << 63) - 1
            or (kind == "str" and argument[0] == 0)
        ):
            raise C0LawError("Lib scalar range is malformed")
        return _TypeSpec(
            kind, str if kind == "str" else int, minimum=argument[0], maximum=argument[1]
        )
    if kind == "enum":
        if (
            type(argument) is not list
            or not 1 <= len(argument) <= 64
            or any(type(item) is not str or not item or len(item) > 64 for item in argument)
            or len(argument) != len(set(argument))
        ):
            raise C0LawError("Lib enum is malformed")
        return _TypeSpec("enum", str, choices=tuple(argument))
    if kind == "optional":
        item = _type_spec(argument, definitions, compile_record, depth + 1)
        if item.kind == "optional":
            raise C0LawError("Lib nested optional is redundant")
        return _TypeSpec("optional", item.annotation | None, item=item)
    if kind == "tuple":
        row = _row(argument, {"item", "max"}, "Lib collection")
        if type(row["max"]) is not int or not 1 <= row["max"] <= 256:
            raise C0LawError("Lib collection needs a finite bound")
        item = _type_spec(row["item"], definitions, compile_record, depth + 1)
        return _TypeSpec("tuple", tuple[item.annotation, ...], item=item, maximum=row["max"])
    raise C0LawError("Lib type operation is unknown")


def _invariant(
    carrier: type, expression: object, pure_definitions=(), *, source_context=None
) -> object:
    names = frozenset(field.name for field in fields(carrier))
    paths = _complete_record_paths("state", carrier)
    readable: dict[type, set[str]] = {carrier: set(names)}
    for field in fields(carrier):
        for record, selected in _complete_value_fields(get_type_hints(carrier)[field.name]).items():
            readable.setdefault(record, set()).update(selected)
    field_ports = {record: frozenset(selected) for record, selected in readable.items()}
    ports = C0ValuePorts(
        roots={"state": carrier},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=field_ports,
        admission_readable_fields=field_ports,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"valid": bool},
        pure_definitions=pure_definitions,
        source_context=source_context,
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": expression,
        "outputs": {"valid": {"const": True}},
    }
    return compile_value_program(json.dumps(source), ports)


def check_nominal_lib(
    source: str | dict[str, object] | C0AuthorDocument, owner_domains: object = None
) -> C0CheckedNominalLib:
    """Compile data-only nominal declarations to closed records and K0 owner adapters."""
    source_context = source.context() if type(source) is C0AuthorDocument else None
    if type(source) is C0AuthorDocument:
        source = source.to_data()
    if type(source) is str:
        if not source or len(source) > 262144:
            raise C0LawError("Lib source is empty or too large")
        try:
            source = json.loads(source, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError) as error:
            raise C0LawError("Lib source is malformed JSON") from error
    if type(source) is not dict:
        raise C0LawError("Lib has missing or unknown fields")
    row = _row(
        source,
        {"schema", "records", "owners"}
        | ({"lawdefs"} if "lawdefs" in source else set())
        | ({"object_kinds"} if "object_kinds" in source else set())
        | ({"actor_kinds"} if "actor_kinds" in source else set())
        | ({"pure_definitions"} if "pure_definitions" in source else set())
        | ({"appraisal_definitions"} if "appraisal_definitions" in source else set()),
        "Lib",
    )
    if row["schema"] != "c0.nominal_lib.v1":
        raise C0LawError("Lib schema is unknown")
    try:
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if type(row["owners"]) is not list or any(type(item) is not dict for item in row["owners"]):
            raise C0LawError("Lib owners must be a finite declaration list")
        # Storage addresses are layout, not part of the nominal validation contract.
        semantic_owners = [
            {key: value for key, value in item.items() if key not in ("key", "key_prefix")}
            for item in row["owners"]
        ]
        nominal = json.dumps(
            {
                key: semantic_owners if key == "owners" else row[key]
                for key in ("schema", "records", "owners", "object_kinds", "actor_kinds")
                if key in row
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise C0LawError("Lib declaration is not finite JSON data") from error
    if len(canonical) > 262144:
        raise C0LawError("Lib declaration is too large")
    fingerprint = sha256(nominal.encode("utf-8")).hexdigest()[:16]
    lawdefs = row.get("lawdefs", [])
    if type(lawdefs) is not list:
        raise C0LawError("Lib LawDefs must be a finite list")
    COMPILE_BUDGET.check("law_definitions", len(lawdefs), stage="Lib declarations")
    if lawdefs:
        C0LawDefinitions(lawdefs)
    appraisal_definitions = row.get("appraisal_definitions", [])
    C0AppraisalDefinitions(appraisal_definitions)
    records = row["records"]
    owners = row["owners"]
    if (
        type(records) is not list
        or len(records) < 1
        or type(owners) is not list
        or not 1 <= len(owners) <= 64
    ):
        raise C0LawError("Lib needs finite record and owner declarations")
    COMPILE_BUDGET.check("nominal_records", len(records), stage="Lib declarations")
    definitions: dict[str, dict[str, object]] = {}
    for raw in records:
        item = _row(
            raw,
            {"name", "fields", "invariant"}
            | ({"variants"} if type(raw) is dict and "variants" in raw else set()),
            "Lib nominal declaration",
        )
        name = _name(item["name"], "Lib record name")
        if name in {
            "bool",
            "int",
            "str",
            "enum",
            "optional",
            "tuple",
            "none",
            "occurrence_ref",
            "individual_ref",
            "actor_ref",
        }:
            raise C0LawError("Lib record name collides with a built-in type")
        if name in definitions:
            raise C0LawError("Lib record names alias")
        definitions[name] = item
    compiled: dict[str, type] = {}
    visiting: set[str] = set()

    def compile_record(name: str) -> type:
        if name in compiled:
            return compiled[name]
        if name in visiting:
            raise C0LawError("Lib record types are recursive")
        visiting.add(name)
        raw_fields = definitions[name]["fields"]
        raw_cases = definitions[name].get("variants", {})
        if "variants" in definitions[name] and (
            type(raw_cases) is not dict or not 2 <= len(raw_cases) <= 32
        ):
            raise C0LawError("Lib variant needs 2..32 distinct cases")
        if type(raw_fields) is not list or not (0 if raw_cases else 1) <= len(raw_fields) <= 64:
            raise C0LawError("Lib record needs finite fields")
        declared = []
        seen = set()
        for raw_field in raw_fields:
            field = _row(raw_field, {"name", "type"}, "Lib record field")
            field_name = _name(field["name"], "Lib field name")
            if field_name in seen or field_name == "validate_for_k0":
                raise C0LawError("Lib record fields alias")
            seen.add(field_name)
            declared.append(
                _FieldSpec(field_name, _type_spec(field["type"], definitions, compile_record))
            )
        cases = []
        if raw_cases:
            if "case" in seen:
                raise C0LawError("variant common fields collide with the discriminator")
            declared.append(_FieldSpec("case", _TypeSpec("enum", str, choices=tuple(raw_cases))))
            for case, raw_type in raw_cases.items():
                _name(case, "variant case")
                if case in seen or case in ("case", "validate_for_k0"):
                    raise C0LawError("variant cases collide with common fields")
                if raw_type == "none":
                    cases.append((case, type(None)))
                    continue
                payload = _type_spec(raw_type, definitions, compile_record)
                if payload.kind == "optional":
                    raise C0LawError("variant payload cannot be optional; use a unit case")
                cases.append((case, payload.annotation))
                declared.append(
                    _FieldSpec(case, _TypeSpec("optional", payload.annotation | None, item=payload))
                )
        carrier = make_dataclass(
            name,
            [(item.name, item.value.annotation) for item in declared],
            frozen=True,
            slots=True,
            namespace={"validate_for_k0": _validate_record},
        )
        carrier.__nomos_fields__ = tuple(declared)
        carrier.__nomos_invariant__ = None
        carrier.__nomos_cases__ = tuple(cases)
        compiled[name] = carrier
        visiting.remove(name)
        return carrier

    for name in definitions:
        compile_record(name)

    # Signatures need the complete nominal table before any body or invariant check.
    pure_definitions = check_pure_definitions(row.get("pure_definitions", []), compiled)
    verify_pure_definition_types(pure_definitions, compiled)
    pure_contexts = (
        tuple(
            (
                item["name"],
                named_source_paths(
                    source_context.at(
                        ("pure_definitions", index, "body"),
                        root=f"pure_definitions.{item['name']}.body",
                    ),
                    item["body"],
                    root=f"pure_definitions.{item['name']}.body",
                ),
            )
            for index, item in enumerate(row.get("pure_definitions", []))
        )
        if source_context is not None
        else ()
    )
    located_definitions = tuple(
        replace(item, source_context=dict(pure_contexts).get(item.name))
        for item in pure_definitions
    )
    record_positions = {item["name"]: index for index, item in enumerate(records)}
    for name, carrier in compiled.items():
        expression = definitions[name]["invariant"]
        if expression is not None:
            context = None
            if source_context is not None:
                path = ("records", record_positions[name], "invariant")
                context = C0SourceContext(
                    source_context.index,
                    (("guard", path),),
                    (
                        C0OriginFrame(
                            "record_invariant",
                            name,
                            repr(path),
                            source_context.index.spans.get(path),
                        ),
                    ),
                )
            carrier.__nomos_invariant__ = _invariant(
                carrier, expression, located_definitions, source_context=context
            )

    # Frontend-only carriers check declarations; production layouts are generated below.
    signatures = _nominal_signatures(compiled, pure_definitions)
    validation_calls = _invariant_pure_names(signatures)
    if validation_calls:
        validation_definitions = [
            item
            for item in sorted(row.get("pure_definitions", []), key=lambda item: item["name"])
            if item["name"] in validation_calls
        ]
        fingerprint = sha256(
            json.dumps(
                {"nominal": json.loads(nominal), "validation_pure": validation_definitions},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]

    object_signatures = []
    object_symbols = set()
    object_sorts = set()
    raw_kinds = row.get("object_kinds", [])
    if type(raw_kinds) is not list or len(raw_kinds) > 64:
        raise C0LawError("Lib Object kinds are not a finite list")
    for raw in raw_kinds:
        item = _row(
            raw,
            {"symbol", "sort", "state", "version", "max_instances"}
            | ({"specializes"} if type(raw) is dict and "specializes" in raw else set()),
            "Lib Object kind",
        )
        symbol = _name(item["symbol"], "Lib Object kind symbol")
        state = item["state"]
        version = item["version"]
        maximum = item["max_instances"]
        if (
            symbol in object_symbols
            or type(state) is not str
            or state not in compiled
            or type(version) is not str
            or not version
            or version != version.strip()
            or len(version) > 128
            or type(maximum) is not int
            or not 1 <= maximum <= 256
        ):
            raise C0LawError("Lib Object kind has malformed identity or state")
        try:
            sort = ObjectSortRef(SemanticIdentity(item["sort"]))
        except (IRValidationError, TypeError) as error:
            raise C0LawError("Lib Object sort is malformed") from error
        if sort in object_sorts:
            raise C0LawError("Lib Object sorts alias")
        object_symbols.add(symbol)
        object_sorts.add(sort)
        parents = item.get("specializes", [])
        if type(parents) is not list or len(parents) > 64:
            raise C0LawError("Lib Object specialization is malformed")
        try:
            parent_sorts = tuple(ObjectSortRef(SemanticIdentity(parent)) for parent in parents)
        except (IRValidationError, TypeError) as error:
            raise C0LawError("Lib Object specialization is malformed") from error
        object_signatures.append(
            C0ObjectKindSignature(
                symbol,
                sort.identity.value,
                state,
                f"{version}:{fingerprint}",
                maximum,
                tuple(parent.identity.value for parent in parent_sorts),
            )
        )

    if object_signatures:
        try:
            ObjectSortHierarchy(
                tuple(sorted(object_sorts)),
                tuple(
                    sorted(
                        ObjectSortSpecialization(
                            ObjectSortRef(SemanticIdentity(item.sort)),
                            ObjectSortRef(SemanticIdentity(parent)),
                        )
                        for item in object_signatures
                        for parent in item.specializes
                    )
                ),
            )
        except IRValidationError as error:
            raise C0LawError("Lib Object specialization is not closed") from error

    actor_signatures = []
    raw_actor_kinds = row.get("actor_kinds", [])
    if type(raw_actor_kinds) is not list or len(raw_actor_kinds) > 64:
        raise C0LawError("Lib Actor kinds must be finite")
    for raw in raw_actor_kinds:
        item = _row(
            raw, {"symbol", "state", "version", "max_instances", "seat_read"}, "Lib Actor kind"
        )
        symbol = _name(item["symbol"], "Lib Actor kind symbol")
        state, version, maximum, read = (
            item[key] for key in ("state", "version", "max_instances", "seat_read")
        )
        if (
            symbol in object_symbols
            or any(a.symbol == symbol for a in actor_signatures)
            or type(state) is not str
            or state not in compiled
            or type(version) is not str
            or not version
            or version != version.strip()
            or len(version) > 128
            or type(maximum) is not int
            or not 1 <= maximum <= 256
            or type(read) is not list
            or len(read) > 128
            or any(
                type(path) is not str or _leaf_type(compiled[state], path) is None for path in read
            )
            or len(read) != len(set(read))
        ):
            raise C0LawError("Lib Actor kind has invalid state, capacity or local read ports")
        actor_signatures.append(
            C0ActorKindSignature(
                symbol, state, f"{version}:{fingerprint}", maximum, frozenset(read)
            )
        )
    if type(row.get("actor_kinds", [])) is not list or len(actor_signatures) > 64:
        raise C0LawError("Lib Actor kinds must be finite")

    bindings: dict[str, tuple[str, ...]] = {}
    if owner_domains is not None:
        if type(owner_domains) is not list or len(owner_domains) > 64:
            raise C0LawError("Source owner domains are malformed")
        for raw_domain in owner_domains:
            if type(raw_domain) is not dict:
                raise C0LawError("Source owner domain is malformed")
            template = raw_domain.get("owner_template")
            if template is None:
                continue
            template = _name(template, "Source owner template")
            members = raw_domain.get("owners")
            if (
                template in bindings
                or type(members) is not list
                or not 1 <= len(members) <= 64
                or any(type(member) is not str for member in members)
            ):
                raise C0LawError("Source owner template binding is malformed")
            bindings[template] = tuple(_name(member, "Source owner instance") for member in members)

    owner_rows: list[tuple[C0OwnerSignature, K0OwnerKey]] = []
    symbols: set[str] = set()
    keys: set[K0OwnerKey] = set()
    template_names: set[str] = set()
    for raw in owners:
        if type(raw) is not dict:
            raise C0LawError("Lib owner is malformed")
        templated = "template" in raw
        item = _row(
            raw,
            {
                "template" if templated else "symbol",
                "key_prefix" if templated else "key",
                "version",
                "state",
                "identity_field",
                "seat_read",
                "write",
            },
            "Lib owner",
        )
        symbol = _name(item["template" if templated else "symbol"], "Lib owner symbol")
        if item["write"] != "replace_one":
            raise C0LawError("Lib owner write strategy is not supported")
        if (
            type(item["key_prefix" if templated else "key"]) is not str
            or type(item["version"]) is not str
            or not item["version"]
            or item["version"] != item["version"].strip()
            or len(item["version"]) > 128
            or type(item["state"]) is not str
            or item["state"] not in compiled
        ):
            raise C0LawError("Lib owner identity or state is malformed")
        carrier = compiled[item["state"]]
        identity = item["identity_field"]
        if identity is not None and (
            type(identity) is not str or get_type_hints(carrier).get(identity) is not str
        ):
            raise C0LawError("Lib Actor identity field is not a string")
        read = item["seat_read"]
        if (
            type(read) is not list
            or len(read) > 128
            or any(type(path) is not str or _leaf_type(carrier, path) is None for path in read)
            or len(read) != len(set(read))
        ):
            raise C0LawError("Lib owner seat read paths are malformed")
        if templated:
            if symbol in template_names or symbol in symbols:
                raise C0LawError("Lib owner templates alias")
            template_names.add(symbol)
            members = bindings.get(symbol)
            if members is None or len(members) != len(set(members)) or identity is None:
                raise C0LawError("Lib Actor template needs distinct Source instances")
            instances = ((member, f"{item['key_prefix']}{member}") for member in members)
        else:
            instances = ((symbol, item["key"]),)
        for instance, raw_key in instances:
            try:
                key = K0OwnerKey(raw_key)
            except K0ProfileError as error:
                raise C0LawError("Lib owner key is malformed") from error
            if instance in symbols or instance in template_names or key in keys:
                raise C0LawError("Lib owner symbols or keys alias")
            symbols.add(instance)
            keys.add(key)
            owner_rows.append(
                (
                    C0OwnerSignature(
                        instance,
                        f"{item['version']}:{fingerprint}",
                        item["state"],
                        identity,
                        frozenset(read),
                    ),
                    key,
                )
            )

    if set(bindings) != template_names:
        raise C0LawError("Source owner template binding does not match Lib")
    if len(owner_rows) > 64:
        raise C0LawError("Lib and Source exceed the finite owner limit")

    signatures = C0NominalSignatures(
        signatures.records,
        signatures.pure_definitions,
        tuple(item for item, _ in owner_rows),
        tuple(object_signatures),
        tuple(actor_signatures),
    )
    record_layout = bind_nominal_records(signatures)
    owner_layout = bind_nominal_owners(
        signatures, record_layout, {item.symbol: key for item, key in owner_rows}
    )
    return C0CheckedNominalLib(
        record_layout.records,
        owner_layout.owners,
        owner_layout.contribution_type,
        signatures,
        record_layout,
        owner_layout,
        tuple((name, bindings[name]) for name in sorted(template_names)),
        tuple(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in lawdefs),
        owner_layout.object_kinds,
        record_layout.pure_definitions,
        source_context,
        pure_contexts,
        appraisal_definitions=tuple(
            json.dumps(item, sort_keys=True, separators=(",", ":"))
            for item in appraisal_definitions
        ),
    )
