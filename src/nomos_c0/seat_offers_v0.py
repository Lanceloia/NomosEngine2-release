"""Finite, seat-readable value offers for an owner-graph GameForm."""

from __future__ import annotations

import json
import keyword
from collections.abc import Mapping
from dataclasses import dataclass, is_dataclass, replace
from types import MappingProxyType
from typing import get_args, get_type_hints

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0SourceContext
from .composable_action_v1 import C0ValueActionPorts
from .composable_value_v1 import (
    C0ValuePorts,
    C0ValueStateError,
    _compile_expression,
    _complete_value_fields,
    _eval,
    _expr_type,
    _guard_proofs,
    _tuple_item,
)
from .expression_ir_v1 import C0Expression
from .private_actor_binding_v1 import C0PrivateActorBinding, check_entry_private_bindings


@dataclass(frozen=True)
class C0FiniteOfferProvider:
    symbol: str
    version: str
    max_candidates: int


@dataclass(frozen=True)
class C0SeatOffer:
    entry: str
    label: str
    payload: tuple[tuple[str, object], ...]
    preview: tuple[tuple[str, object], ...] = ()
    label_fragments: tuple[tuple[str, bool], ...] = ()


@dataclass(frozen=True)
class C0OfferDeclaration:
    entry: str
    label: str
    condition: C0Expression
    payload: Mapping[str, C0Expression]
    ports: C0ValuePorts

    def evaluate(self, scene: object, actor: object) -> C0SeatOffer | None:
        context = {"scene": scene, "actor": actor}
        env = dict(self.ports.roots)
        if _eval(self.condition, context, env, self.ports) is not True:
            return None
        values = tuple(
            (name, _eval(self.payload[name], context, env, self.ports))
            for name in sorted(self.payload)
        )
        return C0SeatOffer(self.entry, self.label, values)

    def evaluate_many(self, scene: object, actor: object) -> tuple[C0SeatOffer, ...]:
        offer = self.evaluate(scene, actor)
        return () if offer is None else (offer,)


@dataclass(frozen=True)
class C0OfferRangeDeclaration:
    entry: str
    label: str
    collection: C0Expression
    item_name: str
    label_value: C0Expression
    condition: C0Expression
    payload: Mapping[str, C0Expression]
    ports: C0ValuePorts
    item_type: object
    max_candidates: int

    def evaluate_many(self, scene: object, actor: object) -> tuple[C0SeatOffer, ...]:
        context = {"scene": scene, "actor": actor}
        roots = dict(self.ports.roots)
        collection = _eval(self.collection, context, roots, self.ports)
        if type(collection) is not tuple or len(collection) > self.max_candidates:
            raise C0ValueStateError("offer collection exceeds its finite bound")
        env = {**roots, self.item_name: self.item_type}
        offers = []
        for item in collection:
            local_context = {**context, self.item_name: item}
            if _eval(self.condition, local_context, env, self.ports) is not True:
                continue
            suffix = _eval(self.label_value, local_context, env, self.ports)
            if type(suffix) is not str:
                raise C0ValueStateError("offer label has a foreign runtime value")
            values = tuple(
                (name, _eval(self.payload[name], local_context, env, self.ports))
                for name in sorted(self.payload)
            )
            offers.append(
                C0SeatOffer(
                    self.entry,
                    self.label + suffix,
                    values,
                    label_fragments=((self.label, False), (suffix, True)),
                )
            )
        return tuple(offers)


@dataclass(frozen=True)
class C0ObjectOfferDeclaration:
    entry: str
    label: str
    kinds: tuple[str, ...]
    object_read_paths: tuple[str, ...]
    visible_when: C0Expression
    condition: C0Expression
    label_value: C0Expression
    payload: Mapping[str, C0Expression]
    ports: C0ValuePorts
    max_candidates: int

    def evaluate_many(
        self,
        scene: object,
        actor: object,
        objects: tuple[tuple[_K0IndividualRef, object], ...],
    ) -> tuple[C0SeatOffer, ...]:
        offers = []
        for individual, target in objects:
            context = {
                "scene": scene,
                "actor": actor,
                "target": target,
                "individual": individual,
            }
            env = dict(self.ports.roots)
            if _eval(self.visible_when, context, env, self.ports) is not True:
                continue
            if _eval(self.condition, context, env, self.ports) is not True:
                continue
            suffix = _eval(self.label_value, context, env, self.ports)
            if type(suffix) is not str:
                raise C0ValueStateError("offer Object label has a foreign value")
            values = tuple(
                (name, _eval(self.payload[name], context, env, self.ports))
                for name in sorted(self.payload)
            )
            offers.append(
                C0SeatOffer(
                    self.entry,
                    self.label + suffix,
                    values,
                    label_fragments=((self.label, False), (suffix, True)),
                )
            )
            if len(offers) > self.max_candidates:
                raise C0ValueStateError("visible Object offers exceed their finite bound")
        return tuple(offers)


