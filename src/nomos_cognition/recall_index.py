"""Persistent postings for current memory records, not historical world identities."""

from dataclasses import dataclass, field, replace

from pyrsistent import pmap, pset


def _update(postings, previous, current, member):
    result = postings
    for key in previous - current:
        remaining = result[key].remove(member)
        result = result.set(key, remaining) if remaining else result.remove(key)
    for key in current - previous:
        result = result.set(key, result.get(key, pset()).add(member))
    return result


def _sample_cues(sample):
    return (
        frozenset() if sample is None else frozenset((sample.trial.context, c) for c in sample.cues)
    )


def _sample_results(sample):
    return (
        frozenset()
        if sample is None
        else frozenset(
            (sample.content.name, sample.content.signature, source.publication)
            for source in sample.weight_sources
        )
    )


def _experience_cues(experience):
    return (
        frozenset()
        if experience is None
        else frozenset((experience.domain, experience.context, c) for c in experience.cues)
    )


def _experience_samples(experience):
    return (
        frozenset()
        if experience is None
        else frozenset(
            (experience.domain, experience.context, key) for key, _ in experience.samples
        )
    )


@dataclass(frozen=True)
class RecordIndex:
    sample_cues: object = field(default_factory=pmap)
    sample_results: object = field(default_factory=pmap)
    experience_cues: object = field(default_factory=pmap)
    experience_samples: object = field(default_factory=pmap)
    sample_positions: object = field(default_factory=pmap)

    def with_sample(self, previous, current, position=None):
        positions = self.sample_positions
        if previous is None:
            if position is None or current.key in positions:
                raise ValueError("new indexed sample requires its unique first position")
            positions = positions.set(current.key, position)
        return replace(
            self,
            sample_cues=_update(
                self.sample_cues, _sample_cues(previous), _sample_cues(current), current.key
            ),
            sample_results=_update(
                self.sample_results,
                _sample_results(previous),
                _sample_results(current),
                current.key,
            ),
            sample_positions=positions,
        )

    def with_experience(self, previous, current):
        return replace(
            self,
            experience_cues=_update(
                self.experience_cues,
                _experience_cues(previous),
                _experience_cues(current),
                current.key,
            ),
            experience_samples=_update(
                self.experience_samples,
                _experience_samples(previous),
                _experience_samples(current),
                current.key,
            ),
        )
