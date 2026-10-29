"""Finite witnesses consume generated Programs and their actual Session records."""

from copy import deepcopy
from dataclasses import dataclass

from nomos_runtime.errors import AdmissionError, SettlementDefect
from nomos_runtime.expressions import ExpressionError, ValueBindingError
from nomos_runtime.records import ActivityKey
from nomos_runtime.world import CompiledProgram


class WitnessError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class Occurrence:
    occurrence: int
    family: str
    source: str
    predecessor: int | None
    scheduled_by: int | None
    actor: str | None


@dataclass(frozen=True)
class Report:
    stage: str
    stop_reason: str
    goal_status: str
    steps_completed: int
    requested_step: int | None
    published: tuple[Occurrence, ...] = ()
    detail: str = ""


def exact(row, required, optional=()):
    if type(row) is not dict or not set(required) <= set(row) <= set(required) | set(optional):
        raise WitnessError("witness_invalid", "missing or unsupported witness fields")
    return row


def actor_selector(value):
    if type(value) is str and value:
        return
    exact(value, {"formed"})
    row = exact(value["formed"], {"source", "ordinal"})
    if (
        type(row["source"]) is not str
        or not row["source"]
        or type(row["ordinal"]) is not int
        or row["ordinal"] < 1
    ):
        raise WitnessError("witness_invalid", "formed identity needs source and positive ordinal")


def case_data(value, *, depth=0, active=None, remaining=None):
    active = set() if active is None else active
    remaining = [65536] if remaining is None else remaining
    remaining[0] -= 1
    if depth > 64 or remaining[0] < 0:
        raise WitnessError("witness_budget", "witness data depth/node budget exceeded")
    if type(value) in (str, int, bool, type(None)):
        return
    if type(value) not in (dict, list):
        raise WitnessError("witness_invalid", "witness data needs closed YAML values")
    if id(value) in active:
        raise WitnessError("witness_invalid", "witness data contains a cycle")
    active.add(id(value))
    try:
        if type(value) is dict and any(type(key) is not str for key in value):
            raise WitnessError("witness_invalid", "witness field names must be text")
        for child in value.values() if type(value) is dict else value:
            case_data(child, depth=depth + 1, active=active, remaining=remaining)
    finally:
        active.remove(id(value))


def validate_case(case):
    case_data(case)
    exact(case, {"schema", "budget", "steps", "expect"})
    if case["schema"] != "nomos.witness" or type(case["budget"]) is not int or case["budget"] < 1:
        raise WitnessError("witness_invalid", "nomos.witness and positive control budget required")
    if type(case["steps"]) is not list or type(case["expect"]) is not list:
        raise WitnessError("witness_invalid", "steps and expect must be finite lists")
    for step in case["steps"]:
        if type(step) is not dict:
            raise WitnessError("witness_invalid", "a step must be a declared operation")
        operations = set(step) & {"action", "next", "defer", "advance", "strategy", "cancel"}
        if len(operations) != 1:
            raise WitnessError("witness_invalid", "each step needs exactly one operation")
        op = next(iter(operations))
        if op == "action":
            exact(step, {"action", "actor"}, {"inputs", "request", "expect_result"})
            actor_selector(step["actor"])
            if (
                type(step["action"]) is not str
                or not step["action"]
                or type(step.get("inputs", {})) is not dict
            ):
                raise WitnessError("witness_invalid", "Action needs a name and named inputs")
            if "request" in step:
                exact(step["request"], {"process", "point"}, {"ordinal"})
        elif op == "next":
            exact(step, {op})
            exact(step[op], {"status"}, {"actor"})
            if step[op]["status"] not in ("ready", "due", "idle", "closed"):
                raise WitnessError("witness_invalid", "unknown schedule status")
            if "actor" in step[op]:
                actor_selector(step[op]["actor"])
        elif op in ("defer", "strategy"):
            exact(step, {op})
            actor_selector(step[op])
        elif op == "advance":
            exact(step, {op})
            if step[op] is not None and (type(step[op]) is not int or step[op] < 0):
                raise WitnessError("witness_invalid", "advance needs a nonnegative time or null")
        else:
            exact(step, {op})
            exact(step[op], {"actor", "activity"}, {"ordinal"})
            actor_selector(step[op]["actor"])
    for goal in case["expect"]:
        exact(goal, set(), {"actor", "ending", "published"})
        if len(goal) != 1:
            raise WitnessError("witness_invalid", "one assertion kind required")
        if "actor" in goal:
            row = exact(goal["actor"], {"name", "fields"})
            actor_selector(row["name"])
            if type(row["fields"]) is not dict:
                raise WitnessError("witness_invalid", "actor fields must be a mapping")
        elif "ending" in goal:
            row = exact(goal["ending"], {"actor", "status"}, {"value"})
            actor_selector(row["actor"])
            if row["status"] not in ("active", "draining", "closed"):
                raise WitnessError("witness_invalid", "unknown world ending status")
        else:
            row = exact(goal["published"], {"source"}, {"count"})
            if type(row["source"]) is not str or not row["source"]:
                raise WitnessError("witness_invalid", "published source must be named")
            if "count" in row and (type(row["count"]) is not int or row["count"] < 0):
                raise WitnessError("witness_invalid", "published count must be nonnegative")
    return deepcopy(case)


