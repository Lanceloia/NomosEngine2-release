"""Check Lib and Source into Program IR and layout; never allocate a Session."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import get_args, get_origin, get_type_hints

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._action_value_abi import (
    _K0ActionValuePolicy,
    _K0ActionValueSeat,
)
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._dynamic_owner_abi import (
    _K0DynamicOwnerKind,
)
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0Owner,
    _K0SameWaveEffectProofOwner,
)

from .actor_binding_v1 import expand_actor_bindings
from .actor_product_v1 import bind_actor_product
from .appraisal_definition_v1 import C0AppraisalDefinitions
from .author_contract_v1 import C0LawError, _unique_object
from .author_document_v1 import C0AssembledSource, C0AuthorDocument, C0OriginFrame, C0SourceContext
from .candidate_input_v1 import (
    C0CandidateInputPorts,
    check_candidate_input,
    compile_candidate_check,
)
from .checked_value_binding_v1 import _WorldValueBuilder
from .compile_budget_v1 import COMPILE_BUDGET
from .composable_action_v1 import (
    C0ActionFormPorts,
    C0SelfActorPorts,
    C0ValueActionPorts,
    C0ValueActionProgram,
    compile_composable_action,
)
from .composable_value_v1 import (
    _MAX_INT,
    C0ValuePorts,
    _complete_record_paths,
    _complete_value_fields,
    compile_value_program,
)
from .control_binding_v1 import (
    _ActionValueForm,
    _C0ActionCostProjector,
    _C0ActionValueProjector,
    _EventJumpForm,
    _WorldStop,
    capture_control,
)
from .control_ir_v1 import C0ControlSeatIR
from .direct_actor_event_v1 import (
    C0DirectActorPorts,
    compile_direct_actor_event,
)
from .direct_scene_event_v1 import (
    C0DirectScenePorts,
    C0DirectSceneProgram,
    compile_direct_scene_event,
)
from .event_formation_v2 import (
    check_event_formations,
)
from .finite_appraisal_v1 import (
    compile_finite_appraisal,
)
from .graph_contracts_v1 import (
    C0GraphAction,
    C0GraphDue,
    C0GraphEvent,
    C0GraphLibrary,
    C0GraphObjectKind,
    C0GraphOperation,
    C0GraphOwner,
)
from .lawdef_binding_v1 import C0LawDefinitions
from .nominal_fields_v1 import _leaf_type
from .nominal_types_v1 import (
    IRValidationError,
    ObjectSortHierarchy,
    ObjectSortRef,
    ObjectSortSpecialization,
)
from .object_owner_binding_v1 import ObjectOwnerPlanError, ObjectOwnerPort, plan_object_owners
from .object_product_v1 import bind_object_product
from .opening_construction_v1 import compile_constructions
from .program_ir_v1 import C0ProgramIR
from .scheduled_scene_event_v1 import (
    C0ScheduledScenePorts,
    C0ScheduledSceneProgram,
    compile_scheduled_scene_event,
)
from .seat_offer_preview_v0 import C0SeatOfferPreview, C0SeatOfferPreviewPorts
from .seat_offers_v0 import (
    C0FiniteOfferProvider,
    compile_seat_offers,
)
from .seat_read_projection_v0 import C0SeatReadPorts, C0SeatReadProjection
from .semantic_ir_v0 import C0PeriodicFormationIR, C0TemporalProgramIR
from .source_schema_v1 import SOURCE_REQUIRED, SOURCE_SECTIONS
from .temporal_lowering_v0 import lower_temporal_program
from .visibility_binding_v1 import _Seat, capture_visibility
from .visibility_ir_v1 import C0SeatPresentation, presentation_scalar_kind
from .world_binding_v1 import C0WorldLayout, capture_world


def _row(
    value: object, keys: set[str], label: str, *, optional: set[str] | None = None
) -> dict[str, object]:
    optional = optional or set()
    if type(value) is not dict or not keys <= set(value) or not set(value) <= keys | optional:
        raise C0LawError(f"{label} has missing or unknown fields")
    return value


def _source(
    value: str | dict[str, object] | C0AuthorDocument | C0AssembledSource,
) -> dict[str, object]:
    if type(value) in (C0AuthorDocument, C0AssembledSource):
        value = value.to_data()
    if type(value) is str:
        if not value or len(value) > 262144:
            raise C0LawError("owner graph Source is empty or too large")
        try:
            value = json.loads(value, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError) as error:
            raise C0LawError("owner graph Source is malformed JSON") from error
    if (
        type(value) is not dict
        or not SOURCE_REQUIRED <= set(value)
        or set(value) - SOURCE_SECTIONS - {"schema"}
        or ("due_events" in value) != ("temporal" in value)
    ):
        raise C0LawError("owner graph Source has missing or unknown fields")
    return value


def _owner_guard_ports(owners: tuple[C0GraphOwner, ...], pure_definitions=()) -> C0ValuePorts:
    roots = {item.symbol: item.owner.state_type for item in owners}
    readable = frozenset().union(
        *(_complete_record_paths(symbol, carrier) for symbol, carrier in roots.items())
    )
    selected_fields: dict[type, set[str]] = {}
    for carrier in roots.values():
        selected_fields.setdefault(carrier, set()).update(get_type_hints(carrier))
        for annotation in get_type_hints(carrier).values():
            for nested, names in _complete_value_fields(annotation).items():
                selected_fields.setdefault(nested, set()).update(names)
    fields_by_type = {carrier: frozenset(names) for carrier, names in selected_fields.items()}
    return C0ValuePorts(
        roots=roots,
        readable_paths=frozenset(readable),
        admission_readable_paths=frozenset(readable),
        readable_fields=fields_by_type,
        admission_readable_fields=fields_by_type,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"valid": bool},
        pure_definitions=pure_definitions,
    )


def _selected_actor_kinds(library, row):
    templates = row.get("actor_templates", [])
    if type(templates) is not list or len(templates) > 64:
        raise C0LawError("Source Actor templates must be finite")
    kinds = {kind.symbol: kind for kind in library.actor_kinds}
    selected = {}
    for template in templates:
        if (
            type(template) is not dict
            or type(template.get("kind")) is not str
            or template["kind"] not in kinds
            or template["kind"] in selected
        ):
            raise C0LawError("Source Actor template selects an unknown or duplicate kind")
        selected[template["kind"]] = kinds[template["kind"]]
    return selected


def _compile_due_programs(
    row, library, due_map, bind_law, compiled, selected_kinds, owner_map, value_builder
):
    dues: list[tuple[str, C0ScheduledSceneProgram]] = []
    temporal_ir = None
    if "temporal" in row:
        due_rows = row["due_events"]
        if type(due_rows) is not list or not 0 <= len(due_rows) <= 64:
            raise C0LawError("Source needs finite due Event instances")
        for raw in due_rows:
            if type(raw) is not dict:
                raise C0LawError("Source due Event has missing or unknown fields")
            due_row = _row(
                raw,
                {
                    "name",
                    "template",
                    "form",
                    "source_key",
                    "event_type",
                    "when_false",
                    "law",
                }
                | ({"owner_bindings"} if "owner_bindings" in raw else set())
                | ({"actor_product"} if "actor_product" in raw else set())
                | ({"actor_domain_effects"} if "actor_domain_effects" in raw else set()),
                "Source due Event",
            )
            name = due_row["name"]
            template_name = due_row["template"]
            template = due_map.get(template_name) if type(template_name) is str else None
            if (
                type(name) is not str
                or not name
                or template is None
                or any(name == prior for prior, _ in dues)
            ):
                raise C0LawError("Source due Event template or instance is foreign or repeated")
            if (
                type(template.ports) is not C0ScheduledScenePorts
                or type(template.ports.source_key) is not K0SourceSpecKey
                or type(template.ports.event_type) is not K0EventTypeKey
            ):
                raise C0LawError("Lib due Event template identity or ports are malformed")
            try:
                ports = replace(
                    template.ports,
                    source_key=K0SourceSpecKey(due_row["source_key"]),
                    event_type=K0EventTypeKey(due_row["event_type"]),
                )
            except (TypeError, K0ProfileError) as error:
                raise C0LawError("Source due Event instance identity is malformed") from error
            if not any(
                ports.scene_owner is item.owner and item.identity_field is None
                for item in library.owners
            ):
                raise C0LawError("due Event Scene owner is outside this graph")
            if any(
                not any(owner is item.owner for item in library.owners)
                for _, owner in ports.extra_owners
            ):
                raise C0LawError("due Event owner root is outside this graph")
            if any(
                family not in {kind.symbol for kind in selected_kinds}
                for _, family, _ in ports.fixed_individual_roots
            ):
                raise C0LawError("due Event fixed Object kind is not selected by Source")
            if any(domain.kind not in selected_kinds for domain in ports.read_object_domains):
                raise C0LawError("due read Object-domain kind is not selected by Source")
            bindings = due_row.get("owner_bindings")
            if bindings is not None:
                if type(bindings) is not dict or set(bindings) != {
                    name for name, _ in ports.extra_owners
                }:
                    raise C0LawError("due Event owner bindings do not fill declared roots")
                rebound = []
                for root_name, exemplar in ports.extra_owners:
                    target_name = bindings[root_name]
                    target = owner_map.get(target_name) if type(target_name) is str else None
                    exemplar_decl = next(
                        (item for item in library.owners if item.owner is exemplar), None
                    )
                    if (
                        target is None
                        or exemplar_decl is None
                        or target.identity_field != exemplar_decl.identity_field
                        or target.owner.state_type is not exemplar.state_type
                        or target.owner.view_type is not exemplar.view_type
                        or target.owner.contribution_type is not exemplar.contribution_type
                    ):
                        raise C0LawError("due Event owner binding has a foreign type")
                    rebound.append((root_name, target.owner))
                ports = replace(ports, extra_owners=tuple(rebound))
            if "actor_product" in due_row:
                ports = replace(
                    ports,
                    actor_product=bind_actor_product(
                        due_row["actor_product"], _selected_actor_kinds(library, row)
                    ),
                )
            bound = bind_law("due_event", due_row["law"], due_row, "due_events", template_name)
            body = bound.body
            ports = replace(
                ports, value_ports=replace(ports.value_ports, source_context=bound.context)
            )
            from .actor_domain_v1 import C0ActorDomainEffect

            raw_domains = due_row.get("actor_domain_effects", [])
            if type(raw_domains) is not list or len(raw_domains) != len(ports.actor_domains):
                raise C0LawError("Source due does not fill its exact Actor domain effects")
            domain_ports = {item.name: item for item in ports.actor_domains}
            checked_domains = []
            for index, raw_domain in enumerate(raw_domains):
                requested = _row(raw_domain, {"name", "law"}, "Source due Actor effect")
                port = (
                    domain_ports.get(requested["name"]) if type(requested["name"]) is str else None
                )
                if (
                    port is None
                    or port.kind.symbol not in _selected_actor_kinds(library, row)
                    or any(prior.ports.name == port.name for prior in checked_domains)
                ):
                    raise C0LawError("Source due Actor effect has an unselected/duplicate domain")
                domain_body = bind_law(
                    "due_event",
                    requested["law"],
                    due_row,
                    "due_events",
                    template_name,
                    suffix=("actor_domain_effects", index, "law"),
                )
                domain_value = compile_value_program(
                    json.dumps(domain_body.body["law"]),
                    replace(port.value_ports, source_context=domain_body.context),
                    state_outputs={f"actor.{field}": output for field, output in port.effects},
                )
                checked_domains.append(
                    C0ActorDomainEffect(
                        replace(port, value_ports=domain_value._ports),
                        domain_value,
                        port.effects,
                    )
                )
            ports = replace(ports, actor_domains=tuple(item.ports for item in checked_domains))
            expanded = {
                key: value
                for key, value in due_row.items()
                if key
                not in ("template", "owner_bindings", "actor_product", "actor_domain_effects")
            }
            expanded["law"] = body["law"]
            expanded["effect"] = {}
            for root, field, alias in template.effects:
                expanded["effect"].setdefault(root, {})[field] = alias
            due_program = compile_scheduled_scene_event(
                expanded, ports, actor_domains=tuple(checked_domains)
            )
            dues.append((name, value_builder.transition(name, due_program)))
        raw_time = row["temporal"]
        if type(raw_time) is not dict:
            raise C0LawError("temporal mechanism has missing or unknown fields")
        mechanism = raw_time.get("mechanism")
        time_keys = (
            {"mechanism", "order", "max_pending", "advance_seats"}
            if mechanism == "ordered_due_microsteps"
            else {"mechanism", "order", "max_pending", "periodic"}
        )
        time_row = _row(raw_time, time_keys, "temporal mechanism")
        order = time_row["order"]
        selected_seats = time_row.get("advance_seats", [])
        if (
            mechanism not in ("ordered_due_microsteps", "action_value_event_jump")
            or type(order) is not list
            or len(order) != len(dues)
            or any(type(name) is not str for name in order)
            or len(set(order)) != len(order)
            or set(order) != {name for name, _ in dues}
            or type(time_row["max_pending"]) is not int
            or not 0 <= time_row["max_pending"] <= len(dues)
            or (not dues) != (time_row["max_pending"] == 0)
            or (
                mechanism == "ordered_due_microsteps"
                and (
                    not dues
                    or type(selected_seats) is not list
                    or not selected_seats
                    or any(type(name) is not str for name in selected_seats)
                    or len(set(selected_seats)) != len(selected_seats)
                )
            )
        ):
            raise C0LawError("temporal mechanism is not a closed finite selection")
        periodic = []
        if mechanism == "action_value_event_jump":
            raw_periodic = time_row["periodic"]
            if type(raw_periodic) is not list or len(raw_periodic) > len(dues):
                raise C0LawError("periodic Event plans are not a closed finite selection")
            names = set()
            for raw_plan in raw_periodic:
                plan_row = _row(
                    raw_plan,
                    {"name", "due", "interval", "max_occurrences", "subject"},
                    "periodic Event plan",
                )
                name = plan_row["name"]
                due_name = plan_row["due"]
                if (
                    type(name) is not str
                    or not name
                    or name in names
                    or type(due_name) is not str
                    or due_name not in dict(dues)
                    or type(plan_row["subject"]) is not str
                    or not plan_row["subject"]
                ):
                    raise C0LawError("periodic Event plan identity is foreign or repeated")
                names.add(name)
                periodic.append(
                    C0PeriodicFormationIR(
                        name,
                        due_name,
                        plan_row["interval"],
                        plan_row["max_occurrences"],
                        plan_row["subject"],
                    )
                )
        temporal_ir = C0TemporalProgramIR(
            mechanism,
            tuple((name, due.ir) for name, due in dues),
            tuple(order),
            time_row["max_pending"],
            tuple(periodic),
            tuple(
                action.schedule.due_source for _, action in compiled if action.schedule is not None
            ),
            tuple(selected_seats),
        )
        try:
            temporal_ir.check()
        except ValueError as error:
            raise C0LawError(str(error)) from error
    elif any(action.schedule is not None for _, action in compiled):
        raise C0LawError("scheduled Action needs a selected time mechanism")
    return dues, temporal_ir


def check_owner_graph(
    library: C0GraphLibrary, source: str | dict[str, object] | C0AuthorDocument | C0AssembledSource
) -> tuple[C0ProgramIR, C0WorldLayout]:
    """Check an authored graph without assembling its executable K0 profile."""
    return _check_graph_declarations(library, source)


def _check_graph_declarations(
    library: C0GraphLibrary, source: str | dict[str, object] | C0AuthorDocument | C0AssembledSource
) -> tuple[C0ProgramIR, C0WorldLayout]:
    if (
        type(library) is not C0GraphLibrary
        or type(library.owners) is not tuple
        or type(library.actions) is not tuple
        or type(library.events) is not tuple
        or type(library.due_events) is not tuple
        or type(library.object_kinds) is not tuple
        or type(library.operations) is not tuple
        or type(library.seat_read_ports) is not tuple
        or type(library.seat_offer_preview_ports) is not tuple
        or type(library.candidate_inputs) is not tuple
        or not library.owners
        or not library.actions
    ):
        raise C0LawError("owner graph needs a closed Lib")
    value_builder = _WorldValueBuilder(library.value_backend)
    owner_layout = library.value_backend.owner_layout
    if (
        owner_layout is None
        or library.owners != owner_layout.owners
        or library.object_kinds != owner_layout.object_kinds
    ):
        raise C0LawError("graph Lib substituted or omitted its generated owner bindings")
    owner_layout.check(library.value_backend.layout.signatures)
    if (
        any(type(item) is not C0GraphOwner for item in library.owners)
        or any(type(item) is not C0GraphAction for item in library.actions)
        or any(type(item) is not C0GraphEvent for item in library.events)
        or any(type(item) is not C0GraphDue for item in library.due_events)
        or any(type(item) is not C0GraphObjectKind for item in library.object_kinds)
        or any(type(item) is not C0GraphOperation for item in library.operations)
        or any(
            type(item.symbol) is not str
            or not item.symbol
            or type(item.receiver) is not ObjectSortRef
            or type(item.template) is not str
            or item.template not in {action.symbol for action in library.actions}
            or type(item.implementations) is not tuple
            or not item.implementations
            or any(
                type(implementation) is not tuple
                or len(implementation) != 2
                or any(type(value) is not str or not value for value in implementation)
                for implementation in item.implementations
            )
            or len(dict(item.implementations)) != len(item.implementations)
            for item in library.operations
        )
        or any(
            type(item.symbol) is not str
            or not item.symbol
            or type(item.sort) is not ObjectSortRef
            or type(item.state_record) is not str
            or not item.state_record
            or type(item.k0_kind) is not _K0DynamicOwnerKind
            or item.k0_kind.family != item.symbol
            or item.k0_kind.state_type.__name__ != item.state_record
            or type(item.specializes) is not tuple
            or any(type(parent) is not ObjectSortRef for parent in item.specializes)
            for item in library.object_kinds
        )
        or any(type(item.symbol) is not str or not item.symbol for item in library.owners)
        or any(type(item.symbol) is not str or not item.symbol for item in library.actions)
        or any(type(item.symbol) is not str or not item.symbol for item in library.events)
        or any(type(item.symbol) is not str or not item.symbol for item in library.due_events)
        or any(type(item) is not C0SeatReadPorts for item in library.seat_read_ports)
        or any(
            type(item) is not C0SeatOfferPreviewPorts for item in library.seat_offer_preview_ports
        )
        or any(type(item.actor) is not str or not item.actor for item in library.actions)
        or any(type(item) is not C0CandidateInputPorts for item in library.candidate_inputs)
    ):
        raise C0LawError("Lib template declaration is malformed")
    provider = library.offer_provider
    if (
        type(provider) is not C0FiniteOfferProvider
        or type(provider.symbol) is not str
        or not provider.symbol
        or type(provider.version) is not str
        or not provider.version
        or type(provider.max_candidates) is not int
        or not 1 <= provider.max_candidates <= COMPILE_BUDGET.finite_offers
    ):
        raise C0LawError("Lib offer provider is not a bounded closed declaration")
    owner_map = {item.symbol: item for item in library.owners}
    action_map = {item.symbol: item for item in library.actions}
    candidate_symbols = set()
    for port in library.candidate_inputs:
        if (
            type(port.symbol) is not str
            or not port.symbol
            or port.symbol in candidate_symbols
            or type(port.action_template) is not str
            or port.action_template not in action_map
            or type(port.value_ports) is not C0ValuePorts
        ):
            raise C0LawError("candidate input needs one closed Action template and identity")
        check_candidate_input(action_map[port.action_template].ports, port.value_ports)
        candidate_symbols.add(port.symbol)
    event_map = {item.symbol: item for item in library.events}
    due_map = {item.symbol: item for item in library.due_events}
    if (
        len(owner_map) != len(library.owners)
        or len(action_map) != len(library.actions)
        or len(event_map) != len(library.events)
        or type(library.due_events) is not tuple
        or len(due_map) != len(library.due_events)
        or set(event_map) & set(due_map)
        or any(type(item.symbol) is not str or not item.symbol for item in library.owners)
        or any(type(item.symbol) is not str or not item.symbol for item in library.actions)
        or any(type(item.symbol) is not str or not item.symbol for item in library.events)
        or len({item.owner.key for item in library.owners}) != len(library.owners)
        or any(type(item.owner.key) is not K0OwnerKey for item in library.owners)
    ):
        raise C0LawError("Lib owner or Action symbols alias")
    for item in library.owners:
        if (
            not isinstance(item.owner, _K0Owner)
            or (
                item.identity_field is not None
                and get_type_hints(item.owner.state_type).get(item.identity_field) is not str
            )
            or type(item.seat_readable_paths) is not frozenset
            or any(
                type(path) is not str or _leaf_type(item.owner.view_type, path) is None
                for path in item.seat_readable_paths
            )
        ):
            raise C0LawError("Lib owner identity port is invalid")
    if len({item.symbol for item in library.seat_read_ports}) != len(library.seat_read_ports):
        raise C0LawError("Lib seat read projection symbols alias")
    if len({item.symbol for item in library.seat_offer_preview_ports}) != len(
        library.seat_offer_preview_ports
    ):
        raise C0LawError("Lib offer preview symbols alias")
    object_kinds = {item.symbol: item for item in library.object_kinds}
    for port in library.seat_read_ports:
        scene = owner_map.get(port.scene_owner)
        actor = owner_map.get(port.actor)
        kind = object_kinds.get(port.object_kind)
        if (
            type(port.symbol) is not str
            or not port.symbol
            or scene is None
            or scene.identity_field is not None
            or actor is None
            or actor.identity_field is None
            or kind is None
            or not isinstance(port.candidate_type, type)
            or type(port.collection_field) is not str
            or type(port.current_field) is not str
            or type(port.candidate_key) is not str
            or type(port.object_root) is not str
            or port.object_root in {"scene", "actor", "candidate"}
            or type(port.max_candidates) is not int
            or not 1 <= port.max_candidates <= 32
            or type(port.value_ports) is not C0ValuePorts
        ):
            raise C0LawError("Lib seat read projection is malformed")
        actor_hints = get_type_hints(actor.owner.view_type)
        candidate_args = get_args(actor_hints.get(port.collection_field))
        if (
            get_origin(actor_hints.get(port.collection_field)) is not tuple
            or candidate_args != (port.candidate_type, Ellipsis)
            or actor_hints.get(port.current_field) is not str
            or get_type_hints(port.candidate_type).get(port.candidate_key) is not str
            or dict(port.value_ports.roots)
            != {
                "scene": scene.owner.view_type,
                "actor": actor.owner.view_type,
                "candidate": port.candidate_type,
                port.object_root: kind.k0_kind.state_type,
            }
            or port.value_ports.writable_fields
            or port.value_ports.record_types
            or any(output not in (str, int, bool) for output in port.value_ports.outputs.values())
        ):
            raise C0LawError("Lib seat read projection exceeds its closed port")
    for port in library.seat_offer_preview_ports:
        scene = owner_map.get(port.scene_owner)
        actor = owner_map.get(port.actor)
        kind = object_kinds.get(port.object_kind)
        action = action_map.get(port.action_template)
        if (
            type(port.symbol) is not str
            or not port.symbol
            or scene is None
            or scene.identity_field is not None
            or actor is None
            or actor.identity_field is None
            or kind is None
            or action is None
            or action.actor != port.actor
            or not isinstance(port.candidate_type, type)
            or type(port.collection_field) is not str
            or type(port.current_field) is not str
            or type(port.candidate_origin_field) is not str
            or type(port.candidate_key) is not str
            or type(port.offer_payload_key) is not str
            or type(port.object_root) is not str
            or port.object_root in {"scene", "actor", "candidate"}
            or type(port.max_candidates) is not int
            or not 1 <= port.max_candidates <= 32
            or type(port.value_ports) is not C0ValuePorts
        ):
            raise C0LawError("Lib seat offer preview is malformed")
        actor_hints = get_type_hints(actor.owner.view_type)
        collection_type = actor_hints.get(port.collection_field)
        if (
            get_origin(collection_type) is not tuple
            or get_args(collection_type) != (port.candidate_type, Ellipsis)
            or actor_hints.get(port.current_field) is not str
            or get_type_hints(port.candidate_type).get(port.candidate_origin_field) is not str
            or get_type_hints(port.candidate_type).get(port.candidate_key) is not str
            or get_type_hints(action.ports.payload_type).get(port.offer_payload_key) is not str
            or dict(port.value_ports.roots)
            != {
                "scene": scene.owner.view_type,
                "actor": actor.owner.view_type,
                "candidate": port.candidate_type,
                port.object_root: kind.k0_kind.state_type,
            }
            or port.value_ports.writable_fields
            or port.value_ports.record_types
            or any(output not in (str, int, bool) for output in port.value_ports.outputs.values())
        ):
            raise C0LawError("Lib seat offer preview exceeds its closed port")
    graph_state_types = {item.owner.state_type for item in library.owners}
    try:
        object_hierarchy = (
            ObjectSortHierarchy(
                tuple(sorted(item.sort for item in library.object_kinds)),
                tuple(
                    sorted(
                        ObjectSortSpecialization(item.sort, parent)
                        for item in library.object_kinds
                        for parent in item.specializes
                    )
                ),
            )
            if library.object_kinds
            else None
        )
    except IRValidationError as error:
        raise C0LawError("Lib Object specialization is invalid") from error
    source_context = (
        source.context() if type(source) in (C0AuthorDocument, C0AssembledSource) else None
    )
    row = _source(source)
    binding_contexts = {
        (collection, item["name"]): source_context.at((collection, index))
        for collection in ("actions", "events", "due_events", "seats", "appraisal_profiles")
        if source_context is not None and type(row.get(collection)) is list
        for index, item in enumerate(row[collection])
        if type(item) is dict and type(item.get("name")) is str
    }
    temporal = "temporal" in row
    if row["schema"] != "c0.owner_graph.v6":
        raise C0LawError("owner graph Source schema is unknown")
    raw_kinds = row["object_kinds"] if "object_kinds" in row else []
    if type(raw_kinds) is not list or len(raw_kinds) > len(library.object_kinds):
        raise C0LawError("Source Object kind bindings are malformed")
    expected = {item.symbol: item for item in library.object_kinds}
    selected = {}
    for raw in raw_kinds:
        if type(raw) is not dict or set(raw) != {"kind", "sort"}:
            raise C0LawError("Source Object kind binding is malformed")
        kind = expected.get(raw["kind"]) if type(raw["kind"]) is str else None
        if kind is None or kind.symbol in selected or raw["sort"] != kind.sort.identity.value:
            raise C0LawError("Source Object kind binding differs from Lib")
        selected[kind.symbol] = kind
    selected_kinds = tuple(selected.values())
    if selected_kinds:
        try:
            sorts = tuple(sorted(item.sort for item in selected_kinds))
            plan_object_owners(
                sorts,
                tuple(
                    ObjectOwnerPort(
                        item.sort,
                        item.symbol,
                        item.state_record,
                        item.k0_kind.max_instances,
                    )
                    for item in selected_kinds
                ),
            )
        except (ObjectOwnerPlanError, ValueError) as error:
            raise C0LawError("Lib Object sorts cannot bind to owner kinds") from error
    if type(row["lawdefs"]) is not list:
        raise C0LawError("Source LawDefs must be a finite list")
    COMPILE_BUDGET.check("law_definitions", len(row["lawdefs"]), stage="Source declarations")
    try:
        library_lawdefs = [
            json.loads(item, object_pairs_hook=_unique_object) for item in library.lawdefs
        ]
    except (TypeError, ValueError) as error:
        raise C0LawError("checked Lib LawDefs are malformed") from error
    COMPILE_BUDGET.check(
        "law_definitions", len(library_lawdefs) + len(row["lawdefs"]), stage="Program LawDefs"
    )
    library_contexts = tuple(
        library.lib_context.at(("lawdefs", index)) if library.lib_context is not None else None
        for index in range(len(library_lawdefs))
    )
    definitions = C0LawDefinitions(
        [*library_lawdefs, *row["lawdefs"]],
        contexts=library_contexts
        + tuple(
            source_context.at(("lawdefs", index)) if source_context is not None else None
            for index in range(len(row["lawdefs"]))
        ),
    )
    library_definitions = (
        C0LawDefinitions(library_lawdefs, contexts=library_contexts) if library_lawdefs else None
    )
    try:
        library_appraisals = [
            json.loads(item, object_pairs_hook=_unique_object)
            for item in library.appraisal_definitions
        ]
    except (TypeError, ValueError) as error:
        raise C0LawError("checked Lib appraisal definitions are malformed") from error
    appraisal_definitions = C0AppraisalDefinitions(
        library_appraisals,
        contexts=tuple(
            library.lib_context.at(("appraisal_definitions", index))
            if library.lib_context is not None
            else None
            for index in range(len(library_appraisals))
        ),
    )

    def bind_law(family, use, declaration, collection, template, *, suffix=("law",), origins=()):
        name = declaration["name"]
        context = binding_contexts.get((collection, name))
        path = dict(context.aliases)[""] + suffix if context is not None else None
        span = context.index.spans.get(path) if context is not None else None
        binding = C0OriginFrame("source_binding", name, repr(path) if path else name, span)
        port_path = f"{collection}.{template}"
        port = C0OriginFrame(
            "port",
            template,
            port_path,
            library.ports_context.locate(port_path) if library.ports_context is not None else None,
        )
        return definitions.bind(
            family,
            use,
            binding=binding,
            port=port,
            origins=(*(context.frames if context is not None else ()), *origins),
        )

    def program_context(kind, name, aliases=None, *, context=None):
        base = context if context is not None else source_context
        if base is None:
            return None
        return C0SourceContext(
            base.index,
            tuple(aliases.items()) if aliases is not None else base.aliases,
            (*base.frames, C0OriginFrame(kind, name, kind)),
            base.scoped_frames,
        )

    operations = {item.symbol: item for item in library.operations}
    if len(operations) != len(library.operations):
        raise C0LawError("Lib operation identity is repeated")
    for operation in operations.values():
        kind = next(
            (item for item in library.object_kinds if item.sort == operation.receiver), None
        )
        template = action_map[operation.template]
        if (
            kind is None
            or template.ports.target is None
            or template.ports.target.state_type is not kind.k0_kind.state_type
            or library_definitions is None
        ):
            raise C0LawError("Lib operation does not match an Object Action port")
        for _, law in operation.implementations:
            library_definitions.instantiate("action", {"ref": law, "args": {}})
    raw_bindings = row.get("operation_bindings", [])
    if type(raw_bindings) is not list or len(raw_bindings) > 64:
        raise C0LawError("Source operation bindings are malformed")
    operation_bindings: dict[str, str] = {}
    operation_origins: dict[str, tuple[C0OriginFrame, ...]] = {}
    for binding_index, raw in enumerate(raw_bindings):
        binding = _row(raw, {"receiver_sort", "operation", "using"}, "Source binding")
        operation = (
            operations.get(binding["operation"]) if type(binding["operation"]) is str else None
        )
        if (
            operation is None
            or binding["operation"] in operation_bindings
            or binding["receiver_sort"] != operation.receiver.identity.value
            or operation.receiver not in {item.sort for item in selected_kinds}
            or type(binding["using"]) is not str
        ):
            raise C0LawError("Source operation binding is foreign or repeated")
        implementation = dict(operation.implementations).get(binding["using"])
        if implementation is None:
            raise C0LawError("Source operation implementation is not in Lib")
        operation_bindings[operation.symbol] = implementation
        selection_path = ("operation_bindings", binding_index, "using")
        operation_index = library.operations.index(operation)
        implementation_index = next(
            index
            for index, (name, _) in enumerate(operation.implementations)
            if name == binding["using"]
        )
        implementation_path = (
            f"operations[{operation_index}].implementations[{implementation_index}].law"
        )
        operation_origins[operation.symbol] = (
            C0OriginFrame(
                "operation_selection",
                operation.symbol,
                repr(selection_path),
                source_context.index.spans.get(selection_path) if source_context else None,
                (("using", binding["using"]), ("law", implementation)),
            ),
            C0OriginFrame(
                "operation_implementation",
                binding["using"],
                implementation_path,
                library.ports_context.locate(implementation_path)
                if library.ports_context
                else None,
            ),
        )
    if row["offer_provider"] != {"name": provider.symbol, "version": provider.version}:
        raise C0LawError("Source offer provider does not match Lib")
    domains = row.get("actor_domains", [])
    if type(domains) is not list:
        raise C0LawError("Source Actor domains are malformed")
    declared = row["owners"]
    if type(declared) is list:
        expanded_owners = []
        for item in declared:
            if type(item) is dict and set(item) == {"domain"}:
                domain = next(
                    (
                        entry
                        for entry in domains
                        if type(entry) is dict and entry.get("name") == item["domain"]
                    ),
                    None,
                )
                if domain is None or type(domain.get("owners")) is not list:
                    raise C0LawError("Source owner domain reference is foreign")
                expanded_owners.extend(domain["owners"])
            else:
                expanded_owners.append(item)
        declared = expanded_owners
    if (
        type(declared) is not list
        or any(type(name) is not str for name in declared)
        or set(declared) != set(owner_map)
        or len(declared) != len(owner_map)
    ):
        raise C0LawError("Source owner declarations do not match Lib")
    source_templates = {}
    for domain in domains:
        if type(domain) is not dict or "owner_template" not in domain:
            continue
        template = domain["owner_template"]
        members = domain.get("owners")
        if (
            type(template) is not str
            or template in source_templates
            or type(members) is not list
            or any(type(member) is not str for member in members)
        ):
            raise C0LawError("Source owner template binding is malformed")
        source_templates[template] = tuple(members)
    if source_templates != dict(library.owner_templates):
        raise C0LawError("Source owner template bindings do not match Lib")
    template_of = {
        member: template for template, members in library.owner_templates for member in members
    }
    row = expand_actor_bindings(
        row,
        {item.symbol: (item.owner.state_type, item.identity_field) for item in library.owners},
        {item.symbol: item.actor for item in library.actions},
        frozenset(item.symbol for item in library.events if type(item.ports) is C0DirectScenePorts),
        frozenset(item.symbol for item in library.actions if item.ports.schedule is not None),
        frozenset(item.symbol for item in library.events if type(item.ports) is C0DirectActorPorts),
        source_context=source_context,
        origins=binding_contexts,
    )
    action_rows = row["actions"]
    if type(action_rows) is not list or not action_rows:
        raise C0LawError("Source needs finite Action instances")
    COMPILE_BUDGET.check("actions", len(action_rows), stage="Program checking")
    compiled = []
    action_instances: dict[str, C0GraphAction] = {}
    action_template_of: dict[str, str] = {}
    for raw in action_rows:
        required = {"name", "template", "actor", "source_key", "event_type"}
        if (
            type(raw) is not dict
            or not required <= set(raw)
            or set(raw)
            - required
            - {
                "schedule",
                "form",
                "target",
                "participants",
                "law",
                "operation",
                "actor_product",
                "actor_domain_effects",
            }
            or ("law" in raw) == ("operation" in raw)
        ):
            raise C0LawError("Source Action has missing or unknown fields")
        action_row = raw
        name = action_row["name"]
        template_name = action_row["template"]
        template = action_map.get(template_name) if type(template_name) is str else None
        actor_symbol = action_row["actor"]
        if type(name) is not str or not name or name in action_instances or template is None:
            raise C0LawError("Source Action template or instance is foreign or repeated")
        if (
            type(template.ports) is not C0ValueActionPorts
            or type(template.ports.source_key) is not K0SourceSpecKey
            or type(template.ports.event_type) is not K0EventTypeKey
            or template.ports.form is not None
        ):
            raise C0LawError("Lib Action template identity or ports are malformed")
        self_actor = type(template.ports.actor_owner) is C0SelfActorPorts
        if self_actor:
            if actor_symbol != {
                "self": template.ports.actor_owner.family
            } or template.ports.actor_owner.family not in _selected_actor_kinds(library, row):
                raise C0LawError("Source self Action must bind its selected Actor kind")
            exemplar = target = None
        elif type(actor_symbol) is not str or actor_symbol not in owner_map:
            raise C0LawError("Source Action Actor binding is foreign")
        else:
            exemplar = owner_map.get(template.actor)
            target = owner_map[actor_symbol]
        if not self_actor and (
            exemplar is None
            or template_of.get(template.actor) != template_of.get(actor_symbol)
            or exemplar.identity_field is None
            or target.identity_field != exemplar.identity_field
            or type(target.owner) is not type(exemplar.owner)
            or target.owner.contribution_type is not exemplar.owner.contribution_type
            or target.owner.state_type is not exemplar.owner.state_type
            or target.owner.view_type is not exemplar.owner.view_type
        ):
            raise C0LawError("Source Action Actor does not match its nominal template")
        try:
            source_key = K0SourceSpecKey(action_row["source_key"])
            event_type = K0EventTypeKey(action_row["event_type"])
        except (TypeError, K0ProfileError) as error:
            raise C0LawError("Source Action instance identity is malformed") from error
        ports = replace(
            template.ports,
            source_key=source_key,
            event_type=event_type,
            actor_owner=template.ports.actor_owner if self_actor else target.owner,
        )
        if ("target" in action_row) != (ports.target is not None):
            raise C0LawError("Source Action target binding differs from Lib")
        if ports.target is not None:
            target_row = action_row["target"]
            if type(target_row) is not dict or set(target_row) != {"kind"}:
                raise C0LawError("Source Action target binding is malformed")
            kind = selected.get(target_row["kind"]) if type(target_row["kind"]) is str else None
            if kind is None or kind.k0_kind.state_type is not ports.target.state_type:
                raise C0LawError("Source Action target kind does not match Lib")
            compatible = tuple(
                sorted(
                    (
                        item.k0_kind
                        for item in selected_kinds
                        if object_hierarchy is not None
                        and object_hierarchy.accepts(kind.sort, item.sort)
                    ),
                    key=lambda item: item.family,
                )
            )
            if any(item.state_type is not ports.target.state_type for item in compatible):
                raise C0LawError("generic Action target needs one shared nominal state record")
            ports = replace(
                ports, target=replace(ports.target, kind=kind.k0_kind, kinds=compatible)
            )
        if ("participants" in action_row) != bool(ports.participants):
            raise C0LawError("Source Action participant binding differs from Lib")
        if ports.participants:
            bindings = action_row["participants"]
            if type(bindings) is not dict or set(bindings) != {
                port.name for port in ports.participants
            }:
                raise C0LawError("Source Action participants do not cover Lib ports")
            bound = []
            for port in ports.participants:
                binding = bindings[port.name]
                if port.selector == "individual":
                    if type(binding) is not dict or set(binding) != {"kind"}:
                        raise C0LawError("Source individual participant binding is malformed")
                    kind = selected.get(binding["kind"]) if type(binding["kind"]) is str else None
                    if kind is None or kind.k0_kind.state_type is not port.state_type:
                        raise C0LawError("Source individual participant kind is foreign")
                    compatible = tuple(
                        sorted(
                            (
                                item.k0_kind
                                for item in selected_kinds
                                if object_hierarchy is not None
                                and object_hierarchy.accepts(kind.sort, item.sort)
                            ),
                            key=lambda item: item.family,
                        )
                    )
                    if any(item.state_type is not port.state_type for item in compatible):
                        raise C0LawError("participant kind has incompatible nominal state")
                    bound.append(replace(port, kind=kind.k0_kind, kinds=compatible))
                elif port.selector == "actor":
                    if type(binding) is not dict or set(binding) != {"kind"}:
                        raise C0LawError("Source Actor participant binding is malformed")
                    kinds = _selected_actor_kinds(library, row)
                    kind = kinds.get(binding["kind"]) if type(binding["kind"]) is str else None
                    if kind is None or kind.factory.state_type is not port.state_type:
                        raise C0LawError("Source Actor participant kind is foreign")
                    bound.append(
                        replace(
                            port,
                            actor_kind=C0SelfActorPorts(
                                kind.symbol, kind.factory.state_type, kind.factory
                            ),
                        )
                    )
                else:
                    if (
                        type(binding) is not dict
                        or set(binding) != {"actors"}
                        or type(binding["actors"]) is not list
                        or not binding["actors"]
                        or len(binding["actors"]) > 64
                        or any(type(name) is not str for name in binding["actors"])
                    ):
                        raise C0LawError("Source closed participant domain is malformed")
                    members = tuple(sorted(binding["actors"]))
                    if len(set(members)) != len(members):
                        raise C0LawError("Source closed participant domain repeats an Actor")
                    if any(
                        name not in owner_map
                        or owner_map[name].identity_field is None
                        or owner_map[name].identity_field != owner_map[members[0]].identity_field
                        or owner_map[name].owner.state_type is not port.state_type
                        or owner_map[name].owner.view_type is not port.state_type
                        for name in members
                    ):
                        raise C0LawError("Source closed participant domain has a foreign Actor")
                    bound.append(
                        replace(
                            port,
                            members=tuple((name, owner_map[name].owner) for name in members),
                            identity_field=owner_map[members[0]].identity_field,
                        )
                    )
            ports = replace(ports, participants=tuple(bound))
        if "form" in action_row:
            form_row = action_row["form"]
            if type(form_row) is not dict or set(form_row) != {"kind", "initial_output"}:
                raise C0LawError("Source Action formation binding is malformed")
            kind = selected.get(form_row["kind"]) if type(form_row["kind"]) is str else None
            if kind is None or type(form_row["initial_output"]) is not str:
                raise C0LawError("Source Action forms an unselected Object kind")
            ports = replace(
                ports,
                form=C0ActionFormPorts(
                    kind.symbol, kind.k0_kind.state_type, form_row["initial_output"]
                ),
            )
        if "actor_product" in action_row:
            ports = replace(
                ports,
                actor_product=bind_actor_product(
                    action_row["actor_product"], _selected_actor_kinds(library, row)
                ),
            )
        if ports.schedule is not None and "schedule" in action_row:
            schedule_row = action_row["schedule"]
            if (
                type(schedule_row) is not dict
                or set(schedule_row) != {"source"}
                or type(schedule_row.get("source")) is not str
            ):
                raise C0LawError("Source Action schedule identity is malformed")
            try:
                due_source = K0SourceSpecKey(schedule_row["source"])
            except K0ProfileError as error:
                raise C0LawError("Source Action schedule identity is malformed") from error
            ports = replace(ports, schedule=replace(ports.schedule, due_source=due_source))
        if (
            not self_actor
            and (
                template.ports.actor_owner is not exemplar.owner
                or ports.actor_identity_field != target.identity_field
            )
        ) or not any(
            ports.scene_owner is item.owner and item.identity_field is None
            for item in library.owners
        ):
            raise C0LawError("Lib Action ports are not in this owner graph")
        if ports.actor_identity_field in ports.state_effects.get("actor", {}):
            raise C0LawError("Action cannot write its Actor identity field")
        operation_name = action_row.get("operation")
        if "operation" in action_row:
            operation = operations.get(operation_name) if type(operation_name) is str else None
            if (
                operation is None
                or operation.template != template_name
                or ports.target is None
                or "target" not in action_row
                or selected[action_row["target"]["kind"]].sort != operation.receiver
                or operation_name not in operation_bindings
            ):
                raise C0LawError("Source Action operation does not match its Lib binding")
            law_use = {"ref": operation_bindings[operation_name], "args": {}}
        else:
            if any(item.template == template_name for item in library.operations):
                raise C0LawError("operation-owned Action template needs a selected binding")
            law_use = action_row["law"]
        bound = bind_law(
            "action",
            law_use,
            action_row,
            "actions",
            template_name,
            suffix=("operation",) if "operation" in action_row else ("law",),
            origins=operation_origins.get(operation_name, ()),
        )
        body = bound.body
        ports = replace(ports, value_ports=replace(ports.value_ports, source_context=bound.context))
        from .actor_domain_v1 import C0ActorDomainEffect

        raw_domains = action_row.get("actor_domain_effects", [])
        if type(raw_domains) is not list or len(raw_domains) != len(ports.actor_domains):
            raise C0LawError("Source Action does not fill its exact Actor domain effects")
        domain_ports = {port.name: port for port in ports.actor_domains}
        domains = []
        for index, raw_domain in enumerate(raw_domains):
            requested = _row(raw_domain, {"name", "law"}, "Source Action Actor effect")
            port = domain_ports.get(requested["name"]) if type(requested["name"]) is str else None
            if (
                port is None
                or port.kind.symbol not in _selected_actor_kinds(library, row)
                or any(domain.ports.name == port.name for domain in domains)
            ):
                raise C0LawError("Source Action Actor effect has an unselected/duplicate domain")
            domain_body = bind_law(
                "action",
                requested["law"],
                action_row,
                "actions",
                template_name,
                suffix=("actor_domain_effects", index, "law"),
            )
            domain_value = compile_value_program(
                json.dumps(domain_body.body["value"]),
                replace(port.value_ports, source_context=domain_body.context),
                state_outputs={f"actor.{field}": output for field, output in port.effects},
            )
            domains.append(
                C0ActorDomainEffect(
                    replace(port, value_ports=domain_value._ports),
                    domain_value,
                    port.effects,
                )
            )
        ports = replace(ports, actor_domains=tuple(domain.ports for domain in domains))
        expanded = {
            "schema": "c0.action.value.v1",
            "source_key": action_row["source_key"],
            "event_type": action_row["event_type"],
            **body,
        }
        if "schedule" in action_row:
            if ports.schedule is None:
                raise C0LawError("Source Action cannot schedule an unscheduled template")
            expanded["schedule"] = {
                "source": ports.schedule.due_source.value,
                "subject_output": ports.schedule.subject_output,
                "delay_output": ports.schedule.delay_output,
            }
        try:
            law_source = json.dumps(expanded)
        except (TypeError, ValueError, RecursionError) as error:
            raise C0LawError("Source Action law is not JSON data") from error
        action = compile_composable_action(law_source, ports, actor_domains=tuple(domains))
        if "operation" in action_row:
            for _, candidate_law in operation.implementations:
                if candidate_law == operation_bindings[operation_name]:
                    continue
                candidate_body = library_definitions.instantiate(
                    "action", {"ref": candidate_law, "args": {}}
                )
                compile_composable_action(
                    json.dumps({**expanded, "value": candidate_body["value"]}),
                    ports,
                    actor_domains=tuple(domains),
                )
        contribution_states = set(get_args(get_type_hints(action.contribution_type)["state"]))
        if not contribution_states <= graph_state_types:
            raise C0LawError("Action contribution carries a state outside this owner graph")
        action = value_builder.transition(name, action)
        compiled.append((name, action))
        action_instances[name] = C0GraphAction(name, actor_symbol, ports)
        action_template_of[name] = template_name
    dues, temporal_ir = _compile_due_programs(
        row, library, due_map, bind_law, compiled, selected_kinds, owner_map, value_builder
    )
    advance_seats = frozenset(temporal_ir.advance_seats) if temporal_ir is not None else frozenset()
    event_rows = row["events"]
    if type(event_rows) is not list:
        raise C0LawError("Source Event instances are not finite")
    COMPILE_BUDGET.check("causal_edges", len(event_rows), stage="Program checking")
    event_declarations = {}
    for raw in event_rows:
        if type(raw) is not dict:
            raise C0LawError("Source Event has missing or unknown fields")
        keys = set(raw) - {"shared_result", "actor_product", "object_product"}
        if keys not in (
            {
                "name",
                "template",
                "trigger_action",
                "source_key",
                "event_type",
                "causal_key",
                "law",
            },
            {
                "name",
                "template",
                "trigger_event",
                "source_key",
                "event_type",
                "causal_key",
                "law",
            },
            {
                "name",
                "template",
                "actor",
                "trigger_action",
                "source_key",
                "event_type",
                "causal_key",
                "law",
            },
            {
                "name",
                "template",
                "actor",
                "trigger_event",
                "source_key",
                "event_type",
                "causal_key",
                "law",
            },
        ):
            raise C0LawError("Source Event has missing or unknown fields")
        if "shared_result" in raw and (
            type(raw["shared_result"]) is not str or not raw["shared_result"]
        ):
            raise C0LawError("shared Event result needs a closed family identity")
        name = raw["name"]
        trigger_kind = "trigger_action" if "trigger_action" in raw else "trigger_event"
        trigger_name = raw[trigger_kind]
        if (
            type(name) is not str
            or not name
            or name in event_declarations
            or name in dict(dues)
            or type(raw["template"]) is not str
            or raw["template"] not in event_map
        ):
            raise C0LawError("Source Event template or instance is foreign or repeated")
        if type(trigger_name) is not str or not trigger_name:
            raise C0LawError("direct Event trigger is malformed")
        event_declarations[name] = raw
    events = []
    pending = dict(event_declarations)
    while pending:
        progress = False
        for name, event_row in tuple(pending.items()):
            trigger = (
                dict(compiled).get(event_row["trigger_action"])
                if "trigger_action" in event_row
                else dict(events).get(event_row["trigger_event"])
                or dict(dues).get(event_row["trigger_event"])
            )
            if trigger is None:
                continue
            template_ports = event_map[event_row["template"]].ports
            if (
                type(template_ports) not in (C0DirectScenePorts, C0DirectActorPorts)
                or type(template_ports.source_key) is not K0SourceSpecKey
                or type(template_ports.event_type) is not K0EventTypeKey
                or type(template_ports.causal_key) is not K0CausalLawKey
            ):
                raise C0LawError("Lib Event template identity or ports are malformed")
            try:
                event_ports = replace(
                    template_ports,
                    source_key=K0SourceSpecKey(event_row["source_key"]),
                    event_type=K0EventTypeKey(event_row["event_type"]),
                    causal_key=K0CausalLawKey(event_row["causal_key"]),
                )
            except (TypeError, K0ProfileError) as error:
                raise C0LawError("Source Event instance identity is malformed") from error
            if type(event_ports) is C0DirectActorPorts:
                actor_symbol = event_row.get("actor")
                target = owner_map.get(actor_symbol) if type(actor_symbol) is str else None
                exemplar = next(
                    (item for item in library.owners if item.owner is template_ports.actor_owner),
                    None,
                )
                if (
                    target is None
                    or exemplar is None
                    or template_of.get(exemplar.symbol) != template_of.get(actor_symbol)
                    or target.identity_field != exemplar.identity_field
                    or type(target.owner) is not type(exemplar.owner)
                    or target.owner.contribution_type is not exemplar.owner.contribution_type
                    or target.owner.state_type is not exemplar.owner.state_type
                    or target.owner.view_type is not exemplar.owner.view_type
                ):
                    raise C0LawError("Source Actor Event recipient is not a nominal template match")
                event_ports = replace(event_ports, actor_owner=target.owner)
            if not any(
                event_ports.scene_owner is item.owner and item.identity_field is None
                for item in library.owners
            ):
                raise C0LawError("direct Event Scene owner is outside this graph")
            if "actor_product" in event_row:
                event_ports = replace(
                    event_ports,
                    actor_product=bind_actor_product(
                        event_row["actor_product"], _selected_actor_kinds(library, row)
                    ),
                )
            if "object_product" in event_row:
                event_ports = replace(
                    event_ports,
                    object_product=bind_object_product(event_row["object_product"], selected),
                )
            if type(event_ports) is C0DirectScenePorts:
                if "actor" in event_row:
                    raise C0LawError("Scene Event cannot bind an Actor recipient")
                bound = bind_law(
                    "direct_event", event_row["law"], event_row, "events", event_row["template"]
                )
                body = bound.body
                event_ports = replace(
                    event_ports,
                    value_ports=replace(event_ports.value_ports, source_context=bound.context),
                )
                expanded = {
                    key: value
                    for key, value in event_row.items()
                    if key not in ("template", "shared_result", "actor_product", "object_product")
                }
                expanded["law"] = body["law"]
                expanded["form"] = "direct"
                expanded["when_false"] = "no_event"
                expanded["effect"] = {"scene": dict(event_map[event_row["template"]].effects)}
                event = compile_direct_scene_event(expanded, event_ports, trigger)
            elif type(event_ports) is C0DirectActorPorts:
                if not any(
                    event_ports.actor_owner is item.owner
                    and item.identity_field == event_ports.actor_identity_field
                    for item in library.owners
                ):
                    raise C0LawError("Actor Event owner is outside this graph")
                bound = bind_law(
                    "direct_actor_event",
                    event_row["law"],
                    event_row,
                    "events",
                    event_row["template"],
                )
                body = bound.body
                event_ports = replace(
                    event_ports,
                    value_ports=replace(event_ports.value_ports, source_context=bound.context),
                )
                expanded = {
                    key: value
                    for key, value in event_row.items()
                    if key
                    not in ("template", "actor", "shared_result", "actor_product", "object_product")
                }
                expanded["law"] = body["law"]
                expanded["form"] = "direct_actor"
                expanded["when_false"] = "no_event"
                expanded["effect"] = {"actor": dict(event_map[event_row["template"]].effects)}
                event = compile_direct_actor_event(expanded, event_ports, trigger)
            else:
                raise C0LawError("direct Event has foreign Lib ports")
            events.append((name, value_builder.transition(name, event)))
            del pending[name]
            progress = True
        if not progress:
            raise C0LawError("direct Event trigger is foreign or forms a cycle")
    writes_by_trigger: dict[tuple[str, K0SourceSpecKey], set[K0OwnerKey]] = {}
    graph_owners = {item.owner.key: item.owner for item in library.owners}
    action_programs = dict(compiled)
    event_programs = dict(events)
    causal_edges: dict[K0SourceSpecKey, set[K0SourceSpecKey]] = {}
    for name, event in events:
        declaration = event_declarations[name]
        trigger = (
            ("trigger_action", action_programs[declaration["trigger_action"]].source_key)
            if "trigger_action" in declaration
            else (
                "trigger_event",
                (
                    event_programs[declaration["trigger_event"]].ports.source_key
                    if declaration["trigger_event"] in event_programs
                    else dict(dues)[declaration["trigger_event"]].ports.source_key
                ),
            )
        )
        if trigger[0] == "trigger_event":
            causal_edges.setdefault(trigger[1], set()).add(event.ports.source_key)
        previous = writes_by_trigger.setdefault(trigger, set())
        write_owners = {
            owner.key
            for root, owner in (
                (("scene", event.ports.scene_owner),)
                if isinstance(event, C0DirectSceneProgram)
                else (("actor", event.ports.actor_owner),)
            )
            if any(effect_root == root for effect_root, _, _ in event.ir.effects)
        }
        if any(
            not isinstance(graph_owners[owner], _K0SameWaveEffectProofOwner)
            for owner in previous & write_owners
        ):
            raise C0LawError("same-trigger owner fanout needs an effect-preservation proof")
        previous.update(write_owners)
    visiting: set[K0SourceSpecKey] = set()
    visited: set[K0SourceSpecKey] = set()

    def check_causal_source(node: K0SourceSpecKey) -> None:
        if node in visiting:
            raise C0LawError("shared Event result forms a causal source cycle")
        if node in visited:
            return
        visiting.add(node)
        for successor in causal_edges.get(node, ()):
            check_causal_source(successor)
        visiting.remove(node)
        visited.add(node)

    for source in causal_edges:
        check_causal_source(source)
    shared_results: dict[str, dict[str, object]] = {}
    for raw in event_rows:
        key = raw["source_key"]
        prior = shared_results.get(key)
        if prior is not None:
            comparable = set(raw) - {"name", "trigger_action", "trigger_event", "causal_key"}
            if (
                type(raw.get("shared_result")) is not str
                or raw.get("shared_result") != prior.get("shared_result")
                or comparable
                != set(prior) - {"name", "trigger_action", "trigger_event", "causal_key"}
                or any(raw[field] != prior[field] for field in comparable)
            ):
                raise C0LawError("shared Event result has incompatible source or Law")
        else:
            shared_results[key] = raw
    COMPILE_BUDGET.check("event_results", len(shared_results), stage="Program checking")
    all_programs = [
        *dict(compiled).values(),
        *(event for _, event in events),
        *(due for _, due in dues),
    ]
    source_keys = [
        item.source_key if isinstance(item, C0ValueActionProgram) else item.ports.source_key
        for item in all_programs
    ]
    event_types = [
        item.event_type if isinstance(item, C0ValueActionProgram) else item.ports.event_type
        for item in all_programs
    ]
    if len(set(source_keys)) != len(compiled) + len(shared_results) + len(dues):
        raise C0LawError("compiled owner graph does not form a K0 profile: source keys alias")
    due_types = {due.ports.event_type for _, due in dues}
    if len(due_types) != len(dues) or any(
        event_type in due_types for event_type in event_types[: -len(dues)] if dues
    ):
        raise C0LawError("temporal Event classification aliases another source")
    world_ir, world_layout = capture_world(
        library.value_backend,
        tuple(compiled),
        tuple(events),
        tuple(dues),
        tuple(item.symbol for item in selected_kinds),
        temporal_ir,
        value_builder.entries,
        tuple(_selected_actor_kinds(library, row)),
    )
    temporal_binding = (
        lower_temporal_program(temporal_ir, tuple(dues)) if temporal_ir is not None else None
    )
    policy = temporal_binding.policy if temporal_binding is not None else None
    seats_raw = row["seats"]
    if type(seats_raw) is not list or not seats_raw:
        raise C0LawError("Source needs finite seats")
    seats = []
    for raw in seats_raw:
        seat_keys = {"name", "actor", "entries", "read", "offers"}
        if type(raw) is dict and "presentation" in raw:
            seat_keys.add("presentation")
        if type(raw) is dict and "read_projection" in raw:
            seat_keys.add("read_projection")
        if type(raw) is dict and "offer_previews" in raw:
            seat_keys.add("offer_previews")
        seat = _row(raw, seat_keys, "Source seat")
        name, actor, entries = seat["name"], seat["actor"], seat["entries"]
        reads = seat["read"]
        if (
            type(name) is not str
            or not name
            or any(name == prior.symbol for prior in seats)
            or type(actor) is not str
            or actor not in owner_map
            or owner_map[actor].identity_field is None
            or any(actor == prior.actor for prior in seats)
            or type(entries) is not list
            or not entries
            or any(type(entry) is not str or entry not in action_instances for entry in entries)
            or len(entries) != len(set(entries))
            or any(action_instances[entry].actor != actor for entry in entries)
            or type(reads) is not list
            or any(type(path) is not str for path in reads)
            or len(reads) != len(set(reads))
            or f"{actor}.{owner_map[actor].identity_field}" not in reads
            or any(
                "." not in path
                or path.split(".", 1)[0] not in owner_map
                or (
                    path.split(".", 1)[0] != actor
                    and owner_map[path.split(".", 1)[0]].identity_field is not None
                )
                or path.split(".", 1)[1] not in owner_map[path.split(".", 1)[0]].seat_readable_paths
                for path in reads
            )
        ):
            raise C0LawError("Source seat aliases or exceeds its Actor/read authority")
        raw_offers = seat["offers"]
        if type(raw_offers) is not list:
            raise C0LawError("Source seat offers are malformed")
        derived_read = None
        if "read_projection" in seat:
            requested = _row(
                seat["read_projection"], {"template", "law"}, "Source seat read projection"
            )
            port = next(
                (item for item in library.seat_read_ports if item.symbol == requested["template"]),
                None,
            )
            if port is None or port.actor != actor or port.object_kind not in selected:
                raise C0LawError("Source seat read projection is not bound to this Actor/Object")
            bound = bind_law(
                "seat_view",
                requested["law"],
                seat,
                "seat_read_projections",
                requested["template"],
                suffix=("read_projection", "law"),
            )
            body = bound.body
            program = compile_value_program(
                json.dumps(body["value"]),
                replace(port.value_ports, source_context=bound.context),
                admission_outputs=frozenset(port.value_ports.outputs),
            )
            derived_read = C0SeatReadProjection(port, program)
        raw_previews = seat.get("offer_previews", [])
        if type(raw_previews) is not list or len(raw_previews) > len(entries):
            raise C0LawError("Source seat offer previews are not finite")
        offer_previews = []
        for preview_index, raw_preview in enumerate(raw_previews):
            requested = _row(
                raw_preview,
                {"template", "entry", "law"},
                "Source seat offer preview",
            )
            port = next(
                (
                    item
                    for item in library.seat_offer_preview_ports
                    if item.symbol == requested["template"]
                ),
                None,
            )
            entry = requested["entry"]
            if (
                port is None
                or port.actor != actor
                or type(entry) is not str
                or entry not in entries
                or action_template_of[entry] != port.action_template
                or port.object_kind not in selected
                or any(item.entry == entry for item in offer_previews)
            ):
                raise C0LawError("Source offer preview is not bound to this Actor/Action/Object")
            bound = bind_law(
                "seat_view",
                requested["law"],
                seat,
                "seat_offer_previews",
                requested["template"],
                suffix=("offer_previews", preview_index, "law"),
            )
            body = bound.body
            program = compile_value_program(
                json.dumps(body["value"]),
                replace(port.value_ports, source_context=bound.context),
                admission_outputs=frozenset(port.value_ports.outputs),
            )
            offer_previews.append(C0SeatOfferPreview(entry, port, program))
        presentation = None
        if "presentation" in seat:
            display = _row(
                seat["presentation"],
                {"title", "fields", "published", "rejected", "no_offers"},
                "Source seat presentation",
                optional={
                    "opening",
                    "terms",
                    "projection_columns",
                    "finish_on_action",
                    "published_actions",
                    "rejected_actions",
                    "preview_fields",
                    "projection_focus",
                    "finish_fields",
                    "published_fields",
                },
            )
            labels = display["fields"]
            terms = display.get("terms", {})
            projection_columns = display.get("projection_columns", {})
            finish_on_action = display.get("finish_on_action", {})
            published_actions = display.get("published_actions", {})
            rejected_actions = display.get("rejected_actions", {})
            preview_fields = display.get("preview_fields", {})
            projection_focus = display.get("projection_focus", {})
            finish_fields = display.get("finish_fields", {})
            published_fields = display.get("published_fields", {})
            preview_outputs = {
                item.entry: item.ports.value_ports.outputs for item in offer_previews
            }
            if (
                type(labels) is not dict
                or set(labels)
                != set(reads) | ({derived_read.ports.symbol} if derived_read is not None else set())
                or any(
                    type(label) is not str or not 1 <= len(label) <= 80
                    for key, label in display.items()
                    if key
                    not in (
                        "fields",
                        "opening",
                        "terms",
                        "projection_columns",
                        "finish_on_action",
                        "published_actions",
                        "rejected_actions",
                        "preview_fields",
                        "projection_focus",
                        "finish_fields",
                        "published_fields",
                    )
                )
                or any(
                    label is not None and (type(label) is not str or not 1 <= len(label) <= 80)
                    for label in labels.values()
                )
                or (
                    "opening" in display
                    and (
                        type(display["opening"]) is not str
                        or not 1 <= len(display["opening"]) <= 400
                    )
                )
                or type(terms) is not dict
                or len(terms) > 256
                or any(
                    type(key) is not str
                    or not 1 <= len(key) <= 80
                    or type(value) is not str
                    or not 1 <= len(value) <= 80
                    for key, value in terms.items()
                )
                or type(projection_columns) is not dict
                or (
                    bool(projection_columns)
                    and (
                        derived_read is None
                        or set(projection_columns) != {derived_read.ports.symbol}
                    )
                )
                or any(
                    type(columns) is not dict
                    or set(columns) != set(derived_read.ports.value_ports.outputs)
                    or any(
                        type(column) is not str
                        or type(label) is not str
                        or not 1 <= len(label) <= 80
                        for column, label in columns.items()
                    )
                    for columns in projection_columns.values()
                )
                or type(finish_on_action) is not dict
                or any(
                    type(messages) is not dict
                    or len(messages) > len(entries)
                    or any(
                        entry not in entries
                        or type(message) is not str
                        or not 1 <= len(message) <= 400
                        for entry, message in messages.items()
                    )
                    for messages in (published_actions, rejected_actions)
                )
                or type(preview_fields) is not dict
                or any(
                    entry not in preview_outputs
                    or type(columns) is not dict
                    or not columns
                    or any(
                        name not in preview_outputs[entry]
                        or preview_outputs[entry][name] not in (str, int, bool)
                        or type(label) is not str
                        or not 1 <= len(label) <= 80
                        for name, label in columns.items()
                    )
                    for entry, columns in preview_fields.items()
                )
                or len(finish_on_action) > len(entries)
                or any(
                    entry not in entries
                    or type(closing) is not dict
                    or set(closing) != {"outcome", "text"}
                    or type(closing["outcome"]) is not str
                    or not closing["outcome"].isidentifier()
                    or type(closing["text"]) is not str
                    or not 1 <= len(closing["text"]) <= 400
                    for entry, closing in finish_on_action.items()
                )
                or type(projection_focus) is not dict
                or any(
                    derived_read is None
                    or symbol != derived_read.ports.symbol
                    or type(path) is not str
                    or path != f"{actor}.{derived_read.ports.current_field}"
                    or path not in reads
                    or labels.get(symbol) is None
                    or labels.get(path) is None
                    or presentation_scalar_kind(world_ir.signatures, path, allow_optional=False)
                    != "str"
                    for symbol, path in projection_focus.items()
                )
                or type(finish_fields) is not dict
                or any(
                    entry not in finish_on_action
                    or type(paths) is not list
                    or not 1 <= len(paths) <= len(reads)
                    or any(
                        type(path) is not str
                        or path not in reads
                        or labels.get(path) is None
                        or presentation_scalar_kind(world_ir.signatures, path) is None
                        for path in paths
                    )
                    or len(set(paths)) != len(paths)
                    for entry, paths in finish_fields.items()
                )
                or type(published_fields) is not dict
                or any(
                    entry not in entries
                    or type(paths) is not list
                    or not 1 <= len(paths) <= len(reads)
                    or any(
                        type(path) is not str
                        or path not in reads
                        or labels.get(path) is None
                        or presentation_scalar_kind(world_ir.signatures, path) is None
                        for path in paths
                    )
                    or len(set(paths)) != len(paths)
                    for entry, paths in published_fields.items()
                )
            ):
                raise C0LawError("Source seat presentation must label its exact read paths")
            presentation = C0SeatPresentation(
                display["title"],
                tuple(
                    (path, labels[path])
                    for path in (
                        *reads,
                        *((derived_read.ports.symbol,) if derived_read is not None else ()),
                    )
                ),
                display["published"],
                display["rejected"],
                display["no_offers"],
                display.get("opening"),
                tuple(terms.items()),
                tuple(
                    (name, tuple(columns.items())) for name, columns in projection_columns.items()
                ),
                tuple(
                    (entry, closing["outcome"], closing["text"])
                    for entry, closing in finish_on_action.items()
                ),
                tuple(published_actions.items()),
                tuple(rejected_actions.items()),
                tuple((entry, tuple(columns.items())) for entry, columns in preview_fields.items()),
                tuple(projection_focus.items()),
                tuple((entry, tuple(paths)) for entry, paths in finish_fields.items()),
                tuple((entry, tuple(paths)) for entry, paths in published_fields.items()),
            )
        checked_offers = []
        candidate_checks = []
        for offer in raw_offers:
            if type(offer) is not dict or type(offer.get("entry")) is not str:
                raise C0LawError("Source seat offer is malformed")
            entry = offer["entry"]
            if entry not in entries or entry not in action_instances:
                raise C0LawError("Source seat offer has an unknown or unselected Action")
            declared_operation = next(
                (item.get("operation") for item in action_rows if item["name"] == entry), None
            )
            if ("operation" in offer) != (declared_operation is not None) or (
                declared_operation is not None and offer["operation"] != declared_operation
            ):
                raise C0LawError("Source offer operation differs from its Action")
            checked_offers.append(
                {
                    key: value
                    for key, value in offer.items()
                    if key not in ("operation", "availability")
                }
            )
            if "availability" in offer:
                template = next(item["template"] for item in action_rows if item["name"] == entry)
                candidate_checks.append(
                    (
                        len(checked_offers) - 1,
                        compile_candidate_check(
                            offer["availability"],
                            library.candidate_inputs,
                            template,
                            action_instances[entry].ports,
                            entry,
                        ),
                    )
                )
        offers = compile_seat_offers(
            checked_offers,
            tuple(entries),
            tuple(
                dict.fromkeys(
                    (
                        *reads,
                        *(
                            f"{actor}.{path}"
                            for path in sorted(owner_map[actor].seat_readable_paths)
                        ),
                    )
                )
            ),
            {entry: action_instances[entry].ports for entry in entries},
            {
                entry: next(
                    symbol
                    for symbol, owner in owner_map.items()
                    if owner.owner is action_instances[entry].ports.scene_owner
                )
                for entry in entries
            },
            actor,
            provider,
            source_context=program_context(
                "seat", name, context=binding_contexts.get(("seats", name))
            ),
            pure_definitions=library.pure_definitions,
        )
        for preview in offer_previews:
            declarations = tuple(item for item in offers if item.entry == preview.entry)
            if not declarations or any(
                not isinstance(getattr(item, "payload", None), Mapping)
                or preview.ports.offer_payload_key not in item.payload
                for item in declarations
            ):
                raise C0LawError("Source offer preview key is absent from the current offer")
        seats.append(
            _Seat(
                name,
                actor,
                tuple(entries),
                tuple(reads),
                offers,
                provider.max_candidates,
                presentation,
                derived_read,
                tuple(offer_previews),
                tuple(candidate_checks),
            )
        )
    if not advance_seats <= {seat.symbol for seat in seats}:
        raise C0LawError("temporal advance seat is not declared")
    from .action_cost_group_v1 import expand_action_cost_groups

    form_row, cost_origins = expand_action_cost_groups(row["game_form"])
    game_form = None
    action_value_policy = None
    action_costs: dict[str, _C0ActionCostProjector] = {}
    if type(form_row) is not dict:
        raise C0LawError("GameForm declaration is malformed")
    if form_row == {"mode": "manual"}:
        pass
    elif form_row.get("mode") == "event_jump_stop":
        _row(form_row, {"mode", "seats", "end_at", "wake_at"}, "GameForm")
        wake_at = form_row["wake_at"]
        controlled = form_row["seats"]
        if (
            form_row["mode"] != "event_jump_stop"
            or not temporal
            or type(controlled) is not list
            or not controlled
            or len(controlled) > 64
            or any(type(name) is not str or name not in advance_seats for name in controlled)
            or len(controlled) != len(set(controlled))
            or type(form_row["end_at"]) is not int
            or not 0 <= form_row["end_at"] <= _MAX_INT
            or type(wake_at) is not list
            or len(wake_at) > 128
            or any(type(tick) is not int or not 0 <= tick <= form_row["end_at"] for tick in wake_at)
            or wake_at != sorted(set(wake_at))
        ):
            raise C0LawError("GameForm is not a closed event-jump stop policy")
        game_form = _EventJumpForm(tuple(controlled), form_row["end_at"], tuple(wake_at))
    elif form_row.get("mode") == "action_value_event_jump":
        form_keys = {"mode", "seats", "end_at", "max_same_time_actions"}
        if "world_stops" in form_row:
            form_keys.add("world_stops")
        _row(
            form_row,
            form_keys,
            "GameForm",
        )
        controlled = form_row["seats"]
        if (
            policy is None
            or policy.capability_ref.value != "c0.owner_graph.action_value_event_jump.v1"
            or type(controlled) is not list
            or not controlled
            or len(controlled) > 64
            or (
                form_row["end_at"] is not None
                and (type(form_row["end_at"]) is not int or not 1 <= form_row["end_at"] <= _MAX_INT)
            )
            or type(form_row["max_same_time_actions"]) is not int
            or not 1 <= form_row["max_same_time_actions"] <= 1024
        ):
            raise C0LawError("GameForm is not a closed action-value policy")
        seats_by_name = {seat.symbol: seat for seat in seats}
        action_by_name = dict(compiled)
        selected_names = []
        selected_sources = []
        action_value_seats = []
        for control_index, raw_control in enumerate(controlled):
            control = _row(
                raw_control,
                {"seat", "tempo", "eligible", "costs"},
                "action-value seat",
            )
            name = control["seat"]
            selected = seats_by_name.get(name) if type(name) is str else None
            if selected is None or name in selected_names or type(control["costs"]) is not dict:
                raise C0LawError("action-value seat is foreign, repeated or malformed")
            if set(control["costs"]) != set(selected.entries):
                raise C0LawError("action-value costs do not cover the seat's exact Actions")
            selected_names.append(name)
            actor = owner_map[selected.actor]
            actor_paths = frozenset(f"actor.{path}" for path in actor.seat_readable_paths)
            actor_fields = _complete_value_fields(actor.owner.view_type)
            actor_ports = C0ValuePorts(
                roots={"actor": actor.owner.view_type},
                readable_paths=actor_paths,
                admission_readable_paths=actor_paths,
                readable_fields=actor_fields,
                admission_readable_fields=actor_fields,
                writable_fields={},
                record_types={},
                tuple_fields={},
                admission_tuple_fields={},
                collection_keys={},
                outputs={"tempo": int, "eligible": bool},
                pure_definitions=library.pure_definitions,
                source_context=program_context(
                    "control",
                    name,
                    {
                        f"outputs.{field}": ("game_form", "seats", control_index, field)
                        for field in ("tempo", "eligible")
                    },
                ),
            )
            projection = compile_value_program(
                json.dumps(
                    {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": {"const": True},
                        "outputs": {
                            "tempo": control["tempo"],
                            "eligible": control["eligible"],
                        },
                    }
                ),
                actor_ports,
                admission_outputs=frozenset({"tempo", "eligible"}),
            )
            sources = []
            for entry in selected.entries:
                action = action_by_name[entry]
                cost_value = compile_value_program(
                    json.dumps(
                        {
                            "schema": "c0.value.v1",
                            "bindings": [],
                            "guard": {"const": True},
                            "outputs": {"cost": control["costs"][entry]},
                        }
                    ),
                    replace(
                        action.value._ports,
                        outputs={"cost": int},
                        pure_definitions=library.pure_definitions,
                        source_context=program_context(
                            "cost",
                            entry,
                            {"outputs.cost": cost_origins.get(
                                (control_index, entry),
                                ("game_form", "seats", control_index, "costs", entry),
                            )},
                        ),
                    ),
                    admission_outputs=frozenset({"cost"}),
                )
                action_costs[entry] = _C0ActionCostProjector(
                    action._cost_basis(),
                    cost_value,
                    _K0CapabilityRef(f"c0.owner_graph.action_cost.{entry}.v1"),
                )
                sources.append(action.source_key)
                selected_sources.append(action.source_key)
            action_value_seats.append(
                _K0ActionValueSeat(
                    name,
                    actor.owner.key,
                    tuple(sources),
                    _C0ActionValueProjector(
                        projection,
                        _K0CapabilityRef(f"c0.owner_graph.action_value.{name}.v1"),
                    ),
                )
            )
        try:
            policy = replace(policy, pre_due_action_sources=tuple(selected_sources))
            action_value_policy = _K0ActionValuePolicy(
                _K0CapabilityRef("c0.owner_graph.action_value_scheduler.v1"),
                tuple(action_value_seats),
                _K0FixedTime(form_row["end_at"]) if form_row["end_at"] is not None else None,
                form_row["max_same_time_actions"],
            )
        except K0ProfileError as error:
            raise C0LawError("action-value GameForm binding is malformed") from error
        game_form = _ActionValueForm(tuple(selected_names), form_row["end_at"])
    else:
        raise C0LawError("GameForm declaration is malformed")
    raw_appraisals = row.get("appraisal_profiles", [])
    if (
        type(raw_appraisals) is not list
        or len(raw_appraisals) > 128
        or (raw_appraisals and type(game_form) is not _ActionValueForm)
    ):
        raise C0LawError("appraisal profiles need a finite action-value GameForm")
    appraisal_profiles = []
    seats_by_name = {seat.symbol: seat for seat in seats}
    for appraisal_index, raw in enumerate(raw_appraisals):
        seat_name = raw.get("seat") if type(raw) is dict else None
        seat = seats_by_name.get(seat_name) if type(seat_name) is str else None
        if seat is None or seat_name not in game_form.seats:
            raise C0LawError("appraisal profile names an uncontrolled seat")
        name = raw.get("name")
        context = binding_contexts.get(("appraisal_profiles", name)) if type(name) is str else None
        if context is None and source_context is not None:
            context = source_context.at(("appraisal_profiles", appraisal_index))
        if "definition" in raw:
            raw, context = appraisal_definitions.bind(raw, source_context=context)
        actor = owner_map[seat.actor]
        appraisal_profiles.append(
            compile_finite_appraisal(
                raw,
                seat=seat.symbol,
                actor_type=actor.owner.view_type,
                readable_paths=frozenset(f"actor.{path}" for path in actor.seat_readable_paths),
                entries=seat.entries,
                actions=dict(compiled),
                source_context=program_context(
                    "appraisal",
                    raw["name"],
                    context=context,
                ),
                pure_definitions=library.pure_definitions,
            )
        )
    if len({profile.name for profile in appraisal_profiles}) != len(appraisal_profiles):
        raise C0LawError("appraisal profile names must be unique")
    owners = tuple(sorted(library.owners, key=lambda item: item.owner.key))
    opening_guard = None
    if "opening_guard" in row:
        opening_guard = compile_value_program(
            json.dumps(
                {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": row["opening_guard"],
                    "outputs": {"valid": {"const": True}},
                }
            ),
            replace(
                _owner_guard_ports(owners, library.pure_definitions),
                source_context=program_context(
                    "opening", "opening_guard", context=binding_contexts.get(("opening_guard", ""))
                ),
            ),
        )
    if type(game_form) is _ActionValueForm and "world_stops" in form_row:
        declarations = form_row["world_stops"]
        if type(declarations) is not list or not 1 <= len(declarations) <= 8:
            raise C0LawError("GameForm world stops need a finite list")
        owner_by_symbol = {item.symbol: item for item in owners}
        stops = []
        for stop_index, raw_stop in enumerate(declarations):
            stop = _row(raw_stop, {"outcome", "owners", "when"}, "GameForm world stop")
            outcome, selected = stop["outcome"], stop["owners"]
            if (
                type(outcome) is not str
                or not outcome.isidentifier()
                or len(outcome) > 64
                or outcome in {item.outcome for item in stops}
                or type(selected) is not list
                or not selected
                or len(selected) > 32
                or any(type(name) is not str or name not in owner_by_symbol for name in selected)
                or len(set(selected)) != len(selected)
            ):
                raise C0LawError("GameForm world stop has a foreign outcome or owner")
            predicate = compile_value_program(
                json.dumps(
                    {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": stop["when"],
                        "outputs": {"valid": {"const": True}},
                    }
                ),
                replace(
                    _owner_guard_ports(
                        tuple(owner_by_symbol[name] for name in selected), library.pure_definitions
                    ),
                    source_context=program_context(
                        "world_stop",
                        outcome,
                        {"guard": ("game_form", "world_stops", stop_index, "when")},
                    ),
                ),
            )
            stops.append(_WorldStop(outcome, tuple(selected), predicate))
        game_form = replace(game_form, world_stops=tuple(stops))
    for seat in seats:
        presentation = seat.presentation
        if presentation is not None and presentation.finish_on_action:
            outcomes = (
                {stop.outcome for stop in game_form.world_stops}
                if type(game_form) is _ActionValueForm
                else set()
            )
            if any(outcome not in outcomes for _, outcome, _ in presentation.finish_on_action):
                raise C0LawError("Source seat finish message names an undeclared world stop")
    visibility_ir = capture_visibility(library.value_backend, world_ir, tuple(seats))
    control_ir = capture_control(
        library.value_backend,
        world_ir,
        tuple(C0ControlSeatIR(seat.symbol, seat.actor, seat.entries) for seat in seats),
        game_form,
        opening_guard,
        action_value_policy,
        action_costs,
        tuple(appraisal_profiles),
    )
    from .actor_template_v1 import capture_actor_templates

    actor_templates = capture_actor_templates(
        row.get("actor_templates", []),
        _selected_actor_kinds(library, row),
        dict(compiled),
        library.value_backend,
        library.pure_definitions,
        library.candidate_inputs,
        tuple((item["name"], item["template"]) for item in action_rows),
    )
    return (
        C0ProgramIR(
            world_ir,
            control_ir,
            visibility_ir,
            check_event_formations(row["ontology"]) if "ontology" in row else None,
            actor_templates,
            compile_constructions(
                row.get("opening_constructions", []),
                library.opening_constructions,
                selected_kinds,
                library.value_backend,
                library.pure_definitions,
                row,
            ),
        ),
        world_layout,
    )
