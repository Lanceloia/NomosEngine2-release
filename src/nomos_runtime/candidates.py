"""One bounded, admitted candidate construction path for all controller policies."""

import json
from dataclasses import dataclass
from itertools import combinations, permutations, product
from types import MappingProxyType

from . import ordering
from .entities import Reference
from .errors import AdmissionError, SettlementDefect


@dataclass(frozen=True)
class CandidateRule:
    """Prepare staged local evaluators once per frame opportunity."""

    ability: str
    supplied: tuple
    choices: tuple
    evaluate: object
    explain: object
    predict: object
    prediction_subject: object
    value_names: tuple
    meaning_features: tuple
    prepare: object = None
    input_types: tuple = ()
    planning: object = None
    prediction_when: object = None
    prediction_score_mode: str = "replace"


@dataclass(frozen=True)
class StrategyDefinition:
    selector: str
    controller: str
    tie: str
    candidates: tuple
    cognition: tuple
    semantics: object = None
    feedback: tuple = ()
    participation: tuple | None = None
    consideration: int | None = None
    tunable: tuple = ()


@dataclass(frozen=True)
class ControllerLibrary:
    program: object
    strategies: tuple
    terms: object = None
    planning: object = None
    bindings: tuple = ()

    def bind(self, values):
        """Return a pre-Start immutable override for explicitly tunable parameters.

        Exact type and selected-strategy checks deliberately happen at Start,
        when the generated world's current type codecs and reference scope are
        available. JSON storage prevents caller mutation after binding.
        """
        if type(values) is not dict or set(values) - set(dict(self.program.actors)):
            raise ValueError("controller bindings need known opening Actor names")
        merged = {actor: dict(items) for actor, items in self.bindings}
        for actor, parameters in values.items():
            if type(parameters) is not dict or not parameters:
                raise ValueError("each controller binding needs named parameter values")
            target = merged.setdefault(actor, {})
            for name, value in parameters.items():
                if type(name) is not str:
                    raise ValueError("controller parameter names need text")
                try:
                    target[name] = json.dumps(value, sort_keys=True, separators=(",", ":"))
                except (TypeError, ValueError) as error:
                    raise ValueError("controller parameter needs plain wire data") from error
        return ControllerLibrary(
            self.program,
            self.strategies,
            self.terms,
            self.planning,
            tuple((actor, tuple(sorted(items.items()))) for actor, items in sorted(merged.items())),
        )

    def materialize(self, session):
        """Decode configured overrides once into the Session's immutable opening state."""
        result = {}
        codec = session.values()
        for actor, items in self.bindings:
            strategy = selected_strategy(session, actor)
            if strategy is None:
                raise ValueError("controller binding has no selected strategy")
            types = dict(strategy.tunable)
            values = {}
            for name, wire in items:
                if name not in types:
                    raise ValueError("controller binding names a non-tunable parameter")
                values[name] = codec.decode(types[name], json.loads(wire))
            result[actor] = MappingProxyType(values)
        return MappingProxyType(result)


@dataclass(frozen=True)
class BoundCandidate:
    rule: int
    opportunity: int
    ability: str
    choices: tuple
    values: tuple
    request: object
    record: object
    binding: object
    epoch: object

    @property
    def key(self):
        return self.ability, self.opportunity, ordering.canonical(tuple(sorted(self.choices)))


@dataclass(frozen=True)
class CandidateEnumeration:
    strategy: StrategyDefinition
    controller: Reference
    status: str
    items: tuple[BoundCandidate, ...]
    work: int


def selected_strategy(session, actor):
    reference = session._actor(actor)
    return next(
        (
            definition
            for definition in (
                () if session.controllers is None else session.controllers.strategies
            )
            if definition.selector == "actor"
            and definition.controller == actor
            or definition.selector == "kind"
            and session.references.accepts(definition.controller, reference.sort)
        ),
        None,
    )


def enumerate_candidates(session, actor, budget, actions):
    from .information import candidate_input_batch

    with candidate_input_batch(session):
        return _enumerate_candidates(session, actor, budget, actions)


