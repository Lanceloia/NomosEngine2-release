from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import nomos_kernel
import pytest
from nomos_kernel import _identity, _owner_abi

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
OWNER_ABI_NAMES = (
    "_K0WireAtom",
    "_K0CanonicalWirePayload",
    "_checked_label",
    "_require_unique",
    "_validate_closed_host_object",
    "_K0MotivatingIntentionRef",
    "_K0RuntimePropositionRef",
    "_K0CapabilityRef",
    "_K0DeclaredSourceInput",
    "_K0SealedEvidence",
    "_K0ClosedParticipants",
    "_K0SealedBinding",
    "_K0SealedIntentionBasis",
    "_K0FixedFamilyReferent",
    "_K0ReadOnlyOwnerView",
    "_K0OwnerContribution",
    "_K0LocalIdentityValue",
    "_K0OwnerView",
    "_K0CrossOwnerInvariant",
    "_K0OccurrenceContribution",
    "_K0Owner",
    "_validate_owner",
)
OWNER_ABI_DEFINED_NAMES = tuple(name for name in OWNER_ABI_NAMES if name != "_checked_label")


def test_legacy_machine_consumes_the_single_kernel_identity_abi() -> None:
    for name in nomos_kernel.__all__:
        assert getattr(nomos_kernel, name).__module__ == "nomos_kernel._identity"


def test_identity_coordinates_reject_non_exact_or_invalid_values() -> None:
    with pytest.raises(nomos_kernel.K0ProfileError):
        nomos_kernel.K0OwnerKey(True)
    with pytest.raises(nomos_kernel.K0ProfileError):
        nomos_kernel.K0SourceSpecKey(" source")
    with pytest.raises(nomos_kernel.K0ProfileError):
        nomos_kernel.K0OccurrenceRef(True)
    with pytest.raises(nomos_kernel.K0ProfileError):
        nomos_kernel.K0OccurrenceRef(0)


def test_local_slot_preserves_the_existing_coordinate_shape() -> None:
    slot = nomos_kernel.K0LocalIdentitySlot(
        "result", nomos_kernel.K0OwnerKey("owner"), "occurrence"
    )
    assert slot.owner == nomos_kernel.K0OwnerKey("owner")
    assert slot.output_family == "occurrence"


def test_closed_host_config_rejects_python_type_expressions() -> None:
    for annotation in (list[str], tuple[str, ...], tuple[str, ...] | None, str | int):
        with pytest.raises(nomos_kernel.K0ProfileError, match="recursively frozen"):
            _owner_abi._validate_closed_host_object((annotation,), "typed output")


def test_public_kernel_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel;print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"