def formed_reference(session, selector, *, kind=None):
    actor_selector(selector)
    row = selector["formed"]
    sources = {item.reference: item.source for item in session.history()}
    matches = [
        item.reference
        for item in session.inspect_individuals()
        if sources.get(item.formed_by) == row["source"]
        and (kind is None or session.program.schemas[item.reference.sort].kind == kind)
    ]
    if row["ordinal"] > len(matches):
        raise WitnessError("identity_unavailable", "requested actual formed individual is absent")
    return matches[row["ordinal"] - 1]


def actor(session, selector):
    actor_selector(selector)
    if type(selector) is str:
        if selector not in dict(session.program.actors):
            raise WitnessError("unknown_actor", "Actor is not an opening control symbol")
        return selector
    reference = formed_reference(session, selector, kind="person")
    return next(
        control
        for control in session.actor_controllers()
        if session.actor_reference(control) == reference
    )


def decode(session, codec, name, value):
    def reference(raw, sort):
        if type(raw) is dict and set(raw) == {"formed"}:
            return formed_reference(session, raw, kind=session.program.schemas[sort].kind)
        if type(raw) is not dict or len(raw) != 1 or not set(raw) <= {"actor", "object"}:
            raise WitnessError("invalid_input", "reference needs actor/object/formed selector")
        kind, symbol = next(iter(raw.items()))
        if type(symbol) is not str:
            raise WitnessError("invalid_input", "reference symbol must be text")
        if symbol not in dict(session.symbols):
            raise WitnessError("identity_unavailable", "opening reference symbol is absent")
        return codec.references.resolve("person" if kind == "actor" else "object", symbol)

    return codec.decode(name, value, reference=reference)


def encode(session, codec, name, value):
    def reference(ref):
        if ref in dict(session.symbols).values():
            return codec.reference(ref)
        individual = next(item for item in session.inspect_individuals() if item.reference == ref)
        source = session.history()[individual.formed_by - 1].source
        kind = session.program.schemas[ref.sort].kind
        same = [
            item.reference
            for item in session.inspect_individuals()
            if item.formed_by is not None
            and session.history()[item.formed_by - 1].source == source
            and session.program.schemas[item.reference.sort].kind == kind
        ]
        return {"formed": {"source": source, "ordinal": same.index(ref) + 1}}

    return codec.encode(name, value, reference=reference)


def matches(session, codec, type_name, value, pattern):
    def overlay(actual, expected):
        if type(actual) is dict and type(expected) is dict:
            return {
                **actual,
                **{key: overlay(actual.get(key), item) for key, item in expected.items()},
            }
        return expected

    # Fill partial records, then compare generated nominal values, not list wire order.
    wire = overlay(encode(session, codec, type_name, value), pattern)
    try:
        expected = decode(session, codec, type_name, wire)
    except ValueBindingError as error:
        if error.diagnostic.code == "ValueBudget":
            raise
        return False
    return type(value) is type(expected) and value == expected


def unique(rows, ordinal=None):
    if ordinal is not None:
        if type(ordinal) is not int or ordinal < 1:
            raise WitnessError("invalid_selector", "ordinal must be a positive integer")
        rows = rows[ordinal - 1 : ordinal]
    if not rows:
        raise WitnessError("choice_unavailable", "no matching current choice")
    if len(rows) != 1:
        raise WitnessError("ambiguous_choice", "multiple current choices match")
    return rows[0]


