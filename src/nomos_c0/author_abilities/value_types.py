"""Named value declarations, separate from assets, entity owners and execution."""

from __future__ import annotations

import hashlib
import json
import keyword
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import reduce
from operator import or_

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import C0SourceContext, C0SourceSpan
from nomos_c0.generated_record_v1 import make_nominal_record, seal_nominal_record

from .literal_values import SymbolLiteral


@dataclass(frozen=True)
class TypeId:
    name: str
    signature: str


@dataclass(frozen=True)
class TypeDiagnostic:
    code: str
    definition: str
    path: str
    span: C0SourceSpan | None
    expected: str
    actual: str
    stage: str = "Compile"


class ValueTypeError(C0LawError):
    def __init__(self, diagnostic: TypeDiagnostic):
        self.diagnostic = diagnostic
        location = diagnostic.path
        if diagnostic.span is not None:
            location += f" ({diagnostic.span.file}:{diagnostic.span.line}:{diagnostic.span.column})"
        super().__init__(
            f"{diagnostic.code}: {location}: {diagnostic.expected}; {diagnostic.actual}"
        )


@dataclass(frozen=True)
class EntitySort:
    name: str
    kind: str
    parents: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValueType:
    name: str
    kind: str
    type_id: TypeId
    annotation: object
    minimum: int = 0
    maximum: int = 0
    choices: tuple[str, ...] = ()
    element: ValueType | None = None
    fields: tuple[tuple[str, ValueType], ...] = ()
    cases: tuple[tuple[str, ValueType], ...] = ()
    sort: str | None = None
    origin: str = ""
    span: C0SourceSpan | None = None
    has_references: bool = field(init=False)
    _field_names: frozenset[str] = field(init=False, repr=False, compare=False)

    def __repr__(self):
        # Shared type graphs must not expand as trees while formatting diagnostics.
        return f"ValueType(name={self.name!r}, kind={self.kind!r}, type_id={self.type_id!r})"

    def __post_init__(self):
        object.__setattr__(
            self,
            "_field_names",
            frozenset(name for name, _ in self.fields),
        )
        children = (
            (self.element,)
            if self.element is not None
            else tuple(child for _, child in (*self.fields, *self.cases))
        )
        object.__setattr__(
            self,
            "has_references",
            self.kind == "ref" or any(child.has_references for child in children),
        )

    def storage_field(self, name):
        if name not in self._field_names:
            raise KeyError(name)
        return "_value_" + name


@dataclass(frozen=True)
class TypeLimits:
    declarations: int = 4096
    depth: int = 64
    nodes: int = 32768

    def __post_init__(self):
        if any(
            type(value) is not int or value < 1
            for value in (self.declarations, self.depth, self.nodes)
        ):
            raise C0LawError("type compilation limits must be positive integers")


