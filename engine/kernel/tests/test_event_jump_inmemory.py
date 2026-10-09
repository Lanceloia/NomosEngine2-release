"""Sourced one-shot due settlement in the private K0 Session."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

import pytest
from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._action_value_abi import (
    _K0ActionValueDueBoundary,
    _K0ActionValueOpening,
    _K0ActionValuePolicy,
    _K0ActionValueProjection,
    _K0ActionValueSeat,
)
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
    _K0PendingDue,
    _K0PeriodicDueKey,
    _K0PeriodicDueOpening,
    _K0PeriodicDuePlan,
    _K0ScheduleOnce,
)
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OccurrenceContribution
from nomos_kernel._rule_products_abi import K0RuleResult
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect, _K0TemporalRejected
from nomos_kernel._state_image_abi import _K0OwnerState

OWNER = K0OwnerKey("event-jump.scene")
START = K0SourceSpecKey("event-jump.start")
TAKE = K0SourceSpecKey("event-jump.take")
FOLLOWUP = K0SourceSpecKey("event-jump.followup")
FINISH = K0SourceSpecKey("event-jump.finish")
FINISH_FOLLOWUP = K0SourceSpecKey("event-jump.finish-followup")
PULSE = K0SourceSpecKey("event-jump.pulse")


@dataclass(frozen=True)
class _Scene:
    mode: str = "raw"
    completed_at: int | None = None
    start_ref: K0OccurrenceRef | None = None
    finish_ref: K0OccurrenceRef | None = None
    take_ref: K0OccurrenceRef | None = None
    pulses: int = 0
    pulse_saw: str | None = None

    def validate_for_k0(self) -> None:
        if (
            self.mode not in ("raw", "baking", "ready", "taken")
            or type(self.pulses) is not int
            or self.pulses < 0
            or self.pulse_saw not in (None, "raw", "baking", "ready", "taken")
        ):
            raise K0ProfileError("invalid test mode")


@dataclass(frozen=True)
class _Attempt:
    kind: str

    def validate_for_k0(self) -> None:
        if self.kind not in ("start", "take", "followup"):
            raise K0ProfileError("invalid test attempt")


@dataclass(frozen=True)
class _Evidence:
    scene: _Scene
    kind: str

    def validate_for_k0(self) -> None:
        self.scene.validate_for_k0()


@dataclass(frozen=True)
class _Participants:
    actor: str = "worker"

    def validate_for_k0(self) -> None:
        if self.actor != "worker":
            raise K0ProfileError("invalid test actor")


@dataclass(frozen=True)
class _Envelope:
    kind: str
    tick: int

    def validate_for_k0(self) -> None:
        if (
            self.kind not in ("start", "take", "followup", "finish", "finish_followup", "pulse")
            or type(self.tick) is not int
        ):
            raise K0ProfileError("invalid test envelope")


@dataclass(frozen=True)
class _Replace:
    owner: K0OwnerKey
    state: _Scene

    def validate_for_k0(self) -> None:
        if self.owner != OWNER or type(self.state) is not _Scene:
            raise K0ProfileError("invalid test contribution")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class _Owner:
    key: K0OwnerKey = OWNER
    owner_version: str = "event-jump-v0"
    state_type: ClassVar[type] = _Scene
    view_type: ClassVar[type] = _Scene
    contribution_type: ClassVar[type] = _Replace
    local_identity_families: ClassVar[tuple[str, ...]] = ()

    def validate_state(self, state: object) -> None:
        if type(state) is not _Scene:
            raise K0ProfileError("wrong test state")
        state.validate_for_k0()

    def read_view(self, state: object) -> object:
        self.validate_state(state)
        return state

    def validate_contribution(self, contribution: object) -> None:
        if type(contribution) is not _Replace:
            raise K0ProfileError("wrong test contribution")
        contribution.validate_for_k0()

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]:
        if len(contributions) != 1:
            raise K0ProfileError("test owner needs one replacement")
        return contributions

    def apply_contributions(
        self, state: object, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> object:
        self.validate_state(state)
        return contributions[0].contribution.state

    def allocate_local_identity(self, state: object, slot: object, occurrence: object) -> object:
        raise K0ProfileError("test owner has no local identity")

    def preserved_occurrences(self, state: object) -> tuple[K0OccurrenceRef, ...]:
        self.validate_state(state)
        return tuple(
            ref for ref in (state.start_ref, state.finish_ref, state.take_ref) if ref is not None
        )

    def encode_state(self, state: object) -> tuple[object, ...]:
        self.validate_state(state)
        return (
            self.owner_version,
            state.mode,
            state.completed_at,
            *(
                None if ref is None else ref.value
                for ref in (state.start_ref, state.finish_ref, state.take_ref)
            ),
            state.pulses,
            state.pulse_saw,
        )

    def decode_state(self, wire: tuple[object, ...]) -> object:
        if type(wire) is not tuple or len(wire) != 8 or wire[0] != self.owner_version:
            raise K0ProfileError("test state wire is malformed")
        state = _Scene(
            wire[1],
            wire[2],
            *(None if ref is None else K0OccurrenceRef(ref) for ref in wire[3:6]),
            wire[6],
            wire[7],
        )
        self.validate_state(state)
        return state


@dataclass(frozen=True)
class _Admission:
    capability_ref: _K0CapabilityRef
    kind: str
    deadline: int = 5

    def admit(self, payload: _Attempt, owner_views: tuple[object, ...]) -> None:
        return None

    def admit_at_time(
        self, payload: _Attempt, owner_views: tuple[object, ...], time: _K0FixedTime
    ) -> _K0AdmissionProjection | None:
        scene = owner_views[0].view
        valid = payload.kind == self.kind and (
            (self.kind == "start" and scene.mode == "raw")
            or (self.kind == "followup" and scene.mode == "baking" and scene.take_ref is None)
            or (
                self.kind == "take"
                and scene.mode == "ready"
                and time.ordinal >= scene.completed_at
                and time.ordinal < self.deadline
            )
        )
        if not valid:
            return None
        return _K0AdmissionProjection(_Evidence(scene, self.kind), _Participants(), ())


@dataclass(frozen=True)
class _DueProjector:
    capability_ref: _K0CapabilityRef
    source: K0SourceSpecKey

    def project_due(
        self, pending: _K0PendingDue, time: _K0FixedTime, owner_views: tuple[object, ...]
    ) -> _K0AdmissionProjection:
        scene = owner_views[0].view
        required_mode = "ready" if self.source == FINISH_FOLLOWUP else "baking"
        if (
            pending.source != self.source
            or pending.subject != ("clock" if self.source == PULSE else "batch")
            or (self.source != PULSE and scene.mode != required_mode)
        ):
            raise K0ProfileError("due has lost its exact basis")
        return _K0AdmissionProjection(_Evidence(scene, "finish"), _Participants(), ())


@dataclass(frozen=True)
class _Rule:
    capability_ref: _K0CapabilityRef
    kind: str
    fail: bool = False
    bad_schedule: bool = False
    same_time: bool = False

    def evaluate(self, rule_input: object) -> _K0InMemoryEvaluation:
        if self.fail:
            raise K0ProfileError("injected due rule defect")
        scene = rule_input.evidence.scene
        if self.kind == "start":
            state = replace(scene, mode="baking", start_ref=rule_input.occurrence)
            scheduled = (
                _K0ScheduleOnce(
                    _K0FixedTime(rule_input.time.ordinal + (0 if self.bad_schedule else 3)),
                    FINISH,
                    "batch",
                ),
            )
        elif self.kind == "followup":
            state = replace(scene, take_ref=rule_input.occurrence)
            scheduled = (
                _K0ScheduleOnce(
                    _K0FixedTime(rule_input.time.ordinal + (3 if self.same_time else 5)),
                    FINISH_FOLLOWUP,
                    "batch",
                ),
            )
        elif self.kind == "finish":
            if rule_input.pending_due is None or rule_input.time != rule_input.pending_due.at:
                raise K0ProfileError("due rule has no current pending key")
            state = replace(
                scene,
                mode="ready",
                completed_at=rule_input.time.ordinal,
                finish_ref=rule_input.occurrence,
            )
            scheduled = ()
        elif self.kind == "finish_followup":
            if rule_input.pending_due is None or rule_input.time != rule_input.pending_due.at:
                raise K0ProfileError("followup due rule has no current pending key")
            state = replace(scene, mode="taken", finish_ref=rule_input.occurrence)
            scheduled = ()
        elif self.kind == "pulse":
            if rule_input.pending_due is None or rule_input.time != rule_input.pending_due.at:
                raise K0ProfileError("pulse rule has no current periodic key")
            state = replace(scene, pulses=scene.pulses + 1, pulse_saw=scene.mode)
            scheduled = ()
        else:
            state = replace(scene, mode="taken", take_ref=rule_input.occurrence)
            scheduled = ()
        return _K0InMemoryEvaluation(
            K0RuleResult((_Replace(OWNER, state),), (), scheduled),
            _Envelope(self.kind, rule_input.time.ordinal),
        )


@dataclass(frozen=True)
class _ActionValueProjector:
    eligible_modes: tuple[str, ...] = ("raw", "baking", "ready", "taken")
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.action-value.project")

    def project(self, owner_view: object) -> _K0ActionValueProjection:
        owner_view.view.validate_for_k0()
        return _K0ActionValueProjection(1, owner_view.view.mode in self.eligible_modes)


@dataclass(frozen=True)
class _CostProjector:
    cost: int
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.action-value.cost")

    def project_cost(self, payload: object, admission: object) -> int:
        return self.cost


def _spec(
    kind: str,
    *,
    fail_due: bool = False,
    bad_schedule: bool = False,
    same_time: bool = False,
) -> _K0InMemorySourceSpec:
    key = {
        "start": START,
        "take": TAKE,
        "followup": FOLLOWUP,
        "finish": FINISH,
        "finish_followup": FINISH_FOLLOWUP,
        "pulse": PULSE,
    }[kind]
    is_due = kind in ("finish", "finish_followup", "pulse")
    return _K0InMemorySourceSpec(
        key,
        K0OccurrenceFamily.EVENT if is_due else K0OccurrenceFamily.ACTION,
        K0EventTypeKey(f"event-jump.{kind}.event"),
        _Attempt,
        _Evidence,
        _Participants,
        (OWNER,),
        (OWNER,),
        (),
        (),
        None if is_due else _Admission(_K0CapabilityRef(f"admit.{kind}"), kind),
        _Rule(_K0CapabilityRef(f"rule.{kind}"), kind, fail_due, bad_schedule, same_time),
        _Envelope,
        (FINISH,) if kind == "start" else (FINISH_FOLLOWUP,) if kind == "followup" else (),
        _DueProjector(_K0CapabilityRef(f"due.{kind}"), key) if is_due else None,
    )


def _session(
    *,
    fail_due: bool = False,
    bad_schedule: bool = False,
    two_due: bool = False,
    same_time: bool = False,
    reverse_order: bool = False,
) -> _K0InMemorySession:
    order = (FINISH, FINISH_FOLLOWUP) if two_due else (FINISH,)
    if reverse_order:
        order = tuple(reversed(order))
    profile = _K0InMemoryProfile(
        (_Owner(),),
        (
            _spec("start", bad_schedule=bad_schedule, same_time=same_time),
            _spec("take"),
            *((_spec("followup", same_time=same_time),) if two_due else ()),
            _spec("finish", fail_due=fail_due),
            *((_spec("finish_followup"),) if two_due else ()),
        ),
        (),
        2,
        0,
        temporal_policy=_K0OrderedTemporalPolicy(
            _K0CapabilityRef("test.ordered-due"), order, len(order)
        ),
    )
    return _K0InMemorySession.create(
        profile, (_K0OwnerState(OWNER, _Scene()),), initial_time=_K0FixedTime(0)
    )


@dataclass(frozen=True)
class _NeverProjector:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("event-jump.never-project")

    def project(self, trigger: object, owner_views: tuple[object, ...]) -> tuple[object, ...]:
        return ()


def test_due_event_cannot_also_be_formed_by_immediate_causality() -> None:
    law = K0CausalLawDefinition(
        K0CausalLawKey("event-jump.illicit-finish"),
        K0EventTypeKey("event-jump.start.event"),
        FINISH,
        1,
        (OWNER,),
        _NeverProjector(),
    )
    with pytest.raises(K0ProfileError, match="temporal due Event"):
        _K0InMemoryProfile(
            (_Owner(),),
            (_spec("start"), _spec("finish")),
            (law,),
            2,
            1,
            temporal_policy=_K0OrderedTemporalPolicy(
                _K0CapabilityRef("test.ordered-due"), (FINISH,), 1
            ),
        )


def _advance(session: _K0InMemorySession, start: int, end: int):
    return session.advance(
        _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(start), _K0FixedTime(end)))
    )


def test_sourced_due_and_empty_interval_share_one_authoritative_session() -> None:
    session = _session()
    start = session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    assert len(start.occurrences) == 1
    assert session._pending_due[0].key.formation == start.occurrences[0].occurrence
    empty = _advance(session, 0, 2)
    assert empty.occurrences == ()
    assert session.read_owner(OWNER).view.mode == "baking"
    assert session.settle(_K0InMemoryActionAttempt(TAKE, _Attempt("take"))).reason == "not_admitted"
    done = _advance(session, 2, 5)
    assert done.interval.t1 == _K0FixedTime(3)
    assert len(done.occurrences) == 1
    assert done.occurrences[0].formation_basis.key == session.temporal_history()[-1].dues[0]
    assert session.read_owner(OWNER).view.mode == "ready"
    assert session._pending_due == ()
    assert len(session.temporal_history()) == 2
    assert len(session.settle(_K0InMemoryActionAttempt(TAKE, _Attempt("take"))).occurrences) == 1


def test_stale_advance_and_late_action_do_not_write() -> None:
    session = _session()
    session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    pending_key = session._pending_due[0].key
    assert _advance(session, 0, 3).occurrences[0].formation_basis.key == pending_key
    assert isinstance(_advance(session, 0, 5), _K0TemporalRejected)
    _advance(session, 3, 5)
    assert session.settle(_K0InMemoryActionAttempt(TAKE, _Attempt("take"))).reason == "not_admitted"
    assert session.read_owner(OWNER).view.mode == "ready"
    assert len(session._tape) == 2


def test_due_defect_rolls_back_time_owner_and_tape_then_fatal() -> None:
    session = _session(fail_due=True)
    session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    before = (
        session.read_time(),
        session.read_owner(OWNER).view,
        session._pending_due,
        session._cursor,
        session._tape,
        session.temporal_history(),
    )
    with pytest.raises(K0SettlementDefect, match="temporal settlement"):
        _advance(session, 0, 3)
    after = (
        session.read_time(),
        session.read_owner(OWNER).view,
        session._pending_due,
        session._cursor,
        session._tape,
        session.temporal_history(),
    )
    assert after == before
    with pytest.raises(K0SettlementDefect, match="fatal"):
        _advance(session, 0, 3)


def test_invalid_scheduled_time_cannot_publish_the_forming_action() -> None:
    session = _session(bad_schedule=True)
    with pytest.raises(K0SettlementDefect, match="in-memory settlement"):
        session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    assert session.read_time() == _K0FixedTime(0)
    assert session.read_owner(OWNER).view == _Scene()
    assert session._pending_due == ()
    assert session._tape == ()


def test_distinct_due_keys_from_two_actions_are_consumed_once_in_time_order() -> None:
    session = _session(two_due=True)
    start = session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    followup = session.settle(_K0InMemoryActionAttempt(FOLLOWUP, _Attempt("followup")))
    keys = tuple(item.key for item in session._pending_due)
    assert len(keys) == 2
    assert keys[0].formation == start.occurrences[0].occurrence
    assert keys[1].formation == followup.occurrences[0].occurrence
    assert (keys[0].ordinal, keys[1].ordinal) == (0, 0)

    first = _advance(session, 0, 7)
    assert first.interval.t1 == _K0FixedTime(3)
    assert first.occurrences[0].formation_basis.key == keys[0]
    assert tuple(item.key for item in session._pending_due) == (keys[1],)
    second = _advance(session, 3, 7)
    assert second.interval.t1 == _K0FixedTime(5)
    assert second.occurrences[0].formation_basis.key == keys[1]
    assert session._pending_due == ()
    assert isinstance(_advance(session, 3, 7), _K0TemporalRejected)


def test_same_time_dues_settle_in_selected_order() -> None:
    session = _session(two_due=True, same_time=True)
    session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    session.settle(_K0InMemoryActionAttempt(FOLLOWUP, _Attempt("followup")))
    done = _advance(session, 0, 7)
    assert done.interval.t1 == _K0FixedTime(3)
    assert [item.source for item in done.occurrences] == [FINISH, FINISH_FOLLOWUP]
    assert session.read_owner(OWNER).view.mode == "taken"
    assert session.temporal_history()[-1].dues == tuple(
        item.formation_basis.key for item in done.occurrences
    )


def test_reversed_same_time_order_rolls_back_entire_advance() -> None:
    session = _session(two_due=True, same_time=True, reverse_order=True)
    session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    session.settle(_K0InMemoryActionAttempt(FOLLOWUP, _Attempt("followup")))
    before = (
        session._pending_due,
        session._tape,
        session.read_owner(OWNER).view,
        session.read_time(),
        session.temporal_history(),
    )
    with pytest.raises(K0SettlementDefect, match="temporal settlement"):
        _advance(session, 0, 7)
    assert before == (
        session._pending_due,
        session._tape,
        session.read_owner(OWNER).view,
        session.read_time(),
        session.temporal_history(),
    )


def _periodic_session(*, fail_pulse: bool = False) -> _K0InMemorySession:
    profile = _K0InMemoryProfile(
        (_Owner(),),
        (
            _spec("start"),
            _spec("take"),
            _spec("finish"),
            _spec("pulse", fail_due=fail_pulse),
        ),
        (),
        2,
        0,
        temporal_policy=_K0OrderedTemporalPolicy(
            _K0CapabilityRef("test.periodic"),
            (FINISH, PULSE),
            2,
            (
                _K0PeriodicDuePlan(
                    _K0CapabilityRef("test.periodic.pulse"),
                    PULSE,
                    3,
                    3,
                    "clock",
                ),
            ),
            (START,),
        ),
    )
    return _K0InMemorySession.create(
        profile,
        (_K0OwnerState(OWNER, _Scene()),),
        initial_time=_K0FixedTime(0),
        opening_periodic_dues=(
            _K0PeriodicDueOpening(_K0CapabilityRef("test.periodic.pulse"), _K0FixedTime(3)),
        ),
    )


def _action_value_session(
    *,
    cost: int = 4,
    freeze_while_baking: bool = False,
    end_at: _K0FixedTime | None = _K0FixedTime(12),
    opening_debt: int = 3,
    pulse_limit: int | None = 3,
) -> _K0InMemorySession:
    start = replace(
        _spec("start"),
        action_value_owner=OWNER,
        action_cost_projector=_CostProjector(cost),
    )
    temporal = _K0OrderedTemporalPolicy(
        _K0CapabilityRef("test.action-value.temporal"),
        (FINISH, PULSE),
        2,
        (
            _K0PeriodicDuePlan(
                _K0CapabilityRef("test.action-value.pulse"), PULSE, 3, pulse_limit, "clock"
            ),
        ),
        (START,),
    )
    action_value = _K0ActionValuePolicy(
        _K0CapabilityRef("test.action-value"),
        (
            _K0ActionValueSeat(
                "worker",
                OWNER,
                (START,),
                _ActionValueProjector(("raw", "ready", "taken"))
                if freeze_while_baking
                else _ActionValueProjector(),
            ),
        ),
        end_at,
        8,
    )
    profile = _K0InMemoryProfile(
        (_Owner(),),
        (start, _spec("finish"), _spec("pulse")),
        (),
        2,
        0,
        temporal_policy=temporal,
        action_value_policy=action_value,
    )
    return _K0InMemorySession.create(
        profile,
        (_K0OwnerState(OWNER, _Scene()),),
        initial_time=_K0FixedTime(0),
        opening_periodic_dues=(
            _K0PeriodicDueOpening(_K0CapabilityRef("test.action-value.pulse"), _K0FixedTime(3)),
        ),
        opening_action_values=(_K0ActionValueOpening("worker", opening_debt, 0),),
    )


def test_periodic_due_repeats_with_stable_keys() -> None:
    session = _periodic_session()
    boundary = session.begin_pre_due(
        _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(3)))
    )
    assert boundary.occurrences == ()
    assert session.read_time() == _K0FixedTime(3)
    assert session.in_pre_due_phase()

    pulse = session.resolve_pre_due()
    assert [item.source for item in pulse.occurrences] == [PULSE]
    assert session.read_owner(OWNER).view.pulse_saw == "raw"
    first_key = pulse.occurrences[0].formation_basis.key
    assert first_key == _K0PeriodicDueKey(_K0CapabilityRef("test.periodic.pulse"), 0)

    second = _advance(session, 3, 6)
    assert [item.source for item in second.occurrences] == [PULSE]
    assert session.read_owner(OWNER).view.pulse_saw == "raw"
    assert second.occurrences[-1].formation_basis.key.ordinal == 1
    third = _advance(session, 6, 9)
    assert third.occurrences[0].formation_basis.key.ordinal == 2
    assert session.next_due_time() is None


def test_pre_due_rejects_unselected_action_and_due_failure_is_fatal() -> None:
    session = _periodic_session()
    session.begin_pre_due(
        _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(3)))
    )
    rejected = session.settle(_K0InMemoryActionAttempt(TAKE, _Attempt("take")))
    assert rejected.reason == "not_admitted"
    assert session.read_owner(OWNER).view == _Scene()
    assert session.occurrence_history() == ()
    assert session.resolve_pre_due().occurrences[0].source == PULSE

    broken = _periodic_session(fail_pulse=True)
    broken.begin_pre_due(
        _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(3)))
    )
    before = (broken.read_owner(OWNER).view, broken.occurrence_history())
    with pytest.raises(K0SettlementDefect, match="pre-due resolution"):
        broken.resolve_pre_due()
    assert before == (broken.read_owner(OWNER).view, broken.occurrence_history())
    with pytest.raises(K0SettlementDefect, match="fatal"):
        broken.resolve_pre_due()


def test_periodic_source_cannot_also_be_action_scheduled() -> None:
    policy = _K0OrderedTemporalPolicy(
        _K0CapabilityRef("test.invalid-periodic"),
        (FINISH,),
        1,
        (
            _K0PeriodicDuePlan(
                _K0CapabilityRef("test.invalid-periodic.finish"),
                FINISH,
                3,
                1,
                "batch",
            ),
        ),
    )
    with pytest.raises(K0ProfileError, match="exclusively plan-formed"):
        _K0InMemoryProfile(
            (_Owner(),),
            (_spec("start"), _spec("finish")),
            (),
            2,
            0,
            temporal_policy=policy,
        )


def test_action_value_clock_without_due_sources_advances_and_publishes_only_actions() -> None:
    take = replace(_spec("take"), action_value_owner=OWNER, action_cost_projector=_CostProjector(4))
    temporal = _K0OrderedTemporalPolicy(_K0CapabilityRef("test.empty-clock"), (), 0, (), (TAKE,))
    action_policy = _K0ActionValuePolicy(
        _K0CapabilityRef("test.empty-clock.actions"),
        (_K0ActionValueSeat("worker", OWNER, (TAKE,), _ActionValueProjector()),),
        _K0FixedTime(12),
        8,
    )
    profile = _K0InMemoryProfile(
        (_Owner(),),
        (take,),
        (),
        1,
        0,
        temporal_policy=temporal,
        action_value_policy=action_policy,
    )
    session = _K0InMemorySession.create(
        profile,
        (_K0OwnerState(OWNER, _Scene(mode="ready", completed_at=0)),),
        initial_time=_K0FixedTime(0),
        opening_action_values=(_K0ActionValueOpening("worker", 3, 0),),
    )
    assert session.continue_action_value().at == _K0FixedTime(3)
    assert session.occurrence_history() == ()
    published = session.settle(_K0InMemoryActionAttempt(TAKE, _Attempt("take")))
    assert published.occurrences[0].source == TAKE
    assert session.continue_action_value().at == _K0FixedTime(7)
    assert [record.source for record in session.occurrence_history()] == [TAKE]
    assert session._pending_due == ()


@pytest.mark.parametrize("sources,capacity", [((), 1), ((FINISH,), 0)])
def test_empty_due_selection_requires_exact_zero_capacity(sources, capacity) -> None:
    with pytest.raises(K0ProfileError, match="temporal policy"):
        _K0OrderedTemporalPolicy(_K0CapabilityRef("test.invalid-clock"), sources, capacity)


def test_empty_due_selection_cannot_hide_a_periodic_or_scheduled_source() -> None:
    plan = _K0PeriodicDuePlan(_K0CapabilityRef("test.invalid-pulse"), PULSE, 3, 1, "clock")
    with pytest.raises(K0ProfileError, match="periodic due"):
        _K0OrderedTemporalPolicy(_K0CapabilityRef("test.invalid-clock"), (), 0, (plan,))
    with pytest.raises(K0ProfileError):
        _K0InMemoryProfile(
            (_Owner(),),
            (_spec("start"),),
            (),
            1,
            0,
            temporal_policy=_K0OrderedTemporalPolicy(_K0CapabilityRef("test.empty-clock"), (), 0),
        )


def test_action_value_scheduler_owns_debt_and_actor_precedes_same_time_pulse() -> None:
    session = _action_value_session()
    opportunity = session.continue_action_value()
    assert opportunity.seat == "worker"
    assert opportunity.at == _K0FixedTime(3)
    assert session.in_pre_due_phase()
    assert session.action_value_state()[0].debt == 0
    action = session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    assert action.occurrences[0].source == START
    assert session.action_value_state()[0].debt == 4
    assert session.continue_action_value() == _K0ActionValueDueBoundary(_K0FixedTime(3))
    assert session.read_time() == _K0FixedTime(3)
    assert session.continue_action_value() == _K0ActionValueDueBoundary(_K0FixedTime(6))
    assert session.read_time() == _K0FixedTime(6)
    next_opportunity = session.continue_action_value()
    assert next_opportunity.at == _K0FixedTime(7)
    assert session.read_owner(OWNER).view.pulse_saw == "ready"
    assert [item.source for item in session.occurrence_history()] == [
        START,
        PULSE,
        FINISH,
        PULSE,
    ]
    assert session.action_value_state()[0].debt == 0


def test_unbounded_action_value_and_periodic_due_continue_past_old_limits() -> None:
    session = _action_value_session(end_at=None, opening_debt=15, pulse_limit=None)
    for at in (3, 6, 9, 12):
        assert session.continue_action_value() == _K0ActionValueDueBoundary(_K0FixedTime(at))
    opportunity = session.continue_action_value()
    assert opportunity is not None and opportunity.at == _K0FixedTime(15)
    assert session.in_pre_due_phase()
    pulses = [item for item in session.occurrence_history() if item.source == PULSE]
    assert [item.formation_basis.key.ordinal for item in pulses] == [0, 1, 2, 3]
    assert session.next_due_time() == _K0FixedTime(15)
    assert session.settle(_K0InMemoryActionAttempt(START, _Attempt("start"))).occurrences
    assert session.resolve_pre_due().occurrences[0].formation_basis.key.ordinal == 4


def test_action_value_cost_must_be_positive_without_world_write() -> None:
    session = _action_value_session(cost=0)
    session.continue_action_value()
    before = (
        session.read_owner(OWNER).view,
        session.action_value_state(),
        session.occurrence_history(),
    )
    rejected = session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    assert rejected.reason == "not_admitted"
    assert before == (
        session.read_owner(OWNER).view,
        session.action_value_state(),
        session.occurrence_history(),
    )


def test_action_value_ineligible_interval_preserves_debt_until_world_restores_actor() -> None:
    session = _action_value_session(freeze_while_baking=True)
    assert session.continue_action_value().at == _K0FixedTime(3)
    assert session.settle(_K0InMemoryActionAttempt(START, _Attempt("start"))).occurrences
    assert session.action_value_state()[0].debt == 4

    assert session.continue_action_value() == _K0ActionValueDueBoundary(_K0FixedTime(3))
    assert session.continue_action_value() == _K0ActionValueDueBoundary(_K0FixedTime(6))
    assert session.continue_action_value() == _K0ActionValueDueBoundary(_K0FixedTime(9))
    opportunity = session.continue_action_value()
    assert session.read_owner(OWNER).view.mode == "ready"
    assert opportunity.at == _K0FixedTime(10)
    assert session.action_value_state()[0].debt == 0
    advances = [record for record in session.action_value_history() if record.kind == "advance"]
    assert any(
        record.at == _K0FixedTime(6)
        and record.debt_before[0].debt == record.debt_after[0].debt == 4
        for record in advances
    )
