"""Author data expressions do not depend on one world's record classes."""

from __future__ import annotations

import json
from dataclasses import dataclass, make_dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0 import C0LawError
from nomos_c0 import composable_value_v1 as value_module
from nomos_c0.composable_value_v1 import (
    C0ValuePorts,
    C0ValueStateError,
    _resolved_fields,
    compile_value_program,
)


def test_resolved_nominal_fields_cache_is_bounded_for_recompiled_libraries() -> None:
    for _ in range(300):
        carrier = make_dataclass("RecompiledRecord", [("value", int)], frozen=True, slots=True)
        assert _resolved_fields(carrier) == {"value": int}
    info = _resolved_fields.cache_info()
    assert info.maxsize == 256
    assert info.currsize <= info.maxsize


@dataclass(frozen=True)
class RouteBook:
    routes: tuple[tuple[str, int, str], ...]
    deadline: int


@dataclass(frozen=True)
class NestedChild:
    id: str


@dataclass(frozen=True)
class NestedBox:
    id: str
    children: tuple[NestedChild, ...]


@dataclass(frozen=True)
class NestedScene:
    boxes: tuple[NestedBox, ...]


@dataclass(frozen=True)
class LocalChargeSample:
    known: int | None
    sites: tuple[str, ...]


@dataclass(frozen=True)
class Parcel:
    id: str
    status: str
    recipient: str | None = None
    content: str | None = None
    dispatch: K0OccurrenceRef | None = None
    due: int | None = None


@dataclass(frozen=True)
class ParcelReceipt:
    item_id: str
    action: K0OccurrenceRef
    started: int
    due: int


@dataclass(frozen=True)
class ParcelScene:
    tick: int
    packages: tuple[Parcel, ...]
    source: RouteBook


@dataclass(frozen=True)
class ParcelActor:
    role: str
    heard: str | None
    receipts: tuple[ParcelReceipt, ...]


@dataclass(frozen=True)
class ParcelAttempt:
    actor: str
    kind: str
    target: str | None
    item_id: str


@dataclass(frozen=True)
class Writ:
    id: str
    status: str
    recipient: str | None = None
    content: str | None = None
    dispatch: K0OccurrenceRef | None = None
    due: int | None = None


@dataclass(frozen=True)
class WritReceipt:
    item_id: str
    action: K0OccurrenceRef
    started: int
    due: int


@dataclass(frozen=True)
class WritScene:
    tick: int
    packages: tuple[Writ, ...]
    source: RouteBook


@dataclass(frozen=True)
class WritActor:
    role: str
    heard: str | None
    receipts: tuple[WritReceipt, ...]


@dataclass(frozen=True)
class LocalSighting:
    carrier: str


@dataclass(frozen=True)
class LocalReader:
    sighting: LocalSighting | None


@dataclass(frozen=True)
class OptionalValue:
    value: int | None


@dataclass(frozen=True)
class OptionalHolder:
    entry: OptionalValue | None


@dataclass(frozen=True)
class BudgetOwner:
    budget: int


@dataclass(frozen=True)
class DieScene:
    seed: int
    sides: int


@dataclass(frozen=True)
class Ballot:
    round: int
    target: str
    action: K0OccurrenceRef


@dataclass(frozen=True)
class BallotLedger:
    current_round: int
    ballots: tuple[Ballot, ...]


@dataclass(frozen=True)
class BallotQuery:
    target: str


@dataclass(frozen=True)
class SealedItem:
    id: str
    secret: str


@dataclass(frozen=True)
class SealedItems:
    items: tuple[SealedItem, ...]


@dataclass(frozen=True)
class WritAttempt:
    actor: str
    kind: str
    target: str | None
    item_id: str


def _ref(name: str) -> dict[str, str]:
    return {"ref": name}


def _const(value):
    return {"const": value}


def _add(left, right):
    return {"add": [left, right]}


