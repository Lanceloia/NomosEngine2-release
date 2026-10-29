"""Bind pure official models to checked Actor-local policy input expressions."""

import hashlib
import json
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError
from nomos_cognition.prediction import provider


@dataclass(frozen=True)
class PredictionPlan:
    provider: str
    artifact: str
    digest: str
    inputs: tuple
    subject: object
    subject_type: str
    label: str
    kind: str
    when: object
    score_mode: str


def compile_prediction(branch, declaration, models, location):
    from .frontend import row

    row(
        declaration,
        {"model", "inputs", "subject", "label"},
        {"views", "when", "score_mode"},
        path=location,
    )
    score_mode = declaration.get("score_mode", "replace")
    if type(score_mode) is not str or score_mode not in ("replace", "add"):
        raise C0LawError(location + ": score_mode must be replace or add")
    name = declaration["model"]
    if type(name) is not str or name not in models:
        raise C0LawError(location + ": unknown named predictor")
    selected = models[name]
    row(selected, {"provider", "artifact"}, path="predictors." + name)
    try:
        implementation = provider(selected["provider"])
        if implementation.prediction_kind not in ("categorical", "event"):
            raise ValueError("unknown official prediction measure")
        model = implementation.build(selected["artifact"])
        artifact = json.dumps(model.data(), sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise C0LawError(location + ": invalid frozen model: " + str(error)) from error
    inputs = declaration["inputs"]
    if type(inputs) is not dict or set(inputs) != set(implementation.ports):
        raise C0LawError(location + ": predictor needs its exact declared input ports")
    label = declaration["label"]
    if type(label) is not str or not label.strip() or len(label) > 128:
        raise C0LawError(location + ": bounded probability label required")
    references, compiled = {}, []

    def shape(plan, expected):
        if expected == "person":
            if plan.kind != "ref" or dict(branch.entities.entities)[plan.sort].kind != "person":
                return False
            previous = references.setdefault("person", plan.type_id)
            return previous == plan.type_id
        if type(expected) is str:
            return plan.kind == expected
        if type(expected) is dict:
            fields = dict(plan.fields)
            return plan.kind == "record" and all(
                key in fields and shape(fields[key], child) for key, child in expected.items()
            )
        kind, element = expected
        if kind == "enum":
            return plan.kind == kind and set(element) <= set(plan.choices)
        return plan.kind == kind and shape(plan.element, element)

    for port, expected in implementation.ports.items():
        expression = branch.expression(inputs[port], None, location + "." + port, context="actor")
        if not shape(expression.result, expected):
            raise C0LawError(location + ": predictor port type mismatch: " + port)
        compiled.append((port, expression))
    subject = branch.expression(
        declaration["subject"], None, location + ".subject", context="actor"
    )
    if not shape(subject.result, implementation.subject_shape):
        raise C0LawError(location + ": prediction subject must match its provider subject shape")
    when = (
        branch.expression(declaration["when"], "Bool", location + ".when", context="actor")
        if "when" in declaration
        else None
    )
    # The full provider contract and weights participate in the recorded identity.
    digest = hashlib.sha256((selected["provider"] + "\n" + artifact).encode()).hexdigest()
    return PredictionPlan(
        selected["provider"],
        artifact,
        digest,
        tuple(compiled),
        subject,
        subject.result.name,
        label,
        implementation.prediction_kind,
        when,
        score_mode,
    )