@dataclass(frozen=True)
class C0ActorOfferRange:
    name: str
    alias: str
    identity_field: str
    collection: C0Expression
    domain: tuple[str, ...]
    family: str | None = None

    def __post_init__(self):
        if (
            any(
                type(name) is not str or not name.isidentifier() or keyword.iskeyword(name)
                for name in (self.name, self.alias, self.identity_field)
            )
            or type(self.domain) is not tuple
            or (self.family is None and not self.domain)
            or (
                self.family is not None
                and (type(self.family) is not str or not self.family or self.domain)
            )
            or any(type(name) is not str for name in self.domain)
            or len(set(self.domain)) != len(self.domain)
            or type(self.collection) is not C0Expression
        ):
            raise C0LawError("participant Actor range is malformed")


@dataclass(frozen=True)
class C0LocalValueOfferRange:
    alias: str
    collection: C0Expression


def _local_value_read_paths(alias, annotation, active=frozenset()):
    """Expose only the item of an already-authorized local aggregate."""
    paths = {alias}
    if is_dataclass(annotation) and annotation not in active:
        for name, carrier in get_type_hints(annotation).items():
            variants = get_args(carrier)
            if len(variants) == 2 and type(None) in variants:
                carrier = next(value for value in variants if value is not type(None))
            paths.update(
                _local_value_read_paths(alias + "." + name, carrier, active | {annotation})
            )
    return paths


@dataclass(frozen=True)
class C0ObjectOfferRange:
    name: str
    payload_field: str
    kinds: tuple[str, ...]
    read_paths: tuple[str, ...]
    singleton: bool


@dataclass(frozen=True)
class C0ParticipantOfferDeclaration:
    entry: str
    objects: tuple[C0ObjectOfferRange, ...]
    actor_range: C0ActorOfferRange | None
    labels: tuple[C0Expression, ...]
    visible_when: C0Expression
    condition: C0Expression
    payload: Mapping[str, C0Expression]
    ports: C0ValuePorts
    max_candidates: int
    local_range: C0LocalValueOfferRange | None = None
    private_actor_fields: tuple[C0PrivateActorBinding, ...] = ()

    @property
    def all_object_kinds(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(family for role in self.objects for family in role.kinds))

    @property
    def label(self) -> str:
        return "".join(
            expression.operand for expression in self.labels if expression.operation == "const"
        )

    @property
    def max_combinations(self) -> int:
        return self.max_candidates * self.max_candidates

    def evaluate_many(
        self,
        scene: object,
        actor: object,
        objects: tuple[tuple[_K0IndividualRef, object], ...],
    ) -> tuple[C0SeatOffer, ...]:
        from itertools import product
        from math import prod

        roots = dict(self.ports.roots)
        actor_range = self.actor_range
        collection = (
            (None,)
            if actor_range is None
            else _eval(actor_range.collection, {"scene": scene, "actor": actor}, roots, self.ports)
        )
        if type(collection) is not tuple or len(collection) > self.max_candidates:
            raise C0ValueStateError("participant offer Actor collection exceeds its bound")
        local_values = (
            (None,)
            if self.local_range is None
            else _eval(
                self.local_range.collection, {"scene": scene, "actor": actor}, roots, self.ports
            )
        )
        if type(local_values) is not tuple or len(local_values) > self.max_candidates:
            raise C0ValueStateError("participant offer local collection exceeds its bound")
        domains = []
        for role in self.objects:
            selected = tuple(item for item in objects if item[0].family in role.kinds)
            if role.singleton and len(selected) > 1:
                raise C0ValueStateError("fixed participant Object is not a singleton")
            if not selected:
                return ()
            domains.append(selected)
        # Bound work before visibility filtering; output bounds alone do not bound products.
        if prod(map(len, domains)) * len(collection) * len(local_values) > self.max_combinations:
            raise C0ValueStateError("participant candidate combinations exceed their finite bound")
        offers = []
        for selections in product(*domains):
            object_context = {}
            for role, (individual, current) in zip(self.objects, selections, strict=True):
                object_context.update({role.name: current, role.name + "_ref": individual})
            for candidate, local_value in product(collection, local_values):
                candidate_context = {}
                if actor_range is not None:
                    person = getattr(candidate, actor_range.identity_field, None)
                    expected_type = str if actor_range.family is None else _K0ActorRef
                    if type(person) is not expected_type:
                        raise C0ValueStateError("participant offer Actor identity is malformed")
                    if (
                        person not in actor_range.domain
                        if actor_range.family is None
                        else person.family != actor_range.family
                    ):
                        continue
                    candidate_context[actor_range.alias] = candidate
                if self.local_range is not None:
                    candidate_context[self.local_range.alias] = local_value
                context = {
                    "scene": scene,
                    "actor": actor,
                    **object_context,
                    **candidate_context,
                }
                if _eval(self.visible_when, context, roots, self.ports) is not True:
                    continue
                if _eval(self.condition, context, roots, self.ports) is not True:
                    continue
                fragments = tuple(
                    (_eval(expression, context, roots, self.ports), expression.operation != "const")
                    for expression in self.labels
                )
                if any(type(text) is not str for text, _ in fragments):
                    raise C0ValueStateError("participant offer labels are malformed")
                values = tuple(
                    (name, _eval(self.payload[name], context, roots, self.ports))
                    for name in sorted(self.payload)
                )
                offers.append(
                    C0SeatOffer(
                        self.entry,
                        "".join(text for text, _ in fragments),
                        values,
                        label_fragments=fragments,
                    )
                )
                if len(offers) > self.max_candidates:
                    raise C0ValueStateError("participant offers exceed their finite bound")
        return tuple(offers)


