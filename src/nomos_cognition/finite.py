"""Reference finite search over caller-supplied values and pure predicates."""

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType

from .state import Term


@dataclass(frozen=True)
class Variable:
    name: str
    type_name: str
    signature: str
    domain: tuple[Term, ...]

    def __post_init__(self):
        if (
            any(type(v) is not str or not v for v in (self.name, self.type_name, self.signature))
            or type(self.domain) is not tuple
            or any(
                type(v) is not Term or (v.name, v.signature) != (self.type_name, self.signature)
                for v in self.domain
            )
            or len(set(self.domain)) != len(self.domain)
        ):
            raise ValueError("finite variable needs a unique nominal domain")
        for value in self.domain:
            value.__post_init__()


@dataclass(frozen=True)
class Predicate:
    name: str
    variables: tuple[str, ...]
    evaluate: Callable

    def __post_init__(self):
        if (
            type(self.name) is not str
            or not self.name
            or type(self.variables) is not tuple
            or any(type(v) is not str or not v for v in self.variables)
            or len(set(self.variables)) != len(self.variables)
            or not callable(self.evaluate)
        ):
            raise ValueError("finite predicate needs explicit dependencies and pure evaluation")


@dataclass(frozen=True)
class Limits:
    work: int = 100000
    models: int = 4096
    variables: int = 64
    domain: int = 4096

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError("finite limits must be positive integers")


@dataclass(frozen=True)
class Answer:
    query: str
    entailed: bool
    possible: bool
    refuted: bool


@dataclass(frozen=True)
class Result:
    status: str
    models: tuple
    answers: tuple[Answer, ...]
    work: int
    examined: int
    found: int
    reason: str | None = None

    def __post_init__(self):
        if (
            self.status not in ("consistent", "inconsistent", "pending")
            or type(self.models) is not tuple
            or type(self.answers) is not tuple
            or any(type(n) is not int or n < 0 for n in (self.work, self.examined, self.found))
            or self.status == "pending"
            and (self.models or self.answers or not self.reason)
            or self.status == "inconsistent"
            and (self.models or self.answers or self.found)
            or self.status == "consistent"
            and (not self.models or self.found != len(self.models))
            or self.status != "pending"
            and self.reason is not None
        ):
            raise ValueError("invalid finite analysis outcome")
        for model in self.models:
            if (
                type(model) is not tuple
                or any(
                    type(v) is not tuple
                    or len(v) != 2
                    or type(v[0]) is not str
                    or type(v[1]) is not Term
                    for v in model
                )
                or len(dict(model)) != len(model)
            ):
                raise ValueError("finite model has invalid variable bindings")
            for _, value in model:
                value.__post_init__()
        if self.models and (
            len(set(self.models)) != len(self.models)
            or any(
                tuple(n for n, _ in m) != tuple(n for n, _ in self.models[0]) for m in self.models
            )
        ):
            raise ValueError("finite models have duplicate or inconsistent variable bindings")
        for answer in self.answers:
            if (
                type(answer) is not Answer
                or type(answer.query) is not str
                or not answer.query
                or any(
                    type(v) is not bool for v in (answer.entailed, answer.possible, answer.refuted)
                )
                or answer.entailed
                and not answer.possible
                or answer.refuted == answer.possible
            ):
                raise ValueError("invalid finite entailment")
        if len({q.query for q in self.answers}) != len(self.answers):
            raise ValueError("finite queries have duplicate names")


class _Exhausted(Exception):
    pass


def solve(variables, constraints, queries=(), *, limits=Limits()):
    """Exhaust the selected finite space; partial search never issues logical answers.

    The caller authenticates inputs and supplies pure, closed evaluators. This module
    neither reads owners nor interprets receipt authority, probability or role names.
    """
    if type(limits) is not Limits:
        raise ValueError("finite solver needs its exact limits")
    limits.__post_init__()
    if type(variables) is not tuple or any(type(v) is not Variable for v in variables):
        raise ValueError("finite solver needs declared variables")
    names = tuple(v.name for v in variables)
    if len(set(names)) != len(names):
        raise ValueError("finite variables must have unique names")
    for variable in variables:
        variable.__post_init__()
    for declarations in (constraints, queries):
        if type(declarations) is not tuple or any(type(p) is not Predicate for p in declarations):
            raise ValueError("finite formulas must be explicit predicates")
        if len({p.name for p in declarations}) != len(declarations):
            raise ValueError("finite predicates must have unique names")
        for predicate in declarations:
            predicate.__post_init__()
            if set(predicate.variables) - set(names):
                raise ValueError("finite formula refers to an undeclared variable")
    if len(variables) > limits.variables or any(len(v.domain) > limits.domain for v in variables):
        return Result("pending", (), (), 0, 0, 0, "domain_budget")

    # A formula runs once, at the earliest depth where all its dependencies exist.
    levels = [[] for _ in range(len(variables) + 1)]
    index = {name: i + 1 for i, name in enumerate(names)}
    for predicate in constraints:
        levels[max((index[n] for n in predicate.variables), default=0)].append(predicate)
    work = examined = found = 0
    models, hits = [], [0] * len(queries)
    assignment = {}

    def spend():
        nonlocal work
        if work >= limits.work:
            raise _Exhausted("work_budget")
        work += 1

    def check(predicate):
        spend()
        selected = MappingProxyType({n: assignment[n] for n in predicate.variables})
        value = predicate.evaluate(selected)
        if type(value) is not bool:
            raise ValueError("finite predicate must return an exact boolean")
        return value

    def search(depth):
        nonlocal examined, found
        spend()
        if depth == len(variables):
            examined += 1
        if any(not check(p) for p in levels[depth]):
            return
        if depth == len(variables):
            found += 1
            if found > limits.models:
                raise _Exhausted("model_budget")
            values = tuple((n, assignment[n]) for n in names)
            for i, query in enumerate(queries):
                hits[i] += int(check(query))
            models.append(values)
            return
        variable = variables[depth]
        for value in variable.domain:
            assignment[variable.name] = value
            search(depth + 1)
        assignment.pop(variable.name, None)

    try:
        search(0)
    except _Exhausted as error:
        return Result("pending", (), (), work, examined, found, str(error))
    if not models:
        return Result("inconsistent", (), (), work, examined, 0)
    answers = tuple(
        Answer(query.name, count == len(models), count > 0, count == 0)
        for query, count in zip(queries, hits, strict=True)
    )
    return Result("consistent", tuple(models), answers, work, examined, found)
