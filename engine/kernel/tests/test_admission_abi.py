from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import nomos_kernel
from nomos_kernel import _admission_abi as subject

from nomos_kernel._admission_abi import (
    _K0AdmissionProjection,
    _K0RuntimePropositionRecord,
    _K0RuntimePropositionState,
)
from nomos_kernel._owner_abi import _K0RuntimePropositionRef

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
NAMES = (
    "_K0RuntimePropositionContent",
    "_K0RuntimePropositionCodec",
    "_K0RuntimePropositionRecord",
    "_K0RuntimePropositionState",
    "_K0AdmissionProjection",
    "_K0AdmissionCapability",
    "_K0RuntimePropositionAdmissionCapability",
    "_K0RuntimePropositionInvariant",
    "_validate_admission_projection",
    "_admit_source",
    "_find_runtime_proposition",
)


@dataclass(frozen=True)
class Evidence:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class Participants:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class Binding:
    key: str

    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class Content:
    source: nomos_kernel.K0SourceSpecKey

    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class OrdinaryAdmission:
    capability_ref: object = subject._K0CapabilityRef("ordinary-admission")

    def admit(self, payload, owner_views):
        return subject._K0AdmissionProjection(
            Evidence(), Participants(), (Binding("ordinary"),)
        )


@dataclass(frozen=True)
class RuntimeAdmission:
    capability_ref: object = subject._K0CapabilityRef("runtime-admission")

    def admit_with_runtime_propositions(self, payload, owner_views, runtime_propositions):
        return subject._K0AdmissionProjection(
            Evidence(), Participants(), (Binding(str(len(runtime_propositions.records))),)
        )


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _all_defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def test_admission_abi_has_one_definition_and_no_legacy_shim() -> None:
    for name in NAMES:
        assert name not in nomos_kernel.__all__
    assert _top_level_definitions(
        KERNEL_ROOT / "nomos_kernel" / "_admission_abi.py"
    ) == set(NAMES)
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_real_projection_and_runtime_state_use_the_engine_types() -> None:
    projection = _K0AdmissionProjection(
        Evidence(), Participants(), (Binding("binding"),)
    )
    assert type(projection) is subject._K0AdmissionProjection

    source = nomos_kernel.K0SourceSpecKey("source")
    content = Content(source)
    record = _K0RuntimePropositionRecord(
        _K0RuntimePropositionRef(1), source, "1", content
    )
    state = _K0RuntimePropositionState((record,), 2)
    assert type(state) is subject._K0RuntimePropositionState
    assert subject._find_runtime_proposition(state, source, content) is record


def test_admission_dispatch_uses_only_the_declared_capability_shape() -> None:
    source = nomos_kernel.K0SourceSpecKey("source")
    state = subject._K0RuntimePropositionState()
    ordinary = subject._admit_source(OrdinaryAdmission(), Content(source), (), state)
    runtime = subject._admit_source(RuntimeAdmission(), Content(source), (), state)
    assert ordinary.bindings == (Binding("ordinary"),)
    assert runtime.bindings == (Binding("0"),)


def test_private_admission_abi_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._admission_abi;"
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"
