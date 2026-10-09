"""Trusted live-Session M1 evidence, never a controller or a restore format."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass

from nomos_kernel import K0OccurrenceRef

from nomos_c0.opening_construction_v1 import C0OpeningConstructionReceipt
from nomos_c0.program_runtime_v1 import C0AuthorSnapshot, C0OwnerGraphSession

RESIDENTS = (
    "huddled_one",
    "huddled_two",
    "ritual_resident",
    "wall_resident",
    "prison_resident_one",
    "prison_resident_two",
    "emma",
)
CHARGE_FIELDS = {
    "everflame": "charges",
    "reservoir": "charges",
    "charge_packet": "charges",
    "balloon": "charges",
    "balloon_power": "charges",
    "elemental_charge": "units",
    "magic_item": "charges",
}


@dataclass(frozen=True)
class M1Capture:
    # Object identity here is an in-process pairing check, not world identity.
    session: C0OwnerGraphSession = field(repr=False, compare=False)
    opening: C0OpeningConstructionReceipt
    snapshot: C0AuthorSnapshot


@dataclass(frozen=True)
class M1AuthorReport:
    initial: C0AuthorSnapshot
    current: C0AuthorSnapshot
    magic_items: tuple[tuple[object, object], ...]
    resources: tuple[tuple[object, int], ...]
    people: tuple[tuple[str, object], ...]
    payments: tuple[object, ...]
    alpha_proposal: object
    alpha_decision: object
    references: tuple[tuple[K0OccurrenceRef, object], ...]
    charge_balance: tuple[int, int]
    gold_balance: tuple[int, int]
    intervals: tuple[tuple[C0AuthorSnapshot, C0AuthorSnapshot], ...]
    unproven: tuple[str, ...]


def capture(session: C0OwnerGraphSession) -> M1Capture:
    """Capture authority once; later projections never read the live Session."""
    if type(session) is not C0OwnerGraphSession:
        raise ValueError("M1 capture requires a checked C0 Session")
    opening = session.author_opening_construction()
    if opening is None:
        raise ValueError("M1 capture requires the actual opening construction receipt")
    return M1Capture(session, opening, session.author_snapshot())


def _refs(value):
    if type(value) is K0OccurrenceRef:
        yield value
    elif is_dataclass(value) and not isinstance(value, type):
        for member in fields(value):
            yield from _refs(getattr(value, member.name))
    elif type(value) is tuple:
        for member in value:
            yield from _refs(member)


def _charge_total(snapshot):
    return sum(
        getattr(row.current_state, CHARGE_FIELDS[row.individual.family])
        for row in snapshot.objects
        if row.individual.family in CHARGE_FIELDS
    )


def _gold_total(snapshot):
    return sum(getattr(state, "gold", 0) for _, state in snapshot.owners) + sum(
        row.current_state.gold
        for row in snapshot.objects
        if row.individual.family in ("treasure_chest", "reward_box")
    )


def project(captures: tuple[M1Capture, ...]) -> M1AuthorReport:
    """Join current identity/source evidence without inventing missing history."""
    if (
        type(captures) is not tuple
        or not captures
        or any(type(item) is not M1Capture for item in captures)
    ):
        raise ValueError("M1 audit needs an ordered capture tuple")
    initial, current = captures[0], captures[-1]
    if initial.snapshot.occurrences or initial.snapshot.time != 0:
        raise ValueError("M1 initial capture must precede world advancement")
    for item in captures:
        if item.session is not initial.session or item.opening != initial.opening:
            raise ValueError("M1 audit cannot join foreign Sessions or openings")
    for before, after in zip(captures, captures[1:], strict=False):
        prefix = before.snapshot.occurrences
        if (
            after.snapshot.time < before.snapshot.time
            or after.snapshot.occurrences[: len(prefix)] != prefix
        ):
            raise ValueError("M1 captures do not preserve the published history prefix")

    snapshot = current.snapshot
    owners = dict(snapshot.owners)
    if not {"adventurer", "alpha", *RESIDENTS} <= owners.keys():
        raise ValueError("M1 audit requires the selected full-world owner roster")
    objects = {row.individual: row for row in snapshot.objects}
    if len(objects) != len(snapshot.objects):
        raise ValueError("M1 audit repeats an Object identity")
    originals = tuple(slot for slot in initial.opening.slots if slot.kind == "magic_item")
    if len(originals) != 5 or len({slot.individual for slot in originals}) != 5:
        raise ValueError("M1 audit requires five distinct original magic items")
    if {row.individual for row in snapshot.objects if row.individual.family == "magic_item"} != {
        slot.individual for slot in originals
    }:
        raise ValueError("M1 current magic inventory differs from its five original identities")
    magic = []
    for slot in originals:
        row = objects.get(slot.individual)
        if row is None or row.owner != slot.owner or row.formed_by is not None:
            raise ValueError("M1 original item differs from its actual opening binding")
        magic.append((slot, row))
    resources = tuple(
        (row, getattr(row.current_state, CHARGE_FIELDS[row.individual.family]))
        for row in snapshot.objects
        if row.individual.family in CHARGE_FIELDS
    )
    actors = {row.actor: row for row in snapshot.actors}
    for row, _ in resources:
        if row.individual.family == "elemental_charge":
            state = row.current_state
            elemental = actors.get(state.elemental)
            if (
                elemental is None
                or elemental.current_state.vital.life != "dead"
                or row.formed_by != state.formed_ref
                or row.predecessor != state.death_ref
            ):
                raise ValueError("M1 elemental charge is not linked to its actual dead Actor")
    queen, alpha = owners["emma"], owners["alpha"]
    people = tuple((name, owners[name]) for name in RESIDENTS)
    verified = queen.reward_account.verified
    if len({row.name for row in verified}) != len(verified):
        raise ValueError("M1 reward verification repeats a resident")
    payments = tuple(row.payment for row in verified if row.payment is not None)
    for receipt in payments:
        box = objects.get(receipt.box)
        if (
            box is None
            or box.individual.family != "reward_box"
            or receipt.resident not in RESIDENTS[:-1]
            or receipt.recipient != "adventurer"
        ):
            raise ValueError("M1 payment has a foreign box, resident or recipient")
    if alpha.trade_decision is not None and alpha.trade_decision.item not in {
        slot.individual for slot in originals
    }:
        raise ValueError("M1 Alpha decision is not about an original item")

    tape = {row.occurrence: row for row in snapshot.occurrences}
    if len(tape) != len(snapshot.occurrences):
        raise ValueError("M1 audit repeats a published occurrence")
    # Link evidence, not just counts or a matching numeric-looking label.
    roots = (
        tuple(row for _, row in magic),
        tuple(row for row, _ in resources),
        people,
        verified,
        alpha.tower_proposal,
        alpha.trade_decision,
        snapshot.actors,
    )
    refs = tuple(dict.fromkeys(_refs(roots)))
    if any(ref not in tape for ref in refs):
        raise ValueError("M1 state evidence references an unpublished occurrence")
    unproven = [
        "Per-source consumption or formation is not inferred from terminal balances.",
        "State/source links are not a tamper-resistant owner-state attestation.",
    ]
    if len(captures) < 3 and snapshot.occurrences:
        unproven.append("Intermediate resource transitions were not captured.")
    return M1AuthorReport(
        initial.snapshot,
        snapshot,
        tuple(magic),
        resources,
        people,
        payments,
        alpha.tower_proposal,
        alpha.trade_decision,
        tuple((ref, tape[ref]) for ref in refs),
        (_charge_total(initial.snapshot), _charge_total(snapshot)),
        (_gold_total(initial.snapshot), _gold_total(snapshot)),
        tuple((before.snapshot, after.snapshot) for before, after in zip(captures, captures[1:])),
        tuple(unproven),
    )
