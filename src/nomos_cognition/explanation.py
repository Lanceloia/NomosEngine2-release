"""Bounded current personal explanations, independent of world and value codecs."""

import json

from .reasoning import Meter, ReasoningBudget, base_arguments


def explain(state, *, encode, limits, analysis_kind):
    """Encode committed grounds and graphs; never infer, revise or expose realizations."""
    meter = Meter(limits)

    def term(value):
        stack = [value.wire]
        while stack:
            meter.spend(work=1)
            child = stack.pop()
            if type(child) is tuple:
                stack.extend(child)
        return encode(value)

    def assumptions(values):
        meter.spend(work=len(values))
        return [{"name": name, "description": description} for name, description in values]

    def evidence(value):
        meter.spend(work=1)
        return {
            "source": value.producer,
            "slot": value.slot,
            "occurrence": value.occurrence,
        }

    def ground(value, *, finite):
        result = {
            **evidence(value.evidence),
            "definition": value.definition,
            "sample": value.sample,
        }
        if finite:
            meter.spend(work=len(value.parameters))
            result.update(
                input=value.input,
                kind=value.kind,
                signature=value.signature,
                arguments={name: term(value) for name, value in value.parameters},
            )
        return result

    def finite(value):
        if value is None:
            return pending("not_initialized", finite=True)
        return {
            "status": value.status,
            "complete": value.status != "pending",
            "reason": value.reason,
            "work": value.work,
            "cutoff": value.cutoff,
            "model_count": len(value.models) if value.status != "pending" else None,
            "assumptions": assumptions(value.assumptions),
            "grounds": [ground(item, finite=True) for item in value.grounds],
        }

    def local(value):
        if value is None:
            return pending("not_initialized")
        bounds = []
        for bound in value.bounds:
            meter.spend(work=1 + len(bound.lower_grounds) + len(bound.upper_grounds))
            bounds.append(
                {
                    "members": [term(member) for member in bound.members],
                    "category": term(bound.category),
                    "minimum": bound.minimum,
                    "maximum": bound.maximum,
                    "lower_grounds": list(bound.lower_grounds),
                    "upper_grounds": list(bound.upper_grounds),
                }
            )
        meter.spend(work=len(value.conflict))
        return {
            "status": value.status,
            "complete": value.status == "complete",
            "reason": value.reason,
            "work": value.work,
            "cutoff": value.cutoff,
            "period": value.context.period,
            "conflict": list(value.conflict),
            "grounds": [ground(item, finite=False) for item in value.grounds],
            "assumptions": assumptions(value.context.assumptions),
            "bounds": bounds,
        }

    def graph(value):
        result = empty_graph(state, complete=True)
        if value is None:
            return result
        meter.spend(work=len(value.frames))
        for base in base_arguments(value.model, value.holder, value.frames):
            meter.spend(work=1, arguments=1)
            result["base_arguments"].append(
                {
                    "id": base.id,
                    "rule": base.frame.rule,
                    "polarity": base.polarity,
                    "proposition": term(base.proposition),
                    **evidence(base.frame.ground),
                }
            )
        for argument in value.arguments:
            meter.spend(work=1 + len(argument.bindings), arguments=1)
            premises = []
            for group in argument.premises:
                meter.spend(work=1 + len(group.alternatives), edges=len(group.alternatives))
                premises.append(
                    {
                        "relation": group.relation,
                        "proposition": term(group.proposition),
                        "polarity": group.polarity,
                        "alternatives": list(group.alternatives),
                    }
                )
            result["arguments"].append(
                {
                    "id": argument.id,
                    "relation": argument.relation,
                    "proposition": term(argument.proposition),
                    "polarity": argument.polarity,
                    "conditional": True,
                    "bindings": {name: term(value) for name, value in argument.bindings},
                    "premises": premises,
                }
            )
        return result

    try:
        meter.spend(work=len(state.frames))
        result = {
            "explanation_complete": True,
            "explanation_reason": None,
            "grounds": [evidence(value) for value in dict.fromkeys(f.ground for f in state.frames)],
            "reasoning": graph(state.reasoning),
            "finite": finite(state.analysis) if analysis_kind == "finite" else None,
            "local": local(state.local) if analysis_kind == "local" else None,
        }
        size = 0
        for part in json.JSONEncoder(ensure_ascii=True).iterencode(result):
            meter.spend(work=1)
            size += len(part.encode())
            if size > limits.wire_bytes:
                raise ReasoningBudget("personal explanation payload budget exhausted")
        return result
    except ReasoningBudget:
        # A graph is returned with all its source leaves or not at all.
        return {
            "explanation_complete": False,
            "explanation_reason": "explanation_budget",
            "grounds": [],
            "reasoning": empty_graph(state, complete=False),
            "finite": pending("explanation_budget", finite=True)
            if analysis_kind == "finite"
            else None,
            "local": pending("explanation_budget") if analysis_kind == "local" else None,
        }


def empty_graph(state, *, complete):
    return {
        "complete": not state.pending,
        "active": not state.pending,
        "provisional": state.pending,
        "current_graph_complete": complete,
        "arguments": [],
        "base_arguments": [],
    }


def pending(reason, *, finite=False):
    result = {
        "status": "pending",
        "complete": False,
        "reason": reason,
        "grounds": [],
        "assumptions": [],
    }
    if finite:
        result["model_count"] = None
    else:
        result.update(bounds=[], conflict=[])
    return result
