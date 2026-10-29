"""Budgeted, detached value construction; never enumerates complete value products."""

from dataclasses import dataclass, field
from types import MappingProxyType

from nomos_cognition.planning.search import _Stop
from nomos_cognition.planning.values import Binding, ConstructDraft

from .ordering import canonical
from .planning_preparation import PreparedMembers


@dataclass(frozen=True)
class Construction:
    kind: str
    expressions: tuple
    children: tuple = ()
    make: object | None = None
    prefix: str | None = None
    _expressions: object = field(init=False, repr=False, compare=False)
    _children: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_expressions", MappingProxyType(dict(self.expressions)))
        object.__setattr__(self, "_children", MappingProxyType(dict(self.children)))


@dataclass(frozen=True)
class Step:
    kind: str
    value: object = None


@dataclass(frozen=True)
class MemberOptions:
    pool: PreparedMembers
    start: int
    stop: int
    can_stop: bool = False

    def __len__(self):
        return int(self.can_stop) + self.stop - self.start

    def __getitem__(self, index):
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        if self.can_stop:
            if index == 0:
                return Step("stop")
            index -= 1
        return Step("member", self.pool.values[self.start + index])

    def __contains__(self, step):
        if type(step) is not Step:
            return False
        if step.kind == "stop":
            return self.can_stop and step.value is None
        if step.kind != "member":
            return False
        try:
            index = self.pool.ranks.get(step.value, -1)
        except TypeError:
            return False
        return self.start <= index < self.stop


@dataclass(frozen=True)
class ConstructionPreparation:
    decisions: int
    evaluations: int
    ready: bool
    choices: int
    sealed: bool


@dataclass(frozen=True)
class _Debit:
    amount: int


@dataclass(frozen=True)
class _Evaluate:
    function: object
    scope: dict


@dataclass(frozen=True)
class _Construct:
    function: object
    fields: dict


class _Choice(Exception):
    def __init__(self, options):
        self.options = options


class _Dead(Exception):
    pass


