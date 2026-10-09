"""Finite collection joins are nominal, permission-checked left semijoins."""

import json
from dataclasses import dataclass, replace
from itertools import product

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueStateError, compile_value_program
from nomos_c0.expression_read_authority_v1 import check_expression_reads


@dataclass(frozen=True)
class Assignment:
    id: str
    role: str
    secret: int = 0


@dataclass(frozen=True)
class Member:
    name: str
    alive: bool


@dataclass(frozen=True)
class World:
    roles: tuple[Assignment, ...]
    members: tuple[Member, ...]


def ports():
    paths = frozenset({"scene.roles", "scene.members"})
    fields = {
        World: frozenset({"roles", "members"}),
        Assignment: frozenset({"id", "role"}),
        Member: frozenset({"name", "alive"}),
    }
    return C0ValuePorts(
        roots={"scene": World},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"result": tuple[Assignment, ...]},
    )


def query():
    return {
        "query": {
            "from": {"collection": {"ref": "scene.roles"}, "as": "assigned", "key": "id"},
            "join": {"collection": {"ref": "scene.members"}, "as": "living", "key": "name"},
            "where": "assigned.role == 'witch' and living.alive",
        }
    }


def compile_query(expression=None, selected=None):
    return compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": True,
                "outputs": {"result": query() if expression is None else expression},
            }
        ),
        ports() if selected is None else selected,
        admission_outputs=frozenset({"result"}),
    )


def evaluate(program, world):
    return program.evaluate({"scene": world}, occurrence=K0OccurrenceRef(1))["result"]


def test_collection_join_uses_different_nominal_rows_and_key_names():
    program = compile_query()
    tree = program._tree["outputs"]["result"]
    assert tree.operation == "collection_query"
    assert tree.result_type == tuple[Assignment, ...]
    world = World(
        (Assignment("B", "witch"), Assignment("A", "witch"), Assignment("C", "witch")),
        (Member("A", True), Member("B", True)),
    )
    assert evaluate(program, world) == world.roles[:2]
    check_expression_reads(tree, ports(), frozenset({"scene"}))
    assert evaluate(program, replace(world, members=(Member("B", False), Member("A", True)))) == (
        world.roles[1],
    )
    assert evaluate(program, replace(world, members=())) == ()
    assert evaluate(program, replace(world, roles=())) == ()


def test_living_role_query_matches_nested_existence_for_every_three_member_configuration():
    program = compile_query()
    for alive, witch in product(product((False, True), repeat=3), repeat=2):
        world = World(
            tuple(
                Assignment(name, "witch" if flag else "villager")
                for name, flag in zip("ABC", witch, strict=True)
            ),
            tuple(Member(name, flag) for name, flag in zip("CBA", alive, strict=True)),
        )
        expected = tuple(
            role
            for role in world.roles
            if role.role == "witch"
            and any(member.name == role.id and member.alive for member in world.members)
        )
        assert evaluate(program, world) == expected


@pytest.mark.parametrize("side", ["left", "right"])
def test_duplicates_reject_even_when_where_would_hide_them(side):
    world = World((Assignment("A", "villager"),), (Member("A", False),))
    world = (
        replace(world, roles=world.roles * 2)
        if side == "left"
        else replace(world, members=world.members * 2)
    )
    with pytest.raises(C0ValueStateError, match="unique"):
        evaluate(compile_query(), world)


@pytest.mark.parametrize(
    "change",
    [
        "both_sources",
        "key_type",
        "nullable_runtime_key",
        "shadow",
        "nonbool",
        "left_read",
        "left_key_read",
        "right_read",
        "input_read",
    ],
)
def test_malformed_or_unauthorized_query_rejects(change):
    expression, selected = query(), ports()
    body = expression["query"]
    if change == "both_sources":
        body["join"]["participants"] = "unknown"
    elif change == "key_type":
        body["join"]["key"] = "alive"
    elif change == "nullable_runtime_key":
        with pytest.raises(C0ValueStateError, match="nominal"):
            evaluate(compile_query(), World((Assignment(None, "witch"),), (Member("A", True),)))
        return
    elif change == "shadow":
        body["join"]["as"] = "assigned"
    elif change == "nonbool":
        body["where"] = {"ref": "assigned.id"}
    elif change == "left_read":
        body["where"] = "assigned.secret == 0"
    elif change == "left_key_read":
        selected = replace(
            selected,
            admission_readable_fields={
                **selected.admission_readable_fields,
                Assignment: frozenset({"role"}),
            },
        )
    elif change == "right_read":
        selected = replace(
            selected,
            admission_readable_fields={
                **selected.admission_readable_fields,
                Member: frozenset({"alive"}),
            },
        )
    else:
        selected = replace(selected, admission_readable_paths=frozenset({"scene.roles"}))
    with pytest.raises(C0LawError):
        compile_query(expression, selected)


def test_nested_query_alias_is_lexical_and_cannot_shadow_outer_rows():
    expression = query()
    expression["query"]["where"] = {
        "eq": [
            0,
            {
                "count_matching": {
                    "collection": query(),
                    "as": "row",
                    "where": True,
                }
            },
        ]
    }
    with pytest.raises(C0LawError, match="shadows"):
        compile_query(expression)


def test_read_projection_does_not_grant_access_to_collection_inputs():
    tree = compile_query()._tree["outputs"]["result"]
    with pytest.raises(C0LawError, match="authority"):
        check_expression_reads(tree, ports(), frozenset())


def test_nested_query_with_distinct_aliases_can_read_checked_outer_row():
    expression = query()
    inner = query()
    inner["query"]["from"]["as"] = "other_role"
    inner["query"]["join"]["as"] = "other_member"
    inner["query"]["where"] = "other_role.id == assigned.id and other_member.alive"
    expression["query"]["where"] = {
        "eq": [1, {"count_matching": {"collection": inner, "as": "matched", "where": True}}]
    }
    program = compile_query(expression)
    check_expression_reads(program._tree["outputs"]["result"], ports(), frozenset({"scene"}))
    world = World(
        (Assignment("A", "villager"), Assignment("B", "witch")),
        (Member("A", True), Member("B", False)),
    )
    assert evaluate(program, world) == world.roles[:1]
