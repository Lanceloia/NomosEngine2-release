"""Read committed cognition history for an explicitly enabled, closed game recap."""

from nomos_cognition.prediction import EventPrediction
from nomos_runtime.cognition import Terms, ground
from nomos_runtime.presentation import DisplayFrame

from .mental_trends import overview

PAGE_SIZE = 12


def page(game, actor, offset):
    session = game.session
    slot = session.inspect_cognition(actor)
    display = game.presentation.open(session, actor)
    frame = DisplayFrame(display)
    terms = Terms(session, session.values(actor).references)

    encoded = {}

    def value(term):
        if term is None:
            return None
        if term not in encoded:
            encoded[term] = {
                "data": frame.encode(term.name, terms.value(term)),
                "format": display.format(term.name),
            }
        return encoded[term]

    def judgment(item):
        return (
            None
            if item is None
            else {
                "proposition": value(item.proposition),
                "support": item.support,
                "opposition": item.opposition,
                "appraisal": value(item.appraisal),
                "score": item.score,
            }
        )

    active, changes = {}, {}
    for item in slot.state.history:
        key = item.rule, item.slot
        prior = active.get(key)
        changes.setdefault(item.ground, []).append((prior, item))
        active[key] = item
    events = []
    for receipt in (*session.opening_acquisitions(), *session.acquisitions()):
        if receipt.recipient == slot.actor:
            evidence = ground(slot.actor, receipt)
            events.append(
                (receipt.occurrence or 0, 0, "message", (receipt, changes.get(evidence, ())))
            )
    definitions = {definition.source: definition for definition in session.program.actions.values()}
    decisions = {item.occurrence: item for item in game.control.decisions if item.actor == actor}
    for record in session.history():
        definition = definitions.get(record.source) if record.family == "Action" else None
        if (
            definition is not None
            and dict(record.participants)[definition.actor_parameter] == slot.actor
        ):
            events.append((record.reference, -1, "action", (definition, record)))
    previous = {}
    for analysis in slot.state.local_history:
        current = {(b.members, b.category): b for b in analysis.bounds}
        changed = [
            (key, previous.get(key), current.get(key))
            for key in dict.fromkeys((*previous, *current))
            if (None if key not in previous else (previous[key].minimum, previous[key].maximum))
            != (None if key not in current else (current[key].minimum, current[key].maximum))
        ]
        events.append((analysis.cutoff, 1, "bounds", (analysis, changed)))
        previous = current
    previous = {}
    for graph in slot.state.reasoning_history:
        current = {(a.proposition, a.polarity): a for a in graph.arguments}
        added = [key for key in current if key not in previous]
        removed = [key for key in previous if key not in current]
        if added or removed:
            cutoff = max((f.ground.occurrence or 0 for f in graph.frames), default=0)
            events.append((cutoff, 2, "reasoning", (added, removed)))
        previous = current
    for analysis in slot.state.analysis_history:
        events.append((analysis.cutoff, 1, "finite", analysis))
    events.sort(key=lambda event: event[:2])
    rows = []
    for occurrence, _, kind, payload in events[offset : offset + PAGE_SIZE]:
        row = {"kind": kind, "occurrence": occurrence or None}
        if kind == "action":
            definition, record = payload
            metadata = game.presentation.actions[definition.name]
            arguments = dict(record.participants)
            row.update(
                title=metadata.specification["title"],
                source=record.source,
                inputs=[
                    {
                        "label": item.specification["label"],
                        "data": frame.encode(item.type_name, arguments[item.name]),
                        "format": display.format(item.type_name),
                    }
                    for item in metadata.inputs
                ],
            )
            decision = decisions.get(record.reference)
            if decision is not None:
                row["decision"] = {
                    "score": decision.score,
                    "parts": [{"label": label, "value": score} for label, score in decision.parts],
                    "explanations": [
                        {
                            "category": category,
                            "label": label,
                            "data": frame.encode(type_name, result),
                            "format": display.format(type_name),
                        }
                        for category, label, type_name, result in decision.explanations
                    ],
                }
        elif kind == "message":
            receipt, revisions = payload
            row.update(
                channel=receipt.channel,
                source=receipt.source,
                message={
                    "data": frame.encode(receipt.type_name, receipt.value),
                    "format": display.format(receipt.type_name),
                },
                processed=ground(slot.actor, receipt) in slot.state.consumed,
                changes=[
                    {"rule": item.rule, "before": judgment(prior), "after": judgment(item)}
                    for prior, item in revisions
                ],
            )
        elif kind == "bounds":
            analysis, changed = payload
            row.update(
                status=analysis.status,
                reason=analysis.reason,
                changes=[
                    {
                        "members": [value(member) for member in key[0]],
                        "category": value(key[1]),
                        "before": None if before is None else [before.minimum, before.maximum],
                        "after": None if after is None else [after.minimum, after.maximum],
                    }
                    for key, before, after in changed
                ],
            )
        elif kind == "reasoning":
            row["changes"] = [
                {"proposition": value(term), "polarity": polarity, "active": active}
                for keys, active in ((payload[0], True), (payload[1], False))
                for term, polarity in keys
            ]
        else:
            row.update(
                status=payload.status,
                model_count=None if payload.status == "pending" else len(payload.models),
            )
        rows.append(row)
    trends = overview(events, value, PAGE_SIZE)
    predictions = []
    for index, (occurrence, _, kind, _) in enumerate(events):
        decision = decisions.get(occurrence) if kind == "action" else None
        prediction = None if decision is None else decision.prediction
        if prediction is None:
            continue
        predictions.append(
            {
                "occurrence": occurrence,
                "basis": prediction.basis,
                "model": prediction.model,
                "label": prediction.label,
                "kind": "event" if type(prediction) is EventPrediction else "categorical",
                "entry": index,
                "page": index // PAGE_SIZE * PAGE_SIZE,
                "subjects": [
                    {
                        "subject": {
                            "data": frame.encode(prediction.subject_type, subject),
                            "format": display.format(prediction.subject_type),
                        },
                        "probability": probability,
                    }
                    for subject, probability in prediction.probabilities
                ],
            }
        )
    frame.check()
    return {
        "actor": actor,
        "offset": offset,
        "total": len(events),
        "next": offset + PAGE_SIZE if offset + PAGE_SIZE < len(events) else None,
        "previous": max(0, offset - PAGE_SIZE) if offset else None,
        "entries": rows,
        "trends": trends,
        "predictions": predictions,
        "pending": slot.state.pending,
    }
