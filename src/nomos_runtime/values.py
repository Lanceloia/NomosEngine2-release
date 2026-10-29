"""Generated value codecs at tool boundaries, independent of compiler type plans."""

import json

from .expressions import ValueBudget, fail_value


def wire_key(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    except (ValueError, TypeError, RecursionError):
        fail_value("Wire", (), "InvalidValue", "encodable plain wire data", "encoding failed")


def check_wire(definition, value, budget):
    """Bound closed tool data, including caller-supplied reference representations."""
    size = getattr(budget, "wire_used", 0)
    nodes = 0

    def charge(amount, path):
        nonlocal size
        size += amount
        if size > budget.limits.wire_bytes:
            fail_value(definition, path, "ValueBudget", "bounded wire bytes", "byte limit")

    def atom(item, path):
        if type(item) is str and len(item) > budget.limits.wire_bytes:
            fail_value(definition, path, "ValueBudget", "bounded wire bytes", "byte limit")
        try:
            encoded = json.dumps(item, ensure_ascii=False).encode("utf-8")
        except (ValueError, TypeError, UnicodeError):
            fail_value(
                definition, path, "InvalidValue", "plain Unicode scalar data", "encoding failed"
            )
        charge(len(encoded), path)

    def walk(item, path, stack):
        nonlocal nodes
        nodes += 1
        if nodes > budget.limits.nodes or len(path) > budget.limits.depth:
            fail_value(
                definition, path, "ValueBudget", "bounded wire structure", "node/depth limit"
            )
        if item is None or type(item) in (bool, int, str):
            atom(item, path)
            return
        if type(item) not in (dict, list) or id(item) in stack:
            fail_value(
                definition, path, "InvalidValue", "acyclic plain wire data", type(item).__name__
            )
        budget.collection(definition, path, len(item))
        charge(2 + max(0, len(item) - 1), path)
        stack = stack | {id(item)}
        for key, child in item.items() if type(item) is dict else enumerate(item):
            if type(item) is dict:
                if type(key) is not str:
                    fail_value(
                        definition, path, "InvalidValue", "text wire keys", type(key).__name__
                    )
                atom(key, path)
                charge(1, path)
            walk(child, (*path, key), stack)

    walk(value, (), frozenset())
    budget.wire_used = size


class ValueCodec:
    """A current identity view; custom wire callbacks never grant identity authority."""

    def __init__(self, session, actor=None):
        domain = (
            session.references
            if actor is None
            else session.context(session._states, "actor", session._actor(actor)).references
        )
        self.references = domain
        self.program, self.limits = session.program, session.limits.value
        self.names = {ref: name for name, ref in domain.symbols.items()}

    def reference(self, value):
        self.references.require(value, value.sort)
        name = self.names.get(value)
        if name is None:
            fail_value(value.sort, (), "UnknownIdentity", "tool reference alias", "absent")
        kind = "actor" if self.program.schemas[value.sort].kind == "person" else "object"
        return {kind: name}

    def decode(self, name, wire, *, reference=None):
        decoder = self.program.decoders.get(name) if type(name) is str else None
        if decoder is None:
            raise ValueError("value type is not selected by Program")
        budget = ValueBudget(self.limits, self.references, resolve_reference=reference)
        check_wire(name, wire, budget)
        return decoder(wire, budget, ())

    def encode(self, name, value, *, reference=None, budget=None):
        encoder = self.program.encoders.get(name) if type(name) is str else None
        if encoder is None:
            raise ValueError("value type is not selected by Program")
        if budget is not None and (type(budget) is not ValueBudget or budget.limits != self.limits):
            raise ValueError("output budget must use the codec's current value limits")
        self.program.validators[name](value, ValueBudget(self.limits, self.references), ())
        budget = ValueBudget(self.limits, self.references) if budget is None else budget
        result = encoder(value, budget, (), self.reference if reference is None else reference)
        check_wire(name, result, budget)
        return result
