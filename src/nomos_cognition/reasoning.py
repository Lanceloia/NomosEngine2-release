"""Finite acyclic argument relations with explicit alternative supports."""

import hashlib
import json
from dataclasses import dataclass
from json.encoder import encode_basestring_ascii

from .state import Frame, Term

POLARITIES = ("support", "opposition")


def key(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def term_wire(term):
    return term.name, term.signature, term.wire


def digest(value):
    return hashlib.sha256(key(value).encode()).hexdigest()


def frame_key(frame):
    return (
        frame.rule,
        term_wire(frame.slot),
        tuple(vars(frame.ground).values()),
        None if frame.proposition is None else term_wire(frame.proposition),
        frame.support,
        frame.opposition,
        None if frame.appraisal is None else term_wire(frame.appraisal),
        frame.score,
    )


@dataclass(frozen=True)
class BaseArgument:
    id: str
    frame: Frame
    polarity: str

    @property
    def proposition(self):
        return self.frame.proposition

    @property
    def relation(self):
        return "base"


def base_arguments(model, holder, frames):
    arguments = []
    for frame in frames:
        for polarity, strength in zip(POLARITIES, (frame.support, frame.opposition), strict=True):
            if frame.proposition is not None and strength:
                arguments.append(
                    BaseArgument(
                        digest((model, holder, frame_key(frame), polarity)), frame, polarity
                    )
                )
    return tuple(sorted(arguments, key=lambda argument: argument.id))


@dataclass(frozen=True)
class PremiseGroup:
    relation: str
    proposition: Term
    polarity: str
    alternatives: tuple[str, ...]


@dataclass(frozen=True)
class Argument:
    id: str
    relation: str
    bindings: tuple[tuple[str, Term], ...]
    proposition: Term
    polarity: str
    premises: tuple[PremiseGroup, ...]


def argument_id(model, holder, relation, bindings, proposition, polarity):
    return digest(
        (
            model,
            holder,
            relation,
            tuple((n, term_wire(t)) for n, t in bindings),
            term_wire(proposition),
            polarity,
        )
    )


@dataclass(frozen=True)
class Graph:
    model: str
    holder: tuple[str, str]
    frames: tuple[Frame, ...]
    arguments: tuple[Argument, ...]

    def __post_init__(self):
        if (
            type(self.model) is not str
            or not self.model
            or type(self.holder) is not tuple
            or len(self.holder) != 2
            or any(type(part) is not str or not part for part in self.holder)
            or type(self.frames) is not tuple
            or any(type(f) is not Frame for f in self.frames)
            or type(self.arguments) is not tuple
        ):
            raise ValueError("invalid reasoning graph basis")
        slots = set()
        for frame in self.frames:
            frame.__post_init__()
            for term in (frame.slot, frame.proposition, frame.appraisal):
                if term is not None:
                    term.__post_init__()
            if (frame.ground.scope, frame.ground.recipient) != self.holder:
                raise ValueError("reasoning crosses personal evidence scopes")
            slot = (frame.rule, frame.slot)
            if slot in slots:
                raise ValueError("reasoning basis has duplicate active slots")
            slots.add(slot)
        available = {a.id: a for a in base_arguments(self.model, self.holder, self.frames)}
        for argument in self.arguments:
            if type(argument) is not Argument:
                raise ValueError("foreign reasoning argument")
            if (
                type(argument.relation) is not str
                or not argument.relation
                or argument.relation == "base"
                or argument.polarity not in POLARITIES
                or type(argument.proposition) is not Term
                or type(argument.bindings) is not tuple
                or any(
                    type(e) is not tuple
                    or len(e) != 2
                    or type(e[0]) is not str
                    or not e[0]
                    or type(e[1]) is not Term
                    for e in argument.bindings
                )
                or argument.bindings != tuple(sorted(dict(argument.bindings).items()))
                or type(argument.premises) is not tuple
                or not argument.premises
            ):
                raise ValueError("invalid reasoning argument")
            if (
                argument.id
                != argument_id(
                    self.model,
                    self.holder,
                    argument.relation,
                    argument.bindings,
                    argument.proposition,
                    argument.polarity,
                )
                or argument.id in available
            ):
                raise ValueError("invalid or duplicated reasoning identity")
            for group in argument.premises:
                if (
                    type(group) is not PremiseGroup
                    or type(group.proposition) is not Term
                    or group.polarity not in POLARITIES
                    or type(group.alternatives) is not tuple
                    or not group.alternatives
                    or any(type(identity) is not str for identity in group.alternatives)
                    or group.alternatives != tuple(sorted(set(group.alternatives)))
                ):
                    raise ValueError("reasoning needs canonical nonempty premise groups")
                for identity in group.alternatives:
                    parent = available.get(identity)
                    if parent is None or (parent.relation, parent.proposition, parent.polarity) != (
                        group.relation,
                        group.proposition,
                        group.polarity,
                    ):
                        raise ValueError("reasoning has a dangling, cyclic or mismatched premise")
            argument.proposition.__post_init__()
            for _, term in argument.bindings:
                term.__post_init__()
            for group in argument.premises:
                group.proposition.__post_init__()
            available[argument.id] = argument


@dataclass(frozen=True)
class Pattern:
    name: str
    signature: str
    operation: str
    operand: object
    children: tuple = ()


@dataclass(frozen=True)
class Premise:
    relation: str
    polarity: str
    pattern: Pattern


@dataclass(frozen=True)
class Rule:
    name: str
    premises: tuple[Premise, ...]


@dataclass(frozen=True)
class Limits:
    work: int = 100000
    arguments: int = 4096
    edges: int = 16384
    wire_bytes: int = 1048576

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("reasoning budgets need positive integers")


class ReasoningBudget(ValueError):
    pass


class Meter:
    def __init__(self, limits):
        limits.__post_init__()
        self.limits = limits
        self.work = self.arguments = self.edges = 0

    def spend(self, *, work=0, arguments=0, edges=0):
        self.work += work
        self.arguments += arguments
        self.edges += edges
        if (
            self.work > self.limits.work
            or self.arguments > self.limits.arguments
            or self.edges > self.limits.edges
        ):
            raise ReasoningBudget("reasoning work, argument or edge budget exhausted")


def order_rules(rules, *, meter=None):
    if meter is not None:
        meter.spend(work=len(rules))
    names = {rule.name: rule for rule in rules}
    if len(names) != len(rules) or "base" in names:
        raise ValueError("reasoning relations need unique nonreserved names")
    ordered, visiting, complete = [], [], set()

    def visit(name):
        if meter is not None:
            meter.spend(work=1)
        if name in visiting:
            raise ValueError("cyclic reasoning: " + " -> ".join((*visiting, name)))
        if name not in names:
            raise ValueError("unknown reasoning relation: " + name)
        if name in complete:
            return
        visiting.append(name)
        rule = names[name]
        if not rule.premises:
            raise ValueError("reasoning rules need explicit premises")
        for premise in rule.premises:
            if meter is not None:
                meter.spend(work=1)
            if premise.polarity not in POLARITIES:
                raise ValueError("invalid premise polarity")
            if premise.relation != "base":
                visit(premise.relation)
        visiting.pop()
        complete.add(name)
        ordered.append(rule)

    for name in sorted(names):
        visit(name)
    return tuple(ordered)


def match(pattern, value, bindings, constant, meter):
    meter.spend(work=1)
    if (value.name, value.signature) != (pattern.name, pattern.signature):
        return None
    if pattern.operation == "variable":
        old = bindings.get(pattern.operand)
        if old is not None and old != value:
            return None
        return {**bindings, pattern.operand: value}
    if pattern.operation == "constant":
        return bindings if value == constant(pattern.operand) else None
    if pattern.operation == "case":
        if (
            type(value.wire) is not tuple
            or len(value.wire) != 2
            or value.wire[0] != pattern.operand
        ):
            return None
        child = pattern.children[0]
        return match(
            child, Term(child.name, child.signature, value.wire[1]), bindings, constant, meter
        )
    if pattern.operation != "tuple" or type(value.wire) is not tuple:
        raise ValueError("invalid typed reasoning pattern")
    if len(value.wire) != len(pattern.children):
        return None
    for child, wire in zip(pattern.children, value.wire, strict=True):
        bindings = match(child, Term(child.name, child.signature, wire), bindings, constant, meter)
        if bindings is None:
            return None
    return bindings


def evaluate(model, holder, frames, rules, *, constant, resolve, limits=Limits()):
    """Join literal matches, retaining OR groups rather than proof-path products."""
    meter = Meter(limits)
    meter.spend(work=len(frames))
    bases = base_arguments(model, holder, frames)
    meter.spend(arguments=len(bases))
    relations, output = {"base": bases}, []
    for rule in order_rules(rules, meter=meter):
        meter.spend(work=1)
        rows = [((), ())]
        for premise in rule.premises:
            meter.spend(work=1)
            joined = {}
            for bindings, groups in rows:
                for parent in relations[premise.relation]:
                    meter.spend(work=1)
                    if parent.polarity != premise.polarity:
                        continue
                    result = match(
                        premise.pattern,
                        parent.proposition,
                        dict(bindings),
                        lambda operand: constant(rule.name, operand),
                        meter,
                    )
                    if result is None:
                        continue
                    bound = tuple(sorted(result.items()))
                    group = PremiseGroup(
                        premise.relation,
                        parent.proposition,
                        premise.polarity,
                        (parent.id,),
                    )
                    previous = joined.get(bound)
                    meter.spend(work=1, edges=1)
                    if previous is None:
                        joined[bound] = (*groups, group)
                    else:
                        if previous[:-1] != groups or previous[-1].proposition != group.proposition:
                            raise ValueError(
                                "reasoning pattern did not fully bind its matched term"
                            )
                        joined[bound] = (
                            *groups,
                            PremiseGroup(
                                group.relation,
                                group.proposition,
                                group.polarity,
                                tuple(sorted({*previous[-1].alternatives, parent.id})),
                            ),
                        )
            rows = tuple(
                sorted(
                    joined.items(),
                    key=lambda entry: key(tuple((n, term_wire(t)) for n, t in entry[0])),
                )
            )
        derived = {}
        for bindings, groups in rows:
            for bound, polarity, proposition in resolve(rule.name, bindings, meter):
                meter.spend(work=1)
                identity = argument_id(model, holder, rule.name, bound, proposition, polarity)
                argument = Argument(identity, rule.name, bound, proposition, polarity, groups)
                if identity in derived and derived[identity] != argument:
                    raise ValueError("reasoning produced ambiguous argument grounds")
                if identity not in derived:
                    meter.spend(arguments=1, edges=sum(len(g.alternatives) for g in groups))
                    derived[identity] = argument
        relations[rule.name] = tuple(derived[k] for k in sorted(derived))
        output.extend(relations[rule.name])
    graph = Graph(model, holder, frames, tuple(output))
    _check_wire_budget(graph_wire(graph), limits.wire_bytes)
    return graph


def _check_wire_budget(wire, maximum):
    """Count the exact default ensure_ascii JSON bytes of validated closed wire data."""
    size, strings = 0, {}
    stack = [iter((wire,))]
    while stack:
        for value in stack[-1]:
            if type(value) is tuple:
                # Default JSON array punctuation is brackets and comma-space separators.
                size += 2 + 2 * max(0, len(value) - 1)
                stack.append(iter(value))
            elif type(value) is str:
                length = strings.get(value)
                if length is None:
                    length = len(encode_basestring_ascii(value))
                    if len(strings) < 256:
                        strings[value] = length
                size += length
            elif value is None:
                size += 4
            elif type(value) is bool:
                size += 4 if value else 5
            elif type(value) is int:
                size += len(str(value))
            else:
                raise ValueError("reasoning graph wire requires closed primitive tuples")
            if size > maximum:
                raise ReasoningBudget("reasoning explanation wire budget exhausted")
            break
        else:
            stack.pop()


def graph_wire(graph):
    from .state import frame_wire

    return (
        graph.model,
        graph.holder,
        tuple(frame_wire(f) for f in graph.frames),
        tuple(
            (
                a.id,
                a.relation,
                tuple((n, term_wire(t)) for n, t in a.bindings),
                term_wire(a.proposition),
                a.polarity,
                tuple(
                    (g.relation, term_wire(g.proposition), g.polarity, g.alternatives)
                    for g in a.premises
                ),
            )
            for a in graph.arguments
        ),
    )


def graph_from_wire(wire):
    from .state import frame_from_wire

    model, holder, frames, arguments = wire
    return Graph(
        model,
        holder,
        tuple(frame_from_wire(f) for f in frames),
        tuple(
            Argument(
                identity,
                relation,
                tuple((n, Term(*t)) for n, t in bindings),
                Term(*proposition),
                polarity,
                tuple(
                    PremiseGroup(r, Term(*p), pol, alternatives)
                    for r, p, pol, alternatives in groups
                ),
            )
            for identity, relation, bindings, proposition, polarity, groups in arguments
        ),
    )
