"""Closed, versioned values for Subject checkpoints and historical audit metadata."""

import json
from dataclasses import fields, is_dataclass
from fractions import Fraction


def _records():
    # File tags only select from these imports, never an import path supplied by data.
    from nomos_cognition import appraisal, exploration, memory, state
    from nomos_cognition.planning import diagnostics, values
    from nomos_cognition.storage.audit import DecisionEvidence

    from .consideration import ConsiderationReport
    from .decisions import DecisionAlternative, PublishedChoice
    from .entities import Reference
    from .local_inputs import InputCursor, InputIdentity
    from .participation import ParticipationLimits, SubjectDecision, Visit
    from .planning_appraisal import ActionEvaluation, StagePreparation
    from .planning_bindings import BindingPreparation
    from .planning_construction import ConstructionPreparation
    from .planning_preparation import FramePreparation
    from .records import ActionEpoch
    from .subject_audit import DecisionRecord
    from .subject_planning import SubjectPlanningReport

    return (
        appraisal.Model,
        appraisal.Candidate,
        appraisal.Score,
        appraisal.Limits,
        exploration.EpsilonGreedy,
        exploration.ExplorationDecision,
        memory.Context,
        memory.Source,
        memory.Episode,
        memory.Sample,
        memory.Experience,
        memory.RecallLimits,
        state.Term,
        diagnostics.PhaseStatistics,
        diagnostics.SearchStatistics,
        values.Basis,
        values.Parameter,
        values.Schema,
        values.Binding,
        values.Action,
        values.Branch,
        values.Plan,
        values.Estimate,
        values.Decision,
        values.Limits,
        DecisionEvidence,
        ConsiderationReport,
        DecisionAlternative,
        PublishedChoice,
        Reference,
        InputCursor,
        InputIdentity,
        SubjectDecision,
        Visit,
        ParticipationLimits,
        ActionEvaluation,
        StagePreparation,
        BindingPreparation,
        ConstructionPreparation,
        FramePreparation,
        ActionEpoch,
        DecisionRecord,
        SubjectPlanningReport,
    )


def _integer(value):
    if type(value) is not str:
        raise ValueError("invalid checkpoint integer")
    number = int(value, 16)
    if format(number, "x") != value:
        raise ValueError("noncanonical checkpoint integer")
    return number


