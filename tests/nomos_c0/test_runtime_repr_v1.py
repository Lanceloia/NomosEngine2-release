"""Failure reporting must not recursively render shared compiled world graphs."""

from dataclasses import fields

import pytest
from test_control_binding_v1 import _inputs
from test_world_binding_v1 import _compile

from nomos_c0.program_runtime_v1 import C0OwnerGraphSession


class Unrenderable:
    def __repr__(self):
        raise AssertionError("diagnostics traversed a private or compiled object")


@pytest.fixture(scope="module")
def compiled():
    lib, ports, source, assets = _inputs()
    return _compile(lib, ports, source), assets


def test_program_repr_counts_entries_without_rendering_graphs(compiled):
    program, _ = compiled
    sentinel = Unrenderable()
    # A deliberately incomplete object exercises diagnostics, not Program publication.
    graph = object.__new__(type(program))
    changes = dict(
        owners=(sentinel,),
        actions=(("unused", sentinel),) * 10000,
        events=(("unused", sentinel),),
        seats=(sentinel,),
        profile=sentinel,
        program_ir=sentinel,
        world_layout=sentinel,
        object_kinds=(sentinel,),
        game_form=sentinel,
    )
    for declaration in fields(program):
        object.__setattr__(
            graph,
            declaration.name,
            changes.get(declaration.name, getattr(program, declaration.name)),
        )
    assert repr(graph) == (
        "C0OwnerGraphProgram(owners=1, actions=10000, events=1, seats=1, object_kinds=1)"
    )


def test_session_repr_never_reads_runtime_or_private_history(compiled):
    program, _ = compiled
    sentinel = Unrenderable()
    lib, ports, source, _ = _inputs()
    source["game_form"] = {"mode": "manual"}
    source["appraisal_profiles"] = []
    session = C0OwnerGraphSession(_compile(lib, ports, source), sentinel)
    session._form_choices.append(sentinel)
    session._appraisal_history.append(sentinel)
    session._pending_seats.add("private-name")
    session._opening_receipt = sentinel
    rendered = repr(session)
    assert len(rendered) < 220
    assert "pending_seats=1, form_choices=1" in rendered
    assert "private-name" not in rendered


def test_default_pytest_traceback_renders_session_without_changing_world(compiled):
    program, assets = compiled
    session = program.start(assets)
    before = session.author_snapshot(), session._runtime.occurrence_history()

    def missing_offer(session):
        next(iter(()))

    with pytest.raises(StopIteration) as failure:
        missing_offer(session)
    report = str(failure.getrepr(style="long", showlocals=True, funcargs=True))
    assert "StopIteration" in report
    assert "C0OwnerGraphSession(program=C0OwnerGraphProgram(" in report
    assert len(report) < 12000
    assert "raised in repr" not in report
    assert (session.author_snapshot(), session._runtime.occurrence_history()) == before