def choices(session, controlled, name, supplied, request):
    form = session.choice_form(controlled, name, request=request)
    fields = {field.name: field for field in form.fields}
    if set(supplied) != set(fields):
        raise WitnessError("invalid_input", "named inputs must match all non-derived formals")
    codec = session.values(controlled)
    explicit = {
        key: decode(session, codec, fields[key].type_name, raw)
        for key, raw in supplied.items()
        if not (type(raw) is dict and set(raw) == {"pick"})
    }

    def with_explicit(selected):
        # Let the generated form resolve derived dependencies and later explicit values.
        selected = dict(selected)
        while True:
            current = session.choice_form(controlled, name, selected, request=request)
            more = {
                field.name: explicit[field.name]
                for field in current.fields
                if field.ready and field.name in explicit
            }
            if not more:
                return selected
            selected.update(more)

    chosen = with_explicit({})
    while True:
        form = session.choice_form(controlled, name, chosen, request=request)
        if form.complete:
            return chosen
        field = next((field for field in form.fields if field.ready), None)
        if field is None:
            raise WitnessError("choice_unavailable", "no input has satisfied dependencies")
        raw = supplied[field.name]
        if type(raw) is not dict or set(raw) != {"pick"} or field.kind != "member":
            raise WitnessError("invalid_input", "pick requires a finite member input")
        candidates = []
        for value in field.pool:
            pattern = raw["pick"]
            if pattern != {} and not matches(session, codec, field.type_name, value, pattern):
                continue
            try:
                trial = with_explicit({**chosen, field.name: value})
                session.choice_form(controlled, name, trial, request=request)
            except AdmissionError as error:
                if error.code not in {"InvalidChoice", "NotAdmitted"}:
                    raise
                continue
            candidates.append(value)
        chosen = with_explicit({**chosen, field.name: unique(candidates)})


def goals_met(session, goals):
    sources = {
        *(definition.source for definition in session.program.actions.values()),
        *session.program.reactions,
        *(
            definition.source
            for definition in (
                ()
                if session.program.time is None
                else (*session.program.time.activities, *session.program.time.periodic)
            )
        ),
        *(
            definition.cancel.source
            for definition in (
                () if session.program.time is None else session.program.time.activities
            )
            if definition.cancel is not None
        ),
    }
    for goal in goals:
        if "published" in goal:
            row = goal["published"]
            if row["source"] not in sources:
                raise WitnessError(
                    "unsupported_goal", "published source is not selected by Program"
                )
            count = sum(item.source == row["source"] for item in session.history())
            if (count != row["count"]) if "count" in row else count == 0:
                return False
            continue
        row = goal.get("actor", goal.get("ending"))
        controlled = actor(session, row["name"] if "actor" in goal else row["actor"])
        codec = session.values(controlled)
        if "ending" in goal:
            ending = session.ending(controlled)
            if ending["status"] != row["status"]:
                return False
            if "value" in row:
                if not ending["available"]:
                    return False
                if not matches(
                    session,
                    codec,
                    session.program.terminal.result_type,
                    ending["value"],
                    row["value"],
                ):
                    return False
        else:
            state = session.read(controlled)
            schema = session.program.schemas[session.actor_reference(controlled).sort]
            kinds = dict(schema.fields)
            if set(row["fields"]) - set(state):
                raise WitnessError("unsupported_goal", "assertion field is outside Actor's view")
            for name, expected in row["fields"].items():
                if not matches(session, codec, kinds[name], state[name], expected):
                    return False
    return True