def test_owner_abi_has_one_definition_and_no_legacy_shim() -> None:
    assert importlib.util.find_spec("nomos_dawn") is None

    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_kernel_leaf_has_no_reverse_project_import() -> None:
    for path in sorted(KERNEL_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = (node.module,)
            for module in modules:
                root = module.split(".", 1)[0]
                assert root == "nomos_kernel" or root in sys.stdlib_module_names


def test_legacy_k0_package_has_no_new_compatibility_module() -> None:
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_private_owner_carriers_reject_invalid_values() -> None:
    with pytest.raises(nomos_kernel.K0ProfileError):
        _owner_abi._K0MotivatingIntentionRef(True)
    with pytest.raises(nomos_kernel.K0ProfileError):
        _owner_abi._K0RuntimePropositionRef(0)
    with pytest.raises(nomos_kernel.K0ProfileError):
        _owner_abi._K0OwnerView(nomos_kernel.K0OwnerKey("owner"), object())


def test_private_references_reenter_class_laws_on_local_identity_consumption() -> None:
    for ref_type in (
        _owner_abi._K0MotivatingIntentionRef,
        _owner_abi._K0RuntimePropositionRef,
    ):
        valid = ref_type(1)
        slot = nomos_kernel.K0LocalIdentitySlot(
            "slot", nomos_kernel.K0OwnerKey("owner"), valid.family
        )
        consumed = _owner_abi._K0LocalIdentityValue(nomos_kernel.K0OccurrenceRef(1), slot, valid)
        assert consumed.referent is valid

        mutated = ref_type(1)
        object.__setattr__(mutated, "value", 0)
        object.__setattr__(mutated, "__post_init__", lambda: None)
        with pytest.raises(nomos_kernel.K0ProfileError, match="positive int"):
            mutated.validate_for_k0()
        with pytest.raises(nomos_kernel.K0ProfileError, match="positive int"):
            _owner_abi._K0LocalIdentityValue(nomos_kernel.K0OccurrenceRef(1), slot, mutated)


def test_owner_identity_products_reenter_occurrence_reference_law() -> None:
    class Contribution:
        owner = nomos_kernel.K0OwnerKey("owner")

        def validate_for_k0(self) -> None:
            pass

    slot = nomos_kernel.K0LocalIdentitySlot(
        "slot",
        nomos_kernel.K0OwnerKey("owner"),
        _owner_abi._K0MotivatingIntentionRef.family,
    )
    referent = _owner_abi._K0MotivatingIntentionRef(1)
    occurrence = nomos_kernel.K0OccurrenceRef(1)
    local = _owner_abi._K0LocalIdentityValue(occurrence, slot, referent)
    product = _owner_abi._K0OccurrenceContribution(occurrence, Contribution(), (local,))
    assert product.resolved_identities == (local,)

    for invalid in ("1", object.__new__(nomos_kernel.K0OccurrenceRef)):
        with pytest.raises(nomos_kernel.K0ProfileError):
            _owner_abi._K0LocalIdentityValue(invalid, slot, referent)
        with pytest.raises(nomos_kernel.K0ProfileError):
            _owner_abi._K0OccurrenceContribution(invalid, Contribution(), ())

    mutated = nomos_kernel.K0OccurrenceRef(1)
    object.__setattr__(mutated, "value", 0)
    object.__setattr__(mutated, "__post_init__", lambda: None)
    with pytest.raises(nomos_kernel.K0ProfileError, match="positive int"):
        _owner_abi._K0LocalIdentityValue(mutated, slot, referent)
    with pytest.raises(nomos_kernel.K0ProfileError, match="positive int"):
        _owner_abi._K0OccurrenceContribution(mutated, Contribution(), ())


def test_private_owner_abi_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._owner_abi;"
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


class _SlotSubclass(nomos_kernel.K0LocalIdentitySlot):
    """A subclass that must not pass as the exact closed slot carrier."""


def test_local_identity_slot_refuses_impersonating_and_hollow_owners() -> None:
    real = nomos_kernel.K0OwnerKey("owner")
    spoof = _SpoofOwnerKey(real)
    assert spoof == real and hash(spoof) == hash(real)
    for foreign in (spoof, "owner", object(), None):
        with pytest.raises(nomos_kernel.K0ProfileError):
            nomos_kernel.K0LocalIdentitySlot("slot", foreign, "family")
    slot = nomos_kernel.K0LocalIdentitySlot("slot", real, "family")
    assert type(slot.owner) is nomos_kernel.K0OwnerKey


def test_local_identity_slot_reenters_its_nested_owner_field_law() -> None:
    mutated = nomos_kernel.K0OwnerKey("owner")
    object.__setattr__(mutated, "value", True)
    with pytest.raises(nomos_kernel.K0ProfileError):
        nomos_kernel.K0LocalIdentitySlot("slot", mutated, "family")


def test_slot_reentry_helper_refuses_subclass_hollow_and_post_mutation() -> None:
    real = nomos_kernel.K0OwnerKey("owner")
    hollow = _SlotSubclass("slot", real, "family")
    with pytest.raises(nomos_kernel.K0ProfileError):
        _identity._require_local_identity_slot(hollow, "test slot")

    slot = nomos_kernel.K0LocalIdentitySlot("slot", real, "family")
    object.__setattr__(slot, "owner", _SpoofOwnerKey(real))
    with pytest.raises(nomos_kernel.K0ProfileError):
        _identity._require_local_identity_slot(slot, "test slot")

    object.__setattr__(slot, "owner", real)
    object.__setattr__(slot, "value", " bad")
    with pytest.raises(nomos_kernel.K0ProfileError):
        _identity._require_local_identity_slot(slot, "test slot")

    healthy = nomos_kernel.K0LocalIdentitySlot("slot", real, "family")
    assert _identity._require_local_identity_slot(healthy, "test slot") is healthy


def test_slot_reentry_uses_class_laws_after_instance_method_shadowing() -> None:
    owner = nomos_kernel.K0OwnerKey("owner")
    object.__setattr__(owner, "value", True)
    object.__setattr__(owner, "__post_init__", lambda: None)
    with pytest.raises(nomos_kernel.K0ProfileError):
        nomos_kernel.K0LocalIdentitySlot("slot", owner, "family")

    slot = nomos_kernel.K0LocalIdentitySlot("slot", nomos_kernel.K0OwnerKey("owner"), "family")
    object.__setattr__(slot, "owner", object())
    object.__setattr__(slot, "__post_init__", lambda: None)
    with pytest.raises(nomos_kernel.K0ProfileError):
        _identity._require_local_identity_slot(slot, "test slot")


def test_slot_reentry_rejects_hollow_exact_carriers_finitely() -> None:
    with pytest.raises(nomos_kernel.K0ProfileError):
        nomos_kernel.K0LocalIdentitySlot("slot", object.__new__(nomos_kernel.K0OwnerKey), "family")
    with pytest.raises(nomos_kernel.K0ProfileError):
        _identity._require_local_identity_slot(
            object.__new__(nomos_kernel.K0LocalIdentitySlot), "test slot"
        )
