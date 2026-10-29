"""Nominal entity fields and current selected reads, separate from value identity."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier
from .opening import ParameterValue, value_node
from .value_types import TypeTable

if TYPE_CHECKING:
    from .expressions import ValueRead


@dataclass(frozen=True)
class OwnerRead:
    sort: str
    field: str
    selector: ValueRead | None
    relation: str = ""


@dataclass(frozen=True)
class EntitySchema:
    name: str
    kind: str
    fields: tuple
    view: tuple[str, ...]
    public: tuple[str, ...]
    carrying: tuple = ()
    reference: str = "public"
    initial: tuple = ()


@dataclass(frozen=True)
class EntityInitial(ParameterValue):
    owner: str


@dataclass(frozen=True)
class CarryingRead:
    name: str
    item: str
    person: str
    holder: str
    ground: str
    position: str

    @property
    def offer_field(self):
        return "_offer_" + self.name


@dataclass(frozen=True)
class EntityReadLibrary:
    table: TypeTable
    entities: tuple[tuple[str, EntitySchema], ...]
    relations: tuple[tuple[str, CarryingRead], ...]
    fingerprint: str

    def field(self, sort, name):
        schema = dict(self.entities).get(sort)
        if schema is None or name not in dict(schema.fields):
            raise C0LawError(f"unknown entity field {sort}.{name}")
        return dict(schema.fields)[name]

    def permitted(self, request, *, context, actor):
        if context == "world":
            return True
        schema = dict(self.entities)[request.sort]
        if request.relation:
            relation = dict(self.relations)[request.relation]
            person = dict(self.entities)[relation.person]
            return (
                relation.holder in schema.view
                and relation.ground in schema.view
                and relation.position in person.public
            )
        own = (
            request.selector is not None
            and request.selector.root == actor
            and not request.selector.steps
        )
        return request.field in (schema.view if own or schema.kind == "object" else schema.public)


def projection_can_grant_references(kind, schemas):
    """Only projected identities can enlarge an already public/self reference domain."""
    if kind.kind == "ref":
        return schemas[kind.sort].reference == "projected"
    if kind.kind in ("set", "sequence", "optional"):
        return projection_can_grant_references(kind.element, schemas)
    children = (
        kind.fields if kind.kind == "record" else kind.cases if kind.kind == "variant" else ()
    )
    return any(projection_can_grant_references(child, schemas) for _, child in children)


def compile_entity_reads(table, entities, relations=None):
    if type(table) is not TypeTable or not isinstance(entities, Mapping):
        raise C0LawError("entity reads need a common type table and entity declarations")
    sorts = {sort.name: sort for sort in table.sorts}
    if set(entities) != set(sorts):
        raise C0LawError("entity fields differ from the selected sort table")
    built = {}

    def build(name):
        if name in built:
            return built[name]
        sort, row = sorts[name], entities[name]
        if not isinstance(row, Mapping) or not {"kind", "reference", "fields", "view"} <= set(row):
            raise C0LawError("entity requires kind/reference/fields/view")
        if set(row) - {"kind", "reference", "fields", "view", "public", "extends", "initial"}:
            raise C0LawError("unsupported entity read declaration")
        parents = () if "extends" not in row else (row["extends"],)
        if row["kind"] != sort.kind or parents != sort.parents:
            raise C0LawError("entity fields contradict the nominal sort graph")
        if row["reference"] not in ("public", "projected"):
            raise C0LawError("entity reference policy must be public or projected")
        fields, inherited_view, inherited_public, initial = {}, set(), set(), {}
        for parent in sort.parents:
            base = build(parent)
            if base.reference == "public" and row["reference"] != "public":
                raise C0LawError("entity specialization narrows an inherited reference policy")
            fields.update(base.fields)
            inherited_view.update(base.view)
            inherited_public.update(base.public)
            initial.update((p.name, p) for p in base.initial)
        if not isinstance(row["fields"], Mapping):
            raise C0LawError("entity fields require named value types")
        for field, declared in row["fields"].items():
            if (
                not _identifier(field)
                or field == "id"
                or type(declared) is not str
                or declared not in dict(table.definitions)
            ):
                raise C0LawError("entity field name or named value type is invalid")
            plan = table[declared]
            if field in fields and fields[field].type_id != plan.type_id:
                raise C0LawError("entity specialization changes an inherited field type")
            fields[field] = plan

        def permission(label):
            value = row.get(label, [])
            if type(value) is not list or any(type(item) is not str for item in value):
                raise C0LawError("entity visibility must be a field list")
            if len(value) != len(set(value)) or set(value) - {"id", *fields}:
                raise C0LawError("entity visibility has duplicate or unknown fields")
            return tuple(sorted(set(value) - {"id"}))

        view, public = permission("view"), permission("public")
        if not inherited_view <= set(view) or not inherited_public <= set(public):
            raise C0LawError("entity specialization narrows an inherited read contract")
        if set(public) - set(view) or sort.kind != "person" and public:
            raise C0LawError("entity public fields must belong to the Person view")
        declared_initial = row.get("initial", {})
        if not isinstance(declared_initial, Mapping) or set(declared_initial) - set(fields):
            raise C0LawError(f"entities.{name}.initial requires declared field names")
        for field, value in declared_initial.items():
            kind = fields[field]
            try:
                node = value_node(table, kind, value, ())
            except ValueError as error:
                raise C0LawError(f"entities.{name}.initial.{field}: {error}") from error
            initial[field] = EntityInitial(field, kind.name, node, name)
        fields = tuple(sorted(fields.items()))

        built[name] = EntitySchema(
            name,
            sort.kind,
            fields,
            view,
            public,
            reference=row["reference"],
            initial=tuple(initial[field] for field in sorted(initial)),
        )
        return built[name]

    for name in sorts:
        build(name)
    relations = {} if relations is None else relations
    if not isinstance(relations, Mapping):
        raise C0LawError("relations require named definitions")
    resolved = []
    for name, row in relations.items():
        if not _identifier(name) or name in sorts or name in dict(table.definitions):
            raise C0LawError("relation name conflicts with a declared type")
        if (
            not isinstance(row, Mapping)
            or set(row) != {"kind", "item", "person", "holder", "ground", "position"}
            or row["kind"] != "carrying"
            or any(
                not _identifier(row[key])
                for key in ("item", "person", "holder", "ground", "position")
            )
        ):
            raise C0LawError("UnsupportedFeature: expected a carrying read definition")
        item, person = built.get(row["item"]), built.get(row["person"])
        if item is None or person is None or item.kind != "object" or person.kind != "person":
            raise C0LawError("carrying requires Object and Person sorts")
        a, b = dict(item.fields), dict(person.fields)
        holder, ground, position = (
            a.get(row["holder"]),
            a.get(row["ground"]),
            b.get(row["position"]),
        )
        if (
            holder is None
            or holder.kind != "optional"
            or holder.element.kind != "ref"
            or holder.element.sort != person.name
        ):
            raise C0LawError("carrying holder requires Optional<PersonRef>")
        if ground is None or position is None or ground.type_id != position.type_id:
            raise C0LawError("carrying ground and position require the same named value type")
        resolved.append(
            (
                name,
                CarryingRead(
                    name, item.name, person.name, row["holder"], row["ground"], row["position"]
                ),
            )
        )
    for name, schema in tuple(built.items()):
        carrying = tuple(
            relation for _, relation in resolved if table.accepts_sort(relation.item, name)
        )
        built[name] = replace(schema, carrying=carrying)
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                "author-state-wire.with-finite-analysis",
                [(name, plan.type_id.signature) for name, plan in table.definitions],
                [
                    (
                        name,
                        schema.kind,
                        [(field, plan.type_id.signature) for field, plan in schema.fields],
                        schema.view,
                        schema.public,
                        schema.reference,
                        [(p.name, p.type_name, repr(p.node), p.owner) for p in schema.initial],
                    )
                    for name, schema in sorted(built.items())
                ],
                [(name, vars(relation)) for name, relation in resolved],
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return EntityReadLibrary(table, tuple(sorted(built.items())), tuple(resolved), fingerprint)
