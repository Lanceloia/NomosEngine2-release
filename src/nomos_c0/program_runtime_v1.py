"""Bound Programs and live controls; no author documents or compilation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, field, fields
from types import MappingProxyType
from typing import Literal, get_type_hints

from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._action_value_abi import (
    _K0ActionValueDueBoundary,
)
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryOccurrence,
    _K0InMemoryProfile,
    _K0InMemorySession,
    _K0OrderedFormation,
)
from nomos_kernel._coordinates import _K0FixedTime, _K0TemporalAdvanceRequest, _K0TemporalInterval
from nomos_kernel._dynamic_owner_abi import (
    _K0IndividualBinding,
    _K0IndividualRef,
)
from nomos_kernel._occurrence_formation_abi import _K0CausalFormation
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
)
from nomos_kernel._settlement_outcome_abi import K0Published

from .actor_template_v1 import C0BoundActorTemplate
from .author_contract_v1 import C0BindingError, C0ControlBudgetExceeded
from .author_diagnostics_v1 import C0AuthorGuardReport
from .checked_value_binding_v1 import C0NamedWorldValueIR
from .composable_action_v1 import (
    C0ValueActionProgram,
)
from .composable_value_v1 import (
    _MAX_INT,
    C0ValueProgram,
    C0ValueStateError,
)
from .control_binding_v1 import (
    _ActionValueForm,
    _EventJumpForm,
)
from .control_ir_v1 import C0ControlIR
from .direct_actor_event_v1 import (
    C0DirectActorProgram,
)
from .direct_scene_event_v1 import (
    C0DirectSceneProgram,
)
from .event_formation_binding_v2 import EventFormationPlan
from .event_formation_v2 import (
    C0FormationSessionScope,
    C0FormedEventView,
    project_formed_events,
)
from .finite_appraisal_v1 import (
    C0AppraisalProposal,
    C0AppraisalRecord,
    C0FiniteAppraisalProfile,
    score_offers,
)
from .graph_contracts_v1 import C0GraphObjectKind, C0GraphOwner
from .nominal_fields_v1 import _read_leaf
from .nominal_types_v1 import ObjectSortRef
from .object_owner_binding_v1 import ObjectOwnerPlan
from .opening_construction_v1 import C0BoundOpeningConstruction, C0OpeningConstructionReceipt
from .program_ir_v1 import C0ProgramIR
from .scheduled_scene_event_v1 import (
    C0ScheduledSceneProgram,
)
from .seat_offers_v0 import (
    C0FixedParticipantOfferDeclaration,
    C0ObjectOfferDeclaration,
    C0ParticipantOfferDeclaration,
    C0SeatOffer,
    _offer_count_upper_bound,
)
from .semantic_ir_v0 import C0TemporalProgramIR
from .visibility_binding_v1 import _Seat
from .visibility_ir_v1 import C0VisibilityIR
from .world_binding_v1 import C0WorldLayout
from .world_ir_v1 import C0WorldIR


@dataclass(frozen=True)
class C0ObjectInstanceView:
    sort: ObjectSortRef
    individual: _K0IndividualRef
    owner: K0OwnerKey
    formed_by: K0OccurrenceRef | None
    current_state: object
    predecessor: K0OccurrenceRef | None = None


class C0ObjectTraceError(ValueError):
    """A K0 individual cannot be projected through the checked Object plan."""


@dataclass(frozen=True)
class C0ActorInstanceView:
    actor: _K0ActorRef
    owner: K0OwnerKey
    formed_by: K0OccurrenceRef | None
    born_at: int
    seat: str
    current_state: object


@dataclass(frozen=True)
class C0SeatView:
    fields: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class C0FormFrame:
    time: int
    view: C0SeatView
    offers: tuple[C0SeatOffer, ...]
    ready_seats: tuple[str, ...]
    finished: bool
    offer_faults: tuple[C0OfferFault, ...] = ()
    outcome: str | None = None


@dataclass(frozen=True)
class C0OfferFault:
    entry: str
    label: str
    code: str


@dataclass(frozen=True)
class C0FormChoice:
    time: int
    seat: str
    choice: str


@dataclass(frozen=True)
class C0ControlCommand:
    operation: Literal["submit", "defer", "continue", "advance"]
    seat: str
    offer: C0SeatOffer | None = None
    target_time: int | None = None


@dataclass(frozen=True)
class C0ControlResult:
    result: object


@dataclass(frozen=True)
class C0AuthorSnapshot:
    owners: tuple[tuple[str, object], ...]
    objects: tuple[C0ObjectInstanceView, ...]
    occurrences: tuple[_K0InMemoryOccurrence, ...]
    form_choices: tuple[C0FormChoice, ...]
    time: int | None
    actors: tuple[C0ActorInstanceView, ...] = ()


@dataclass
class _ProjectionReads:
    """Reuse isolated K0 views only within one synchronous, read-only projection."""

    runtime: _K0InMemorySession
    _owners: dict[K0OwnerKey, object] = field(default_factory=dict)
    _individuals: dict[_K0IndividualRef, object] = field(default_factory=dict)

    def owner(self, key: K0OwnerKey) -> object:
        if key not in self._owners:
            self._owners[key] = self.runtime.read_owner(key).view
        return self._owners[key]

    def individual(self, ref: _K0IndividualRef) -> object:
        if ref not in self._individuals:
            self._individuals[ref] = self.runtime.read_individual(ref).view
        return self._individuals[ref]


@dataclass(frozen=True, repr=False, init=False)
class C0OwnerGraphProgram:
    owners: tuple[C0GraphOwner, ...]
    actions: tuple[tuple[str, C0ValueActionProgram], ...]
    events: tuple[tuple[str, C0DirectSceneProgram | C0DirectActorProgram], ...]
    seats: tuple[_Seat, ...]
    profile: _K0InMemoryProfile
    advance_seats: frozenset[str]
    game_form: _EventJumpForm | _ActionValueForm | None
    opening_guard: C0ValueProgram | None = None
    formation_plan: EventFormationPlan | None = None
    object_kinds: tuple[C0GraphObjectKind, ...] = ()
    object_plan: ObjectOwnerPlan | None = None
    periodic_plans: tuple[tuple[str, _K0CapabilityRef], ...] = ()
    appraisal_profiles: tuple[C0FiniteAppraisalProfile, ...] = ()
    due_laws: tuple[tuple[str, C0ScheduledSceneProgram], ...] = ()
    temporal_ir: C0TemporalProgramIR | None = None
    world_layout: C0WorldLayout | None = None
    program_ir: C0ProgramIR | None = None
    actor_templates: tuple[C0BoundActorTemplate, ...] = ()
    opening_constructions: tuple[C0BoundOpeningConstruction, ...] = ()
    _actions_by_name: Mapping[str, C0ValueActionProgram] = field(
        init=False, repr=False, compare=False
    )
    _owners_by_symbol: Mapping[str, C0GraphOwner] = field(init=False, repr=False, compare=False)
    _seats_by_symbol: Mapping[str, _Seat] = field(init=False, repr=False, compare=False)
    _appraisals_by_name: Mapping[str, C0FiniteAppraisalProfile] = field(
        init=False, repr=False, compare=False
    )
    _candidate_checks_by_seat: Mapping[str, Mapping[int, object]] = field(
        init=False, repr=False, compare=False
    )

    def __init__(self, *args, **kwargs):
        raise C0BindingError("Program must be published by complete checked Bind")

    @classmethod
    def _from_binding(cls, **values):
        # Private backend construction, not an author token or a hot-rebind API.
        result = object.__new__(cls)
        for declaration in fields(cls):
            if not declaration.init:
                continue
            if declaration.name in values:
                value = values.pop(declaration.name)
            elif declaration.default is not MISSING:
                value = declaration.default
            else:
                raise C0BindingError("bound Program is missing a compiled component")
            object.__setattr__(result, declaration.name, value)
        if values:
            raise C0BindingError("bound Program has an unknown compiled component")
        result.__post_init__()
        return result

    def __post_init__(self) -> None:
        # These indexes contain declarations, never current owner state or read grants.
        def index(rows):
            result = dict(rows)
            if len(result) != len(rows):
                raise C0BindingError("bound Program repeats a declaration identity")
            return MappingProxyType(result)

        for name, rows in (
            ("_actions_by_name", self.actions),
            ("_owners_by_symbol", tuple((item.symbol, item) for item in self.owners)),
            ("_seats_by_symbol", tuple((item.symbol, item) for item in self.seats)),
            ("_appraisals_by_name", tuple((item.name, item) for item in self.appraisal_profiles)),
            (
                "_candidate_checks_by_seat",
                tuple((item.symbol, index(item.candidate_checks)) for item in self.seats),
            ),
        ):
            object.__setattr__(self, name, index(rows))

    def __repr__(self) -> str:
        # Shared IR graphs must not be recursively expanded by failure reporters.
        return (
            f"{type(self).__name__}(owners={len(self.owners)}, "
            f"actions={len(self.actions)}, events={len(self.events)}, "
            f"seats={len(self.seats)}, object_kinds={len(self.object_kinds)})"
        )

    @property
    def world_ir(self) -> C0WorldIR | None:
        return self.program_ir.world if self.program_ir is not None else None

    @property
    def control_ir(self) -> C0ControlIR | None:
        return self.program_ir.control if self.program_ir is not None else None

    @property
    def visibility_ir(self) -> C0VisibilityIR | None:
        return self.program_ir.visibility if self.program_ir is not None else None

    @property
    def world_values(self) -> tuple[C0NamedWorldValueIR, ...]:
        return (
            tuple(
                C0NamedWorldValueIR(item.formation, item.symbol, item.body)
                for item in self.program_ir.world.transitions
            )
            if self.program_ir is not None
            else ()
        )

    def start(self, assets: str | dict[str, object]) -> C0OwnerGraphSession:
        from .program_start_v1 import start_program

        return start_program(self, assets)


@dataclass(repr=False)
class C0OwnerGraphSession:
    program: C0OwnerGraphProgram
    _runtime: _K0InMemorySession
    _pending_seats: set[str] = field(default_factory=set)
    _form_choices: list[C0FormChoice] = field(default_factory=list)
    _formation_scope: C0FormationSessionScope = field(default_factory=C0FormationSessionScope)
    _controllers: tuple[tuple[str, str, str | None], ...] = ()
    _appraisal_history: list[C0AppraisalRecord] = field(default_factory=list)
    _opening_receipt: C0OpeningConstructionReceipt | None = None

    def __repr__(self) -> str:
        # Diagnostics neither traverse the runtime nor read private owner state.
        return (
            f"{type(self).__name__}(program={self.program!r}, "
            f"pending_seats={len(self._pending_seats)}, "
            f"form_choices={len(self._form_choices)})"
        )

    def author_opening_construction(self) -> C0OpeningConstructionReceipt | None:
        """Trusted author audit only; no evaluation or seed consumption on readback."""
        return self._opening_receipt

    def __post_init__(self) -> None:
        form = self.program.game_form
        if type(form) is _EventJumpForm and self.time < form.end_at:
            self._pending_seats.update(
                seat for seat in form.seats if any(self._offer_projection(seat))
            )

    @property
    def time(self) -> int:
        if self.program.profile.temporal_policy is None:
            raise C0BindingError("this Session has no selected time mechanism")
        return self._runtime.read_time().ordinal

    def _world_outcome(self) -> str | None:
        terminal = self._runtime.terminal_state()
        return None if terminal is None else terminal.outcome

    def advance(self, seat: str, target: int) -> object:
        if self.program.game_form is not None:
            raise C0BindingError("selected GameForm owns time advancement")
        if seat not in self.program.advance_seats:
            raise C0BindingError("seat cannot advance this Session")
        if type(target) is not int or not self.time < target <= _MAX_INT:
            raise C0BindingError("advance needs a future bounded time")
        return self._runtime.advance(
            _K0TemporalAdvanceRequest(
                _K0TemporalInterval(_K0FixedTime(self.time), _K0FixedTime(target))
            )
        )

    def read(self, seat: str) -> C0SeatView:
        return self._project_read(seat, _ProjectionReads(self._runtime))

    def _dynamic_actor(self, seat: str):
        binding = next((item for item in self._runtime.actors() if item.seat == seat), None)
        if binding is None:
            return None
        template = next(
            (
                item
                for item in self.program.actor_templates
                if item.kind.family == binding.actor.family
            ),
            None,
        )
        if template is None or binding.control != template.kind.control:
            raise C0BindingError("formed Actor lacks its compiled control template")
        return binding, template

    def _has_seat(self, seat: str) -> bool:
        return seat in self.program._seats_by_symbol or (self._dynamic_actor(seat) is not None)

    def _project_read(self, seat: str, reads: _ProjectionReads) -> C0SeatView:
        dynamic = self._dynamic_actor(seat)
        if dynamic is not None:
            binding, template = dynamic
            view = reads.owner(binding.owner)
            return C0SeatView(
                tuple(
                    (path, _read_leaf(view, path.split(".", 1)[1]))
                    for path in template.ir.read_paths
                )
            )
        selected = self.program._seats_by_symbol.get(seat)
        if selected is None:
            raise C0BindingError("seat is not bound to this Session")
        owners = self.program._owners_by_symbol
        views = {}
        fields = []
        for path in selected.read_paths:
            symbol, leaf = path.split(".", 1)
            if symbol not in views:
                views[symbol] = reads.owner(owners[symbol].owner.key)
            value = _read_leaf(views[symbol], leaf)
            if value is not None:
                fields.append((path, value))
        if selected.derived_read is not None:
            projection = selected.derived_read
            scene_owner = owners[projection.ports.scene_owner]
            scene = reads.owner(scene_owner.owner.key)
            actor = views.get(selected.actor)
            if actor is None:
                actor = reads.owner(owners[selected.actor].owner.key)
            bindings = tuple(
                item.individual
                for item in self._runtime.individuals()
                if item.individual.family == projection.ports.object_kind
            )
            if len(bindings) != 1:
                raise C0BindingError("seat read Object is no longer unique")
            selected_object = reads.individual(bindings[0])
            try:
                result = projection.project(scene, actor, selected_object)
            except C0ValueStateError as error:
                raise C0BindingError(
                    "seat read projection cannot evaluate current state"
                ) from error
            fields.append((projection.ports.symbol, result))
        return C0SeatView(tuple(fields))

    def offers(self, seat: str) -> tuple[C0SeatOffer, ...]:
        if not self._has_seat(seat):
            raise C0BindingError("seat is not bound to this Session")
        reads = _ProjectionReads(self._runtime)
        if self._world_outcome() is not None:
            return ()
        return self._project_offers(seat, reads)[0]

    def offer_faults(self, seat: str) -> tuple[C0OfferFault, ...]:
        if not self._has_seat(seat):
            raise C0BindingError("seat is not bound to this Session")
        reads = _ProjectionReads(self._runtime)
        if self._world_outcome() is not None:
            return ()
        return self._project_offers(seat, reads)[1]

    def _offer_projection(
        self, seat: str
    ) -> tuple[tuple[C0SeatOffer, ...], tuple[C0OfferFault, ...]]:
        return self._project_offers(seat, _ProjectionReads(self._runtime))

    def _project_offers(
        self, seat: str, reads: _ProjectionReads, *, entry: str | None = None
    ) -> tuple[tuple[C0SeatOffer, ...], tuple[C0OfferFault, ...]]:
        dynamic = self._dynamic_actor(seat)
        if dynamic is not None:
            if entry is not None:
                raise C0BindingError("formed Actor offers require complete fault checking")
            binding, template = dynamic
            actor = reads.owner(binding.owner)
            allowed = []
            faults = []
            for declaration in template.offers:
                try:
                    offer = declaration.project(actor)
                    if offer is None:
                        continue
                    action = self.program._actions_by_name[offer.entry]
                    payload = self._dynamic_attempt(binding, offer, reads)
                    roots = self._selected_action_roots(action, actor, payload, reads)
                    if (
                        roots is not None
                        and (
                            declaration.candidate_check is None
                            or declaration.candidate_check.allows(roots)
                        )
                        and offer not in allowed
                    ):
                        allowed.append(offer)
                except C0ValueStateError:
                    faults.append(C0OfferFault(declaration.entry, declaration.label, "value_state"))
            return tuple(allowed), tuple(faults)
        selected = self.program._seats_by_symbol.get(seat)
        if selected is None:
            raise C0BindingError("seat is not bound to this Session")
        actions = self.program._actions_by_name
        result = []
        faults = []
        candidate_checks = self.program._candidate_checks_by_seat[seat]
        for index, declaration in enumerate(selected.offers):
            if entry is not None and declaration.entry != entry:
                continue
            action = actions[declaration.entry]
            scene = reads.owner(action.scene_owner.key)
            actor = reads.owner(action.actor_owner.key)
            try:
                if type(declaration) in (
                    C0ObjectOfferDeclaration,
                    C0ParticipantOfferDeclaration,
                    C0FixedParticipantOfferDeclaration,
                ):
                    families = (
                        declaration.all_object_kinds
                        if type(declaration) is C0ParticipantOfferDeclaration
                        else declaration.kinds
                    )
                    objects = tuple(
                        (binding.individual, reads.individual(binding.individual))
                        for binding in self._runtime.individuals()
                        if binding.individual.family in families
                    )
                    offers = declaration.evaluate_many(scene, actor, objects)
                    if any(port.selector == "actor" for port in action.ir.selected):
                        offers = tuple(
                            offer
                            for offer in offers
                            if self._selected_action_roots(
                                action,
                                actor,
                                self._attempt_for_offer(selected, offer, actor, reads),
                                reads,
                            )
                            is not None
                        )
                else:
                    offers = declaration.evaluate_many(scene, actor)
                check = candidate_checks.get(index)
                if check is not None:
                    allowed = []
                    for offer in offers:
                        payload = self._attempt_for_offer(selected, offer, actor, reads)
                        roots = self._selected_action_roots(action, actor, payload, reads)
                        if roots is not None and check.allows(roots):
                            allowed.append(offer)
                    offers = tuple(allowed)
            except C0ValueStateError:
                faults.append(C0OfferFault(declaration.entry, declaration.label, "value_state"))
                continue
            if len(result) + len(offers) > selected.offer_limit:
                faults.append(C0OfferFault(declaration.entry, declaration.label, "value_state"))
                return (), tuple(faults)
            for offer in offers:
                if any(
                    previous.entry == offer.entry and previous.payload == offer.payload
                    for previous in result
                ):
                    continue
                result.append(offer)
        for preview in selected.offer_previews:
            if entry is not None and preview.entry != entry:
                continue
            bindings = tuple(
                item.individual
                for item in self._runtime.individuals()
                if item.individual.family == preview.ports.object_kind and item.formed_by is None
            )
            if len(bindings) != 1:
                continue
            selected_object = reads.individual(bindings[0])
            scene = reads.owner(self.program._owners_by_symbol[preview.ports.scene_owner].owner.key)
            actor = reads.owner(self.program._owners_by_symbol[preview.ports.actor].owner.key)
            for index, offer in enumerate(result):
                if offer.entry == preview.entry:
                    try:
                        result[index] = preview.project(scene, actor, selected_object, offer)
                    except C0ValueStateError:
                        result[index] = offer
        return tuple(result), tuple(faults)

    def _can_project_entry(self, selected: _Seat, reads: _ProjectionReads) -> bool:
        # The complete menu's overflow must still reject all offers. Prove a safe
        # upper bound before skipping unrelated declarations; never cache across Actions.
        families = Counter(binding.individual.family for binding in self._runtime.individuals())
        bound = 0
        try:
            for declaration in selected.offers:
                action = self.program._actions_by_name[declaration.entry]
                maximum = _offer_count_upper_bound(
                    declaration,
                    reads.owner(action.scene_owner.key),
                    reads.owner(action.actor_owner.key),
                    families,
                )
                if maximum is None:
                    return False
                bound += maximum
                if bound > selected.offer_limit:
                    return False
        except C0ValueStateError:
            return False
        return True

    def _seat_projection(
        self, seat: str
    ) -> tuple[C0SeatView, tuple[C0SeatOffer, ...], tuple[C0OfferFault, ...]]:
        reads = _ProjectionReads(self._runtime)
        offers, faults = self._project_offers(seat, reads)
        return self._project_read(seat, reads), offers, faults

    def _controller(self, seat: str) -> tuple[str, str | None]:
        dynamic = self._dynamic_actor(seat)
        if dynamic is not None:
            template = dynamic[1]
            return template.ir.mode, (
                None if template.appraisal is None else template.appraisal.name
            )
        selected = next((item for item in self._controllers if item[0] == seat), None)
        return ("human_prompt", None) if selected is None else (selected[1], selected[2])

    def human_seats(self) -> tuple[str, ...]:
        return tuple(
            seat.symbol
            for seat in self.program.seats
            if self._controller(seat.symbol)[0] == "human_prompt"
        ) + tuple(
            item.seat
            for item in self._runtime.actors()
            if self._controller(item.seat)[0] == "human_prompt"
        )

    def _dynamic_offer_declaration(self, template, offer):
        declaration = next(
            (
                item
                for item in template.offers
                if item.entry == offer.entry
                and set(item.value._ports.outputs) - {"offered"} == set(dict(offer.payload))
            ),
            None,
        )
        if declaration is None:
            raise C0BindingError("formed Actor offer does not match its public payload partition")
        return declaration

    def _dynamic_attempt(self, binding, offer, reads: _ProjectionReads):
        from nomos_kernel._actor_identity import _K0ActorRef

        dynamic = self._dynamic_actor(binding.seat)
        if dynamic is None or dynamic[0] != binding or offer.entry not in dynamic[1].ir.entries:
            raise C0BindingError("instance-relative offer needs its actual registered self Actor")
        action = self.program._actions_by_name[offer.entry]
        declaration = self._dynamic_offer_declaration(dynamic[1], offer)
        values = self._complete_private_values(
            action,
            declaration.private_actor_fields,
            dict(offer.payload),
            binding.actor,
            reads.owner(binding.owner),
            reads,
        )
        hints = get_type_hints(action.payload_type)
        if set(values) != set(hints) or any(
            (
                annotation not in (str, int, bool, _K0ActorRef)
                or type(values[name]) is not annotation
            )
            and not (
                annotation == str | None
                and any(p.nullable and p.payload_field == name for p in action.ir.selected)
                and type(values[name]) in (str, type(None))
            )
            for name, annotation in hints.items()
        ):
            raise C0BindingError("instance-relative Action has malformed payload fields")
        attempt = action.payload_type(**values)
        attempt.validate_for_k0()
        return attempt

    def submit(self, seat: str, entry: str, payload: dict[str, object]) -> object:
        if self._controller(seat)[0] != "human_prompt":
            raise C0BindingError("automated seat requires its current appraisal proposal")
        return self._submit_selected(seat, entry, payload)

    def _complete_private_values(self, action, bindings, payload, identity, actor, reads):
        values = {**payload, action.payload_actor_field: identity}
        roles = {port.payload_field: port for port in action.ir.selected}
        for binding in bindings:
            if binding.payload_field in values:
                raise C0BindingError("public payload cannot inject a private participant")
            values[binding.payload_field] = (
                None if roles[binding.payload_field].nullable else binding.member
            )
        if any(binding.condition is not None for binding in bindings):
            # Resolve required inputs first; no nullable owner is read to choose its identity.
            initial = {
                name: None if name in roles and roles[name].nullable else value
                for name, value in values.items()
            }
            attempt = action.payload_type(**initial)
            attempt.validate_for_k0()
            roots = self._selected_action_roots(action, actor, attempt, reads)
            if roots is None:
                raise C0BindingError("private participant prerequisites are no longer available")
            for binding in bindings:
                values[binding.payload_field] = binding.resolve(roots)
        else:
            for binding in bindings:
                values[binding.payload_field] = binding.member
        return values

    def _attempt_for_offer(
        self, selected: _Seat, offer: C0SeatOffer, actor_view: object, reads: _ProjectionReads
    ) -> object:
        action = self.program._actions_by_name[offer.entry]
        payload = dict(offer.payload)
        fixed = next(
            (
                item
                for item in selected.offers
                if type(item) is C0FixedParticipantOfferDeclaration and item.entry == offer.entry
            ),
            None,
        )
        if fixed is not None:
            individuals = tuple(
                binding.individual
                for binding in self._runtime.individuals()
                if binding.individual.family in fixed.kinds
            )
            if len(individuals) != len(fixed.kinds):
                raise C0BindingError("fixed participant Objects are no longer unique")
            payload = {**payload, **fixed.resolve_payload(individuals)}
        # The public field partition fixes which checked singleton selectors are omitted.
        participant = next(
            (
                item
                for item in selected.offers
                if type(item) is C0ParticipantOfferDeclaration
                and item.entry == offer.entry
                and set(item.payload) == set(payload)
            ),
            None,
        )
        actor = self.program._owners_by_symbol[selected.actor]
        identity = getattr(actor_view, actor.identity_field)
        values = self._complete_private_values(
            action,
            () if participant is None else participant.private_actor_fields,
            payload,
            identity,
            actor_view,
            reads,
        )
        hints = get_type_hints(action.payload_type)
        if set(values) != set(hints):
            raise C0BindingError("Action payload does not fill exact non-Actor fields")
        actor_fields = {
            port.payload_field for port in action.ir.selected if port.selector == "actor"
        }
        nullable_fields = {port.payload_field for port in action.ir.selected if port.nullable}
        for name, annotation in hints.items():
            if name in nullable_fields:
                if annotation != str | None or type(values[name]) not in (str, type(None)):
                    raise C0BindingError("Action nullable participant field is malformed")
                continue
            if (
                annotation not in (str, int, bool, _K0IndividualRef, K0OccurrenceRef)
                and not (annotation is _K0ActorRef and name in actor_fields)
                or type(values[name]) is not annotation
            ):
                raise C0BindingError("Action payload field is malformed")
        attempt = action.payload_type(**values)
        attempt.validate_for_k0()
        return attempt

    def _submit_selected(self, seat: str, entry: str, payload: dict[str, object]) -> object:
        form = self.program.game_form
        if form is not None and (
            (form.end_at is not None and self.time >= form.end_at)
            or self._world_outcome() is not None
        ):
            raise C0BindingError("GameForm has finished")
        if form is not None and seat not in form.seats and self._dynamic_actor(seat) is None:
            raise C0BindingError("seat is not controlled by this GameForm")
        if type(form) is _EventJumpForm and seat not in self._pending_seats:
            raise C0BindingError("seat has no pending GameForm opportunity")
        if type(form) is _ActionValueForm:
            opportunity = self._runtime.action_opportunity()
            if opportunity is None or opportunity.seat != seat:
                raise C0BindingError("seat has no current action-value opportunity")
        reads = _ProjectionReads(self._runtime)
        dynamic = self._dynamic_actor(seat)
        if dynamic is not None:
            binding, template = dynamic
            if entry not in template.ir.entries or type(payload) is not dict:
                raise C0BindingError("seat cannot invoke this instance-relative Action")
            offer = next(
                (
                    item
                    for item in self._project_offers(seat, reads)[0]
                    if item.entry == entry and dict(item.payload) == payload
                ),
                None,
            )
            if offer is None:
                raise C0BindingError("Action value is not a current seat offer")
            action = self.program._actions_by_name[entry]
            return self._runtime.settle(
                _K0InMemoryActionAttempt(
                    action.source_key,
                    self._dynamic_attempt(binding, offer, reads),
                )
            )
        selected = self.program._seats_by_symbol.get(seat)
        if selected is None or entry not in selected.entries:
            raise C0BindingError("seat cannot invoke this Action entry")
        if type(payload) is not dict:
            raise C0BindingError("Action value is not a current seat offer")
        offered = next(
            (
                offer
                for offer in self._project_offers(
                    seat, reads, entry=entry if self._can_project_entry(selected, reads) else None
                )[0]
                if offer.entry == entry and dict(offer.payload) == payload
            ),
            None,
        )
        if offered is None:
            raise C0BindingError("Action value is not a current seat offer")
        action = self.program._actions_by_name[entry]
        actor = self.program._owners_by_symbol[selected.actor]
        attempt = self._attempt_for_offer(selected, offered, reads.owner(actor.owner.key), reads)
        before = (
            {name: self._seat_projection(name) for name in form.seats}
            if type(form) is _EventJumpForm
            else {}
        )
        result = self._runtime.settle(_K0InMemoryActionAttempt(action.source_key, attempt))
        if type(form) is _EventJumpForm and isinstance(result, K0Published):
            self._pending_seats.discard(seat)
            self._pending_seats.update(
                name for name, previous in before.items() if self._seat_projection(name) != previous
            )
        return result

    def propose_appraisal(self, seat: str) -> C0AppraisalProposal:
        return self._prepare_appraisal(seat)[0]

    def _prepare_appraisal(self, seat: str) -> tuple[C0AppraisalProposal, object]:
        mode, profile_name = self._controller(seat)
        if mode != "finite_appraisal" or type(self.program.game_form) is not _ActionValueForm:
            raise C0BindingError("seat has no selected finite appraisal")
        opportunity = self._runtime.action_opportunity()
        if (
            opportunity is None
            or opportunity.seat != seat
            or (
                self.program.game_form.end_at is not None
                and self.time >= self.program.game_form.end_at
            )
            or self._world_outcome() is not None
        ):
            raise C0BindingError("seat has no current appraisal opportunity")
        dynamic = self._dynamic_actor(seat)
        reads = _ProjectionReads(self._runtime)
        if dynamic is not None:
            from dataclasses import replace

            binding, template = dynamic
            offers, faults = self._project_offers(seat, reads)
            if faults or not offers:
                raise C0BindingError("formed Actor has no evaluable current world offers")
            try:
                payloads = tuple(self._dynamic_attempt(binding, offer, reads) for offer in offers)
                proposal = score_offers(
                    replace(template.appraisal, seat=seat),
                    offers,
                    actor=self._runtime.read_actor(binding.actor).view,
                    payloads=payloads,
                    time=self.time,
                )
                return proposal, payloads[offers.index(proposal.chosen)]
            except C0ValueStateError as error:
                raise C0BindingError(
                    "formed Actor appraisal cannot evaluate current state"
                ) from error
        selected = self.program._seats_by_symbol[seat]
        actor = self.program._owners_by_symbol[selected.actor]
        view = reads.owner(actor.owner.key)
        profile = self.program._appraisals_by_name[profile_name]
        offers, faults = self._project_offers(seat, reads)
        if faults:
            raise C0BindingError("current offers have a value projection fault")
        if not offers:
            raise C0BindingError("appraisal has no current world Action offer")
        try:
            payloads = tuple(
                self._attempt_for_offer(selected, offer, view, reads) for offer in offers
            )
            proposal = score_offers(
                profile,
                offers,
                actor=view,
                payloads=payloads,
                time=self.time,
            )
            return proposal, payloads[offers.index(proposal.chosen)]
        except C0ValueStateError as error:
            raise C0BindingError("current appraisal score cannot be evaluated") from error

    def commit_appraisal(self, proposal: C0AppraisalProposal) -> object:
        if type(proposal) is not C0AppraisalProposal:
            raise C0BindingError("appraisal proposal is malformed")
        current, attempt = self._prepare_appraisal(proposal.seat)
        if proposal != current:
            raise C0BindingError("appraisal proposal is stale or foreign")
        return self._publish_appraisal(current, attempt)

    def _publish_appraisal(self, proposal: C0AppraisalProposal, attempt: object) -> object:
        # Consume only the current preparation, synchronously, without an intervening transition.
        action = self.program._actions_by_name[proposal.chosen.entry]
        result = self._runtime.settle(_K0InMemoryActionAttempt(action.source_key, attempt))
        self._appraisal_history.append(
            C0AppraisalRecord(
                proposal, "published" if isinstance(result, K0Published) else "not_admitted"
            )
        )
        return result

    def appraisal_history(self) -> tuple[C0AppraisalRecord, ...]:
        """Trusted author audit, separate from all Actor-local read models."""
        return tuple(self._appraisal_history)

    def author_guard_report(self, seat: str, offer: C0SeatOffer) -> C0AuthorGuardReport:
        """Check current authored predicates, not the historical or complete K0 refusal."""
        selected = self.program._seats_by_symbol.get(seat)
        if (
            selected is None
            or type(offer) is not C0SeatOffer
            or offer.entry not in selected.entries
        ):
            raise C0BindingError("author diagnostic needs a bound seat Action")
        action = self.program._actions_by_name[offer.entry]

        def report(status, failures=()):
            return C0AuthorGuardReport(offer.entry, action.source_key.value, status, failures)

        reads = _ProjectionReads(self._runtime)
        actor = reads.owner(action.actor_owner.key)
        try:
            payload = self._attempt_for_offer(selected, offer, actor, reads)
            roots = self._selected_action_roots(action, actor, payload, reads)
            if roots is None:
                return report("basis_unavailable")
            failures = action.value.false_guard_clauses(roots)
        except C0BindingError:
            return report("basis_unavailable")
        except C0ValueStateError:
            return report("evaluation_fault")
        return report("false_predicates" if failures else "no_false_predicates", failures)

    def _selected_action_roots(self, action, actor, payload, reads):
        if action.ir.self_actor is not None:
            ref = getattr(payload, action.payload_actor_field)
            binding = next((item for item in self._runtime.actors() if item.actor == ref), None)
            if binding is None or ref.family != action.ir.self_actor[0]:
                return None
            actor = reads.owner(binding.owner)
        participants = []
        for port in action.ir.selected:
            selector = getattr(payload, port.payload_field)
            if port.nullable and selector is None:
                continue
            if port.selector == "individual":
                if type(selector) is not _K0IndividualRef or selector.family not in port.families:
                    return None
                binding = next(
                    (item for item in self._runtime.individuals() if item.individual == selector),
                    None,
                )
                if binding is None:
                    return None
                participants.append((port.root, reads.individual(selector), binding.owner))
            elif port.selector == "actor":
                if type(selector) is not _K0ActorRef or selector.family not in port.families:
                    return None
                binding = next(
                    (item for item in self._runtime.actors() if item.actor == selector), None
                )
                if binding is None:
                    return None
                participants.append((port.root, reads.owner(binding.owner), binding.owner))
            else:
                key = dict(port.members).get(selector)
                if key is None:
                    return None
                owner = K0OwnerKey(key)
                view = reads.owner(owner)
                if getattr(view, port.identity_field) != selector:
                    return None
                participants.append((port.root, view, owner))
        return action._roots(
            reads.owner(action.scene_owner.key),
            actor,
            payload,
            participants[0][1] if action._has_target() else None,
            () if action._has_target() else tuple(participants),
        )

    def form_frame(self, seat: str) -> C0FormFrame:
        form = self.program.game_form
        if form is None or (seat not in form.seats and self._dynamic_actor(seat) is None):
            raise C0BindingError("seat has no selected event-jump GameForm")
        reads = _ProjectionReads(self._runtime)
        outcome = self._world_outcome()
        finished = (form.end_at is not None and self.time >= form.end_at) or outcome is not None
        view = self._project_read(seat, reads)
        opportunity = self._runtime.action_opportunity() if type(form) is _ActionValueForm else None
        active = not finished and (
            seat in self._pending_seats
            if type(form) is _EventJumpForm
            else opportunity is not None and opportunity.seat == seat
        )
        offers, faults = self._project_offers(seat, reads) if active else ((), ())
        return C0FormFrame(
            self.time,
            view,
            offers,
            ()
            if finished
            else (
                tuple(name for name in form.seats if name in self._pending_seats)
                if type(form) is _EventJumpForm
                else (() if opportunity is None else (opportunity.seat,))
            ),
            finished,
            faults,
            outcome,
        )

    def defer_form(self, seat: str) -> C0FormFrame:
        form = self.program.game_form
        if (
            type(form) is not _EventJumpForm
            or seat not in form.seats
            or seat not in self._pending_seats
            or self.time >= form.end_at
        ):
            raise C0BindingError("seat has no pending GameForm opportunity")
        self._pending_seats.remove(seat)
        self._form_choices.append(C0FormChoice(self.time, seat, "defer"))
        return self.form_frame(seat)

    def form_control_history(self) -> tuple[C0FormChoice, ...]:
        return tuple(self._form_choices)

    def apply_control(self, command: C0ControlCommand) -> C0ControlResult:
        """One shared control transition for interactive play and author verification."""
        if type(command) is not C0ControlCommand or type(command.seat) is not str:
            raise C0BindingError("control command is malformed")
        operation = command.operation
        if operation == "submit":
            if type(command.offer) is not C0SeatOffer or command.target_time is not None:
                raise C0BindingError("submit needs one current offer")
        elif operation == "advance":
            if command.offer is not None or type(command.target_time) is not int:
                raise C0BindingError("advance needs one future time")
        elif operation in ("defer", "continue"):
            if command.offer is not None or command.target_time is not None:
                raise C0BindingError("GameForm control has unexpected operands")
        else:
            raise C0BindingError("control operation is unknown")

        if operation == "submit":
            assert command.offer is not None
            result = self.submit(command.seat, command.offer.entry, dict(command.offer.payload))
        elif operation == "advance":
            assert command.target_time is not None
            result = self.advance(command.seat, command.target_time)
        elif operation == "defer":
            result = self.defer_form(command.seat)
        else:
            result = self.continue_form(command.seat)
        return C0ControlResult(result)

    def author_snapshot(self) -> C0AuthorSnapshot:
        """Trusted verification view; never feed it into a seat controller."""
        return C0AuthorSnapshot(
            tuple(
                (item.symbol, self._runtime.read_owner(item.owner.key).view)
                for item in self.program.owners
            ),
            self.author_object_instances(),
            self._runtime.occurrence_history(),
            self.form_control_history(),
            self.time if self.program.profile.temporal_policy is not None else None,
            self.author_actor_instances(),
        )

    def author_actor_instances(self) -> tuple[C0ActorInstanceView, ...]:
        """Trusted post-state audit, not permission to expose other Actor instances."""
        occurrences = {item.occurrence: item for item in self._runtime.occurrence_history()}
        products = {
            item.source_key
            if isinstance(item, C0ValueActionProgram)
            else item.ports.source_key: item.ir.actor_product.family
            for item in (
                *self.program._actions_by_name.values(),
                *(event for _, event in self.program.events),
                *(due for _, due in self.program.due_laws),
            )
            if item.ir.actor_product is not None
        }
        result = []
        for binding in self._runtime.actors():
            dynamic = self._dynamic_actor(binding.seat)
            template = dynamic[1]
            record = occurrences.get(binding.formed_by)
            if binding.formed_by is not None and (
                record is None or products.get(record.source) != binding.actor.family
            ):
                raise C0BindingError("formed Actor has no compatible published product source")
            view = self._runtime.read_actor(binding.actor)
            if view.owner != binding.owner or type(view.view) is not template.kind.state_type:
                raise C0BindingError("Actor audit differs from its checked nominal owner")
            result.append(
                C0ActorInstanceView(
                    binding.actor,
                    binding.owner,
                    binding.formed_by,
                    binding.born_at.ordinal,
                    binding.seat,
                    view.view,
                )
            )
        return tuple(result)

    def author_object_instances(self) -> tuple[C0ObjectInstanceView, ...]:
        """Trusted author audit; never used to construct a seat-local view or offer."""
        bindings = self._runtime.individuals()
        plan = self.program.object_plan
        if plan is None:
            if bindings:
                raise C0ObjectTraceError("K0 has individuals without a checked Object plan")
            return ()
        ports = {port.family: port for port in plan.ports}
        kinds = {kind.family: kind for kind in self.program.profile.dynamic_owner_kinds}
        forming_sources = {
            action.source_key: (K0OccurrenceFamily.ACTION, action.event_type, action.form.family)
            for _, action in self.program.actions
            if action.form is not None
        }
        forming_sources.update(
            {
                K0SourceSpecKey(event.ir.source_key): (
                    K0OccurrenceFamily.EVENT,
                    K0EventTypeKey(event.ir.event_type),
                    event.ir.object_product.family,
                )
                for _, event in self.program.events
                if event.ir.object_product is not None
            }
        )
        history = self._runtime.occurrence_history()
        occurrences = {record.occurrence: record for record in history}
        if len(occurrences) != len(history):
            raise C0ObjectTraceError("K0 history repeats an occurrence")
        seen_individuals: set[_K0IndividualRef] = set()
        seen_owners: set[K0OwnerKey] = set()
        result = []
        for item in bindings:
            if type(item) is not _K0IndividualBinding:
                raise C0ObjectTraceError("K0 individual binding is malformed")
            port = ports.get(item.individual.family)
            kind = kinds.get(item.individual.family)
            if (
                port is None
                or kind is None
                or kind.state_type.__name__ != port.state_record
                or item.individual in seen_individuals
                or item.owner in seen_owners
            ):
                raise C0ObjectTraceError("K0 individual lacks one checked Object sort and owner")
            seen_individuals.add(item.individual)
            seen_owners.add(item.owner)
            predecessor = None
            if item.formed_by is not None:
                # K0 owns birth identity; the checked source fixes Action/Event provenance.
                basis = occurrences.get(item.formed_by)
                if type(basis) is not _K0InMemoryOccurrence or forming_sources.get(
                    basis.source
                ) != (basis.family, basis.classification, item.individual.family):
                    raise C0ObjectTraceError("K0 individual has no selected forming source")
                if basis.family is K0OccurrenceFamily.EVENT:
                    formation = basis.formation_basis
                    if type(formation) is _K0CausalFormation:
                        predecessor, edge_key = formation.predecessor, formation.causal_law
                    elif type(formation) is _K0OrderedFormation:
                        predecessor, edge_key = formation.trigger, formation.law
                    else:
                        raise C0ObjectTraceError("forming Event has no checked causal formation")
                    trigger = occurrences.get(predecessor)
                    if trigger is None or not any(
                        event.ir.source_key == basis.source.value
                        and event.edge.causal_key == edge_key.value
                        and event.edge.predecessor.matches(trigger)
                        and type(basis.semantic_envelope) is event.occurrence_contract.envelope_type
                        and basis.semantic_envelope.trigger == predecessor
                        and basis.semantic_envelope.event == item.formed_by
                        for _, event in self.program.events
                    ):
                        raise C0ObjectTraceError("forming Event lacks its checked predecessor")
            try:
                current = self._runtime.read_individual(item.individual)
            except K0ProfileError as error:
                raise C0ObjectTraceError("K0 individual is not readable in this Session") from error
            if current.owner != item.owner or type(current.view) is not kind.state_type:
                raise C0ObjectTraceError("K0 individual owner state differs from its Object port")
            result.append(
                C0ObjectInstanceView(
                    port.sort,
                    item.individual,
                    item.owner,
                    item.formed_by,
                    current.view,
                    predecessor,
                )
            )
        return tuple(result)

    def formation_trace(self) -> tuple[C0FormedEventView, ...]:
        if self.program.formation_plan is None:
            raise C0BindingError("this Program has no checked Event formation projection")
        return project_formed_events(
            self.program.formation_plan,
            self._runtime.occurrence_history(),
            self._formation_scope,
        )

    def continue_form(self, seat: str) -> C0FormFrame:
        before = self.form_frame(seat)
        form = self.program.game_form
        if form is None:
            raise C0BindingError("seat has no selected event-jump GameForm")
        if before.finished:
            raise C0BindingError("GameForm has finished")
        if type(form) is _ActionValueForm:
            transition_limit = 1024
            for _ in range(transition_limit):
                opportunity = self._runtime.continue_action_value()
                # World termination is checked at every transition. A read model
                # is only projected at an actual return, never as an NPC guard.
                finished = (
                    form.end_at is not None and self.time >= form.end_at
                ) or self._world_outcome() is not None
                if isinstance(opportunity, _K0ActionValueDueBoundary):
                    if finished:
                        return self.form_frame(seat)
                    continue
                if (
                    finished
                    or opportunity is None
                    or self._controller(opportunity.seat)[0] == "human_prompt"
                ):
                    return self.form_frame(seat)
                proposal, attempt = self._prepare_appraisal(opportunity.seat)
                result = self._publish_appraisal(proposal, attempt)
                if not isinstance(result, K0Published):
                    raise C0BindingError("selected appraisal Action was rejected by K0")
                if (
                    form.end_at is not None and self.time >= form.end_at
                ) or self._world_outcome() is not None:
                    return self.form_frame(seat)
            raise C0ControlBudgetExceeded(transition_limit)
        if self._pending_seats:
            return before
        snapshots = {name: self._seat_projection(name) for name in form.seats}
        while self.time < form.end_at:
            boundary = min((tick for tick in form.wake_at if tick > self.time), default=form.end_at)
            previous = self.time
            self._runtime.advance(
                _K0TemporalAdvanceRequest(
                    _K0TemporalInterval(_K0FixedTime(previous), _K0FixedTime(boundary))
                )
            )
            if self.time <= previous:
                raise C0BindingError("K0 did not advance the selected GameForm")
            if self.time < form.end_at:
                self._pending_seats.update(
                    name
                    for name, previous_frame in snapshots.items()
                    if self._seat_projection(name) != previous_frame
                )
            current = self.form_frame(seat)
            if current.finished or self.time in form.wake_at or self._pending_seats:
                return current
        raise C0BindingError("GameForm failed to reach its declared end")
