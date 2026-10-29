"""Values for partial action construction and observation-conditioned plans."""

from collections.abc import Hashable
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol


def _name(value):
    if type(value) is not str or not value:
        raise ValueError("planning labels must be nonempty strings")


def _carriers(value):
    return value if type(value) is tuple else (value,)


@dataclass(frozen=True)
class Basis:
    actor: str
    view: str
    semantics: str
    experience: str

    def __post_init__(self):
        for value in vars(self).values():
            _name(value)


@dataclass(frozen=True)
class Parameter:
    name: str
    value_type: type | tuple[type, ...]
    element_type: type | tuple[type, ...] | None = None
    structured: bool = False

    def __post_init__(self):
        _name(self.name)
        carriers = _carriers(self.value_type)
        if not carriers or any(not isinstance(t, type) for t in carriers):
            raise ValueError("a planning parameter needs a nominal Python value type")
        if type(self.structured) is not bool or self.structured and self.element_type is not None:
            raise ValueError("structured construction and subset drafts are distinct protocols")
        if self.element_type is not None:
            elements = _carriers(self.element_type)
            if (
                self.value_type is not frozenset
                or not elements
                or any(not isinstance(t, type) for t in elements)
            ):
                raise ValueError("subset parameters need frozenset and nominal element types")


@dataclass(frozen=True)
class SetDraft:
    """An unfinished subset, never a complete argument or a world value."""

    members: frozenset

    def __post_init__(self):
        if type(self.members) is not frozenset:
            raise ValueError("a subset draft needs immutable members")


@dataclass(frozen=True)
class ConstructDraft:
    """Append-only construction decisions, optionally sealed with one completed value."""

    steps: tuple = ()
    result: tuple = ()

    def __post_init__(self):
        if type(self.steps) is not tuple or type(self.result) is not tuple or len(self.result) > 1:
            raise ValueError("construction drafts need immutable decisions and at most one result")
        hash((self.steps, self.result))


def is_draft(value):
    return type(value) in (SetDraft, ConstructDraft)


@dataclass(frozen=True)
class Schema:
    name: str
    parameters: tuple[Parameter, ...] = ()

    def __post_init__(self):
        _name(self.name)
        if (
            type(self.parameters) is not tuple
            or any(type(p) is not Parameter for p in self.parameters)
            or len({p.name for p in self.parameters}) != len(self.parameters)
        ):
            raise ValueError("a schema needs distinct, typed parameters")


@dataclass(frozen=True)
class Binding:
    schema: Schema
    arguments: tuple[tuple[str, Hashable], ...] = ()

    def __post_init__(self):
        if type(self.schema) is not Schema or type(self.arguments) is not tuple:
            raise ValueError("a binding needs a schema and immutable arguments")
        if any(type(a) is not tuple or len(a) != 2 for a in self.arguments):
            raise ValueError("invalid argument pair")
        parameters = {p.name: p for p in self.schema.parameters}
        names = []
        for name, value in self.arguments:
            if type(name) is not str or name not in parameters:
                raise ValueError("argument does not match its declared nominal type")
            parameter = parameters[name]
            if type(value) is ConstructDraft:
                if not parameter.structured:
                    raise ValueError("construction draft needs its declared parameter protocol")
                names.append(name)
                continue
            draft = type(value) is SetDraft
            carriers = _carriers(parameter.value_type)
            if (
                (draft and parameter.element_type is None)
                or (not draft and type(value) not in carriers)
                or (
                    parameter.element_type is not None
                    and any(
                        type(v) not in _carriers(parameter.element_type)
                        for v in (value.members if draft else value)
                    )
                )
            ):
                raise ValueError("argument does not match its declared nominal type")
            hash(value)
            names.append(name)
        if len(set(names)) != len(names):
            raise ValueError("duplicate argument")

    @property
    def missing(self):
        bound = {name for name, value in self.arguments if not is_draft(value)}
        return tuple(p for p in self.schema.parameters if p.name not in bound)


@dataclass(frozen=True)
class Action:
    binding: Binding

    def __post_init__(self):
        if type(self.binding) is not Binding or self.binding.missing:
            raise ValueError("an action intent must have complete typed arguments")


@dataclass(frozen=True)
class Scenario:
    state: Hashable
    probability: Fraction

    def __post_init__(self):
        hash(self.state)
        if type(self.probability) is not Fraction or self.probability <= 0:
            raise ValueError("scenario weights must be positive explicit fractions")


@dataclass(frozen=True)
class Belief:
    scenarios: tuple[Scenario, ...]

    def __post_init__(self):
        if (
            type(self.scenarios) is not tuple
            or not self.scenarios
            or any(type(s) is not Scenario for s in self.scenarios)
            or sum(s.probability for s in self.scenarios) != 1
        ):
            raise ValueError("a belief needs an explicitly normalized scenario distribution")


@dataclass(frozen=True)
class Outcome:
    state: Hashable
    observation: Hashable
    utility: Fraction
    probability: Fraction = Fraction(1)

    def __post_init__(self):
        hash(self.state)
        hash(self.observation)
        if (
            type(self.utility) is not Fraction
            or type(self.probability) is not Fraction
            or self.probability <= 0
        ):
            raise ValueError("predicted outcomes need explicit utility and positive probability")


@dataclass(frozen=True)
class Inapplicable:
    reason: str

    def __post_init__(self):
        _name(self.reason)


@dataclass(frozen=True)
class Branch:
    observation: Hashable
    continuation: "Plan | None"

    def __post_init__(self):
        hash(self.observation)
        if self.continuation is not None and type(self.continuation) is not Plan:
            raise ValueError("a branch needs a complete continuation or a terminal leaf")


@dataclass(frozen=True)
class Plan:
    action: Action
    branches: tuple[Branch, ...]

    def __post_init__(self):
        if (
            type(self.action) is not Action
            or type(self.branches) is not tuple
            or not self.branches
            or any(type(b) is not Branch for b in self.branches)
            or len({b.observation for b in self.branches}) != len(self.branches)
        ):
            raise ValueError("a plan needs a complete action and distinct observation branches")


@dataclass(frozen=True)
class Limits:
    work: int = 20000
    depth: int = 6
    nodes: int = 4000
    pending: int = 8000
    scenarios: int = 32
    outcomes: int = 16
    parameters: int = 32
    quantum: int = 256  # Initial service; completed same-family costs may raise later starts.

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError("planning limits must be positive integers")


@dataclass(frozen=True)
class Estimate:
    value: Fraction
    kind: str


@dataclass(frozen=True)
class Decision:
    status: str
    based_on: Basis
    intent: Action | None
    plan: Plan | None
    estimate: Estimate | None
    work: int
    nodes: int
    pending: int
    search_complete: bool
    stopped_by: str
    cutoffs: tuple[str, ...]


class Model(Protocol):
    """Trusted pure callbacks; each call must have bounded internal work.

    Cursors enumerate one local refinement at a time, not whole ground action lists.
    The caller supplies subjective scenarios, not a live world's hidden state.
    """

    def terminal(self, belief: Belief, goal: Hashable, work) -> Fraction | None: ...

    def schema_at(self, belief: Belief, goal: Hashable, cursor: int, work) -> Schema | None: ...

    def binding_at(
        self, belief: Belief, goal: Hashable, partial: Binding, cursor: int, work
    ) -> Binding | None: ...

    def predict(
        self, state: Hashable, goal: Hashable, action: Action, work
    ) -> tuple[Outcome, ...] | Inapplicable | None: ...
