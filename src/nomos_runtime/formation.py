"""Transaction-local allocation; published identities retain their actual producer."""

from collections import Counter
from dataclasses import dataclass

from .entities import Reference
from .errors import SettlementDefect


@dataclass(frozen=True)
class Individual:
    reference: Reference
    formed_by: int | None


class FormationBatch:
    def __init__(self, references, limits, scope):
        self.scope = scope
        self.schemas = references.schemas
        self.next_ordinal = max((ref.ordinal for ref in references.references), default=0) + 1
        self.counts = Counter(ref.sort for ref in references.references)
        self.capacities = {"object": limits.objects_per_type, "person": limits.actors_per_type}
        self.products = []
        self.check_capacity()

    def check_capacity(self):
        for sort, count in self.counts.items():
            if count > self.capacities[self.schemas[sort].kind]:
                raise SettlementDefect("entity capacity per exact sort exceeded: " + sort)

    def allocate(self, sort, occurrence):
        self.counts[sort] += 1
        self.check_capacity()
        reference = Reference(self.scope, self.next_ordinal, sort)
        self.next_ordinal += 1
        self.products.append(Individual(reference, occurrence))
        return reference
