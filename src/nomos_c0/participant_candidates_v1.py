"""Compile explicit finite Object roles without adding world admission rules."""

import keyword
from dataclasses import replace
from types import MappingProxyType
from typing import get_args, get_type_hints

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError
from .composable_value_v1 import (
    _assignable,
    _compile_expression,
    _complete_value_fields,
    _expr_type,
    _guard_proofs,
    _tuple_item,
)
from .condition_source_v0 import lower_author_expression
from .private_actor_binding_v1 import compile_private_binding
from .seat_offers_v0 import (
    C0ActorOfferRange,
    C0LocalValueOfferRange,
    C0ObjectOfferRange,
    C0ParticipantOfferDeclaration,
    _local_value_read_paths,
)


def compile_participant_offer(item, action, ports, provider, index):
    selections = action.participants
    objects = tuple(p for p in selections if p.selector == "individual")
    actors = tuple(p for p in selections if p.selector in ("closed_domain", "actor"))
    bindings = item["for_each_participants"]
    if (
        not selections
        or type(bindings) is not dict
        or set(bindings) != {p.name for p in selections}
    ):
        raise C0LawError("participant offer requires every declared role")
    ranges = []
    paths = set()
    roots = dict(ports.roots)
    fields = {carrier: set(names) for carrier, names in ports.readable_fields.items()}
    for role in objects:
        row = bindings[role.name]
        if type(row) is not dict or set(row) not in ({"kind", "read"}, {"fixed_kind", "read"}):
            raise C0LawError("participant Object role needs a selected domain and read grant")
        singleton = "fixed_kind" in row
        if (
            role.kind is None
            or row["fixed_kind" if singleton else "kind"] != role.kind.family
            or (singleton and (len(role.kinds) != 1 or role.kind.max_instances != 1))
            or type(row["read"]) is not list
            or any(type(path) is not str for path in row["read"])
            or len(set(row["read"])) != len(row["read"])
            or any(
                not path.startswith(role.name + ".")
                or path not in action.value_ports.readable_paths
                for path in row["read"]
            )
        ):
            raise C0LawError("participant Object domain or read grant is incompatible")
        for root, carrier in ((role.name, role.state_type), (role.name + "_ref", _K0IndividualRef)):
            if root in roots:
                raise C0LawError("participant Object role roots alias")
            roots[root] = carrier
        ranges.append(
            C0ObjectOfferRange(
                role.name,
                role.payload_field,
                tuple(k.family for k in role.kinds),
                tuple(sorted(row["read"])),
                singleton,
            )
        )
        paths.add(role.name + "_ref")
        paths.update(row["read"])
        for path in row["read"]:
            carrier = role.state_type
            for part in path.split(".")[1:]:
                fields.setdefault(carrier, set()).add(part)
                annotation = get_type_hints(carrier).get(part)
                if annotation is None:
                    raise C0LawError("participant Object read path is foreign")
                variants = get_args(annotation)
                carrier = (
                    next(value for value in variants if value is not type(None))
                    if len(variants) == 2 and type(None) in variants
                    else annotation
                )
    ranged_actors = tuple(
        p
        for p in actors
        if type(bindings[p.name]) is dict
        and (
            set(bindings[p.name]) == {"selected_members", "as"}
            or set(bindings[p.name])
            == (
                {"collection", "as", "identity_field"}
                if p.selector == "actor"
                else {"collection", "as"}
            )
        )
    )
    if len(ranged_actors) > 1:
        raise C0LawError("participant offer allows at most one local Actor range")
    person = ranged_actors[0] if ranged_actors else None
    actor_range = None
    if person is not None:
        row = bindings[person.name]
        selected_members = "selected_members" in row
        if selected_members and (
            row["selected_members"] is not True or person.selector != "closed_domain"
        ):
            raise C0LawError("selected Actor candidates need an explicit closed member domain")
        candidate_type = (
            str
            if selected_members
            else _tuple_item(_expr_type(row["collection"], ports.roots, ports, set()))
        )
        identity = (
            None
            if selected_members
            else (row["identity_field"] if person.selector == "actor" else person.identity_field)
        )
        identity_type = _K0ActorRef if person.selector == "actor" else str
        if (
            type(row["as"]) is not str
            or row["as"] in roots
            or (
                not selected_members
                and (
                    type(identity) is not str
                    or get_type_hints(candidate_type).get(identity) is not identity_type
                )
            )
        ):
            raise C0LawError("participant Actor range needs an unaliased local identity record")
        actor_range = C0ActorOfferRange(
            person.name,
            row["as"],
            identity,
            None
            if selected_members
            else _compile_expression(
                row["collection"],
                dict(ports.roots),
                ports,
                set(),
                origin=f"offers[{index}].for_each_participants.{person.name}.collection",
            ),
            tuple(name for name, _ in person.members),
            person.actor_kind.family if person.selector == "actor" else None,
        )
        roots[row["as"]] = candidate_type
        # The range contains acquired local values, not views of target owners.
        paths.update(_local_value_read_paths(row["as"], candidate_type))
        for carrier, names in _complete_value_fields(candidate_type).items():
            fields.setdefault(carrier, set()).update(names)
    private_actor_fields = []
    for person_port in actors:
        if person_port is person:
            continue
        row = bindings[person_port.name]
        if (
            type(row) is not dict
            or person_port.selector == "actor"
            or set(row)
            not in ({"fixed_actor"}, {"fixed_actor", "private"}, {"fixed_actor", "private", "when"})
            or ("private" in row and row["private"] is not True)
            or len(person_port.members) != 1
            or row["fixed_actor"] != person_port.members[0][0]
        ):
            raise C0LawError("participant fixed Actor must be a selected singleton")
        if row.get("private") is True:
            private_actor_fields.append(compile_private_binding(row, person_port, action))
    local_range = None
    if "for_each" in item:
        row = item["for_each"]
        reserved = (
            set(roots)
            | {"occurrence", "payload", "initiator"}
            | {p.name for p in selections}
            | {p.name + "_ref" for p in selections}
        )
        if (
            type(row) is not dict
            or set(row) != {"collection", "as"}
            or type(row["collection"]) is not dict
            or set(row["collection"]) != {"ref"}
            or type(row["as"]) is not str
            or not row["as"].isidentifier()
            or keyword.iskeyword(row["as"])
            or row["as"] in reserved
        ):
            raise C0LawError("participant local value range needs an unaliased readable collection")
        collection_type = _expr_type(row["collection"], ports.roots, ports, set())
        item_type = _tuple_item(collection_type)
        local_range = C0LocalValueOfferRange(
            row["as"],
            _compile_expression(
                row["collection"],
                dict(ports.roots),
                ports,
                set(),
                origin=f"offers[{index}].for_each.collection",
            ),
        )
        roots[row["as"]] = item_type
        paths.update(_local_value_read_paths(row["as"], item_type))
        for carrier, names in _complete_value_fields(item_type).items():
            fields.setdefault(carrier, set()).update(names)
    ports = replace(
        ports,
        roots=roots,
        readable_paths=ports.readable_paths | paths,
        admission_readable_paths=ports.admission_readable_paths | paths,
        readable_fields={key: frozenset(value) for key, value in fields.items()},
        admission_readable_fields={key: frozenset(value) for key, value in fields.items()},
    )
    env = dict(ports.roots)
    visible, visible_paths = lower_author_expression(
        item["visible_when"], path=f"offers[{index}].visible_when"
    )
    condition, condition_paths = lower_author_expression(item["when"], path=f"offers[{index}].when")
    if _expr_type(visible, env, ports, set()) is not bool:
        raise C0LawError("participant offer visibility must be Boolean")
    proofs = _guard_proofs(visible, env, ports)
    if _expr_type(condition, env, ports, proofs) is not bool:
        raise C0LawError("participant offer condition must be Boolean")
    proofs.update(_guard_proofs(condition, env, ports, proofs))
    labels = item["label"]
    if type(labels) is not list or not 1 <= len(labels) <= 32:
        raise C0LawError("participant label needs finite string-expression fragments")
    if any(_expr_type(label, env, ports, proofs) is not str for label in labels):
        raise C0LawError("participant label fragment must be a readable string")
    payload = item["payload"]
    hints = get_type_hints(action.payload_type)
    private_fields = {binding.payload_field for binding in private_actor_fields}
    if type(payload) is not dict or set(payload) != set(hints) - {
        action.payload_actor_field,
        *private_fields,
    }:
        raise C0LawError("participant offer payload misses a declared field")
    for name, expression in payload.items():
        nullable = any(role.payload_field == name and role.nullable for role in actors)
        if (
            hints[name] not in (str, int, bool, _K0IndividualRef, _K0ActorRef, K0OccurrenceRef)
            and not (nullable and hints[name] == str | None)
            or (
                hints[name] is _K0ActorRef
                and name not in {role.payload_field for role in actors if role.selector == "actor"}
            )
            or not _assignable(_expr_type(expression, env, ports, proofs), hints[name])
        ):
            raise C0LawError("participant offer payload has a foreign public type")
    expected = {role.payload_field: {"ref": role.name + "_ref"} for role in objects}
    for role in actors:
        if role.payload_field in private_fields:
            continue
        expected[role.payload_field] = (
            {
                "ref": actor_range.alias
                if actor_range.identity_field is None
                else f"{actor_range.alias}.{actor_range.identity_field}"
            }
            if person is role
            else {"const": bindings[role.name]["fixed_actor"]}
        )
    if any(payload[name] != selection for name, selection in expected.items()):
        raise C0LawError("participant payload must use each resolved role selection")

    def expression(raw, path, nonnull=proofs):
        return _compile_expression(
            raw,
            env,
            ports,
            nonnull,
            origin=f"offers[{index}].{path}",
            source_paths=visible_paths
            if path == "visible_when"
            else condition_paths
            if path == "when"
            else None,
        )

    return C0ParticipantOfferDeclaration(
        item["entry"],
        tuple(ranges),
        actor_range,
        tuple(expression(label, f"label[{n}]") for n, label in enumerate(labels)),
        expression(visible, "visible_when", set()),
        expression(condition, "when", _guard_proofs(visible, env, ports)),
        MappingProxyType(
            {name: expression(value, f"payload.{name}") for name, value in payload.items()}
        ),
        ports,
        provider.max_candidates,
        local_range,
        tuple(sorted(private_actor_fields, key=lambda binding: binding.payload_field)),
    )
