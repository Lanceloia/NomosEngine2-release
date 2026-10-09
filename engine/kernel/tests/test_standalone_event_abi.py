from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import nomos_kernel
import pytest
from nomos_kernel import _standalone_event_abi as subject
from nomos_kernel._owner_abi import _K0CapabilityRef

from nomos_kernel._standalone_event_abi import (
    _K0StandaloneEventDefinition,
    _K0StandaloneEventFormation,
    _K0StandaloneEventRequest,
)

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
NAMES = (
    "_K0StandaloneEventFormation",
    "_K0StandaloneEventRequest",
    "_K0StandaloneEventResolution",
    "_K0StandaloneEventResolver",
    "_K0StandaloneEventDefinition",
)


@dataclass(frozen=True)
class Focus:
    value: str

    def validate_for_k0(self) -> None:
        if type(self.value) is not str or not self.value:
            raise nomos_kernel.K0ProfileError("focus value must be nonempty")


@dataclass(frozen=True)
class Resolver:
    capability_ref: _K0CapabilityRef

    def resolve(self, focus, owner_views):
        return None


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


def test_standalone_event_abi_has_one_definition_and_no_legacy_shim() -> None:
    for name in NAMES:
        assert name not in nomos_kernel.__all__
    assert _top_level_definitions(
        KERNEL_ROOT / "nomos_kernel" / "_standalone_event_abi.py"
    ) == set(NAMES)
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_real_definition_and_request_use_engine_types() -> None:
    source = nomos_kernel.K0SourceSpecKey("standalone-test-source")
    focus = Focus("focus")
    resolver = Resolver(_K0CapabilityRef("standalone-test-resolver@1"))
    definition = _K0StandaloneEventDefinition(
        source, Focus, (), resolver
    )
    request = _K0StandaloneEventRequest(source, focus)
    formation = _K0StandaloneEventFormation(source)

    assert type(definition) is subject._K0StandaloneEventDefinition
    assert type(request) is subject._K0StandaloneEventRequest
    assert type(formation) is subject._K0StandaloneEventFormation

    with pytest.raises(nomos_kernel.K0ProfileError):
        _K0StandaloneEventRequest(source, object())
    with pytest.raises(nomos_kernel.K0ProfileError):
        _K0StandaloneEventDefinition(source, Focus, (), object())


def test_private_standalone_event_abi_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._standalone_event_abi;"
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"


def test_standalone_event_resolution_requires_an_exact_tuple_container() -> None:
    evidence = object()
    participants = object()
    exact = subject._K0StandaloneEventResolution(evidence, participants, ())
    assert exact.bindings == ()

    with pytest.raises(nomos_kernel.K0ProfileError, match="exact tuple"):
        subject._K0StandaloneEventResolution(evidence, participants, [])
    with pytest.raises(nomos_kernel.K0ProfileError, match="exact tuple"):
        subject._K0StandaloneEventResolution(
            evidence, participants, (item for item in ())
        )
