"""Shared compiler resource bounds, independent of authored world semantics."""

from __future__ import annotations

from dataclasses import dataclass

from .author_contract_v1 import C0LawError


class C0CompileLimitError(C0LawError):
    """An expansion limit, not a claim that the world is semantically invalid."""

    def __init__(self, resource: str, actual: int, limit: int, stage: str):
        self.resource = resource
        self.actual = actual
        self.limit = limit
        self.stage = stage
        super().__init__(f"C0-COMPILE-LIMIT: {stage}: {resource}={actual} exceeds limit={limit}")


@dataclass(frozen=True)
class C0CompileBudget:
    ports_canonical_bytes: int = 524288
    ports_source_bytes: int = 4194304
    nominal_records: int = 256
    law_definitions: int = 256
    actions: int = 512
    causal_edges: int = 4096
    event_results: int = 512
    value_read_paths: int = 8192
    finite_offers: int = 256

    def check(self, resource: str, actual: int, *, stage: str) -> None:
        limit = getattr(self, resource)
        if actual > limit:
            raise C0CompileLimitError(resource, actual, limit, stage)


# This is a compiler resource policy, not a Source switch or K0 settlement policy.
COMPILE_BUDGET = C0CompileBudget()
