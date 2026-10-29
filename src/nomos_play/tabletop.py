"""Shared browser controls over a generated Program, display and table controller."""

import secrets
from copy import deepcopy
from types import MappingProxyType

from nomos_runtime.candidates import selected_strategy
from nomos_runtime.errors import AdmissionError
from nomos_runtime.expressions import ValueBindingError
from nomos_runtime.presentation import CompiledDisplay, data
from nomos_runtime.world import CompiledProgram

from .errors import TableError
from .inputs import caption, construct, describe
from .timeline import VisibleTimeline


class TableGame:
    def __init__(self, program, assets, presentation, controllers, player, *, subject_group=None):
        if (
            type(program) is not CompiledProgram
            or type(presentation) is not CompiledDisplay
            or presentation.program is not program
        ):
            raise TableError("WrongPresentation")
        if program.play is None or program.play.mechanism != "tabletop":
            raise TableError("NoTabletopMechanism")
        if type(player) is not str or player not in program.play.seats:
            raise TableError("UnknownSeat")
        self.session = program.start(assets, controllers=controllers)
        self.subject_group = subject_group
        self.participations = MappingProxyType({})
        self.experience_round = None
        if (
            self.subject_group is None
            and controllers is not None
            and any(s.participation is not None for s in controllers.strategies)
        ):
            from nomos_runtime.experience_play import SubjectGroup

            self.subject_group = SubjectGroup()
        if self.subject_group is not None:
            self.participations = MappingProxyType(
                dict(self.subject_group.bind(self.session, player=player))
            )
            self.experience_round = self.subject_group.rounds + 1
        try:
            self.control = self.session.table_control(
                player, record_decisions=presentation.specification.get("cognition_recap", False)
            )
            self.display = presentation.open(self.session, player)
            self.player, self.presentation = player, presentation
            self.status, self.code = "ready", None
            self.revision = secrets.token_urlsafe(18)
            self._tickets, self._confirmed_choices = {}, []
            self.timeline = VisibleTimeline(self)
            self.drive()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.subject_group is not None and self.subject_group.session is self.session:
            self.subject_group.interrupt()

    def _changed(self):
        self._tickets.clear()
        self.revision = secrets.token_urlsafe(18)

    def _published(self, actor, outcome):
        self._changed()
        self.timeline.capture()

    def _run(self, operation):
        try:
            with self.control.observe(self._published):
                result = operation()
        except AdmissionError as error:
            raise TableError(error.code) from error
        self.status, self.code = result.status, result.code
        if (
            result.status == "closed"
            and self.subject_group is not None
            and self.subject_group.session is self.session
        ):
            self.subject_group.finish()
        return result

    def drive(self, budget=64):
        self.timeline.capture()
        return self._run(lambda: self.control.drive(budget=budget))

    def coordinate(self, revision):
        if revision != self.revision or self.status not in ("ready", "waiting"):
            raise TableError("StaleCoordination")
        try:
            offer = self.control.coordination_offer()
        except AdmissionError as error:
            raise TableError(error.code) from error
        if offer is None:
            raise TableError("StaleCoordination")
        self.timeline.begin()
        self._run(lambda: self.control.coordinate(offer))
        self._changed()
        return self.view()

    def continue_play(self, revision):
        paused = self.control.joint.has_paused()
        if revision != self.revision or (
            self.status != "budget" and not (paused and self.status in ("ready", "waiting"))
        ):
            raise TableError("StaleContinuation")
        self.timeline.begin()
        if paused:
            self._run(self.control.resume_coordination)
        else:
            self.drive()
        self._changed()
        return self.view()

    def _entry(self, ticket, revision):
        if type(revision) is not str or revision != self.revision:
            raise TableError("StaleChoice")
        if type(ticket) is not str or ticket not in self._tickets or self.status != "ready":
            raise TableError("UnknownChoice")
        return self._tickets[ticket]

    def _construct(self, ticket, revision, selections, *, tolerant=False):
        ability, request = self._entry(ticket, revision)
        try:
            return construct(self.display, ability, selections, request, tolerant=tolerant)
        except (AdmissionError, ValueBindingError) as error:
            raise TableError(
                error.code if isinstance(error, AdmissionError) else error.diagnostic.code
            ) from error

    def draft(self, ticket, revision, selections):
        built = self._construct(ticket, revision, selections, tolerant=True)
        return {"fields": built.fields, "complete": built.complete, "preview": built.previews}

    def submit(self, ticket, revision, selections):
        ability, request = self._entry(ticket, revision)
        built = self._construct(ticket, revision, selections)
        if not built.complete:
            raise TableError("IncompleteInputs")
        metadata = self.presentation.actions[ability]
        labels = self.presentation.specification["labels"]
        chosen = []
        for item in metadata.inputs:
            shown = self.display.encode(item.type_name, built.choices[item.name])
            spec = data(item.specification)
            chosen.append(
                {
                    "label": spec["label"],
                    "value": caption(spec, shown)
                    or describe(shown, labels, self.display.format(item.type_name)),
                }
            )
        decision = {
            "action": metadata.specification["title"],
            "source": self.session.program.actions[ability].source,
            "inputs": chosen,
            "context": deepcopy(
                [
                    {key: panel[key] for key in ("title", "data", "format")}
                    for panel in self.timeline.state["panels"]
                    if panel["zone"] == "board"
                    and not panel["fold"]
                    and (
                        panel["format"]["kind"]
                        in (
                            "scalar",
                            "number",
                            "enum",
                            "boolean",
                            "indicator",
                            "reference",
                            "badge",
                        )
                        or panel["format"]["kind"] == "collection"
                        and (
                            panel["format"]["element"]["kind"] == "reference"
                            or panel["format"]["element"]["kind"] == "badge"
                            and panel["format"]["element"].get("reference")
                        )
                    )
                ]
            ),
        }
        try:
            prepared = self.session.prepare(self.player, ability, built.choices, request=request)
            outcome = self.session.submit(self.player, ability, prepared)
        except AdmissionError as error:
            raise TableError(error.code) from error
        if outcome.status != "published":
            raise TableError(outcome.code or "NotAdmitted")
        self._confirmed_choices.append(decision)
        self._changed()
        self.timeline.begin()
        self.timeline.submitted(decision)
        self.timeline.capture()
        self.drive()
        return self.view()

    def advice(self, revision):
        if revision != self.revision or self.status != "ready":
            raise TableError("StaleChoice")
        window = self.control.joint.for_actor(self.player)
        policy = selected_strategy(self.session, self.player)
        if policy is not None and policy.semantics is not None:
            from .experience_audit import advice

            status, described = advice(self, None if window is None else window.plan.actions)
            result = {"revision": revision, "status": status}
            if described is None:
                return result
        else:
            decision = self.session.propose(
                self.player, actions=None if window is None else window.plan.actions
            )
            result = {"revision": revision, "status": decision.status}
            if decision.proposal is None:
                return result
            described = self.session.proposal_details(self.player, decision.proposal)
        metadata = self.presentation.actions[described["ability"]]
        fields = []
        for item in metadata.inputs:
            if item.name not in described["inputs"]:
                continue
            shown = self.display.encode(item.type_name, described["inputs"][item.name])
            spec = data(item.specification)
            text = caption(spec, shown)
            fields.append(
                {
                    "label": spec["label"],
                    "data": text if text is not None else shown,
                    "format": {"kind": "scalar"}
                    if text is not None
                    else self.display.format(item.type_name),
                }
            )
        result.update(
            action=metadata.specification["title"],
            score=described["score"],
            parts=described["parts"],
            inputs=fields,
            explanations=[
                {
                    "category": item["category"],
                    "label": item["label"],
                    "data": self.display.encode(item["type"], item["value"]),
                    "format": self.display.format(item["type"]),
                }
                for item in described["explanations"]
            ],
        )
        return result

    def cognition_audit_actors(self):
        if not self.presentation.specification.get("cognition_recap", False):
            return []
        if self.session.ending(self.player)["status"] != "closed":
            return []
        from nomos_runtime.cognition import selected

        labels = self.presentation.specification["labels"]
        participants = self.participations
        return [
            {
                "actor": actor,
                "label": labels.get(actor, actor.upper()),
                "self": actor == self.player,
            }
            for actor in self.session.program.play.seats
            if actor in participants
            or selected(self.session, self.session.actor_reference(actor)) is not None
        ]

    def cognition_audit(self, actor, offset):
        if type(actor) is not str or actor not in {
            item["actor"] for item in self.cognition_audit_actors()
        }:
            raise TableError("CognitionAuditUnavailable")
        if type(offset) is not int or offset < 0:
            raise TableError("InvalidAuditPage")
        if actor in self.participations:
            from .experience_audit import page

            return page(self, actor, offset)
        from .mental_audit import page

        return page(self, actor, offset)

    def snapshot(self):
        result = self.display.snapshot()
        labels = self.presentation.specification["labels"]
        for panel in result["panels"]:
            panel["value"] = describe(panel["data"], labels, panel["format"])
        return result

    def view(self):
        shown = self.snapshot()
        actions = []
        if self.status == "ready":
            entries = [(name, None) for name in self.session.available_abilities(self.player)]
            entries += [
                (f"{request.process}.{request.point}", request)
                for request in self.session.requests(self.player)
            ]
            for ability, request in entries:
                ticket = next(
                    (key for key, entry in self._tickets.items() if entry == (ability, request)),
                    None,
                )
                if ticket is None:
                    ticket = secrets.token_urlsafe(18)
                    self._tickets[ticket] = ability, request
                metadata = self.presentation.actions[ability]
                action = {**data(metadata.specification), "id": ticket, "key": ability}
                action["immediate"] = not metadata.inputs
                target = action.pop("target")
                if target:
                    action["target"] = next(
                        field
                        for field in self._construct(ticket, self.revision, {}).fields
                        if field["name"] == target
                    )
                    if action["surface"] == "seats":
                        refs = {person["reference"] for person in shown["seats"]}
                        if any(
                            option["data"]["reference"] not in refs
                            for option in action["target"]["options"]
                        ):
                            raise TableError("NonSeatTarget")
                if action["surface"] == "buttons":
                    built = self._construct(ticket, self.revision, {})
                    action["direct"] = built.fields[0]
                    action["preview"] = built.previews
                actions.append(action)
        ending = shown["ending"]
        end_data = ending["value"] if ending["available"] else None
        end_value = (
            describe(
                end_data,
                shown["labels"],
                self.display.format(self.session.program.terminal.result_type),
            )
            if ending["available"]
            else None
        )
        end_report = None
        if ending["status"] == "closed":
            end_report = {
                "result": end_value,
                "terminal": self.session.program.terminal.name,
                "closure": "engine_confirmed",
                "history": [panel for panel in shown["panels"] if panel["zone"] == "history"],
                "player_choices": deepcopy(self._confirmed_choices),
                "cognition_audit": self.cognition_audit_actors(),
            }
        coordination = (
            self.control.coordination_state() if self.status in ("ready", "waiting") else None
        )
        return {
            **shown,
            "schema": "nomos.tabletop.player-view",
            "seat": shown["labels"].get(self.player, self.player.upper()),
            "revision": self.revision,
            "status": self.status,
            "code": self.code,
            "coordination": coordination,
            "actions": actions,
            "strategy_available": self.status == "ready"
            and selected_strategy(self.session, self.player) is not None,
            "events": deepcopy(self.timeline.events),
            "recent_events": deepcopy(self.timeline.recent),
            "playback": self.timeline.playback(),
            "ending": end_value,
            "end_report": end_report,
            "end_data": end_data,
            "end_format": None
            if not ending["available"]
            else self.display.format(self.session.program.terminal.result_type),
            "experience": None
            if self.subject_group is None
            else {
                "visits": self.experience_round - (self.status != "closed"),
                "players": len(self.subject_group.subjects),
                "active_players": len(self.participations),
            },
            "computation": {
                "computer_actions": len(self.control.timings),
                "decision_ms": sum(t.decision_ms for t in self.control.timings),
                "submit_ms": sum(t.submit_ms for t in self.control.timings),
                "decision_phases_ms": {
                    name: sum(
                        getattr(t.phases, name)
                        for t in self.control.timings
                        if t.phases is not None
                    )
                    for name in ("synchronize_ms", "candidates_ms", "recall_ms", "appraisal_ms")
                },
                "candidate_stages_ms": {
                    name: sum(
                        getattr(t.phases.construction, name)
                        for t in self.control.timings
                        if t.phases is not None
                    )
                    for name in (
                        "enumeration_ms",
                        "preparation_ms",
                        "screening_ms",
                        "semantics_ms",
                        "metadata_ms",
                        "explanations_ms",
                        "validation_ms",
                    )
                },
            },
        }
