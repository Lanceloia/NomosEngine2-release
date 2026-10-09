"""Production file origins accompany the checked Law, not a runtime file lookup."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest
import yaml
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_document_v1 import (
    C0AuthorDocument,
    C0SourceContext,
    C0SourceIndex,
    parse_author_document,
    read_author_document,
)
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_binding_v1 import bind_program

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _document(raw, file):
    return parse_author_document(yaml.safe_dump(raw, sort_keys=False), file=file, format="yaml")


def _sample(*, amount=3, pure=False):
    def record(name, definitions):
        return {
            "name": name,
            "fields": [{"name": key, "type": value} for key, value in definitions.items()],
            "invariant": None,
        }

    lib = {
        "schema": "c0.nominal_lib.v1",
        "records": [
            record("Scene", {"tokens": {"int": [0, 10]}}),
            record("Actor", {"name": {"str": [1, 24]}}),
            record("Attempt", {"actor": {"str": [1, 24]}}),
            record("Envelope", {"action": "occurrence_ref"}),
        ],
        "owners": [
            {
                "symbol": name,
                "key": f"origin.{name}",
                "version": "v1",
                "write": "replace_one",
                "state": state,
                "identity_field": None if name == "scene" else "name",
                "seat_read": ["tokens"] if name == "scene" else ["name"],
            }
            for name, state in (("scene", "Scene"), ("a", "Actor"), ("b", "Actor"))
        ],
        "lawdefs": [
            {
                "name": "spend",
                "family": "action",
                "formals": {"amount": "int"},
                "body": {
                    "value": {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": {"require": [{"same_actor": "actor.name == payload.actor"}]},
                        "effects": [
                            {
                                "payment": {
                                    "debit": "scene.tokens",
                                    "amount": {"arg": "amount"},
                                    "floor": 0,
                                }
                            }
                        ],
                        "outputs": {"action": {"ref": "occurrence"}},
                    }
                },
            }
        ],
    }
    if pure:
        lib["pure_definitions"] = [
            {
                "name": "positive",
                "parameters": {"number": "int"},
                "result": "bool",
                "stage": "admission",
                "body": {"require": [{"positive": "number > 0"}]},
            }
        ]
        lib["lawdefs"][0]["body"]["value"]["guard"] = {
            "call": {"ref": "positive", "args": {"number": {"ref": "scene.tokens"}}}
        }
    ports = {
        "schema": "c0.graph_ports.v1",
        "scene_owner": "scene",
        "offer_provider": {"name": "finite_value", "version": "1", "limit": 8},
        "actions": [
            {
                "symbol": "use",
                "actor": "a",
                "payload": "Attempt",
                "envelope": "Envelope",
                "actor_identity_field": "name",
                "payload_actor_field": "actor",
                "effects": {"scene": {"tokens": "remaining"}, "actor": {}},
                "envelope_fields": {"action": "action"},
                "schedule": None,
                "value": {
                    "read": ["scene.tokens", "actor.name", "payload.actor"],
                    "fields": {},
                    "write_paths": ["scene.tokens"],
                    "construct": [],
                    "collections": {},
                },
            }
        ],
        "events": [],
        "due_events": [],
    }
    source = {
        "schema": "c0.owner_graph.v6",
        "owners": ["scene", "a", "b"],
        "lawdefs": [],
        "offer_provider": {"name": "finite_value", "version": "1"},
        "game_form": {"mode": "manual"},
        "actions": [
            {
                "name": f"use_{actor}",
                "template": "use",
                "actor": actor,
                "source_key": f"origin.use-{actor}",
                "event_type": f"origin.use-{actor}.action",
                "law": {"ref": "spend", "args": {"amount": amount}},
            }
            for actor in ("a", "b")
        ],
        "events": [],
        "seats": [
            {
                "name": actor,
                "actor": actor,
                "entries": [f"use_{actor}"],
                "read": [f"{actor}.name", "scene.tokens"],
                "offers": [
                    {
                        "entry": f"use_{actor}",
                        "label": "Use",
                        "when": {"const": True},
                        "payload": {},
                    }
                ],
            }
            for actor in ("a", "b")
        ],
    }
    return lib, ports, source


def _compile(documents):
    lib, ports, source = documents
    checked = check_nominal_lib(lib)
    library = check_graph_ports(ports, checked)
    return compile_owner_graph(library, source)


def _assets(tokens=2):
    return {
        "schema": "c0.owner_graph.assets.v1",
        "opening": {
            "scene": {"tokens": tokens},
            "a": {"name": "a"},
            "b": {"name": "b"},
        },
    }


def _failure(program, session, actor):
    action = dict(program.actions)[f"use_{actor}"]
    scene = session._runtime.read_owner(action.scene_owner.key).view
    owner = session._runtime.read_owner(action.actor_owner.key).view
    return action.value.false_guard_clauses(
        {
            "scene": scene,
            "actor": owner,
            "payload": action.payload_type(actor),
        }
    )


def _no_context(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    assert type(value) not in (C0AuthorDocument, C0SourceContext, C0SourceIndex)
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _no_context(getattr(value, field.name), seen)
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _no_context(key, seen)
            _no_context(child, seen)
    elif type(value) in (list, tuple):
        for child in value:
            _no_context(child, seen)


def test_one_lib_two_source_files_retain_actual_call_arguments_and_port_locations():
    lib, ports, source = _sample()
    libdoc, portdoc = _document(lib, "shared.lib.yaml"), _document(ports, "shared.ports.yaml")
    first = _document(source, "first.source.yaml")
    source["actions"][0]["law"]["args"]["amount"] = 4
    second = _document(source, "second.source.yaml")
    programs = [_compile((libdoc, portdoc, doc)) for doc in (first, second)]
    for program, source_doc, amount in zip(programs, (first, second), (3, 4), strict=True):
        session = program.start(_assets())
        before = session.author_snapshot()
        assert isinstance(session.submit("a", "use_a", {}), K0NotAdmitted)
        assert session.author_snapshot() == before
        (failure,) = _failure(program, session, "a")
        assert failure.path == "effects.payment.sufficient"
        binding, port, definition, expression = failure.provenance
        assert binding.name == "use_a" and binding.arguments == (("amount", amount),)
        assert binding.span == source_doc.spans["actions", 0, "law"]
        assert port.span == portdoc.spans["actions", 0]
        assert definition.name == "spend" and definition.span == libdoc.spans["lawdefs", 0]
        assert (
            expression.span == libdoc.spans["lawdefs", 0, "body", "value", "effects", 0, "payment"]
        )
        (other,) = _failure(program, session, "b")
        assert other.provenance[0].span == source_doc.spans["actions", 1, "law"]
        _no_context(program)


def test_file_compile_then_edit_delete_bind_start_run_never_reopens_sources(tmp_path, monkeypatch):
    paths = []
    for raw, part in zip(_sample(amount=1), ("lib", "ports", "source"), strict=True):
        path = tmp_path / f"test.{part}.yaml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        paths.append(path)
    documents = tuple(read_author_document(path) for path in paths)
    checked = check_nominal_lib(documents[0])
    library = check_graph_ports(documents[1], checked)
    ir, layout = check_owner_graph(library, documents[2])
    paths[0].write_text("changed: true\n", encoding="utf-8")
    paths[1].unlink()
    paths[2].unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError("Bind/Start/Run reread a source file")

    monkeypatch.setattr(Path, "read_text", forbidden)
    program = bind_program(ir, layout)
    session = program.start(_assets(tokens=1))
    assert isinstance(session.submit("a", "use_a", {}), K0Published)
    assert isinstance(session.submit("b", "use_b", {}), K0NotAdmitted)
    (failure,) = _failure(program, session, "b")
    assert failure.provenance[0].span == documents[2].spans["actions", 1, "law"]
    assert failure.provenance[-1].span.digest == documents[0].digest
    assert len(session._runtime.occurrence_history()) == 1


def test_actual_pure_call_keeps_both_definition_and_named_body_source():
    documents = tuple(
        _document(raw, name)
        for raw, name in zip(
            _sample(pure=True),
            ("world.lib.yaml", "world.ports.yaml", "world.source.yaml"),
            strict=True,
        )
    )
    program = _compile(documents)
    session = program.start(_assets(tokens=0))
    failures = _failure(program, session, "a")
    named = next(failure for failure in failures if failure.names == ("positive",))
    assert [frame.kind for frame in named.provenance] == [
        "source_binding",
        "port",
        "law_definition",
        "pure_call",
        "pure_definition",
        "expression",
    ]
    assert named.provenance[3].span.path == ("lawdefs", 0, "body", "value", "guard")
    assert named.provenance[-1].span.path == (
        "pure_definitions",
        0,
        "body",
        "require",
        0,
        "positive",
    )
    _no_context(program.program_ir)


def test_lib_and_source_laws_locate_all_four_transition_kinds():
    documents = [
        read_author_document(ROOT / f"parcel_delivery_v0.{part}.json")
        for part in ("lib", "ports", "source")
    ]
    lib, source = documents[0].to_data(), documents[2].to_data()
    lib["lawdefs"] = [source["lawdefs"].pop(0)]
    documents[0] = _document(lib, "parcel.lib.yaml")
    documents[2] = _document(source, "parcel.source.yaml")
    program = _compile(documents)
    values = [
        ("actions", "dispatch", dict(program.actions)["dispatch"].value, documents[0], 0),
        ("events", "depart", dict(program.events)["depart"].value, documents[2], 1),
        ("events", "notice", dict(program.events)["notice"].value, documents[2], 2),
        ("due_events", "arrive", dict(program.due_laws)["arrive"].value, documents[2], 4),
    ]
    for collection, name, value, document, law_index in values:
        frames = value.guard_ir.expression.provenance
        assert frames[0].name == name
        assert frames[0].span.path[0] == collection
        assert frames[1].span.file == str(ROOT / "parcel_delivery_v0.ports.json")
        assert frames[2].span == document.spans["lawdefs", law_index]
    session = program.start(json.loads((ROOT / "parcel_delivery_v0.a.assets.json").read_text()))
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    session.defer_form("sender")
    session.defer_form("receiver")
    session.continue_form("sender")
    assert [item.source.value for item in session._runtime.occurrence_history()] == [
        "c0.parcel.dispatch",
        "c0.parcel.depart",
        "c0.parcel.notice",
        "c0.parcel.manifest",
        "c0.parcel.arrive.due",
    ]
    _no_context(program)


def test_unlocated_low_level_data_never_borrows_caller_coordinates():
    lib, ports, source = _sample()
    program = _compile((lib, ports, _document(source, "only.source.yaml")))
    (failure,) = _failure(program, program.start(_assets()), "a")
    assert failure.provenance[0].span.file == "only.source.yaml"
    assert all(frame.span is None for frame in failure.provenance[1:])


def test_selected_branch_locates_named_guard_without_blame_for_other_branch():
    lib, ports, source = _sample(amount=1)
    lib["lawdefs"][0]["body"]["value"]["guard"] = {
        "if": {
            "when": "actor.name == 'a'",
            "then": {"require": [{"selected": "scene.tokens > 3"}]},
            "else": {"require": [{"other": "scene.tokens > 0"}]},
        }
    }
    documents = tuple(
        _document(raw, name)
        for raw, name in zip(
            (lib, ports, source), ("lib.yaml", "ports.yaml", "source.yaml"), strict=True
        )
    )
    program = _compile(documents)
    session = program.start(_assets())
    (failure,) = _failure(program, session, "a")
    assert failure.names == ("selected",)
    assert (
        failure.provenance[-1].span
        == documents[0].spans[
            "lawdefs", 0, "body", "value", "guard", "if", "then", "require", 0, "selected"
        ]
    )
    assert _failure(program, session, "b") == ()
    assert isinstance(session.submit("b", "use_b", {}), K0Published)


def test_terminal_production_reader_preserves_all_three_documents(tmp_path, monkeypatch, capsys):
    from nomos_c0 import owner_graph_play_v1 as play

    arguments = []
    for raw, part in zip(
        (*_sample(amount=1), _assets()), ("lib", "ports", "source", "assets"), strict=True
    ):
        path = tmp_path / f"demo.{part}.yaml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        arguments.extend((f"--{part}", str(path)))
    original = play.compile_owner_graph
    seen = []

    def capture(library, document):
        assert type(document) is C0AuthorDocument
        assert library.lib_context.locate("").file.endswith("demo.lib.yaml")
        assert library.ports_context.locate("").file.endswith("demo.ports.yaml")
        result = original(library, document)
        seen.append(result)
        return result

    monkeypatch.setattr(play, "compile_owner_graph", capture)
    monkeypatch.setattr("builtins.input", lambda prompt: "quit")
    assert play.main(arguments) == 0
    assert len(seen) == 1
    output = capsys.readouterr().out
    assert "Seats: a, b" in output
    assert "law_definition" not in output and "source_binding" not in output


def test_origin_metadata_is_not_a_nominal_type_or_owner_version_change():
    lib, ports, source = _sample(pure=True)
    located = check_nominal_lib(_document(lib, "lib.yaml"))
    unlocated = check_nominal_lib(lib)
    assert located.signatures == unlocated.signatures
    assert [item.owner.owner_version for item in located.owners] == [
        item.owner.owner_version for item in unlocated.owners
    ]
    assert all(item.source_context is None for item in located.record_layout.pure_definitions)
    with pytest.raises(ValueError):
        from nomos_c0.author_document_v1 import C0OriginFrame

        C0OriginFrame("binding", "use", "actions", arguments=(("name", []),))


def test_operation_selection_retains_actual_source_using_and_ports_implementation():
    documents = [
        read_author_document(ROOT / f"object_target_v1.{part}.yaml")
        for part in ("lib", "ports", "source")
    ]
    source = documents[2].to_data()
    assets = yaml.safe_load((ROOT / "object_target_v1.assets.yaml").read_text())
    for index, (selection, law, expected_ready) in enumerate(
        (
            ("consuming_inspection", "action.inspect_consume", False),
            ("preserving_inspection", "action.inspect_preserve", True),
        )
    ):
        source["operation_bindings"][0]["using"] = selection
        document = _document(source, f"{selection}.source.yaml")
        program = _compile((*documents[:2], document))
        action = dict(program.actions)["inspect"]
        frames = action.value.guard_ir.expression.provenance
        assert [frame.kind for frame in frames] == [
            "source_binding",
            "operation_selection",
            "operation_implementation",
            "port",
            "law_definition",
            "expression",
        ]
        assert frames[0].span == document.spans["actions", 1, "operation"]
        assert frames[1].span == document.spans["operation_bindings", 0, "using"]
        assert frames[1].arguments == (("using", selection), ("law", law))
        assert (
            frames[2].span == documents[1].spans["operations", 0, "implementations", index, "law"]
        )
        assert frames[4].name == law
        session = program.start(assets)
        offer = next(item for item in session.offers("actor") if item.label == "Inspect old")
        assert isinstance(session.submit("actor", offer.entry, dict(offer.payload)), K0Published)
        assert session.author_object_instances()[0].current_state.ready is expected_ready
        _no_context(program)