@dataclass(frozen=True)
class C0FixedParticipantOfferDeclaration:
    entry: str
    label: str
    object_fields: tuple[tuple[str, str], ...]
    actor_fields: tuple[tuple[str, str], ...]
    condition: C0Expression
    payload: Mapping[str, C0Expression]
    ports: C0ValuePorts

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(family for _, family in self.object_fields)

    def evaluate_many(
        self,
        scene: object,
        actor: object,
        objects: tuple[tuple[_K0IndividualRef, object], ...],
    ) -> tuple[C0SeatOffer, ...]:
        by_family = {individual.family: individual for individual, _ in objects}
        if len(by_family) != len(objects) or set(by_family) != set(self.kinds):
            return ()
        if (
            _eval(self.condition, {"scene": scene, "actor": actor}, self.ports.roots, self.ports)
            is not True
        ):
            return ()
        values = tuple(
            (
                name,
                _eval(
                    self.payload[name],
                    {"scene": scene, "actor": actor},
                    self.ports.roots,
                    self.ports,
                ),
            )
            for name in sorted(self.payload)
        )
        return (C0SeatOffer(self.entry, self.label, values),)

    def resolve_payload(self, individuals: tuple[_K0IndividualRef, ...]) -> dict[str, object]:
        by_family = {individual.family: individual for individual in individuals}
        if len(by_family) != len(individuals) or set(by_family) != set(self.kinds):
            raise C0ValueStateError("fixed participant Object families changed")
        return {
            **{field: by_family[family] for field, family in self.object_fields},
            **dict(self.actor_fields),
        }


def _offer_count_upper_bound(declaration, scene, actor, family_counts):
    """Bound successful output counts without reading other Object owners."""
    if type(declaration) in (C0OfferDeclaration, C0FixedParticipantOfferDeclaration):
        return 1
    if type(declaration) is C0ObjectOfferDeclaration:
        return min(
            sum(family_counts.get(kind, 0) for kind in declaration.kinds),
            declaration.max_candidates,
        )
    context = {"scene": scene, "actor": actor}
    if type(declaration) is C0OfferRangeDeclaration:
        collection = _eval(
            declaration.collection, context, declaration.ports.roots, declaration.ports
        )
        return (
            min(len(collection), declaration.max_candidates) if type(collection) is tuple else None
        )
    if type(declaration) is not C0ParticipantOfferDeclaration:
        return None
    count = 1
    for role in declaration.objects:
        count *= sum(family_counts.get(kind, 0) for kind in role.kinds)
    for collection in (
        None if declaration.actor_range is None else declaration.actor_range.collection,
        None if declaration.local_range is None else declaration.local_range.collection,
    ):
        if collection is not None:
            values = _eval(collection, context, declaration.ports.roots, declaration.ports)
            if type(values) is not tuple:
                return None
            count *= len(values)
    return min(count, declaration.max_candidates)


