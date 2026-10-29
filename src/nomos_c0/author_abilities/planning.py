"""Select a checked, fully local deterministic projection of authored capabilities."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .effects import FieldEffect
from .entity_reads import OwnerRead
from .expressions import compile_value_expression
from .program import AuthorProgram


@dataclass(frozen=True)
class PlanningPlan:
    program: AuthorProgram
    name: str
    actor: str
    actor_type: str
    goal_type: str
    achieved: object
    reward: int
    step: int
    actions: tuple
    fields: tuple


def compile_planning(program, document):
    if type(program) is not AuthorProgram or type(document) is not dict:
        raise C0LawError("planning requires its checked Program and a selection document")
    if set(document) != {"schema", "name", "actor", "goal", "utility", "actions"} or (
        document["schema"] != "nomos.author.planning"
    ):
        raise C0LawError("planning requires the exact selection schema")
    actor, goal, utility = document["actor"], document["goal"], document["utility"]
    if (
        type(document["name"]) is not str
        or not document["name"]
        or type(actor) is not dict
        or len(actor) != 1
        or type(goal) is not dict
        or set(goal) != {"type", "achieved"}
        or type(utility) is not dict
        or set(utility) != {"reward", "step"}
        or any(type(v) is not int for v in utility.values())
    ):
        raise C0LawError("planning needs one Actor, a typed goal and explicit integer utility")
    actor_name, actor_type = next(iter(actor.items()))
    definitions = dict(program.table.definitions)
    if (
        type(actor_name) is not str
        or actor_name == "goal"
        or not actor_name.isidentifier()
        or type(actor_type) is not str
        or actor_type not in definitions
        or definitions[actor_type].kind != "ref"
        or type(goal["type"]) is not str
        or goal["type"] not in definitions
    ):
        raise C0LawError("planning needs declared Actor and goal types")
    entities = dict(program.entities.entities)
    if entities[definitions[actor_type].sort].kind != "person":
        raise C0LawError("planning controller must be a Person")
    names = document["actions"]
    if (
        type(names) is not list
        or not names
        or any(type(n) is not str for n in names)
        or len(set(names)) != len(names)
        or set(names) - {a.name for a in program.abilities}
    ):
        raise C0LawError("planning selects distinct existing Source capability names")
    if any(
        (
            program.reactions,
            program.time,
            program.random,
            program.activities,
            program.periodic,
            program.terminal,
            program.opening,
            program.settlements,
        )
    ):
        raise C0LawError("planning projection requires a world without automatic mechanisms")
    achieved = compile_value_expression(
        goal["achieved"],
        program.table,
        {actor_name: actor_type, "goal": goal["type"]},
        returns="Bool",
        library=program.queries,
        entities=program.entities,
        actor=actor_name,
        context="actor",
        path="planning.goal.achieved",
    )
    fields = set()
    possible_sorts = {*program.objects, *program.actor_kinds, *(sort for _, sort in program.actors)}

    def check_read(read, holder):
        if read.relation or not program.entities.permitted(read, context="actor", actor=holder):
            raise C0LawError(f"planning cannot predict unreadable field {read.sort}.{read.field}")
        fields.add((read.sort, read.field))

    def check_expression(expression, holder):
        for read in expression.summary.owner_reads:
            check_read(read, holder)
        if expression.summary.context == "world":
            for sort in expression.summary.reference_domains:
                if any(
                    program.table.accepts_sort(sort, actual)
                    and entities[actual].reference != "public"
                    for actual in possible_sorts
                ):
                    raise C0LawError(f"planning cannot localize world reference domain {sort}")

    check_expression(achieved, actor_name)
    actions = tuple(next(a for a in program.abilities if a.name == name) for name in names)
    for action in actions:
        if not program.table.accepts_sort(
            program.table[action.actor_type].sort, definitions[actor_type].sort
        ) or any(
            (
                action.context,
                action.process,
                action.epoch,
                action.views,
                action.costs,
                action.time_cost,
            )
        ):
            raise C0LawError("planning requires matching, stateless, direct local capabilities")
        leaf = action.resolution
        if (
            leaf.result is None
            or leaf.forms
            or leaf.draws
            or leaf.deliveries
            or leaf.next_point is not None
            or any(type(e) is not FieldEffect or e.operation != "set" for e in leaf.effects)
        ):
            raise C0LawError("planning projection supports one deterministic set-effect leaf")
        if any(
            item.kind != "member"
            or program.table[item.type_name].kind
            not in {"bool", "unit", "int", "text", "enum", "ref"}
            for item in action.inputs.inputs
        ):
            raise C0LawError("planning projection currently requires scalar member inputs")
        io = program.execution_io.rule(action.name)
        if io.information or io.context_writes:
            raise C0LawError("planning projection cannot acquire information or write contexts")
        for use in io.expressions:
            check_expression(use.expression, action.actor)
        for write in io.field_writes:
            check_read(OwnerRead(write.sort, write.field, write.selector), action.actor)
    return PlanningPlan(
        program,
        document["name"],
        actor_name,
        actor_type,
        goal["type"],
        achieved,
        utility["reward"],
        utility["step"],
        actions,
        tuple(sorted(fields)),
    )
