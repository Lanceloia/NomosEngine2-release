"""Readable projections of frozen personal decisions and sourced experience."""

from nomos_cognition.appraisal import assess, choose, query_for
from nomos_cognition.memory import Context, Memory, recall
from nomos_runtime.candidates import selected_strategy
from nomos_runtime.decisions import canonical_selection

from . import experience_timeline

PAGE_SIZE = 12


def advice(game, actions):
    session, actor = game.session, game.player
    strategy = selected_strategy(session, actor)
    if strategy.participation is None:
        return "no_candidate", None
    personality, goals = strategy.participation
    frame = session.candidate_frame(actor, actions=actions)
    if frame.status != "complete":
        return frame.status, None
    context = Context(frame.model.domain, session.actor_reference(actor).scope)
    memory = Memory("human-advice-preview")
    query = query_for(frame.model, memory.subject, context, frozenset(), frame.candidates)
    decision = choose(
        assess(frame.model, recall(memory, query), frame.candidates),
        personality=personality,
        goals=goals,
    )
    key = decision.choice
    if decision.status == "tie" and strategy.tie == "canonical":
        key = canonical_selection(session, actor, frame, decision)
    if key is None:
        return decision.status, None
    details = session.candidate_details(actor, frame, key)
    score = next(s for s in decision.scores if s.candidate == key)
    labels = game.presentation.specification["labels"]
    return "proposed", {
        **details,
        "score": float(score.total),
        "parts": [
            {"label": labels.get(name, name), "value": float(weighted)}
            for name, _, _, _, weighted in score.parts
        ],
        "explanations": [
            {"category": category, "label": label, "type": kind, "value": value}
            for category, label, kind, value in details["explanations"]
        ],
    }


def page(game, actor, offset):
    visit = game.participations[actor]
    memory = visit.snapshot.memory
    samples = memory._sample_versions
    records = visit.decisions
    labels = game.presentation.specification["labels"]
    action_sources = {a.source: a.name for a in game.session.program.actions.values()}
    contexts = [v.context for v in visit.past_visits] + [visit.snapshot.context]
    rows = []
    for index, record in enumerate(records[offset : offset + PAGE_SIZE], offset):
        trial, decision = record.trial, record.decision
        metadata = game.presentation.actions[trial.ability]
        inputs = dict(trial.inputs)
        estimate = next(
            e for e in decision.assessment.estimates if e.candidate.key == record.selection
        )
        score = next(s for s in decision.scores if s.candidate == record.selection)
        weights = {
            axis: (dict(decision.personality).get(axis, 0) + dict(decision.goals).get(axis, 0))
            * dict(estimate.candidate.valuation).get(axis, 1)
            for axis in decision.assessment.model.outcomes
        }
        baseline = sum(value * weights[axis] for axis, value in estimate.candidate.prior)
        contributions = []
        adjustments = experience_timeline.experience_adjustments(
            decision.assessment.model, estimate, weights
        )
        for contribution, adjustment in zip(estimate.contributions, adjustments, strict=True):
            sample = samples[contribution.sample]
            origin = sample.trial.context
            old_action = action_sources.get(sample.trial.producer)
            title = (
                game.presentation.actions[old_action].specification["title"]
                if old_action
                else sample.trial.producer
            )
            contributions.append(
                {
                    "game": contexts.index(origin) + 1 if origin in contexts else None,
                    "past": origin != record.context,
                    "action": title,
                    "occurrence": sample.trial.occurrence,
                    "adjustment": float(sum(value for _, value in adjustment)),
                    "adjustments": [
                        {"label": labels.get(axis, axis), "value": float(value)}
                        for axis, value in adjustment
                    ],
                    "results": [
                        {"label": labels.get(name, name), "value": value}
                        for name, value in contribution.outcomes
                    ],
                    "similarity": float(contribution.similarity),
                    "independence": [
                        {"label": labels.get(name, name), "value": str(value)}
                        for name, value in contribution.independence
                    ],
                    "evidence": [
                        {"channel": s.channel, "occurrence": s.occurrence} for s in sample.evidence
                    ],
                }
            )
        rows.append(
            {
                "occurrence": trial.occurrence,
                "index": index,
                "alternatives": experience_timeline.alternatives(game, record),
                "received": experience_timeline.received(
                    game,
                    actor,
                    records[index - 1].trial.occurrence if index else None,
                    trial.occurrence,
                ),
                "title": metadata.specification["title"],
                "source": trial.source,
                "resolution": record.resolution,
                "planning": None
                if record.planning is None
                else {
                    "work": record.planning.decision.work,
                    "nodes": record.planning.decision.nodes,
                    "pending": record.planning.decision.pending,
                    "search_complete": record.planning.decision.search_complete,
                    "stopped_by": record.planning.decision.stopped_by,
                    "considered": len(record.planning.evaluations),
                },
                "inputs": [
                    {
                        "label": item.specification["label"],
                        "data": game.display.encode(item.type_name, inputs[item.name]),
                        "format": game.display.format(item.type_name),
                    }
                    for item in metadata.inputs
                ],
                "goals": [
                    {"label": labels.get(name, name), "weight": value}
                    for name, value in decision.goals
                ],
                "personality": [
                    {"label": labels.get(name, name), "weight": value}
                    for name, value in decision.personality
                ],
                "explanations": [
                    {
                        "category": category,
                        "label": label,
                        "data": game.display.encode(kind, value),
                        "format": game.display.format(kind),
                    }
                    for category, label, kind, value in record.explanations
                ],
                "prior": baseline,
                "total": float(score.total),
                "exact": str(score.total),
                "memory_delta": float(score.total - baseline),
                "contributions": contributions,
            }
        )
    return {
        "kind": "experience",
        "actor": actor,
        "offset": offset,
        "total": len(records),
        "next": offset + PAGE_SIZE if offset + PAGE_SIZE < len(records) else None,
        "previous": max(0, offset - PAGE_SIZE) if offset else None,
        "entries": rows,
        "timeline": experience_timeline.overview(game, records, PAGE_SIZE),
        "participations": len(contexts),
        "samples": len(memory.samples),
        "pending_feedback": len(visit.snapshot.pending),
    }