class ConstructionChoices:
    def __init__(self, field, recipe, draft, environment, evaluate):
        self.field, self.draft = field, draft
        self.options, self.result = (), draft.result
        self.prepared, self._failed = bool(draft.result), False
        self._evaluations = 0
        self._evaluate = None if self.prepared else evaluate
        self._pending = None
        self._iterator = None if self.prepared else self._traverse(recipe, environment)

    def _traverse(self, recipe, environment):
        draft = self.draft
        position = 0

        def choose(options):
            nonlocal position
            if position == len(draft.steps):
                raise _Choice(options)
            step = draft.steps[position]
            position += 1
            if step not in options:
                raise ValueError("construction decisions do not match their current recipe")
            return step

        def expression(node, label, scope):
            return (yield _Evaluate(node._expressions[label], scope))

        def allowed(node, scope):
            if "when" not in node._expressions:
                return True
            return (yield from expression(node, "when", scope))

        def visit(node, scope, *, condition_checked=False):
            yield _Debit(1)
            if not condition_checked and not (yield from allowed(node, scope)):
                raise _Dead
            kind = node.kind
            if kind == "value":
                return (yield from expression(node, "value", scope))
            if kind == "choose":
                pool = yield from expression(node, "choose", scope)
                if type(pool) is not PreparedMembers:
                    raise ValueError("construction requires prepared member domains")
                yield _Debit(1)
                choice = choose(MemberOptions(pool, 0, len(pool.values)))
                return choice.value
            if kind == "fields":
                fields, inner = {}, dict(scope)
                for name, child in node.children:
                    fields[name] = yield from visit(child, inner)
                    inner[name] = fields[name]
                return (yield _Construct(node.make, fields))
            if kind == "cases":
                choices = []
                for name, child in node.children:
                    yield _Debit(1)
                    if (yield from allowed(child, scope)):
                        choices.append(Step("case", name))
                yield _Debit(max(1, len(choices)))
                selected = choose(tuple(choices))
                # Availability was checked in this same captured pure scope.
                return (
                    yield from visit(node._children[selected.value], scope, condition_checked=True)
                )
            if kind not in {"sequence", "set", "subset"}:
                raise ValueError("unknown construction recipe")
            minimum = yield from expression(node, "min", scope)
            maximum = yield from expression(node, "max", scope)
            if minimum < 0 or maximum < minimum:
                raise _Dead
            values = []
            pool = None
            start, previous_key = 0, None
            if kind == "subset":
                members = yield from expression(node, "pool", scope)
                if type(members) is not PreparedMembers:
                    raise ValueError("construction requires prepared member domains")
                pool = members
                if minimum > len(pool.values):
                    raise _Dead
                maximum = min(maximum, len(pool.values))
            while True:
                yield _Debit(1)
                can_stop, can_append = len(values) >= minimum, len(values) < maximum
                count = int(can_stop) + int(can_append)
                if can_append and kind == "subset":
                    if values:
                        start = pool.ranks[values[-1]] + 1
                    # Keep enough later members available to reach the lower bound.
                    stop = len(pool.values) - max(0, minimum - len(values) - 1)
                    count = int(can_stop) + max(0, stop - start)
                yield _Debit(1 if kind == "subset" else max(1, count))
                if kind == "subset":
                    options = MemberOptions(
                        pool, start, max(start, stop) if can_append else start, can_stop
                    )
                else:
                    options = (Step("stop"),) if can_stop else ()
                    if can_append:
                        options = (*options, Step("append"))
                step = choose(options)
                if step.kind == "stop":
                    return tuple(values) if kind == "sequence" else frozenset(values)
                if kind == "subset":
                    values.append(step.value)
                else:
                    inner = dict(scope)
                    if node.prefix is not None:
                        inner[node.prefix] = (
                            tuple(values) if kind == "sequence" else frozenset(values)
                        )
                    value = yield from visit(node.children[0][1], inner)
                    if kind == "set" and values:
                        key = canonical(value)
                        if previous_key is None:
                            previous_key = canonical(values[-1])
                        if key <= previous_key:
                            raise _Dead
                        previous_key = key
                    values.append(value)

        result = yield from visit(recipe, environment)
        if position != len(draft.steps):
            raise ValueError("construction contains trailing decisions")
        return result

    def _release(self):
        if self._iterator is not None:
            self._iterator.close()
        self._iterator = self._pending = None
        self._evaluate = None

    def _advance(self, value=None):
        try:
            self._pending = self._iterator.send(value)
        except _Choice as choice:
            self.options = choice.options
            self.prepared = True
        except _Dead:
            self.prepared = True
        except StopIteration as complete:
            self.result = (complete.value,)
            self.prepared = True
        except BaseException as failure:
            self._failed = True
            self._release()
            if isinstance(failure, _Stop):
                raise ValueError("construction stopped outside a budgeted request") from failure
            raise
        if self.prepared:
            self._release()

    def preparation(self):
        return ConstructionPreparation(
            len(self.draft.steps),
            self._evaluations,
            self.prepared,
            len(self.options),
            bool(self.result),
        )

    def _prepare(self, work):
        if self._failed:
            raise ValueError("failed construction cannot continue")
        if self._pending is None:
            self._advance()
        while not self.prepared:
            request = self._pending
            try:
                if type(request) is _Debit:
                    work.spend(request.amount)
                    value = None
                elif type(request) is _Evaluate:
                    value = self._evaluate(request.function, request.scope, work)
                    self._evaluations += 1
                else:
                    value = request.function(request.fields)
            except _Stop:
                raise
            except BaseException:
                self._failed = True
                self._release()
                raise
            self._advance(value)

    def at(self, partial, cursor, work):
        if not self.prepared:
            self._prepare(work)
        work.spend()
        if self.result:
            if cursor:
                return None
            value = (
                self.result[0]
                if self.draft.result
                else ConstructDraft(
                    self.draft.steps,
                    self.result,
                )
            )
        elif cursor < len(self.options):
            value = ConstructDraft((*self.draft.steps, self.options[cursor]))
        else:
            return None
        arguments = dict(partial.arguments)
        arguments[self.field] = value
        return Binding(partial.schema, tuple(arguments.items()))
