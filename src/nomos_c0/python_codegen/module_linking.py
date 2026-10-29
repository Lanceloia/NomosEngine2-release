"""Link generated rule functions, optional consumers and Program exports into one module."""

import ast

from nomos_c0.author_contract_v1 import C0LawError
from nomos_runtime.artifact_format import ARTIFACT_ABI

from .cognition import definition as cognition_definition
from .cognition_terms import term_codecs
from .control import terminal_definition
from .expressions import _Emitter
from .fixed_values import fixed_value
from .information import context_definition, information_definition, projection_definition
from .play import play_definition
from .presentation import definition as display_definition
from .strategies import controller_definition
from .syntax import constant, statements
from .temporal import time_definition


def link_world(world):
    contexts = [
        context_definition(world, index, plan) for index, plan in enumerate(world.program.contexts)
    ]
    projections = [
        projection_definition(world, index, plan)
        for index, plan in enumerate(world.program.projections)
    ]
    information = [
        information_definition(world, index + len(projections), plan)
        for index, plan in enumerate(world.program.information)
    ]
    terminal = terminal_definition(world)
    time = time_definition(world)
    actions = [world.action(index, plan) for index, plan in enumerate(world.program.abilities)]
    reactions = [world.reaction(index, plan) for index, plan in enumerate(world.program.reactions)]
    controllers = controller_definition(world)
    play = play_definition(world)
    cognition = cognition_definition(world)
    display = display_definition(world)
    planning_functions = None
    planning_memory = False
    if world.planning is not None:
        from nomos_c0.author_abilities.scenario_planning import ScenarioPlanningPlan

        from . import planning as planning_codegen

        if type(world.planning) is ScenarioPlanningPlan:
            from . import scenario_planning as planning_codegen

            planning_memory = world.planning.guidance is not None
        planning_functions = planning_codegen.functions(world, world.planning)
    for name, plan in world.resolutions.disclosures.values():
        world.disclosure(name, plan)
    if not world.expressions:
        raise C0LawError(
            "Python world generation does not yet support worlds without executable expressions"
        )
    emitter = _Emitter(world.expressions[0][1], world=True, report=world.report)
    for _, plan in world.program.table.definitions:
        emitter.types.add(plan)
    for _, schema in world.program.entities.entities:
        for _, plan in schema.fields:
            emitter.types.add(plan)
    # Captures remain typed ABI inputs even when no expression reads their values.
    for plan in world.resolution_plans:
        for _, _, kind in getattr(plan, "captures", ()):
            emitter.types.add(world.program.table[kind])
    from .frame_queries import repeated_queries

    module = emitter.module(
        tuple(world.expressions),
        input_proofs=world.expression_entry_proofs,
        frame_queries=repeated_queries(world.controllers),
        # Finalize the complete world once after linking its remaining functions.
        finalize_locations=False,
    )
    if world.report is not None:
        for function, checked, type_name in world.derived_result_proofs:
            world.report.remark(
                "Passed",
                "derived-input-result",
                function,
                checked.source,
                (checked.node.offset,),
                "exact-actor-result-contract",
                f"Compose the generated {type_name} Actor result directly into its binding; "
                "retain the expression's own checks, failures and logical budgets.",
            )
    evaluation_plans = (
        ()
        if world.controllers is None
        else tuple(
            (index, ordinal, *plan.manifest())
            for index, ordinal, plan in world.controllers.evaluations
        )
    )
    module.body.append(
        ast.Assign(
            targets=[ast.Name(id="CANDIDATE_EVALUATION_PLANS", ctx=ast.Store())],
            value=constant(evaluation_plans),
        )
    )
    cognition_value = "None"
    semantics = world.controllers is not None and any(
        strategy.semantics is not None for strategy in world.controllers.strategies
    )
    if cognition is not None or semantics or planning_memory:
        module.body.extend(
            statements(
                "import json\nfrom nomos_runtime.entities import Reference\n"
                "from types import MappingProxyType\nfrom nomos_cognition import Term"
            )
        )
        functions, codecs = term_codecs(emitter.types)
        module.body.extend(functions)
        module.body.extend(statements(f"_TERM_CODECS = MappingProxyType({codecs})"))
    if semantics:
        module.body.extend(
            statements(
                "from nomos_cognition.appraisal import Candidate as SemanticCandidate, "
                "Model as AppraisalModel"
            )
        )
        module.body.extend(
            statements(
                "from time import perf_counter\n"
                "from nomos_runtime.decisions import (CandidateDescription, "
                "CandidateMetadata, DescriptionTiming, PreparedCandidateRule)\n"
                "from nomos_runtime.feedback import (FeedbackPort, "
                "FeedbackRelation, FeedbackRule)"
            )
        )
    if cognition is not None:
        module.body.extend(
            statements(
                "from nomos_cognition import Frame\n"
                "from nomos_cognition.state import judgments\n"
                "from nomos_cognition.reasoning import Rule, Premise, Pattern, Limits\n"
                "from nomos_runtime.cognition import (CognitionDefinition, CognitionLibrary, "
                "RevisionRule, Derivation, read_context as cognition_reads)"
            )
        )
        module.body.extend(
            statements(
                "from nomos_cognition.local import Count, Allocation, Limits as LocalLimits\n"
                "from nomos_cognition.finite import Limits as FiniteLimits\n"
                "from nomos_runtime.analysis import AnalysisInput\n"
                "from nomos_runtime.local_analysis import "
                "LocalDefinition, analyze as analyze_local\n"
                "from nomos_runtime.finite_analysis import (FiniteDefinition, FiniteVariable, "
                "FiniteQuery, analyze as analyze_finite)"
            )
        )
        cognition_value = f"CognitionLibrary({cognition}, _TERM_CODECS)"
    module.body.extend(
        statements(
            "from nomos_runtime.entities import EntitySchema\n"
            "from nomos_runtime.presentation import (CompiledDisplay, DisplayRead, "
            "DisplayAction, DisplayInput, InputDisplayError)\n"
            "from nomos_runtime.processes import request_binding\n"
            "from nomos_runtime import report_inputs as _report_inputs\n"
            "from nomos_runtime.values import wire_key\n"
            "from nomos_runtime.ordering import canonical as _delivery_order\n"
            "from nomos_runtime.carrying import "
            "CarryingDefinition, CarryOffer, proposal, set_proposal, set_field\n"
            "from nomos_runtime.assurances import "
            "CheckedFact, CheckedConstraint, InformationViolation\n"
            "from nomos_runtime.information import "
            "ContextDefinition, ProjectionDefinition, InformationDefinition\n"
            "from nomos_runtime.processes import (ProcessNode, ResponseWindow, "
            "check_stage_entry, destination)\n"
            "from nomos_runtime.terminals import TerminalDefinition\n"
            "from nomos_runtime.settlement import OrderedSettlement, OrderedStep\n"
            "from nomos_runtime.temporal import (TimeDefinition, ActivityDefinition, "
            "PeriodicDefinition, ActivityRequest)\n"
            "from nomos_runtime.scheduling import ScheduleDefinition, Projection\n"
            "from nomos_runtime.choices import InputField, ChoiceForm\n"
            "from nomos_runtime.candidates import "
            "ControllerLibrary, StrategyDefinition, CandidateRule\n"
            "from nomos_runtime.play import PlayDefinition\n"
            "from nomos_runtime.joint_decisions import JointDecision\n"
            "from nomos_runtime.opening import OpeningDeal\n"
            "from nomos_runtime.errors import AdmissionError, ControlRejection\n"
            "from nomos_runtime.effects import Draft\n"
            "from nomos_runtime.actions import (ActionDefinition, ActionAdmission, "
            "ReactionDefinition, Delivery)\n"
            "from nomos_runtime.records import ActionEpoch\n"
            "from nomos_runtime.world import CompiledProgram, SessionLimits"
        )
    )
    module.body.extend(world.functions)
    planning_value = "None"
    if planning_functions is not None:
        import hashlib

        selected = world.planning
        metadata = planning_codegen.definition(selected, "model-signature", planning_functions)
        signature = hashlib.sha256(
            (ast.unparse(ast.fix_missing_locations(module)) + metadata).encode()
        ).hexdigest()
        module.body.extend(statements(planning_codegen.IMPORTS))
        planning_value = planning_codegen.definition(selected, signature, planning_functions)
    sorts = {sort.name: sort for sort in world.program.table.sorts}
    schemas = [
        f"EntitySchema({name!r}, {schema.kind!r}, {sorts[name].parents!r}, "
        f"{tuple((field, plan.name) for field, plan in schema.fields)!r}, "
        f"{schema.view!r}, {schema.public!r}, {schema.reference!r}, "
        "initial=("
        + ", ".join(
            f"({p.name!r}, {p.owner!r}, lambda references, limits: "
            + fixed_value(world.program.table, p, references="references", limits="limits")
            + ")"
            for p in schema.initial
        )
        + ("," if schema.initial else "")
        + "))"
        for name, schema in world.program.entities.entities
    ]
    channels = tuple(
        (plan.channel_name + "." + call.label, call.definition.value.result.name)
        for plan in world.resolution_plans
        for leaf in plan.resolution.leaves()
        for call in leaf.deliveries
    )
    relations = [
        f"CarryingDefinition({plan.name!r}, {plan.item!r}, {plan.person!r}, "
        f"{plan.holder!r}, {plan.ground!r}, {plan.position!r})"
        for _, plan in world.program.entities.relations
    ]
    settlements = [
        f"OrderedSettlement({plan.source!r}, {plan.key!r}, ("
        + ", ".join(f"OrderedStep({step.source!r}, {step.required!r})" for step in plan.steps)
        + ",))"
        for plan in world.program.settlements
    ]
    opening = [
        f"OpeningDeal({plan.name!r}, {plan.context!r}, {plan.deal!r}, {plan.to!r}, "
        f"{plan.sort!r}, {plan.field!r}, {plan.stream!r})"
        for plan in world.program.opening
    ]
    module.body.extend(
        statements(
            f"PROGRAM = CompiledProgram({world.program.name!r}, "
            f"{world.program.entities.fingerprint!r}, "
            f"({', '.join(schemas)},), {world.program.actors!r}, "
            f"{world.program.actor_kinds!r}, {world.program.objects!r}, "
            f"_VALIDATORS, _DECODERS, _ENCODERS, "
            f"({', '.join(actions)}{',' if actions else ''}), "
            f"({', '.join(reactions)}{',' if reactions else ''}), {channels!r}, "
            f"({', '.join(contexts)}{',' if contexts else ''}), "
            f"({', '.join(projections)}{',' if projections else ''}), "
            f"({', '.join(information)}{',' if information else ''}), "
            f"_REFERENCES, {terminal}, ({', '.join(relations)}{',' if relations else ''}), "
            f"{() if world.program.random is None else world.program.random.streams!r}, "
            f"({', '.join(settlements)}{',' if settlements else ''}), {time}, {play}, "
            f"{cognition_value}, opening=({', '.join(opening)}{',' if opening else ''}), "
            f"report_collections={world.program.report_collections!r})\n"
            f"PLANNING = {planning_value}\n"
            f"CONTROLLERS = {controllers}\n"
            f"DISPLAY = {display}\n"
            "def start(assets, *, limits=SessionLimits(), controllers=CONTROLLERS):\n"
            "    return PROGRAM.start(assets, limits=limits, controllers=controllers)"
        )
    )
    module.body.extend(statements(f"NOMOS_ARTIFACT_ABI = {ARTIFACT_ABI}"))
    return ast.fix_missing_locations(module)
