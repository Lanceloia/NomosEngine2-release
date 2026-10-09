"""Compiler nominal types stay independent of machine and backend contracts."""

import ast
from pathlib import Path

import pytest

from nomos_c0.nominal_types_v1 import (
    EventSortRef,
    IRValidationError,
    ObjectSortHierarchy,
    ObjectSortRef,
    ObjectSortSpecialization,
    SemanticIdentity,
)


def _sort(name: str) -> ObjectSortRef:
    return ObjectSortRef(SemanticIdentity(f"TEST.{name}@1"))


@pytest.mark.parametrize("value", ("", "test.A@1", "TEST..A@1", "TEST.A@0", 1, True))
def test_semantic_identity_requires_an_exact_versioned_name(value):
    with pytest.raises(IRValidationError):
        SemanticIdentity(value)


def test_sort_references_are_distinct_nominal_categories():
    identity = SemanticIdentity("TEST.A@1")
    assert ObjectSortRef(identity) != EventSortRef(identity)
    for cls in (ObjectSortRef, EventSortRef):
        with pytest.raises(IRValidationError):
            cls(identity.value)


def test_transitive_specialization_and_unrelated_sort():
    item, tool, blade, stone = (_sort(name) for name in ("ITEM", "TOOL", "BLADE", "STONE"))
    hierarchy = ObjectSortHierarchy(
        tuple(sorted((item, tool, blade, stone))),
        tuple(
            sorted((ObjectSortSpecialization(tool, item), ObjectSortSpecialization(blade, tool)))
        ),
    )
    assert hierarchy.accepts(item, item)
    assert hierarchy.accepts(item, tool)
    assert hierarchy.accepts(item, blade)
    assert not hierarchy.accepts(tool, item)
    assert not hierarchy.accepts(item, stone)
    with pytest.raises(IRValidationError):
        hierarchy.accepts(item, _sort("UNDECLARED"))
    with pytest.raises(IRValidationError):
        hierarchy.accepts(item, EventSortRef(item.identity))


def test_unknown_cycle_duplicate_and_foreign_reference_reject():
    item, tool, foreign = (_sort(name) for name in ("ITEM", "TOOL", "FOREIGN"))
    edge = ObjectSortSpecialization(tool, item)
    with pytest.raises(IRValidationError):
        ObjectSortHierarchy(tuple(sorted((item, tool))), (ObjectSortSpecialization(tool, foreign),))
    with pytest.raises(IRValidationError):
        ObjectSortHierarchy(tuple(sorted((item, tool))), (edge, edge))
    with pytest.raises(IRValidationError):
        ObjectSortHierarchy(
            tuple(sorted((item, tool))),
            tuple(sorted((edge, ObjectSortSpecialization(item, tool)))),
        )
    with pytest.raises(IRValidationError):
        ObjectSortSpecialization(item, item)


def test_nominal_and_formation_ir_import_only_standard_library_and_each_other():
    root = Path(__file__).resolve().parents[2] / "src" / "nomos_c0"
    allowed = {"nominal_types_v1", "dataclasses", "enum", "re", "__future__"}
    for name in ("nominal_types_v1.py", "event_formation_ir_v2.py"):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level in (0, 1) and node.module in allowed
