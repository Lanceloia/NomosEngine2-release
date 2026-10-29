"""Decode one opening's assets and identities before Session control or publication begins."""

from types import MappingProxyType
from uuid import uuid4

from .carrying import opening_states as carrying_opening
from .entities import Reference, ReferenceDomain
from .expressions import ValueBudget
from .formation import FormationBatch
from .information import opening_states
from .opening import EntityInitialRecord, supplied_fields
from .randomness import opening_states as random_opening


def decode_opening(program, assets, limits):
    """Build fresh local data; never retain layouts or decoded defaults across Starts."""
    if (
        type(assets) is not dict
        or set(assets)
        != (
            {"schema", "actors", "objects"}
            | ({"contexts"} if any(p.fields for p in program.contexts) else set())
            | ({"random"} if program.random_streams else set())
            | ({"time"} if program.time is not None else set())
        )
        or assets["schema"] != "nomos.author.assets"
    ):
        raise ValueError("Assets require the exact selected author schema")
    if (
        type(assets["actors"]) is not dict
        or set(assets["actors"]) != set(dict(program.actors))
        or type(assets["objects"]) is not dict
    ):
        raise ValueError("Assets require exact opening actors and named objects")
    scope, symbols, states = uuid4().hex, {}, {}
    for name, sort in program.actors:
        symbols[name] = Reference(scope, len(symbols) + 1, sort)
    for name, value in sorted(assets["objects"].items()):
        if (
            type(name) is not str
            or not name
            or name in symbols
            or type(value) is not dict
            or set(value) != {"type", "state"}
            or value["type"] not in program.objects
        ):
            raise ValueError("object opening needs a unique symbol and selected sort")
        symbols[name] = Reference(scope, len(symbols) + 1, value["type"])
    references = ReferenceDomain(program.schemas, symbols)
    FormationBatch(references, limits, scope)
    initial_records = []
    layouts = {}
    for name, reference in symbols.items():
        schema = program.schemas[reference.sort]
        value = (
            assets["actors"][name] if schema.kind == "person" else assets["objects"][name]["state"]
        )
        if reference.sort not in layouts:
            layouts[reference.sort] = (
                set(dict(schema.fields)),
                {field: (owner, decode) for field, owner, decode in schema.initial},
                supplied_fields(program, references, reference.sort),
            )
        fields, initial, supplied = layouts[reference.sort]
        if (
            type(value) is not dict
            or not fields - supplied - initial.keys() <= set(value) <= fields
        ):
            raise ValueError("opening needs exact entity fields")
        state = {
            field: program.decoders[kind](value[field], ValueBudget(limits.value, references), ())
            for field, kind in schema.fields
            if field in value
        }
        for field in sorted(initial.keys() - value.keys()):
            owner, decode = initial[field]
            state[field] = decode(references, limits.value)
            initial_records.append(
                EntityInitialRecord(
                    f"author.{program.name}.entities.{owner}.initial.{field}",
                    reference,
                    field,
                    state[field],
                )
            )
        states[reference] = MappingProxyType(state)
    states.update(opening_states(program, assets, references, limits.value))
    states.update(carrying_opening(program, references))
    states.update(random_opening(program.random_streams, assets))
    return scope, symbols, references, states, tuple(initial_records)
