from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import nomos_kernel
import pytest
from nomos_kernel import _rule_products_abi as subject

from nomos_kernel._rule_products_abi import (
    K0RuleResult,
    _K0Activation,
)

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
NAMES = ("_K0Activation", "K0RuleResult", "_validate_rule_result")


@dataclass(frozen=True)
class Evidence:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class Participants:
    def validate_for_k0(self) -> None:
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


def test_rule_products_have_one_definition_and_no_legacy_shim() -> None:
    for name in NAMES:
        assert name not in nomos_kernel.__all__
    assert _top_level_definitions(
        KERNEL_ROOT / "nomos_kernel" / "_rule_products_abi.py"
    ) == set(NAMES)
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_real_rule_products_use_engine_types_and_validation() -> None:
    activation = _K0Activation(
        "activation", Evidence(), Participants(), ()
    )
    result = K0RuleResult((), ())

    assert type(activation) is subject._K0Activation
    assert type(result) is subject.K0RuleResult

    with pytest.raises(nomos_kernel.K0ProfileError):
        _K0Activation("", Evidence(), Participants(), ())
    slot = nomos_kernel.K0LocalIdentitySlot(
        "slot", nomos_kernel.K0OwnerKey("owner"), "family"
    )
    with pytest.raises(nomos_kernel.K0ProfileError):
        K0RuleResult((), (slot, slot))
    with pytest.raises(nomos_kernel.K0ProfileError):
        K0RuleResult([], ())  # type: ignore[arg-type]

    object.__setattr__(result, "local_output_requests", [slot])
    with pytest.raises(nomos_kernel.K0ProfileError):
        result.__post_init__()


def test_private_rule_products_abi_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._rule_products_abi;"
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"


class _SpoofOwnerKey:
    """Hash/equality-impersonating value that is not an exact K0OwnerKey."""

    def __init__(self, key: nomos_kernel.K0OwnerKey) -> None:
        self._key = key

    def __hash__(self) -> int:
        return hash(self._key)

    def __eq__(self, other: object) -> bool:
        return other == self._key or other is self._key


def test_rule_result_reenters_the_local_slot_law_on_consumption() -> None:
    real = nomos_kernel.K0OwnerKey("owner")
    slot = nomos_kernel.K0LocalIdentitySlot("slot", real, "family")
    object.__setattr__(slot, "owner", _SpoofOwnerKey(real))
    with pytest.raises(nomos_kernel.K0ProfileError):
        K0RuleResult((), (slot,))
    with pytest.raises(nomos_kernel.K0ProfileError):
        subject._validate_rule_result((), K0RuleResult((), ()), (slot,), ())


def test_rule_result_consumption_uses_class_law_after_instance_mutation() -> None:
    valid = K0RuleResult((), ())
    subject._validate_rule_result((), valid, (), ())

    mutated = K0RuleResult((), ())
    object.__setattr__(mutated, "contributions", [])
    object.__setattr__(mutated, "__post_init__", lambda: None)
    with pytest.raises(nomos_kernel.K0ProfileError, match="exact tuple"):
        subject._validate_rule_result((), mutated, (), ())


def test_rule_result_preserves_canonical_order_for_valid_slots() -> None:
    first = nomos_kernel.K0LocalIdentitySlot(
        "a", nomos_kernel.K0OwnerKey("owner"), "family"
    )
    second = nomos_kernel.K0LocalIdentitySlot(
        "b", nomos_kernel.K0OwnerKey("owner"), "family"
    )
    result = K0RuleResult((), (first, second))
    assert result.local_output_requests == (first, second)