def execute(session, step, schedule):
    if "next" in step:
        result = session.next_opportunity()
        row = step["next"]
        if result.status != row["status"]:
            raise WitnessError("opportunity_mismatch", "schedule status differs from witness")
        if result.opportunity is not None:
            controlled = result.opportunity.actor
            schedule[controlled] = result.opportunity
            if "actor" in row and controlled != actor(session, row["actor"]):
                raise WitnessError("opportunity_mismatch", "another Actor holds the opportunity")
        elif "actor" in row:
            raise WitnessError("opportunity_mismatch", "result contains no Actor opportunity")
        return
    if "advance" in step:
        result = session.advance(step["advance"])
    else:
        selector = (
            step["actor"]
            if "action" in step
            else step["cancel"]["actor"]
            if "cancel" in step
            else step.get("defer", step.get("strategy"))
        )
        controlled = actor(session, selector)
        if session.ending(controlled)["status"] == "closed":
            raise WitnessError("world_closed", "witness has an unexecuted suffix after closure")
        if "defer" in step:
            if controlled not in schedule:
                raise WitnessError("opportunity_unavailable", "defer needs an issued opportunity")
            result = session.defer_opportunity(controlled, schedule.pop(controlled))
        elif "strategy" in step:
            decision = session.propose(controlled)
            if decision.proposal is None:
                raise WitnessError("choice_unavailable", "local strategy: " + decision.status)
            result = session.submit_proposal(controlled, decision.proposal)
        elif "cancel" in step:
            row = step["cancel"]
            offer = unique(
                [
                    offer
                    for offer in session.activity_offers(controlled)
                    if offer.name == row["activity"]
                ],
                row.get("ordinal"),
            )
            result = session.cancel_activity(controlled, offer)
        else:
            request = None
            if "request" in step:
                row = step["request"]
                request = unique(
                    [
                        r
                        for r in session.requests(controlled)
                        if r.process == row["process"] and r.point == row["point"]
                    ],
                    row.get("ordinal"),
                )
            supplied = choices(session, controlled, step["action"], step.get("inputs", {}), request)
            result = session.act(controlled, step["action"], supplied, request=request)
        if result.status == "rejected":
            raise WitnessError("admission_rejected", str(result.code))
        if "expect_result" in step:
            definition = session.program.actions[step["action"]]
            if not matches(
                session,
                session.values(),
                definition.result_type,
                result.feedback,
                step["expect_result"],
            ):
                raise WitnessError(
                    "expectation_failed", "published result differs from expectation"
                )
    if result.status in ("closed", "rejected"):
        raise WitnessError(
            "world_closed" if result.status == "closed" else "control_rejected",
            "control operation did not publish",
        )


def trace(session):
    names = {
        session.actor_reference(control): str(control) for control in session.actor_controllers()
    }
    definitions = {definition.source: definition for definition in session.program.actions.values()}
    if session.program.time is not None:
        definitions.update(
            (definition.cancel.source, definition.cancel)
            for definition in session.program.time.activities
            if definition.cancel is not None
        )
    return tuple(
        Occurrence(
            row.reference,
            row.family,
            row.source,
            row.predecessor,
            row.due.key.formation
            if row.due is not None and type(row.due.key) is ActivityKey
            else None,
            names.get(dict(row.participants).get(definitions[row.source].actor_parameter))
            if row.source in definitions
            else None,
        )
        for row in session.history()
    )


CONTROL_ERRORS = (AdmissionError, ValueBindingError, ExpressionError, ValueError)


def check_witness(program, assets, case, *, controllers=None):
    if type(program) is not CompiledProgram:
        return Report(
            "artifact",
            "unsupported_program",
            "unknown",
            0,
            None,
            detail="generated CompiledProgram required",
        )
    try:
        case = validate_case(case)
    except (ValueError, TypeError) as error:
        return Report(
            "input",
            getattr(error, "code", "witness_invalid"),
            "unknown",
            0,
            None,
            detail=str(error)[:4096],
        )
    try:
        session = program.start(assets, controllers=controllers)
    except (SettlementDefect, *CONTROL_ERRORS) as error:
        return Report("start", "start_rejected", "unknown", 0, None, detail=str(error)[:4096])

    def report(reason, completed, requested, detail="", *, defective=False):
        try:
            status = (
                "unknown"
                if defective
                else ("met" if goals_met(session, case["expect"]) else "not_met_within_bound")
            )
        except CONTROL_ERRORS as error:
            status = "unknown"
            detail = detail or str(error)
            if reason == "witness_completed":
                reason = "unsupported_goal"
        return Report("run", reason, status, completed, requested, trace(session), detail[:4096])

    schedule = {}
    for index, step in enumerate(case["steps"], 1):
        if index > case["budget"]:
            return report("budget_exhausted", index - 1, index)
        try:
            execute(session, step, schedule)
        except SettlementDefect as error:
            return report("settlement_defect", index - 1, index, str(error), defective=True)
        except WitnessError as error:
            return report(error.code, index - 1, index, str(error))
        except CONTROL_ERRORS as error:
            code = getattr(error, "code", getattr(getattr(error, "diagnostic", None), "code", ""))
            return report(
                "world_closed" if code == "WorldClosed" else "control_rejected",
                index - 1,
                index,
                str(error),
            )
    result = report("witness_completed", len(case["steps"]), None)
    if result.goal_status != "met" and result.stop_reason == "witness_completed":
        return Report(
            result.stage,
            "goal_not_met",
            result.goal_status,
            result.steps_completed,
            None,
            result.published,
            result.detail,
        )
    return result
