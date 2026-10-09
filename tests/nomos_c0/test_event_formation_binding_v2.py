"""Selected Event ports cannot change checked sorts, predecessors or mechanisms."""

from dataclasses import replace

import pytest

from nomos_c0.event_formation_binding_v2 import (
    EventFormationPlanError,
    EventFormationPort,
    bind_event_formation_ports,
)
from nomos_c0.event_formation_ir_v2 import (
    EventFormationProgram,
    EventFormationRule,
    FormationMechanism,
    FormationTriggerKind,
)
from nomos_c0.nominal_types_v1 import EventSortRef, SemanticIdentity

DEPARTURE = EventSortRef(SemanticIdentity("TEST.DEPARTURE@1"))
NOTICE = EventSortRef(SemanticIdentity("TEST.NOTICE@1"))
SEMANTIC = EventFormationProgram(
    (DEPARTURE, NOTICE),
    (
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
    ),
)
PORTS = (
    EventFormationPort(
        "depart",
        "source.depart",
        "type.depart",
        "dispatch",
        "source.dispatch",
        "type.dispatch",
        "law.depart",
    ),
    EventFormationPort(
        "notice",
        "source.notice",
        "type.notice",
        "depart",
        "source.depart",
        "type.depart",
        "law.notice",
    ),
)


def test_binding_retains_checked_sort_and_exact_ports():
    plan = bind_event_formation_ports(SEMANTIC, PORTS)
    assert plan.semantic_program is SEMANTIC
    assert tuple(edge.port for edge in plan.edges) == PORTS
    assert tuple(edge.result_sort for edge in plan.edges) == (DEPARTURE, NOTICE)


def test_missing_or_changed_trigger_port_rejects():
    with pytest.raises(EventFormationPlanError, match="cover exactly"):
        bind_event_formation_ports(SEMANTIC, PORTS[:1])
    with pytest.raises(EventFormationPlanError, match="trigger binding"):
        bind_event_formation_ports(SEMANTIC, (PORTS[0], replace(PORTS[1], trigger_source="other")))


def test_shared_result_source_cannot_change_sort():
    with pytest.raises(EventFormationPlanError, match="conflicting Event sorts"):
        bind_event_formation_ports(
            SEMANTIC, (PORTS[0], replace(PORTS[1], result_source="source.depart"))
        )


def test_shared_result_source_preserves_distinct_formation_edges():
    semantic = EventFormationProgram(
        (DEPARTURE, NOTICE),
        (
            SEMANTIC.rules[0],
            EventFormationRule(
                "notice_a",
                NOTICE,
                "depart",
                FormationTriggerKind.EVENT,
                FormationMechanism.CAUSAL,
                DEPARTURE,
            ),
            EventFormationRule(
                "notice_b",
                NOTICE,
                "depart",
                FormationTriggerKind.EVENT,
                FormationMechanism.CAUSAL,
                DEPARTURE,
            ),
        ),
    )
    first = replace(PORTS[1], result_entry="notice_a", causal_law="law.notice_a")
    second = replace(PORTS[1], result_entry="notice_b", causal_law="law.notice_b")
    plan = bind_event_formation_ports(semantic, (PORTS[0], first, second))
    assert tuple(edge.port.causal_law for edge in plan.edges[1:]) == (
        "law.notice_a",
        "law.notice_b",
    )


def test_due_port_requires_no_causal_law_and_unique_runtime_basis():
    semantic = EventFormationProgram(
        (DEPARTURE,),
        (
            EventFormationRule(
                "arrive", DEPARTURE, "dispatch", FormationTriggerKind.ACTION, FormationMechanism.DUE
            ),
        ),
    )
    port = EventFormationPort(
        "arrive",
        "source.arrive",
        "type.arrive",
        "dispatch",
        "source.dispatch",
        "type.dispatch",
        None,
    )
    plan = bind_event_formation_ports(semantic, (port,))
    assert plan.edges[0].mechanism is FormationMechanism.DUE
    with pytest.raises(EventFormationPlanError, match="mechanism"):
        bind_event_formation_ports(semantic, (replace(port, causal_law="law.arrive"),))
    duplicate = EventFormationProgram(
        (DEPARTURE,),
        (
            replace(semantic.rules[0], result_entry="arrive_a"),
            replace(semantic.rules[0], result_entry="arrive_b"),
        ),
    )
    with pytest.raises(EventFormationPlanError, match="repeats one runtime formation basis"):
        bind_event_formation_ports(
            duplicate,
            (replace(port, result_entry="arrive_a"), replace(port, result_entry="arrive_b")),
        )
