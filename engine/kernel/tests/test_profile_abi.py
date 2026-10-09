from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._profile_abi import (
    _K0_ROOTLESS_STATIC_OPENING,
    _K0RootlessStaticOpeningCapability,
)


def test_legacy_kernel_uses_the_extracted_nominal_capability() -> None:
    assert _K0RootlessStaticOpeningCapability is _K0RootlessStaticOpeningCapability
    assert _K0_ROOTLESS_STATIC_OPENING is _K0_ROOTLESS_STATIC_OPENING


def test_rootless_static_opening_is_one_exact_frozen_capability() -> None:
    assert type(_K0_ROOTLESS_STATIC_OPENING) is _K0RootlessStaticOpeningCapability
    assert _K0_ROOTLESS_STATIC_OPENING.version == "k0-rootless-static-opening-v1"

    with pytest.raises(FrozenInstanceError):
        _K0_ROOTLESS_STATIC_OPENING.version = "other"  # type: ignore[misc]

    with pytest.raises(K0ProfileError):
        _K0RootlessStaticOpeningCapability("other")

    with pytest.raises(K0ProfileError):
        _K0RootlessStaticOpeningCapability(True)  # type: ignore[arg-type]