def _source():
    tick = _ref("scene.tick")
    route_time = _ref("route.travel")
    return {
        "schema": "c0.value.v1",
        "bindings": [
            {
                "name": "item",
                "collection": "scene.packages",
                "key": "id",
                "value": _ref("payload.item_id"),
                "required": True,
            },
            {
                "name": "route",
                "collection": "scene.source.routes",
                "key": "recipient",
                "value": _ref("payload.target"),
                "required": False,
            },
        ],
        "guard": {
            "all": [
                {"eq": [_ref("payload.actor"), _const("keeper")]},
                {"eq": [_ref("payload.kind"), _const("dispatch")]},
                {"not_none": _ref("actor.heard")},
                {"eq": [_ref("item.status"), _const("home")]},
                {"not_none": _ref("route")},
                {"le": [_add(tick, route_time), _ref("scene.source.deadline")]},
                {
                    "none_matching": {
                        "collection": _ref("actor.receipts"),
                        "as": "d",
                        "where": {
                            "all": [
                                {"le": [_ref("d.started"), tick]},
                                {"lt": [tick, _ref("d.due")]},
                            ]
                        },
                    }
                },
            ]
        },
        "outputs": {
            "new_packages": {
                "replace_unique": {
                    "collection": _ref("scene.packages"),
                    "old": _ref("item"),
                    "key": "id",
                    "new": {
                        "copy": {
                            "from": _ref("item"),
                            "changes": {
                                "status": _const("preparing"),
                                "recipient": _ref("route.recipient"),
                                "content": _ref("route.content"),
                                "dispatch": _ref("occurrence"),
                                "due": _add(tick, route_time),
                            },
                        }
                    },
                }
            },
            "new_receipts": {
                "append": [
                    _ref("actor.receipts"),
                    {
                        "record": {
                            "type": "Receipt",
                            "fields": {
                                "item_id": _ref("payload.item_id"),
                                "action": _ref("occurrence"),
                                "started": tick,
                                "due": _add(tick, _const(1)),
                            },
                        }
                    },
                ]
            },
            "message": _ref("route.content"),
        },
    }


def _ports(scene_type, actor_type, attempt_type, item_type, receipt_type):
    paths = frozenset(
        {
            "scene.tick",
            "scene.packages",
            "scene.source.routes",
            "scene.source.deadline",
            "actor.heard",
            "actor.receipts",
            "payload.actor",
            "payload.kind",
            "payload.target",
            "payload.item_id",
        }
    )
    readable_fields = {
        scene_type: frozenset({"tick", "packages", "source"}),
        RouteBook: frozenset({"routes", "deadline"}),
        actor_type: frozenset({"heard", "receipts"}),
        attempt_type: frozenset({"actor", "kind", "target", "item_id"}),
        item_type: frozenset({"id", "status", "recipient", "content", "dispatch", "due"}),
        receipt_type: frozenset({"item_id", "started", "due"}),
    }
    return C0ValuePorts(
        roots={"scene": scene_type, "actor": actor_type, "payload": attempt_type},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=readable_fields,
        admission_readable_fields=readable_fields,
        writable_fields={
            item_type: frozenset(
                {
                    "status",
                    "recipient",
                    "content",
                    "dispatch",
                    "due",
                }
            )
        },
        record_types={"Receipt": receipt_type},
        tuple_fields={
            tuple[str, int, str]: {
                "recipient": 0,
                "travel": 1,
                "content": 2,
            }
        },
        admission_tuple_fields={tuple[str, int, str]: {"recipient": 0, "travel": 1}},
        collection_keys={
            "scene.packages": "id",
            "scene.source.routes": "recipient",
            "actor.receipts": "item_id",
        },
        outputs={
            "new_packages": tuple[item_type, ...],
            "new_receipts": tuple[receipt_type, ...],
            "message": str,
        },
    )


@pytest.mark.parametrize(
    ("scene_type", "actor_type", "attempt_type", "item_type", "receipt_type"),
    (
        (ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt),
        (WritScene, WritActor, WritAttempt, Writ, WritReceipt),
    ),
)
def test_one_author_expression_updates_two_distinct_nominal_worlds(
    scene_type,
    actor_type,
    attempt_type,
    item_type,
    receipt_type,
):
    program = compile_value_program(
        json.dumps(_source()),
        _ports(scene_type, actor_type, attempt_type, item_type, receipt_type),
    )
    scene = scene_type(3, (item_type("P", "home"),), RouteBook((("chapel", 2, "inspect"),), 9))
    actor = actor_type("keeper", "heard", ())
    result = program.evaluate(
        {
            "scene": scene,
            "actor": actor,
            "payload": attempt_type("keeper", "dispatch", "chapel", "P"),
        },
        occurrence=K0OccurrenceRef(12),
    )
    assert result == {
        "new_packages": (item_type("P", "preparing", "chapel", "inspect", K0OccurrenceRef(12), 5),),
        "new_receipts": (receipt_type("P", K0OccurrenceRef(12), 3, 4),),
        "message": "inspect",
    }


def test_optional_lookup_and_busy_guard_are_finite_non_admission():
    program = compile_value_program(
        json.dumps(_source()),
        _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt),
    )
    scene = ParcelScene(3, (Parcel("P", "home"),), RouteBook((("chapel", 2, "inspect"),), 9))
    actor = ParcelActor("keeper", "heard", ())
    roots = {
        "scene": scene,
        "actor": actor,
        "payload": ParcelAttempt("keeper", "dispatch", "unknown", "P"),
    }
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(12)) is None
    roots["payload"] = replace(roots["payload"], target="chapel")
    roots["actor"] = replace(actor, receipts=(ParcelReceipt("P", K0OccurrenceRef(1), 3, 4),))
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(12)) is None
    roots["actor"] = replace(actor, heard=None)
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(12)) is None


