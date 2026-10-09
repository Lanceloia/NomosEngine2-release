"""Normal closure is a stable root boundary, not a post-publication filter."""

from dataclasses import dataclass, replace
from typing import ClassVar

import pytest
from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._action_value_abi import _K0ActionValueOpening
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemoryProfile,
    _K0InMemorySession,
    _K0InMemorySourceSpec,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._coordinates import _K0FixedTime, _K0TemporalAdvanceRequest, _K0TemporalInterval
from nomos_kernel._event_jump_abi import (
    _K0OrderedTemporalPolicy,
    _K0PeriodicDueOpening,
    _K0PeriodicDuePlan,
    _K0ScheduleOnce,
)
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from nomos_kernel._terminal_settlement_abi import (
    _K0SessionClosed,
    _K0TerminalClause,
    _K0TerminalPolicy,
)
from test_event_jump_inmemory import (
    OWNER,
    START,
    _action_value_session,
    _Attempt,
    _Participants,
)

KEY = K0OwnerKey("terminal.world")
SOURCES = {
    name: K0SourceSpecKey(f"terminal.{name}") for name in ("start", "a", "b", "c", "d", "future")
}


@dataclass(frozen=True)
class _State:
    done: bool = False
    marker: int = 0
    seed: int = 7

    def validate_for_k0(self):
        if (
            type(self.done) is not bool
            or type(self.marker) is not int
            or type(self.seed) is not int
        ):
            raise K0ProfileError("invalid terminal test view")


@dataclass(frozen=True)
class _Write:
    owner: K0OwnerKey
    state: _State

    def validate_for_k0(self):
        assert self.owner == KEY and type(self.state) is _State


@dataclass(frozen=True)
class _Owner:
    key: K0OwnerKey = KEY
    owner_version: str = "terminal-v1"
    state_type: ClassVar[type] = _State
    view_type: ClassVar[type] = _State
    contribution_type: ClassVar[type] = _Write
    local_identity_families: ClassVar[tuple] = ()

    def validate_state(self, state):
        if (
            type(state) is not _State
            or type(state.done) is not bool
            or type(state.marker) is not int
            or type(state.seed) is not int
        ):
            raise K0ProfileError("invalid terminal test state")

    def read_view(self, state):
        self.validate_state(state)
        return state

    def validate_contribution(self, value):
        if type(value) is not _Write or value.owner != self.key:
            raise K0ProfileError("invalid terminal test write")
        self.validate_state(value.state)

    def merge_contributions(self, values):
        if len(values) != 1:
            raise K0ProfileError("terminal test has no same-wave merge")
        return values

    def apply_contributions(self, state, values):
        return values[0].contribution.state

    def preserved_occurrences(self, state):
        return ()

    def allocate_local_identity(self, state, slot, occurrence):
        raise K0ProfileError("no local identities")

    def encode_state(self, state):
        self.validate_state(state)
        return state.done, state.marker, state.seed

    def decode_state(self, wire):
        state = _State(*wire)
        self.validate_state(state)
        return state


@dataclass(frozen=True)
class _Evidence:
    state: _State

    def validate_for_k0(self):
        _Owner().validate_state(self.state)


@dataclass(frozen=True)
class _Projector:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("terminal.project")
    fail: bool = False

    def _projection(self, views):
        if self.fail:
            raise K0ProfileError("suffix projector must not run")
        return _K0AdmissionProjection(_Evidence(views[0].view), _Participants(), ())

    def admit(self, payload, owner_views):
        return self._projection(owner_views)

    def project_due(self, pending, time, owner_views):
        return self._projection(owner_views)

    def project(self, trigger, owner_views):
        projection = self._projection(owner_views)
        return (_K0Activation("one", projection.evidence, projection.participants, ()),)


@dataclass(frozen=True)
class _Rule:
    name: str
    fail: bool = False
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("terminal.rule")

    def evaluate(self, entry):
        if self.fail:
            raise K0ProfileError("closure child fault")
        state = entry.evidence.state
        if self.name == "start":
            dues = tuple(
                _K0ScheduleOnce(_K0FixedTime(at), SOURCES[name], "unit")
                for name, at in (("a", 3), ("b", 3), ("future", 8))
            )
        else:
            dues = ()
        if self.name == "c":
            state = replace(state, done=True)
        if self.name == "d":
            state = replace(state, marker=state.marker + 1)
        if self.name == "b":
            state = replace(state, seed=(state.seed * 17 + 3) % 101)
        return _K0InMemoryEvaluation(K0RuleResult((_Write(KEY, state),), (), dues), _Envelope())


