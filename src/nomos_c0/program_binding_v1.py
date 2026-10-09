"""The Program backend assembles one actual private K0 profile from checked IR."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from nomos_kernel import K0OccurrenceFamily, K0ProfileError
from nomos_kernel._atomic_inmemory_session import _K0InMemoryProfile

from .actor_template_v1 import bind_actor_templates
from .author_contract_v1 import C0LawError
from .composable_action_v1 import C0SelfActorPorts
from .control_binding_v1 import bind_control
from .event_formation_v2 import C0FormationEntry, bind_event_formations
from .object_owner_binding_v1 import ObjectOwnerPort, _bind_object_owner_plan, plan_object_owners
from .opening_construction_v1 import bind_constructions
from .program_ir_v1 import C0ProgramIR
from .visibility_binding_v1 import bind_visibility
from .world_binding_v1 import C0WorldLayout, bind_world

if TYPE_CHECKING:
    from .program_runtime_v1 import C0OwnerGraphProgram


def bind_program(ir: C0ProgramIR, layout: C0WorldLayout) -> C0OwnerGraphProgram:
    """No Source, Assets, parsing or type inference crosses this boundary."""
    from .program_runtime_v1 import C0OwnerGraphProgram

    if type(ir) is not C0ProgramIR or type(layout) is not C0WorldLayout:
        raise C0LawError("Program binding requires checked IR and generated world layout")
    ir.__post_init__()
    world = bind_world(ir.world, layout)
    control = bind_control(ir.control, world)
    visibility = bind_visibility(ir.visibility, world)
    actor_templates = bind_actor_templates(ir.actor_templates, world)
    kinds = {item.symbol: item for item in layout.owners.object_kinds}
    selected = tuple(kinds[name] for name in ir.world.selected_kinds)
    object_plan = (
        plan_object_owners(
            tuple(sorted(item.sort for item in selected)),
            tuple(
                ObjectOwnerPort(
                    item.sort, item.symbol, item.state_record, item.k0_kind.max_instances
                )
                for item in selected
            ),
        )
        if selected
        else None
    )
    costs = dict(control.action_costs)
    costs.update(pair for template in actor_templates for pair in template.costs)
    specs = [
        replace(
            action.build_spec(action_cost_projector=costs[name])
            if type(action.actor_owner) is C0SelfActorPorts
            else action.build_spec(),
            action_value_owner=(
                None if type(action.actor_owner) is C0SelfActorPorts else action.actor_owner.key
            ),
            action_cost_projector=costs[name],
        )
        if name in costs
        else action.build_spec()
        for name, action in world.actions
    ]
    laws, registered = [], set()
    for _, event in world.events:
        spec, causal = event.build()
        if spec.key not in registered:
            specs.append(spec)
            registered.add(spec.key)
        laws.append(causal)
    if world.temporal_binding is not None:
        specs.extend(world.temporal_binding.due_specs)
    temporal_policy = control.temporal_policy
    if actor_templates:
        temporal_policy = replace(
            temporal_policy,
            pre_due_action_sources=(
                *temporal_policy.pre_due_action_sources,
                *(source for item in actor_templates for source in item.kind.action_sources),
            ),
        )
    try:
        profile = _K0InMemoryProfile(
            tuple(item.owner for item in layout.owners.owners),
            tuple(specs),
            tuple(laws),
            len(world.events) + max(1, len(world.dues)),
            len(world.events),
            temporal_policy=temporal_policy,
            dynamic_owner_kinds=_bind_object_owner_plan(object_plan, selected),
            action_value_policy=control.action_value_policy,
            terminal_policy=control.terminal_policy,
            actor_kinds=tuple(item.kind for item in actor_templates),
        )
    except K0ProfileError as error:
        raise C0LawError("checked Program does not form a K0 profile") from error
    formation_plan = None
    if ir.event_formations is not None:
        claims = {rule.result_entry: rule.trigger_entry for rule in ir.event_formations.rules}
        entries = [
            C0FormationEntry(name, action.source_key, action.event_type, K0OccurrenceFamily.ACTION)
            for name, action in world.actions
        ]
        entries.extend(
            C0FormationEntry(
                name,
                event.ports.source_key,
                event.ports.event_type,
                K0OccurrenceFamily.EVENT,
                event.ports.causal_key,
                claims.get(name),
            )
            for name, event in world.events
        )
        entries.extend(
            C0FormationEntry(
                name,
                due.ports.source_key,
                due.ports.event_type,
                K0OccurrenceFamily.EVENT,
                trigger_entry=next(
                    (
                        action_name
                        for action_name, action in world.actions
                        if action.schedule is not None
                        and action.schedule.due_source == due.ports.source_key.value
                    ),
                    None,
                ),
            )
            for name, due in world.dues
        )
        formation_plan = bind_event_formations(ir.event_formations, tuple(entries), profile)
    temporal = ir.world.temporal
    return C0OwnerGraphProgram._from_binding(
        owners=layout.owners.owners,
        actions=world.actions,
        events=world.events,
        seats=visibility.seats,
        profile=profile,
        advance_seats=frozenset(temporal.advance_seats) if temporal is not None else frozenset(),
        game_form=control.game_form,
        opening_guard=control.opening,
        formation_plan=formation_plan,
        object_kinds=selected,
        object_plan=object_plan,
        periodic_plans=(
            world.temporal_binding.periodic_names if world.temporal_binding is not None else ()
        ),
        appraisal_profiles=control.appraisals,
        due_laws=world.dues,
        temporal_ir=world.temporal_ir,
        world_layout=layout,
        program_ir=ir,
        actor_templates=actor_templates,
        opening_constructions=bind_constructions(
            ir.opening_constructions, dict(layout.owners.record_layout.records), selected
        ),
    )