@dataclass(frozen=True)
class TypeTable:
    definitions: tuple[tuple[str, ValueType], ...]
    sorts: tuple[EntitySort, ...]

    def __getitem__(self, name: str) -> ValueType:
        for symbol, definition in self.definitions:
            if symbol == name:
                return definition
        if type(name) is str and "." in name:
            parent, tag = name.split(".", 1)
            plan = dict(self.definitions).get(parent)
            if plan is not None and plan.kind == "variant" and tag in dict(plan.cases):
                return dict(plan.cases)[tag]
        if name == "Integer<>":
            return ValueType(
                name, "int", _type_id(name, "int", {}, "inferred"), int, minimum=None, maximum=None
            )
        if type(name) is str and name.endswith(">"):
            for prefix, kind in (("Set<", "set"), ("Sequence<", "sequence")):
                if name.startswith(prefix):
                    return self.collection(name[len(prefix) : -1], kind=kind)
            if name.startswith("Optional<"):
                return self.optional(name[9:-1])
            if name.startswith("Ref<"):
                return self.reference(name[4:-1])
        raise KeyError(name)

    def reference(self, sort):
        selected = next((item for item in self.sorts if item.name == sort), None)
        if selected is None:
            raise KeyError(sort)
        declared = next(
            (plan for _, plan in self.definitions if plan.kind == "ref" and plan.sort == sort), None
        )
        if declared is not None:
            return declared
        name = f"Ref<{sort}>"
        identity = _type_id(
            name,
            "ref",
            {"sort": sort, "kind": selected.kind, "parents": selected.parents},
            "inferred",
        )
        return ValueType(
            name,
            "ref",
            identity,
            SymbolLiteral,
            sort=sort,
        )

    def collection(self, element, *, kind="set"):
        if kind not in ("set", "sequence"):
            raise KeyError(kind)
        plan = self[element]
        name = f"{'Set' if kind == 'set' else 'Sequence'}<{plan.name}>"
        identity = _type_id(name, kind, {"element": plan.type_id.signature}, "inferred")
        annotation = frozenset[plan.annotation] if kind == "set" else tuple[plan.annotation, ...]
        return ValueType(name, kind, identity, annotation, element=plan)

    def optional(self, element):
        plan = self[element]
        name = f"Optional<{plan.name}>"
        identity = _type_id(name, "optional", {"element": plan.type_id.signature}, "inferred")
        return ValueType(name, "optional", identity, plan.annotation | type(None), element=plan)

    def expression_type(self, plan):
        declared = self.by_id(plan.type_id)
        if declared is not None:
            return declared
        if plan.kind == "int":
            return self["Integer<>"]
        if plan.kind == "ref":
            return self.reference(plan.sort)
        if plan.kind in ("set", "sequence"):
            return self.collection(self.expression_type(plan.element).name, kind=plan.kind)
        if plan.kind == "optional":
            return self.optional(self.expression_type(plan.element).name)
        raise C0LawError("expression requires a named result type")

    def accepts_sort(self, expected: str, actual: str) -> bool:
        by_name = {sort.name: sort for sort in self.sorts}
        if expected not in by_name or actual not in by_name:
            return False
        pending = [actual]
        seen = set()
        while pending:
            name = pending.pop()
            if name == expected:
                return True
            if name not in seen:
                seen.add(name)
                pending.extend(by_name[name].parents)
        return False

    def by_id(self, identity):
        plans = [plan for _, plan in self.definitions]
        for plan in tuple(plans):
            if plan.kind == "variant":
                plans.extend(child for _, child in plan.cases)
        found = next((plan for plan in plans if plan.type_id == identity), None)
        if found is not None or type(identity) is not TypeId:
            return found
        # Ref identity names its declared sort even without an authored value alias.
        if any(sort.name == identity.name for sort in self.sorts):
            reference = self.reference(identity.name)
            if reference.type_id == identity:
                return reference
        return None

    def assignable(self, expected, actual):
        if expected.type_id == actual.type_id:
            return True
        if expected.kind == "optional":
            return actual.kind == "unit" or self.assignable(
                expected.element, actual.element if actual.kind == "optional" else actual
            )
        if expected.kind == actual.kind == "ref":
            return self.accepts_sort(expected.sort, actual.sort)
        if expected.kind == actual.kind and expected.kind in ("set", "sequence"):
            return self.assignable(expected.element, actual.element)
        if expected.kind == actual.kind == "int":
            return (
                expected.minimum is None
                or actual.minimum is not None
                and expected.minimum <= actual.minimum
            ) and (
                expected.maximum is None
                or actual.maximum is not None
                and actual.maximum <= expected.maximum
            )
        if expected.kind == actual.kind == "text":
            return actual.maximum <= expected.maximum
        return False


def _name(value):
    return (
        type(value) is str
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value) is not None
        and not keyword.iskeyword(value)
    )


def _type_id(name, kind, arguments, namespace):
    nominal = kind in ("enum", "record", "variant", "ref")
    identity = arguments["sort"] if kind == "ref" else name if nominal else kind
    raw = json.dumps(
        [namespace if nominal else "", identity, kind, arguments], separators=(",", ":")
    )
    return TypeId(identity, hashlib.sha256(raw.encode("utf-8")).hexdigest())


