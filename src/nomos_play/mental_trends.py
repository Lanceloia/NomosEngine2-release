"""Project committed audit checkpoints without solving or rescoring history."""


def overview(events, encode, page_size):
    bounds = {"tracks": [], "points": []}
    appraisals = {"tracks": [], "points": []}
    bound_ids, appraisal_ids, active = {}, {}, {}
    for index, (occurrence, _, kind, payload) in enumerate(events):
        point = {
            "entry": index,
            "page": index // page_size * page_size,
            "occurrence": occurrence or None,
        }
        if kind == "bounds":
            analysis, _ = payload
            values = {}
            for bound in analysis.bounds:
                key = bound.members, bound.category
                if key not in bound_ids:
                    identity = str(len(bound_ids))
                    bound_ids[key] = identity
                    bounds["tracks"].append(
                        {
                            "id": identity,
                            "members": [encode(member) for member in bound.members],
                            "category": encode(bound.category),
                        }
                    )
                values[bound_ids[key]] = [bound.minimum, bound.maximum]
            point.update(status=analysis.status, values=values)
            # Equal conclusions remain available in the detailed log, not as repeated columns.
            previous = bounds["points"][-1] if bounds["points"] else None
            if previous is None or (previous["status"], previous["values"]) != (
                point["status"],
                values,
            ):
                bounds["points"].append(point)
        elif kind == "message":
            _, revisions = payload
            for _, item in revisions:
                key = item.rule, item.slot
                active.pop(key, None)
                if item.appraisal is None:
                    continue
                track = key, item.appraisal
                if track not in appraisal_ids:
                    identity = str(len(appraisal_ids))
                    appraisal_ids[track] = identity
                    appraisals["tracks"].append(
                        {
                            "id": identity,
                            "rule": item.rule,
                            "subject": encode(item.appraisal),
                            "occurrence": occurrence or None,
                        }
                    )
                active[key] = appraisal_ids[track], item.score
            values = dict(active.values())
            previous = appraisals["points"][-1] if appraisals["points"] else None
            if (previous is None and values) or (
                previous is not None and previous["values"] != values
            ):
                appraisals["points"].append({**point, "values": values})
    return {"bounds": bounds, "appraisals": appraisals}
