"""Postgame views of recorded choices; never re-evaluate a historical mind."""

from fractions import Fraction


def experience_adjustments(model, estimate, priorities):
    """Decompose the frozen estimate delta using its original shared denominator."""
    prior = dict(estimate.candidate.prior)
    denominators = {axis: Fraction(model.prior_weight) for axis in model.outcomes}
    for contribution in estimate.contributions:
        factors = dict(contribution.independence)
        for axis, _ in contribution.outcomes:
            if axis not in estimate.candidate.known:
                denominators[axis] += contribution.similarity * factors[axis]
    return tuple(
        tuple(
            (
                axis,
                contribution.similarity
                * dict(contribution.independence)[axis]
                * (value - prior[axis])
                * priorities[axis]
                / denominators[axis],
            )
            for axis, value in contribution.outcomes
            if axis not in estimate.candidate.known
        )
        for contribution in estimate.contributions
    )


def typed(game, kind, value):
    return {"data": game.display.encode(kind, value), "format": game.display.format(kind)}


def inputs(game, ability, values):
    metadata = game.presentation.actions[ability]
    values = dict(values)
    from .inputs import caption

    rows = []
    for item in metadata.inputs:
        shown = typed(game, item.type_name, values[item.name])
        text = caption(item.specification, shown["data"])
        value = shown["data"]
        if text is not None and (value is None or type(value) in (str, int, bool)):
            key = (
                "null"
                if value is None
                else str(value).lower()
                if type(value) is bool
                else str(value)
            )
            shown["format"] = {**shown["format"], "value_labels": {key: text}}
        rows.append({"label": item.specification["label"], **shown})
    return rows


def competition(record):
    scores = {score.candidate: score for score in record.decision.scores}
    estimates = {
        estimate.candidate.key: estimate for estimate in record.decision.assessment.estimates
    }
    return sorted(
        ((option, scores[option.key], estimates[option.key]) for option in record.alternatives),
        key=lambda row: (-row[1].total, row[0].key != record.selection),
    )


def alternatives(game, record):
    labels = game.presentation.specification["labels"]
    rows, ranks = [], {}
    for option, score, estimate in competition(record):
        ranks[option.ability] = ranks.get(option.ability, 0) + 1
        rank = ranks[option.ability]
        prior = dict(estimate.candidate.prior)
        factors = dict(estimate.candidate.valuation)
        parts = [
            {
                "label": labels.get(axis, axis),
                "expected": float(expected),
                "prior": prior[axis],
                "weight": personality + goal,
                "valuation": factors.get(axis, 1),
                "valued": float(expected * factors.get(axis, 1)),
                "weighted": float(weighted),
                "baseline": prior[axis] * factors.get(axis, 1) * (personality + goal),
            }
            for axis, expected, personality, goal, weighted in score.parts
        ]
        rows.append(
            {
                "ability": option.ability,
                "id": f"{option.ability}:{rank}",
                "rank": rank,
                "title": game.presentation.actions[option.ability].specification["title"],
                "selected": option.key == record.selection,
                "count": option.count,
                "detailed": option.detailed,
                "inputs": inputs(game, option.ability, option.inputs),
                "total": float(score.total),
                "exact": str(score.total),
                "prior": sum(part["baseline"] for part in parts),
                "parts": parts,
                "judgments": [
                    {"category": category, "label": label, **typed(game, kind, value)}
                    for category, label, kind, value in option.explanations
                    if category != "information"
                ],
            }
        )
    return rows


def overview(game, records, page_size):
    tracks, judgment_tracks, points = {}, {}, []
    for index, record in enumerate(records):
        values = {}
        for option, score, _ in competition(record):
            tracks.setdefault(
                option.ability,
                {
                    "id": option.ability,
                    "title": game.presentation.actions[option.ability].specification["title"],
                },
            )
            values.setdefault(option.ability, float(score.total))
        judgments = {}
        for category, label, kind, value in record.explanations:
            if category == "judgment" and type(value) is int:
                key = label, kind
                track = judgment_tracks.setdefault(
                    key, {"id": f"judgment:{len(judgment_tracks)}", "title": label}
                )
                judgments[track["id"]] = value
        points.append(
            {
                "index": index,
                "occurrence": record.trial.occurrence,
                "page": index // page_size * page_size,
                "selected": record.trial.ability,
                "selected_value": float(
                    next(
                        score.total
                        for score in record.decision.scores
                        if score.candidate == record.selection
                    )
                ),
                "values": values,
                "judgments": judgments,
            }
        )
    return {
        "tracks": list(tracks.values()),
        "judgments": list(judgment_tracks.values()),
        "points": points,
    }


def received(game, actor, previous, occurrence):
    recipient = game.session.actor_reference(actor)
    labels = game.presentation.specification["labels"]
    receipts = (
        *(() if previous is not None else game.session.opening_acquisitions()),
        *game.session.acquisitions(),
    )
    return [
        {
            "occurrence": receipt.occurrence,
            "source": receipt.source,
            "label": labels.get(receipt.channel, receipt.channel),
            **typed(game, receipt.type_name, receipt.value),
        }
        for receipt in receipts
        if receipt.recipient == recipient
        and (
            receipt.occurrence is None
            or (
                (previous is None or receipt.occurrence >= previous)
                and receipt.occurrence < occurrence
            )
        )
    ]
