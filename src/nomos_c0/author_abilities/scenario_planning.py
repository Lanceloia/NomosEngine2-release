"""Check explicit finite subjective models separately from authoritative world rules."""

from dataclasses import dataclass
from fractions import Fraction

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier
from .expressions import compile_value_expression
from .frontend import row
from .inputs import compile_inputs
from .local_views import compile_local_views
from .planning_construction import compile_construction
from .program import AuthorProgram


@dataclass(frozen=True)
class ScenarioActionPlan:
    name: str
    inputs: object
    where: object
    state: object
    observation: object
    utility: object
    constructions: tuple


@dataclass(frozen=True)
class ScenarioPlanningPlan:
    """Shared lowering plan; atomic state tracks publication, not the future world."""

    program: AuthorProgram
    name: str
    actor: str
    actor_type: str
    goal_type: str
    local_type: str
    state_type: str
    observation_type: str
    capture: object
    views: tuple
    hypotheses: tuple
    consistent: object
    terminal: object
    actions: tuple
    assumptions: tuple
    guidance: object | None
    continuation: object | None
    atomic: bool


def compile_scenario_planning(program, document):
    return _compile(program, document, atomic=False)


def compile_opportunity_planning(program, document):
    return _compile(program, document, atomic=True)


def _compile(program, document, *, atomic):
    if type(program) is not AuthorProgram:
        raise C0LawError("scenario planning needs its checked Program")
    common = {"schema", "name", "actor", "local", "actions"}
    forecast = {
        "goal",
        "state",
        "observation",
        "hypotheses",
        "consistent",
        "terminal",
        "assumptions",
    }
    row(
        document,
        common if atomic else common | forecast,
        {"guidance"} if atomic else {"guidance", "continuation"},
        path="scenario_planning",
    )
    schema = "nomos.author.opportunity_planning" if atomic else "nomos.author.scenario_planning"
    if document["schema"] != schema or not _identifier(document["name"]):
        raise C0LawError("scenario planning needs its schema and a valid name")
    actor = document["actor"]
    if type(actor) is not dict or len(actor) != 1:
        raise C0LawError("scenario planning needs one Actor")
    actor_name, actor_type = next(iter(actor.items()))
    table, entities = program.table, program.entities
    types, schemas = dict(table.definitions), dict(entities.entities)
    if (
        not _identifier(actor_name)
        or actor_name in {"local", "state", "goal"}
        or type(actor_type) is not str
        or actor_type not in types
        or types[actor_type].kind != "ref"
        or schemas[types[actor_type].sort].kind != "person"
    ):
        raise C0LawError("scenario planning controller needs a declared Person Ref")
    goal, local = "Unit" if atomic else document["goal"], document["local"]
    state_type = "Bool" if atomic else document["state"]
    observation_type = "Unit" if atomic else document["observation"]
    if type(goal) is not str or goal not in types:
        raise C0LawError("scenario planning goal needs a named type")
    if not atomic and any(
        (
            program.time,
            program.activities,
            program.periodic,
            program.settlements,
        )
    ):
        raise C0LawError(
            "scenario planning does not yet model time, randomness or deferred execution"
        )
    if (
        not atomic
        and program.random is not None
        and (
            not program.opening
            or any(
                node.draws
                for producer in (*program.abilities, *program.reactions)
                for node in producer.resolution.walk()
            )
        )
    ):
        raise C0LawError("scenario planning accepts opening-only randomness, not runtime draws")
    row(local, {"type", "value", "views"}, path="scenario_planning.local")
    for name in (local["type"], state_type, observation_type):
        if type(name) is not str or name not in types:
            raise C0LawError("scenario planning needs named local/state/observation types")
    assumptions = (
        {"scope": "One atomic publication, valued by the bound Subject."}
        if atomic
        else document["assumptions"]
    )
    if (
        type(assumptions) is not dict
        or not assumptions
        or any(
            not _identifier(k) or type(v) is not str or not v.strip() or len(v) > 2000
            for k, v in assumptions.items()
        )
    ):
        raise C0LawError("scenario planning needs explicit bounded assumptions")
    if type(local["views"]) is not dict:
        raise C0LawError("scenario planning views need named report ports")
    from .cognition import channel_signatures_from_program

    channels = channel_signatures_from_program(program)
    declarations, supplied = {}, {}
    for alias, body in local["views"].items():
        row(body, {"channel"}, {"reports", "projection"}, path="scenario_planning.local.views")
        if (
            not _identifier(alias)
            or alias
            in {actor_name, "goal", "local", "state", *types, *dict(program.queries.definitions)}
            or type(body["channel"]) is not str
            or len(set(body) & {"reports", "projection"}) != 1
            or any(type(v) is not str for v in body.values())
        ):
            raise C0LawError("scenario planning report port needs a valid alias/channel")
        declarations[alias] = {k: v for k, v in body.items() if k != "channel"}
        supplied[alias] = body["channel"]
    views = compile_local_views(
        declarations,
        supplied,
        table,
        program.queries,
        entities,
        {actor_name: actor_type, "local": local["type"], "state": state_type, "goal": goal},
        channels,
    )
    capture = compile_value_expression(
        local["value"],
        table,
        {actor_name: actor_type, "goal": goal},
        returns=local["type"],
        library=program.queries,
        entities=entities,
        actor=actor_name,
        context="actor",
        local_views=tuple(views),
        path="scenario_planning.local.value",
    )
    base = {"local": local["type"], "goal": goal}

    def pure(text, bindings, returns, path):
        expression = compile_value_expression(
            text,
            table,
            bindings,
            returns=returns,
            library=program.queries,
            entities=entities,
            context="actor",
            path="scenario_planning." + path,
        )
        check_pure(expression)
        return expression

    hypotheses = [{"probability": [1, 1], "value": "False"}] if atomic else document["hypotheses"]
    if type(hypotheses) is not list or not hypotheses or len(hypotheses) > 32:
        raise C0LawError("scenario planning needs one to 32 explicit hypotheses")
    compiled = []
    for item in hypotheses:
        row(item, {"probability", "value"}, path="scenario_planning.hypotheses")
        weight = item["probability"]
        if (
            type(weight) is not list
            or len(weight) != 2
            or any(type(v) is not int or v < 1 for v in weight)
        ):
            raise C0LawError("scenario probability needs positive integer numerator/denominator")
        compiled.append((Fraction(*weight), pure(item["value"], base, state_type, "seed")))
    if sum(p for p, _ in compiled) != 1:
        raise C0LawError("scenario probabilities must sum to one")
    state_base = {**base, "state": state_type}
    consistent = pure(
        "True" if atomic else document["consistent"], state_base, "Bool", "consistent"
    )
    terminal = pure("state" if atomic else document["terminal"], state_base, "Bool", "terminal")
    actions = document["actions"]
    if type(actions) is not dict or not atomic and not actions:
        raise C0LawError("scenario planning needs named actual capabilities")
    selected = {a.name: a for a in program.abilities}
    output = []
    for name, body in actions.items():
        row(
            body,
            {"inputs", "where"} if atomic else {"inputs", "where", "predict"},
            path="scenario_planning.actions",
        )
        actual = selected.get(name) if type(name) is str else None
        if (
            actual is None
            or actual.process
            or not atomic
            and (actual.epoch or actual.time_cost)
            or not table.accepts_sort(table[actual.actor_type].sort, types[actor_type].sort)
        ):
            raise C0LawError("scenario planning requires selected instantaneous Actor capabilities")
        declarations = body["inputs"]
        if type(declarations) is not dict:
            raise C0LawError("scenario planning inputs need named declarations")
        recipes, ordinary = {}, {}
        for key, declaration in declarations.items():
            if type(declaration) is dict and "construct" in declaration:
                row(declaration, {"type", "construct"}, {"constraint"}, path="planning.construct")
                recipes[key] = declaration["construct"]
                ordinary[key] = {k: v for k, v in declaration.items() if k != "construct"}
                ordinary[key]["enter"] = "typed"
            else:
                ordinary[key] = declaration
        inputs = compile_inputs(
            table,
            ordinary,
            base,
            library=program.queries,
            entities=entities,
            path="scenario_planning.actions." + name + ".inputs",
        )
        if any(i.name == "state" for i in inputs.inputs):
            raise C0LawError("scenario planning input cannot shadow the hypothesis state binding")
        actual_types = {i.name: i.type_name for i in actual.inputs.inputs}
        if (
            set(actual_types) != {i.name for i in inputs.inputs}
            or any(
                table[actual_types[i.name]].type_id != table[i.type_name].type_id
                for i in inputs.inputs
            )
            or any(
                i.name not in recipes and not _supported_input(table, i)
                for i in (*inputs.inputs, *actual.inputs.inputs)
            )
            or any(actual.inputs.definition(n).kind != "enter" for n in recipes)
            or any(inputs.definition(i.name).kind != i.kind for i in actual.inputs.inputs)
        ):
            raise C0LawError(
                "scenario planning inputs must match member/subset or constructed typed ports"
            )
        constructions, bindings = [], dict(base)
        for item in inputs.inputs:
            if item.name in recipes:
                constructions.append(
                    (
                        item.name,
                        compile_construction(
                            program,
                            item.type_name,
                            recipes[item.name],
                            bindings,
                            path="scenario_planning.actions."
                            + name
                            + ".inputs."
                            + item.name
                            + ".construct",
                        ),
                    )
                )
            for expression in (item.pool, item.minimum, item.maximum, item.constraint):
                if expression is not None:
                    check_pure(expression)
            bindings[item.name] = item.type_name
        environment = {**(base if atomic else state_base), **actual_types}
        predict = (
            {"state": "True", "observation": "None", "utility": "0"} if atomic else body["predict"]
        )
        row(predict, {"state", "observation", "utility"}, path="scenario_planning.predict")
        output.append(
            ScenarioActionPlan(
                name,
                inputs,
                pure(body["where"], environment, "Bool", name + ".where"),
                pure(predict["state"], environment, state_type, name + ".state"),
                pure(
                    predict["observation"],
                    environment,
                    observation_type,
                    name + ".observation",
                ),
                pure(predict["utility"], environment, "Integer<>", name + ".utility"),
                tuple(constructions),
            )
        )
    guidance = None
    if "guidance" in document:
        from .planning_guidance import compile_guidance

        guidance = compile_guidance(program, document["guidance"], views, output, base)
    continuation = None
    if "continuation" in document:
        from .planning_continuation import compile_continuation

        continuation = compile_continuation(program, document["continuation"], base)
    return ScenarioPlanningPlan(
        program,
        document["name"],
        actor_name,
        actor_type,
        goal,
        local["type"],
        state_type,
        observation_type,
        capture,
        tuple(views),
        tuple(compiled),
        consistent,
        terminal,
        tuple(output),
        tuple(assumptions.items()),
        guidance,
        continuation,
        atomic,
    )


def check_pure(expression):
    if expression.summary.owner_reads or expression.summary.reference_domains:
        raise C0LawError("scenario prediction accepts supplied values, not world/local owner reads")


def _supported_input(table, item):
    kind = table[item.type_name]
    # The authored pool is finite even when its nominal members are structured values.
    return item.kind == "member" or item.kind == "subset" and kind.kind == "set"
