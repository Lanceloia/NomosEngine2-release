"""Generate rule functions from checked declarations; module exports are linked separately."""

import ast

from nomos_c0.author_abilities.formation import FormedSelector
from nomos_c0.author_abilities.program import AuthorProgram
from nomos_c0.author_contract_v1 import C0LawError

from .assurances import certification
from .choices import choice_function, eligibility_function
from .control import process_completion, process_node
from .costs import costs
from .fixed_values import fixed_value
from .information import local_readers
from .input_bindings import InputBindings
from .module_linking import link_world
from .resolution import ResolutionEmitter, check_effects, write_targets
from .scheduling import action_cost
from .syntax import statements
from .temporal import start_checks, start_requests


def unsupported(message):
    raise C0LawError("Python world generation does not yet support " + message)


class WorldEmitter:
    def __init__(
        self,
        program,
        controllers,
        cognition,
        presentation,
        report=None,
        planning=None,
        subject_planning=False,
    ):
        self.program = program
        self.report = report
        if planning is not None:
            from nomos_c0.author_abilities.planning import PlanningPlan
            from nomos_c0.author_abilities.scenario_planning import ScenarioPlanningPlan

            if (
                type(planning) not in (PlanningPlan, ScenarioPlanningPlan)
                or planning.program is not program
            ):
                raise C0LawError("planning export needs its exact checked Program")
        self.planning = planning
        if type(subject_planning) is not bool:
            raise C0LawError("subject planning selection must be boolean")
        if subject_planning:
            from nomos_c0.author_abilities.scenario_planning import ScenarioPlanningPlan
            from nomos_c0.author_abilities.strategies import ControllerPlan

            if (
                type(planning) is not ScenarioPlanningPlan
                or not planning.atomic
                or type(controllers) is not ControllerPlan
                or program.table[planning.goal_type].kind != "unit"
                or program.table[planning.state_type].kind != "bool"
                or program.table[planning.observation_type].kind != "unit"
                or len({a.name for a in planning.actions}) != len(planning.actions)
                or any(
                    s.semantics is None or s.participation is None or s.tie != "canonical"
                    for s in controllers.strategies
                )
            ):
                raise C0LawError(
                    "subject planning requires an opportunity plan, Unit goal/observation, "
                    "Bool state "
                    "and semantic participation policies"
                )
        if (
            planning is not None
            and type(planning) is ScenarioPlanningPlan
            and planning.atomic
            and not subject_planning
        ):
            raise C0LawError("opportunity planning requires explicit Subject control selection")
        self.subject_planning = subject_planning
        if subject_planning and any(
            len({r.ability for r in s.candidates}) != len(s.candidates)
            for s in controllers.strategies
        ):
            raise C0LawError("subject planning needs one distinct semantic rule per ability")
        from nomos_c0.author_abilities.play import PlayPlan, TabletopPlan

        if program.play is not None and type(program.play) not in (PlayPlan, TabletopPlan):
            unsupported("unrecognized play mechanism")
        if (
            presentation is None
            and program.play is not None
            and program.play.mechanism == "tabletop"
        ):
            from nomos_c0.author_abilities.tabletop_presentation import (
                compile_tabletop_presentation,
            )

            presentation = compile_tabletop_presentation(
                program, {"schema": "nomos.tabletop.presentation"}
            )
        if presentation is not None:
            from nomos_c0.author_abilities.tabletop_presentation import TablePresentation

            if type(presentation) is not TablePresentation or presentation.program is not program:
                raise C0LawError("Python display requires its exact checked world Program")
        self.presentation = presentation
        self.controllers = controllers
        if controllers is not None:
            from nomos_c0.author_abilities.strategies import ControllerPlan

            if type(controllers) is not ControllerPlan or controllers.program is not program:
                raise C0LawError("Python controllers require their exact checked world Program")
            if cognition is None:
                cognition = controllers.cognition
            elif controllers.cognition is not None and controllers.cognition is not cognition:
                raise C0LawError("Python controllers and world must select the same cognition")
        if cognition is not None:
            from nomos_c0.author_abilities.cognition import CognitionPlan
            from nomos_c0.author_abilities.finite_model import FinitePlan
            from nomos_c0.author_abilities.local_model import LocalPlan

            if type(cognition) is not CognitionPlan or cognition.program is not program:
                raise C0LawError("Python cognition requires its exact checked world Program")
            if any(
                b.finite is not None
                and type(b.finite) is not FinitePlan
                or b.local is not None
                and type(b.local) is not LocalPlan
                for b in cognition.bindings
            ):
                raise C0LawError("Python cognition requires checked finite/local plans")
        self.cognition = cognition
        self.expressions, self.functions = [], []
        self.resolutions = ResolutionEmitter()
        self.action_views = {}
        self.certification_count = 0
        self.constraint_functions = {}
        self.derived_result_proofs = []
        self.expression_entry_proofs = {}
        self.check_scope()

    def check_scope(self):
        self.resolution_plans = (
            *self.program.abilities,
            *self.program.reactions,
            *(p.completion for p in self.program.activities),
            *(p.cancellation for p in self.program.activities if p.cancellation is not None),
            *(p.event for p in self.program.periodic),
        )
        for plan in self.resolution_plans:
            check_effects(getattr(plan, "costs", ()), costs=True)
            for node in plan.resolution.walk():
                for product in node.forms:
                    selected = (
                        self.program.actor_kinds
                        if product.schema.kind == "person"
                        else self.program.objects
                    )
                    if product.schema.name not in selected:
                        unsupported("formation of unselected entity sorts")
                check_effects(node.effects)
        for plan in self.program.abilities:
            for _, view in plan.views:
                if view.kind not in {"reports", "projected"}:
                    unsupported("cognition views")
            for item in plan.inputs.inputs:
                if item.kind not in {"member", "subset", "sequence", "enter", "derive"}:
                    unsupported("input kind " + item.kind)
        for plan in self.program.reactions:
            for _, remote, _ in plan.captures:
                if type(remote) not in (str, FormedSelector):
                    unsupported("capture selector")

    def expression(
        self,
        checked,
        environment="environment",
        reads=None,
        *,
        limits="session.limits.value",
        logical_work=None,
    ):
        name = "_expression_" + str(len(self.expressions))
        self.expressions.append((name, checked))
        inputs = (
            "{" + ", ".join(f"{key!r}: {environment}[{key!r}]" for key, _ in checked.inputs) + "}"
        )
        context = reads or ("actor_reads" if checked.summary.context == "actor" else "world_reads")
        work = "" if logical_work is None else f", logical_work={logical_work}"
        return f"{name}({inputs}, {context}, value_limits={limits}{work})"

    def context(self, views=None, *, cache_inputs=False, actor_only=False):
        lines, local = [], ""
        if views is not None:
            lines.append(f"local_values = {views}(session, before, controller, receipts, record)")
            local = ", local_values=local_values"
        lines.append(
            "actor_reads = session.context(before, 'actor', controller, receipts=receipts"
            + local
            + (", cache_inputs=True" if cache_inputs else "")
            + ")"
        )
        if not actor_only:
            lines.append(
                "world_reads = session.context(before, controller=controller"
                + local
                + (", cache_inputs=True" if cache_inputs else "")
                + ")"
            )
        return lines

    def function(self, name, signature, lines):
        self.functions.extend(
            statements(f"def {name}({signature}):\n" + "\n".join("    " + line for line in lines))
        )

    def action(self, index, plan):
        prefix = f"_action_{index}"
        views = local_readers(self, prefix, plan) if plan.views else None
        self.action_views[plan.name] = views
        eligible = eligibility_function(self, prefix, plan, views)
        choice = choice_function(self, prefix, plan, views)
        bindings = InputBindings(self)
        lines = bindings.environment(plan, views)
        choices = tuple(item.name for item in plan.inputs.inputs if item.kind != "derive")
        lines.append(
            f"if type(choices) is not dict or set(choices) != set({choices!r}): "
            "raise AdmissionError('MissingBinding', 'exact declared choices required')"
        )
        inputs = {item.name: item for item in plan.inputs.inputs}
        for name in plan.inputs.order:
            item = inputs[name]
            lines.extend(bindings.bind(item))
        for item in plan.inputs.inputs:
            if item.constraint is not None:
                lines.append(
                    f"if not {bindings.expression(item.constraint)}: "
                    "raise AdmissionError('InvalidChoice', 'input constraint is false')"
                )
        lines.append(
            f"if not {bindings.expression(plan.where)}: "
            "raise AdmissionError('NotAdmitted', 'Action condition is false')"
        )
        lines.extend(write_targets(self, plan))
        lines.extend(costs(self, plan, execute=False))
        lines.extend(start_checks(self, plan))
        if plan.process is not None and plan.process.point == "begin":
            lines.append(
                f"check_stage_entry(session, session.program.actions[{plan.name!r}], environment)"
            )
        participants = (
            *(() if plan.process is None else (c.name for c in plan.process.prefix)),
            *(name for name, _ in plan.inputs.base),
            *(p.name for p in plan.inputs.inputs),
        )
        participants = tuple(dict.fromkeys(participants))
        if plan.context is not None:
            participants = (
                plan.actor,
                *(p.name for p in plan.parameters),
                *(p.name for p in plan.inputs.inputs),
            )
        epoch = (
            "None"
            if plan.epoch is None
            else f"ActionEpoch({plan.epoch.result.name!r}, {self.expression(plan.epoch)})"
        )
        lines.append(
            "return ActionAdmission({"
            + ", ".join(f"{key!r}: environment[{key!r}]" for key in participants)
            + "}, "
            + epoch
            + ")"
        )
        self.function(prefix + "_admit", "session, actor, choices, record", lines)
        self.execution(prefix + "_execute", plan, views=views, process=True)
        cost = action_cost(self, prefix + "_time_cost", plan, views)
        local_types = tuple(
            (alias, view.type_name) for alias, view in plan.views if view.process_point
        )
        return (
            f"ActionDefinition({plan.name!r}, {plan.source!r}, "
            f"{self.program.table[plan.actor_type].sort!r}, {prefix}_admit, {prefix}_execute, "
            f"{process_node(self, plan)}, {views or 'None'}, {cost}, {choice}, {eligible}, "
            f"{plan.actor!r}, {plan.resolution.leaves()[0].result.result.name!r}, "
            f"{local_types!r})"
        )

    def execution(self, name, plan, *, views=None, process):
        lines = [
            *self.context(views),
            "draft = Draft(session, before, world_reads.references, "
            "session.limits.value, occurrence, allocation)",
        ]
        if plan.context is not None:
            lines.append(
                f"environment = {{**session.context_values({plan.context.name!r}, before), "
                "**environment}"
            )
        else:
            lines.append("environment = dict(environment)")
        lines.extend(costs(self, plan, execute=True))
        lines.extend(self.resolutions.emit(self, plan))
        if process:
            lines.extend(process_completion(self, plan))
            lines.extend(start_requests(self, plan))
        lines.append("return draft")
        self.function(
            name,
            "session, before, controller, environment, receipts, record, occurrence, allocation",
            lines,
        )

    def reaction(self, index, plan):
        name = f"_reaction_{index}"
        lines = [
            "original = dict(trigger.participants)",
            "original['result'] = trigger.result",
            "environment = {}",
            "world_reads = session.context(before)",
        ]
        for local, remote, kind in plan.captures:
            value = (
                "frozenset(ref for ref in trigger.products "
                f"if world_reads.references.accepts({remote.sort!r}, ref.sort))"
                if type(remote) is FormedSelector
                else f"original[{remote!r}]"
            )
            lines.append(
                f"environment[{local!r}] = _VALIDATORS[{kind!r}]({value}, "
                "ValueBudget(session.limits.value, world_reads.references), ())"
            )
        lines.extend(
            f"environment[{p.name!r}] = "
            + fixed_value(self.program.table, p, references="world_reads.references")
            for p in plan.parameters
        )
        if plan.context is not None:
            lines.append(
                f"environment = {{**session.context_values({plan.context.name!r}, before), "
                "**environment}"
            )
        lines.append(f"if not {self.expression(plan.when)}: return None, environment")
        lines.append(
            "draft = Draft(session, before, world_reads.references, "
            "session.limits.value, occurrence, allocation)"
        )
        lines.extend(self.resolutions.emit(self, plan))
        participants = (*(key for key, _, _ in plan.captures), *(p.name for p in plan.parameters))
        lines.append(
            "return draft, {"
            + ", ".join(f"{key!r}: environment[{key!r}]" for key in participants)
            + "}"
        )
        self.function(name, "session, before, trigger, receipts, occurrence, allocation", lines)
        return f"ReactionDefinition({plan.name!r}, {plan.source!r}, {plan.triggers!r}, {name})"

    def disclosure(self, name, plan):
        # Sampling is invoked only inside the candidate transaction, never by Actor reads.
        lines = [
            "environment = dict(zip("
            + repr(tuple(key for key, _ in plan.parameters))
            + ", arguments, strict=True))"
        ]
        for key, kind in plan.parameters:
            lines.append(
                f"environment[{key!r}] = _VALIDATORS[{kind!r}](environment[{key!r}], "
                "ValueBudget(value_limits, reads.references), ())"
            )
        recipients = self.expression(plan.recipients, reads="reads", limits="value_limits")
        value = self.expression(plan.value, reads="reads", limits="value_limits")
        checker = certification(self, plan)
        lines.extend(
            [
                f"recipients = {recipients}",
                "if not recipients: return recipients, None, (), ()",
                f"content = {value}",
                f"claims, constraints = {checker}(content, reads, value_limits)",
                "return recipients, content, claims, constraints",
            ]
        )
        self.function(name, "arguments, reads, value_limits", lines)


def emit_world_module(
    program,
    *,
    controllers=None,
    cognition=None,
    presentation=None,
    report=None,
    planning=None,
    subject_planning=False,
):
    """Generate a selected world slice; unsupported semantics fail at Compile."""
    if type(program) is not AuthorProgram:
        raise C0LawError("Python world generation needs a checked AuthorProgram")
    emitter = WorldEmitter(
        program,
        controllers,
        cognition,
        presentation,
        report,
        planning=planning,
        subject_planning=subject_planning,
    )
    module = link_world(emitter)
    compile(module, "<c0-generated-world>", "exec")
    return ast.unparse(module) + "\n"
