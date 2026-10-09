"""Focused tests for temporal runtime validation ownership."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._temporal_abi import _K0TemporalResolution
from nomos_kernel._temporal_runtime import _validate_temporal_resolution


def test_temporal_runtime_accepts_exact_no_output_resolution() -> None:
    _validate_temporal_resolution(object(), _K0TemporalResolution("no_change"))


def test_temporal_runtime_rejects_foreign_resolution_carrier() -> None:
    with pytest.raises(K0ProfileError, match="malformed"):
        _validate_temporal_resolution(object(), object())


def test_temporal_runtime_import_does_not_load_dawn() -> None:
    script = (
        "import sys; import nomos_kernel._temporal_runtime; "
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    output = subprocess.check_output(
        [sys.executable, "-c", script], env=env, text=True
    ).strip()
    assert output == "False"


class _TemporalEvidence:
    def validate_for_k0(self) -> None:
        return None


class _TemporalParticipants:
    def validate_for_k0(self) -> None:
        return None


class _TemporalBinding:
    key = "a"

    def validate_for_k0(self) -> None:
        return None


class _TemporalSpec:
    evidence_type = _TemporalEvidence
    participants_type = _TemporalParticipants
    binding_keys = ("a",)
    binding_types = (_TemporalBinding,)


def _mutation_prone_no_output() -> _K0TemporalResolution:
    return _K0TemporalResolution("no_change")


def test_temporal_runtime_seals_post_construction_kind_mutation() -> None:
    resolution = _mutation_prone_no_output()
    object.__setattr__(resolution, "kind", "bogus")
    with pytest.raises(K0ProfileError, match="unknown kind"):
        _validate_temporal_resolution(_TemporalSpec(), resolution)


def test_temporal_runtime_seals_post_construction_payload_mutation() -> None:
    resolution = _K0TemporalResolution("not_applicable")
    object.__setattr__(resolution, "evidence", _TemporalEvidence())
    with pytest.raises(K0ProfileError, match="cannot carry a payload"):
        _validate_temporal_resolution(_TemporalSpec(), resolution)


def test_temporal_runtime_keeps_source_shape_rejection_after_reentry() -> None:
    class _ForeignEvidence:
        def validate_for_k0(self) -> None:
            return None

    resolution = _K0TemporalResolution(
        "change",
        _ForeignEvidence(),
        _TemporalParticipants(),
        (_TemporalBinding(),),
    )
    with pytest.raises(K0ProfileError, match="wrong source carrier"):
        _validate_temporal_resolution(_TemporalSpec(), resolution)


def test_temporal_consumer_edge_calls_the_runtime_validator() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "libraries"
        / "mind"
        / "src"
        / "nomos_mind"
        / "_legacy_session_temporal.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "_validate_temporal_resolution" for alias in node.names)
        for node in ast.walk(tree)
    )
    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_validate_temporal_resolution"
        for node in ast.walk(tree)
    )
    assert imported and called
