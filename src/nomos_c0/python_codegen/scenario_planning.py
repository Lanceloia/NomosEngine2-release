"""Emit value-only hypothetical models and separately checked local captures."""

from .information import local_readers
from .planning_construction import carrier, emit_construction

IMPORTS = (
    "from fractions import Fraction\n"
    "from nomos_runtime.entities import Reference\n"
    "from nomos_runtime.planning import PlanningAction\n"
    "from nomos_runtime.planning_bindings import SubsetDomain\n"
    "from nomos_runtime.planning_construction import Construction\n"
    "from nomos_runtime.planning_preparation import ConstructionExpression\n"
    "from nomos_runtime.planning_recall import CompiledGuidance, RecallPort\n"
    "from nomos_runtime.scenario_planning import CompiledScenarioPlanning, PlanningWindow"
)


def functions(emitter, plan):
    def expression(checked):
        return emitter.expression(
            checked, reads="reads", limits="value_limits", logical_work="work"
        )

    readers = local_readers(emitter, "_planning_capture", plan, memoize=True)
    emitter.function(
        "_planning_capture",
        "session, actor, goal, work",
        [
            "before, receipts = session._states, session._receipts",
            "record, controller = None, actor",
            "value_limits = session.limits.value",
            f"local_values = {readers}(session, before, controller, receipts, record)",
            "reads = session.context(before, 'actor', actor, receipts=receipts, "
            "local_values=local_values)",
            f"environment = {{{plan.actor!r}: actor, 'goal': goal}}",
            f"return {expression(plan.capture)}, reads.references",
        ],
    )
    seeds = []
    for index, (probability, seed) in enumerate(plan.hypotheses):
        name = f"_planning_seed_{index}"
        emitter.function(
            name,
            "reads, value_limits, local, goal, work",
            [
                "environment = {'local': local, 'goal': goal}",
                "return " + expression(seed),
            ],
        )
        seeds.append(f"(Fraction({probability.numerator}, {probability.denominator}), {name})")
    for name, checked in (("consistent", plan.consistent), ("terminal", plan.terminal)):
        emitter.function(
            "_planning_" + name,
            "reads, value_limits, local, state, goal, work",
            [
                "environment = {'local': local, 'state': state, 'goal': goal}",
                "return " + expression(checked),
            ],
        )
    actions = []
    for index, action in enumerate(plan.actions):
        prefix = f"_planning_case_{index}"
        names = tuple(item.name for item in action.inputs.inputs)
        lines = [
            f"if set(arguments) - set({names!r}): raise ValueError('unknown planning argument')",
            "environment = {'local': local, 'goal': goal}",
        ]
        for item in action.inputs.inputs:
            if item.name in dict(action.constructions):
                lines.extend(
                    [
                        f"if {item.name!r} not in arguments: return {item.name!r}, None",
                        f"environment[{item.name!r}] = _VALIDATORS[{item.type_name!r}]("
                        f"arguments[{item.name!r}], "
                        "ValueBudget(value_limits, reads.references), ())",
                    ]
                )
                continue
            if item.kind == "subset":
                lines.extend(
                    [
                        "pool = " + expression(item.pool),
                        "minimum = " + expression(item.minimum),
                        "maximum = " + expression(item.maximum),
                        "if minimum < 0 or maximum < minimum or minimum > len(pool): return None",
                        f"if {item.name!r} not in arguments: "
                        f"return {item.name!r}, SubsetDomain(pool, minimum, maximum)",
                        f"value = _VALIDATORS[{item.type_name!r}](arguments[{item.name!r}], "
                        "ValueBudget(value_limits, reads.references), ())",
                        "work.spend(max(1, len(value)))",
                        "if not minimum <= len(value) <= maximum or not value <= pool: return None",
                        f"environment[{item.name!r}] = value",
                    ]
                )
                continue
            lines.extend(
                [
                    "pool = " + expression(item.pool),
                    f"if {item.name!r} not in arguments: return {item.name!r}, pool",
                    f"value = _VALIDATORS[{item.type_name!r}](arguments[{item.name!r}], "
                    "ValueBudget(value_limits, reads.references), ())",
                    "if value not in pool: return None",
                    f"environment[{item.name!r}] = value",
                ]
            )
        for item in action.inputs.inputs:
            if item.constraint is not None:
                lines.append(f"if not {expression(item.constraint)}: return None")
        lines.append("return None, environment")
        emitter.function(
            prefix + "_bind", "reads, value_limits, local, goal, arguments, work", lines
        )
        lines = [
            f"bound = {prefix}_bind(reads, value_limits, local, goal, arguments, work)",
            "if bound is None or bound[0] is not None: return None",
            "environment = {**bound[1], 'state': state}",
            f"if not {expression(action.where)}: return None",
            "following = " + expression(action.state),
            "observation = " + expression(action.observation),
            "utility = " + expression(action.utility),
            "return following, observation, utility",
        ]
        emitter.function(
            prefix + "_predict", "reads, value_limits, local, state, goal, arguments, work", lines
        )
        parameters = ", ".join(
            f"({i.name!r}, {i.type_name!r}, {carrier(emitter, emitter.program.table[i.type_name])})"
            for i in action.inputs.inputs
        )
        subsets = ", ".join(
            f"({i.name!r}, {carrier(emitter, emitter.program.table[i.type_name].element)})"
            for i in action.inputs.inputs
            if i.kind == "subset"
        )
        constructions = ", ".join(
            f"({name!r}, {emit_construction(emitter, recipe, prefix + '_construct_' + str(n))})"
            for n, (name, recipe) in enumerate(action.constructions)
        )
        actions.append(
            f"PlanningAction({action.name!r}, ({parameters}{',' if parameters else ''}), "
            f"{prefix}_bind, {prefix}_predict, ({subsets}{',' if subsets else ''}), "
            f"({constructions}{',' if constructions else ''}))"
        )
    guidance = "None"
    if plan.guidance is not None:
        priorities, members = [], []
        for index, (action, checked) in enumerate(plan.guidance.actions):
            name = f"_planning_priority_{index}"
            emitter.function(
                name,
                "reads, value_limits, local, goal, work",
                [
                    "environment = {'local': local, 'goal': goal}",
                    "return " + expression(checked),
                ],
            )
            priorities.append(f"({action!r}, {name})")
        for index, (action, field, member, checked) in enumerate(plan.guidance.members):
            name = f"_planning_member_{index}"
            emitter.function(
                name,
                "reads, value_limits, local, goal, arguments, member, work",
                [
                    "environment = {**arguments, 'local': local, 'goal': goal, "
                    f"{member!r}: member}}",
                    "return " + expression(checked),
                ],
            )
            members.append(f"({action!r}, {field!r}, {name})")
        ports = ", ".join(
            f"RecallPort({alias!r}, {plan.program.table[view.type_name].element.name!r}, "
            f"{view.channel!r}, {view.source!r})"
            for alias, view in plan.guidance.views
        )
        guidance = (
            f"CompiledGuidance(({ports},), {plan.guidance.exploration}, "
            f"({', '.join(priorities)}{',' if priorities else ''}), "
            f"({', '.join(members)}{',' if members else ''}), _TERM_CODECS)"
        )
    continuation = "None"
    if plan.continuation is not None:
        continuation = "_planning_window"
        emitter.function(
            continuation,
            "reads, value_limits, local, goal, work",
            [
                "environment = {'local': local, 'goal': goal}",
                "return PlanningWindow("
                + ", ".join(
                    expression(getattr(plan.continuation, name))
                    for name in ("scope", "ready", "complete", "closed")
                )
                + ")",
            ],
        )
    return seeds, actions, guidance, continuation, plan.atomic


def definition(plan, signature, functions):
    seeds, actions, guidance, continuation, atomic = functions
    return (
        f"CompiledScenarioPlanning(PROGRAM, {plan.name!r}, {signature!r}, "
        f"{plan.program.table[plan.actor_type].sort!r}, {plan.goal_type!r}, "
        f"_VALIDATORS[{plan.goal_type!r}], _planning_capture, "
        f"({', '.join(seeds)},), _planning_consistent, _planning_terminal, "
        f"({', '.join(actions)}{',' if actions else ''}), "
        f"{plan.assumptions!r}, {guidance}, {continuation}, {atomic!r})"
    )
