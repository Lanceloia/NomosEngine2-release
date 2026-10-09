from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import nomos_kernel
from nomos_kernel import _occurrence_codec_abi as subject
from nomos_kernel._owner_abi import _K0CapabilityRef

from nomos_kernel._occurrence_codec_abi import (
    _K0ParticipantsCodec,
    _K0SemanticEnvelopeCodec,
)

ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = ROOT / "engine" / "kernel" / "src"
MODULE_NAMES = (
    "_K0ParticipantsCodec",
    "_K0SemanticEnvelopeCodec",
    "_K0SemanticEnvelopeSpec",
    "_validate_semantic_envelope",
)
LEGACY_NAMES = (
    "_K0ParticipantsCodec",
    "_K0SemanticEnvelopeCodec",
    "_validate_semantic_envelope",
)


@dataclass(frozen=True)
class ParticipantsCodec:
    capability_ref: _K0CapabilityRef

    def encode(self, participants):
        return ("participants",)

    def decode(self, wire):
        return wire


@dataclass(frozen=True)
class EnvelopeCodec:
    capability_ref: _K0CapabilityRef
    version: str

    def encode(self, envelope):
        return ("envelope",)

    def decode(self, wire):
        return wire


@dataclass(frozen=True)
class Envelope:
    value: str


@dataclass(frozen=True)
class RoundTripEnvelopeCodec:
    capability_ref: _K0CapabilityRef
    version: str

    def encode(self, envelope):
        return (envelope.value,)

    def decode(self, wire):
        return Envelope(wire[0])


@dataclass(frozen=True)
class EnvelopeSpec:
    semantic_envelope_type: type[object]
    semantic_envelope_codec: RoundTripEnvelopeCodec


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


def test_occurrence_codecs_have_one_definition_and_no_legacy_shim() -> None:
    for name in LEGACY_NAMES:
        assert name not in nomos_kernel.__all__
    assert _top_level_definitions(
        KERNEL_ROOT / "nomos_kernel" / "_occurrence_codec_abi.py"
    ) == set(MODULE_NAMES)
    assert not (ROOT / "src" / "nomos_dawn" / "k0" / "_kernel.py").exists()


def test_real_protocol_checks_use_engine_types() -> None:
    participants = ParticipantsCodec(_K0CapabilityRef("participants-codec@1"))
    envelope = EnvelopeCodec(_K0CapabilityRef("envelope-codec@1"), "1")

    assert isinstance(participants, _K0ParticipantsCodec)
    assert isinstance(participants, subject._K0ParticipantsCodec)
    assert isinstance(envelope, _K0SemanticEnvelopeCodec)
    assert isinstance(envelope, subject._K0SemanticEnvelopeCodec)


def test_semantic_envelope_validation_is_engine_owned_and_codec_stable() -> None:
    envelope = Envelope("closed")
    spec = EnvelopeSpec(
        Envelope,
        RoundTripEnvelopeCodec(_K0CapabilityRef("envelope-codec@1"), "1"),
    )
    subject._validate_semantic_envelope(spec, envelope)


def test_private_occurrence_codec_abi_import_does_not_load_dawn() -> None:
    code = (
        "import sys,nomos_kernel._occurrence_codec_abi;"
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    )
    assert output == "False\n"