def _predicate_lookup_source():
    source = _source()
    source["bindings"][1] = {
        "name": "route",
        "collection": "scene.source.routes",
        "as": "candidate",
        "where": {"eq": [{"ref": "candidate.recipient"}, {"ref": "payload.target"}]},
        "required": False,
    }
    return source


def _predicate_lookup_ports():
    ports = _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt)
    return replace(
        ports,
        collection_keys={
            key: value
            for key, value in ports.collection_keys.items()
            if key != "scene.source.routes"
        },
    )


def test_typed_predicate_lookup_has_zero_one_and_multiple_match_semantics():
    source = _predicate_lookup_source()
    program = compile_value_program(json.dumps(source), _predicate_lookup_ports())
    roots = {
        "scene": ParcelScene(3, (Parcel("P", "home"),), RouteBook((("chapel", 2, "inspect"),), 9)),
        "actor": ParcelActor("keeper", "heard", ()),
        "payload": ParcelAttempt("keeper", "dispatch", "chapel", "P"),
    }
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(12))["message"] == "inspect"
    roots["scene"] = replace(roots["scene"], source=RouteBook((), 9))
    assert program.admits(roots) is False
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(12)) is None
    roots["scene"] = replace(
        roots["scene"],
        source=RouteBook((("chapel", 2, "inspect"), ("chapel", 3, "other")), 9),
    )
    assert program.admits(roots) is False
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(12)) is None
    source["bindings"][1]["required"] = True
    required = compile_value_program(json.dumps(source), _predicate_lookup_ports())
    roots["scene"] = replace(roots["scene"], source=RouteBook((), 9))
    assert required.admits(roots) is False


def test_predicate_lookup_compiles_only_boolean_admission_visible_conditions():
    source = _predicate_lookup_source()
    ports = _predicate_lookup_ports()
    source["bindings"][1]["where"] = {"const": 1}
    with pytest.raises(C0LawError, match="boolean"):
        compile_value_program(json.dumps(source), ports)
    source["bindings"][1]["where"] = {"eq": [{"ref": "candidate.content"}, {"const": "guess"}]}
    with pytest.raises(C0LawError, match="tuple field"):
        compile_value_program(json.dumps(source), ports)
    source["bindings"][1]["where"] = {"const": True}
    source["bindings"][1]["as"] = "scene"
    with pytest.raises(C0LawError, match="shadows"):
        compile_value_program(json.dumps(source), ports)
    source["bindings"][1]["as"] = "bad.name"
    with pytest.raises(C0LawError, match="item name"):
        compile_value_program(json.dumps(source), ports)


def test_predicate_lookup_needs_exact_declared_collection_path():
    ports = C0ValuePorts(
        roots={"scene": NestedScene},
        readable_paths=frozenset({"scene.boxes"}),
        admission_readable_paths=frozenset({"scene.boxes"}),
        readable_fields={
            NestedScene: frozenset({"boxes"}),
            NestedBox: frozenset({"id", "children"}),
            NestedChild: frozenset({"id"}),
        },
        admission_readable_fields={
            NestedScene: frozenset({"boxes"}),
            NestedBox: frozenset({"id", "children"}),
            NestedChild: frozenset({"id"}),
        },
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={"scene.boxes": "id"},
        outputs={"found": NestedChild},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [
            {
                "name": "box",
                "collection": "scene.boxes",
                "key": "id",
                "value": {"const": "B"},
                "required": True,
            },
            {
                "name": "found",
                "collection": "box.children",
                "as": "candidate",
                "where": {"eq": [{"ref": "candidate.id"}, {"const": "X"}]},
                "required": True,
            },
        ],
        "guard": {"const": True},
        "outputs": {"found": {"ref": "found"}},
    }
    with pytest.raises(C0LawError, match="declared collection"):
        compile_value_program(json.dumps(source), ports)
    unhashable_key = replace(ports, collection_keys={"scene.boxes": "children"})
    with pytest.raises(C0LawError, match="scalar identity"):
        compile_value_program(json.dumps(source), unhashable_key)


def test_predicate_lookup_checks_declared_key_integrity_outside_matches():
    source = _predicate_lookup_source()
    program = compile_value_program(
        json.dumps(source), _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt)
    )
    roots = {
        "scene": ParcelScene(
            3,
            (Parcel("P", "home"),),
            RouteBook((("chapel", 2, "inspect"), ("tower", 2, "x"), ("tower", 3, "y")), 9),
        ),
        "actor": ParcelActor("keeper", "heard", ()),
        "payload": ParcelAttempt("keeper", "dispatch", "chapel", "P"),
    }
    with pytest.raises(C0ValueStateError, match="not unique"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))


