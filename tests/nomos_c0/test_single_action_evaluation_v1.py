"""Action effects and semantic envelope consume one authored output evaluation."""

from unittest.mock import patch

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_composable_action_v1 import Attempt, Envelope, Receipt, _session, _states

from nomos_c0.composable_action_v1 import C0ValueActionProgram
from tools.c0_audit_m1_wait import _repeat_publication_outputs


@pytest.mark.parametrize("diagnostic_repeat", [False, True])
def test_action_publishes_effects_and_envelope_from_one_output_evaluation(diagnostic_repeat):
    program, runtime = _session()
    original = C0ValueActionProgram._outputs
    calls = []

    def observe(self, rule_input):
        calls.append(rule_input.occurrence)
        return original(self, rule_input)

    from contextlib import nullcontext

    from nomos_c0.composable_action_v1 import _Rule

    with (
        patch.object(C0ValueActionProgram, "_outputs", observe),
        patch.object(_Rule, "evaluate", _repeat_publication_outputs)
        if diagnostic_repeat
        else nullcontext(),
    ):
        published = runtime.settle(
            _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
        )
        rejected = runtime.settle(
            _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
        )
    assert isinstance(published, K0Published)
    assert isinstance(rejected, K0NotAdmitted)
    occurrence = published.occurrences[0]
    assert calls == [occurrence.occurrence] * (2 if diagnostic_repeat else 1)
    scene, actor = _states(runtime)
    assert scene.parcels[0].dispatch == occurrence.occurrence
    assert actor.receipts == (Receipt("P", occurrence.occurrence),)
    assert occurrence.semantic_envelope == Envelope(occurrence.occurrence, "inspect")


def test_publication_construction_failure_keeps_effects_unpublished():
    program, runtime = _session()
    before = _states(runtime)

    def fail_envelope(self):
        raise ValueError("publication defect after candidate effects")

    with patch.object(Envelope, "validate_for_k0", fail_envelope):
        with pytest.raises(K0SettlementDefect):
            runtime.settle(
                _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
            )
    assert _states(runtime) == before
    assert runtime.occurrence_history() == ()
    assert runtime._fatal
