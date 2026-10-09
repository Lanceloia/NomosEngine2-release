"""Bind checked startup/control declarations to existing private K0 contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace

from nomos_kernel import K0ProfileError
from nomos_kernel._action_value_abi import (
    _K0ActionValuePolicy,
    _K0ActionValueProjection,
    _K0ActionValueSeat,
)
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._event_jump_abi import _K0OrderedTemporalPolicy
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._terminal_settlement_abi import _K0TerminalClause, _K0TerminalPolicy

from .author_contract_v1 import C0LawError
from .checked_value_binding_v1 import C0ValueBackend
from .composable_action_v1 import C0ValueActionEvidence, _C0ActionBasis
from .composable_value_v1 import C0ValueProgram, C0ValueRangeError, C0ValueStateError
from .control_ir_v1 import (
    C0ActionValueSeatIR,
    C0AppraisalProfileIR,
    C0AppraisalRuleIR,
    C0ControlIR,
    C0ControlSeatIR,
    C0WorldStopIR,
)
from .finite_appraisal_v1 import C0AppraisalRule, C0FiniteAppraisalProfile
from .world_binding_v1 import C0BoundWorld
from .world_ir_v1 import C0WorldIR


@dataclass(frozen=True)
class _EventJumpForm:
    seats: tuple[str, ...]
    end_at: int
    wake_at: tuple[int, ...]


@dataclass(frozen=True)
class _ActionValueForm:
    seats: tuple[str, ...]
    end_at: int | None
    world_stops: tuple[_WorldStop, ...] = ()


@dataclass(frozen=True)
class _WorldStop:
    outcome: str
    owners: tuple[str, ...]
    predicate: C0ValueProgram


@dataclass(frozen=True)
class _C0ActionValueProjector:
    value: C0ValueProgram
    capability_ref: _K0CapabilityRef

    def project(self, owner_view) -> _K0ActionValueProjection:
        try:
            result = self.value.evaluate_admission_outputs({"actor": owner_view.view})
        except C0ValueStateError as error:
            raise K0ProfileError("action-value Actor projection failed") from error
        if result is None:
            raise K0ProfileError("action-value Actor projection lost its total basis")
        return _K0ActionValueProjection(result["tempo"], result["eligible"])


@dataclass(frozen=True)
class _C0ActionCostProjector:
    basis: _C0ActionBasis
    value: C0ValueProgram
    capability_ref: _K0CapabilityRef

    def project_cost(self, payload: object, admission: object) -> int | None:
        evidence = getattr(admission, "evidence", None)
        if type(evidence) is not C0ValueActionEvidence or evidence.payload is not payload:
            raise K0ProfileError("action-value cost lacks the admitted Action basis")
        try:
            roots = self.basis.roots(
                evidence.scene,
                evidence.actor,
                evidence.payload,
                evidence.target,
                evidence.selected,
            )
            result = self.value.evaluate_admission_outputs(roots)
        except C0ValueRangeError:
            return None
        except (C0ValueStateError, K0ProfileError) as error:
            raise K0ProfileError("action-value cost projection failed") from error
        if result is None:
            raise K0ProfileError("action-value cost lost its total basis")
        return result["cost"]


@dataclass(frozen=True)
class _C0TerminalProjector:
    symbols: tuple[str, ...]
    value: C0ValueProgram
    capability_ref: _K0CapabilityRef

    def project(self, owner_views: tuple[object, ...]) -> bool:
        # K0 supplies only the clause's exact, isolated owner views.
        roots = {name: view.view for name, view in zip(self.symbols, owner_views, strict=True)}
        return self.value.admits(roots)


@dataclass(frozen=True)
class C0BoundControl:
    ir: C0ControlIR
    game_form: _EventJumpForm | _ActionValueForm | None
    opening: C0ValueProgram | None
    temporal_policy: _K0OrderedTemporalPolicy | None
    action_value_policy: _K0ActionValuePolicy | None
    terminal_policy: _K0TerminalPolicy | None
    action_costs: tuple[tuple[str, _C0ActionCostProjector], ...]
    appraisals: tuple[C0FiniteAppraisalProfile, ...]


def capture_control(
    backend: C0ValueBackend,
    world: C0WorldIR,
    seats: tuple[C0ControlSeatIR, ...],
    game_form,
    opening: C0ValueProgram | None,
    action_value_policy: _K0ActionValuePolicy | None,
    costs: dict[str, _C0ActionCostProjector],
    appraisals: tuple[C0FiniteAppraisalProfile, ...],
) -> C0ControlIR:
    """Capture checked frontend artifacts before native Profile assembly."""
    if backend.layout.signatures is not world.signatures or backend.owner_layout is None:
        raise C0LawError("control capture needs the world's generated layout")
    by_seat = {item.symbol: item for item in seats}
    mode = (
        "manual"
        if game_form is None
        else {
            _EventJumpForm: "event_jump_stop",
            _ActionValueForm: "action_value_event_jump",
        }.get(type(game_form))
    )
    if mode is None or (mode == "action_value_event_jump") != (action_value_policy is not None):
        raise C0LawError("control capture has inconsistent selected policy")
    action_values = []
    for item in () if action_value_policy is None else action_value_policy.seats:
        seat = by_seat[item.seat]
        if (
            item.owner != backend.owner_layout.owner(seat.actor).owner.key
            or type(item.projector) is not _C0ActionValueProjector
        ):
            raise C0LawError("control projection differs from its declared Actor")
        action_values.append(
            C0ActionValueSeatIR(
                item.seat,
                backend.capture(item.projector.value),
                tuple((name, backend.capture(costs[name].value)) for name in seat.entries),
            )
        )
    return C0ControlIR(
        world,
        seats,
        mode,
        () if game_form is None else game_form.seats,
        None if game_form is None else game_form.end_at,
        game_form.wake_at if type(game_form) is _EventJumpForm else (),
        None if action_value_policy is None else action_value_policy.max_same_time_actions,
        tuple(action_values),
        tuple(
            C0WorldStopIR(item.outcome, item.owners, backend.capture(item.predicate))
            for item in (game_form.world_stops if type(game_form) is _ActionValueForm else ())
        ),
        tuple(
            C0AppraisalProfileIR(
                profile.name,
                profile.seat,
                profile.fallback_entry,
                profile.tie_order,
                tuple(
                    C0AppraisalRuleIR(
                        rule.entry,
                        rule.mode,
                        None if rule.value is None else backend.capture(rule.value),
                    )
                    for rule in profile.rules
                ),
            )
            for profile in appraisals
        ),
        None if opening is None else backend.capture(opening),
    )


def bind_control(ir: C0ControlIR, world: C0BoundWorld) -> C0BoundControl:
    """Realize control using the exact bound world's Actions and owner layout."""
    if type(ir) is not C0ControlIR or type(world) is not C0BoundWorld or ir.world is not world.ir:
        raise C0LawError("control binding needs the exact selected world")
    ir.__post_init__()
    world.layout.check(ir.world)
    backend = C0ValueBackend(world.layout.owners.record_layout, world.layout.owners)
    owners = {item.symbol: item.owner for item in world.layout.owners.owners}
    declarations = {item.symbol: item for item in world.ir.signatures.owners}
    seats = {item.symbol: item for item in ir.seats}
    actions = dict(world.actions)
    for seat in ir.seats:
        if any(actions[name].actor_owner is not owners[seat.actor] for name in seat.entries):
            raise C0LawError("control entry is not owned by its declared Actor")
    policy = None if world.temporal_binding is None else world.temporal_binding.policy
    opening = None if ir.opening is None else backend.bind(ir.opening)
    if opening is not None and opening._ports.roots != {
        name: owner.state_type for name, owner in owners.items()
    }:
        raise C0LawError("startup assertion has foreign owner roots")
    costs, projections = [], []
    for item in ir.action_values:
        seat = seats.get(item.seat)
        if (
            seat is None
            or item.seat not in ir.controlled
            or tuple(name for name, _ in item.costs) != seat.entries
        ):
            raise C0LawError("control costs do not cover the declared seat entries")
        projection = backend.bind(item.projection)
        if (
            projection._ports.roots != {"actor": owners[seat.actor].state_type}
            or projection._ports.outputs
            != {
                "tempo": int,
                "eligible": bool,
            }
            or projection._admission_outputs != frozenset({"tempo", "eligible"})
            or not projection._ports.readable_paths
            <= {f"actor.{path}" for path in declarations[seat.actor].seat_readable_paths}
            or projection._ports.admission_readable_paths != projection._ports.readable_paths
        ):
            raise C0LawError("control projection crosses its nominal Actor port")
        for name, value in item.costs:
            action, cost = actions[name], backend.bind(value)
            if cost._ports != replace(
                action.value._ports, outputs={"cost": int}
            ) or cost._admission_outputs != frozenset({"cost"}):
                raise C0LawError("control cost differs from its Action admission ports")
            costs.append(
                (
                    name,
                    _C0ActionCostProjector(
                        action._cost_basis(),
                        cost,
                        _K0CapabilityRef(f"c0.owner_graph.action_cost.{name}.v1"),
                    ),
                )
            )
        projections.append(
            _K0ActionValueSeat(
                item.seat,
                owners[seat.actor].key,
                tuple(actions[name].source_key for name in seat.entries),
                _C0ActionValueProjector(
                    projection, _K0CapabilityRef(f"c0.owner_graph.action_value.{item.seat}.v1")
                ),
            )
        )
    stops = []
    for item in ir.world_stops:
        predicate = backend.bind(item.predicate)
        if (
            not item.owners
            or not set(item.owners) <= set(owners)
            or len(set(item.owners)) != len(item.owners)
            or predicate._ports.roots != {name: owners[name].state_type for name in item.owners}
            or predicate._ports.outputs != {"valid": bool}
            or predicate._admission_outputs
            or predicate._ports.admission_readable_paths != predicate._ports.readable_paths
            or predicate._ports.writable_fields
            or predicate.effects
            or predicate._tree["bindings"]
            or predicate._tree["outputs"]["valid"].operation != "const"
            or predicate._tree["outputs"]["valid"].operand is not True
        ):
            raise C0LawError("control stop has foreign owner roots")
        stops.append(_WorldStop(item.outcome, item.owners, predicate))
    form = action_policy = None
    if ir.mode == "manual":
        if (
            ir.controlled
            or ir.end_at is not None
            or ir.wake_at
            or projections
            or stops
            or ir.max_same_time_actions is not None
        ):
            raise C0LawError("manual control has undeclared scheduling")
    elif ir.mode == "event_jump_stop":
        if (
            policy is None
            or not ir.controlled
            or not set(ir.controlled) <= set(ir.world.temporal.advance_seats)
            or projections
            or stops
            or ir.max_same_time_actions is not None
        ):
            raise C0LawError("event-jump control differs from its temporal contract")
        form = _EventJumpForm(ir.controlled, ir.end_at, ir.wake_at)
    else:
        if (
            policy is None
            or ir.world.temporal.mechanism != "action_value_event_jump"
            or not ir.controlled
            or tuple(item.seat for item in projections) != ir.controlled
            or ir.wake_at
        ):
            raise C0LawError("action-value control differs from its temporal contract")
        try:
            policy = replace(
                policy,
                pre_due_action_sources=tuple(
                    source for item in projections for source in item.action_sources
                ),
            )
            action_policy = _K0ActionValuePolicy(
                _K0CapabilityRef("c0.owner_graph.action_value_scheduler.v1"),
                tuple(projections),
                None if ir.end_at is None else _K0FixedTime(ir.end_at),
                ir.max_same_time_actions,
            )
        except K0ProfileError as error:
            raise C0LawError("control cannot bind its action-value policy") from error
        # Stops have one executable authority: the selected K0 policy.
        form = _ActionValueForm(ir.controlled, ir.end_at)
    appraisals = []
    for profile in ir.appraisals:
        seat = seats.get(profile.seat)
        if (
            seat is None
            or profile.seat not in ir.controlled
            or ir.mode != "action_value_event_jump"
        ):
            raise C0LawError("control appraisal names an uncontrolled seat")
        if (
            set(profile.tie_order) != set(seat.entries)
            or len(profile.tie_order) != len(seat.entries)
            or {rule.entry for rule in profile.rules} != set(seat.entries)
            or len(profile.rules) != len(seat.entries)
            or profile.fallback_entry not in seat.entries
        ):
            raise C0LawError("control appraisal does not cover its declared entries")
        rules = []
        for rule in profile.rules:
            value = None if rule.value is None else backend.bind(rule.value)
            if (
                rule.mode not in ("score", "default", "ignore")
                or (rule.mode == "score") != (value is not None)
                or (rule.entry == profile.fallback_entry and rule.mode != "default")
                or (
                    value is not None
                    and (
                        value._ports.roots
                        != {
                            "actor": owners[seat.actor].state_type,
                            "payload": actions[rule.entry].payload_type,
                        }
                        or value._ports.outputs != {"score": int}
                        or value._admission_outputs != frozenset({"score"})
                        or not value._ports.readable_paths
                        <= (
                            {
                                f"actor.{path}"
                                for path in declarations[seat.actor].seat_readable_paths
                            }
                            | {
                                f"payload.{field}"
                                for field in actions[rule.entry].payload_type.__dataclass_fields__
                            }
                        )
                        or value._ports.admission_readable_paths != value._ports.readable_paths
                    )
                )
            ):
                raise C0LawError("control appraisal crosses its Actor/payload contract")
            rules.append(C0AppraisalRule(rule.entry, rule.mode, value))
        appraisals.append(
            C0FiniteAppraisalProfile(
                profile.name,
                profile.seat,
                profile.fallback_entry,
                profile.tie_order,
                tuple(rules),
            )
        )
    terminal_policy = (
        None
        if not stops
        else _K0TerminalPolicy(
            _K0CapabilityRef("c0.owner_graph.terminal.v1"),
            tuple(
                _K0TerminalClause(
                    stop.outcome,
                    tuple(owners[name].key for name in stop.owners),
                    _C0TerminalProjector(
                        stop.owners,
                        stop.predicate,
                        _K0CapabilityRef(f"c0.owner_graph.terminal.{stop.outcome}.v1"),
                    ),
                )
                for stop in stops
            ),
        )
    )
    return C0BoundControl(
        ir, form, opening, policy, action_policy, terminal_policy, tuple(costs), tuple(appraisals)
    )