class SubjectValueCodec:
    """Pure data only; historical References are values, not a current identity domain."""

    def __init__(self, module=None, *, nodes=1_000_000, depth=128, wire_bytes=64 * 1024 * 1024):
        if any(type(n) is not int or n < 1 for n in (nodes, depth, wire_bytes)):
            raise ValueError("checkpoint codec requires positive resource limits")
        self.nodes, self.depth, self.wire_bytes = nodes, depth, wire_bytes
        self.program = None if module is None else module.PROGRAM
        self.generated = {}
        self.types = {
            **{c.__module__ + "." + c.__name__: c for c in _records()},
            **{"builtin." + c.__name__: c for c in (bool, int, str, tuple, frozenset, type(None))},
        }
        if module is not None:
            records = getattr(module, "RECORDS", None)
            if type(records) is not dict:
                raise ValueError("checkpoint carriers require a generated RECORDS table")
            for name, carrier in sorted(records.items()):
                if (
                    type(name) is not str
                    or not name
                    or not isinstance(carrier, type)
                    or not is_dataclass(carrier)
                    or not carrier.__dataclass_params__.frozen
                    or carrier.__module__ != module.__name__
                ):
                    raise ValueError("checkpoint carrier must be a local frozen generated record")
                self.types["generated." + name] = carrier
                self.generated.setdefault(carrier, name)
        self.tags = {}
        for tag, carrier in self.types.items():
            self.tags.setdefault(carrier, tag)
        self.shapes = {
            tag: tuple(f.name for f in fields(carrier) if f.init)
            for tag, carrier in self.types.items()
            if is_dataclass(carrier)
        }

    def _visitor(self):
        used = 0

        def visit(depth):
            nonlocal used
            used += 1
            if depth > self.depth or used > self.nodes:
                raise ValueError("checkpoint value exceeds node or depth limit")

        return visit

    def _check_record(self, value):
        from .entities import Reference, ReferenceDomain
        from .expressions import ValueBudget, ValueLimits

        if type(value) is Reference and (
            type(value.scope) is not str
            or not value.scope
            or type(value.sort) is not str
            or not value.sort
            or type(value.ordinal) is not int
            or value.ordinal < 1
        ):
            raise ValueError("historical reference needs its original scope, sort and ordinal")
        name = self.generated.get(type(value))
        if name is not None:
            references = self.program.reference_readers[name](value)
            domain = ReferenceDomain(self.program.schemas, (), references=references)
            self.program.validators[name](value, ValueBudget(ValueLimits(), domain), ())
        return value

    def dumps(self, value):
        visit = self._visitor()

        def encode(value, depth):
            visit(depth)
            carrier = type(value)
            if value is None or carrier in (bool, str):
                return value
            if carrier is int:
                return ["int", format(value, "x")]
            if carrier is Fraction:
                return ["fraction", format(value.numerator, "x"), format(value.denominator, "x")]
            if carrier in (tuple, list, frozenset):
                members = [encode(v, depth + 1) for v in value]
                if carrier is frozenset:
                    members.sort(key=lambda v: json.dumps(v, ensure_ascii=True))
                return [carrier.__name__, members]
            if carrier is dict:
                return [
                    "dict",
                    [[encode(k, depth + 1), encode(v, depth + 1)] for k, v in value.items()],
                ]
            if isinstance(value, type):
                tag = self.tags.get(value)
                if tag is not None:
                    return ["type", tag]
            tag = self.tags.get(carrier)
            if tag in self.shapes:
                self._check_record(value)
                return [
                    "record",
                    tag,
                    [[n, encode(getattr(value, n), depth + 1)] for n in self.shapes[tag]],
                ]
            raise ValueError("unsupported checkpoint value type: " + carrier.__name__)

        try:
            body = json.dumps(
                ["nomos.subject.values", 1, encode(value, 0)],
                ensure_ascii=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except RecursionError as error:
            raise ValueError("cyclic or excessively nested checkpoint value") from error
        if len(body) > self.wire_bytes:
            raise ValueError("checkpoint value exceeds wire byte limit")
        return body

    def loads(self, body):
        if (
            type(body) is not str
            or len(body) > self.wire_bytes
            or len(body.encode("utf-8")) > self.wire_bytes
        ):
            raise ValueError("checkpoint requires bounded encoded text")
        visit = self._visitor()

        def decode(wire, depth):
            visit(depth)
            if wire is None or type(wire) in (bool, str):
                return wire
            if type(wire) is not list or not wire or type(wire[0]) is not str:
                raise ValueError("invalid tagged checkpoint value")
            tag = wire[0]
            if tag == "int" and len(wire) == 2:
                return _integer(wire[1])
            if tag == "fraction" and len(wire) == 3:
                numerator, denominator = _integer(wire[1]), _integer(wire[2])
                if denominator < 1:
                    raise ValueError("checkpoint fraction requires positive denominator")
                value = Fraction(numerator, denominator)
                if (value.numerator, value.denominator) != (numerator, denominator):
                    raise ValueError("checkpoint fraction must be reduced")
                return value
            if tag == "type" and len(wire) == 2 and type(wire[1]) is str:
                if wire[1] not in self.types:
                    raise ValueError("unknown checkpoint type")
                return self.types[wire[1]]
            if tag in ("tuple", "list", "frozenset", "dict") and len(wire) == 2:
                if type(wire[1]) is not list:
                    raise ValueError("checkpoint collection requires a list of values")
                if tag == "dict":
                    result = {}
                    for pair in wire[1]:
                        if type(pair) is not list or len(pair) != 2:
                            raise ValueError("checkpoint dictionary requires key/value pairs")
                        key, value = (decode(v, depth + 1) for v in pair)
                        if key in result:
                            raise ValueError("duplicate checkpoint dictionary key")
                        result[key] = value
                    return result
                values = [decode(v, depth + 1) for v in wire[1]]
                if tag == "list":
                    return values
                if tag == "tuple":
                    return tuple(values)
                result = frozenset(values)
                if len(result) != len(values):
                    raise ValueError("duplicate checkpoint set member")
                return result
            if tag == "record" and len(wire) == 3 and type(wire[1]) is str:
                name, pairs = wire[1:]
                shape = self.shapes.get(name)
                if (
                    shape is None
                    or type(pairs) is not list
                    or any(type(p) is not list or len(p) != 2 for p in pairs)
                    or tuple(p[0] for p in pairs) != shape
                ):
                    raise ValueError("unknown checkpoint record or incorrect fields")
                return self._check_record(
                    self.types[name](*(decode(p[1], depth + 1) for p in pairs))
                )
            raise ValueError("unknown checkpoint tag or incorrect shape")

        try:
            wire = json.loads(body)
            if (
                type(wire) is not list
                or len(wire) != 3
                or wire[0] != "nomos.subject.values"
                or type(wire[1]) is not int
                or wire[1] != 1
            ):
                raise ValueError("unsupported checkpoint value format")
            return decode(wire[2], 0)
        except (RecursionError, TypeError, KeyError, ZeroDivisionError) as error:
            raise ValueError("invalid checkpoint value") from error
