"""Conditional local-identity planning protocols for the causal machine."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nomos_kernel import K0LocalIdentitySlot, K0OccurrenceRef, K0OwnerKey, K0SourceSpecKey
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0LocalIdentityValue,
    _K0OwnerView,
)
from nomos_kernel._rule_products_abi import K0RuleResult


@runtime_checkable
class _K0ConditionalLocalIdentityConformanceProjection(Protocol):
    """One source-specific opaque projection of the complete planned result."""

    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0ConditionalLocalIdentityPlan(Protocol):
    """One source-specific sealed allocation decision, never a world carrier."""

    source: K0SourceSpecKey
    occurrence: K0OccurrenceRef
    capability_ref: _K0CapabilityRef
    capability_version: str
    input_provenance: object
    selected_slots: tuple[K0LocalIdentitySlot, ...]
    conformance_projection: _K0ConditionalLocalIdentityConformanceProjection

    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0ConditionalLocalIdentitySettlement(Protocol):
    """One source-specific closed settlement of an already validated Plan."""

    source: K0SourceSpecKey
    occurrence: K0OccurrenceRef
    capability_ref: _K0CapabilityRef
    capability_version: str
    selected_slots: tuple[K0LocalIdentitySlot, ...]
    conformance_projection: _K0ConditionalLocalIdentityConformanceProjection
    result: K0RuleResult

    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0ConditionalLocalIdentityRuleCapability(Protocol):
    """Strict opt-in Action rule owning one Plan and settle revision."""

    capability_ref: _K0CapabilityRef
    capability_version: str
    plan_type: type[object]
    settlement_type: type[object]
    conformance_projection_type: type[object]
    eligible_slots: tuple[K0LocalIdentitySlot, ...]

    def plan(self, rule_input: object) -> object: ...

    def settle(
        self,
        plan: object,
        resolved_slots: tuple[_K0LocalIdentityValue, ...],
    ) -> object: ...


@runtime_checkable
class _K0BranchSettlementRuleCapability(_K0ConditionalLocalIdentityRuleCapability, Protocol):
    """One source-profile-bound terminal-basis refinement for a fixed root."""

    applicability_type: type[object]
    source_classification_type: type[object]
    terminal_basis_type: type[object]
    supplemental_owner: K0OwnerKey

    def classify_applicability(self, common_views: tuple[_K0OwnerView, ...]) -> object: ...
    def request_supplemental_owner(self, applicability: object) -> K0OwnerKey | None: ...
    def classify_source(
        self, applicability: object, supplemental_view: object | None
    ) -> object: ...

    def form_terminal_basis(
        self,
        applicability: object,
        supplemental_view: object | None,
        source_classification: object,
    ) -> object: ...

    def rederive_terminal_basis(
        self,
        common_views: tuple[_K0OwnerView, ...],
        applicability: object,
        supplemental_view: object | None,
        basis: object,
    ) -> object: ...
    def plan_branch(self, rule_input: object, basis: object) -> object: ...