@dataclass(frozen=True)
class _Envelope:
    label: str = "applied"

    def validate_for_k0(self):
        if self.label != "applied":
            raise K0ProfileError("invalid test envelope")


@dataclass(frozen=True)
class _Stop:
    mode: str = "done"
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("terminal.stop")

    def project(self, owner_views):
        state = owner_views[0].view
        if self.mode == "fault" and state.done:
            raise K0ProfileError("terminal predicate fault")
        if self.mode == "non_bool" and state.done:
            return 1
        return state.done and self.mode != "false"


def _policy(mode="done", key=KEY):
    return _K0TerminalPolicy(
        _K0CapabilityRef("terminal.policy"), (_K0TerminalClause("finished", (key,), _Stop(mode)),)
    )


def _session(mode="done", *, fail_d=False, fail_b=False, opening_done=False, periodic=False):
    specs = []
    for name, key in SOURCES.items():
        causal = name in ("c", "d")
        action = name == "start"
        specs.append(
            _K0InMemorySourceSpec(
                key,
                K0OccurrenceFamily.ACTION if action else K0OccurrenceFamily.EVENT,
                K0EventTypeKey(f"terminal.{name}.event"),
                _Attempt,
                _Evidence,
                _Participants,
                (KEY,),
                (KEY,),
                (),
                (),
                _Projector() if action else None,
                _Rule(name, fail_d and name == "d"),
                _Envelope,
                tuple(SOURCES[n] for n in ("a", "b", "future")) if action else (),
                None if causal or action else _Projector(fail=fail_b and name == "b"),
            )
        )
    laws = tuple(
        K0CausalLawDefinition(
            K0CausalLawKey(f"terminal.{left}-{right}"),
            K0EventTypeKey(f"terminal.{left}.event"),
            SOURCES[right],
            1,
            (KEY,),
            _Projector(),
        )
        for left, right in (("a", "c"), ("c", "d"))
    )
    plans = (
        ()
        if not periodic
        else (
            _K0PeriodicDuePlan(
                _K0CapabilityRef("terminal.periodic"),
                SOURCES["a"],
                3,
                None,
                "unit",
            ),
        )
    )
    # A periodic root cannot also be scheduled by an Action.
    if periodic:
        specs[0] = replace(specs[0], scheduled_due_sources=())
    profile = _K0InMemoryProfile(
        (_Owner(),),
        tuple(specs),
        laws,
        8,
        2,
        temporal_policy=_K0OrderedTemporalPolicy(
            _K0CapabilityRef("terminal.time"),
            tuple(SOURCES[n] for n in ("a", "b", "future")),
            3,
            plans,
        ),
        terminal_policy=_policy(mode),
    )
    return _K0InMemorySession.create(
        profile,
        (_K0OwnerState(KEY, _State(done=opening_done)),),
        initial_time=_K0FixedTime(0),
        opening_periodic_dues=tuple(
            _K0PeriodicDueOpening(plan.capability_ref, _K0FixedTime(3)) for plan in plans
        ),
    )


def _request(start, end):
    return _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(start), _K0FixedTime(end)))


def _snapshot(session):
    return (
        session.read_time(),
        session._states,
        session.occurrence_history(),
        session._cursor,
        session._pending_due,
        session.temporal_history(),
        session.terminal_state(),
        session._pre_due_phase,
    )


def _start(session):
    session.settle(_K0InMemoryActionAttempt(SOURCES["start"], _Attempt("start")))


def test_stable_closure_stops_before_suffix_projection_seed_and_allocation():
    session = _session(fail_b=True)
    _start(session)
    pending = session._pending_due
    result = session.advance(_request(0, 8))
    assert [row.source for row in result.occurrences] == [SOURCES[n] for n in ("a", "c", "d")]
    assert session.read_owner(KEY).view == _State(True, 1, 7)
    assert session._cursor.next_value == 5
    terminal = session.terminal_state()
    assert terminal.checkpoint == "due" and terminal.trigger == result.occurrences[0].occurrence
    assert terminal.time.ordinal == 3
    assert tuple(row.pending for row in terminal.not_reached) == pending[1:]
    assert session.temporal_history()[-1].dues == (pending[0].key,)
    assert session._pending_due == () and not session._fatal
    before = _snapshot(session)
    for result in (
        session.settle(object()),
        session.advance(object()),
        session.begin_pre_due(object()),
        session.resolve_pre_due(),
        session.continue_action_value(),
    ):
        assert isinstance(result, _K0SessionClosed)
    assert _snapshot(session) == before


