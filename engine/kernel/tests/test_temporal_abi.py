from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import nomos_kernel
import pytest
from nomos_kernel import _coordinates, _temporal_abi
from nomos_kernel._coordinates import (
    _K0FixedTime,
    _K0OccurrenceCoordinate,
    _K0TemporalAdvanceRequest,
    _K0TemporalInterval,
)

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
COORDINATE_NAMES = (
    "_K0OccurrenceCoordinate",
    "_K0FixedTime",
    "_K0TemporalInterval",
    "_K0TemporalAdvanceRequest",
)
TEMPORAL_NAMES = (
    "_K0QuiescentOwnerTimeValidator",
    "_K0TemporalDefinitionKey",
    "_K0TemporalFocus",
    "_K0TemporalResolution",
    "_K0TemporalResolver",
    "_K0TemporalBasisCodec",
    "_K0TemporalDefinition",
    "_K0TemporalFormation",
)
NAMES = COORDINATE_NAMES + TEMPORAL_NAMES


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _all_defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_temporal_contracts_have_one_definition_and_no_legacy_shim() -> None:
    for name in COORDINATE_NAMES:
        assert name not in nomos_kernel.__all__
    for name in TEMPORAL_NAMES:
        assert name not in nomos_kernel.__all__

    assert _top_level_definitions(
        KERNEL_ROOT / "nomos_kernel" / "_coordinates.py"
    ) == set(COORDINATE_NAMES)
    assert _top_level_definitions(
        KERNEL_ROOT / "nomos_kernel" / "_temporal_abi.py"
    ) == set(TEMPORAL_NAMES)
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_coordinate_contracts_retain_exact_validation() -> None:
    start = _K0FixedTime(2)
    end = _K0FixedTime(3)
    interval = _K0TemporalInterval(start, end)
    request = _K0TemporalAdvanceRequest(interval)

    assert type(start) is _coordinates._K0FixedTime
    assert type(interval) is _coordinates._K0TemporalInterval
    assert type(request) is _coordinates._K0TemporalAdvanceRequest
    assert _K0OccurrenceCoordinate(None, 0) == (
        _coordinates._K0OccurrenceCoordinate(None, 0)
    )

    with pytest.raises(nomos_kernel.K0ProfileError):
        _K0FixedTime(True)
    with pytest.raises(nomos_kernel.K0ProfileError):
        _K0TemporalInterval(end, start)
    with pytest.raises(nomos_kernel.K0ProfileError):
        _K0TemporalAdvanceRequest(object())


def test_private_temporal_modules_do_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._coordinates,nomos_kernel._temporal_abi;"
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"


class _TemporalEvidence:
    def validate_for_k0(self) -> None:
        return None


class _TemporalParticipants:
    def validate_for_k0(self) -> None:
        return None


class _TemporalBinding:
    def __init__(self, key: str) -> None:
        self.key = key

    def validate_for_k0(self) -> None:
        return None


class _StrSubclass(str):
    pass


def test_temporal_resolution_accepts_only_the_three_legal_kinds() -> None:
    assert _temporal_abi._K0TemporalResolution("no_change").kind == "no_change"
    assert (
        _temporal_abi._K0TemporalResolution("not_applicable").kind
        == "not_applicable"
    )
    change = _temporal_abi._K0TemporalResolution(
        "change",
        _TemporalEvidence(),
        _TemporalParticipants(),
        (_TemporalBinding("a"),),
    )
    assert change.kind == "change"


def test_temporal_resolution_rejects_non_exact_or_unknown_kind() -> None:
    with pytest.raises(nomos_kernel.K0ProfileError, match="unknown kind"):
        _temporal_abi._K0TemporalResolution(_StrSubclass("no_change"))
    with pytest.raises(nomos_kernel.K0ProfileError, match="unknown kind"):
        _temporal_abi._K0TemporalResolution("bogus")


def test_temporal_resolution_rejects_payload_mutation_after_construction() -> None:
    resolution = _temporal_abi._K0TemporalResolution("not_applicable")
    object.__setattr__(resolution, "evidence", _TemporalEvidence())
    with pytest.raises(nomos_kernel.K0ProfileError):
        _temporal_abi._K0TemporalResolution.__post_init__(resolution)