def _enumerate_candidates(session, actor, budget, actions):
    from .processes import request_binding
    from .scheduling import has_opportunity

    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot propose during settlement or after fatal")
    if type(budget) is not int or budget < 1:
        raise AdmissionError("InvalidBudget", "positive candidate budget required")
    if actions is not None and (
        type(actions) is not tuple
        or any(type(a) is not str or a not in session.program.actions for a in actions)
        or len(actions) != len(set(actions))
    ):
        raise AdmissionError("InvalidStrategyScope", "distinct selected Actions required")
    controller = session._actor(actor)
    strategy = selected_strategy(session, actor)
    if strategy is None:
        raise AdmissionError("NoStrategy", "Actor has no selected strategy")
    if session.ending(actor)["status"] == "closed":
        return CandidateEnumeration(strategy, controller, "closed", (), 0)
    if not has_opportunity(session, controller):
        return CandidateEnumeration(strategy, controller, "no_opportunity", (), 0)
    if any(not session.cognition_value(controller, name).complete for name in strategy.cognition):
        return CandidateEnumeration(strategy, controller, "cognition_pending", (), 0)
    selected = {r.ability for r in strategy.candidates if actions is None or r.ability in actions}
    eligible = []
    for definition in session.program.actions.values():
        if (
            definition.name not in selected
            or not session.references.accepts(definition.actor_sort, controller.sort)
            or definition.process is not None
            and definition.process.point != "begin"
        ):
            continue
        try:
            session.choice_form(actor, definition.name)
        except AdmissionError as error:
            if error.code in {
                "NotAdmitted",
                "InvalidDomain",
                "InvalidChoice",
                "StagePending",
                "ProcessPending",
                "WorldClosed",
                "WorldDraining",
            }:
                continue
            raise
        eligible.append((definition.name, None))
    eligible.extend(
        (f"{r.process}.{r.point}", r)
        for r in session.requests(actor)
        if f"{r.process}.{r.point}" in selected
    )
    work, candidates = 0, []

    def tick():
        nonlocal work
        work += 1
        if work > budget:
            raise AdmissionError("CandidateBudget", "finite candidate construction budget exceeded")

    def visit(rule, request, record, choices):
        tick()
        if len(choices) == len(rule.input_types):
            # A complete choice is checked by the real admission path below.
            yield choices
            return
        try:
            form = session.choice_form(actor, rule.ability, choices, request=request)
        except AdmissionError as error:
            if error.code in {"NotAdmitted", "InvalidChoice", "InvalidDomain"}:
                return
            raise
        field = next(f for f in form.fields if f.ready)
        if field.name in rule.supplied:
            values = (rule.evaluate(session, controller, form.values, record, field.name),)
        elif field.name in rule.choices:
            values = sorted(
                rule.evaluate(session, controller, form.values, record, field.name),
                key=ordering.canonical,
            )
        elif field.kind == "enter":
            raise AdmissionError("MissingBinding", "typed-entry strategy needs a supplied value")
        else:
            pool = sorted(field.pool, key=ordering.canonical)
            if field.kind == "member":
                values = pool
            elif field.kind == "subset":
                values = (
                    frozenset(group)
                    for count in range(field.minimum, min(field.maximum, len(pool)) + 1)
                    for group in combinations(pool, count)
                )
            else:
                if field.length > session.limits.value.items:
                    raise AdmissionError("CandidateBudget", "bounded candidate sequence required")
                values = (
                    product(pool, repeat=field.length)
                    if field.repetition == "allow"
                    else permutations(pool, field.length)
                )
        for value in values:
            tick()
            yield from visit(rule, request, record, {**choices, field.name: value})

    for rule_index, rule in enumerate(strategy.candidates):
        for opportunity, (ability, request) in enumerate(eligible):
            if ability != rule.ability or actions is not None and ability not in actions:
                continue
            binding = None if request is None else request_binding(session, actor, request)
            _, _, record = session._entry(actor, ability, binding)
            for choices in visit(rule, request, record, {}):
                try:
                    _, _, participants, _, epoch = session._admit(actor, ability, choices, binding)
                except AdmissionError as error:
                    if error.code in {
                        "NotAdmitted",
                        "InsufficientResource",
                        "AliasedWrite",
                        "InvalidChoice",
                        "StagePending",
                    }:
                        continue
                    raise
                candidates.append(
                    BoundCandidate(
                        rule_index,
                        opportunity,
                        ability,
                        tuple(choices.items()),
                        tuple((name, participants[name]) for name in rule.value_names),
                        request,
                        record,
                        binding,
                        epoch,
                    )
                )
    return CandidateEnumeration(
        strategy, controller, "complete" if candidates else "no_candidate", tuple(candidates), work
    )
