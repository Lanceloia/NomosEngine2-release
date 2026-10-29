"""Atomic generated-rule sessions; executable rules arrive as compiled functions."""

from dataclasses import dataclass
from types import MappingProxyType
from uuid import uuid4
from weakref import WeakKeyDictionary

from . import actions, errors, information, records, scheduling, temporal
from .assurances import checked_constraints, checked_facts
from .carrying import ProposalKey
from .controllers import ActorControl, require_writer
from .entities import ReadContext
from .expressions import ExpressionError, ValueBindingError, ValueLimits
from .formation import FormationBatch, Individual
from .information import ContextKey, bind_contexts, initialize, visible_references
from .initialization import decode_opening
from .local_inputs import read_inputs, stage_inputs
from .opening import initialize as initialize_deals
from .processes import (
    ProcessStore,
    pending_record,
    prune_requests,
    request_binding,
    requests,
    transition,
)
from .randomness import RandomKey
from .settlement import settle_causality
from .terminals import CheckpointBasis, OpeningBasis, checkpoint, ending, gate, is_closed


@dataclass(frozen=True)
class SessionLimits:
    value: ValueLimits = ValueLimits()
    occurrences: int | None = None
    settlement_occurrences: int = 10000
    processes: int = 1000
    objects_per_type: int = 64
    actors_per_type: int = 64
    pending_due: int = 64
    same_time_actions: int = 1024

    def __post_init__(self):
        if (
            type(self.value) is not ValueLimits
            or self.occurrences is not None
            and (type(self.occurrences) is not int or self.occurrences < 1)
            or type(self.settlement_occurrences) is not int
            or self.settlement_occurrences < 1
            or type(self.processes) is not int
            or self.processes < 1
            or type(self.objects_per_type) is not int
            or self.objects_per_type < 1
            or type(self.actors_per_type) is not int
            or self.actors_per_type < 1
            or type(self.pending_due) is not int
            or self.pending_due < 1
            or type(self.same_time_actions) is not int
            or not 1 <= self.same_time_actions <= 1024
        ):
            raise ValueError("Session limits need positive capacities and value budgets")


class CompiledProgram:
    def __init__(
        self,
        name,
        schema_id,
        schemas,
        actors,
        actor_kinds,
        objects,
        validators,
        decoders,
        encoders,
        actions,
        reactions,
        channels,
        contexts,
        projections,
        information,
        reference_readers,
        terminal,
        relations,
        random_streams,
        settlements,
        time,
        play,
        cognition,
        *,
        opening=(),
        report_collections=(),
    ):
        self.name, self.schema_id = name, schema_id
        self.schemas = MappingProxyType({schema.name: schema for schema in schemas})
        self.actors, self.objects = actors, objects
        self.actor_kinds = actor_kinds
        self.random_streams = random_streams
        self.opening = opening
        self.time = time
        self.play = play
        self.cognition = cognition
        self.settlements = MappingProxyType({plan.trigger: plan for plan in settlements})
        self.reactions = MappingProxyType({reaction.source: reaction for reaction in reactions})
        self.validators, self.decoders = MappingProxyType(validators), MappingProxyType(decoders)
        self.encoders = MappingProxyType(encoders)
        self.actions = MappingProxyType({action.name: action for action in actions})
        self.processes = MappingProxyType(
            {
                name: MappingProxyType(
                    {a.process.point: a for a in actions if a.process and a.process.process == name}
                )
                for name in {a.process.process for a in actions if a.process}
            }
        )
        self.terminal = terminal
        self.relations = MappingProxyType({plan.name: plan for plan in relations})
        self.channels = MappingProxyType(dict(channels))
        self.report_collections = MappingProxyType(
            {name: (kind, frozenset(channels)) for name, kind, channels in report_collections}
        )
        self.contexts = contexts
        self.context_definitions = MappingProxyType({plan.name: plan for plan in contexts})
        self.projections = MappingProxyType({plan.name: plan for plan in projections})
        self.information = MappingProxyType({plan.name: plan for plan in information})
        self.reference_readers = MappingProxyType(reference_readers)
        self.subscriptions = MappingProxyType(
            {
                source: tuple(reaction for reaction in reactions if source in reaction.triggers)
                for source in {trigger for reaction in reactions for trigger in reaction.triggers}
            }
        )

    def start(self, assets, *, limits=SessionLimits(), controllers=None):
        return Session(self, assets, limits, controllers)