def _public_ports(
    action: C0ValueActionPorts,
    read_paths: tuple[str, ...],
    scene_symbol: str,
    actor_symbol: str,
) -> C0ValuePorts:
    value = action.value_ports
    scene_paths = {
        "scene." + path.split(".", 1)[1]
        for path in read_paths
        if path.startswith(scene_symbol + ".")
    }
    actor_paths = {
        "actor." + path.split(".", 1)[1]
        for path in read_paths
        if path.startswith(actor_symbol + ".")
    }
    field_ports: dict[type, set[str]] = {}
    resolved: dict[type, dict[str, object]] = {}
    for path in scene_paths | actor_paths:
        root, *parts = path.split(".")
        carrier = action.scene_owner.view_type if root == "scene" else action.actor_owner.view_type
        for part in parts:
            field_ports.setdefault(carrier, set()).add(part)
            # Reuse type metadata only inside this port construction.
            if carrier not in resolved:
                resolved[carrier] = get_type_hints(carrier)
            annotation = resolved[carrier][part]
            variants = get_args(annotation)
            carrier = (
                next(value for value in variants if value is not type(None))
                if len(variants) == 2 and type(None) in variants
                else annotation
            )
        for record, names in _complete_value_fields(carrier).items():
            field_ports.setdefault(record, set()).update(names)
    return replace(
        value,
        roots={"scene": action.scene_owner.view_type, "actor": action.actor_owner.view_type},
        readable_paths=frozenset(scene_paths | actor_paths),
        admission_readable_paths=frozenset(scene_paths | actor_paths),
        readable_fields={key: frozenset(value) for key, value in field_ports.items()},
        admission_readable_fields={key: frozenset(value) for key, value in field_ports.items()},
    )


