"""Semantic Event formation remains closed without a foundational Program wrapper."""

import pytest

from nomos_c0.event_formation_ir_v2 import (
    EventFormationProgram,
    EventFormationRule,
    FormationMechanism,
    FormationTriggerKind,
)
from nomos_c0.nominal_types_v1 import EventSortRef, IRValidationError, SemanticIdentity

DEPARTURE = EventSortRef(SemanticIdentity("TEST.DEPARTURE@1"))
NOTICE = EventSortRef(SemanticIdentity("TEST.NOTICE@1"))


def _rules():
    return (
        EventFormationRule(
            "depart", DEPARTURE, "dispatch", FormationTriggerKind.ACTION, FormationMechanism.CAUSAL
        ),
        EventFormationRule(
            "notice",
            NOTICE,
            "depart",
            FormationTriggerKind.EVENT,
            FormationMechanism.CAUSAL,
            DEPARTURE,
        ),
    )


def test_projection_contains_types_and_edges_not_occurrences():
    program = EventFormationProgram((DEPARTURE, NOTICE), _rules())
    assert program.canonical_projection() == (
        "c0.event_formation.v2",
        ("TEST.DEPARTURE@1", "TEST.NOTICE@1"),
        (
            ("depart", "TEST.DEPARTURE@1", "dispatch", "action", "causal", ""),
            ("notice", "TEST.NOTICE@1", "depart", "event", "causal", "TEST.DEPARTURE@1"),
        ),
    )
    assert not hasattr(program, "occurrences")
    assert not hasattr(program, "declarations")


@pytest.mark.parametrize("fault", ("trigger_sort", "missing_sort", "order", "duplicate"))
def test_unclosed_or_noncanonical_formation_rejects(fault):
    rules = _rules()
    sorts = (DEPARTURE, NOTICE)
    if fault == "trigger_sort":
        rules = (
            rules[0],
            EventFormationRule(
                "notice",
                NOTICE,
                "depart",
                FormationTriggerKind.EVENT,
                FormationMechanism.CAUSAL,
                NOTICE,
            ),
        )
    elif fault == "missing_sort":
        sorts = (DEPARTURE,)
    elif fault == "order":
        rules = tuple(reversed(rules))
    else:
        rules = (rules[0], rules[0])
    with pytest.raises(IRValidationError):
        EventFormationProgram(sorts, rules)


@pytest.mark.parametrize("sorts", ([], (), (NOTICE, DEPARTURE), (DEPARTURE, DEPARTURE), ("sort",)))
def test_formation_sort_table_is_exact_canonical_and_nonempty(sorts):
    with pytest.raises(IRValidationError):
        EventFormationProgram(sorts, _rules())


def test_trigger_kind_and_due_mechanism_are_checked():
    with pytest.raises(IRValidationError, match="Action-triggered"):
        EventFormationRule(
            "depart",
            DEPARTURE,
            "dispatch",
            FormationTriggerKind.ACTION,
            FormationMechanism.CAUSAL,
            NOTICE,
        )
    with pytest.raises(IRValidationError, match="Action scheduler"):
        EventFormationRule(
            "arrive",
            NOTICE,
            "depart",
            FormationTriggerKind.EVENT,
            FormationMechanism.DUE,
            DEPARTURE,
        )
