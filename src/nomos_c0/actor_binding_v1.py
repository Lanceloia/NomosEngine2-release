"""Expand closed Actor domains into independently identified C0 instances."""

from __future__ import annotations

import keyword
from copy import deepcopy

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame, C0SourceContext, C0SourceIndex
from .compile_budget_v1 import COMPILE_BUDGET


def _identifier(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.isidentifier()
        or keyword.iskeyword(value)
        or value.startswith("_")
        or len(value) > 64
    ):
        raise C0LawError(f"{label} must be a finite public identifier")
    return value


def _row(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise C0LawError(f"{label} has missing or unknown fields")
    return value


def _prefix(value: object, label: str) -> str:
    if type(value) is not str or not value or len(value) > 192:
        raise C0LawError(f"{label} is malformed")
    return value


def _unique_generated_values(
    generated: list[object], existing: list[object], field: str, label: str
) -> None:
    generated_values = [
        row[field] for row in generated if type(row) is dict and type(row.get(field)) is str
    ]
    existing_values = {
        row[field] for row in existing if type(row) is dict and type(row.get(field)) is str
    }
    if len(generated_values) != len(set(generated_values)) or any(
        value in existing_values for value in generated_values
    ):
        raise C0LawError(f"expanded {label} identities alias")


def _unique_result_groups(generated: list[object], existing: list[object]) -> None:
    for field in ("source_key", "event_type"):
        label = "source" if field == "source_key" else "Event type"
        seen: dict[str, dict[str, object]] = {}
        existing_values = {
            row[field] for row in existing if type(row) is dict and type(row.get(field)) is str
        }
        for raw in generated:
            if type(raw) is not dict:
                continue
            value = raw.get(field)
            if type(value) is not str:
                continue
            if value in existing_values:
                raise C0LawError(f"expanded {label} identities alias")
            prior = seen.get(value)
            if prior is not None and not (
                type(raw.get("shared_result")) is str
                and raw.get("shared_result") == prior.get("shared_result")
                and all(
                    raw.get(key) == prior.get(key)
                    for key in (
                        "template",
                        "actor",
                        "source_key",
                        "event_type",
                        "law",
                    )
                )
            ):
                raise C0LawError(f"expanded {label} identities alias")
            seen[value] = raw


def _bind_actor_refs(node: object, actor: str) -> object:
    if type(node) is dict:
        if set(node) == {"ref"} and type(node["ref"]) is str:
            ref = node["ref"]
            return {"ref": f"{actor}{ref[5:]}"} if ref.startswith("actor.") else dict(node)
        return {key: _bind_actor_refs(value, actor) for key, value in node.items()}
    if type(node) is list:
        return [_bind_actor_refs(value, actor) for value in node]
    return node


def _bind_domain_sizes(
    node: object, domains: dict[str, tuple[type, str | None, tuple[str, ...]]]
) -> object:
    if type(node) is dict:
        if set(node) == {"domain_size"}:
            name = node["domain_size"]
            if type(name) is not str or name not in domains:
                raise C0LawError("opening domain size needs a declared Actor domain")
            return {"const": len(domains[name][2])}
        return {key: _bind_domain_sizes(value, domains) for key, value in node.items()}
    if type(node) is list:
        return [_bind_domain_sizes(value, domains) for value in node]
    return node


def _event_recipients(
    item: dict[str, object],
    domains: dict[str, tuple[type, str | None, tuple[str, ...]]],
    owner_types: dict[str, tuple[type, str | None]],
    *,
    trigger_actor: str | None = None,
) -> tuple[tuple[str | None, ...], bool]:
    if "actor" in item and "actor_domain" in item:
        raise C0LawError("Event family needs one Actor recipient binding")
    if "actor_domain" in item:
        name = item["actor_domain"]
        domain = domains.get(name) if type(name) is str else None
        if domain is None:
            raise C0LawError("Event family Actor domain is foreign")
        return domain[2], True
    recipient = item.get("actor")
    correlated = type(recipient) is dict
    if correlated:
        if recipient != {"from_trigger": "actor"} or trigger_actor is None:
            raise C0LawError("Event recipient correlation needs an Action trigger actor")
        recipient = trigger_actor
    if "actor" in item and (
        type(recipient) is not str
        or recipient not in owner_types
        or owner_types[recipient][1] is None
    ):
        raise C0LawError("Event family Actor recipient is foreign")
    return (recipient,), correlated


def expand_actor_bindings(
    source: dict[str, object],
    owner_types: dict[str, tuple[type, str | None]],
    action_templates: dict[str, str],
    scene_event_templates: frozenset[str],
    scheduled_templates: frozenset[str] = frozenset(),
    actor_event_templates: frozenset[str] = frozenset(),
    *,
    source_context: C0SourceContext | None = None,
    origins: dict[tuple[str, str], C0SourceContext] | None = None,
) -> dict[str, object]:
    """Lower typed domains without choosing roles or bypassing later port checks."""
    from .offer_set_v1 import expand_offer_sets
    from .participant_binding_v1 import expand_participant_bindings

    source, participant_frames = expand_participant_bindings(source, owner_types, source_context)
    source, offer_origins = expand_offer_sets(source, source_context)

    def origin(collection, name, index, *, arguments=(), aliases=()):
        if origins is None:
            return
        path = (collection, index)
        span = source_context.index.spans.get(path) if source_context else None
        frames = (
            (C0OriginFrame("actor_instance", name, repr(path), span, arguments),)
            if arguments
            else ()
        )
        if collection == "actions":
            frames = (*frames, *participant_frames.get(index, ()))
        scoped_frames = ()
        if collection == "seats":
            offer_aliases = {
                f"offers[{offer_index}]": offer_path
                for (seat_index, offer_index), (offer_path, _) in offer_origins.items()
                if seat_index == index
            }
            aliases = tuple(
                (key, value) for key, value in aliases if key not in offer_aliases
            ) + tuple(offer_aliases.items())
            scoped_frames = tuple(
                (f"offers[{offer_index}]", offer_frames)
                for (seat_index, offer_index), (_, offer_frames) in offer_origins.items()
                if seat_index == index
            )
        origins[collection, name] = C0SourceContext(
            source_context.index if source_context else C0SourceIndex({}),
            (("", path), *aliases),
            frames,
            scoped_frames,
        )

    declarations = source.get("actor_domains", [])
    if type(declarations) is not list or len(declarations) > 64:
        raise C0LawError("Actor domains must be finite declarations")
    domains: dict[str, tuple[type, str | None, tuple[str, ...]]] = {}
    for raw in declarations:
        if type(raw) is not dict:
            raise C0LawError("Actor domain is malformed")
        item = _row(
            raw,
            {"name", "actor_state", "owners"}
            | ({"owner_template"} if "owner_template" in raw else set()),
            "Actor domain",
        )
        if "owner_template" in item:
            _identifier(item["owner_template"], "Actor owner template")
        name = _identifier(item["name"], "Actor domain name")
        state_name = _identifier(item["actor_state"], "Actor domain state")
        members = item["owners"]
        if (
            name in domains
            or type(members) is not list
            or not 1 <= len(members) <= 64
            or any(type(symbol) is not str or symbol not in owner_types for symbol in members)
            or len(members) != len(set(members))
        ):
            raise C0LawError("Actor domain has missing, foreign or repeated owners")
        states = [owner_types[symbol] for symbol in members]
        state_type, identity_field = states[0]
        if (
            state_type.__name__ != state_name
            or identity_field is None
            or any(item != (state_type, identity_field) for item in states)
        ):
            raise C0LawError("Actor domain does not have one nominal state and identity")
        domains[name] = (state_type, identity_field, tuple(members))

    raw_actions = source.get("actions")
    raw_events = source.get("events")
    if type(raw_actions) is not list or type(raw_events) is not list:
        raise C0LawError("Actor binding needs Action and Event declarations")
    actions: list[object] = []
    events: list[object] = []
    generated_actions: list[object] = []
    generated_events: list[object] = []
    existing_actions: list[object] = []
    existing_events: list[object] = []
    families: dict[str, tuple[str, ...]] = {}
    event_families: dict[str, tuple[str, ...]] = {}
    for action_index, raw in enumerate(raw_actions):
        COMPILE_BUDGET.check("actions", len(actions) + 1, stage="Actor expansion")
        if type(raw) is not dict or "domain" not in raw:
            actions.append(raw)
            existing_actions.append(raw)
            if type(raw) is dict and type(raw.get("name")) is str:
                origin("actions", raw["name"], action_index)
            continue
        expected = (
            {"family", "template", "domain", "source_prefix", "law"}
            | ({"participants"} if "participants" in raw else set())
            | ({"target"} if "target" in raw else set())
            | ({"actor_domain_effects"} if "actor_domain_effects" in raw else set())
        )
        item = _row(raw, expected, "Action family")
        if "target" in item and "participants" in item:
            raise C0LawError("Action family cannot mix target and participants")
        family = _identifier(item["family"], "Action family name")
        template = _identifier(item["template"], "Action family template")
        domain = domains.get(item["domain"]) if type(item["domain"]) is str else None
        exemplar = action_templates.get(template)
        if family in families or domain is None or exemplar not in owner_types:
            raise C0LawError("Action family has a foreign domain or template")
        state_type, identity_field, members = domain
        if owner_types[exemplar] != (state_type, identity_field):
            raise C0LawError("Action family template does not match its Actor domain")
        if template in scheduled_templates:
            raise C0LawError("scheduled Action family needs a due binding contract")
        prefix = _prefix(item["source_prefix"], "Action family source prefix")
        families[family] = members
        for actor in members:
            COMPILE_BUDGET.check("actions", len(actions) + 1, stage="Actor expansion")
            source_key = f"{prefix}-{actor}"
            instance = {
                "name": f"{family}_{actor}",
                "template": template,
                "actor": actor,
                "source_key": source_key,
                "event_type": f"{source_key}.action",
                "law": deepcopy(item["law"]),
            }
            if "participants" in item:
                instance["participants"] = deepcopy(item["participants"])
            if "target" in item:
                instance["target"] = deepcopy(item["target"])
            if "actor_domain_effects" in item:
                instance["actor_domain_effects"] = deepcopy(item["actor_domain_effects"])
            actions.append(instance)
            generated_actions.append(instance)
            origin(
                "actions",
                instance["name"],
                action_index,
                arguments=(("family", family), ("actor", actor)),
            )

    action_actors = {
        row["name"]: row.get("actor")
        for row in actions
        if type(row) is dict and type(row.get("name")) is str
    }
    pending_event_families = []
    for event_index, raw in enumerate(raw_events):
        if type(raw) is dict and {"form", "when_false", "effect"} & set(raw):
            raise C0LawError("Source causal Event form/when_false/effect are compiler-owned")
        if type(raw) is dict and ("for_event_family" in raw or "for_event_families" in raw):
            pending_event_families.append((event_index, raw))
            continue
        if type(raw) is not dict or not (
            "for_action_family" in raw or "for_action_families" in raw or "for_actions" in raw
        ):
            events.append(raw)
            existing_events.append(raw)
            if type(raw) is dict and type(raw.get("name")) is str:
                origin("events", raw["name"], event_index)
            continue
        multi = "for_action_families" in raw
        explicit = "for_actions" in raw
        trigger_key = (
            "for_actions" if explicit else "for_action_families" if multi else "for_action_family"
        )
        shared = "share_result" in raw
        item = _row(
            raw,
            {
                "family",
                "template",
                trigger_key,
                "source_prefix",
                "law",
            }
            | ({"actor"} if "actor" in raw else set())
            | ({"actor_domain"} if "actor_domain" in raw else set())
            | ({"share_result"} if shared else set())
            | ({"actor_product"} if "actor_product" in raw else set()),
            "Event family",
        )
        if shared and item["share_result"] is not True:
            raise C0LawError("Event family result sharing must be explicit")
        family = _identifier(item["family"], "Event family name")
        if family in event_families:
            raise C0LawError("Event family names must be distinct")
        trigger_families = item[trigger_key] if multi or explicit else [item[trigger_key]]
        allowed_triggers = action_actors if explicit else families
        if (
            type(trigger_families) is not list
            or not 1 <= len(trigger_families) <= 64
            or any(
                type(name) is not str or name not in allowed_triggers for name in trigger_families
            )
            or len(trigger_families) != len(set(trigger_families))
        ):
            raise C0LawError(
                "Event family needs distinct declared Action triggers or Action family"
            )
        template = item["template"]
        has_recipient = "actor" in item or "actor_domain" in item
        allowed_templates = actor_event_templates if has_recipient else scene_event_templates
        if type(template) is not str or template not in allowed_templates:
            raise C0LawError(
                "Event family needs a matching direct Scene template or Actor recipient"
            )
        prefix = _prefix(item["source_prefix"], "Event family source prefix")
        members_generated = []
        for trigger_family in trigger_families:
            trigger_names = (
                (trigger_family,)
                if explicit
                else tuple(f"{trigger_family}_{actor}" for actor in families[trigger_family])
            )
            for trigger_name in trigger_names:
                actor = action_actors[trigger_name]
                name_suffix = trigger_name if explicit or multi else actor
                trigger_suffix = (
                    trigger_name if explicit else f"{trigger_family}-{actor}" if multi else actor
                )
                recipients, scoped = _event_recipients(
                    item, domains, owner_types, trigger_actor=actor
                )
                for recipient in recipients:
                    COMPILE_BUDGET.check("causal_edges", len(events) + 1, stage="Actor expansion")
                    suffix = f"-{recipient}" if scoped else ""
                    # A correlated edge already identifies its actor in the trigger suffix.
                    edge_suffix = suffix if "actor_domain" in item else ""
                    source_key = (
                        (prefix + suffix) if shared else f"{prefix}-{trigger_suffix}{edge_suffix}"
                    )
                    instance = {
                        "name": f"{family}_{name_suffix}{edge_suffix}",
                        "template": template,
                        "trigger_action": trigger_name,
                        "source_key": source_key,
                        "event_type": f"{source_key}.event",
                        "causal_key": f"{prefix}-{trigger_suffix}{edge_suffix}.causes",
                        "law": deepcopy(item["law"]),
                    }
                    if has_recipient:
                        instance["actor"] = recipient
                    if "actor_product" in item:
                        instance["actor_product"] = deepcopy(item["actor_product"])
                    if shared:
                        instance["shared_result"] = family + suffix
                    events.append(instance)
                    generated_events.append(instance)
                    members_generated.append(instance["name"])
                    origin(
                        "events",
                        instance["name"],
                        event_index,
                        arguments=(
                            ("family", family),
                            ("trigger_action", trigger_name),
                            *(((("actor", actor),)) if type(actor) is str else ()),
                            *(((("recipient", recipient),)) if recipient is not None else ()),
                        ),
                    )
        event_families[family] = tuple(members_generated)

    while pending_event_families:
        progressed = False
        for event_index, raw in tuple(pending_event_families):
            multi = "for_event_families" in raw
            actor_recipient = "actor" in raw
            recipient_domain = "actor_domain" in raw
            shared = "share_result" in raw
            item = _row(
                raw,
                {
                    "family",
                    "template",
                    "for_event_families" if multi else "for_event_family",
                    "source_prefix",
                    "law",
                }
                | ({"actor"} if actor_recipient else set())
                | ({"actor_domain"} if recipient_domain else set())
                | ({"share_result"} if shared else set())
                | ({"actor_product"} if "actor_product" in raw else set()),
                "Event successor family",
            )
            if shared and item["share_result"] is not True:
                raise C0LawError("Event family result sharing must be explicit")
            family = _identifier(item["family"], "Event family name")
            trigger_families = item["for_event_families"] if multi else [item["for_event_family"]]
            if (
                type(trigger_families) is not list
                or not 1 <= len(trigger_families) <= 64
                or any(type(name) is not str for name in trigger_families)
                or len(trigger_families) != len(set(trigger_families))
            ):
                raise C0LawError("Event successor needs distinct Event family triggers")
            if any(name not in event_families for name in trigger_families):
                continue
            if family in event_families:
                raise C0LawError("Event family names must be distinct")
            template = item["template"]
            if actor_recipient and recipient_domain:
                raise C0LawError("Event successor needs one Actor recipient binding")
            allowed_templates = (
                actor_event_templates
                if actor_recipient or recipient_domain
                else scene_event_templates
            )
            if type(template) is not str or template not in allowed_templates:
                raise C0LawError("Event successor needs a matching direct Event template")
            recipients, _ = _event_recipients(item, domains, owner_types)
            prefix = _prefix(item["source_prefix"], "Event family source prefix")
            members_generated = []
            for trigger_family in trigger_families:
                seen_triggers: set[str] = set()
                for trigger_name in event_families[trigger_family]:
                    trigger_source = next(
                        row["source_key"]
                        for row in events
                        if type(row) is dict and row.get("name") == trigger_name
                    )
                    if trigger_source in seen_triggers:
                        continue
                    seen_triggers.add(trigger_source)
                    for bound_recipient in recipients:
                        COMPILE_BUDGET.check(
                            "causal_edges", len(events) + 1, stage="Actor expansion"
                        )
                        suffix = f"-{bound_recipient}" if recipient_domain else ""
                        source_key = (prefix if shared else f"{prefix}-{trigger_name}") + suffix
                        instance = {
                            "name": f"{family}_{trigger_name}{suffix}",
                            "template": template,
                            "trigger_event": trigger_name,
                            "source_key": source_key,
                            "event_type": f"{source_key}.event",
                            "causal_key": (
                                f"{prefix}-{trigger_name}{suffix}.causes"
                                if shared
                                else f"{source_key}.causes"
                            ),
                            "law": deepcopy(item["law"]),
                        }
                        if actor_recipient or recipient_domain:
                            instance["actor"] = bound_recipient
                        if "actor_product" in item:
                            instance["actor_product"] = deepcopy(item["actor_product"])
                        if shared:
                            instance["shared_result"] = family
                        events.append(instance)
                        generated_events.append(instance)
                        members_generated.append(instance["name"])
                        origin(
                            "events",
                            instance["name"],
                            event_index,
                            arguments=(
                                ("family", family),
                                ("trigger_event", trigger_name),
                                *(
                                    ((("recipient", bound_recipient),))
                                    if bound_recipient is not None
                                    else ()
                                ),
                            ),
                        )
            event_families[family] = tuple(members_generated)
            pending_event_families.remove((event_index, raw))
            progressed = True
        if not progressed:
            raise C0LawError("Event successor trigger is foreign or forms a cycle")

    if not actions:
        raise C0LawError("Source needs finite Action instances")
    for resource, actual in (
        ("actions", len(actions)),
        ("causal_edges", len(events)),
        (
            "event_results",
            len({row["source_key"] for row in events if type(row) is dict and "source_key" in row}),
        ),
    ):
        COMPILE_BUDGET.check(resource, actual, stage="Actor expansion")
    due_events = source.get("due_events", [])
    if type(due_events) is not list:
        raise C0LawError("due Event declarations must be finite")
    _unique_generated_values(generated_actions, existing_actions, "name", "Action")
    _unique_generated_values(generated_events, existing_events, "name", "Event")
    generated = generated_actions + generated_events
    existing = existing_actions + existing_events + due_events
    _unique_generated_values(generated_actions, existing, "source_key", "source")
    _unique_generated_values(generated_actions, existing, "event_type", "Event type")
    _unique_result_groups(generated_events, existing + generated_actions)
    _unique_generated_values(
        generated_events, existing_events + due_events, "causal_key", "causal Law"
    )
    seats = source.get("seats")
    if type(seats) is list:
        expanded_seats: list[object] = []
        for seat_index, raw in enumerate(seats):
            if type(raw) is not dict or "seat_family" not in raw:
                expanded_seats.append(raw)
                if type(raw) is dict and type(raw.get("name")) is str:
                    origin("seats", raw["name"], seat_index)
                continue
            has_additional = "additional" in raw
            item = _row(
                raw,
                {"seat_family", "names", "entries", "read", "offers"}
                | ({"additional"} if has_additional else set()),
                "seat family",
            )
            domain_name = _identifier(item["seat_family"], "seat family domain")
            domain = domains.get(domain_name)
            names, entries, reads, offers = (
                item["names"],
                item["entries"],
                item["read"],
                item["offers"],
            )
            if names == "upper" and domain is not None:
                names = {actor: actor.upper() for actor in domain[2]}
            if (
                domain is None
                or type(names) is not dict
                or set(names) != set(domain[2])
                or any(type(value) is not str or not value for value in names.values())
                or len(set(names.values())) != len(names)
                or type(entries) is not list
                or not entries
                or any(type(name) is not str for name in entries)
                or len(entries) != len(set(entries))
                or any(not set(domain[2]).issubset(families.get(name, ())) for name in entries)
                or type(reads) is not list
                or any(type(path) is not str for path in reads)
                or type(offers) is not list
            ):
                raise C0LawError("seat family has an invalid domain, entry or read declaration")
            additional = item.get("additional", {})
            if type(additional) is not dict or any(actor not in domain[2] for actor in additional):
                raise C0LawError("seat family additional entries have a foreign Actor")
            action_owners = {
                action["name"]: action.get("actor")
                for action in actions
                if type(action) is dict and type(action.get("name")) is str
            }
            for actor in domain[2]:
                generated_offers = []
                offer_aliases = []
                for raw_offer in offers:
                    if type(raw_offer) is not dict or "entry" in raw_offer:
                        raise C0LawError("seat family offer needs only its family entry")
                    family = raw_offer.get("entry_family")
                    if type(family) is not str or family not in entries:
                        raise C0LawError("seat family offer needs a bound Action family")
                    # All offer forms use the ordinary frontend's type/permission checks.
                    generated = deepcopy(raw_offer)
                    del generated["entry_family"]
                    generated["entry"] = f"{family}_{actor}"
                    generated_offers.append(generated)
                    offer_aliases.append(
                        (
                            f"offers[{len(generated_offers) - 1}]",
                            ("seats", seat_index, "offers", len(generated_offers) - 1),
                        )
                    )
                extra = additional.get(actor, {"entries": [], "offers": []})
                extra = _row(extra, {"entries", "offers"}, "seat family additional capability")
                extra_entries, extra_offers = extra["entries"], extra["offers"]
                common_entries = {f"{family}_{actor}" for family in entries}
                if (
                    type(extra_entries) is not list
                    or type(extra_offers) is not list
                    or any(type(name) is not str for name in extra_entries)
                    or len(extra_entries) != len(set(extra_entries))
                    or any(name in common_entries for name in extra_entries)
                    or any(action_owners.get(name) != actor for name in extra_entries)
                ):
                    raise C0LawError("seat family additional Action is foreign or repeated")
                for extra_index, raw_offer in enumerate(extra_offers):
                    if type(raw_offer) is not dict or raw_offer.get("entry") not in extra_entries:
                        raise C0LawError("seat family additional offer needs its Actor Action")
                    generated_offers.append(deepcopy(raw_offer))
                    offer_aliases.append(
                        (
                            f"offers[{len(generated_offers) - 1}]",
                            ("seats", seat_index, "additional", actor, "offers", extra_index),
                        )
                    )
                origin(
                    "seats",
                    names[actor],
                    seat_index,
                    arguments=(("family", domain_name), ("actor", actor)),
                    aliases=tuple(offer_aliases),
                )
                expanded_seats.append(
                    {
                        "name": names[actor],
                        "actor": actor,
                        "entries": [f"{family}_{actor}" for family in entries] + extra_entries,
                        "read": [
                            f"{actor}.{path[6:]}" if path.startswith("actor.") else path
                            for path in reads
                        ],
                        "offers": generated_offers,
                    }
                )
        if len(expanded_seats) > 64:
            raise C0LawError("expanded seat family exceeds finite Program limits")
    else:
        expanded_seats = seats
    appraisals = source.get("appraisal_profiles", [])
    if type(appraisals) is not list or len(appraisals) > 128:
        raise C0LawError("appraisal profiles must be finite declarations")
    seat_actors = {
        seat["name"]: seat.get("actor")
        for seat in (expanded_seats if type(expanded_seats) is list else [])
        if type(seat) is dict and type(seat.get("name")) is str
    }
    expanded_appraisals = []
    for index, raw in enumerate(appraisals):
        if type(raw) is not dict or "appraisal_family" not in raw:
            expanded_appraisals.append(raw)
            if type(raw) is dict and type(raw.get("name")) is str:
                origin("appraisal_profiles", raw["name"], index)
            continue
        item = _row(
            raw,
            {"appraisal_family", "profiles", "definition", "entries"},
            "appraisal family",
        )
        domain_name = _identifier(item["appraisal_family"], "appraisal family domain")
        domain = domains.get(domain_name)
        profiles, entries = item["profiles"], item["entries"]
        if (
            domain is None
            or type(profiles) is not dict
            or any(type(seat) is not str for seat in profiles)
            or any(type(name) is not str or not name for name in profiles.values())
            or len(set(profiles.values())) != len(profiles)
            or len(profiles) != len(domain[2])
            or any(type(seat_actors.get(seat)) is not str for seat in profiles)
            or {seat_actors.get(seat) for seat in profiles} != set(domain[2])
            or type(entries) is not dict
            or not entries
            or any(type(slot) is not str or not slot for slot in entries)
            or any(
                type(family) is not str or not set(domain[2]).issubset(families.get(family, ()))
                for family in entries.values()
            )
        ):
            raise C0LawError("appraisal family needs exact seats and bound Action families")
        for seat, name in profiles.items():
            actor = seat_actors[seat]
            expanded_appraisals.append(
                {
                    "name": name,
                    "seat": seat,
                    "definition": deepcopy(item["definition"]),
                    "entries": {slot: f"{family}_{actor}" for slot, family in entries.items()},
                }
            )
            origin(
                "appraisal_profiles",
                name,
                index,
                arguments=(("family", domain_name), ("actor", actor), ("seat", seat)),
            )
        if len(expanded_appraisals) > 128:
            raise C0LawError("expanded appraisal family exceeds finite Program limits")
    result = dict(source)
    result.pop("actor_domains", None)
    if "opening_guard" in result:
        result["opening_guard"] = _bind_domain_sizes(result["opening_guard"], domains)
    opening_actor_guards = result.pop("opening_actor_guards", [])
    if type(opening_actor_guards) is not list or len(opening_actor_guards) > 64:
        raise C0LawError("opening Actor guards must be finite declarations")
    opening_conditions = []
    if origins is not None and "opening_guard" in result:
        base = source_context or C0SourceContext(C0SourceIndex({}))
        origins["opening_guard", ""] = base.at(("opening_guard",), root="guard")
    opening_origins = []
    for guard_index, raw_guard in enumerate(opening_actor_guards):
        guard = _row(raw_guard, {"domain", "when"}, "opening Actor guard")
        domain = domains.get(guard["domain"]) if type(guard["domain"]) is str else None
        if domain is None or type(guard["when"]) is not dict:
            raise C0LawError("opening Actor guard needs a closed domain and condition")
        for actor in domain[2]:
            opening_conditions.append(_bind_actor_refs(guard["when"], actor))
            path = ("opening_actor_guards", guard_index, "when")
            opening_origins.append(
                (
                    path,
                    C0OriginFrame(
                        "actor_instance",
                        actor,
                        repr(path),
                        source_context.index.spans.get(path) if source_context else None,
                        (("domain", guard["domain"]), ("actor", actor)),
                    ),
                )
            )
    if opening_conditions:
        existing_guard = result.get("opening_guard")
        result["opening_guard"] = {
            "all": ([existing_guard] if existing_guard is not None else []) + opening_conditions
        }
        if origins is not None:
            offset = 1 if existing_guard is not None else 0
            aliases = (("guard.all[0]", ("opening_guard",)),) if offset else ()
            aliases += tuple(
                (f"guard.all[{index + offset}]", path)
                for index, (path, _) in enumerate(opening_origins)
            )
            origins["opening_guard", ""] = C0SourceContext(
                source_context.index if source_context else C0SourceIndex({}),
                aliases,
                scoped_frames=tuple(
                    (f"guard.all[{index + offset}]", (frame,))
                    for index, (_, frame) in enumerate(opening_origins)
                ),
            )
    result["actions"] = actions
    result["events"] = events
    if type(seats) is list:
        result["seats"] = expanded_seats
    if "appraisal_profiles" in source:
        result["appraisal_profiles"] = expanded_appraisals
    return result