class Session:
    """Trusted local seat control, matching the current manual author Session boundary."""

    def __init__(self, program, assets, limits, controllers):
        from .candidates import ControllerLibrary

        if controllers is not None and (
            type(controllers) is not ControllerLibrary or controllers.program is not program
        ):
            raise ValueError("Start requires controllers bound to the exact generated Program")
        self.controllers = controllers
        self._strategy_handles = WeakKeyDictionary()
        self._candidate_frames = WeakKeyDictionary()
        self._acquired_reference_batch = None
        self._report_input_batch = None
        self._local_calculation = None
        self._subject_actors = MappingProxyType({})
        if type(limits) is not SessionLimits:
            raise ValueError("Start requires SessionLimits")
        scope, symbols, references, states, initial_records = decode_opening(
            program, assets, limits
        )
        self.program, self.limits, self.references = program, limits, references
        self._scope = scope
        self.symbols = tuple(symbols.items())
        self._individuals = tuple(Individual(ref, None) for ref in symbols.values())
        self._states = MappingProxyType(states)
        self._history, self._receipts = (), ()
        self._controller_parameters = (
            MappingProxyType({}) if controllers is None else controllers.materialize(self)
        )
        self._preparations, self._busy, self._fatal = WeakKeyDictionary(), False, False
        self._opening_receipts = ()
        self._initial_fields = initial_records
        self._local_inputs = MappingProxyType({})
        self._processes, self._terminal, self._requests = ProcessStore(), None, {}
        self._control_handles, self._control_by_ref = {}, {}
        self._activity_handles = WeakKeyDictionary()
        self._schedule_handles = WeakKeyDictionary()
        self._advances, self._cancellations = (), ()
        bind_contexts(self)
        initialize_deals(self)
        self._time, self._pending_due = temporal.opening(self, assets)
        self._scheduling = scheduling.opening(self, assets)
        initialize(self)
        from .cognition import checkpoint as cognition_checkpoint

        self._minds = cognition_checkpoint(self, self._states, (), OpeningBasis(scope), {})
        self._terminal = checkpoint(
            self, self._states, self._processes, OpeningBasis(scope), prior=None
        )
        if is_closed(self._terminal):
            self._pending_due = ()
        self._local_inputs = stage_inputs(
            self, self._opening_receipts, self._terminal, opening=True
        )
        self._subject_opening = (self._history, self._advances, self._scheduling, self._time)

    def inspect_opening(self):
        """Trusted initialization audit; never an Actor-local disclosure."""
        return self._opening_deals

    def inspect_initials(self):
        """Trusted declared-default audit; does not grant Actor-local information."""
        return self._initial_fields

    def context(
        self,
        states,
        mode="world",
        controller=None,
        *,
        receipts=None,
        local_values=None,
        cache_inputs=False,
    ):
        if mode == "actor":
            if controller is None:
                raise errors.AdmissionError(
                    "WrongController", "Actor context requires its controller"
                )
            references = visible_references(
                self,
                states,
                controller,
                self._receipts if receipts is None else receipts,
                acquired=self._acquired_reference_batch,
            )
        else:
            references = self.references.at(states)
        return ReadContext(
            self.program.schema_id,
            references,
            states,
            mode,
            self.program.reference_readers,
            controller,
            local_values,
            {} if cache_inputs else None,
            self._report_input_batch.input_proofs
            if cache_inputs and self._report_input_batch is not None
            else None,
        )

    def context_values(self, name, states, *, local=False):
        definition = self.program.context_definitions[name]
        values = {
            key: value
            for key, value in self._contexts[name].items()
            if not local or key not in definition.world_parameters
        }
        if definition.fields:
            values.update(
                (key, value)
                for key, value in states[ContextKey(name)].items()
                if not local or key in definition.public
            )
        return values

    def _actor(self, actor):
        if type(actor) is str and actor in dict(self.program.actors):
            return dict(self.symbols)[actor]
        selected = self._control_handles.get(actor) if type(actor) is ActorControl else None
        if selected is not None:
            reference, label = selected
            if actor.label == label and reference in self.references.references:
                return reference
        raise errors.AdmissionError(
            "WrongController", "unknown or modified Session Actor controller"
        )

    def _controller(self, reference):
        if (
            reference not in self.references.references
            or self.program.schemas[reference.sort].kind != "person"
        ):
            raise errors.AdmissionError("WrongController", "foreign or nonexistent Actor")
        opening = next((name for name, ref in self.symbols if ref == reference), None)
        if opening is not None:
            return opening
        if reference not in self._control_by_ref:
            label = "Actor [" + uuid4().hex[:12] + "]"
            handle = ActorControl(label)
            self._control_handles[handle] = (reference, label)
            self._control_by_ref[reference] = handle
        return self._control_by_ref[reference]

    def actor_controllers(self):
        """Trusted control inventory; this does not deliver Actor identities to a player."""
        return tuple(
            self._controller(individual.reference)
            for individual in self._individuals
            if self.program.schemas[individual.reference.sort].kind == "person"
        )

    def actor_reference(self, actor):
        return self._actor(actor)

    def controller_parameter(self, actor, name, default):
        """Read an immutable pre-Start policy override without exposing world state."""
        opening = next((symbol for symbol, ref in self.symbols if ref == actor), None)
        if opening is None:
            return default
        return self._controller_parameters.get(opening, {}).get(name, default)

    def bind_subject(self, actor, subject, *, goals, limits=None, planning=None):
        from .participation import ParticipationLimits, bind_subject

        return bind_subject(
            self,
            actor,
            subject,
            goals=goals,
            limits=ParticipationLimits() if limits is None else limits,
            planning=planning,
        )

    def planning_problem(self, actor, definition, goal, *, limits=None, capture_budget=4096):
        from .planning import planning_problem

        return planning_problem(
            self, actor, definition, goal, limits=limits, capture_budget=capture_budget
        )

    def planning_continuation(self, actor, definition, goal, *, limits=None, capture_budget=4096):
        from .planning_continuation import PlanningContinuation

        return PlanningContinuation(
            self,
            actor,
            definition,
            goal,
            limits=limits,
            capture_budget=capture_budget,
        )

    def _entry(self, actor, ability, binding):
        reference = self._actor(actor)
        definition = self.program.actions.get(ability) if type(ability) is str else None
        if definition is None or not self.references.accepts(definition.actor_sort, reference.sort):
            raise errors.AdmissionError(
                "WrongController", "ability is not bound to this Actor sort"
            )
        gate(self._terminal, binding)
        record = pending_record(self, definition, reference, binding)
        return definition, reference, record

    def _admit(self, actor, ability, choices, binding):
        definition, reference, record = self._entry(actor, ability, binding)
        admission = definition.admit(self, reference, choices, record)
        return definition, reference, admission.participants, record, admission.epoch

    def choice_form(self, actor, ability, choices=None, *, request=None):
        from .choices import choice_form

        return choice_form(self, actor, ability, choices, request)

    def values(self, actor=None):
        from .values import ValueCodec

        return ValueCodec(self, actor)

    def wire(self, actor, *, reference=None, resolve_reference=None):
        """Consume typed wire inputs through the same current native authority."""
        from .wire_actions import WireActions

        return WireActions(self, actor, reference=reference, resolve_reference=resolve_reference)

    def available_abilities(self, actor):
        from .choices import available_abilities

        return available_abilities(self, actor)

    def propose(self, actor, *, budget=4096, actions=None):
        from .strategies import propose

        return propose(self, actor, budget, actions)

    def proposal_score_frame(self, actor, *, budget=4096, actions=None):
        """Trusted read-only score audit for one direct-policy opportunity."""
        from .strategies import score_frame

        return score_frame(self, actor, budget, actions)

    def candidate_frame(self, actor, *, budget=4096, actions=None, exhaustive=False):
        from .decisions import candidate_frame

        return candidate_frame(self, actor, budget=budget, actions=actions, exhaustive=exhaustive)

    def candidate_details(self, actor, frame, key):
        from .decisions import candidate_details

        return candidate_details(self, actor, frame, key)

    def candidate_frame_details(self, actor, frame):
        from .decisions import candidate_frame_details

        return candidate_frame_details(self, actor, frame)

    def submit_candidate(self, actor, frame, key):
        from .decisions import submit_candidate

        return submit_candidate(self, actor, frame, key)

    def drive_play(self, *, budget=64):
        from .play import drive_play

        return drive_play(self, budget)

    def table_control(self, player, *, record_decisions=False):
        from .play import TableControl

        return TableControl(self, player, record_decisions=record_decisions)

    def proposal_details(self, actor, proposal):
        from .strategies import issued

        _, ability, score, parts, choices, _, _, explanations, prediction, priority = issued(
            self, actor, proposal
        )
        return {
            "ability": ability,
            "score": score,
            "priority": priority,
            "parts": [{"label": label, "value": value} for label, value in parts],
            "inputs": dict(choices),
            "explanations": [
                {"category": category, "label": label, "type": type_name, "value": value}
                for category, label, type_name, value in explanations
            ],
            "prediction": prediction,
        }

    def submit_proposal(self, actor, proposal):
        from .strategies import issued

        if self._busy or self._fatal:
            raise errors.SettlementDefect("Session cannot submit during settlement or after fatal")
        _, ability, _, _, choices, binding, epoch, *_ = issued(self, actor, proposal)
        del self._strategy_handles[proposal]
        return self._submit_selected(actor, ability, dict(choices), binding, epoch)

    def prepare(self, actor, ability, choices, *, request=None):
        if self._busy or self._fatal:
            raise errors.SettlementDefect(
                "Session cannot prepare during settlement or after a fatal defect"
            )
        require_writer(self, self._actor(actor))
        if self._terminal is not None and self._terminal.closed is not None:
            gate(self._terminal, None)
        binding = None if request is None else request_binding(self, actor, request)
        _, controller, _, _, epoch = self._admit(actor, ability, choices, binding)
        prepared = actions.PreparedAction(actor, ability)
        self._preparations[prepared] = (controller, ability, dict(choices), binding, epoch)
        return prepared

    def submit(self, actor, ability, prepared):
        if self._busy or self._fatal:
            raise errors.SettlementDefect(
                "Session cannot submit during settlement or after a fatal defect"
            )
        controller = self._actor(actor)
        selected = (
            self._preparations.get(prepared) if type(prepared) is actions.PreparedAction else None
        )
        if (
            type(prepared) is not actions.PreparedAction
            or prepared.actor != actor
            or prepared.ability != ability
            or selected is None
            or selected[:2] != (controller, ability)
        ):
            raise errors.AdmissionError("WrongController", "unknown or consumed prepared action")
        _, _, choices, binding, prepared_epoch = self._preparations.pop(prepared)
        return self._submit_selected(actor, ability, choices, binding, prepared_epoch)

    def _submit_selected(
        self, actor, ability, choices, binding, prepared_epoch, *, selection=None, authority=None
    ):
        controller = self._actor(actor)
        require_writer(self, controller, authority)
        if not scheduling.has_opportunity(self, controller):
            return actions.ActionResult("rejected", code="NotAdmitted")
        try:
            definition, reference, environment, record, epoch = self._admit(
                actor, ability, choices, binding
            )
            if epoch != prepared_epoch:
                raise errors.AdmissionError("StaleEpoch", "request epoch is no longer current")
        except (errors.AdmissionError, ValueBindingError, ExpressionError) as error:
            code = error.code if type(error) is errors.AdmissionError else error.diagnostic.code
            return actions.ActionResult("rejected", code=code)
        return self._commit_action(
            definition,
            reference,
            environment,
            record,
            (),
            epoch,
            selection=selection,
            authority=authority,
        )

    def _commit_action(
        self,
        definition,
        reference,
        environment,
        record,
        cancelled,
        epoch,
        *,
        selection=None,
        authority=None,
    ):
        require_writer(self, reference, authority)
        try:
            charge = scheduling.charge(self, definition, reference, environment, record)
        except (errors.AdmissionError, ValueBindingError, ExpressionError) as error:
            code = error.code if type(error) is errors.AdmissionError else error.diagnostic.code
            return actions.ActionResult("rejected", code=code)
        self._busy = True
        try:
            allocation = FormationBatch(self.references, self.limits, self._scope)
            try:
                draft = definition.execute(
                    self,
                    self._states,
                    reference,
                    environment,
                    self._receipts,
                    record,
                    len(self._history) + 1,
                    allocation,
                )
            except errors.ControlRejection as error:
                return actions.ActionResult("rejected", code=error.code)
            states, occurrences, receipts, processes, terminal, pending = self._settle(
                definition,
                reference,
                environment,
                record,
                draft,
                allocation,
                cancelled,
                charge,
                epoch,
            )
            schedule_state, advances = scheduling.after_action(
                self,
                charge,
                states,
                reference,
                occurrences[0].reference,
                occurrences[-1].reference,
                cancelled,
                terminal,
            )
            references = self.references.at(states)
            individuals = self._individuals + tuple(allocation.products)
            from .cognition import checkpoint as cognition_checkpoint

            minds = cognition_checkpoint(
                self,
                states,
                self._receipts + receipts,
                CheckpointBasis(self._scope, occurrences[0].reference, occurrences[-1].reference),
                self._minds,
            )
            choice = None
            if selection is not None:
                from .decisions import PublishedChoice

                choice = (
                    reference,
                    PublishedChoice(
                        definition.source,
                        occurrences[0].reference,
                        definition.name,
                        selection.inputs,
                        epoch,
                        selection.semantics,
                        selection.profile,
                        selection.correlation,
                        selection.input_terms,
                        selection.capture,
                    ),
                )
            local_inputs = stage_inputs(self, receipts, terminal, choice=choice)
        except Exception as error:
            self._fatal = True
            raise errors.SettlementDefect("generated root rolled back; Session is fatal") from error
        finally:
            self._busy = False
        self._states, self._history, self._receipts = (
            states,
            self._history + occurrences,
            self._receipts + receipts,
        )
        self._processes, self._terminal = processes, terminal
        self.references, self._individuals = references, individuals
        self._pending_due = pending
        self._minds = minds
        self._local_inputs = local_inputs
        self._scheduling = schedule_state
        self._advances += advances
        self._cancellations += tuple(
            temporal.CancellationRecord(key, occurrences[0].reference, self._time)
            for key in cancelled
        )
        prune_requests(self)
        return actions.ActionResult(
            "published",
            occurrences[0].result,
            tuple(
                (receipt.channel, receipt.value)
                for receipt in receipts
                if receipt.recipient == reference
            ),
        )

    def act(self, actor, ability, choices, *, request=None):
        return self.submit(actor, ability, self.prepare(actor, ability, choices, request=request))

    def _settle(
        self,
        definition,
        controller,
        environment,
        record,
        draft,
        allocation,
        cancelled,
        charge,
        epoch,
    ):
        before = self._states
        draft.materialize()
        pending, scheduled = temporal.schedule(self, draft, cancelled)
        binding = None if record is None else record.binding()
        supports = () if record is None else record.supports
        if record is not None and definition.process.window is not None:
            supports = (*supports, *dict(record.origins).get(record.point, ()))
        if self._terminal is not None and type(self._terminal.trigger) is CheckpointBasis:
            trigger = self._terminal.trigger
            supports = tuple(dict.fromkeys((*supports, trigger.root, trigger.tip)))
        root = records.Occurrence(
            len(self._history) + 1,
            "Action",
            definition.source,
            tuple(environment.items()),
            draft.result,
            None,
            binding,
            tuple(dict.fromkeys((*supports, *draft.supports))),
            draft.next_point,
            draft.advanced,
            tuple(draft.formed),
            tuple(draft.random.draws),
            at=self._time,
            scheduled=scheduled,
            cancelled=cancelled,
            time_cost=None if charge is None else charge.cost,
            epoch=epoch,
        )
        processes = transition(
            self, definition, record, controller, environment, draft, root.reference
        )
        states = draft.after()
        states, rows, receipts = settle_causality(
            self,
            root,
            states,
            information.deliver(self, draft, root, before, states),
            allocation,
            offset=len(self._history),
            receipt_prefix=self._receipts,
        )
        basis = CheckpointBasis(controller.scope, root.reference, rows[-1].reference)
        terminal = checkpoint(self, states, processes, basis, prior=self._terminal)
        return states, rows, receipts, processes, terminal, () if is_closed(terminal) else pending

    def read_time(self):
        return self._time

    def cognition_value(self, controller, name):
        from .cognition import current

        return current(self, controller, name).view

    def cognition(self, actor):
        from .cognition import current

        slot = current(self, self._actor(actor))
        return {
            "binding": slot.name,
            "revision": slot.state.revision,
            "view": slot.view,
            "basis": slot.basis,
            "grounds": tuple(dict.fromkeys(frame.ground for frame in slot.state.frames)),
        }

    def inspect_cognition(self, actor):
        """Trusted immutable audit of one controlled Actor's complete revision state."""
        from .cognition import current

        return current(self, self._actor(actor))

    def explain_cognition(self, actor, *, encode=None):
        """Read committed personal grounds through the caller's nominal display encoder."""
        from .cognition import explanation

        return explanation(self, actor, encode)

    def next_opportunity(self):
        return scheduling.next_opportunity(self)

    def defer_opportunity(self, actor, offer):
        return scheduling.defer_opportunity(self, actor, offer)

    def action_value_state(self):
        """Trusted immutable debt inventory, not Actor knowledge."""
        return () if self._scheduling is None else self._scheduling.debts

    def action_value_history(self):
        return () if self._scheduling is None else self._scheduling.history

    def advance(self, to=None):
        return temporal.advance(self, to)

    def activity_offers(self, actor):
        return temporal.activity_offers(self, actor)

    def cancel_activity(self, actor, offer):
        return temporal.cancel_activity(self, actor, offer)

    def inspect_pending(self):
        """Trusted due inventory; Actor control uses activity_offers()."""
        return self._pending_due

    def temporal_history(self):
        return self._advances

    def due_cancellation_history(self):
        return self._cancellations

    def requests(self, actor):
        return requests(self, actor)

    def reply(self, actor, request, choices):
        if self._terminal is not None and self._terminal.closed is not None:
            gate(self._terminal, None)
        binding = request_binding(self, actor, request)
        ability = self.program.processes[binding.process][binding.point].name
        return self.act(actor, ability, choices, request=request)

    def decision_reports(self, actor, request):
        binding = request_binding(self, actor, request)
        definition = self.program.processes[binding.process][binding.point]
        controller = self._actor(actor)
        record = pending_record(self, definition, controller, binding)
        if definition.local_views is None:
            return {}
        readers = definition.local_views(self, self._states, controller, self._receipts, record)
        return {alias: reader() for alias, reader in readers.items()}

    def ending(self, actor):
        return ending(self, actor)

    def inspect_processes(self):
        """Trusted immutable transcripts, not another Actor's decision or private report view."""
        return tuple(self._processes.records)

    def inspect_terminal(self):
        """Trusted frozen closure evidence; Actor results use ending()."""
        return self._terminal

    def read(self, actor):
        reference = self._actor(actor)
        schema = self.program.schemas[reference.sort]
        return {
            field: value for field, value in self._states[reference].items() if field in schema.view
        }

    def reports(self, actor, channel):
        reference = self._actor(actor)
        if type(channel) is not str or channel not in self.program.channels:
            raise errors.AdmissionError("UnknownInformation", "report channel is not selected")
        values = [
            receipt.value
            for receipt in self._receipts
            if receipt.recipient == reference and receipt.channel == channel
        ]
        return {"acquired": bool(values), "values": values}

    def report_collection(self, actor, name):
        """Read only the actor's committed receipts, in their original acquisition order."""
        reference = self._actor(actor)
        if type(name) is not str or name not in self.program.report_collections:
            raise errors.AdmissionError("UnknownInformation", "report collection is not selected")
        _, channels = self.program.report_collections[name]
        values = [
            receipt.value
            for receipt in self._receipts
            if receipt.recipient == reference and receipt.channel in channels
        ]
        return {"acquired": bool(values), "values": values}

    def local_inputs(self, actor, *, after=None, limit=128):
        """Read committed inputs with stable, Session/Actor-scoped incremental cursors."""
        return read_inputs(self, actor, after=after, limit=limit)

    def feedback_memory(self, actor, memory, *, budget=None, checkpoint=None):
        """Interpret only this Actor's committed inputs; publish no world or subject state."""
        from .feedback import feedback_memory

        return feedback_memory(self, actor, memory, budget=budget, checkpoint=checkpoint)

    def checked_facts(self, actor, channel):
        return checked_facts(self, actor, channel)

    def checked_constraints(self, actor, channel):
        return checked_constraints(self, actor, channel)

    def project(self, actor, name):
        reference = self._actor(actor)
        definition = self.program.projections.get(name) if type(name) is str else None
        if definition is None:
            raise errors.AdmissionError("UnknownProjection", "projection is not selected")
        try:
            available, value = self.project_value(definition, self._states, reference)
        except (ExpressionError, ValueBindingError):
            raise errors.AdmissionError(
                "ProjectionFailed", "projection could not be read"
            ) from None
        return {"available": True, "value": value} if available else {"available": False}

    def project_value(self, definition, states, viewer):
        if not self.references.accepts(definition.viewer_sort, viewer.sort):
            raise errors.AdmissionError(
                "WrongController", "projection viewer has an incompatible sort"
            )
        return definition.evaluate(self, states, viewer)

    def report(self, actor, name):
        reference = self._actor(actor)
        if type(name) is not str or name not in self.program.information:
            raise errors.AdmissionError("UnknownInformation", "opening report is not selected")
        values = [
            receipt.value
            for receipt in self._opening_receipts
            if receipt.recipient == reference and receipt.channel == name
        ]
        return {"acquired": True, "value": values[0]} if values else {"acquired": False}

    def projected_value(self, viewer, channel, states):
        definition = self.program.projections[channel]
        available, value = self.project_value(definition, states, viewer)
        if not available:
            raise errors.AdmissionError(
                "InputDomainUnavailable", "projection is currently unavailable"
            )
        return value

    def known(self, actor, sort):
        if type(sort) is not str or sort not in self.program.schemas:
            raise errors.AdmissionError("UnknownType", "entity sort is not selected")
        return self.context(self._states, "actor", self._actor(actor)).references.known(sort)

    def opening_acquisitions(self):
        """Trusted audit of opening delivery, separate from world occurrences."""
        return self._opening_receipts

    def read_context(self, actor, name):
        self._actor(actor)
        definition = self.program.context_definitions.get(name) if type(name) is str else None
        if definition is None or not definition.fields:
            raise errors.AdmissionError("UnknownContext", "shared storage is not selected")
        state = self._states[ContextKey(name)]
        return {key: state[key] for key in definition.public}

    def inspect_contexts(self):
        """Detached trusted diagnostic; player reads use read_context or project."""
        return {
            plan.name: dict(self._states[ContextKey(plan.name)])
            for plan in self.program.contexts
            if plan.fields
        }

    def inspect_random(self):
        """Trusted stream audit; seeds and counters are not Actor-visible fields."""
        return {
            name: self._states[RandomKey(name)]["state"] for name in self.program.random_streams
        }

    def history(self):
        """Trusted audit, not an Actor-visible timeline."""
        return self._history

    def acquisitions(self):
        return self._receipts

    def inspect_state(self):
        """Detached trusted diagnostic; player reads use read/reports instead."""
        return {name: dict(self._states[ref]) for name, ref in self.symbols}

    def inspect_snapshot(self):
        """Compose common trusted diagnostics; this is not a save or an Actor view."""
        return {
            "state": self.inspect_state(),
            "contexts": self.inspect_contexts(),
            "acquisitions": self.acquisitions(),
            "opening": self.opening_acquisitions(),
            "history": self.history(),
            "terminal": self.inspect_terminal(),
            "processes": self.inspect_processes(),
            "pending": self.inspect_pending(),
            "individuals": self.inspect_individuals(),
            "random": self.inspect_random(),
        }

    def inspect_relations(self):
        """Trusted current proposals, never an Actor-visible projection."""
        return {
            (key.relation, key.item): state["offer"]
            for key, state in self._states.items()
            if type(key) is ProposalKey
        }

    def inspect_individuals(self):
        """Trusted identity/producer audit; formation alone grants no Actor knowledge."""
        return self._individuals

    def inspect_individual(self, reference):
        """Trusted state diagnostic for an opening or formed local individual."""
        self.references.require(reference, reference.sort)
        return dict(self._states[reference])