def compile_value_types(
    declarations: Mapping,
    *,
    sorts: tuple[EntitySort, ...] = (),
    namespace: str = "Lib",
    context: C0SourceContext | None = None,
    limits: TypeLimits = TypeLimits(),
) -> TypeTable:
    """Resolve one closed type graph; references to entity sorts are terminal edges."""
    if not isinstance(declarations, Mapping) or type(limits) is not TypeLimits:
        raise C0LawError("value declarations or type limits are malformed")
    limits.__post_init__()
    if type(namespace) is not str or not namespace:
        raise C0LawError("type namespace is empty or declaration budget is exceeded")
    if context is not None and type(context) is not C0SourceContext:
        raise C0LawError("type source context is malformed")

    def fail(code, definition, path, expected, actual):
        raise ValueTypeError(
            TypeDiagnostic(
                code,
                definition,
                path,
                None if context is None else context.locate(path),
                expected,
                actual,
            )
        )

    if type(sorts) is not tuple or any(type(sort) is not EntitySort for sort in sorts):
        raise C0LawError("entity sorts require closed declarations")
    if len(declarations) + len(sorts) > limits.declarations:
        fail("TypeBudget", "", "values", "bounded declaration count", "count exceeded")
    nodes = len(declarations) + len(sorts)

    def account(count, path):
        nonlocal nodes
        nodes += count
        if nodes > limits.nodes:
            fail("TypeBudget", "", path, "bounded type nodes", "node limit")

    by_sort = {}
    for sort in sorts:
        if (
            not _name(sort.name)
            or sort.name in ("Bool", "Unit")
            or sort.name in by_sort
            or sort.kind not in ("person", "object")
            or type(sort.parents) is not tuple
            or len(set(sort.parents)) != len(sort.parents)
            or any(not _name(parent) for parent in sort.parents)
        ):
            fail(
                "InvalidType",
                sort.name,
                "entities",
                "unique selected entity sort",
                "malformed sort",
            )
        by_sort[sort.name] = sort
        account(len(sort.parents), f"entities.{sort.name}")

    checked_sorts = {}

    def check_sort(name, stack):
        if name in stack:
            fail(
                "TypeCycle",
                name,
                f"entities.{name}",
                "finite entity hierarchy",
                "cycle",
            )
        if len(stack) >= limits.depth:
            fail("TypeBudget", name, f"entities.{name}", "bounded sort depth", "depth exceeded")
        if name in checked_sorts:
            return
        for parent in by_sort[name].parents:
            if parent not in by_sort or by_sort[parent].kind != by_sort[name].kind:
                fail("UnknownType", name, f"entities.{name}", "same-kind declared parent", parent)
            check_sort(parent, (*stack, name))
        depth = 1 + max((checked_sorts[parent] for parent in by_sort[name].parents), default=0)
        if depth > limits.depth:
            fail("TypeBudget", name, f"entities.{name}", "bounded sort depth", "depth exceeded")
        checked_sorts[name] = depth

    for name in by_sort:
        check_sort(name, ())

    resolved = {}

    def build(name, kind, path, **parts):
        fields = parts.get("fields", ())
        cases = parts.get("cases", ())
        element = parts.get("element")
        signature = {
            "range": [parts.get("minimum", 0), parts.get("maximum", 0)],
            "choices": parts.get("choices", ()),
            "element": None if element is None else element.type_id.signature,
            "fields": [(field, value.type_id.signature) for field, value in fields],
            "cases": [(tag, value.type_id.signature) for tag, value in cases],
            "sort": parts.get("sort"),
            "sort_kind": by_sort[parts["sort"]].kind if kind == "ref" else None,
            "parents": by_sort[parts["sort"]].parents if kind == "ref" else (),
        }
        identity = _type_id(name, kind, signature, namespace)
        annotations = {"bool": bool, "unit": type(None), "int": int, "text": str, "enum": str}
        if kind == "record":
            annotation = seal_nominal_record(
                make_nominal_record(
                    name,
                    [("_value_" + field, value.annotation) for field, value in fields],
                    namespace={},
                )
            )
        elif kind == "variant":
            annotation = reduce(or_, (value.annotation for _, value in cases))
        elif kind == "optional":
            annotation = element.annotation | type(None)
        elif kind in ("set", "sequence"):
            annotation = (
                frozenset[element.annotation] if kind == "set" else tuple[element.annotation, ...]
            )
        elif kind == "ref":
            annotation = SymbolLiteral
        else:
            annotation = annotations[kind]
        plan = ValueType(
            name,
            kind,
            identity,
            annotation,
            origin=path,
            span=None if context is None else context.locate(path),
            **parts,
        )
        return plan

    resolved["Bool"] = build("Bool", "bool", "values.Bool")
    resolved["Unit"] = build("Unit", "unit", "values.Unit")
    depths = {"Bool": 0, "Unit": 0}
    for name in declarations:
        if not _name(name) or name in resolved or name in by_sort:
            fail("DuplicateName", str(name), "values", "unambiguous type name", str(name))

    def named_fields(name, row, path, stack):
        if isinstance(row, Mapping):
            account(len(row), path)
        if not isinstance(row, Mapping) or any(not _name(field) for field in row):
            fail("InvalidType", name, path, "named field map", type(row).__name__)
        return tuple(
            (field, resolve(row[field], (*stack, name), f"{path}.{field}")) for field in sorted(row)
        )

    def resolve(name, stack=(), use_path="values"):
        if not _name(name):
            fail("UnknownType", str(name), use_path, "declared type name", type(name).__name__)
        if name in resolved:
            return resolved[name]
        if name in stack:
            fail(
                "TypeCycle",
                name,
                use_path,
                "acyclic value definitions",
                " -> ".join((*stack, name)),
            )
        if len(stack) >= limits.depth:
            fail("TypeBudget", name, use_path, "bounded type depth", "depth exceeded")
        if name not in declarations:
            fail("UnknownType", name, use_path, "declared value type", name)
        path = f"values.{name}"
        row = declarations[name]
        if type(row) is str:
            plan = resolve(row, (*stack, name), path)
            dependencies = (row,)
        else:
            if not isinstance(row, Mapping) or len(row) != 1:
                fail("InvalidType", name, path, "one type constructor", type(row).__name__)
            kind, body = next(iter(row.items()))
            parts = {}
            dependencies = ()
            if kind == "int":
                if (
                    type(body) is not list
                    or len(body) != 2
                    or any(v is not None and type(v) is not int for v in body)
                    or body[0] is not None
                    and body[1] is not None
                    and body[0] > body[1]
                ):
                    fail("InvalidType", name, path, "ordered integer bounds", "invalid interval")
                parts = {"minimum": body[0], "maximum": body[1]}
            elif kind == "text":
                if (
                    not isinstance(body, Mapping)
                    or set(body) != {"max_chars"}
                    or type(body["max_chars"]) is not int
                    or body["max_chars"] < 0
                ):
                    fail("InvalidType", name, path, "nonnegative max_chars", "invalid text limit")
                parts = {"maximum": body["max_chars"]}
            elif kind == "enum":
                if type(body) is list:
                    account(len(body), path)
                if (
                    type(body) is not list
                    or not body
                    or any(not _name(v) for v in body)
                    or len(set(body)) != len(body)
                ):
                    fail("InvalidType", name, path, "unique enum labels", "invalid enum")
                parts = {"choices": tuple(body)}
            elif kind in ("optional", "set", "sequence"):
                parts = {"element": resolve(body, (*stack, name), path)}
                dependencies = (body,)
            elif kind == "record":
                parts = {"fields": named_fields(name, body, f"{path}.record", stack)}
                dependencies = tuple(body.values())
            elif kind == "variant":
                if not isinstance(body, Mapping) or not body or any(not _name(tag) for tag in body):
                    fail("InvalidType", name, path, "named variant cases", "invalid cases")
                account(len(body), path)
                parts = {
                    "cases": tuple(
                        (
                            tag,
                            build(
                                f"{name}.{tag}",
                                "record",
                                f"{path}.variant.{tag}",
                                fields=named_fields(
                                    name, body[tag], f"{path}.variant.{tag}", stack
                                ),
                            ),
                        )
                        for tag in sorted(body)
                    )
                }
                dependencies = tuple(child for fields in body.values() for child in fields.values())
            elif kind == "ref":
                if not _name(body) or body not in by_sort:
                    fail("UnknownType", name, path, "declared entity sort", str(body))
                parts = {"sort": body}
            else:
                fail("UnsupportedFeature", name, path, "selected value constructor", str(kind))
            plan = build(name, kind, path, **parts)
        depth = 1 + max((depths[child] for child in dependencies), default=0)
        if depth > limits.depth:
            fail("TypeBudget", name, path, "bounded type depth", "depth exceeded")
        depths[name] = depth
        resolved[name] = plan
        return plan

    for name in declarations:
        resolve(name)
    return TypeTable(
        tuple(sorted(resolved.items())), tuple(sorted(sorts, key=lambda sort: sort.name))
    )
