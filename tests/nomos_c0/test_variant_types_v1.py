"""Tagged-sum typing, backend binding, private codecs and branch read authority."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import build, counter_documents
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._owner_state_runtime import _isolate_candidate_owner_state
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import (
    C0ValuePorts,
    _complete_record_paths,
    _complete_value_fields,
    compile_value_program,
)
from nomos_c0.declarative_nominal_v0 import bind_nominal_records, check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_start_v1 import C0BindingError, _opening_value
from nomos_c0.value_symbols_v1 import bind_value_program, symbolize_value_program
from nomos_c0.variant_types_v1 import construct_variant


def declaration():
    return {
        "schema": "c0.nominal_lib.v1",
        "records": [
            {
                "name": "Ticket",
                "fields": [
                    {"name": "number", "type": {"int": [0, 8]}},
                    {"name": "secret", "type": {"str": [1, 16]}},
                    {"name": "origin", "type": {"optional": "occurrence_ref"}},
                ],
                "invariant": None,
            },
            {
                "name": "Result",
                "fields": [{"name": "request", "type": {"str": [1, 8]}}],
                "variants": {
                    "success": "Ticket",
                    "failure": {"enum": ["busy", "denied"]},
                    "waiting": "none",
                },
                "invariant": None,
            },
            {
                "name": "State",
                "fields": [{"name": "result", "type": {"optional": "Result"}}],
                "invariant": None,
            },
        ],
        "owners": [
            {
                "symbol": "state",
                "key": "variant.state",
                "version": "v1",
                "state": "State",
                "identity_field": None,
                "seat_read": ["result"],
                "write": "replace_one",
            }
        ],
    }


def ports(lib, output=int, *, secret=True):
    carrier = lib.record("Result")
    paths = set(_complete_record_paths("state", carrier)) | {"state"}
    readable = {t: set(names) for t, names in _complete_value_fields(carrier).items()}
    if not secret:
        paths.remove("state.success.secret")
        readable[lib.record("Ticket")].remove("secret")
    return C0ValuePorts(
        {"state": carrier},
        frozenset(paths),
        frozenset(paths),
        {t: frozenset(names) for t, names in readable.items()},
        {t: frozenset(names) for t, names in readable.items()},
        {},
        dict(lib.records),
        {},
        {},
        {},
        {"out": output},
        lib.pure_definitions,
    )


def program(lib, expression, *, output=int, guard=True, secret=True):
    return compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": guard,
                "outputs": {"out": expression},
            }
        ),
        ports(lib, output, secret=secret),
    )


def match_value(success=None):
    return {
        "match": {
            "value": {"ref": "state"},
            "cases": {
                "success": {"as": "ticket", "then": success or {"ref": "ticket.number"}},
                "failure": {"as": "error", "then": 0},
                "waiting": {"as": "unit", "then": 1},
            },
        }
    }


def sample(lib, case="success"):
    payload = (
        lib.record("Ticket")(3, "hidden", K0OccurrenceRef(7))
        if case == "success"
        else "busy"
        if case == "failure"
        else None
    )
    return construct_variant(lib.record("Result"), case, payload, {"request": "r"})


def test_signature_and_rebinding_preserve_nominal_variant_and_opaque_refs():
    lib = check_nominal_lib(declaration())
    signature = lib.signatures.record("Result")
    assert signature.kind == "variant"
    assert signature.cases[0].payload.record == "Ticket"
    assert lib.signatures.record("State").fields[0].value.item.kind == "variant"
    compiled = program(lib, match_value())
    symbolic = symbolize_value_program(compiled, dict(lib.records))
    assert symbolic.ports.roots[0][1].kind == "variant"
    other = bind_nominal_records(lib.signatures)
    bound = bind_value_program(symbolic, dict(other.records))
    assert bound.evaluate({"state": sample(other)}, occurrence=K0OccurrenceRef(8))["out"] == 3
    assert other.record("Result") is not lib.record("Result")
    with pytest.raises(K0ProfileError):
        other.record("State")(sample(lib)).validate_for_k0()
    wrong = declaration()
    wrong["records"][1] = {
        "name": "Result",
        "fields": [{"name": "case", "type": {"str": [1, 8]}}],
        "invariant": None,
    }
    wrong["records"][2]["fields"][0]["type"] = {"optional": "Result"}
    with pytest.raises(C0LawError, match="backend kind"):
        bind_value_program(symbolic, dict(check_nominal_lib(wrong).records))
    with pytest.raises(TypeError, match="read-only"):
        lib.record("Result").__nomos_cases__ = (("success", int),)
    lib.check_record_layout()


@pytest.mark.parametrize("case,expected", [("success", 3), ("failure", 0), ("waiting", 1)])
def test_exhaustive_match_uses_only_selected_arm(case, expected):
    lib = check_nominal_lib(declaration())
    compiled = program(lib, match_value())
    result = compiled.evaluate({"state": sample(lib, case)}, occurrence=K0OccurrenceRef(8))
    assert result["out"] == expected


@pytest.mark.parametrize(
    "change", ["missing", "extra", "shadow", "wrong_payload", "record", "copy"]
)
def test_invalid_construction_and_match_reject_at_compile(change):
    lib = check_nominal_lib(declaration())
    expression = match_value()
    if change == "missing":
        del expression["match"]["cases"]["waiting"]
    elif change == "extra":
        expression["match"]["cases"]["other"] = {"as": "x", "then": 1}
    elif change == "shadow":
        expression["match"]["cases"]["success"]["as"] = "state"
    elif change == "wrong_payload":
        expression = {
            "variant": {
                "type": "Result",
                "case": "success",
                "value": 1,
                "fields": {"request": {"const": "r"}},
            }
        }
    elif change == "record":
        expression = {"record": {"type": "Result", "fields": {}}}
    else:
        expression = {"copy": {"from": {"ref": "state"}, "changes": {"case": {"const": "waiting"}}}}
    with pytest.raises(C0LawError):
        program(lib, expression)


def test_constructor_and_private_codec_only_store_selected_case():
    lib = check_nominal_lib(declaration())
    expression = {
        "variant": {
            "type": "Result",
            "case": "failure",
            "value": {"const": "busy"},
            "fields": {"request": {"const": "r"}},
        }
    }
    made = program(lib, expression, output=lib.record("Result")).evaluate(
        {"state": sample(lib)}, occurrence=K0OccurrenceRef(8)
    )["out"]
    assert made == sample(lib, "failure")
    owner = lib.owner("state").owner
    state = lib.record("State")(sample(lib))
    wire = owner.encode_state(state)
    assert wire[1] == (("success", (3, "hidden", 7), ("r",)),)
    assert owner.decode_state(wire) == state
    assert owner.preserved_occurrences(state) == (K0OccurrenceRef(7),)
    for payload in (
        ("unknown", None, ("r",)),
        ("waiting", 1, ("r",)),
        ("success", None, ("r",)),
        ("success", (3, "hidden", 7), ("r",), "extra"),
    ):
        with pytest.raises(K0ProfileError):
            owner.decode_state((wire[0], (payload,)))
    for invalid in (
        replace(state.result, failure="busy"),
        replace(state.result, success=None),
        replace(state.result, case="waiting"),
    ):
        with pytest.raises(K0ProfileError):
            invalid.validate_for_k0()


@pytest.mark.parametrize("case", ["success", "failure", "waiting"])
def test_candidate_isolation_preserves_variant_case_common_fields_and_optional_payload(case):
    lib = check_nominal_lib(declaration())
    owner = lib.owner("state").owner
    state = lib.record("State")(sample(lib, case))
    isolated = _isolate_candidate_owner_state(owner, state)
    assert isolated == state and isolated is not state and isolated.result is not state.result
    assert isolated.result.case == case and isolated.result.request == "r"
    assert owner.encode_state(isolated) == owner.encode_state(state)
    assert owner.preserved_occurrences(isolated) == owner.preserved_occurrences(state)
    if case == "success":
        assert isolated.result.success is not state.result.success
        assert isolated.result.success.origin is not state.result.success.origin
    absent = lib.record("State")(None)
    empty = _isolate_candidate_owner_state(owner, absent)
    assert empty == absent and empty is not absent
    with pytest.raises(K0ProfileError):
        _isolate_candidate_owner_state(
            owner, replace(state, result=replace(state.result, case="bad"))
        )


def test_assets_use_tagged_input_not_lowered_optional_slots():
    lib = check_nominal_lib(declaration())
    raw = {
        "case": "success",
        "value": {"number": 3, "secret": "hidden", "origin": None},
        "fields": {"request": "r"},
    }
    result = _opening_value(lib.record("Result"), raw)
    result.validate_for_k0()
    assert result.success.number == 3
    for invalid in (
        {"case": "waiting", "success": None, "failure": None, "request": "r"},
        {**raw, "case": "unknown"},
        {**raw, "value": 3},
    ):
        with pytest.raises(C0BindingError):
            _opening_value(lib.record("Result"), invalid)


@pytest.mark.parametrize("wrap", ["direct", "let", "pure", "nested_match"])
def test_match_alias_cannot_expand_read_rights(wrap):
    raw = declaration()
    expression = match_value({"ref": "ticket.secret"})
    if wrap == "let":
        expression["match"]["cases"]["success"]["then"] = {
            "let": {"name": "alias", "value": {"ref": "ticket"}, "in": {"ref": "alias.secret"}}
        }
    elif wrap == "pure":
        raw["pure_definitions"] = [
            {
                "name": "secret",
                "parameters": {"result": "Result"},
                "result": "str",
                "stage": "admission",
                "body": {
                    "match": {
                        "value": {"ref": "result"},
                        "cases": {
                            "success": {"as": "ticket", "then": {"ref": "ticket.secret"}},
                            "failure": {"as": "error", "then": {"const": "error"}},
                            "waiting": {"as": "unit", "then": {"const": "wait"}},
                        },
                    }
                },
            }
        ]
        expression = {"call": {"ref": "secret", "args": {"result": {"ref": "state"}}}}
    elif wrap == "nested_match":
        expression = {
            "let": {
                "name": "chosen",
                "value": match_value({"ref": "ticket"}),
                "in": {"ref": "chosen.secret"},
            }
        }
        expression["let"]["value"]["match"]["cases"]["failure"]["then"] = {"ref": "state.success"}
        expression["let"]["value"]["match"]["cases"]["waiting"]["then"] = {"ref": "state.success"}
        expression["let"]["in"] = {
            "if": {
                "when": "chosen is not None",
                "then": {"ref": "chosen.secret"},
                "else": {"const": "none"},
            }
        }
    lib = check_nominal_lib(raw)
    if wrap != "nested_match":
        expression_match = expression.get("match")
        if expression_match is not None:
            expression_match["cases"]["failure"]["then"] = {"const": "error"}
            expression_match["cases"]["waiting"]["then"] = {"const": "waiting"}
    program(lib, expression, output=str, secret=True)
    with pytest.raises(C0LawError):
        program(lib, expression, output=str, secret=False)


def test_case_proof_is_branch_local_and_does_not_grant_read_permission():
    lib = check_nominal_lib(declaration())
    case = {"is_case": {"value": {"ref": "state"}, "case": "success"}}
    expression = {"if": {"when": case, "then": {"ref": "state.success.number"}, "else": 0}}
    compiled = program(lib, expression)
    assert compiled.evaluate({"state": sample(lib)}, occurrence=K0OccurrenceRef(8))["out"] == 3
    expression["if"]["else"] = {"ref": "state.success.number"}
    with pytest.raises(C0LawError):
        program(lib, expression)
    with pytest.raises(C0LawError):
        program(lib, {"ref": "state.success.secret"}, output=str, guard=case, secret=False)


def test_declaration_rejects_optional_payload_and_colliding_discriminator():
    for edit in ("optional", "collision"):
        raw = deepcopy(declaration())
        if edit == "optional":
            raw["records"][1]["variants"]["success"] = {"optional": "Ticket"}
        else:
            raw["records"][1]["fields"][0]["name"] = "case"
        with pytest.raises(C0LawError):
            check_nominal_lib(raw)


def test_match_does_not_recursively_validate_its_own_domain_invariant():
    raw = declaration()
    raw["records"][1]["invariant"] = match_value({"lt": [{"ref": "ticket.number"}, 3]})
    raw["records"][1]["invariant"]["match"]["value"] = {"ref": "state"}
    for case in ("failure", "waiting"):
        raw["records"][1]["invariant"]["match"]["cases"][case]["then"] = True
    lib = check_nominal_lib(raw)
    sample(lib, "waiting").validate_for_k0()
    with pytest.raises(K0ProfileError, match="invariant"):
        sample(lib)


def test_matching_rejects_foreign_nominal_payload_without_reentering_invariant():
    lib = check_nominal_lib(declaration())
    foreign = check_nominal_lib(declaration())
    forged = replace(sample(lib), success=foreign.record("Ticket")(3, "hidden", None))
    with pytest.raises(K0ProfileError, match="nominal shape"):
        program(lib, match_value()).evaluate({"state": forged}, occurrence=K0OccurrenceRef(8))


def test_unselected_match_arm_is_not_evaluated():
    lib = check_nominal_lib(declaration())
    expression = match_value()
    expression["match"]["cases"]["failure"]["then"] = {"ceil_div": [1, 0]}
    compiled = program(lib, expression)
    assert compiled.evaluate({"state": sample(lib)}, occurrence=K0OccurrenceRef(8))["out"] == 3


def test_whole_payload_alias_requires_its_own_read_port_but_unused_alias_does_not():
    lib = check_nominal_lib(declaration())
    expression = match_value({"ref": "ticket"})
    for case in ("failure", "waiting"):
        expression["match"]["cases"][case]["then"] = None
    body = {"schema": "c0.value.v1", "bindings": [], "guard": True, "outputs": {"out": expression}}
    selected = ports(lib, lib.record("Ticket") | None)
    compile_value_program(json.dumps(body), selected)
    limited = replace(
        selected,
        readable_paths=selected.readable_paths - {"state.success"},
        admission_readable_paths=selected.admission_readable_paths - {"state.success"},
    )
    with pytest.raises(C0LawError, match="read boundary"):
        compile_value_program(json.dumps(body), limited)
    for arm in expression["match"]["cases"].values():
        arm["then"] = None
    compile_value_program(json.dumps(body), limited)


def test_match_guard_diagnostics_only_describe_selected_case_and_scope_names():
    lib = check_nominal_lib(declaration())
    guard = match_value()
    for case, arm in guard["match"]["cases"].items():
        arm["then"] = {"require": [{"permitted": False if case == "success" else True}]}
    compiled = program(lib, 1, guard=guard)
    failures = compiled.false_guard_clauses({"state": sample(lib)})
    assert len(failures) == 1
    assert failures[0].names == ("permitted",)
    assert failures[0].path == "guard.match.cases.success.then.require.permitted"
    assert failures[0].branches == ("guard.match.cases.success.then",)


def test_compile_start_and_real_k0_action_share_variant_contract():
    lib, port, source, assets = counter_documents()
    lib["records"].extend(declaration()["records"][:2])
    lib["records"][1]["fields"][1] = {"name": "result", "type": {"optional": "Result"}}
    lib["owners"][1]["seat_read"] = ["name", "result"]
    template = port["actions"][0]
    template["effects"]["actor"] = {"result": "result"}
    template["value"]["read"] = ["actor.name", "payload.target"]
    template["value"]["write_paths"] = ["actor.result"]
    template["value"]["construct"] = ["Result", "Ticket"]
    source["lawdefs"][0]["body"]["value"]["outputs"] = {
        "action": {"ref": "occurrence"},
        "result": {
            "variant": {
                "type": "Result",
                "case": "success",
                "fields": {"request": {"const": "r"}},
                "value": {
                    "record": {
                        "type": "Ticket",
                        "fields": {
                            "number": 3,
                            "secret": {"const": "hidden"},
                            "origin": {"ref": "occurrence"},
                        },
                    }
                },
            }
        },
    }
    source["lawdefs"][0]["formals"] = {}
    source["actions"][0]["law"]["args"] = {}
    source["seats"][0]["read"] = ["actor_0.name", "actor_0.result"]
    assets["opening"]["actor_0"] = {"name": "person_0", "result": None}
    compiled = compile_owner_graph(build(lib, port), source)
    second_assets = deepcopy(assets)
    second_assets["opening"]["actor_0"]["result"] = {
        "case": "waiting",
        "value": None,
        "fields": {"request": "r"},
    }
    for selected in (assets, second_assets):
        game = compiled.start(selected)
        offer = game.offers("seat_0")[0]
        outcome = game.submit("seat_0", offer.entry, dict(offer.payload))
        assert isinstance(outcome, K0Published)
        result = dict(game.read("seat_0").fields)["actor_0.result"]
        assert result.case == "success"
        assert result.success.origin == outcome.occurrences[0].occurrence
        assert result.success.number == 3
    second_assets["opening"]["actor_0"]["result"]["case"] = "invalid"
    with pytest.raises(C0BindingError):
        compiled.start(second_assets)
