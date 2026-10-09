"""Private codecs for occurrence participants and semantic envelopes."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nomos_kernel import K0ProfileError
from nomos_kernel._canonical_wire import _canonical_wire
from nomos_kernel._owner_abi import (
    _K0CanonicalWirePayload,
    _K0CapabilityRef,
    _K0ClosedParticipants,
    _validate_closed_host_object,
)


@runtime_checkable
class _K0ParticipantsCodec(Protocol):
    capability_ref: _K0CapabilityRef

    def encode(self, participants: _K0ClosedParticipants) -> _K0CanonicalWirePayload: ...

    def decode(self, wire: _K0CanonicalWirePayload) -> _K0ClosedParticipants: ...


@runtime_checkable
class _K0SemanticEnvelopeCodec(Protocol):
    """Codec for one source-declared, exact semantic-envelope carrier."""

    capability_ref: _K0CapabilityRef
    version: str

    def encode(self, envelope: object) -> _K0CanonicalWirePayload: ...

    def decode(self, wire: _K0CanonicalWirePayload) -> object: ...


class _K0SemanticEnvelopeSpec(Protocol):
    semantic_envelope_type: type[object]
    semantic_envelope_codec: _K0SemanticEnvelopeCodec


def _validate_semantic_envelope(
    spec: _K0SemanticEnvelopeSpec, envelope: object
) -> None:
    """Prove one source's named envelope is exact, closed and codec-stable."""
    if type(envelope) is not spec.semantic_envelope_type:
        raise K0ProfileError("semantic envelope has the wrong exact source carrier")
    _validate_closed_host_object(envelope, "semantic envelope")
    try:
        payload = _canonical_wire(spec.semantic_envelope_codec.encode(envelope))
        decoded = spec.semantic_envelope_codec.decode(payload)
    except Exception as error:
        raise K0ProfileError("semantic envelope codec failed") from error
    if type(decoded) is not spec.semantic_envelope_type or decoded != envelope:
        raise K0ProfileError("semantic envelope codec round-trip is incompatible")