def test_false_condition_preserves_actual_root_closure_order_and_suffix_seed():
    session = _session("false")
    _start(session)
    result = session.advance(_request(0, 3))
    assert [row.source for row in result.occurrences] == [SOURCES[n] for n in ("a", "c", "d", "b")]
    assert session.read_owner(KEY).view == _State(True, 1, 21)
    assert session.terminal_state() is None
    assert len(session._pending_due) == 1


@pytest.mark.parametrize(
    "mode,fail_d,fail_b",
    [
        ("done", True, False),
        ("fault", False, False),
        ("non_bool", False, False),
        ("false", False, True),
    ],
)
def test_closure_or_predicate_defect_rolls_back_entire_advance_and_is_fatal(mode, fail_d, fail_b):
    session = _session(mode, fail_d=fail_d, fail_b=fail_b)
    _start(session)
    before = _snapshot(session)
    with pytest.raises(K0SettlementDefect):
        session.advance(_request(0, 3))
    assert _snapshot(session) == before and session._fatal
    with pytest.raises(K0SettlementDefect, match="fatal"):
        session.advance(_request(0, 3))
    with pytest.raises(K0SettlementDefect, match="fatal"):
        session.continue_action_value()


def test_opening_closure_has_no_fake_trigger_and_closes_periodic_plan():
    session = _session(opening_done=True, periodic=True)
    terminal = session.terminal_state()
    assert terminal.checkpoint == "opening" and terminal.trigger is None
    assert len(terminal.not_reached) == len(terminal.closed_plans) == 1
    assert terminal.closed_plans[0].last_occurrence is None
    assert session._tape == () and session._cursor.next_value == 1


def test_completed_periodic_terminal_root_does_not_renew():
    session = _session(periodic=True)
    result = session.advance(_request(0, 3))
    assert session._pending_due == ()
    terminal = session.terminal_state()
    assert terminal.not_reached == ()
    assert terminal.closed_plans[0].last_occurrence == result.occurrences[0].occurrence


@dataclass(frozen=True)
class _ModeStop:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("terminal.mode-stop")

    def project(self, owner_views):
        return owner_views[0].view.mode == "baking"


def test_actor_first_action_closes_phase_without_following_due():
    base = _action_value_session()
    policy = _K0TerminalPolicy(
        _K0CapabilityRef("terminal.actor-first"),
        (_K0TerminalClause("baking", (OWNER,), _ModeStop()),),
    )
    session = _K0InMemorySession.create(
        replace(base._profile, terminal_policy=policy),
        base._states,
        initial_time=_K0FixedTime(0),
        opening_periodic_dues=(
            _K0PeriodicDueOpening(
                base._profile.temporal_policy.periodic_plans[0].capability_ref, _K0FixedTime(3)
            ),
        ),
        opening_action_values=(_K0ActionValueOpening("worker", 3, 0),),
    )
    session.continue_action_value()
    assert session.in_pre_due_phase()
    result = session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    assert session.terminal_state().trigger == result.occurrences[0].occurrence
    assert not session.in_pre_due_phase()
    assert session.temporal_history()[-1].dues == ()
    assert session.temporal_history()[-1].interval == _K0TemporalInterval(
        _K0FixedTime(0), _K0FixedTime(3)
    )
    assert session.action_value_state()[0].debt == 4
    assert session.action_opportunity() is None
    before = (session.action_value_history(), _snapshot(session))
    assert isinstance(session.continue_action_value(), _K0SessionClosed)
    assert (session.action_value_history(), _snapshot(session)) == before


def test_terminal_policy_rejects_undeclared_owner_port():
    base = _session()
    with pytest.raises(K0ProfileError, match="undeclared owner"):
        replace(base._profile, terminal_policy=_policy(key=K0OwnerKey("foreign")))


@dataclass(frozen=True)
class _Invariant:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("terminal.invariant")
    read_owners: tuple[K0OwnerKey, ...] = (KEY,)

    def validate(self, owner_views):
        if owner_views[0].view.marker:
            raise K0ProfileError("stable marker violates invariant")


def test_invariants_precede_terminal_at_opening_and_full_closure():
    base = _session()
    with pytest.raises(K0ProfileError, match="invariant"):
        _K0InMemorySession.create(
            base._profile,
            (_K0OwnerState(KEY, _State(True, 1)),),
            invariants=(_Invariant(),),
            initial_time=_K0FixedTime(0),
        )
    session = _K0InMemorySession.create(
        base._profile, base._states, invariants=(_Invariant(),), initial_time=_K0FixedTime(0)
    )
    _start(session)
    before = _snapshot(session)
    with pytest.raises(K0SettlementDefect):
        session.advance(_request(0, 3))
    assert _snapshot(session) == before and session._fatal
