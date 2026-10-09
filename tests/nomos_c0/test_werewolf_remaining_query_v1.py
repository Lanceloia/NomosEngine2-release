"""The authored faction count uses a closed query, not an actor or role-specific host."""

import json
from dataclasses import make_dataclass, replace
from functools import cache

import pytest
from test_six_seat_werewolf_v0 import SIX, THREE, _part

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueStateError, compile_value_program
from nomos_c0.declarative_nominal_v0 import check_nominal_lib


@cache
def model():
    checked = check_nominal_lib(_part(THREE, "lib"), _part(SIX, "source")["actor_domains"])
    records = dict(checked.records)
    player, assignment = records["Player"], records["Assignment"]
    fields = {player: frozenset({"id", "alive"}), assignment: frozenset({"id", "role"})}
    annotations = {
        "players": tuple[player, ...],
        "roles": tuple[assignment, ...],
        "excluded": str | None,
        "wolf_side": bool,
    }
    census = make_dataclass("Census", list(annotations.items()), frozen=True)
    fields[census] = frozenset(annotations)
    paths = frozenset(f"census.{name}" for name in annotations)
    ports = C0ValuePorts(
        roots={"census": census},
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
        pure_definitions=checked.pure_definitions,
    )
    source = json.dumps(
        {
            "schema": "c0.value.v1",
            "bindings": [],
            "guard": True,
            "outputs": {
                "count": {
                    "call": {
                        "ref": "town.remaining_count",
                        "args": {name: {"ref": f"census.{name}"} for name in annotations},
                    }
                }
            },
        }
    )
    return player, assignment, census, ports, source


def test_authored_count_handles_all_alive_masks_exclusions_and_both_factions():
    player, assignment, census, ports, source = model()
    program = compile_value_program(source, ports, admission_outputs=frozenset({"count"}))
    names, roles = "ABCDEF", ("seer", "witch", "wolf", "wolf", "villager", "villager")
    assignments = tuple(assignment(name, role) for name, role in zip(names, roles, strict=True))
    for mask in range(64):
        players = tuple(player(name, bool(mask & (1 << index))) for index, name in enumerate(names))
        for excluded in (None, *names, "unknown"):
            for wolf_side in (False, True):
                expected = sum(
                    item.alive and item.id != excluded and (role == "wolf") == wolf_side
                    for item, role in zip(players, roles, strict=True)
                )
                for table in (assignments, assignments[::-1]):
                    roots = dict(
                        players=players, roles=table, excluded=excluded, wolf_side=wolf_side
                    )
                    assert program.evaluate_admission_outputs({"census": census(**roots)}) == {
                        "count": expected
                    }
    assert program.evaluate_admission_outputs(
        {"census": census(players=(), roles=(), excluded=None, wolf_side=True)}
    ) == {"count": 0}


@pytest.mark.parametrize("field", ["id", "role"])
def test_pure_query_does_not_borrow_caller_assignment_read_permission(field):
    _, assignment, _, ports, source = model()
    fields = dict(ports.readable_fields)
    fields[assignment] = fields[assignment] - {field}
    denied = replace(ports, readable_fields=fields, admission_readable_fields=fields)
    with pytest.raises(C0LawError):
        compile_value_program(source, denied, admission_outputs=frozenset({"count"}))


@pytest.mark.parametrize("table", ["players", "roles"])
def test_query_rejects_duplicate_identity_instead_of_multiplying_count(table):
    player, assignment, census, ports, source = model()
    program = compile_value_program(source, ports, admission_outputs=frozenset({"count"}))
    roots = dict(
        players=(player("A", True),),
        roles=(assignment("A", "wolf"),),
        excluded=None,
        wolf_side=True,
    )
    roots[table] *= 2
    with pytest.raises(C0ValueStateError, match="unique"):
        program.evaluate_admission_outputs({"census": census(**roots)})


def role_count_source(role):
    source = json.loads(model()[-1])
    source["outputs"]["count"]["call"] = {
        "ref": "town.living_role_count",
        "args": {
            "players": {"ref": "census.players"},
            "roles": {"ref": "census.roles"},
            "role": {"const": role},
        },
    }
    return json.dumps(source)


def test_living_role_count_matches_current_role_and_alive_state_without_table_order_dependency():
    player, assignment, census, ports, _ = model()
    names, roles = "ABCDEF", ("seer", "witch", "wolf", "wolf", "villager", "villager")
    assignments = tuple(assignment(name, role) for name, role in zip(names, roles, strict=True))
    for role in ("seer", "witch", "wolf", "villager", "unknown"):
        program = compile_value_program(
            role_count_source(role), ports, admission_outputs=frozenset({"count"})
        )
        for mask in range(64):
            players = tuple(
                player(name, bool(mask & (1 << index))) for index, name in enumerate(names)
            )
            expected = sum(
                item.alive and assigned == role
                for item, assigned in zip(players, roles, strict=True)
            )
            for table in (assignments, assignments[::-1]):
                current = census(players, table, None, False)
                assert program.evaluate_admission_outputs({"census": current}) == {
                    "count": expected
                }
        assert program.evaluate_admission_outputs({"census": census((), (), None, False)}) == {
            "count": 0
        }


@pytest.mark.parametrize("field", ["id", "role"])
def test_living_role_count_requires_assignment_field_read_permission(field):
    _, assignment, _, ports, _ = model()
    fields = dict(ports.readable_fields)
    fields[assignment] = fields[assignment] - {field}
    denied = replace(ports, readable_fields=fields, admission_readable_fields=fields)
    with pytest.raises(C0LawError):
        compile_value_program(
            role_count_source("wolf"), denied, admission_outputs=frozenset({"count"})
        )


@pytest.mark.parametrize("table", ["players", "roles"])
def test_living_role_count_rejects_duplicate_id(table):
    player, assignment, census, ports, _ = model()
    program = compile_value_program(
        role_count_source("wolf"), ports, admission_outputs=frozenset({"count"})
    )
    current = dict(
        players=(player("A", True),),
        roles=(assignment("A", "wolf"),),
        excluded=None,
        wolf_side=False,
    )
    current[table] *= 2
    with pytest.raises(C0ValueStateError, match="unique"):
        program.evaluate_admission_outputs({"census": census(**current)})