def compile_seat_offers(
    raw: object,
    entries: tuple[str, ...],
    read_paths: tuple[str, ...],
    actions: dict[str, C0ValueActionPorts],
    scene_symbols: dict[str, str],
    actor_symbol: str,
    provider: C0FiniteOfferProvider,
    *,
    source_context: C0SourceContext | None = None,
    pure_definitions: tuple | None = None,
) -> tuple[
    C0OfferDeclaration
    | C0OfferRangeDeclaration
    | C0ObjectOfferDeclaration
    | C0ParticipantOfferDeclaration
    | C0FixedParticipantOfferDeclaration,
    ...,
]:
    if type(raw) is not list or not raw or len(raw) > provider.max_candidates:
        raise C0LawError("seat needs a bounded nonempty offer domain")
    compiled = []
    declarations = set()
    fixed_entries = set()
    for index, item in enumerate(raw):
        ranged = type(item) is dict and "for_each" in item
        object_ranged = type(item) is dict and "for_each_object" in item
        participant_ranged = type(item) is dict and "for_each_participants" in item
        fixed = type(item) is dict and "fixed_participants" in item
        expected = (
            {"entry", "fixed_participants", "label", "when", "payload"}
            if fixed
            else {"entry", "for_each_participants", "label", "visible_when", "when", "payload"}
            if participant_ranged
            else {"entry", "for_each_object", "label", "visible_when", "when", "payload"}
            if object_ranged
            else {"entry", "for_each", "label", "when", "payload"}
            if ranged
            else {"entry", "label", "when", "payload"}
        )
        if participant_ranged and ranged:
            expected.add("for_each")
        if type(item) is not dict or set(item) != expected:
            raise C0LawError("offer declaration has missing or unknown fields")
        entry, label, condition, payload = (
            item["entry"],
            item["label"],
            item["when"],
            item["payload"],
        )
        if type(entry) is not str or entry not in entries:
            raise C0LawError("offer entry or label is not declared")
        try:
            identity = json.dumps(item, sort_keys=True)
        except (TypeError, ValueError, RecursionError) as error:
            raise C0LawError("offer declaration is not JSON data") from error
        if identity in declarations:
            raise C0LawError("offer declaration is repeated")
        declarations.add(identity)
        action = actions[entry]
        ports = _public_ports(action, read_paths, scene_symbols[entry], actor_symbol)
        ports = replace(
            ports,
            source_context=source_context,
            pure_definitions=pure_definitions
            if pure_definitions is not None
            else ports.pure_definitions,
        )
        env = dict(ports.roots)
        payload_proofs: set[str] = set()

        def checked_expression(
            value: object, path: str, proofs: set[str] | None = None
        ) -> C0Expression:
            return _compile_expression(
                value,
                env,
                ports,
                set() if proofs is None else proofs,
                origin=f"offers[{index}].{path}",
            )

        def payload_expressions() -> Mapping[str, C0Expression]:
            return MappingProxyType(
                {
                    name: checked_expression(value, f"payload.{name}", payload_proofs)
                    for name, value in payload.items()
                }
            )

        if fixed:
            selections = action.participants
            individual_ports = tuple(p for p in selections if p.selector == "individual")
            closed_ports = tuple(p for p in selections if p.selector == "closed_domain")
            if (
                item["fixed_participants"] is not True
                or not selections
                or len(selections) != len(individual_ports) + len(closed_ports)
                or type(label) is not str
                or not label
                or type(payload) is not dict
                or entry in fixed_entries
                or any(existing.entry == entry for existing in compiled)
            ):
                raise C0LawError("fixed participant offer needs nonempty singleton participants")
            if (
                any(
                    obj.kind is None or len(obj.kinds) != 1 or obj.kind.max_instances != 1
                    for obj in individual_ports
                )
                or len({obj.kind.family for obj in individual_ports}) != len(individual_ports)
                or any(len(person.members) != 1 for person in closed_ports)
                or len({person.members[0][0] for person in closed_ports}) != len(closed_ports)
                or _expr_type(condition, env, ports, set()) is not bool
            ):
                raise C0LawError("fixed participant offer ports or condition are incompatible")
            hints = get_type_hints(action.payload_type)
            selected_fields = {action.payload_actor_field, *(p.payload_field for p in selections)}
            if set(payload) != set(hints) - selected_fields:
                raise C0LawError("fixed participant payload must fill only non-selector fields")
            payload_proofs = _guard_proofs(condition, env, ports)
            for name, expression in payload.items():
                if (
                    hints[name] not in (str, int, bool, K0OccurrenceRef)
                    or _expr_type(expression, env, ports, payload_proofs) is not hints[name]
                ):
                    raise C0LawError("fixed participant payload has the wrong public type")
            fixed_entries.add(entry)
            compiled.append(
                C0FixedParticipantOfferDeclaration(
                    entry,
                    label,
                    tuple((obj.payload_field, obj.kind.family) for obj in individual_ports),
                    tuple((person.payload_field, person.members[0][0]) for person in closed_ports),
                    checked_expression(condition, "when"),
                    payload_expressions(),
                    ports,
                )
            )
            continue
        if entry in fixed_entries:
            raise C0LawError("fixed participant offer cannot share an Action entry")
        if participant_ranged:
            from .participant_candidates_v1 import compile_participant_offer

            compiled.append(compile_participant_offer(item, action, ports, provider, index))
            continue
        if object_ranged:
            target = action.target
            binding = item["for_each_object"]
            if (
                target is None
                or target.kind is None
                or type(binding) is not dict
                or set(binding) != {"kind", "read"}
                or binding["kind"] != target.kind.family
                or type(binding["read"]) is not list
                or len(binding["read"]) != len(set(map(str, binding["read"])))
                or any(
                    type(path) is not str
                    or not path.startswith("target.")
                    or path not in action.value_ports.readable_paths
                    for path in binding["read"]
                )
            ):
                raise C0LawError("offer Object domain is not a selected readable kind")
            object_paths = set(binding["read"])
            field_ports = {carrier: set(names) for carrier, names in ports.readable_fields.items()}
            for path in object_paths:
                carrier = target.state_type
                for part in path.split(".")[1:]:
                    field_ports.setdefault(carrier, set()).add(part)
                    annotation = get_type_hints(carrier).get(part)
                    if annotation is None:
                        raise C0LawError("offer Object read path has a foreign field")
                    variants = get_args(annotation)
                    carrier = (
                        next(value for value in variants if value is not type(None))
                        if len(variants) == 2 and type(None) in variants
                        else annotation
                    )
            ports = replace(
                ports,
                roots={**ports.roots, "target": target.state_type, "individual": _K0IndividualRef},
                readable_paths=ports.readable_paths | object_paths | {"individual"},
                admission_readable_paths=ports.admission_readable_paths
                | object_paths
                | {"individual"},
                readable_fields={key: frozenset(names) for key, names in field_ports.items()},
                admission_readable_fields={
                    key: frozenset(names) for key, names in field_ports.items()
                },
            )
            env = dict(ports.roots)
            if (
                type(label) is not dict
                or set(label) != {"prefix", "value"}
                or type(label["prefix"]) is not str
                or not label["prefix"]
                or _expr_type(item["visible_when"], env, ports, set()) is not bool
                or _expr_type(label["value"], env, ports, set()) is not str
            ):
                raise C0LawError("offer Object visibility or label is malformed")
            if _expr_type(condition, env, ports, set()) is not bool:
                raise C0LawError("offer Object condition must be boolean")
            hints = get_type_hints(action.payload_type)
            if type(payload) is not dict or set(payload) != set(hints) - {
                action.payload_actor_field
            }:
                raise C0LawError("offer Object payload misses a declared field")
            payload_proofs = _guard_proofs(item["visible_when"], env, ports)
            payload_proofs.update(_guard_proofs(condition, env, ports, payload_proofs))
            for name, expression in payload.items():
                if (
                    hints[name] not in (str, int, bool, _K0IndividualRef, K0OccurrenceRef)
                    or _expr_type(expression, env, ports, payload_proofs) is not hints[name]
                ):
                    raise C0LawError("offer Object payload has a foreign public type")
            if payload[target.payload_field] != {"ref": "individual"}:
                raise C0LawError("offer Object target must use the resolved individual ref")
            compiled.append(
                C0ObjectOfferDeclaration(
                    entry,
                    label["prefix"],
                    tuple(kind.family for kind in target.kinds),
                    tuple(sorted(object_paths)),
                    checked_expression(item["visible_when"], "visible_when"),
                    checked_expression(condition, "when"),
                    checked_expression(label["value"], "label.value"),
                    payload_expressions(),
                    ports,
                    provider.max_candidates,
                )
            )
            continue
        if ranged:
            binding = item["for_each"]
            if type(binding) is not dict or set(binding) != {"collection", "as"}:
                raise C0LawError("offer range needs a collection and item alias")
            collection, item_name = binding["collection"], binding["as"]
            if (
                type(collection) is not dict
                or set(collection) != {"ref"}
                or type(item_name) is not str
                or not item_name.isidentifier()
                or keyword.iskeyword(item_name)
                or item_name in env
            ):
                raise C0LawError("offer range collection or item alias is malformed")
            item_type = _tuple_item(_expr_type(collection, env, ports, set()))
            env[item_name] = item_type
            if (
                type(label) is not dict
                or set(label) != {"prefix", "value"}
                or type(label["prefix"]) is not str
                or not label["prefix"]
                or _expr_type(label["value"], env, ports, set()) is not str
            ):
                raise C0LawError("offer range label needs a string prefix and value")
        elif type(label) is not str or not label:
            raise C0LawError("offer entry or label is not declared")
        if _expr_type(condition, env, ports, set()) is not bool:
            raise C0LawError("offer condition must be public and boolean")
        hints = get_type_hints(action.payload_type)
        if type(payload) is not dict or set(payload) != set(hints) - {action.payload_actor_field}:
            raise C0LawError("offer payload misses a declared non-Actor field")
        payload_proofs = _guard_proofs(condition, env, ports)
        for name, expression in payload.items():
            if (
                hints[name] not in (str, int, bool, K0OccurrenceRef)
                or _expr_type(expression, env, ports, payload_proofs) is not hints[name]
            ):
                raise C0LawError("offer payload field has the wrong public type")

        if ranged:
            compiled.append(
                C0OfferRangeDeclaration(
                    entry,
                    label["prefix"],
                    checked_expression(collection, "for_each.collection"),
                    item_name,
                    checked_expression(label["value"], "label.value"),
                    checked_expression(condition, "when"),
                    payload_expressions(),
                    ports,
                    item_type,
                    provider.max_candidates,
                )
            )
        else:
            compiled.append(
                C0OfferDeclaration(
                    entry,
                    label,
                    checked_expression(condition, "when"),
                    payload_expressions(),
                    ports,
                )
            )
    check_entry_private_bindings(compiled)
    return tuple(
        replace(
            item,
            ports=replace(
                item.ports,
                source_context=None,
                pure_definitions=tuple(
                    replace(definition, source_context=None)
                    for definition in item.ports.pure_definitions
                ),
            ),
        )
        for item in compiled
    )
