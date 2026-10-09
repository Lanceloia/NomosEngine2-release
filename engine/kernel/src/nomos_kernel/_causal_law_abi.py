"""Closed immediate-causality declarations for kernel profiles."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._dynamic_actor_abi import _K0ActorDomainPort
from nomos_kernel._occurrence_record_abi import _K0ActivationProjector, _K0OccurrenceRecordView
from nomos_kernel._owner_abi import _K0CapabilityRef, _require_unique
from nomos_kernel._rule_products_abi import _K0Activation


@dataclass(frozen=True)
class K0CausalLawDefinition:
    """A finite immediate-causality declaration bound to one target source."""

    key: K0CausalLawKey
    triggering_event_type: K0EventTypeKey
    resulting_source: K0SourceSpecKey
    max_activations: int
    read_owners: tuple[K0OwnerKey, ...]
    activation_projector: _K0ActivationProjector
    receipt_local: bool = False
    actor_domains: tuple[_K0ActorDomainPort, ...] = ()

    def __post_init__(self) -> None:
        if type(self) is not K0CausalLawDefinition or tuple(vars(self)) != tuple(
            self.__dataclass_fields__
        ):
            raise K0ProfileError("causal law definition must be one exact closed carrier")
        if type(self.max_activations) is not int or self.max_activations < 1:
            raise K0ProfileError("causal law max activations must be a positive int")
        if type(self.receipt_local) is not bool:
            raise K0ProfileError("causal law receipt-local flag must be an exact bool")
        if type(self.actor_domains) is not tuple or any(
            type(port) is not _K0ActorDomainPort or port.write for port in self.actor_domains
        ):
            raise K0ProfileError("causal projection Actor domains must be declared read-only")
        for port in self.actor_domains:
            port.__post_init__()
        for value, expected, label in (
            (self.key, K0CausalLawKey, "causal law key"),
            (self.triggering_event_type, K0EventTypeKey, "causal law trigger"),
            (self.resulting_source, K0SourceSpecKey, "causal law result source"),
        ):
            if type(value) is not expected:
                raise K0ProfileError(f"{label} must use one exact key")
            try:
                expected.__post_init__(value)
            except (AttributeError, TypeError) as error:
                raise K0ProfileError(f"{label} is malformed") from error
        if type(self.read_owners) is not tuple:
            raise K0ProfileError("causal law read owners must be an exact tuple")
        for owner in self.read_owners:
            if type(owner) is not K0OwnerKey:
                raise K0ProfileError("causal law read owner must be an exact key")
            try:
                K0OwnerKey.__post_init__(owner)
            except (AttributeError, TypeError) as error:
                raise K0ProfileError("causal law read owner is malformed") from error
        if not isinstance(self.activation_projector, _K0ActivationProjector):
            raise K0ProfileError("causal law must bind one closed activation projector")
        capability_ref = self.activation_projector.capability_ref
        if type(capability_ref) is not _K0CapabilityRef:
            raise K0ProfileError("activation projector must have a stable capability reference")
        try:
            _K0CapabilityRef.__post_init__(capability_ref)
        except (AttributeError, TypeError) as error:
            raise K0ProfileError(
                "activation projector capability reference is malformed"
            ) from error
        _require_unique(self.read_owners, "causal law read owners")
        object.__setattr__(self, "read_owners", tuple(sorted(self.read_owners)))


@dataclass(frozen=True)
class _K0PlannedActivation:
    """One already projected activation paired with its law and trigger."""

    law: K0CausalLawDefinition
    trigger: _K0OccurrenceRecordView
    activation: _K0Activation
