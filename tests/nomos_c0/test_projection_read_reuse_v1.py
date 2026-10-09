"""Projection reuse is local to one read and never spans a K0 transition."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, replace

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._settlement_outcome_abi import K0Published
from test_control_binding_v1 import _inputs
from test_seat_offer_preview_v0 import _authored as _preview
from test_world_binding_v1 import _compile

from nomos_c0 import program_runtime_v1 as runtime
from tools.c0_profile_pipeline import _snapshot_digest, measure


@pytest.fixture(scope="module")
def compiled():
    lib, ports, source, assets = _inputs()
    return _compile(lib, ports, source), assets


def _count_reads(monkeypatch, session):
    calls = Counter()
    original = session._runtime.read_owner

    def read(key):
        calls[key] += 1
        return original(key)

    monkeypatch.setattr(session._runtime, "read_owner", read)
    return calls


@pytest.mark.parametrize("projection", ["offers", "form_frame", "_seat_projection"])
def test_each_projection_reuses_only_requested_owners_and_then_discards_them(
    compiled, monkeypatch, projection
):
    program, assets = compiled
    session = program.start(assets)
    calls = _count_reads(monkeypatch, session)
    first = getattr(session, projection)("sender")
    assert calls and all(count == 1 for count in calls.values())
    keys = {item.symbol: item.owner.key for item in program.owners}
    expected = {keys["scene"], keys["sender"]}
    # World-stop settlement now belongs to K0; a frame reads its terminal result.
    assert set(calls) == expected
    assert getattr(session, projection)("sender") == first
    assert all(count == 2 for count in calls.values())


def test_submit_generates_one_menu_but_still_rechecks_k0(compiled, monkeypatch):
    program, assets = compiled
    session = program.start(assets)
    offer = session.offers("sender")[0]
    calls = []
    original = session._project_offers

    def project(seat, reads):
        calls.append(seat)
        return original(seat, reads)

    monkeypatch.setattr(session, "_project_offers", project)
    result = session.submit("sender", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert calls == ["sender"]
    assert result.occurrences[0].source == dict(program.actions)[offer.entry].source_key
    assert session._runtime.action_value_history()[-1].cost == 4


def test_current_owner_invariant_is_checked_again_on_next_projection(compiled):
    program, assets = compiled
    session = program.start(assets)
    session.offers("sender")
    owner = next(item.owner.key for item in program.owners if item.symbol == "sender")
    session._runtime._states = tuple(
        replace(row, state=replace(row.state, name="")) if row.owner == owner else row
        for row in session._runtime._states
    )
    with pytest.raises(K0ProfileError):
        session.offers("sender")


class _UncachedReads:
    def __init__(self, k0):
        self.runtime = k0

    def owner(self, key):
        return self.runtime.read_owner(key).view

    def individual(self, ref):
        return self.runtime.read_individual(ref).view


def _delivery(program, assets):
    session = program.start(assets)
    observations = []
    for seat, entry in (("sender", "dispatch"), ("receiver", "confirm_alt")):
        frame = session.continue_form(seat)
        observations.append((frame, session.author_snapshot()))
        offer = next(item for item in frame.offers if item.entry == entry)
        observations.append(session.submit(seat, entry, dict(offer.payload)))
        observations.append(session.author_snapshot())
    assert session.form_frame("sender").outcome == "delivered"
    return (
        observations,
        session._runtime.action_value_history(),
        tuple(asdict(item) for item in session.formation_trace()),
    )


def test_reuse_matches_uncached_real_action_event_due_and_control(compiled, monkeypatch):
    program, assets = compiled
    cached = _delivery(program, assets)
    monkeypatch.setattr(runtime, "_ProjectionReads", _UncachedReads)
    assert _delivery(program, assets) == cached


def test_object_preview_reuses_view_but_action_and_formation_invalidate_it(monkeypatch):
    lib, ports, source, assets = _preview()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    calls = _count_reads(monkeypatch, session)
    offer = next(item for item in session.offers("actor") if item.entry == "inspect")
    assert offer.preview == (("condition", "ready"),)
    assert len(calls) == 3 and all(count == 1 for count in calls.values())
    assert isinstance(session.submit("actor", "inspect", dict(offer.payload)), K0Published)
    assert not any(item.entry == "inspect" for item in session.offers("actor"))
    assert isinstance(session.submit("actor", "make", {}), K0Published)
    offers = session.offers("actor")
    assert any(item.entry == "inspect" and item.label == "Inspect new" for item in offers)
    assert not any(item.entry == "inspect" and item.label == "Inspect old" for item in offers)


def test_measurement_digest_matches_real_opening_and_formed_objects_across_runs():
    lib, ports, source, assets = _preview()
    program = _compile(lib, ports, source)
    digests = []
    for _ in range(2):
        session = program.start(assets)
        offer = next(item for item in session.offers("actor") if item.entry == "inspect")
        assert isinstance(session.submit("actor", "inspect", dict(offer.payload)), K0Published)
        assert isinstance(session.submit("actor", "make", {}), K0Published)
        snapshot = session.author_snapshot()
        assert len(snapshot.objects) == 2
        digests.append(_snapshot_digest(snapshot, session._runtime._individual_scope))
    assert digests[0] == digests[1]


def test_measurement_tool_runs_the_real_pipeline_and_records_stage_boundaries(tmp_path):
    documents = _inputs()
    paths = []
    for name, document in zip(("lib", "ports", "source", "assets"), documents, strict=True):
        path = tmp_path / f"sample.{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths.append(path)
    report = measure(*paths, seat="sender", entry="dispatch", steps=1)
    stages = report["stages"]
    assert [row["stage"] for row in stages] == [
        "load",
        "nominal",
        "ports",
        "check_source",
        "backend",
        "check_assets_standalone",
        "start_including_assets",
        "continue_0",
        "read_0",
        "offers_0",
        "submit_0",
    ]
    assert not report["profiled"] and report["final_time"] == 0
    assert all(row["owner_reads"] is None for row in stages[:7])
    assert all(row["owner_reads"] > 0 for row in stages[7:])
    assert [row["source"] for row in report["occurrences"]] == [
        "c0.parcel.dispatch",
        "c0.parcel.depart",
        "c0.parcel.notice",
        "c0.parcel.manifest",
    ]


@pytest.mark.parametrize("steps", [True, 0, 101])
def test_measurement_tool_rejects_unbounded_or_noninteger_replay(steps):
    with pytest.raises(ValueError, match="steps"):
        measure(None, None, None, None, seat="sender", entry="dispatch", steps=steps)
