"""Private occurrence-formation markers for the causal machine."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0CausalLawKey, K0OccurrenceRef


@dataclass(frozen=True)
class _K0CausalFormation:
    predecessor: K0OccurrenceRef
    causal_law: K0CausalLawKey
