"""Domain-neutral, occurrence-sourced variable Collective membership.

This owner is an opt-in K0 capability. A selected source/law decides which
membership attempt is justified; this module owns only the resulting relation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from nomos_kernel._identity import K0OccurrenceRef, K0OwnerKey, K0ProfileError, _checked_label
from nomos_kernel._owner_abi import _K0OccurrenceContribution


def _exact_ref(value: object, label: str) -> K0OccurrenceRef:
    if type(value) is not K0OccurrenceRef:
        raise K0ProfileError(f"{label} must be an exact occurrence reference")
    try:
        K0OccurrenceRef.__post_init__(value)
    except (AttributeError, TypeError) as error:
        raise K0ProfileError(f"{label} is malformed") from error
    return value


@dataclass(frozen=True, order=True)
class _K0CollectiveRef:
    value: str

    def __post_init__(self) -> None:
        _checked_label(getattr(self, "value", None), "Collective reference")


@dataclass(frozen=True, order=True)
class _K0CollectiveMemberRef:
    family: str
    value: str

    def __post_init__(self) -> None:
        _checked_label(getattr(self, "family", None), "Collective member family")
        _checked_label(getattr(self, "value", None), "Collective member reference")


@dataclass(frozen=True, order=True)
class _K0CollectiveDeclaration:
    ref: _K0CollectiveRef
    member_family: str

    def __post_init__(self) -> None:
        ref = getattr(self, "ref", None)
        if type(ref) is not _K0CollectiveRef:
            raise K0ProfileError("Collective declaration requires an exact reference")
        _K0CollectiveRef.__post_init__(ref)
        _checked_label(getattr(self, "member_family", None), "Collective declared member family")


@dataclass(frozen=True, order=True)
class _K0Membership:
    collective: _K0CollectiveRef
    member: _K0CollectiveMemberRef
    added_by: K0OccurrenceRef

    def __post_init__(self) -> None:
        collective = getattr(self, "collective", None)
        member = getattr(self, "member", None)
        if type(collective) is not _K0CollectiveRef:
            raise K0ProfileError("membership requires an exact Collective reference")
        _K0CollectiveRef.__post_init__(collective)
        if type(member) is not _K0CollectiveMemberRef:
            raise K0ProfileError("membership requires an exact member reference")
        _K0CollectiveMemberRef.__post_init__(member)
        _exact_ref(getattr(self, "added_by", None), "membership source")


@dataclass(frozen=True)
class _K0CollectiveState:
    declarations: tuple[_K0CollectiveDeclaration, ...]
    memberships: tuple[_K0Membership, ...] = ()

    def validate_for_k0(self) -> None:
        if (
            type(getattr(self, "declarations", None)) is not tuple
            or type(getattr(self, "memberships", None)) is not tuple
        ):
            raise K0ProfileError("Collective state requires exact tuples")
        for declaration in self.declarations:
            if type(declaration) is not _K0CollectiveDeclaration:
                raise K0ProfileError("Collective state has a malformed declaration")
            _K0CollectiveDeclaration.__post_init__(declaration)
        if not self.declarations or self.declarations != tuple(sorted(self.declarations)):
            raise K0ProfileError("Collective declarations must be nonempty and canonical")
        families = {item.ref: item.member_family for item in self.declarations}
        if len(families) != len(self.declarations):
            raise K0ProfileError("Collective identity is duplicated")
        for membership in self.memberships:
            if type(membership) is not _K0Membership:
                raise K0ProfileError("Collective state has a malformed membership")
            _K0Membership.__post_init__(membership)
            if families.get(membership.collective) != membership.member.family:
                raise K0ProfileError("Collective member has the wrong declared family")
        if self.memberships != tuple(sorted(self.memberships)):
            raise K0ProfileError("Collective memberships must be canonical")
        pairs = {(item.collective, item.member) for item in self.memberships}
        if len(pairs) != len(self.memberships):
            raise K0ProfileError("Collective membership is duplicated")

    def members_of(self, ref: _K0CollectiveRef) -> tuple[_K0Membership, ...]:
        self.validate_for_k0()
        if type(ref) is not _K0CollectiveRef:
            raise K0ProfileError("Collective query names no declared identity")
        _K0CollectiveRef.__post_init__(ref)
        if ref not in {item.ref for item in self.declarations}:
            raise K0ProfileError("Collective query names no declared identity")
        return tuple(item for item in self.memberships if item.collective == ref)


@dataclass(frozen=True)
class _K0CollectiveView:
    declarations: tuple[_K0CollectiveDeclaration, ...]
    memberships: tuple[_K0Membership, ...]

    def validate_for_k0(self) -> None:
        _K0CollectiveState(self.declarations, self.memberships).validate_for_k0()

    def members_of(self, ref: _K0CollectiveRef) -> tuple[_K0Membership, ...]:
        return _K0CollectiveState(self.declarations, self.memberships).members_of(ref)


@dataclass(frozen=True)
class _K0CollectiveAdd:
    owner: K0OwnerKey
    collective: _K0CollectiveRef
    member: _K0CollectiveMemberRef

    def validate_for_k0(self) -> None:
        owner = getattr(self, "owner", None)
        collective = getattr(self, "collective", None)
        member = getattr(self, "member", None)
        if type(owner) is not K0OwnerKey:
            raise K0ProfileError("Collective contribution has no exact owner")
        try:
            K0OwnerKey.__post_init__(owner)
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("Collective contribution owner is malformed") from error
        if type(collective) is not _K0CollectiveRef:
            raise K0ProfileError("Collective contribution has no exact identity")
        _K0CollectiveRef.__post_init__(collective)
        if type(member) is not _K0CollectiveMemberRef:
            raise K0ProfileError("Collective contribution has no exact member")
        _K0CollectiveMemberRef.__post_init__(member)


@dataclass(frozen=True)
class _K0CollectiveOwner:
    key: K0OwnerKey
    declarations: tuple[_K0CollectiveDeclaration, ...]

    owner_version: ClassVar[str] = "K0.COLLECTIVE.ADD@1"
    state_type: ClassVar[type[object]] = _K0CollectiveState
    view_type: ClassVar[type[object]] = _K0CollectiveView
    contribution_type: ClassVar[type[object]] = _K0CollectiveAdd
    local_identity_families: ClassVar[tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        key = getattr(self, "key", None)
        if type(key) is not K0OwnerKey:
            raise K0ProfileError("Collective owner requires an exact owner key")
        try:
            K0OwnerKey.__post_init__(key)
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("Collective owner key is malformed") from error
        _K0CollectiveState(getattr(self, "declarations", None)).validate_for_k0()

    def validate_state(self, state: object) -> None:
        if type(state) is not _K0CollectiveState:
            raise K0ProfileError("Collective owner state has the wrong exact type")
        state.validate_for_k0()
        if state.declarations != self.declarations:
            raise K0ProfileError("Collective declarations changed inside one owner")

    def validate_opening_state(self, state: object) -> None:
        self.validate_state(state)
        if state.memberships:
            raise K0ProfileError("Collective opening membership needs a published occurrence")

    def read_view(self, state: object) -> _K0CollectiveView:
        self.validate_state(state)
        return _K0CollectiveView(state.declarations, state.memberships)

    def validate_contribution(self, contribution: object) -> None:
        if type(contribution) is not _K0CollectiveAdd:
            raise K0ProfileError("Collective owner requires an add contribution")
        contribution.validate_for_k0()
        if contribution.owner != self.key:
            raise K0ProfileError("Collective contribution crossed its owner")
        declaration = next(
            (item for item in self.declarations if item.ref == contribution.collective), None
        )
        if declaration is None or declaration.member_family != contribution.member.family:
            raise K0ProfileError("Collective contribution has wrong identity or member family")

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]:
        if type(contributions) is not tuple or not contributions:
            raise K0ProfileError("Collective merge needs occurrence contributions")
        for item in contributions:
            if type(item) is not _K0OccurrenceContribution:
                raise K0ProfileError("Collective merge received a malformed occurrence")
            self.validate_contribution(item.contribution)
        pairs = tuple(
            (item.contribution.collective, item.contribution.member) for item in contributions
        )
        if len(set(pairs)) != len(pairs):
            raise K0ProfileError("Collective merge repeats one membership")
        return contributions

    def apply_contributions(
        self, state: object, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> _K0CollectiveState:
        self.validate_state(state)
        merged = self.merge_contributions(contributions)
        existing = {(item.collective, item.member) for item in state.memberships}
        additions = []
        for item in merged:
            contribution = item.contribution
            pair = (contribution.collective, contribution.member)
            if pair in existing:
                raise K0ProfileError("Collective membership already exists")
            existing.add(pair)
            additions.append(_K0Membership(*pair, item.occurrence))
        updated = _K0CollectiveState(
            state.declarations, tuple(sorted((*state.memberships, *additions)))
        )
        self.validate_state(updated)
        return updated

    def prove_same_wave_effects(
        self,
        prior_state: object,
        contributions: tuple[_K0OccurrenceContribution, ...],
        final_state: object,
    ) -> None:
        self.validate_state(prior_state)
        self.validate_state(final_state)
        if final_state != self.apply_contributions(prior_state, contributions):
            raise K0ProfileError("same-wave Collective ADD lost a membership or its source")

    def allocate_local_identity(self, state: object, slot: object, occurrence: object) -> object:
        raise K0ProfileError("Collective add owner does not allocate member identities")

    def preserved_occurrences(self, state: object) -> tuple[K0OccurrenceRef, ...]:
        self.validate_state(state)
        return tuple(item.added_by for item in state.memberships)

    def encode_state(self, state: object) -> tuple[object, ...]:
        self.validate_state(state)
        return tuple(
            (item.collective.value, item.member.family, item.member.value, item.added_by.value)
            for item in state.memberships
        )

    def decode_state(self, wire: object) -> _K0CollectiveState:
        if type(wire) is not tuple:
            raise K0ProfileError("Collective state wire must be an exact tuple")
        memberships = []
        for row in wire:
            if (
                type(row) is not tuple
                or len(row) != 4
                or type(row[0]) is not str
                or type(row[1]) is not str
                or type(row[2]) is not str
                or type(row[3]) is not int
            ):
                raise K0ProfileError("Collective membership wire row is malformed")
            memberships.append(
                _K0Membership(
                    _K0CollectiveRef(row[0]),
                    _K0CollectiveMemberRef(row[1], row[2]),
                    K0OccurrenceRef(row[3]),
                )
            )
        state = _K0CollectiveState(self.declarations, tuple(memberships))
        self.validate_state(state)
        return state