def test_admitted_effect_needs_occurrence_and_bounded_time():
    program = compile_value_program(
        json.dumps(_source()),
        _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt),
    )
    roots = {
        "scene": ParcelScene(3, (Parcel("P", "home"),), RouteBook((("chapel", 2, "inspect"),), 9)),
        "actor": ParcelActor("keeper", "heard", ()),
        "payload": ParcelAttempt("keeper", "dispatch", "chapel", "P"),
    }
    with pytest.raises(C0ValueStateError, match="actual occurrence"):
        program.evaluate(roots)
    roots["scene"] = replace(roots["scene"], tick=(1 << 63) - 1)
    with pytest.raises(C0ValueStateError, match="bounded integer"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))


def test_bounded_subtraction_requires_an_authored_guard() -> None:
    ports = C0ValuePorts(
        roots={"actor": BudgetOwner},
        readable_paths=frozenset({"actor.budget"}),
        admission_readable_paths=frozenset({"actor.budget"}),
        readable_fields={BudgetOwner: frozenset({"budget"})},
        admission_readable_fields={BudgetOwner: frozenset({"budget"})},
        writable_fields={BudgetOwner: frozenset({"budget"})},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"budget": int},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [{"name": "cost", "const": 2}],
        "guard": {"le": [{"ref": "cost"}, {"ref": "actor.budget"}]},
        "outputs": {"budget": {"sub": [{"ref": "actor.budget"}, {"ref": "cost"}]}},
    }
    program = compile_value_program(json.dumps(source), ports)
    assert not program.admits({"actor": BudgetOwner(1)})
    assert program.evaluate({"actor": BudgetOwner(2)}, occurrence=K0OccurrenceRef(1)) == {
        "budget": 0
    }
    source["guard"] = {"const": True}
    unchecked = compile_value_program(json.dumps(source), ports)
    with pytest.raises(C0ValueStateError, match="subtraction"):
        unchecked.evaluate({"actor": BudgetOwner(1)}, occurrence=K0OccurrenceRef(1))
    source["bindings"][0]["name"] = "actor"
    with pytest.raises(C0LawError, match="shadows"):
        compile_value_program(json.dumps(source), ports)


def test_bounded_multiplication_and_ceiling_division_are_exact() -> None:
    ports = C0ValuePorts(
        roots={"actor": BudgetOwner},
        readable_paths=frozenset({"actor.budget"}),
        admission_readable_paths=frozenset({"actor.budget"}),
        readable_fields={BudgetOwner: frozenset({"budget"})},
        admission_readable_fields={BudgetOwner: frozenset({"budget"})},
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"cost": int},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"const": True},
        "outputs": {
            "cost": {
                "ceil_div": [
                    {"mul": [{"const": 10}, {"const": 5}]},
                    {"ref": "actor.budget"},
                ]
            }
        },
    }
    program = compile_value_program(json.dumps(source), ports)
    assert program.evaluate({"actor": BudgetOwner(3)}, occurrence=K0OccurrenceRef(1)) == {
        "cost": 17
    }
    with pytest.raises(C0ValueStateError, match="ceiling division"):
        program.evaluate({"actor": BudgetOwner(0)}, occurrence=K0OccurrenceRef(1))

    source["outputs"]["cost"] = {"mul": [{"const": (1 << 63) - 1}, {"const": 2}]}
    overflow = compile_value_program(json.dumps(source), ports)
    with pytest.raises(C0ValueStateError, match="multiplication"):
        overflow.evaluate({"actor": BudgetOwner(1)}, occurrence=K0OccurrenceRef(1))


