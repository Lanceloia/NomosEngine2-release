"""Worker-local measurement state must not survive into the next sample.

Neutral fakes exercise the real worker without compiling or running a world.
"""

import io
import json
import sys
import weakref
from types import SimpleNamespace

import pytest

from tools import release_runtime_gate as gate


class Tracked:
    def __init__(self, **values):
        self.__dict__.update(values)


class Report(dict):
    pass


class Published:
    pass


@pytest.fixture
def run_worker(monkeypatch, capsys):
    document = SimpleNamespace(to_data=lambda: {})
    bundle = SimpleNamespace(assets=document)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(gate, "input_fingerprint", lambda *args: {})
    replacements = {
        "nomos_c0.author_document_v1.read_author_document": lambda *args: document,
        "nomos_c0.declarative_graph_ports_v0.check_graph_ports": lambda *args: None,
        "nomos_c0.declarative_nominal_v0.check_nominal_lib": lambda *args: None,
        "nomos_c0.source_bundle_v1.read_source_bundle": lambda *args: bundle,
        "nomos_kernel._settlement_outcome_abi.K0Published": Published,
        "tools.c0_profile_pipeline._snapshot_digest": lambda *args: "same",
        "tools.c0_profile_pipeline._local_value": lambda *args: (),
    }
    for target, replacement in replacements.items():
        monkeypatch.setattr(target, replacement)

    def run(commands, sampler, parcel=None, program=None, journey=None):
        monkeypatch.setattr("tools.c0_benchmark_m1_continue.measure_program", sampler)
        monkeypatch.setattr("nomos_c0.owner_graph_v1.compile_owner_graph", lambda *args: parcel)
        monkeypatch.setattr(
            "nomos_c0.source_bundle_v1.compile_source_bundle", lambda *args: program
        )
        if journey is not None:
            monkeypatch.setattr("tools.c0_benchmark_m1_route.Journey", journey)
        monkeypatch.setattr(
            sys, "stdin", io.StringIO("".join(json.dumps({"sample": c}) + "\n" for c in commands))
        )
        gate.worker(
            gate.Path(__file__).resolve().parents[2],
            gate.Path("unused"),
            gate.Path("unused"),
            parcel_sessions=2,
        )
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    return run


def test_report_is_released_before_the_next_collection_and_sample(run_worker, monkeypatch):
    references = []
    retained = []
    collections = []
    collect = gate.gc.collect

    def collecting():
        collections.append(any(ref() is not None for ref in references))
        return collect()

    def sample(*args):
        retained.append(any(ref() is not None for ref in references))
        report = Report(run_seconds=0)
        references.append(weakref.ref(report))
        return report

    monkeypatch.setattr(gate.gc, "collect", collecting)
    reports = run_worker(["short", "short", "quit"], sample)
    assert collections == retained == [False, False]
    assert all(ref() is None for ref in references)
    assert reports[1:] == [{"run_seconds": 0}] * 2


def test_parcel_views_are_released_between_sessions_and_commands(run_worker):
    references = []
    retained = []

    def tracked(**values):
        value = Tracked(**values)
        references.append(weakref.ref(value))
        return value

    class Session:
        def __init__(self):
            self.rows = []
            # Bind only rows, not self: fake cycles must not hide worker-local retention.
            self._runtime = SimpleNamespace(
                occurrence_history=lambda rows=self.rows: rows, _individual_scope=None
            )

        def form_frame(self, seat):
            if seat == "sender":
                retained.append(any(ref() is not None for ref in references))
            return SimpleNamespace(offers=[tracked(entry=seat, payload={})])

        def submit(self, seat, entry, payload):
            self.rows[:] = [SimpleNamespace(source=SimpleNamespace(value="c0.parcel.confirm"))]
            self.rows[:] *= 4 if seat == "sender" else 6
            return Published()

        def defer_form(self, seat):
            pass

        def continue_form(self, seat):
            self.rows.append(SimpleNamespace(source=SimpleNamespace(value="c0.parcel.arrive.due")))

        def author_snapshot(self):
            return tracked(
                owners=(
                    ("scene", tracked(parcel=SimpleNamespace(status="arrived"))),
                    ("receiver", tracked(receipt=True)),
                ),
                occurrences=tuple(self.rows),
                form_choices=(0, 1),
            )

    def sample(*args):
        retained.append(any(ref() is not None for ref in references))
        return {}

    reports = run_worker(
        ["parcel", "short", "quit"], sample, SimpleNamespace(start=lambda _: Session())
    )
    assert retained == [False, False, False]
    assert all(ref() is None for ref in references)
    assert reports[1]["digests"] == ["same", "same"]
    assert reports[1]["sessions_per_pair"] == 2


def test_full_views_are_released_before_the_next_command(run_worker):
    references = []

    def tracked(**values):
        value = Tracked(**values)
        references.append(weakref.ref(value))
        return value

    class Session:
        time = 1

        def __init__(self):
            self._runtime = SimpleNamespace(_individual_scope=None, action_value_history=lambda: ())

        def form_frame(self, seat):
            return tracked(finished=True, outcome="departed_palace")

        def author_snapshot(self):
            return tracked(
                owners=(
                    (
                        "ritual_resident",
                        tracked(
                            site="palace_exit",
                            rescue_state="safe",
                            vital=SimpleNamespace(life="alive"),
                            rescue_ref=1,
                        ),
                    ),
                    ("ritual", SimpleNamespace(status="interrupted")),
                ),
                occurrences=(1,),
                objects=(),
                actors=(),
            )

        def appraisal_history(self):
            return ()

    class Journey:
        def __init__(self, session):
            self.actions = []

        def rescue(self):
            pass

    retained = []

    def sample(*args):
        retained.append(any(ref() is not None for ref in references))
        return {}

    reports = run_worker(
        ["full", "short", "quit"],
        sample,
        program=SimpleNamespace(start=lambda _: Session()),
        journey=Journey,
    )
    assert retained == [False]
    assert all(ref() is None for ref in references)
    assert reports[1]["occurrences"] == 1
    assert reports[1]["state_digest"] == "same"
