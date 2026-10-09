"""Finite output templates preserve nominal ports and one atomic K0 occurrence."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0SourceSpecKey
from nomos_kernel._atomic_inmemory_session import K0SettlementDefect

from nomos_c0 import C0LawError
from nomos_c0 import composable_value_v1 as values
from nomos_c0.composable_value_v1 import C0ValuePorts, compile_value_program
from nomos_c0.output_family_v1 import expand_output_families
from nomos_c0.owner_graph_v1 import compile_owner_graph


@dataclass(frozen=True)
class Person:
    amount: int
    ready: bool = True
    secret: int = 99
    maybe: int | None = None
    name: str = "person.amount"
    stamp: K0OccurrenceRef | None = None


@dataclass(frozen=True)
class Wrapper:
    ref: str


@dataclass(frozen=True)
class Holder:
    item: Wrapper


def _ports():
    fields = frozenset({"amount", "ready", "maybe", "name"})
    paths = frozenset(f"{root}.{field}" for root in ("one", "two", "three") for field in fields)
    return C0ValuePorts(
        roots={"one": Person, "two": Person, "three": Person},
        readable_paths=paths,
        admission_readable_paths=paths - {"two.name"},
        readable_fields={Person: fields},
        admission_readable_fields={Person: fields},
        writable_fields={Person: frozenset({"amount"})},
        writable_paths=frozenset({"one.amount", "two.amount"}),
        record_types={"Person": Person},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"first_slot": int, "second_slot": int, "stamp": K0OccurrenceRef},
    )


def _source(expression=None):
    return {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "outputs": {"stamp": {"ref": "occurrence"}},
        "output_families": [
            {
                "name": "balances",
                "owners": ["one", "two"],
                "as": "person",
                "fields": {
                    "amount": {"add": [{"ref": "person.amount"}, {"ref": "two.amount"}]}
                    if expression is None
                    else expression
                },
            }
        ],
    }


def _compile(source=None, ports=None, mapping=None, **kwargs):
    return compile_value_program(
        json.dumps(_source() if source is None else source),
        _ports() if ports is None else ports,
        state_outputs={"one.amount": "first_slot", "two.amount": "second_slot"}
        if mapping is None
        else mapping,
        **kwargs,
    )


def test_family_uses_one_pre_state_and_never_discovers_an_unselected_owner():
    program = _compile()
    roots = {"one": Person(2), "two": Person(5), "three": Person(100)}
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(9)) == {
        "first_slot": 7,
        "second_slot": 10,
        "stamp": K0OccurrenceRef(9),
    }
    assert roots["one"].amount == 2 and roots["three"].amount == 100
    assert "output_families" not in program._tree
    first = program._tree["outputs"]["first_slot"]
    assert first.origin == "output_families.balances.owners.one.fields.amount"
    assert first["add"][0].origin.endswith(".amount.add[0]")
    with pytest.raises(TypeError):
        first["add"] = ()


def test_compact_text_and_structured_refs_use_the_same_lexical_alias():
    expression = {
        "if": {
            "when": "person.ready and person.amount < two.amount",
            "then": {"ref": "person.amount"},
            "else": {"const": 0},
        }
    }
    roots = {"one": Person(2), "two": Person(5), "three": Person(100)}
    assert _compile(_source(expression)).evaluate(roots, occurrence=K0OccurrenceRef(1)) == {
        "first_slot": 2,
        "second_slot": 0,
        "stamp": K0OccurrenceRef(1),
    }


def test_member_bindings_share_lazy_computation_per_owner_and_evaluation(monkeypatch):
    source = _source("sample + sample if person.ready else person.amount")
    source["output_families"][0]["bindings"] = {
        "sample": {"die_roll": {"seed": "person.amount", "sides": 20}},
    }
    program = _compile(source)
    calls = []
    draw = values._die_roll

    def counted(seed, sides):
        calls.append((seed, sides))
        return draw(seed, sides)

    monkeypatch.setattr(values, "_die_roll", counted)
    roots = {"one": Person(2), "two": Person(5, ready=False), "three": Person(100)}
    result = program.evaluate(roots, occurrence=K0OccurrenceRef(1))
    assert result["first_slot"] == 2 * draw(2, 20) and result["second_slot"] == 5
    assert calls == [(2, 20)]
    program.evaluate(roots, occurrence=K0OccurrenceRef(2))
    assert calls == [(2, 20), (2, 20)]


def test_member_bindings_are_ordered_and_support_typed_arithmetic():
    source = _source("second")
    source["output_families"][0]["bindings"] = {
        "first": "person.amount + 1",
        "second": "first * 2 - 1",
    }
    result = _compile(source).evaluate(
        {"one": Person(2), "two": Person(5), "three": Person(100)},
        occurrence=K0OccurrenceRef(1),
    )
    assert (result["first_slot"], result["second_slot"]) == (5, 11)


@pytest.mark.parametrize("expression", ["person.amount / 2", "eval('1')", "lambda: 1"])
def test_compact_member_expressions_do_not_enable_python_execution(expression):
    source = _source("sample")
    source["output_families"][0]["bindings"] = {"sample": expression}
    with pytest.raises(C0LawError):
        _compile(source)


@pytest.mark.parametrize(
    "bindings",
    [
        {"person": 1},
        {"one": 1},
        {"occurrence": 1},
        {"_hidden": 1},
        {"first": "second", "second": 1},
        {"first": "first + 1"},
        [],
    ],
)
def test_invalid_member_binding_scope_rejects(bindings):
    source = _source()
    source["output_families"][0]["bindings"] = bindings
    with pytest.raises(C0LawError):
        _compile(source)


def test_member_bindings_cannot_escape_or_acquire_hidden_reads():
    source = _source("sample")
    source["output_families"][0]["bindings"] = {"sample": 1}
    source["outputs"]["stamp"] = "balances_one_sample"
    with pytest.raises(C0LawError, match="escape"):
        _compile(source)
    source["outputs"]["stamp"] = {"ref": "occurrence"}
    source["output_families"][0]["bindings"]["sample"] = "person.secret"
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(source)


def test_generated_member_names_cannot_connect_different_families():
    source = _source("sample")
    family = source["output_families"][0]
    family["owners"] = ["one"]
    family["bindings"] = {"sample": 1}
    second = deepcopy(family)
    second["name"] = "other"
    second["owners"] = ["two"]
    second["bindings"] = {"sample": "balances_one_sample"}
    source["output_families"].append(second)
    with pytest.raises(C0LawError, match="escape"):
        _compile(source)


def test_assignment_effect_cannot_escape_a_member_binding():
    source = _source("sample")
    source["output_families"][0]["bindings"] = {"sample": "person.amount + 1"}
    source["effects"] = [{"outside": {"assign": {"three.amount": "balances_one_sample"}}}]
    selected = replace(
        _ports(),
        outputs={**_ports().outputs, "third_slot": int},
        writable_paths=_ports().writable_paths | {"three.amount"},
    )
    mapping = {
        "one.amount": "first_slot",
        "two.amount": "second_slot",
        "three.amount": "third_slot",
    }
    with pytest.raises(C0LawError, match="escape"):
        _compile(source, selected, mapping)


def test_member_computations_do_not_become_admission_inputs_or_shadow_inner_scopes():
    source = _source("sample")
    source["output_families"][0]["bindings"] = {"sample": 1}
    with pytest.raises(C0LawError):
        _compile(source, admission_outputs=frozenset({"first_slot"}))
    source["output_families"][0]["fields"]["amount"] = {
        "let": {"name": "sample", "value": 1, "in": "sample"}
    }
    with pytest.raises(C0LawError, match="shadowed"):
        _compile(source)


def test_member_computations_share_the_existing_program_binding_budget():
    source = _source("last")
    source["output_families"][0]["bindings"] = {
        **{f"local_{index}": 1 for index in range(32)},
        "last": 1,
    }
    with pytest.raises(C0LawError, match="binding limit"):
        _compile(source)


def test_constants_and_record_field_names_are_not_alias_references():
    # A record field called `ref` is metadata, not an expression reference.
    selected = _ports()
    selected = replace(
        selected,
        roots={"one": Holder, "two": Holder},
        readable_paths=frozenset(),
        admission_readable_paths=frozenset(),
        writable_fields={Holder: frozenset({"item"}), Wrapper: frozenset({"ref"})},
        writable_paths=frozenset({"one.item", "two.item"}),
        record_types={"Wrapper": Wrapper},
        outputs={"first_slot": Wrapper, "second_slot": Wrapper, "stamp": K0OccurrenceRef},
    )
    source = _source()
    source["output_families"][0]["fields"] = {
        "item": {"record": {"type": "Wrapper", "fields": {"ref": {"const": "person.item"}}}}
    }
    program = _compile(source, selected, {"one.item": "first_slot", "two.item": "second_slot"})
    result = program.evaluate(
        {"one": Holder(Wrapper("old")), "two": Holder(Wrapper("old"))},
        occurrence=K0OccurrenceRef(1),
    )
    assert result["first_slot"] == result["second_slot"] == Wrapper("person.item")


@pytest.mark.parametrize(
    "key,value",
    [
        ("owners", []),
        ("owners", ["one", "one"]),
        ("owners", ["missing"]),
        ("owners", [{}]),
        ("owners", "one"),
        ("fields", {}),
        ("fields", []),
        ("as", "one"),
        ("as", "occurrence"),
        ("as", "_hidden"),
        ("name", "bad-name"),
        ("extra", True),
    ],
)
def test_malformed_finite_domains_and_names_reject(key, value):
    source = _source()
    source["output_families"][0][key] = value
    with pytest.raises(C0LawError):
        _compile(source)


@pytest.mark.parametrize(
    "mapping",
    [
        {},
        {"one.amount": "first_slot"},
        {"one.amount": "first_slot", "two.amount": "first_slot"},
        {"one.secret": "first_slot", "two.amount": "second_slot"},
        {"one.amount": "absent", "two.amount": "second_slot"},
    ],
)
def test_output_names_come_only_from_the_typed_write_graph(mapping):
    with pytest.raises(C0LawError, match="write"):
        _compile(mapping=mapping)


def test_family_requires_adapter_mapping_and_covers_all_declared_outputs():
    with pytest.raises(C0LawError, match="state write graph"):
        compile_value_program(json.dumps(_source()), _ports())
    source = _source()
    source["output_families"][0]["owners"] = ["one"]
    with pytest.raises(C0LawError, match="value outputs"):
        _compile(source)


def test_alias_cannot_be_used_outside_the_family_or_capture_a_binding():
    source = _source()
    source["bindings"] = [{"name": "person", "stage": "effect", "let": 1}]
    with pytest.raises(C0LawError, match="shadows"):
        _compile(source)
    source = _source()
    source["outputs"]["stamp"] = {"ref": "person.amount"}
    with pytest.raises(C0LawError, match="root"):
        _compile(source)


@pytest.mark.parametrize(
    "expression",
    [
        {"let": {"name": "person", "value": 1, "in": {"ref": "person"}}},
        {"count_matching": {"collection": {"ref": "one"}, "as": "person", "where": True}},
    ],
)
def test_template_local_declarations_cannot_shadow_the_owner_alias(expression):
    with pytest.raises(C0LawError, match="shadowed"):
        _compile(_source(expression))


def test_each_instance_keeps_its_actual_read_boundary_and_nominal_field_type():
    selected = _ports()
    with pytest.raises(C0LawError, match="owners.two.fields.amount.*read boundary"):
        _compile(
            ports=replace(
                selected,
                readable_paths=selected.readable_paths - {"two.amount"},
                admission_readable_paths=selected.admission_readable_paths - {"two.amount"},
            ),
            source=_source({"ref": "person.amount"}),
        )
    with pytest.raises(C0LawError, match="nominal type"):
        _compile(_source({"ref": "person.ready"}))
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(_source({"ref": "person.secret"}))
    with pytest.raises(C0LawError):
        _compile(_source({"add": [{"ref": "person.maybe"}, 1]}))


def test_admission_projection_cannot_capture_effect_occurrence_or_narrow_read():
    selected = replace(
        _ports(),
        outputs={
            "first_slot": K0OccurrenceRef | None,
            "second_slot": K0OccurrenceRef | None,
            "stamp": K0OccurrenceRef,
        },
        writable_fields={Person: frozenset({"stamp"})},
        writable_paths=frozenset({"one.stamp", "two.stamp"}),
    )
    source = _source()
    source["output_families"][0]["fields"] = {"stamp": {"ref": "occurrence"}}
    with pytest.raises(C0LawError, match="occurrence"):
        _compile(
            source,
            selected,
            {"one.stamp": "first_slot", "two.stamp": "second_slot"},
            admission_outputs=frozenset({"first_slot"}),
        )
    selected = replace(
        _ports(),
        outputs={"first_slot": str, "second_slot": str, "stamp": K0OccurrenceRef},
        writable_fields={Person: frozenset({"name"})},
        writable_paths=frozenset({"one.name", "two.name"}),
    )
    source = _source()
    source["output_families"][0]["fields"] = {"name": {"ref": "person.name"}}
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(
            source,
            selected,
            {"one.name": "first_slot", "two.name": "second_slot"},
            admission_outputs=frozenset({"second_slot"}),
        )


@pytest.mark.parametrize("overlap", ["explicit", "family", "effect"])
def test_overlapping_output_writes_are_never_sequenced_or_silently_replaced(overlap):
    source = _source()
    if overlap == "explicit":
        source["outputs"]["first_slot"] = 1
    elif overlap == "family":
        duplicate = deepcopy(source["output_families"][0])
        duplicate["name"] = "other"
        source["output_families"].append(duplicate)
    else:
        source["effects"] = [{"spend": {"debit": "one.amount", "amount": 1, "floor": 0}}]
    with pytest.raises(C0LawError, match="overlap"):
        _compile(source)


def test_run_does_not_expand_or_reparse_the_family(monkeypatch):
    program = _compile()

    def forbidden(*args, **kwargs):
        raise AssertionError("Run entered the compiler")

    monkeypatch.setattr(values, "expand_output_families", forbidden)
    monkeypatch.setattr(values, "lower_author_expression", forbidden)
    assert (
        program.evaluate(
            {"one": Person(2), "two": Person(5), "three": Person(100)},
            occurrence=K0OccurrenceRef(1),
        )["first_slot"]
        == 7
    )


def test_family_call_names_and_formal_parameter_names_are_not_owner_references():
    from test_pure_definition_v1 import checked, definition

    selected = replace(
        _ports(),
        pure_definitions=checked(
            [definition("person.amount", {"person": "int"}, {"ref": "person"})]
        ),
    )
    program = _compile(
        _source({"call": {"ref": "person.amount", "args": {"person": {"ref": "person.amount"}}}}),
        selected,
    )
    result = program.evaluate(
        {"one": Person(2), "two": Person(5), "three": Person(100)}, occurrence=K0OccurrenceRef(1)
    )
    assert (result["first_slot"], result["second_slot"]) == (2, 5)


def test_nullable_proofs_are_reestablished_for_each_actual_owner():
    program = _compile(
        _source(
            {"if": {"when": "person.maybe is not None", "then": {"ref": "person.maybe"}, "else": 0}}
        )
    )
    result = program.evaluate(
        {"one": Person(2), "two": Person(5, maybe=7), "three": Person(100)},
        occurrence=K0OccurrenceRef(1),
    )
    assert (result["first_slot"], result["second_slot"]) == (0, 7)


def test_family_instances_are_checked_against_each_nominal_carrier():
    @dataclass(frozen=True)
    class Switch:
        amount: bool

    selected = _ports()
    selected = replace(
        selected,
        roots={**selected.roots, "two": Switch},
        readable_fields={**selected.readable_fields, Switch: frozenset({"amount"})},
        admission_readable_fields={
            **selected.admission_readable_fields,
            Switch: frozenset({"amount"}),
        },
        readable_paths=frozenset({"one.amount", "two.amount"}),
        admission_readable_paths=frozenset({"one.amount", "two.amount"}),
        writable_fields={**selected.writable_fields, Switch: frozenset({"amount"})},
        outputs={**selected.outputs, "second_slot": bool},
    )
    with pytest.raises(C0LawError, match="owners.two.fields.amount"):
        _compile(_source({"add": [{"ref": "person.amount"}, 1]}), selected)


@pytest.mark.parametrize("limit", ["outputs", "nodes"])
def test_expansion_has_program_wide_finite_limits(limit):
    owners = [f"owner_{index}" for index in range(64)]
    fields = (
        {f"field_{index}": True for index in range(17)}
        if limit == "outputs"
        else {"amount": {"all": [True] * 2100}}
    )
    with pytest.raises(C0LawError, match="finite .*limit"):
        expand_output_families(
            [{"name": "people", "owners": owners, "as": "person", "fields": fields}],
            roots=dict.fromkeys(owners, Person),
            binding_names=set(),
            explicit_outputs={},
            state_outputs={
                f"{owner}.{field}": f"{owner}_{field}" for owner in owners for field in fields
            },
        )


def _due_world(expression=None, *, member_bindings=None):
    from authored_counter_v1 import action_value_documents, build

    lib, ports, source, assets = action_value_documents()
    roots = ["actor_0", "actor_1"]
    template = ports["due_events"][0]
    template["owner_roots"] = roots
    template["value"]["read"].extend(f"{root}.count" for root in roots)
    template["value"]["write_paths"].extend(f"{root}.count" for root in roots)
    template["value"]["outputs"].update(first="actor_0.count", second="actor_1.count")
    law = source["lawdefs"][-1]["body"]["law"]
    law["output_families"] = [
        {
            "name": "people",
            "owners": list(roots),
            "as": "person",
            "fields": {"count": expression or {"add": [{"ref": "person.count"}, 1]}},
        }
    ]
    if member_bindings is not None:
        law["output_families"][0]["bindings"] = member_bindings
    for seat in source["game_form"]["seats"]:
        seat["eligible"] = False
    assets["opening"]["actor_0"]["count"] = 3
    assets["opening"]["actor_1"]["count"] = 7
    return compile_owner_graph(build(lib, ports), source).start(assets)


def test_member_computations_enter_one_real_k0_due_without_new_owner_or_source():
    from authored_counter_v1 import _actor

    session = _due_world("after", member_bindings={"after": "person.count + 1"})
    assert session.continue_form("seat_0").finished
    assert (_actor(session, 0).count, _actor(session, 1).count) == (4, 8)
    (event,) = session._runtime.occurrence_history()
    assert event.source == K0SourceSpecKey("c0.graph.pulse")


def test_one_real_k0_due_publishes_both_owner_results_with_one_source():
    from authored_counter_v1 import _actor

    session = _due_world()
    assert session.continue_form("seat_0").finished
    assert (_actor(session, 0).count, _actor(session, 1).count) == (4, 8)
    (event,) = session._runtime.occurrence_history()
    assert event.source == K0SourceSpecKey("c0.graph.pulse")
    assert session._runtime.read_owner(K0OwnerKey("c0.graph.scene")).view.signal == "pulse"


def test_family_effect_fault_rolls_back_all_owners_and_keeps_the_fatal_boundary():
    from authored_counter_v1 import _actor

    session = _due_world(
        {
            "if": {
                "when": "person.count == 7",
                "then": {"ceil_div": [1, 0]},
                "else": {"add": [{"ref": "person.count"}, 1]},
            }
        }
    )
    with pytest.raises(K0SettlementDefect):
        session.continue_form("seat_0")
    assert (_actor(session, 0).count, _actor(session, 1).count) == (3, 7)
    assert session._runtime.occurrence_history() == ()
    with pytest.raises((K0SettlementDefect, ValueError)):
        session.continue_form("seat_0")
