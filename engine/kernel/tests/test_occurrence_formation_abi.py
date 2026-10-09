from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import nomos_kernel
from nomos_kernel import _occurrence_formation_abi as subject

from nomos_kernel._occurrence_formation_abi import _K0CausalFormation

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
NAME = "_K0CausalFormation"


def _defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_causal_formation_has_one_definition_and_no_legacy_shim() -> None:
    assert _K0CausalFormation is subject._K0CausalFormation
    assert subject._K0CausalFormation.__module__ == (
        "nomos_kernel._occurrence_formation_abi"
    )
    assert NAME not in nomos_kernel.__all__
    assert _defined_names(
        KERNEL_ROOT / "nomos_kernel" / "_occurrence_formation_abi.py"
    ) == {NAME}
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_legacy_causal_formation_uses_the_engine_type_unchanged() -> None:
    predecessor = nomos_kernel.K0OccurrenceRef(1)
    law = nomos_kernel.K0CausalLawKey("law")
    formation = _K0CausalFormation(predecessor, law)

    assert type(formation) is subject._K0CausalFormation
    assert formation.predecessor is predecessor
    assert formation.causal_law is law


def test_private_occurrence_formation_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._occurrence_formation_abi;"
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"
