"""Actor-local bounded search over admitted choices, before expensive descriptions."""

from dataclasses import dataclass
from heapq import nsmallest

from .errors import AdmissionError
from .ordering import canonical


@dataclass(frozen=True)
class ConsiderationReport:
    per_ability: int | None
    exhaustive: bool
    groups: tuple

    @property
    def enumerated(self):
        return sum(row[2] for row in self.groups)

    @property
    def retained(self):
        return sum(row[3] for row in self.groups)

    @property
    def wire(self):
        return self.per_ability, self.exhaustive, self.groups


def shortlist(entries, score, per_ability, *, exhaustive):
    if (
        type(exhaustive) is not bool
        or per_ability is not None
        and (type(per_ability) is not int or not 1 <= per_ability <= 128)
    ):
        raise AdmissionError("InvalidConsideration", "checked finite consideration required")
    groups = {}
    for index, entry in enumerate(entries):
        groups.setdefault((entry.ability, entry.opportunity), []).append(index)
    retained, coverage = set(), []
    for (ability, opportunity), indices in groups.items():
        cutoff = None
        if per_ability is not None and not exhaustive and len(indices) > per_ability:
            scores, strata = {}, {}
            for index in indices:
                result = score(entries[index])
                if type(result) is not tuple or len(result) != 2 or type(result[0]) is not int:
                    raise AdmissionError(
                        "InvalidConsideration", "typed screen score/group required"
                    )
                value, group = result
                scores[index] = value
                strata.setdefault(canonical(group), []).append(index)

            def rank(i):
                return -scores[i], entries[i].key

            ordered = [nsmallest(per_ability, group, key=rank) for group in strata.values()]
            selected = []
            for depth in range(per_ability):
                heads = [group[depth] for group in ordered if depth < len(group)]
                selected.extend(nsmallest(per_ability - len(selected), heads, key=rank))
                if len(selected) == per_ability:
                    break
            cutoff = min(scores[index] for index in selected)
        else:
            selected = indices
        retained.update(selected)
        coverage.append((ability, opportunity, len(indices), len(selected), cutoff))
    return (
        tuple(entry for index, entry in enumerate(entries) if index in retained),
        ConsiderationReport(per_ability, exhaustive, tuple(coverage)),
    )