def test_replayable_die_is_effect_only_and_advances_from_current_seed() -> None:
    ports = C0ValuePorts(
        roots={"scene": DieScene},
        readable_paths=frozenset({"scene.seed", "scene.sides"}),
        admission_readable_paths=frozenset({"scene.seed", "scene.sides"}),
        readable_fields={DieScene: frozenset({"seed", "sides"})},
        admission_readable_fields={DieScene: frozenset({"seed", "sides"})},
        writable_fields={DieScene: frozenset({"seed"})},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"roll": int, "next_seed": int},
    )
    draw = {"die_roll": {"seed": _ref("scene.seed"), "sides": _ref("scene.sides")}}
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": _const(True),
        "outputs": {
            "roll": draw,
            "next_seed": {"die_next_seed": _ref("scene.seed")},
        },
    }
    program = compile_value_program(json.dumps(source), ports)
    initial = {"scene": DieScene(17, 20)}
    first = program.evaluate(initial, occurrence=K0OccurrenceRef(1))
    assert first == {"roll": 7, "next_seed": 7912066803415325917}
    assert first == program.evaluate(initial, occurrence=K0OccurrenceRef(2))
    assert 1 <= first["roll"] <= 20
    assert 0 <= first["next_seed"] < 1 << 63
    assert (
        program.evaluate({"scene": DieScene(first["next_seed"], 20)}, occurrence=K0OccurrenceRef(3))
        != first
    )
    assert (
        program.evaluate({"scene": DieScene(17, 6)}, occurrence=K0OccurrenceRef(4))["next_seed"]
        == first["next_seed"]
    )
    with pytest.raises(C0LawError, match="before Action admission"):
        compile_value_program(json.dumps(source), ports, admission_outputs=frozenset({"roll"}))

    source["guard"] = draw
    with pytest.raises(C0LawError, match="before Action admission"):
        compile_value_program(json.dumps(source), ports)
    source["guard"] = _const(True)
    with pytest.raises(C0ValueStateError, match="die draw"):
        program.evaluate({"scene": DieScene(17, 1)}, occurrence=K0OccurrenceRef(1))
    with pytest.raises(C0ValueStateError, match="die"):
        program.evaluate({"scene": DieScene(True, 20)}, occurrence=K0OccurrenceRef(1))


def test_authored_count_matching_is_round_scoped_and_port_checked() -> None:
    ports = C0ValuePorts(
        roots={"scene": BallotLedger, "payload": BallotQuery},
        readable_paths=frozenset({"scene.ballots", "scene.current_round", "payload.target"}),
        admission_readable_paths=frozenset(
            {"scene.ballots", "scene.current_round", "payload.target"}
        ),
        readable_fields={
            BallotLedger: frozenset({"ballots", "current_round"}),
            Ballot: frozenset({"round", "target"}),
            BallotQuery: frozenset({"target"}),
        },
        admission_readable_fields={
            BallotLedger: frozenset({"ballots", "current_round"}),
            Ballot: frozenset({"round", "target"}),
            BallotQuery: frozenset({"target"}),
        },
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"votes": int},
    )
    count = {
        "count_matching": {
            "collection": _ref("scene.ballots"),
            "as": "ballot",
            "where": {
                "all": [
                    {"eq": [_ref("ballot.round"), _ref("scene.current_round")]},
                    {"eq": [_ref("ballot.target"), _ref("payload.target")]},
                ]
            },
        }
    }
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"const": True},
        "outputs": {"votes": count},
    }
    program = compile_value_program(json.dumps(source), ports)
    roots = {
        "scene": BallotLedger(
            2,
            (
                Ballot(1, "C", K0OccurrenceRef(1)),
                Ballot(2, "C", K0OccurrenceRef(2)),
                Ballot(2, "C", K0OccurrenceRef(3)),
                Ballot(2, "B", K0OccurrenceRef(4)),
            ),
        ),
        "payload": BallotQuery("C"),
    }
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(5)) == {"votes": 2}
    roots["payload"] = BallotQuery("A")
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(5)) == {"votes": 0}

    count["count_matching"]["where"] = _const(1)
    with pytest.raises(C0LawError, match="predicate is not boolean"):
        compile_value_program(json.dumps(source), ports)
    count["count_matching"]["where"] = {"eq": [_ref("ballot.action"), _ref("ballot.action")]}
    with pytest.raises(C0LawError, match="read port"):
        compile_value_program(json.dumps(source), ports)


def test_conditional_value_selects_one_typed_branch_without_reading_the_other() -> None:
    ports = C0ValuePorts(
        roots={"actor": BudgetOwner},
        readable_paths=frozenset({"actor.budget"}),
        admission_readable_paths=frozenset({"actor.budget"}),
        readable_fields={BudgetOwner: frozenset({"budget"})},
        admission_readable_fields={BudgetOwner: frozenset({"budget"})},
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"result": int},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"const": True},
        "outputs": {
            "result": {
                "if": {
                    "when": {"lt": [_ref("actor.budget"), _const(2)]},
                    "then": _const(0),
                    "else": {"sub": [_ref("actor.budget"), _const(2)]},
                }
            }
        },
    }
    program = compile_value_program(json.dumps(source), ports)
    assert program.evaluate({"actor": BudgetOwner(1)}, occurrence=K0OccurrenceRef(1)) == {
        "result": 0
    }
    assert program.evaluate({"actor": BudgetOwner(4)}, occurrence=K0OccurrenceRef(1)) == {
        "result": 2
    }
    source["outputs"]["result"]["if"]["when"] = _const(1)
    with pytest.raises(C0LawError, match="guard is not boolean"):
        compile_value_program(json.dumps(source), ports)


