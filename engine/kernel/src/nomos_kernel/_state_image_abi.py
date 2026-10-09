"""Private value carriers used by authoritative causal state images."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0OwnerKey, K0ProfileError


@dataclass(frozen=True)
class K0InitialOwnerState:
    """Keyed input used only to create a fresh authoritative state image."""

    owner: K0OwnerKey
    state: object


@dataclass(frozen=True)
class _K0OwnerState:
    owner: K0OwnerKey
    state: object


@dataclass(frozen=True)
class _K0OccurrenceCursor:
    next_value: int = 1

    def __post_init__(self) -> None:
        if type(self.next_value) is not int or self.next_value < 1:
            raise K0ProfileError("occurrence cursor must be a positive int")
