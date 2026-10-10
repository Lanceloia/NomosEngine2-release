"""Check data-only Action/Event port declarations and build a C0 graph library."""

from __future__ import annotations

import json
from dataclasses import is_dataclass
from typing import get_args, get_origin, get_type_hints

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceRef,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError, _unique_object
from .author_document_v1 import C0AuthorDocument, C0SourceContext
from .candidate_input_v1 import C0CandidateInputPorts, check_candidate_input
from .checked_value_binding_v1 import C0ValueBackend
from .compile_budget_v1 import COMPILE_BUDGET
from .composable_action_v1 import (
    C0ActionParticipantPorts,
    C0ActionSchedulePorts,
    C0ActionTargetPorts,
    C0SelfActorPorts,
    C0ValueActionPorts,
)
from .composable_value_v1 import C0ValuePorts, _assignable, _check_ports
from .declarative_nominal_v0 import C0CheckedNominalLib, _name, _row
from .direct_actor_event_v1 import C0DirectActorPorts, C0EventTrigger
from .direct_scene_event_v1 import C0DirectScenePorts
from .endpoint_signature_v1 import action_outputs, endpoint_field
from .graph_contracts_v1 import (
    C0GraphAction,
    C0GraphDue,
    C0GraphEvent,
    C0GraphLibrary,
    C0GraphOperation,
)
from .opening_construction_v1 import check_construction_ports
from .participant_group_v1 import expand_participant_groups
from .scheduled_scene_event_v1 import C0DueValue, C0ScheduledScenePorts, C0TimeValue
from .seat_offer_preview_v0 import C0SeatOfferPreviewPorts
from .seat_offers_v0 import C0FiniteOfferProvider
from .seat_read_projection_v0 import (
    SEAT_READ_OUTPUT_TYPES,
    C0SeatReadPorts,
    check_fixed_projection_roots,
)


def _items(value: object, label: str, *, minimum: int = 0) -> list[object]:
    if type(value) is not list or not minimum <= len(value) <= 64:
        raise C0LawError(f"{label} must be a finite list")
    return value