def test_keyed_quantifier_and_append_reject_duplicate_receipts():
    program = compile_value_program(
        json.dumps(_source()),
        _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt),
    )
    roots = {
        "scene": ParcelScene(3, (Parcel("P", "home"),), RouteBook((("chapel", 2, "inspect"),), 9)),
        "actor": ParcelActor("keeper", "heard", ()),
        "payload": ParcelAttempt("keeper", "dispatch", "chapel", "P"),
    }
    previous = ParcelReceipt("P", K0OccurrenceRef(1), 0, 1)
    roots["actor"] = replace(roots["actor"], receipts=(previous,))
    with pytest.raises(C0ValueStateError, match="not unique"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))
    other = ParcelReceipt("Q", K0OccurrenceRef(2), 0, 1)
    roots["actor"] = replace(roots["actor"], receipts=(other, other))
    with pytest.raises(C0ValueStateError, match="not unique"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))


def test_duplicate_json_fields_and_undeclared_read_ports_reject_at_compile():
    ports = _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt)
    with pytest.raises(C0LawError, match="JSON"):
        compile_value_program('{"schema":"c0.value.v1","schema":"c0.value.v1"}', ports)
    source = _source()
    narrowed = replace(
        ports,
        readable_paths=ports.readable_paths - {"actor.heard"},
        admission_readable_paths=ports.admission_readable_paths - {"actor.heard"},
    )
    with pytest.raises(C0LawError, match="read boundary"):
        compile_value_program(json.dumps(source), narrowed)
    source = _source()
    source["outputs"]["new_packages"]["replace_unique"]["collection"] = {"ref": []}
    with pytest.raises(C0LawError, match="foreign key"):
        compile_value_program(json.dumps(source), ports)


def test_required_missing_and_duplicate_keys_are_state_defects():
    program = compile_value_program(
        json.dumps(_source()),
        _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt),
    )
    scene = ParcelScene(3, (), RouteBook((("chapel", 2, "inspect"),), 9))
    roots = {
        "scene": scene,
        "actor": ParcelActor("keeper", "heard", ()),
        "payload": ParcelAttempt("keeper", "dispatch", "chapel", "P"),
    }
    with pytest.raises(C0ValueStateError, match="required or unique"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))
    roots["scene"] = replace(scene, packages=(Parcel("P", "home"), Parcel("P", "home")))
    with pytest.raises(C0ValueStateError, match="not unique"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))
    roots["scene"] = replace(
        scene,
        packages=(Parcel("P", "home"),),
        source=RouteBook((("chapel", 2, "inspect"), ("chapel", 3, "inspect")), 9),
    )
    with pytest.raises(C0ValueStateError, match="not unique"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))
    roots["scene"] = replace(
        scene,
        packages=(Parcel("P", "home"), Parcel("Q", "home"), Parcel("Q", "home")),
    )
    with pytest.raises(C0ValueStateError, match="not unique"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(12))


@pytest.mark.parametrize(
    "change",
    (
        "unknown_field",
        "wrong_record",
        "unrefined_route",
        "foreign_write",
        "wrong_key",
        "bad_quantifier",
        "negative_time",
    ),
)
def test_bad_author_expression_rejects_at_compile(change):
    source = _source()
    if change == "unknown_field":
        source["guard"]["all"][3] = {"eq": [_ref("item.secret"), _const("x")]}
    elif change == "wrong_record":
        source["outputs"]["new_receipts"]["append"][1]["record"]["fields"]["due"] = _const("later")
    elif change == "unrefined_route":
        source["guard"]["all"].pop(4)
    elif change == "foreign_write":
        source["outputs"]["new_packages"]["replace_unique"]["new"]["copy"]["changes"]["id"] = (
            _const("Q")
        )
    elif change == "wrong_key":
        source["bindings"][0]["key"] = "status"
    elif change == "bad_quantifier":
        source["guard"]["all"][-1]["none_matching"]["where"] = _const(1)
    else:
        source["outputs"]["new_receipts"]["append"][1]["record"]["fields"]["due"] = _const(-1)
    with pytest.raises(C0LawError):
        compile_value_program(
            json.dumps(source),
            _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt),
        )


