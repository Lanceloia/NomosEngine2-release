"""Domain-neutral identity coordinates for the causal machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class K0ProfileError(ValueError):
    """A closed kernel profile, carrier, or authoritative image is malformed."""


def _checked_label(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise K0ProfileError(f"{label} must be a non-empty, trimmed str")
    return value


@dataclass(frozen=True, order=True)
class K0OwnerKey:
    value: str

    def __post_init__(self) -> None:
        _checked_label(self.value, "owner key")


@dataclass(frozen=True, order=True)
class K0SourceSpecKey:
    value: str

    def __post_init__(self) -> None:
        _checked_label(self.value, "source spec key")


@dataclass(frozen=True, order=True)
class K0CausalLawKey:
    value: str

    def __post_init__(self) -> None:
        _checked_label(self.value, "causal law key")


@dataclass(frozen=True, order=True)
class K0EventTypeKey:
    value: str

    def __post_init__(self) -> None:
        _checked_label(self.value, "event type key")


@dataclass(frozen=True, order=True)
class K0OccurrenceRef:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise K0ProfileError("occurrence reference must be a positive int")


class K0OccurrenceFamily(Enum):
    ACTION = "action"
    EVENT = "event"


@dataclass(frozen=True, order=True)
class K0LocalIdentitySlot:
    value: str
    owner: K0OwnerKey
    output_family: str

    def __post_init__(self) -> None:
        _checked_label(self.value, "local identity slot")
        if type(self.owner) is not K0OwnerKey:
            raise K0ProfileError("local identity slot owner must be an exact owner key")
        try:
            K0OwnerKey.__post_init__(self.owner)
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("local identity slot owner is malformed") from error
        _checked_label(self.output_family, "local identity output family")


def _require_local_identity_slot(value: object, label: str) -> K0LocalIdentitySlot:
    """Re-enter one exact local identity slot and its nested owner-field law.

    Consumption boundaries must not trust a slot only because its class is exact: a hollow,
    subclassed or post-mutated slot can still carry an impersonating owner value. Re-running the
    slot law re-checks the exact owner type and the owner key's own field law.
    """

    if type(value) is not K0LocalIdentitySlot:
        raise K0ProfileError(f"{label} must be an exact local identity slot")
    try:
        K0LocalIdentitySlot.__post_init__(value)
    except (AttributeError, TypeError) as error:
        raise K0ProfileError(f"{label} is malformed") from error
    return value
