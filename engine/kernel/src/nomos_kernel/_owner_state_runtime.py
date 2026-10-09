"""Owner-state isolation, view construction and topology validation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import _FIELD, dataclass, is_dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from types import MappingProxyType, MemberDescriptorType
from typing import Protocol

from nomos_kernel import K0OwnerKey, K0ProfileError
from nomos_kernel._admission_abi import (
    _K0RuntimePropositionInvariant,
    _K0RuntimePropositionState,
)
from nomos_kernel._canonical_wire import _canonical_wire
from nomos_kernel._occurrence_record_abi import (
    _K0OccurrenceCursorValidator,
    _K0OccurrenceRecordView,
)
from nomos_kernel._owner_abi import (
    _K0CrossOwnerInvariant,
    _K0Owner,
    _K0OwnerView,
    _K0ReadOnlyOwnerView,
    _K0ValidationOperationOwner,
    _require_unique,
)
from nomos_kernel._state_image_abi import _K0OccurrenceCursor, _K0OwnerState


class _K0OwnerTopology(Protocol):
    """Structural owner portion consumed by the causal machine."""

    owners: tuple[_K0Owner, ...]
    cross_owner_invariants: tuple[_K0CrossOwnerInvariant, ...]
    _occurrence_cursor_validator: _K0OccurrenceCursorValidator | None


@dataclass(frozen=True)
class _K0OwnerStateDirectory:
    """Private lookup tied to one exact topology and persistent state tuple.

    This indexes storage, not validation results. Callbacks still receive fresh
    isolated, validated values; neither these maps nor storage leave K0.
    """

    topology: _K0OwnerTopology
    owner_states: tuple[_K0OwnerState, ...]
    owners: Mapping[K0OwnerKey, _K0Owner] = dataclass_field(init=False, repr=False, compare=False)
    states: Mapping[K0OwnerKey, object] = dataclass_field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.owner_states) is not tuple or type(self.topology.owners) is not tuple:
            raise K0ProfileError("owner state directory is not closed")
        owners = {owner.key: owner for owner in self.topology.owners}
        states = {entry.owner: entry.state for entry in self.owner_states}
        if (
            len(owners) != len(self.topology.owners)
            or len(states) != len(self.owner_states)
            or states.keys() != owners.keys()
        ):
            raise K0ProfileError("owner state directory shape is invalid")
        object.__setattr__(self, "owners", MappingProxyType(owners))
        object.__setattr__(self, "states", MappingProxyType(states))


@contextmanager
def _validation_operation(owner):
    scope = (
        owner.validation_operation()
        if isinstance(owner, _K0ValidationOperationOwner)
        else nullcontext()
    )
    failure = None
    with scope:
        try:
            yield
        except BaseException as error:
            failure = error
            raise
    if failure is not None:
        # An optional backend scope cannot swallow a K0 validation failure.
        raise failure


def _clone_owner_state(owner: _K0Owner, state: object) -> object:
    with _validation_operation(owner):
        return _clone_owner_state_in_operation(owner, state)


_NO_OPENING_VALIDATOR = object()


def _validate_opening_state(owner: _K0Owner, state: object) -> None:
    """Opening hooks inspect disposable data and cannot rewrite the opening."""
    validator = getattr(owner, "validate_opening_state", _NO_OPENING_VALIDATOR)
    if validator is not _NO_OPENING_VALIDATOR:
        if not callable(validator):
            raise K0ProfileError("owner opening validator is not callable")
        detached = _copy_closed_state(state)
        validator(detached)
        _copy_closed_state(detached, state)


def _clone_owner_state_in_operation(owner: _K0Owner, state: object) -> object:
    detached = _copy_closed_state(state)
    owner.validate_state(detached)
    wire = _canonical_wire(owner.encode_state(detached))
    if detached != _copy_closed_state(state):
        raise K0ProfileError("owner validation or encoding changed input state")
    cloned = owner.decode_state(wire)
    owner.validate_state(cloned)
    if cloned is detached or cloned is state:
        raise K0ProfileError("owner canonical decode must create an isolated state")
    return _copy_closed_state(cloned)


_UNCHECKED_STATE = object()
_DICT_VALUES_TYPE = type({}.values())


def _snapshot_record_fields(carrier: type):
    """Snapshot current real fields before any nested copy can invoke native code."""
    try:
        metadata = getattr(carrier, "__dataclass_fields__")
    except AttributeError:
        raise TypeError("must be called with a dataclass type or instance") from None
    values = metadata.values()
    if type(values) is not _DICT_VALUES_TYPE:
        return tuple(item for item in values if item._field_type is _FIELD)
    try:
        return [item for item in values if item._field_type is _FIELD]
    except StopIteration as error:
        # Preserve the generator-expression failure boundary of dataclasses.fields.
        raise RuntimeError("generator raised StopIteration") from error


def _copy_closed_state(state: object, expected: object = _UNCHECKED_STATE) -> object:
    """Detach data without invoking owner code or record constructors.

    This is an ownership boundary, not semantic validation. The owner still
    validates the detached value. No owner callback may receive or retain the
    authoritative storage object. When expected is supplied, compare actual
    closed data while making the final detached copy, without record equality.
    """
    carrier = type(state)
    checking = expected is not _UNCHECKED_STATE
    if checking and carrier is not type(expected):
        raise K0ProfileError("owner validation changed candidate state semantics")
    if state is None or carrier in (bool, int, str):
        if checking and state != expected:
            raise K0ProfileError("owner validation changed candidate state semantics")
        return state
    if isinstance(state, Enum):
        raise K0ProfileError("owner state cannot share Python Enum member objects")
    if carrier is tuple:
        if checking:
            if len(state) != len(expected):
                raise K0ProfileError("owner validation changed candidate state semantics")
            return tuple(
                [
                    _copy_closed_state(item, prior)
                    for item, prior in zip(state, expected, strict=True)
                ]
            )
        return tuple([_copy_closed_state(item) for item in state])
    if carrier is frozenset:
        if checking and _closed_data_key(state) != _closed_data_key(expected):
            raise K0ProfileError("owner validation changed candidate state semantics")
        return frozenset(_copy_closed_state(item) for item in state)
    if carrier is MappingProxyType:
        if checking and _closed_data_key(state) != _closed_data_key(expected):
            raise K0ProfileError("owner validation changed candidate state semantics")
        return MappingProxyType(
            {_copy_closed_state(key): _copy_closed_state(value) for key, value in state.items()}
        )
    parameters = getattr(carrier, "__dataclass_params__", None)
    if not is_dataclass(state) or parameters is None or not parameters.frozen:
        raise K0ProfileError("owner state must use recursively frozen closed values")
    copied = object.__new__(carrier)
    for field in _snapshot_record_fields(carrier):
        descriptor = None
        for base in carrier.__mro__:
            namespace = vars(base)
            if field.name in namespace:
                descriptor = namespace[field.name]
                break
        if hasattr(type(descriptor), "__get__") and type(descriptor) is not MemberDescriptorType:
            raise K0ProfileError("owner nominal value field cannot use a computed descriptor")
        object.__setattr__(
            copied,
            field.name,
            _copy_closed_state(
                object.__getattribute__(state, field.name),
                object.__getattribute__(expected, field.name) if checking else _UNCHECKED_STATE,
            ),
        )
    return copied


def _closed_data_key(value: object) -> tuple:
    """Compare unordered data without hashing or comparing original record keys.

    Sorted closed keys preserve multiplicity even for records whose native
    equality differs from their fields. Rebuilding containers still uses native
    hash/equality on the detached keys, just as ordinary detachment does.
    """
    carrier = type(value)
    if value is None or carrier in (bool, int, str):
        return (id(carrier), value)
    if carrier is tuple:
        return (id(carrier), tuple(_closed_data_key(item) for item in value))
    if carrier is frozenset:
        return (id(carrier), tuple(sorted((_closed_data_key(item) for item in value), key=repr)))
    if carrier is MappingProxyType:
        return (
            id(carrier),
            tuple(
                sorted(
                    (
                        (_closed_data_key(key), _closed_data_key(item))
                        for key, item in value.items()
                    ),
                    key=repr,
                )
            ),
        )
    parameters = getattr(carrier, "__dataclass_params__", None)
    if (
        isinstance(value, Enum)
        or not is_dataclass(value)
        or parameters is None
        or not parameters.frozen
    ):
        raise K0ProfileError("owner state must use recursively frozen closed values")
    result = []
    for field in _snapshot_record_fields(carrier):
        descriptor = None
        for base in carrier.__mro__:
            namespace = vars(base)
            if field.name in namespace:
                descriptor = namespace[field.name]
                break
        if hasattr(type(descriptor), "__get__") and type(descriptor) is not MemberDescriptorType:
            raise K0ProfileError("owner nominal value field cannot use a computed descriptor")
        result.append((field.name, _closed_data_key(object.__getattribute__(value, field.name))))
    return (id(carrier), tuple(result))


def _isolate_candidate_owner_state(owner: _K0Owner, state: object) -> object:
    """Isolate one closed candidate state without weakening persistence codecs."""
    with _validation_operation(owner):
        return _isolate_candidate_owner_state_in_operation(owner, state)


def _isolate_candidate_owner_state_in_operation(owner: _K0Owner, state: object) -> object:
    if type(state) is not owner.state_type:
        raise K0ProfileError("candidate state has the wrong exact owner type")
    detached = _copy_closed_state(state)
    owner.validate_state(detached)
    # The validator may retain its temporary input; callers get another detached value.
    return _copy_closed_state(detached, state)


def _build_owner_views(
    profile: _K0OwnerTopology,
    owner_states: tuple[_K0OwnerState, ...],
    read_owners: tuple[K0OwnerKey, ...],
) -> tuple[_K0OwnerView, ...]:
    """Build declared views from kernel-detached data, never live candidate state."""
    _require_unique(read_owners, "requested read owners")
    owners = {owner.key: owner for owner in profile.owners}
    states = {entry.owner: entry.state for entry in owner_states}
    if not set(read_owners).issubset(owners) or set(states) != set(owners):
        raise K0ProfileError("requested read owners or owner state shape is invalid")
    views: list[_K0OwnerView] = []
    for owner_key in sorted(read_owners):
        owner = owners[owner_key]
        with _validation_operation(owner):
            view = owner.read_view(
                _isolate_candidate_owner_state_in_operation(owner, states[owner_key])
            )
            if type(view) is not owner.view_type or not isinstance(view, _K0ReadOnlyOwnerView):
                raise K0ProfileError(
                    "owner read_view returned the wrong closed immutable view type"
                )
            view.validate_for_k0()
            views.append(_K0OwnerView(owner_key, view))
    return tuple(views)


def _build_candidate_owner_views(
    directory: _K0OwnerStateDirectory,
    read_owners: tuple[K0OwnerKey, ...],
) -> tuple[_K0OwnerView, ...]:
    """Build declared views from candidate-safe owner-bounded isolation."""
    _require_unique(read_owners, "requested read owners")
    owners = directory.owners
    states = directory.states
    if any(key not in owners for key in read_owners):
        raise K0ProfileError("requested read owners or owner state shape is invalid")
    views: list[_K0OwnerView] = []
    for owner_key in sorted(read_owners):
        owner = owners[owner_key]
        with _validation_operation(owner):
            isolated = _isolate_candidate_owner_state_in_operation(owner, states[owner_key])
            view = owner.read_view(isolated)
            if type(view) is not owner.view_type or not isinstance(view, _K0ReadOnlyOwnerView):
                raise K0ProfileError(
                    "owner read_view returned the wrong closed immutable view type"
                )
            view.validate_for_k0()
            views.append(_K0OwnerView(owner_key, view))
    return tuple(views)


def _validate_profile_cross_owner_invariants(
    profile: _K0OwnerTopology,
    owner_states: tuple[_K0OwnerState, ...],
    runtime_propositions: _K0RuntimePropositionState,
) -> None:
    for invariant in profile.cross_owner_invariants:
        views = _build_owner_views(profile, owner_states, invariant.read_owners)
        if isinstance(invariant, _K0RuntimePropositionInvariant):
            invariant.validate_with_runtime_propositions(views, runtime_propositions)
        else:
            invariant.validate(views)


def _validate_profile_occurrence_cursor(
    profile: _K0OwnerTopology,
    owner_states: tuple[_K0OwnerState, ...],
    cursor: _K0OccurrenceCursor,
    representations: tuple[_K0OccurrenceRecordView, ...],
) -> None:
    validator = profile._occurrence_cursor_validator
    if validator is None:
        return
    views = _build_owner_views(profile, owner_states, validator.read_owners)
    try:
        validator.validate_occurrence_cursor(cursor, representations, views)
    except K0ProfileError:
        raise
    except Exception as error:
        raise K0ProfileError("occurrence cursor validation failed") from error