def test_optional_owner_path_needs_a_prior_nonnull_proof():
    ports = C0ValuePorts(
        roots={"actor": LocalReader},
        readable_paths=frozenset({"actor.sighting", "actor.sighting.carrier"}),
        admission_readable_paths=frozenset({"actor.sighting", "actor.sighting.carrier"}),
        readable_fields={
            LocalReader: frozenset({"sighting"}),
            LocalSighting: frozenset({"carrier"}),
        },
        admission_readable_fields={
            LocalReader: frozenset({"sighting"}),
            LocalSighting: frozenset({"carrier"}),
        },
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"carrier": str},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {
            "all": [
                {"not_none": {"ref": "actor.sighting"}},
                {"eq": [{"ref": "actor.sighting.carrier"}, {"const": "R1"}]},
            ]
        },
        "outputs": {"carrier": {"ref": "actor.sighting.carrier"}},
    }
    program = compile_value_program(json.dumps(source), ports)
    assert program.evaluate(
        {"actor": LocalReader(LocalSighting("R1"))}, occurrence=K0OccurrenceRef(1)
    ) == {"carrier": "R1"}
    assert program.admits({"actor": LocalReader(None)}) is False

    source["guard"] = source["guard"]["all"][1]
    with pytest.raises(C0LawError, match="nullable value"):
        compile_value_program(json.dumps(source), ports)


def _nested_optional_ports():
    paths = frozenset({"actor.entry", "actor.entry.value"})
    fields = {OptionalHolder: frozenset({"entry"}), OptionalValue: frozenset({"value"})}
    return C0ValuePorts(
        {"actor": OptionalHolder}, paths, paths, fields, fields, {}, {}, {}, {}, {}, {"value": int}
    )


@pytest.mark.parametrize("named", [False, True])
def test_nested_nonnull_proofs_preserve_short_circuit_order(named):
    proofs = [
        {"not_none": _ref("actor.entry")},
        {"not_none": _ref("actor.entry.value")},
    ]
    guard = (
        {"require": [{f"proof_{index}": item} for index, item in enumerate(proofs)]}
        if named
        else {"all": proofs}
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": guard,
        "outputs": {"value": _ref("actor.entry.value")},
    }
    program = compile_value_program(json.dumps(source), _nested_optional_ports())
    for entry in (None, OptionalValue(None)):
        assert not program.admits({"actor": OptionalHolder(entry)})
    assert program.evaluate(
        {"actor": OptionalHolder(OptionalValue(7))}, occurrence=K0OccurrenceRef(1)
    ) == {"value": 7}
    key = "require" if named else "all"
    source["guard"] = {key: list(reversed(guard[key]))}
    with pytest.raises(C0LawError, match="nullable value"):
        compile_value_program(json.dumps(source), _nested_optional_ports())
    source["guard"] = {"any": [proofs[0], {"const": True}]}
    with pytest.raises(C0LawError, match="nullable value"):
        compile_value_program(json.dumps(source), _nested_optional_ports())


def test_nested_if_nonnull_proof_inherits_outer_guard_only_in_selected_branch():
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"not_none": _ref("actor.entry")},
        "outputs": {
            "value": {
                "if": {
                    "when": {"not_none": _ref("actor.entry.value")},
                    "then": _ref("actor.entry.value"),
                    "else": _const(0),
                }
            }
        },
    }
    program = compile_value_program(json.dumps(source), _nested_optional_ports())
    for value, result in ((None, 0), (7, 7)):
        assert program.evaluate(
            {"actor": OptionalHolder(OptionalValue(value))}, occurrence=K0OccurrenceRef(1)
        ) == {"value": result}
    source["outputs"]["value"]["if"]["else"] = _ref("actor.entry.value")
    with pytest.raises(C0LawError, match="wrong nominal type"):
        compile_value_program(json.dumps(source), _nested_optional_ports())


def test_quantified_collection_can_prove_its_optional_input_locally() -> None:
    paths = frozenset({"actor.known", "actor.sites"})
    fields = {LocalChargeSample: frozenset({"known", "sites"})}
    ports = C0ValuePorts(
        roots={"actor": LocalChargeSample},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"count": int},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"const": True},
        "outputs": {
            "count": {
                "count_matching": {
                    "collection": {
                        "if": {
                            "when": {"not_none": {"ref": "actor.known"}},
                            "then": {
                                "if": {
                                    "when": {
                                        "lt": [
                                            {"const": 0},
                                            {"sub": [{"ref": "actor.known"}, {"const": 1}]},
                                        ]
                                    },
                                    "then": {"ref": "actor.sites"},
                                    "else": {"ref": "actor.sites"},
                                }
                            },
                            "else": {"ref": "actor.sites"},
                        }
                    },
                    "as": "site",
                    "where": {"eq": [{"ref": "site"}, {"const": "A"}]},
                }
            }
        },
    }
    program = compile_value_program(json.dumps(source), ports)
    assert program.evaluate(
        {"actor": LocalChargeSample(None, ("A",))}, occurrence=K0OccurrenceRef(1)
    ) == {"count": 1}
    assert program.evaluate(
        {"actor": LocalChargeSample(2, ("A",))}, occurrence=K0OccurrenceRef(2)
    ) == {"count": 1}


