from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import nomos_kernel
import pytest
from nomos_kernel import _state_image_abi as subject

from nomos_kernel._state_image_abi import (
    K0InitialOwnerState,
    _K0OccurrenceCursor,
    _K0OwnerState,
)

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
NAMES = ("K0InitialOwnerState", "_K0OwnerState", "_K0OccurrenceCursor")


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_state_image_carriers_have_one_definition_and_no_legacy_shim() -> None:
    for name in NAMES:
        assert name not in nomos_kernel.__all__
    assert _top_level_definitions(
        KERNEL_ROOT / "nomos_kernel" / "_state_image_abi.py"
    ) == set(NAMES)
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_legacy_state_image_carriers_use_engine_types_unchanged() -> None:
    owner = nomos_kernel.K0OwnerKey("owner")
    state = object()
    opening = K0InitialOwnerState(owner, state)
    current = _K0OwnerState(owner, state)
    cursor = _K0OccurrenceCursor()

    assert type(opening) is subject.K0InitialOwnerState
    assert type(current) is subject._K0OwnerState
    assert type(cursor) is subject._K0OccurrenceCursor
    assert opening.owner is owner and opening.state is state
    assert current.owner is owner and current.state is state
    assert cursor.next_value == 1

    for value in (0, -1, True):
        with pytest.raises(nomos_kernel.K0ProfileError):
            _K0OccurrenceCursor(value)


def test_private_state_image_abi_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._state_image_abi;"
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"
