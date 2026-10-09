"""Assets checking precedes the sole atomic K0 Session allocation."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import TYPE_CHECKING, get_args, get_origin, get_type_hints

from nomos_kernel import (
    K0OccurrenceRef,
    K0ProfileError,
)
from nomos_kernel._action_value_abi import (
    _K0ActionValueOpening,
)
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemorySession,
)
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._dynamic_actor_abi import _K0OpeningActor
from nomos_kernel._dynamic_owner_abi import (
    _K0IndividualRef,
    _K0OpeningIndividual,
)
from nomos_kernel._event_jump_abi import _K0PeriodicDueOpening
from nomos_kernel._state_image_abi import _K0OwnerState

from .author_contract_v1 import C0BindingError, _unique_object
from .composable_value_v1 import (
    _MAX_INT,
    C0ValueStateError,
)
from .control_binding_v1 import (
    _ActionValueForm,
)
from .opening_construction_v1 import (
    C0OpeningConstructionReceipt,
    canonical_json,
    construct_opening,
)
from .variant_types_v1 import construct_variant, variant_cases, variant_common_fields

if TYPE_CHECKING:
    from .program_runtime_v1 import C0OwnerGraphProgram, C0OwnerGraphSession


def _assets(value: str | dict[str, object]) -> dict[str, object]:
    if type(value) is str:
        if not value or len(value) > 262144:
            raise C0BindingError("owner graph Assets are empty or too large")
        try:
            value = json.loads(value, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError) as error:
            raise C0BindingError("owner graph Assets are malformed JSON") from error
    if (
        type(value) is not dict
        or not {"schema", "opening"} <= set(value)
        or set(value)
        - {
            "schema",
            "opening",
            "time",
            "opening_objects",
            "opening_actors",
            "periodic_due_openings",
            "action_value_openings",
            "controllers",
            "opening_seeds",
        }
    ):
        raise C0BindingError("owner graph Assets have missing or unknown fields")
    return value


def _opening_fields(
    carrier: type, value: dict[str, object], names: tuple[str, ...], depth: int
) -> dict[str, object]:
    if any(type(name) is not str for name in value):
        raise C0BindingError("opening nominal record field names must be strings")
    hints = get_type_hints(carrier)
    unknown = set(value) - set(names)
    missing = {
        name
        for name in set(names) - set(value)
        if not (len(get_args(hints[name])) == 2 and type(None) in get_args(hints[name]))
    }
    if unknown or missing:
        raise C0BindingError(
            "opening nominal record fields do not match its carrier: "
            f"unknown={sorted(unknown)}, missing required={sorted(missing)}"
        )
    # Only Assets reconstruction supplies omitted optionals; runtime writes remain exact.
    return {name: _opening_value(hints[name], value.get(name), depth + 1) for name in names}


def _opening_value(annotation: object, value: object, depth: int = 0) -> object:
    if depth > 16:
        raise C0BindingError("opening nominal value is too deep")
    variants = get_args(annotation)
    if len(variants) == 2 and type(None) in variants:
        if value is None:
            return None
        return _opening_value(
            next(item for item in variants if item is not type(None)), value, depth + 1
        )
    if annotation is str and type(value) is str and value:
        return value
    if annotation is int and type(value) is int and 0 <= value <= _MAX_INT:
        return value
    if annotation is bool and type(value) is bool:
        return value
    if annotation in (K0OccurrenceRef, _K0IndividualRef, _K0ActorRef):
        raise C0BindingError("opening occurrence or instance identity cannot be authored")
    if get_origin(annotation) is tuple and len(variants) == 2 and variants[1] is Ellipsis:
        if type(value) is not list or len(value) > 256:
            raise C0BindingError("opening collection is malformed or too large")
        return tuple(_opening_value(variants[0], item, depth + 1) for item in value)
    if (
        isinstance(annotation, type)
        and is_dataclass(annotation)
        and annotation.__dataclass_params__.frozen
        and type(value) is dict
    ):
        cases = variant_cases(annotation)
        if cases:
            if (
                set(value) != {"case", "value", "fields"}
                or type(value["case"]) is not str
                or value["case"] not in cases
                or type(value["fields"]) is not dict
            ):
                raise C0BindingError("opening variant case, payload or common fields are malformed")
            case = value["case"]
            payload_type = cases[case]
            if payload_type is type(None):
                if value["value"] is not None:
                    raise C0BindingError("opening unit variant must have no payload")
                payload = None
            else:
                payload = _opening_value(payload_type, value["value"], depth + 1)
            common = _opening_fields(
                annotation, value["fields"], variant_common_fields(annotation), depth
            )
            try:
                return construct_variant(annotation, case, payload, common)
            except (TypeError, ValueError) as error:
                raise C0BindingError("opening variant value is invalid") from error
        normalized = _opening_fields(
            annotation, value, tuple(field.name for field in fields(annotation)), depth
        )
        try:
            return annotation(**normalized)
        except (TypeError, ValueError) as error:
            raise C0BindingError("opening nominal carrier cannot be built") from error
    raise C0BindingError("opening nominal value is malformed or unsupported")


def _opening(carrier: type, value: object) -> object:
    if not isinstance(carrier, type) or not is_dataclass(carrier):
        raise C0BindingError("opening owner needs an exact nominal record")
    return _opening_value(carrier, value)


def _constructed_opening(carrier: type, literal: dict, generated: dict) -> object:
    hints = get_type_hints(carrier)
    names = set(literal) | set(generated)
    missing = {
        name
        for name in hints.keys() - names
        if not (len(get_args(hints[name])) == 2 and type(None) in get_args(hints[name]))
    }
    if names - hints.keys() or missing:
        raise C0BindingError("constructed opening fields do not match the exact nominal carrier")
    values = {
        name: generated[name]
        if name in generated
        else _opening_value(annotation, literal.get(name))
        for name, annotation in hints.items()
    }
    try:
        return carrier(**values)
    except (TypeError, ValueError) as error:
        raise C0BindingError("constructed opening nominal carrier is invalid") from error


@dataclass(frozen=True)
class C0OpeningBinding:
    """Checked K0 inputs, not a saved Session or an author-editable snapshot."""

    states: tuple[_K0OwnerState, ...]
    time: _K0FixedTime | None
    objects: tuple[_K0OpeningIndividual, ...]
    periodic: tuple[_K0PeriodicDueOpening, ...]
    action_values: tuple[_K0ActionValueOpening, ...]
    controllers: tuple[tuple[str, str, str | None], ...]
    actors: tuple[_K0OpeningActor, ...] = ()
    construction: C0OpeningConstructionReceipt | None = None


def check_assets(program: C0OwnerGraphProgram, assets: str | dict[str, object]) -> C0OpeningBinding:
    row = _assets(assets)
    if row["schema"] != "c0.owner_graph.assets.v1":
        raise C0BindingError("owner graph Assets schema is unknown")
    opening = row["opening"]
    temporal = program.profile.temporal_policy is not None
    if ("time" in row) != temporal:
        raise C0BindingError("Assets time does not match selected temporal mechanism")
    if temporal and (type(row["time"]) is not int or not 0 <= row["time"] <= _MAX_INT):
        raise C0BindingError("opening time is not a bounded integer")
    action_value = type(program.game_form) is _ActionValueForm
    if ("periodic_due_openings" in row) != bool(program.periodic_plans):
        raise C0BindingError("Assets periodic openings do not match selected plans")
    if ("action_value_openings" in row) != action_value:
        raise C0BindingError("Assets action values do not match selected GameForm")
    if "controllers" in row and not action_value:
        raise C0BindingError("Assets controllers need an action-value GameForm")
    if type(opening) is not dict or set(opening) != {item.symbol for item in program.owners}:
        raise C0BindingError("Assets do not fill the Program's exact owner set")
    if ("opening_objects" in row) != bool(program.object_kinds):
        raise C0BindingError("Assets Object opening does not match selected kinds")
    raw_objects = row.get("opening_objects", [])
    if ("opening_actors" in row) != bool(program.actor_templates):
        raise C0BindingError("Assets Actor opening does not match selected templates")
    raw_actors = row.get("opening_actors", [])
    if type(raw_actors) is not list or len(raw_actors) > 256:
        raise C0BindingError("opening Actors are not a finite list")
    if type(raw_objects) is not list or len(raw_objects) > 256:
        raise C0BindingError("opening Objects are not a finite list")
    if any(type(raw) is not dict or set(raw) != {"kind", "state"} for raw in raw_objects):
        raise C0BindingError("opening Object row is malformed")
    if ("opening_seeds" in row) != bool(program.opening_constructions):
        raise C0BindingError("Assets opening seeds do not match selected constructions")
    states = []
    identities = []
    construction_slots = ()
    final_seeds = ()
    input_json = None
    try:
        if program.opening_constructions:
            try:
                input_json = canonical_json(row)
            except (TypeError, ValueError, RecursionError) as error:
                raise C0BindingError(
                    "construction Assets must be finite literal JSON data"
                ) from error
            raw_objects, construction_slots, final_seeds = construct_opening(
                program.opening_constructions, row["opening_seeds"], raw_objects, _opening_value
            )
        for item in program.owners:
            state = _opening(item.owner.state_type, opening[item.symbol])
            item.owner.validate_state(state)
            if item.owner.read_view(state) is not state:
                raise C0BindingError("opening owner view does not preserve its state")
            if item.identity_field is not None:
                identity = getattr(state, item.identity_field)
                if type(identity) is not str or not identity:
                    raise C0BindingError("Actor opening identity is malformed")
                identities.append(identity)
            states.append(_K0OwnerState(item.owner.key, state))
        if len(identities) != len(set(identities)):
            raise C0BindingError("Actor opening identities alias")
        opening_by_symbol = {
            item.symbol: state.state for item, state in zip(program.owners, states, strict=True)
        }
        for _, action in program.actions:
            for port in action.participants:
                if port.selector == "closed_domain" and any(
                    getattr(opening_by_symbol[symbol], port.identity_field) != symbol
                    for symbol, _ in port.members
                ):
                    raise C0BindingError("closed participant opening identity differs from Source")
        kinds = {item.symbol: item for item in program.object_kinds}
        opening_objects = []
        for raw in raw_objects:
            if type(raw) is not dict or set(raw) not in (
                {"kind", "state"},
                {"kind", "state", "generated"},
            ):
                raise C0BindingError("opening Object row is malformed")
            kind = kinds.get(raw["kind"]) if type(raw["kind"]) is str else None
            if kind is None:
                raise C0BindingError("opening Object has an undeclared kind")
            opening_objects.append(
                _K0OpeningIndividual(
                    kind.symbol,
                    _constructed_opening(kind.k0_kind.state_type, raw["state"], raw["generated"])
                    if "generated" in raw
                    else _opening(kind.k0_kind.state_type, raw["state"]),
                )
            )
        if program.opening_constructions:
            for item in opening_objects:
                item.initial_state.validate_for_k0()
            if any(
                sum(item.family == kind.symbol for item in opening_objects)
                > kind.k0_kind.max_instances
                for kind in program.object_kinds
            ):
                raise C0BindingError("constructed opening exceeds Object capacity")
        for seat in program.seats:
            if (
                seat.derived_read is not None
                and sum(
                    item.family == seat.derived_read.ports.object_kind for item in opening_objects
                )
                != 1
            ):
                raise C0BindingError("seat read Object needs one opening individual")
            for preview in seat.offer_previews:
                if sum(item.family == preview.ports.object_kind for item in opening_objects) != 1:
                    raise C0BindingError("offer preview Object needs one opening individual")
        actor_kinds = {item.kind.family: item.kind for item in program.actor_templates}
        opening_actors = []
        for raw in raw_actors:
            if type(raw) is not dict or set(raw) != {"kind", "state", "debt"}:
                raise C0BindingError("opening Actor row is malformed")
            kind = actor_kinds.get(raw["kind"]) if type(raw["kind"]) is str else None
            if kind is None:
                raise C0BindingError("opening Actor has an undeclared kind")
            opening_actors.append(
                _K0OpeningActor(
                    kind.family,
                    _opening(kind.state_type, raw["state"]),
                    raw["debt"],
                )
            )
        if program.opening_guard is not None and not program.opening_guard.admits(
            {item.symbol: state.state for item, state in zip(program.owners, states, strict=True)}
        ):
            raise C0BindingError("Assets fail the Source opening guard")
        raw_periodic = row.get("periodic_due_openings", [])
        if type(raw_periodic) is not list or len(raw_periodic) != len(program.periodic_plans):
            raise C0BindingError("periodic due openings are not a closed list")
        periodic_refs = dict(program.periodic_plans)
        periodic_openings = []
        for raw in raw_periodic:
            if type(raw) is not dict or set(raw) != {"plan", "first_at"}:
                raise C0BindingError("periodic due opening is malformed")
            plan = periodic_refs.get(raw["plan"]) if type(raw["plan"]) is str else None
            first_at = raw["first_at"]
            if plan is None or type(first_at) is not int or not 0 <= first_at <= _MAX_INT:
                raise C0BindingError("periodic due opening has a foreign plan or time")
            periodic_openings.append(_K0PeriodicDueOpening(plan, _K0FixedTime(first_at)))
        raw_action_values = row.get("action_value_openings", [])
        if type(raw_action_values) is not list:
            raise C0BindingError("action-value openings are not a closed list")
        action_value_openings = []
        for raw in raw_action_values:
            if type(raw) is not dict or set(raw) != {"seat", "debt", "tie_priority"}:
                raise C0BindingError("action-value opening is malformed")
            try:
                action_value_openings.append(
                    _K0ActionValueOpening(raw["seat"], raw["debt"], raw["tie_priority"])
                )
            except K0ProfileError as error:
                raise C0BindingError("action-value opening is malformed") from error
    except C0ValueStateError as error:
        raise C0BindingError("opening guard evaluation failed") from error
    except K0ProfileError as error:
        raise C0BindingError("opening owner state is not admitted") from error
    if (
        program.game_form is not None
        and program.game_form.end_at is not None
        and row["time"] > program.game_form.end_at
    ):
        raise C0BindingError("opening time exceeds GameForm end")
    controllers = []
    if action_value:
        raw_controllers = row.get("controllers")
        if raw_controllers is None:
            controllers = [(seat, "human_prompt", None) for seat in program.game_form.seats]
        else:
            if type(raw_controllers) is not list or len(raw_controllers) != len(
                program.game_form.seats
            ):
                raise C0BindingError("Assets controllers do not fill the selected seats")
            profiles = {profile.name: profile for profile in program.appraisal_profiles}
            for raw in raw_controllers:
                if type(raw) is not dict or raw.get("mode") not in (
                    "human_prompt",
                    "finite_appraisal",
                ):
                    raise C0BindingError("Assets controller is malformed")
                mode = raw["mode"]
                expected = (
                    {"seat", "mode", "profile"} if mode == "finite_appraisal" else {"seat", "mode"}
                )
                seat = raw.get("seat")
                if (
                    set(raw) != expected
                    or type(seat) is not str
                    or seat not in program.game_form.seats
                ):
                    raise C0BindingError("Assets controller has a foreign seat or shape")
                profile = raw.get("profile")
                if mode == "finite_appraisal" and (
                    type(profile) is not str
                    or profile not in profiles
                    or profiles[profile].seat != seat
                ):
                    raise C0BindingError("Assets controller names a foreign appraisal")
                controllers.append((seat, mode, profile))
            if {item[0] for item in controllers} != set(program.game_form.seats):
                raise C0BindingError("Assets controllers repeat or omit a seat")
    return C0OpeningBinding(
        tuple(states),
        _K0FixedTime(row["time"]) if temporal else None,
        tuple(opening_objects),
        tuple(periodic_openings),
        tuple(action_value_openings),
        tuple(controllers),
        tuple(opening_actors),
        C0OpeningConstructionReceipt(
            input_json,
            program.opening_constructions[0].ir.source_digest,
            tuple(plan.ir for plan in program.opening_constructions),
            tuple((name, row["opening_seeds"][name]) for name, _ in final_seeds),
            final_seeds,
            tuple(
                replace(slot, state=opening_objects[slot.slot].initial_state)
                for slot in construction_slots
            ),
            program.world_ir.signatures,
        )
        if input_json is not None
        else None,
    )


def start_program(
    program: C0OwnerGraphProgram, assets: str | dict[str, object]
) -> C0OwnerGraphSession:
    from .program_runtime_v1 import C0OwnerGraphSession

    opening = check_assets(program, assets)
    try:
        runtime = _K0InMemorySession.create(
            program.profile,
            opening.states,
            initial_time=opening.time,
            opening_individuals=opening.objects,
            opening_periodic_dues=opening.periodic,
            opening_action_values=opening.action_values,
            opening_actors=opening.actors,
        )
    except K0ProfileError as error:
        raise C0BindingError("opening owner state is not admitted") from error
    receipt = opening.construction
    if receipt is not None:
        bindings = runtime.individuals()
        receipt = replace(
            receipt,
            slots=tuple(
                replace(
                    slot, individual=bindings[slot.slot].individual, owner=bindings[slot.slot].owner
                )
                for slot in receipt.slots
            ),
        )
    return C0OwnerGraphSession(
        program, runtime, _controllers=opening.controllers, _opening_receipt=receipt
    )
