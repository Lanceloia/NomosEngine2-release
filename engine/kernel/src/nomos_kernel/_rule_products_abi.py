"""Private products emitted by causal activation and source-rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0LocalIdentitySlot, K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._dynamic_actor_abi import _K0ActorProductSlot, _K0FormActorProduct
from nomos_kernel._dynamic_owner_abi import _K0FormOwnerRequest
from nomos_kernel._event_jump_abi import _K0ScheduleOnce
from nomos_kernel._identity import _require_local_identity_slot
from nomos_kernel._owner_abi import (
    _checked_label,
    _K0ClosedParticipants,
    _K0Owner,
    _K0OwnerContribution,
    _K0SealedBinding,
    _K0SealedEvidence,
)


@dataclass(frozen=True)
class _K0Activation:
    binding_key: str
    evidence: _K0SealedEvidence
    participants: _K0ClosedParticipants
    bindings: tuple[_K0SealedBinding, ...]

    def __post_init__(self) -> None:
        _checked_label(self.binding_key, "activation binding key")


@dataclass(frozen=True)
class K0RuleResult:
    """Declared owner contributions, local slots, dues and owner formation."""

    contributions: tuple[_K0OwnerContribution, ...]
    local_output_requests: tuple[K0LocalIdentitySlot, ...]
    scheduled_due: tuple[_K0ScheduleOnce, ...] = ()
    formed_owners: tuple[_K0FormOwnerRequest, ...] = ()
    formed_actors: tuple[_K0FormActorProduct, ...] = ()

    def __post_init__(self) -> None:
        if type(self.contributions) is not tuple:
            raise K0ProfileError("rule contributions must use an exact tuple")
        for contribution in self.contributions:
            if not isinstance(contribution, _K0OwnerContribution):
                raise K0ProfileError("rule contribution is not an exact owner contribution")
            contribution.validate_for_k0()
        slots = self.local_output_requests
        if type(slots) is not tuple:
            raise K0ProfileError("rule local output requests must use an exact tuple")
        for slot in slots:
            _require_local_identity_slot(slot, "rule local output request")
        if tuple(sorted(slots)) != slots or len(set(slots)) != len(slots):
            raise K0ProfileError("rule local output requests must be unique and canonical-order")
        if type(self.scheduled_due) is not tuple or any(
            type(request) is not _K0ScheduleOnce for request in self.scheduled_due
        ):
            raise K0ProfileError("rule scheduled due products must be exact")
        if type(self.formed_owners) is not tuple or any(
            type(request) is not _K0FormOwnerRequest for request in self.formed_owners
        ):
            raise K0ProfileError("rule formed owners must be exact")
        for request in self.formed_owners:
            request.__post_init__()
        if type(self.formed_actors) is not tuple or any(
            type(request) is not _K0FormActorProduct for request in self.formed_actors
        ):
            raise K0ProfileError("rule Actor products must use explicit exact slots")
        for request in self.formed_actors:
            request.__post_init__()


def _validate_rule_result(
    owners: tuple[_K0Owner, ...],
    result: K0RuleResult,
    expected_slots: tuple[K0LocalIdentitySlot, ...],
    expected_contribution_owners: tuple[K0OwnerKey, ...],
    expected_due_sources: tuple[K0SourceSpecKey, ...] = (),
    expected_form_families: tuple[str, ...] = (),
    expected_actor_product: _K0ActorProductSlot | None = None,
) -> None:
    """Reject undeclared writes and runtime-invented local output requests."""
    if type(expected_slots) is not tuple:
        raise K0ProfileError("rule-result validation schema is malformed")
    for slot in expected_slots:
        _require_local_identity_slot(slot, "rule-result expected slot")
    if (
        type(owners) is not tuple
        or any(not isinstance(owner, _K0Owner) for owner in owners)
        or len({owner.key for owner in owners}) != len(owners)
        or tuple(sorted(expected_slots)) != expected_slots
        or len(set(expected_slots)) != len(expected_slots)
        or type(expected_contribution_owners) is not tuple
        or any(type(owner) is not K0OwnerKey for owner in expected_contribution_owners)
        or tuple(sorted(expected_contribution_owners)) != expected_contribution_owners
        or len(set(expected_contribution_owners)) != len(expected_contribution_owners)
    ):
        raise K0ProfileError("rule-result validation schema is malformed")
    if type(result) is not K0RuleResult:
        raise K0ProfileError("rule capability returned a malformed result")
    try:
        K0RuleResult.__post_init__(result)
    except (AttributeError, TypeError) as error:
        raise K0ProfileError("rule capability returned a malformed result") from error
    if result.local_output_requests != expected_slots:
        raise K0ProfileError("rule local output requests must equal the source declaration")
    if tuple(request.source for request in result.scheduled_due) != expected_due_sources:
        raise K0ProfileError("rule scheduled due sources must equal the source declaration")
    if tuple(request.family for request in result.formed_owners) != expected_form_families:
        raise K0ProfileError("rule formed owners must equal the source declaration")
    if expected_actor_product is None:
        if result.formed_actors:
            raise K0ProfileError("rule emitted an undeclared Actor product")
    elif (
        len(result.formed_actors) != 1
        or result.formed_actors[0].family != expected_actor_product.family
        or (expected_actor_product.required and result.formed_actors[0].initial_state is None)
    ):
        raise K0ProfileError("rule Actor product does not fill its declared cardinality slot")
    owner_index = {owner.key: owner for owner in owners}
    if any(owner not in owner_index for owner in expected_contribution_owners):
        raise K0ProfileError("rule contribution schema names an undeclared owner")
    contribution_keys = tuple(contribution.owner for contribution in result.contributions)
    if tuple(sorted(set(contribution_keys))) != expected_contribution_owners:
        raise K0ProfileError("rule contribution owners must equal the source declaration")
    for owner_key in set(contribution_keys):
        owner = owner_index.get(owner_key)
        if owner is None:
            raise K0ProfileError("rule contribution names an undeclared owner")
        if contribution_keys.count(owner_key) >= 2:
            allowed = getattr(owner, "allows_same_occurrence_contribution_batch", False)
            if type(allowed) is not bool or not allowed:
                raise K0ProfileError("owner does not allow multiple same-occurrence contributions")
    for contribution in result.contributions:
        owner = owner_index.get(contribution.owner)
        if owner is None:
            raise K0ProfileError("rule contribution names an undeclared owner")
        if type(contribution) is not owner.contribution_type:
            raise K0ProfileError("rule contribution has the wrong exact owner type")
        owner.validate_contribution(contribution)
