"""Focused tests for conditional local-identity planning protocols."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0LocalIdentitySlot, K0OccurrenceRef, K0SourceSpecKey
from nomos_kernel._conditional_identity_abi import (
    _K0ConditionalLocalIdentityConformanceProjection,
    _K0ConditionalLocalIdentityPlan,
)
from nomos_kernel._owner_abi import _K0CapabilityRef


@dataclass(frozen=True)
class _Projection:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Plan:
    source: K0SourceSpecKey
    occurrence: K0OccurrenceRef
    capability_ref: _K0CapabilityRef
    capability_version: str
    input_provenance: object
    selected_slots: tuple[K0LocalIdentitySlot, ...]
    conformance_projection: _Projection

    def validate_for_k0(self) -> None:
        return None


def test_conditional_plan_keeps_rule_input_as_opaque_identity_provenance() -> None:
    provenance = object()
    projection = _Projection()
    plan = _Plan(
        K0SourceSpecKey("conditional-source"),
        K0OccurrenceRef(1),
        _K0CapabilityRef("CONDITIONAL.IDENTITY.TEST@1"),
        "1",
        provenance,
        (),
        projection,
    )
    assert isinstance(projection, _K0ConditionalLocalIdentityConformanceProjection)
    assert isinstance(plan, _K0ConditionalLocalIdentityPlan)
    assert plan.input_provenance is provenance
