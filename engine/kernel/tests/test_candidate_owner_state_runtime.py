"""Focused tests for the domain-neutral candidate owner-state runtime."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from nomos_kernel import K0OwnerKey, K0ProfileError
from nomos_kernel._candidate_owner_state_runtime import (
    _K0CandidateOwnerTopology,
    _K0OwnerStateCandidate,
)
from nomos_kernel._state_image_abi import _K0OwnerState

KERNEL_ROOT = Path(__file__).resolve().parents[1] / "src"

GENERIC_METHODS = (
    "_state_for",
    "owner_views",
    "_snapshot_states",
    "source_owner_views",
    "causal_owner_views",
    "validate_cross_owner_invariants",
    "allocate_occurrence",
    "materialize_local_identity",
    "apply_owner_contributions",
    "_replace_owner_state",
)


def test_candidate_runtime_import_does_not_load_mind_or_dawn() -> None:
    script = (
        "import sys,nomos_kernel._candidate_owner_state_runtime as m;"
        "print(any(n.startswith(('nomos_mind','nomos_dawn')) for n in sys.modules),"
        "all(hasattr(m._K0OwnerStateCandidate, n) for n in "
        + repr(GENERIC_METHODS)
        + "))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", script],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    ).strip()
    assert output == "False True"


def test_owner_topology_carrier_rejects_malformed_shapes() -> None:
    with pytest.raises(K0ProfileError, match="topology is not closed"):
        _K0CandidateOwnerTopology(())
    with pytest.raises(K0ProfileError, match="topology is not closed"):
        _K0CandidateOwnerTopology([])


def test_base_instance_exposes_topology_and_rejects_undeclared_owner() -> None:
    owner_key = K0OwnerKey("test-owner")

    class _Owner:
        key = owner_key

    owner = _Owner()
    topology = _K0CandidateOwnerTopology((owner,))
    candidate = _K0OwnerStateCandidate(
        topology,
        (),
        (),
        (),
        (_K0OwnerState(owner_key, object()),),
        cursor=None,
        time=None,
        runtime_propositions=None,
    )
    assert candidate.owners == (owner,)
    with pytest.raises(K0ProfileError, match="undeclared owner"):
        candidate._state_for(K0OwnerKey("other-owner"))


def test_base_construction_requires_matching_owner_state_keys() -> None:
    class _Owner:
        key = object()

    owner = _Owner()
    topology = _K0CandidateOwnerTopology((owner,))
    with pytest.raises(K0ProfileError, match="topology is not closed"):
        _K0OwnerStateCandidate(
            topology,
            (),
            (),
            (),
            (),
            cursor=None,
            time=None,
            runtime_propositions=None,
        )
