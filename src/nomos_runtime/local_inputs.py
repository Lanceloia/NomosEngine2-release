"""Immutable recipient-local inputs staged alongside successful world publication."""

from dataclasses import dataclass
from types import MappingProxyType

from .entities import Reference
from .errors import AdmissionError
from .terminals import CheckpointBasis, OpeningBasis, is_closed


@dataclass(frozen=True)
class InputIdentity:
    recipient: Reference
    kind: str
    sequence: int


@dataclass(frozen=True)
class InputCursor:
    recipient: Reference
    sequence: int


@dataclass(frozen=True)
class TerminalFeedback:
    source: str
    type_name: str
    value: object
    trigger: OpeningBasis | CheckpointBasis
    closed: OpeningBasis | CheckpointBasis


@dataclass(frozen=True)
class LocalInput:
    identity: InputIdentity
    payload: object


@dataclass(frozen=True)
class InputBatch:
    items: tuple[LocalInput, ...]
    cursor: InputCursor
    complete: bool


def stage_inputs(session, receipts, terminal, *, opening=False, choice=None):
    additions = {}
    if choice is not None:
        recipient, selected = choice
        additions[recipient] = [("choice", selected)]
    for receipt in receipts:
        additions.setdefault(receipt.recipient, []).append(
            ("opening" if opening else "delivery", receipt)
        )
    if is_closed(terminal) and (opening or not is_closed(session._terminal)):
        feedback = TerminalFeedback(
            terminal.rule,
            session.program.terminal.result_type,
            terminal.value,
            terminal.trigger,
            terminal.closed,
        )
        for recipient in terminal.recipients:
            additions.setdefault(recipient, []).append(("terminal", feedback))
    if not additions:
        return session._local_inputs
    streams = dict(session._local_inputs)
    for recipient, entries in additions.items():
        prior = streams.get(recipient, ())
        streams[recipient] = prior + tuple(
            LocalInput(InputIdentity(recipient, kind, len(prior) + offset), payload)
            for offset, (kind, payload) in enumerate(entries, 1)
        )
    return MappingProxyType(streams)


def read_inputs(session, actor, *, after=None, limit=128):
    recipient = session._actor(actor)
    if session._busy:
        raise AdmissionError("SessionBusy", "local inputs require a completed publication")
    if type(limit) is not int or limit < 1:
        raise ValueError("local input limit must be a positive integer")
    stream = session._local_inputs.get(recipient, ())
    if after is not None and (
        type(after) is not InputCursor
        or after.recipient != recipient
        or type(after.sequence) is not int
        or not 0 <= after.sequence <= len(stream)
    ):
        raise AdmissionError("WrongInputCursor", "cursor must name this Actor's published input")
    start = 0 if after is None else after.sequence
    stop = min(start + limit, len(stream))
    return InputBatch(stream[start:stop], InputCursor(recipient, stop), stop == len(stream))
