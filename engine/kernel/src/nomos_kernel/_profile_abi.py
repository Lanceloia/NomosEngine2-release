"""Domain-neutral profile construction capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0ProfileError


@dataclass(frozen=True)
class _K0RootlessStaticOpeningCapability:
    """Sealed opt-in for a producer-free private static opening profile."""

    version: str = "k0-rootless-static-opening-v1"

    def __post_init__(self) -> None:
        if (
            type(self.version) is not str
            or self.version != "k0-rootless-static-opening-v1"
        ):
            raise K0ProfileError("rootless static opening capability is malformed")


_K0_ROOTLESS_STATIC_OPENING = _K0RootlessStaticOpeningCapability()
