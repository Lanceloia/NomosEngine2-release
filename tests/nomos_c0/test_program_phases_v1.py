"""Compiler, Assets binding and live controls have separate dependencies."""

from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError
from importlib.util import find_spec

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_control_binding_v1 import _inputs
from test_nominal_signatures_v1 import forbid_frontend
from test_program_binding_v1 import _block, _checked
from test_world_binding_v1 import _compile

from nomos_c0 import (
    graph_contracts_v1,
    owner_graph_v1,
    program_binding_v1,
    program_runtime_v1,
    program_start_v1,
)
from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.program_runtime_v1 import C0ControlCommand, C0OwnerGraphProgram
from nomos_c0.program_start_v1 import check_assets


@pytest.fixture(scope="module")
def compiled():
    lib, ports, source, assets = _inputs()
    return _compile(lib, ports, source), assets


def test_runtime_start_and_contract_imports_do_not_load_graph_compiler():
    code = """
import sys
from nomos_c0 import graph_contracts_v1, program_runtime_v1, program_start_v1
for module in (
    'graph_frontend_v1', 'owner_graph_v1', 'program_binding_v1',
    'native_program_binding_v1', 'declarative_graph_ports_v0', 'declarative_nominal_v0',
    'action_start_v0', 'action_event_v0', 'derived_event_v0', 'game_form_v1',
    'library_v1', 'program_v0', 'event_jump', 'event_jump_native', 'latch_native_v1',
):
    assert 'nomos_c0.' + module not in sys.modules, module
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_compile_composition_has_no_transitional_contract_or_runtime_exports():
    assert owner_graph_v1.__all__ == ["compile_owner_graph"]
    for name in (
        "C0GraphLibrary",
        "C0OwnerGraphProgram",
        "C0BindingError",
        "C0ControlCommand",
        "_opening",
        "_source",
        "_leaf_type",
        "_bind_object_owner_plan",
        "check_owner_graph",
    ):
        assert not hasattr(owner_graph_v1, name), name
    assert C0OwnerGraphProgram.__module__ == "nomos_c0.program_runtime_v1"
    assert graph_contracts_v1.C0GraphLibrary.__module__ == "nomos_c0.graph_contracts_v1"


def test_generated_frontend_has_no_native_entry_and_does_not_bind_program(monkeypatch):
    lib, ports, source, _ = _inputs()
    assert find_spec("nomos_c0.native_program_binding_v1") is None
    monkeypatch.setattr(program_binding_v1, "bind_program", forbid_frontend)
    ir, layout = _checked(lib, ports, source)
    assert ir.world is layout.world
    source["actions"][0]["template"] = "missing"
    with pytest.raises(C0LawError):
        _checked(lib, ports, source)


def test_checked_assets_are_frozen_and_detached_before_k0_allocation(compiled, monkeypatch):
    program, original = compiled
    assets = deepcopy(original)
    monkeypatch.setattr(program_start_v1._K0InMemorySession, "create", forbid_frontend)
    binding = check_assets(program, assets)
    assets["opening"]["sender"]["name"] = "changed"
    assets["action_value_openings"].clear()
    assert (
        next(row.state.name for row in binding.states if hasattr(row.state, "sent_ref")) == "Mira"
    )
    assert len(binding.action_values) == 2
    assert binding.controllers == (
        ("sender", "human_prompt", None),
        ("receiver", "human_prompt", None),
    )
    with pytest.raises(FrozenInstanceError):
        binding.controllers = ()


def test_start_consumes_one_checked_binding_and_allocates_one_session(compiled, monkeypatch):
    program, original = compiled
    checks, allocations = [], []
    original_check = program_start_v1.check_assets
    original_create = program_start_v1._K0InMemorySession.create

    def check(*args):
        binding = original_check(*args)
        checks.append(binding)
        return binding

    def create(*args, **kwargs):
        assert len(checks) == 1
        binding = checks[0]
        assert args == (program.profile, binding.states)
        assert kwargs == {
            "initial_time": binding.time,
            "opening_individuals": binding.objects,
            "opening_periodic_dues": binding.periodic,
            "opening_action_values": binding.action_values,
            "opening_actors": binding.actors,
        }
        runtime = original_create(*args, **kwargs)
        allocations.append(runtime)
        return runtime

    monkeypatch.setattr(program_start_v1, "check_assets", check)
    monkeypatch.setattr(program_start_v1._K0InMemorySession, "create", create)
    assets = deepcopy(original)
    session = program.start(assets)
    assert allocations == [session._runtime]
    assert session._controllers is checks[0].controllers
    assets.clear()
    assert dict(session.read("sender").fields)["sender.name"] == "Mira"


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("late", "opening time exceeds GameForm end"),
        ("controller_count", "controllers do not fill"),
        ("controller_seat", "foreign seat"),
        ("controller_profile", "foreign appraisal"),
        ("controller_duplicate", "repeat or omit"),
        ("opening_guard", "opening guard"),
        ("occurrence", "opening occurrence or instance identity cannot be authored"),
    ],
)
def test_invalid_c0_opening_rejects_before_session_allocation(
    compiled, monkeypatch, defect, message
):
    program, original = compiled
    live = program.start(deepcopy(original))
    before = live.author_snapshot()
    assets = deepcopy(original)
    assets["controllers"] = [
        {"seat": "sender", "mode": "human_prompt"},
        {"seat": "receiver", "mode": "human_prompt"},
    ]
    if defect == "late":
        assets["time"] = 9
    elif defect == "controller_count":
        assets["controllers"].pop()
    elif defect == "controller_seat":
        assets["controllers"][0]["seat"] = "foreign"
    elif defect == "controller_profile":
        assets["controllers"][0].update(mode="finite_appraisal", profile="prefer_alt")
    elif defect == "controller_duplicate":
        assets["controllers"][0]["seat"] = "receiver"
    elif defect == "opening_guard":
        assets["opening"]["scene"]["parcel"]["id"] = "wrong"
    else:
        assets["opening"]["sender"]["sent_ref"] = 1
    monkeypatch.setattr(program_start_v1._K0InMemorySession, "create", forbid_frontend)
    with pytest.raises(C0BindingError, match=message):
        program.start(assets)
    assert live.author_snapshot() == before


def test_start_then_live_run_need_neither_source_frontend_nor_backend(compiled, monkeypatch):
    program, assets = compiled
    _block(monkeypatch)
    monkeypatch.setattr(program_binding_v1, "bind_program", forbid_frontend)
    first = program.start(deepcopy(assets))
    second = program.start(deepcopy(assets))
    assert type(first) is program_runtime_v1.C0OwnerGraphSession
    baseline = first.author_snapshot()
    other = second.author_snapshot()
    first.read("sender")
    offer = first.form_frame("sender").offers[0]
    assert first.author_snapshot() == baseline
    monkeypatch.setattr(program_start_v1, "check_assets", forbid_frontend)
    result = first.apply_control(C0ControlCommand("submit", "sender", offer)).result
    assert isinstance(result, K0Published)
    assert first._runtime.action_value_history()[-1].cost == 4
    frame = first.apply_control(C0ControlCommand("continue", "sender")).result
    assert frame.time == 3 and frame.ready_seats == ("receiver",)
    offer = first.form_frame("receiver").offers[0]
    assert isinstance(
        first.apply_control(C0ControlCommand("submit", "receiver", offer)).result, K0Published
    )
    assert first.form_frame("sender").outcome == "delivered"
    assert second.author_snapshot() == other
    trace = first.formation_trace()
    assert trace and all(item.occurrence is not None for item in trace)