def _mapping(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict or len(value) > 64 or any(type(key) is not str for key in value):
        raise C0LawError(f"{label} must be a finite string-keyed object")
    return value


def _symbol(value: object, label: str) -> str:
    return _name(value, label)


def _key(key_type: type, value: object, label: str) -> object:
    if type(value) is not str:
        raise C0LawError(f"{label} must be a string")
    try:
        return key_type(value)
    except K0ProfileError as error:
        raise C0LawError(f"{label} is invalid") from error


def _field_map(raw: object, label: str) -> dict[str, str]:
    if type(raw) is list:
        names = _items(raw, label)
        if any(type(name) is not str for name in names) or len(set(names)) != len(names):
            raise C0LawError(f"{label} has aliased or malformed fields")
        return {name: name for name in names}
    mapping = _mapping(raw, label)
    if any(type(alias) is not str for alias in mapping.values()):
        raise C0LawError(f"{label} output is malformed")
    return mapping


def _output_destinations(raw: dict, value: C0ValuePorts, roots: frozenset[str]):
    effects = []
    for alias, declaration in _mapping(raw.get("outputs", {}), "Lib outputs").items():
        destination = (
            declaration["target"]
            if type(declaration) is dict and set(declaration) == {"target", "type"}
            else declaration
        )
        if type(destination) is not str or "." not in destination:
            continue
        if destination.count(".") != 1 or destination.split(".")[0] not in roots:
            raise C0LawError("Lib owner output must target its declared owner")
        root = destination.split(".")[0]
        _, field, _ = endpoint_field(value.roots, destination)
        if destination not in raw["write_paths"]:
            raise C0LawError("Lib owner output lacks an explicit write permission")
        if any(
            (prior_root, prior_field) == (root, field) for prior_root, prior_field, _ in effects
        ):
            raise C0LawError("Lib owner output destinations alias")
        effects.append((root, field, alias))
    return tuple(effects)


def _owner_output_effects(raw: dict, value: C0ValuePorts, root: str):
    return tuple(
        (field, alias) for _, field, alias in _output_destinations(raw, value, frozenset({root}))
    )


def _actor_domain_ports(name, kind, raw, checked, roots):
    from .actor_domain_v1 import C0ActorDomainPorts

    value = _value_ports(raw, checked, endpoint_roots=roots)
    effects = _owner_output_effects(raw, value, "actor")
    if not effects or {alias for _, alias in effects} != set(value.outputs):
        raise C0LawError("Lib Actor domain outputs need explicit member destinations")
    return C0ActorDomainPorts(name, kind, value, effects)


def _value_ports(
    raw: object,
    checked: C0CheckedNominalLib,
    *,
    endpoint_roots: dict[str, type],
    endpoint_outputs: dict[str, object] | None = None,
    participant_groups=(),
) -> C0ValuePorts:
    optional = {"outputs"}
    row = _row(
        raw,
        {"read", "fields", "write_paths", "construct", "collections"}
        | (set(raw) & optional if type(raw) is dict else set()),
        "Lib value ports",
    )
    builtins = {
        "str": str,
        "int": int,
        "bool": bool,
        "occurrence_ref": K0OccurrenceRef,
        "individual_ref": _K0IndividualRef,
        "actor_ref": _K0ActorRef,
        "event_trigger": C0EventTrigger,
        "due": C0DueValue,
        "time": C0TimeValue,
    }
    records = dict(checked.records)
    if set(records) & set(builtins):
        raise C0LawError("Lib record name collides with a port type")
    types = builtins | records

    def resolve(name: object) -> type:
        if type(name) is not str or name not in types:
            raise C0LawError("Lib port type is not declared")
        return types[name]

    def resolve_output(value: object) -> object:
        if type(value) is str and "." in value:
            return endpoint_field(endpoint_roots, value)[2]
        if type(value) is dict and set(value) == {"target", "type"}:
            target_type = endpoint_field(endpoint_roots, value["target"])[2]
            if (
                type(value["type"]) is str
                and "." in value["type"]
                or type(value["type"]) is dict
                and "target" in value["type"]
            ):
                raise C0LawError("Lib output refinement must name a type, not another endpoint")
            annotation = resolve_output(value["type"])
            if not _assignable(annotation, target_type):
                raise C0LawError("Lib output refinement differs from its endpoint type")
            return annotation
        if type(value) is dict and set(value) == {"tuple"}:
            item = value["tuple"]
            if type(item) is str and item in types:
                return tuple[types[item], ...]
            raise C0LawError("Lib tuple output needs a declared type")
        if type(value) is dict and set(value) == {"optional"}:
            item = value["optional"]
            if type(item) is str and item in types:
                return types[item] | None
            raise C0LawError("Lib optional output needs a declared type")
        return resolve(value)

    roots = endpoint_roots
    if not roots or any(not name.isidentifier() or name.startswith("_") for name in roots):
        raise C0LawError("Lib roots are malformed")
    paths = row["read"]
    if type(paths) is not list or not paths:
        raise C0LawError("Lib readable paths must be a nonempty finite list")
    COMPILE_BUDGET.check("value_read_paths", len(paths), stage="Ports value readable paths")
    if len(paths) != len(set(map(str, paths))):
        raise C0LawError("Lib readable paths alias")
    readable: dict[type, set[str]] = {}
    resolved: dict[type, dict[str, object]] = {}

    def annotations(carrier):
        if carrier not in resolved:
            resolved[carrier] = get_type_hints(carrier) if is_dataclass(carrier) else {}
        return resolved[carrier]

    for path in paths:
        if type(path) is str and path in roots:
            if roots[path] is _K0IndividualRef:
                continue
            variants = get_args(roots[path])
            if len(variants) == 2 and type(None) in variants:
                continue
        if type(path) is not str or path.count(".") < 1:
            raise C0LawError("Lib readable path is malformed")
        parts = path.split(".")
        current = roots.get(parts[0])
        if current is None:
            raise C0LawError("Lib readable path has an unknown root")
        if current is _K0IndividualRef:
            raise C0LawError("Lib individual input is opaque and has no readable fields")
        for field in parts[1:]:
            variants = get_args(current)
            if len(variants) == 2 and type(None) in variants:
                current = next(item for item in variants if item is not type(None))
            hints = annotations(current)
            if field not in hints:
                raise C0LawError("Lib readable path has an unknown field")
            readable.setdefault(current, set()).add(field)
            current = hints[field]
            variants = get_args(current)
            if len(variants) == 2 and type(None) in variants:
                current = next(item for item in variants if item is not type(None))
    for carrier, names in _mapping(row["fields"], "Lib extra readable fields").items():
        target = resolve(carrier)
        selected = _items(names, "Lib extra readable fields")
        if not is_dataclass(target) or any(
            type(name) is not str or name not in annotations(target) for name in selected
        ):
            raise C0LawError("Lib extra readable field is not declared")
        readable.setdefault(target, set()).update(selected)
    writable: dict[type, frozenset[str]] = {}
    selected = _items(row["write_paths"], "Lib write paths")
    if any(type(path) is not str for path in selected) or len(set(selected)) != len(selected):
        raise C0LawError("Lib write paths are malformed or aliased")
    for path in selected:
        target, field, _ = endpoint_field(roots, path)
        writable[target] = writable.get(target, frozenset()) | {field}
    explicit_outputs = {
        name: resolve_output(carrier)
        for name, carrier in _mapping(row.get("outputs", {}), "Lib outputs").items()
    }
    outputs = dict(endpoint_outputs or {})
    for name, annotation in explicit_outputs.items():
        if name in outputs and annotation == outputs[name]:
            raise C0LawError(f"Lib output {name} redundantly repeats its endpoint type")
        if name in outputs and not _assignable(annotation, outputs[name]):
            raise C0LawError(f"Lib output {name} differs from its endpoint type")
        outputs[name] = annotation
    if not outputs or any(not name.isidentifier() for name in outputs):
        raise C0LawError("Lib outputs are malformed")
    constructors = _items(row["construct"], "Lib constructors")
    if any(type(name) is not str or name not in records for name in constructors):
        raise C0LawError("Lib constructor is not a declared record")
    collections = _mapping(row["collections"], "Lib collection keys")
    if any(type(name) is not str or type(key) is not str for name, key in collections.items()):
        raise C0LawError("Lib collection key is malformed")
    ports = C0ValuePorts(
        roots=roots,
        readable_paths=frozenset(paths),
        admission_readable_paths=frozenset(paths),
        readable_fields={carrier: frozenset(names) for carrier, names in readable.items()},
        admission_readable_fields={
            carrier: frozenset(names) for carrier, names in readable.items()
        },
        writable_fields=writable,
        writable_paths=frozenset(selected),
        record_types={name: records[name] for name in constructors},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys=collections,
        outputs=outputs,
        pure_definitions=checked.attributed_pure_definitions(),
        participant_groups=participant_groups,
    )
    return _check_ports(ports)


def check_graph_ports(
    source: str | dict[str, object] | C0AuthorDocument, checked: C0CheckedNominalLib
) -> C0GraphLibrary:
    """Turn checked nominal carriers and declared port signatures into one graph library."""
    checked.check_record_layout()
    source_context = source.context() if type(source) is C0AuthorDocument else None
    if type(source) is C0AuthorDocument:
        source = source.to_data()
    if type(source) is str:
        if not source:
            raise C0LawError("Lib port source is empty")
        try:
            source_bytes = len(source.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise C0LawError("Lib port source is not valid UTF-8") from error
        COMPILE_BUDGET.check("ports_source_bytes", source_bytes, stage="Ports parse")
        try:
            source = json.loads(source, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError) as error:
            raise C0LawError("Lib port source is malformed JSON") from error
    row = _row(
        source,
        {"schema", "scene_owner", "offer_provider", "actions", "events", "due_events"}
        | ({"operations"} if type(source) is dict and "operations" in source else set())
        | ({"candidate_inputs"} if type(source) is dict and "candidate_inputs" in source else set())
        | (
            {"participant_groups"}
            if type(source) is dict and "participant_groups" in source
            else set()
        )
        | (
            {"opening_constructions"}
            if type(source) is dict and "opening_constructions" in source
            else set()
        )
        | (
            {"seat_read_projections"}
            if type(source) is dict and "seat_read_projections" in source
            else set()
        )
        | (
            {"seat_offer_previews"}
            if type(source) is dict and "seat_offer_previews" in source
            else set()
        ),
        "Lib ports",
    )
    if row["schema"] != "c0.graph_ports.v1":
        raise C0LawError("Lib port schema is unknown")
    try:
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as error:
        raise C0LawError("Lib ports are not finite JSON data") from error
    COMPILE_BUDGET.check(
        "ports_canonical_bytes", len(canonical.encode("ascii")), stage="Ports declaration"
    )
    authored_groups = row.get("participant_groups", [])
    authored_actions = row["actions"]
    row = expand_participant_groups(row)
    group_members = {group["name"]: tuple(group["members"]) for group in authored_groups}
    action_groups = [
        tuple((name, group_members[name]) for name in action.get("participant_groups", []))
        for action in authored_actions
    ]
    COMPILE_BUDGET.check(
        "ports_canonical_bytes",
        len(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("ascii")),
        stage="Expanded Ports declaration",
    )
    provider = _row(row["offer_provider"], {"name", "version", "limit"}, "Lib offer provider")
    if (
        type(provider["limit"]) is not int
        or not 1 <= provider["limit"] <= COMPILE_BUDGET.finite_offers
    ):
        raise C0LawError("Lib offer limit is malformed")
    if type(provider["version"]) is not str or not 1 <= len(provider["version"]) <= 64:
        raise C0LawError("Lib offer version is malformed")
    offer = C0FiniteOfferProvider(
        _symbol(provider["name"], "Lib offer name"),
        provider["version"],
        provider["limit"],
    )
    owners = {item.symbol: item.owner for item in checked.owners}
    representatives = {name: members[0] for name, members in checked.owner_templates}

    def owner(symbol: object):
        if type(symbol) is str and symbol in representatives:
            symbol = representatives[symbol]
        if type(symbol) is not str or symbol not in owners:
            raise C0LawError("Lib port owner is not declared")
        return owners[symbol]

    scene_owner = owner(_symbol(row["scene_owner"], "Lib Scene owner"))
    scene_symbol = next(item.symbol for item in checked.owners if item.owner.key == scene_owner.key)
    actions = []
    action_rows = row["actions"]
    if type(action_rows) is not list or not action_rows:
        raise C0LawError("Lib actions must be a nonempty finite list")
    COMPILE_BUDGET.check("actions", len(action_rows), stage="Ports action templates")
    for action_index, raw in enumerate(action_rows):
        item = _row(
            raw,
            {
                "symbol",
                "actor",
                "payload",
                "envelope",
                "actor_identity_field",
                "payload_actor_field",
                "effects",
                "envelope_fields",
                "schedule",
                "value",
            }
            | ({"target"} if type(raw) is dict and "target" in raw else set())
            | ({"participants"} if type(raw) is dict and "participants" in raw else set())
            | ({"actor_domains"} if type(raw) is dict and "actor_domains" in raw else set()),
            "Lib action",
        )
        schedule = item["schedule"]
        action_symbol = _symbol(item["symbol"], "Lib Action symbol")
        if schedule is not None:
            schedule = _row(
                schedule,
                {"one_shot_field", "subject_output", "delay_output"},
                "Lib action schedule",
            )
            schedule = C0ActionSchedulePorts(
                _key(K0SourceSpecKey, f"c0.template.{action_symbol}.due", "template due source"),
                _symbol(schedule["one_shot_field"], "Lib one-shot field"),
                _symbol(schedule["subject_output"], "Lib subject output"),
                _symbol(schedule["delay_output"], "Lib delay output"),
            )
        effects = _mapping(item["effects"], "Lib Action effects")
        target_row = item.get("target")
        target = None
        participants = []
        if target_row is not None and "participants" in item:
            raise C0LawError("Lib Action cannot mix target and participant declarations")
        if target_row is not None:
            target_row = _row(target_row, {"state", "payload_field", "write"}, "Lib Action target")
            if type(target_row["write"]) is not bool:
                raise C0LawError("Lib Action target write permission is malformed")
            target = C0ActionTargetPorts(
                _symbol(target_row["payload_field"], "Lib target payload field"),
                checked.record(target_row["state"]),
                target_row["write"],
            )
            if (
                get_type_hints(checked.record(item["payload"])).get(target.payload_field)
                is not _K0IndividualRef
            ):
                raise C0LawError("Lib Action target payload is not an individual reference")
        for raw_participant in _items(item.get("participants", []), "Lib participants"):
            declaration = _row(
                raw_participant,
                {"name", "selector", "state", "payload_field", "write"}
                | (
                    {"nullable"}
                    if type(raw_participant) is dict and "nullable" in raw_participant
                    else set()
                ),
                "Lib Action participant",
            )
            name = _symbol(declaration["name"], "Lib participant name")
            selector = declaration["selector"]
            payload_field = _symbol(declaration["payload_field"], "Lib participant payload")
            nullable = declaration.get("nullable", False)
            if (
                selector not in ("individual", "closed_domain", "actor")
                or type(declaration["write"]) is not bool
                or type(nullable) is not bool
                or (nullable and selector != "closed_domain")
            ):
                raise C0LawError("Lib Action participant selector or permission is malformed")
            expected = {
                "individual": _K0IndividualRef,
                "closed_domain": str | None if nullable else str,
                "actor": _K0ActorRef,
            }[selector]
            annotation = get_type_hints(checked.record(item["payload"])).get(payload_field)
            if (annotation != expected) if nullable else (annotation is not expected):
                raise C0LawError("Lib Action participant payload type does not match selector")
            participants.append(
                C0ActionParticipantPorts(
                    name,
                    selector,
                    payload_field,
                    checked.record(declaration["state"]),
                    declaration["write"],
                    nullable,
                )
            )
        names = tuple(participant.name for participant in participants)
        if names != tuple(sorted(set(names))) or len(
            {p.payload_field for p in participants}
        ) != len(participants):
            raise C0LawError("Lib Action participants need unique canonical names and fields")
        if set(effects) != {"scene", "actor", *names, *({"target"} if target else set())}:
            raise C0LawError("Lib Action effects do not match declared owner ports")
        effect_rows = {
            name: _field_map(value, "Lib Action owner effects") for name, value in effects.items()
        }
        if any(
            type(field) is not str or type(output) is not str
            for values in effect_rows.values()
            for field, output in values.items()
        ):
            raise C0LawError("Lib Action effect is malformed")
        envelope_fields = _field_map(item["envelope_fields"], "Lib Action envelope")
        if any(type(value) is not str for value in envelope_fields.values()):
            raise C0LawError("Lib Action envelope field is malformed")
        self_actor = type(item["actor"]) is dict
        if self_actor:
            binding = _row(item["actor"], {"self"}, "Lib Action self")
            kind = next(
                (kind for kind in checked.actor_kinds if kind.symbol == binding["self"]), None
            )
            if kind is None or item["actor_identity_field"] is not None:
                raise C0LawError("Lib Action self needs a declared Actor kind, not a state name")
            actor_symbol = kind.symbol
            actor_owner = C0SelfActorPorts(kind.symbol, kind.factory.state_type, kind.factory)
        else:
            actor_symbol = _symbol(item["actor"], "Lib Action actor")
            actor_symbol = representatives.get(actor_symbol, actor_symbol)
            actor_owner = owner(actor_symbol)
        payload_type = checked.record(item["payload"])
        envelope_type = checked.record(item["envelope"])
        roots = {
            "scene": scene_owner.view_type,
            "actor": actor_owner.view_type,
            "payload": payload_type,
            **{
                participant.name: participant.state_type | None
                if participant.nullable
                else participant.state_type
                for participant in participants
            },
            **({"target": target.state_type} if target else {}),
        }
        outputs = action_outputs(
            roots,
            effect_rows,
            envelope_type,
            envelope_fields,
            ((schedule.subject_output, str), (schedule.delay_output, int)) if schedule else (),
        )
        domain_ports = []
        actors = {kind.symbol: kind for kind in checked.actor_kinds}
        for raw_domain in _items(item.get("actor_domains", []), "Lib Action Actor domains"):
            domain = _row(raw_domain, {"name", "kind", "value"}, "Lib Action Actor domain")
            name = _symbol(domain["name"], "Lib Action Actor domain name")
            kind = actors.get(domain["kind"]) if type(domain["kind"]) is str else None
            if (
                kind is None
                or "initiator" in roots
                or name in {*roots, "initiator", "occurrence"}
                or any(p.name == name or p.kind.symbol == kind.symbol for p in domain_ports)
            ):
                raise C0LawError("Lib Action Actor domain aliases or has an unknown kind")
            raw_value = domain["value"]
            if (
                type(raw_value) is not dict
                or type(raw_value.get("write_paths")) is not list
                or any(
                    type(path) is not str or not path.startswith("actor.")
                    for path in raw_value["write_paths"]
                )
            ):
                raise C0LawError("Action Actor domain may write only its member")
            domain_ports.append(
                _actor_domain_ports(
                    name,
                    kind,
                    raw_value,
                    checked,
                    {
                        **roots,
                        "initiator": roots["actor"],
                        "actor": kind.factory.state_type,
                    },
                )
            )
        actions.append(
            C0GraphAction(
                action_symbol,
                actor_symbol,
                C0ValueActionPorts(
                    _key(
                        K0SourceSpecKey,
                        f"c0.template.{action_symbol}.action",
                        "template Action source",
                    ),
                    _key(
                        K0EventTypeKey,
                        f"c0.template.{action_symbol}.action",
                        "template Action type",
                    ),
                    scene_owner,
                    actor_owner,
                    payload_type,
                    checked.contribution_type,
                    envelope_type,
                    _value_ports(
                        item["value"],
                        checked,
                        endpoint_roots=roots,
                        endpoint_outputs=outputs,
                        participant_groups=action_groups[action_index],
                    ),
                    None
                    if self_actor
                    else _symbol(item["actor_identity_field"], "Lib Actor identity field"),
                    _symbol(item["payload_actor_field"], "Lib payload Actor field"),
                    effect_rows,
                    envelope_fields,
                    schedule=schedule,
                    target=target,
                    participants=tuple(participants),
                    actor_domains=tuple(domain_ports),
                ),
            )
        )
    events = []
    for raw in _items(row["events"], "Lib events"):
        item = _row(
            raw,
            {
                "symbol",
                "form",
                "actor",
                "actor_identity_field",
                "value",
            }
            | (
                {"read_actor_domains"}
                if type(raw) is dict and "read_actor_domains" in raw
                else set()
            ),
            "Lib Event",
        )
        event_symbol = _symbol(item["symbol"], "Lib Event symbol")
        identity = (
            _key(K0SourceSpecKey, f"c0.template.{event_symbol}.event", "template Event source"),
            _key(K0EventTypeKey, f"c0.template.{event_symbol}.event", "template Event type"),
            _key(K0CausalLawKey, f"c0.template.{event_symbol}.causes", "template causal key"),
        )
        if item["form"] in ("direct_actor", "direct_scene"):
            from .actor_domain_v1 import C0ReadActorDomainPorts

            domains = []
            kinds = {kind.symbol: kind for kind in checked.actor_kinds}
            for raw_domain in _items(
                item.get("read_actor_domains", []), "Lib Event read Actor domains"
            ):
                domain = _row(
                    raw_domain,
                    {
                        "name",
                        "kind",
                        "wrapper",
                        "members_field",
                        "record",
                        "identity_field",
                        "fields",
                    },
                    "Lib Event read Actor domain",
                )
                kind = kinds.get(domain["kind"]) if type(domain["kind"]) is str else None
                if kind is None:
                    raise C0LawError("Lib Event read Actor domain has an unknown nominal kind")
                domains.append(
                    C0ReadActorDomainPorts(
                        _symbol(domain["name"], "Lib Event read Actor root"),
                        kind,
                        checked.record(domain["wrapper"]),
                        _symbol(domain["members_field"], "Lib Event members field"),
                        checked.record(domain["record"]),
                        _symbol(domain["identity_field"], "Lib Event actual identity field"),
                        tuple(
                            _field_map(domain["fields"], "Lib Event projected Actor fields").items()
                        ),
                    )
                )
        else:
            raise C0LawError("Lib Event form is malformed")
        if (
            item["form"] == "direct_scene"
            and item["actor"] is None
            and item["actor_identity_field"] is None
        ):
            value = _value_ports(
                item["value"],
                checked,
                endpoint_roots={
                    "scene": scene_owner.view_type,
                    "trigger": C0EventTrigger,
                    **{domain.name: domain.wrapper for domain in domains},
                },
            )
            ports = C0DirectScenePorts(
                *identity,
                scene_owner,
                checked.contribution_type,
                value,
                read_actor_domains=tuple(domains),
            )
            ports.check_domains()
        elif item["form"] == "direct_actor":
            actor_owner = owner(item["actor"])
            value = _value_ports(
                item["value"],
                checked,
                endpoint_roots={
                    "scene": scene_owner.view_type,
                    "actor": actor_owner.view_type,
                    "trigger": C0EventTrigger,
                    **{domain.name: domain.wrapper for domain in domains},
                },
            )
            ports = C0DirectActorPorts(
                *identity,
                scene_owner,
                actor_owner,
                _symbol(item["actor_identity_field"], "Lib Event Actor identity field"),
                checked.contribution_type,
                value,
                read_actor_domains=tuple(domains),
            )
            ports.check_domains()
        else:
            raise C0LawError("Lib Event form or Actor binding is malformed")
        root = "scene" if type(ports) is C0DirectScenePorts else "actor"
        effects = _owner_output_effects(item["value"], value, root)
        events.append(C0GraphEvent(event_symbol, ports, effects))
    due = []
    for raw in _items(row["due_events"], "Lib due Events"):
        if (
            type(raw) is not dict
            or not {"symbol", "value"} <= set(raw)
            or not set(raw)
            <= {
                "symbol",
                "value",
                "owner_roots",
                "fixed_individual_roots",
                "actor_domains",
                "read_object_domains",
            }
        ):
            raise C0LawError("Lib due Event has missing or unknown fields")
        item = raw
        due_symbol = _symbol(item["symbol"], "Lib due symbol")
        extra = item.get("owner_roots", [])
        if type(extra) is not list or len(extra) > 32:
            raise C0LawError("Lib due owner roots are not a closed finite selection")
        extra_roots = []
        for raw_root in extra:
            if type(raw_root) is str:
                name, symbol = raw_root, raw_root
            else:
                selected_root = _row(raw_root, {"name", "owner"}, "Lib due owner root")
                name, symbol = selected_root["name"], selected_root["owner"]
            if (
                type(name) is not str
                or not name
                or name in ("scene", "due", "time")
                or any(previous[0] == name for previous in extra_roots)
            ):
                raise C0LawError("Lib due owner roots are not a closed finite selection")
            extra_roots.append((name, owner(symbol)))
        fixed = item.get("fixed_individual_roots", [])
        if type(fixed) is not list or len(fixed) > 32:
            raise C0LawError("Lib due fixed Object roots are not a finite selection")
        kinds = {kind.symbol: kind for kind in checked.object_kinds}
        fixed_roots = []
        for raw_root in fixed:
            selected_root = _row(raw_root, {"name", "kind", "binding"}, "Lib due fixed Object root")
            name = _symbol(selected_root["name"], "Lib due fixed Object root name")
            kind_name = selected_root["kind"]
            kind = kinds.get(kind_name) if type(kind_name) is str else None
            if (
                name in ("scene", "due", "time")
                or kind is None
                or selected_root["binding"] != "fixed_unique_opening"
                or any(
                    previous[0] == name or previous[1] == kind.symbol for previous in fixed_roots
                )
            ):
                raise C0LawError("Lib due fixed Object binding is malformed")
            fixed_roots.append((name, kind.symbol, kind.k0_kind.state_type))
        endpoint_roots = {
            "scene": scene_owner.view_type,
            "due": C0DueValue,
            "time": C0TimeValue,
            **{name: selected.view_type for name, selected in extra_roots},
            **{name: state for name, _, state in fixed_roots},
        }
        from .object_domain_v1 import C0ReadObjectDomainPorts, check_read_object_domains

        object_domains = []
        for raw_domain in _items(
            item.get("read_object_domains", []), "Lib due read Object domains"
        ):
            domain = _row(
                raw_domain,
                {"name", "kind", "wrapper", "members_field", "record", "identity_field", "fields"},
                "Lib due read Object domain",
            )
            kind = kinds.get(domain["kind"]) if type(domain["kind"]) is str else None
            if kind is None:
                raise C0LawError("Lib due read Object domain has an unknown nominal kind")
            object_domains.append(
                C0ReadObjectDomainPorts(
                    _symbol(domain["name"], "Lib due read Object root"),
                    kind,
                    checked.record(domain["wrapper"]),
                    _symbol(domain["members_field"], "Lib due Object members field"),
                    checked.record(domain["record"]),
                    _symbol(domain["identity_field"], "Lib due Object actual identity field"),
                    tuple(_field_map(domain["fields"], "Lib due projected Object fields").items()),
                )
            )
        check_read_object_domains(tuple(object_domains), {*endpoint_roots, "actor"})
        endpoint_roots.update({domain.name: domain.wrapper for domain in object_domains})
        domain_ports = []
        actors = {kind.symbol: kind for kind in checked.actor_kinds}
        for raw_domain in _items(item.get("actor_domains", []), "Lib due Actor domains"):
            domain = _row(raw_domain, {"name", "kind", "value"}, "Lib due Actor domain")
            name = _symbol(domain["name"], "Lib due Actor domain name")
            kind = actors.get(domain["kind"]) if type(domain["kind"]) is str else None
            if (
                kind is None
                or name in endpoint_roots
                or name == "actor"
                or any(
                    previous.name == name or previous.kind.symbol == kind.symbol
                    for previous in domain_ports
                )
            ):
                raise C0LawError("Lib due Actor domain aliases or has an unknown kind")
            domain_ports.append(
                _actor_domain_ports(
                    name,
                    kind,
                    domain["value"],
                    checked,
                    {**endpoint_roots, "actor": kind.factory.state_type},
                )
            )
        due_value = _value_ports(item["value"], checked, endpoint_roots=endpoint_roots)
        due.append(
            C0GraphDue(
                due_symbol,
                C0ScheduledScenePorts(
                    _key(K0SourceSpecKey, f"c0.template.{due_symbol}.due", "template due source"),
                    _key(K0EventTypeKey, f"c0.template.{due_symbol}.due", "template due type"),
                    scene_owner,
                    checked.contribution_type,
                    due_value,
                    tuple(extra_roots),
                    tuple(fixed_roots),
                    actor_domains=tuple(domain_ports),
                    read_object_domains=tuple(object_domains),
                ),
                _output_destinations(
                    item["value"],
                    due_value,
                    frozenset({"scene", *(name for name, _ in extra_roots)}),
                ),
            )
        )
    action_map = {item.symbol: item for item in actions}
    kind_sorts = {item.sort.identity.value: item for item in checked.object_kinds}
    operations = []
    for raw in _items(row.get("operations", []), "Lib operations"):
        item = _row(
            raw,
            {"id", "receiver_sort", "action_template", "implementations"},
            "Lib operation",
        )
        symbol = _symbol(item["id"], "Lib operation id")
        sort = kind_sorts.get(item["receiver_sort"]) if type(item["receiver_sort"]) is str else None
        action = (
            action_map.get(item["action_template"])
            if type(item["action_template"]) is str
            else None
        )
        if (
            sort is None
            or action is None
            or action.ports.target is None
            or action.ports.target.state_type is not sort.k0_kind.state_type
            or any(previous.symbol == symbol for previous in operations)
        ):
            raise C0LawError("Lib operation receiver or Action template is invalid")
        implementations = []
        for implementation in _items(item["implementations"], "Lib implementations", minimum=1):
            candidate = _row(implementation, {"id", "law"}, "Lib implementation")
            identity = _symbol(candidate["id"], "Lib implementation id")
            law = candidate["law"]
            if type(law) is not str or not 1 <= len(law) <= 128:
                raise C0LawError("Lib implementation LawDef is malformed")
            if any(prior[0] == identity for prior in implementations):
                raise C0LawError("Lib implementation identity is repeated")
            implementations.append((identity, law))
        operations.append(
            C0GraphOperation(symbol, sort.sort, action.symbol, tuple(implementations))
        )
    seat_reads = []
    kinds = {kind.symbol: kind for kind in checked.object_kinds}
    for raw in _items(row.get("seat_read_projections", []), "Lib seat read projections"):
        item = _row(
            raw,
            {
                "symbol",
                "actor",
                "collection_field",
                "current_field",
                "candidate_key",
                "fixed_individual_root",
                "max_candidates",
                "value",
            }
            | (
                set(raw) & {"fixed_actor_roots", "additional_fixed_individual_roots"}
                if type(raw) is dict else set()
            ),
            "Lib seat read projection",
        )
        symbol = _symbol(item["symbol"], "Lib seat read symbol")
        actor_symbol = _symbol(item["actor"], "Lib seat read Actor")
        actor_owner = owner(actor_symbol)
        fixed = _row(
            item["fixed_individual_root"],
            {"name", "kind", "binding"},
            "Lib seat read Object",
        )
        object_root = _symbol(fixed["name"], "Lib seat read Object root")
        kind = kinds.get(fixed["kind"]) if type(fixed["kind"]) is str else None
        fixed_actors = []
        for raw_root in _items(item.get("fixed_actor_roots", []), "Lib seat read fixed Actors"):
            root = _row(raw_root, {"name", "actor"}, "Lib seat read fixed Actor")
            fixed_actors.append((
                _symbol(root["name"], "Lib seat read fixed Actor root"),
                _symbol(root["actor"], "Lib seat read fixed Actor symbol"),
            ))
        fixed_objects = []
        for raw_root in _items(
            item.get("additional_fixed_individual_roots", []), "Lib seat read fixed Objects"
        ):
            root = _row(raw_root, {"name", "kind", "binding"}, "Lib seat read fixed Object")
            if root["binding"] != "fixed_unique_opening":
                raise C0LawError("Lib seat read fixed Object binding is malformed")
            fixed_objects.append((
                _symbol(root["name"], "Lib seat read fixed Object root"),
                _symbol(root["kind"], "Lib seat read fixed Object kind"),
            ))
        fixed_actors = tuple(fixed_actors)
        fixed_objects = tuple(fixed_objects)
        check_fixed_projection_roots(
            object_root, fixed["kind"], actor_symbol, fixed_actors, fixed_objects,
            frozenset(owner.symbol for owner in checked.owners if owner.identity_field is not None),
            frozenset(kinds),
        )
        endpoint_roots = {
            "scene": scene_owner.view_type,
            "actor": actor_owner.view_type,
            object_root: kind.k0_kind.state_type if kind else None,
            **{name: owners[symbol].view_type for name, symbol in fixed_actors},
            **{name: kinds[symbol].k0_kind.state_type for name, symbol in fixed_objects},
            **{
                f"{name}_ref": _K0IndividualRef
                for name in (object_root, *(name for name, _ in fixed_objects))
            },
        }
        collection_field = _symbol(item["collection_field"], "Lib seat read collection")
        current_field = _symbol(item["current_field"], "Lib seat read current field")
        candidate_key = _symbol(item["candidate_key"], "Lib seat read candidate key")
        hints = get_type_hints(actor_owner.view_type)
        collection_type = hints.get(collection_field)
        candidate_args = get_args(collection_type)
        candidate_type = candidate_args[0] if len(candidate_args) == 2 else None
        limit = item["max_candidates"]
        endpoint_roots["candidate"] = candidate_type
        value = _value_ports(
            item["value"],
            checked,
            endpoint_roots=endpoint_roots,
        )
        if (
            any(previous.symbol == symbol for previous in seat_reads)
            or actor_owner.key == scene_owner.key
            or object_root in {"scene", "actor", "candidate"}
            or kind is None
            or fixed["binding"] != "fixed_unique_opening"
            or get_origin(collection_type) is not tuple
            or candidate_args != (candidate_type, Ellipsis)
            or candidate_type not in dict(checked.records).values()
            or get_type_hints(candidate_type).get(candidate_key) is not str
            or hints.get(current_field) is not str
            or type(limit) is not int
            or not 1 <= limit <= 32
            or dict(value.roots)
            != endpoint_roots
            or value.writable_fields
            or value.writable_paths
            or value.record_types
            or value.readable_fields.get(_K0IndividualRef)
            or any(output not in SEAT_READ_OUTPUT_TYPES for output in value.outputs.values())
        ):
            raise C0LawError("Lib seat read projection exceeds its closed port")
        seat_reads.append(
            C0SeatReadPorts(
                symbol,
                scene_symbol,
                actor_symbol,
                collection_field,
                current_field,
                candidate_type,
                candidate_key,
                object_root,
                kind.symbol,
                value,
                limit,
                fixed_actors,
                fixed_objects,
            )
        )
    previews = []
    for raw in _items(row.get("seat_offer_previews", []), "Lib seat offer previews"):
        item = _row(
            raw,
            {
                "symbol",
                "actor",
                "action_template",
                "collection_field",
                "current_field",
                "candidate_origin_field",
                "candidate_key",
                "offer_payload_key",
                "fixed_individual_root",
                "max_candidates",
                "value",
            },
            "Lib seat offer preview",
        )
        symbol = _symbol(item["symbol"], "Lib seat offer preview symbol")
        actor_symbol = _symbol(item["actor"], "Lib seat offer preview Actor")
        actor_owner = owner(actor_symbol)
        action = (
            action_map.get(item["action_template"])
            if type(item["action_template"]) is str
            else None
        )
        fixed = _row(
            item["fixed_individual_root"],
            {"name", "kind", "binding"},
            "Lib seat offer preview Object",
        )
        object_root = _symbol(fixed["name"], "Lib seat offer preview Object root")
        kind = kinds.get(fixed["kind"]) if type(fixed["kind"]) is str else None
        collection_field = _symbol(item["collection_field"], "Lib preview collection")
        current_field = _symbol(item["current_field"], "Lib preview current field")
        origin_field = _symbol(item["candidate_origin_field"], "Lib preview origin field")
        candidate_key = _symbol(item["candidate_key"], "Lib preview candidate key")
        payload_key = _symbol(item["offer_payload_key"], "Lib preview payload key")
        hints = get_type_hints(actor_owner.view_type)
        collection_type = hints.get(collection_field)
        candidate_args = get_args(collection_type)
        candidate_type = candidate_args[0] if len(candidate_args) == 2 else None
        limit = item["max_candidates"]
        value = _value_ports(
            item["value"],
            checked,
            endpoint_roots={
                "scene": scene_owner.view_type,
                "actor": actor_owner.view_type,
                "candidate": candidate_type,
                object_root: kind.k0_kind.state_type if kind else None,
            },
        )
        if (
            any(previous.symbol == symbol for previous in previews)
            or action is None
            or action.actor != actor_symbol
            or get_type_hints(action.ports.payload_type).get(payload_key) is not str
            or actor_owner.key == scene_owner.key
            or object_root in {"scene", "actor", "candidate"}
            or kind is None
            or fixed["binding"] != "fixed_unique_opening"
            or get_origin(collection_type) is not tuple
            or candidate_args != (candidate_type, Ellipsis)
            or candidate_type not in dict(checked.records).values()
            or get_type_hints(candidate_type).get(origin_field) is not str
            or get_type_hints(candidate_type).get(candidate_key) is not str
            or hints.get(current_field) is not str
            or type(limit) is not int
            or not 1 <= limit <= 32
            or dict(value.roots)
            != {
                "scene": scene_owner.view_type,
                "actor": actor_owner.view_type,
                "candidate": candidate_type,
                object_root: kind.k0_kind.state_type,
            }
            or value.writable_fields
            or value.writable_paths
            or value.record_types
            or any(output not in (str, int, bool) for output in value.outputs.values())
        ):
            raise C0LawError("Lib seat offer preview exceeds its closed port")
        previews.append(
            C0SeatOfferPreviewPorts(
                symbol,
                scene_symbol,
                actor_symbol,
                action.symbol,
                collection_field,
                current_field,
                origin_field,
                candidate_type,
                candidate_key,
                payload_key,
                object_root,
                kind.symbol,
                value,
                limit,
            )
        )
    candidate_inputs = []
    for raw in _items(row.get("candidate_inputs", []), "Lib candidate inputs"):
        item = _row(raw, {"symbol", "action", "read", "fields"}, "Lib candidate input")
        symbol = _symbol(item["symbol"], "Lib candidate input name")
        action = next((entry for entry in actions if entry.symbol == item["action"]), None)
        if action is None or any(port.symbol == symbol for port in candidate_inputs):
            raise C0LawError("Lib candidate input has an unknown Action or repeated name")
        value = _value_ports(
            {
                "read": item["read"],
                "fields": item["fields"],
                "write_paths": [],
                "construct": [],
                "collections": {},
            },
            checked,
            endpoint_roots=dict(action.ports.value_ports.roots),
            endpoint_outputs={"allowed": bool},
            participant_groups=action.ports.value_ports.participant_groups,
        )
        check_candidate_input(action.ports, value)
        candidate_inputs.append(C0CandidateInputPorts(symbol, action.symbol, value))
    return C0GraphLibrary(
        checked.owners,
        tuple(actions),
        tuple(events),
        offer,
        tuple(due),
        checked.owner_templates,
        checked.lawdefs,
        checked.object_kinds,
        tuple(operations),
        tuple(seat_reads),
        tuple(previews),
        checked.attributed_pure_definitions(),
        checked.source_context,
        C0SourceContext(
            source_context.index,
            (("", ()),)
            + tuple(
                (f"{collection}.{item['symbol']}", (collection, index))
                for collection in (
                    "actions",
                    "events",
                    "due_events",
                    "seat_read_projections",
                    "seat_offer_previews",
                    "candidate_inputs",
                )
                for index, item in enumerate(row.get(collection, []))
            ),
        )
        if source_context is not None
        else None,
        value_backend=C0ValueBackend(checked.record_layout, checked.owner_layout),
        actor_kinds=checked.actor_kinds,
        appraisal_definitions=checked.appraisal_definitions,
        candidate_inputs=tuple(candidate_inputs),
        opening_constructions=check_construction_ports(
            row.get("opening_constructions", []), checked
        ),
    )