def test_guard_refines_the_nullable_record_itself() -> None:
    ports = C0ValuePorts(
        roots={"actor": LocalReader},
        readable_paths=frozenset({"actor.sighting"}),
        admission_readable_paths=frozenset({"actor.sighting"}),
        readable_fields={LocalReader: frozenset({"sighting"})},
        admission_readable_fields={LocalReader: frozenset({"sighting"})},
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"sighting": LocalSighting},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"not_none": {"ref": "actor.sighting"}},
        "outputs": {"sighting": {"ref": "actor.sighting"}},
    }
    program = compile_value_program(json.dumps(source), ports)
    assert program.admits({"actor": LocalReader(None)}) is False
    sighting = LocalSighting("R1")
    assert program.evaluate({"actor": LocalReader(sighting)}, occurrence=K0OccurrenceRef(1)) == {
        "sighting": sighting
    }


def test_checked_value_tree_does_not_reparse_or_follow_author_mutation(monkeypatch) -> None:
    ports = C0ValuePorts(
        roots={"actor": LocalReader},
        readable_paths=frozenset({"actor.sighting"}),
        admission_readable_paths=frozenset({"actor.sighting"}),
        readable_fields={LocalReader: frozenset({"sighting"})},
        admission_readable_fields={LocalReader: frozenset({"sighting"})},
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"sighting": LocalSighting},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"not_none": {"ref": "actor.sighting"}},
        "outputs": {"sighting": {"ref": "actor.sighting"}},
    }
    program = compile_value_program(json.dumps(source), ports)
    source["guard"]["not_none"]["ref"] = "actor.other"
    with pytest.raises(TypeError):
        program.guard_ir.expression["not_none"]["ref"] = "actor.other"

    def reject_reparse(*_args, **_kwargs):
        raise AssertionError("compiled value reparsed author JSON at runtime")

    monkeypatch.setattr(value_module.json, "loads", reject_reparse)
    assert program.admits({"actor": LocalReader(None)}) is False
    assert program.false_guard_clauses({"actor": LocalReader(None)})[0].expression == (
        '{"not_none":{"ref":"actor.sighting"}}'
    )
    sighting = LocalSighting("R1")
    assert program.evaluate({"actor": LocalReader(sighting)}, occurrence=K0OccurrenceRef(1)) == {
        "sighting": sighting
    }


def test_admission_cannot_read_a_bound_items_effect_only_field() -> None:
    ports = C0ValuePorts(
        roots={"scene": SealedItems},
        readable_paths=frozenset({"scene.items"}),
        admission_readable_paths=frozenset({"scene.items"}),
        readable_fields={
            SealedItems: frozenset({"items"}),
            SealedItem: frozenset({"id", "secret"}),
        },
        admission_readable_fields={
            SealedItems: frozenset({"items"}),
            SealedItem: frozenset({"id"}),
        },
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={"scene.items": "id"},
        outputs={"secret": str},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [
            {
                "name": "found",
                "collection": "scene.items",
                "key": "id",
                "value": {"const": "folio"},
                "required": True,
            }
        ],
        "guard": {"eq": [{"ref": "found.secret"}, {"const": "guess"}]},
        "outputs": {"secret": {"ref": "found.secret"}},
    }
    with pytest.raises(C0LawError, match="read port"):
        compile_value_program(json.dumps(source), ports)
    source["guard"] = {"const": True}
    program = compile_value_program(json.dumps(source), ports)
    assert program.evaluate(
        {"scene": SealedItems((SealedItem("folio", "actual"),))},
        occurrence=K0OccurrenceRef(1),
    ) == {"secret": "actual"}
    source["bindings"].append({**source["bindings"][0], "name": "another"})
    source["guard"] = {"eq": [{"ref": "found"}, {"ref": "another"}]}
    with pytest.raises(C0LawError, match="scalar"):
        compile_value_program(json.dumps(source), ports)


def test_admission_cannot_read_a_bound_tuples_effect_only_field() -> None:
    ports = _ports(ParcelScene, ParcelActor, ParcelAttempt, Parcel, ParcelReceipt)
    source = _source()
    source["guard"]["all"].append({"eq": [{"ref": "route.content"}, {"const": "guess"}]})
    with pytest.raises(C0LawError, match="tuple field"):
        compile_value_program(json.dumps(source), ports)
    source = _source()
    source["bindings"].append({**source["bindings"][1], "name": "another_route"})
    source["guard"] = {"eq": [{"ref": "route"}, {"ref": "another_route"}]}
    with pytest.raises(C0LawError, match="scalar"):
        compile_value_program(json.dumps(source), ports)
