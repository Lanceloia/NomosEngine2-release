"""Private causal/time coordinates and the bounded advance request carrier."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0ProfileError


@dataclass(frozen=True)
class _K0OccurrenceCoordinate:
    dependency_stage: int | None
    causal_wave_depth: int

    def __post_init__(self) -> None:
        if self.dependency_stage is not None and (
            type(self.dependency_stage) is not int or self.dependency_stage < 0
        ):
            raise K0ProfileError(
                "occurrence dependency stage must be None or a non-negative int"
            )
        if type(self.causal_wave_depth) is not int or self.causal_wave_depth < 0:
            raise K0ProfileError("occurrence causal wave depth must be a non-negative int")


@dataclass(frozen=True, order=True)
class _K0FixedTime:
    """The private, fixed-discrete coordinate carried by the authoritative image."""

    ordinal: int = 0

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise K0ProfileError("fixed time ordinal must be a non-negative int")


@dataclass(frozen=True)
class _K0TemporalInterval:
    t0: _K0FixedTime
    t1: _K0FixedTime

    def __post_init__(self) -> None:
        if type(self.t0) is not _K0FixedTime or type(self.t1) is not _K0FixedTime:
            raise K0ProfileError("temporal interval must use exact fixed times")
        if self.t1.ordinal <= self.t0.ordinal:
            raise K0ProfileError("temporal interval must be positive")


@dataclass(frozen=True)
class _K0TemporalAdvanceRequest:
    interval: _K0TemporalInterval

    def __post_init__(self) -> None:
        if type(self.interval) is not _K0TemporalInterval:
            raise K0ProfileError("temporal advance request must carry one exact interval")
