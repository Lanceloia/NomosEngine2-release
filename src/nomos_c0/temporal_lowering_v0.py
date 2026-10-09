"""Lower a checked temporal/due subgraph into one private K0 binding."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0ProfileError, K0SourceSpecKey
from nomos_kernel._atomic_inmemory_session import _K0InMemorySourceSpec
from nomos_kernel._event_jump_abi import _K0OrderedTemporalPolicy, _K0PeriodicDuePlan
from nomos_kernel._owner_abi import _K0CapabilityRef

from .author_contract_v1 import C0LawError
from .scheduled_scene_event_v1 import C0ScheduledSceneProgram
from .semantic_ir_v0 import C0TemporalProgramIR


@dataclass(frozen=True)
class C0LoweredTemporal:
    policy: _K0OrderedTemporalPolicy
    due_specs: tuple[_K0InMemorySourceSpec, ...]
    periodic_names: tuple[tuple[str, _K0CapabilityRef], ...]


def lower_temporal_program(
    ir: C0TemporalProgramIR,
    dues: tuple[tuple[str, C0ScheduledSceneProgram], ...],
) -> C0LoweredTemporal:
    if type(ir) is not C0TemporalProgramIR or type(dues) is not tuple:
        raise C0LawError("temporal Program IR or due carrier is malformed")
    try:
        ir.check()
    except ValueError as error:
        raise C0LawError(str(error)) from error
    if len(dues) != len(ir.due_laws) or any(
        name != ir_name or type(program) is not C0ScheduledSceneProgram or program.ir is not law
        for (name, program), (ir_name, law) in zip(dues, ir.due_laws, strict=True)
    ):
        raise C0LawError("temporal Program IR differs from its checked due carriers")
    by_name = dict(ir.due_laws)
    try:
        plans = tuple(
            _K0PeriodicDuePlan(
                _K0CapabilityRef(f"c0.owner_graph.periodic.{plan.name}.v1"),
                K0SourceSpecKey(by_name[plan.due].source_key),
                plan.interval,
                plan.max_occurrences,
                plan.subject,
            )
            for plan in ir.periodic
        )
        policy = _K0OrderedTemporalPolicy(
            _K0CapabilityRef(f"c0.owner_graph.{ir.mechanism}.v1"),
            tuple(K0SourceSpecKey(by_name[name].source_key) for name in ir.order),
            ir.max_pending,
            plans,
        )
        specs = tuple(program.build_spec() for _, program in dues)
    except K0ProfileError as error:
        raise C0LawError("temporal Program IR cannot bind to K0") from error
    return C0LoweredTemporal(
        policy,
        specs,
        tuple(
            (plan.name, lowered.capability_ref)
            for plan, lowered in zip(ir.periodic, plans, strict=True)
        ),
    )
