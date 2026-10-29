"""Typed pure value plans; logical reads stay separate from K0 owner selection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import C0SourceContext

from .entity_reads import EntityReadLibrary, OwnerRead
from .expression_syntax import (
    ExpressionLimits,
    ExpressionSource,
    _identifier,
    parse_expression,
)
from .value_types import TypeId, TypeTable, ValueType
from .values import validate_scalar

NORMALIZED_OPERATIONS = frozenset(
    {
        "literal",
        "variable",
        "field",
        "construct",
        "collection",
        "pure_call",
        "filter",
        "map",
        "size",
        "contains",
        "sum",
        "sum_by",
        "exists",
        "exactly_one",
        "forall",
        "min_by",
        "max_by",
        "latest_by",
        "distinct",
        "union",
        "difference",
        "at",
        "append",
        "concat",
        "index_of",
        "take",
        "drop",
        "if",
        "match",
        "and",
        "or",
        "not",
        "unary",
        "is",
        "is not",
        "in",
        "not in",
        "+",
        "-",
        "*",
        "//",
        "%",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "known",
        "entity_field",
        "local_view",
        "relation",
    }
)

_INTRINSICS = frozenset(
    (
        "optional_choices",
        "filter",
        "map",
        "exists",
        "exactly_one",
        "reports",
        "projected",
        "cognition",
        "forall",
        "size",
        "distinct",
        "contains",
        "union",
        "difference",
        "sum",
        "sum_by",
        "min_by",
        "max_by",
        "latest_by",
        "match",
        "known",
        "at",
        "append",
        "concat",
        "index_of",
        "take",
        "drop",
    )
)
_LAMBDA_INTRINSICS = frozenset(("filter", "map", "exists", "exactly_one", "forall", "sum_by"))
_ELEMENTS = "[]"


@dataclass(frozen=True, order=True)
class ValueRead:
    root: str
    steps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValueInput:
    type_name: str
    readable: tuple[tuple[str, ...], ...] | None = None
    exposure: str = "actor"


@dataclass(frozen=True)
class PureDependency:
    definition: str
    call_path: str
    offset: int
    arguments: tuple[tuple[str, tuple[ValueRead, ...]], ...]


@dataclass(frozen=True)
class ExprSummary:
    result_type: TypeId
    reads: tuple[ValueRead, ...]
    context: str
    dependencies: tuple[PureDependency, ...]
    exposure: tuple[str, ...]
    owner_reads: tuple[OwnerRead, ...] = ()
    reference_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValueExpression:
    operation: str
    value_type: ValueType | IntegerExpressionType
    children: tuple[ValueExpression, ...] = ()
    operand: object = None
    path: ValueRead | None = None
    reads: tuple[ValueRead, ...] = ()
    dependencies: tuple[PureDependency, ...] = ()
    offset: int = 0
    flow_path: tuple[str | int, ...] | None = None
    owner_reads: tuple[OwnerRead, ...] = ()
    reference_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class PureValueDefinition:
    name: str
    parameters: tuple[tuple[str, ValueType], ...]
    returns: ValueType
    body: ValueExpression
    source: ExpressionSource
    call_depth: int = 1


def _unique(values):
    return tuple(dict.fromkeys(values))


def _selected_reads(value, path):
    if path is None:
        return value.reads
    # Refine the value path while retaining indices and other selection dependencies.
    return _unique((path, *(read for read in value.reads if read != value.path)))


@dataclass(frozen=True)
class IntegerExpressionType:
    """An intermediate integer may lack proven bounds; it is not an authored TypeDef."""

    minimum: int | None = None
    maximum: int | None = None
    kind: str = "int"
    name: str = "IntegerExpression"

    @property
    def has_references(self):
        return False

    @property
    def type_id(self):
        raw = f"{self.minimum}:{self.maximum}"
        return TypeId("int", hashlib.sha256(raw.encode()).hexdigest())


def _integer(low=None, high=None):
    return IntegerExpressionType(low, high)


def _collection(kind, element):
    raw = kind + element.type_id.signature
    return ValueType(
        "CollectionExpression",
        kind,
        TypeId(kind, hashlib.sha256(raw.encode()).hexdigest()),
        frozenset if kind == "set" else tuple,
        element=element,
    )


def _optional(element):
    return ValueType(
        "OptionalExpression",
        "optional",
        TypeId("optional", element.type_id.signature),
        object,
        element=element,
    )


def _compatible(table, expected, actual):
    if expected.kind == "optional":
        return actual.kind == "unit" or _compatible(
            table, expected.element, actual.element if actual.kind == "optional" else actual
        )
    if expected.kind == actual.kind and expected.kind in ("int", "text"):
        return True
    if expected.kind == actual.kind and expected.kind in ("set", "sequence"):
        return _compatible(table, expected.element, actual.element)
    return table.assignable(expected, actual)


def _join(table, left, right):
    if left.type_id == right.type_id:
        return left
    if left.kind == "unit" or right.kind == "unit":
        other = right if left.kind == "unit" else left
        return other if other.kind == "optional" else _optional(other)
    if left.kind == right.kind == "int":
        if None in (left.minimum, left.maximum, right.minimum, right.maximum):
            return _integer()
        return _integer(min(left.minimum, right.minimum), max(left.maximum, right.maximum))
    if left.kind == right.kind and left.kind in ("set", "sequence"):
        element = _join(table, left.element, right.element)
        return None if element is None else _collection(left.kind, element)
    if left.kind == "optional" or right.kind == "optional":
        optional, other = (left, right) if left.kind == "optional" else (right, left)
        if other.kind == "unit":
            return optional
        element = _join(
            table, optional.element, other.element if other.kind == "optional" else other
        )
        if element is None:
            return None
        return _optional(element)
    if table.assignable(left, right):
        return left
    if table.assignable(right, left):
        return right
    return None


def _substitute(read, arguments):
    argument = arguments[read.root]
    if argument.path is not None:
        return (ValueRead(argument.path.root, (*argument.path.steps, *read.steps)),)
    return argument.reads


class _Compiler:
    def __init__(self, table, source, limits, definitions, entities=None, local_views=()):
        self.table, self.source, self.limits = table, source, limits
        self.definitions = definitions
        self.entities = entities
        self.local_views = dict(local_views)
        self.nodes = self.depth = 0

    def fail(self, syntax, code, expected, actual):
        self.source.fail(code, syntax.start, expected, actual)

    def node(
        self,
        syntax,
        operation,
        plan,
        children=(),
        *,
        operand=None,
        path=None,
        reads=None,
        dependencies=None,
        flow_path=None,
        owner_reads=None,
        reference_domains=None,
    ):
        children = tuple(children)
        if operation not in NORMALIZED_OPERATIONS:
            raise C0LawError("undeclared normalized operation: " + operation)
        value = ValueExpression(
            operation,
            plan,
            children,
            operand,
            path,
            _unique(read for child in children for read in child.reads)
            if reads is None
            else _unique(reads),
            _unique(dep for child in children for dep in child.dependencies)
            if dependencies is None
            else _unique(dependencies),
            syntax.start,
            flow_path,
            _unique(read for child in children for read in child.owner_reads)
            if owner_reads is None
            else _unique(owner_reads),
            _unique(sort for child in children for sort in child.reference_domains)
            if reference_domains is None
            else _unique(reference_domains),
        )
        if (
            len(value.reads)
            + len(value.dependencies)
            + len(value.owner_reads)
            + len(value.reference_domains)
            > self.limits.nodes
        ):
            self.fail(syntax, "ExpressionBudget", "bounded dependency summary", "summary limit")
        return value

    def check(self, syntax, environment, expected=None, refinements=None):
        self.nodes += 1
        self.depth += 1
        if self.nodes > self.limits.nodes or self.depth > self.limits.depth:
            self.fail(syntax, "ExpressionBudget", "bounded typed plan", "node/depth limit")
        try:
            result = self._check(syntax, environment, expected, refinements or {})
            if expected is not None and not _compatible(self.table, expected, result.value_type):
                self.fail(syntax, "TypeMismatch", expected.name, result.value_type.name)
            if expected is not None and result.operation == "literal":
                target = (
                    expected.element
                    if expected.kind == "optional" and result.operand is not None
                    else expected
                )
                if target.kind in ("bool", "unit", "int", "text", "enum"):
                    scalar_options = {}
                    if target.kind == "int":
                        scalar_options = {"minimum": target.minimum, "maximum": target.maximum}
                    elif target.kind == "text":
                        scalar_options = {"maximum": target.maximum}
                    elif target.kind == "enum":
                        scalar_options = {"choices": target.choices}
                    try:
                        validate_scalar(
                            target.kind,
                            result.operand,
                            **scalar_options,
                        )
                    except ValueError:
                        self.fail(
                            syntax, "InvalidValue", expected.name, "literal outside declared domain"
                        )
            return result
        finally:
            self.depth -= 1

    def _check(self, syntax, environment, expected, refinements):
        kind = syntax.operation
        if kind == "literal":
            value = syntax.value
            if type(value) is bool:
                plan = self.table["Bool"]
            elif value is None:
                plan = self.table["Unit"]
            elif type(value) is int:
                plan = _integer(value, value)
            elif type(value) is str:
                if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                    self.fail(syntax, "InvalidValue", "Unicode scalar text", "surrogate")
                plan = ValueType(
                    "TextExpression",
                    "text",
                    TypeId("text", str(len(value))),
                    str,
                    maximum=len(value),
                )
            else:
                self.fail(syntax, "InvalidValue", "value literal", type(value).__name__)
            return self.node(syntax, "literal", plan, operand=value)
        if kind == "name":
            if syntax.value not in environment:
                self.fail(syntax, "UnboundName", "declared input or parameter", syntax.value)
            value = environment[syntax.value]
            return replace(
                value,
                value_type=refinements.get(value.flow_path, value.value_type),
                offset=syntax.start,
            )
        if kind == "field":
            if syntax.children[0].operation == "name":
                name = syntax.children[0].value
                plan = dict(self.table.definitions).get(name)
                if plan is not None and plan.kind == "enum":
                    if syntax.value not in plan.choices:
                        self.fail(syntax, "InvalidValue", "declared enum label", syntax.value)
                    return self.node(syntax, "literal", plan, operand=syntax.value)
            value = self.check(syntax.children[0], environment, refinements=refinements)
            plan = value.value_type
            if plan.kind == "ref":
                if syntax.value == "id":
                    return value
                if self.entities is None:
                    self.fail(
                        syntax, "UnsupportedFeature", "declared entity field schema", syntax.value
                    )
                try:
                    result = self.entities.field(plan.sort, syntax.value)
                except C0LawError:
                    self.fail(syntax, "UnknownField", "declared entity field", syntax.value)
                request = OwnerRead(plan.sort, syntax.value, value.path)
                flow_path = (
                    None
                    if value.flow_path is None
                    else (*value.flow_path, "entity_field", plan.sort, syntax.value)
                )
                return self.node(
                    syntax,
                    "entity_field",
                    refinements.get(flow_path, result),
                    (value,),
                    operand=request,
                    owner_reads=(*value.owner_reads, request),
                    flow_path=flow_path,
                )
            if plan.kind != "record" or syntax.value not in dict(plan.fields):
                self.fail(syntax, "UnknownField", "declared Record field", syntax.value)
            field = dict(plan.fields)[syntax.value]
            path = (
                None
                if value.path is None
                else ValueRead(value.path.root, (*value.path.steps, syntax.value))
            )
            flow_path = (
                None if value.flow_path is None else (*value.flow_path, "field", syntax.value)
            )
            field = refinements.get(flow_path, field)
            return self.node(
                syntax,
                "field",
                field,
                (value,),
                operand=(plan, syntax.value),
                path=path,
                reads=_selected_reads(value, path),
                flow_path=flow_path,
            )
        if kind == "if":
            condition = self.check(syntax.children[0], environment, self.table["Bool"], refinements)
            left = self.check(
                syntax.children[1], environment, expected, self.refine(refinements, condition, True)
            )
            right = self.check(
                syntax.children[2],
                environment,
                expected,
                self.refine(refinements, condition, False),
            )
            plan = expected or _join(self.table, left.value_type, right.value_type)
            if plan is None:
                self.fail(
                    syntax,
                    "TypeMismatch",
                    "compatible conditional branches",
                    "different nominal values",
                )
            return self.node(syntax, "if", plan, (condition, left, right))
        if kind == "not":
            child = self.check(syntax.children[0], environment, self.table["Bool"], refinements)
            return self.node(syntax, "not", self.table["Bool"], (child,))
        if kind == "unary":
            child = self.check(syntax.children[0], environment, refinements=refinements)
            if child.value_type.kind != "int":
                self.fail(syntax, "TypeMismatch", "Integer", child.value_type.name)
            if child.operation == "literal":
                return self.node(
                    syntax,
                    "literal",
                    _integer(-child.operand, -child.operand)
                    if syntax.value == "-"
                    else child.value_type,
                    operand=-child.operand if syntax.value == "-" else child.operand,
                )
            plan = child.value_type
            if syntax.value == "-":
                plan = _integer(
                    None if plan.maximum is None else -plan.maximum,
                    None if plan.minimum is None else -plan.minimum,
                )
            return self.node(syntax, "unary", plan, (child,), operand=syntax.value)
        if kind == "binary":
            return self.binary(syntax, environment, refinements)
        if kind == "call":
            return self.call(syntax, environment, expected, refinements)
        if kind == "match":
            return self.match(syntax, environment, expected, refinements)
        self.fail(syntax, "InvalidSyntax", "typed expression", kind)

    def match(self, syntax, environment, expected, refinements):
        subject = self.check(syntax.children[0], environment, refinements=refinements)
        if subject.value_type.kind != "variant":
            self.fail(syntax, "TypeMismatch", "named Variant", subject.value_type.name)
        declared = dict(subject.value_type.cases)
        tags = [case.value[0] for case in syntax.children[1:]]
        if len(tags) != len(set(tags)) or set(tags) != set(declared):
            self.fail(syntax, "IncompleteMatch", "each declared tag exactly once", str(tags))
        branches, bindings = [], []
        result = expected
        for case in syntax.children[1:]:
            tag, binder = case.value
            local = dict(environment)
            if binder is not None:
                if (
                    binder in dict(self.table.definitions)
                    or binder in _INTRINSICS
                    or binder in self.definitions
                    or self.entities is not None
                    and binder in dict(self.entities.relations)
                ):
                    self.fail(case, "InvalidCall", "unambiguous case binding", binder)
                path = (
                    None
                    if subject.path is None
                    else ValueRead(subject.path.root, (*subject.path.steps, tag))
                )
                local[binder] = self.node(
                    case,
                    "variable",
                    declared[tag],
                    operand=binder,
                    path=path,
                    reads=(path,) if path is not None else subject.reads,
                    flow_path=("case", self.source.path, case.start, binder),
                )
            branch = self.check(case.children[0], local, expected, refinements)
            result = (
                branch.value_type
                if result is None
                else _join(self.table, result, branch.value_type)
            )
            if result is None:
                self.fail(case, "TypeMismatch", "compatible match results", branch.value_type.name)
            branches.append(branch)
            bindings.append((tag, binder, declared[tag].annotation))
        return self.node(
            syntax, "match", expected or result, (subject, *branches), operand=tuple(bindings)
        )

    def refine(self, current, condition, truth):
        result = dict(current)
        if condition.operation == "not":
            return self.refine(result, condition.children[0], not truth)
        if condition.operation in ("is", "is not"):
            value = condition.children[0]
            if value.flow_path is not None and value.value_type.kind == "optional":
                present = truth if condition.operation == "is not" else not truth
                result[value.flow_path] = (
                    value.value_type.element if present else self.table["Unit"]
                )
        if condition.operation == "and" and truth or condition.operation == "or" and not truth:
            for child in condition.children:
                result = self.refine(result, child, truth)
        return result

    def binary(self, syntax, environment, refinements):
        operation = syntax.value
        left = self.check(syntax.children[0], environment, refinements=refinements)
        next_refinements = (
            self.refine(refinements, left, operation == "and")
            if operation in ("and", "or")
            else refinements
        )
        right = self.check(syntax.children[1], environment, refinements=next_refinements)
        a, b = left.value_type, right.value_type
        if operation in ("and", "or"):
            valid = a.kind == b.kind == "bool"
        elif operation in ("+", "-", "*", "//", "%", "<", "<=", ">", ">="):
            valid = a.kind == b.kind == "int"
        elif operation in ("in", "not in"):
            valid = b.kind == "set" and _compatible(self.table, b.element, a)
        elif operation in ("is", "is not"):
            valid = (
                right.operation == "literal"
                and right.operand is None
                and a.kind in ("optional", "unit")
            )
        else:
            valid = _compatible(self.table, a, b) or _compatible(self.table, b, a)
        if not valid:
            self.fail(
                syntax,
                "TypeMismatch",
                "compatible operands for " + operation,
                a.name + "/" + b.name,
            )
        if operation in ("+", "-", "*", "//", "%"):
            if operation == "+":
                plan = _integer(
                    None if a.minimum is None or b.minimum is None else a.minimum + b.minimum,
                    None if a.maximum is None or b.maximum is None else a.maximum + b.maximum,
                )
            elif operation == "-":
                plan = _integer(
                    None if a.minimum is None or b.maximum is None else a.minimum - b.maximum,
                    None if a.maximum is None or b.minimum is None else a.maximum - b.minimum,
                )
            elif None in (a.minimum, a.maximum, b.minimum, b.maximum):
                plan = _integer()
            elif operation == "*":
                products = [x * y for x in (a.minimum, a.maximum) for y in (b.minimum, b.maximum)]
                plan = _integer(min(products), max(products))
            else:
                bound = max(abs(a.minimum), abs(a.maximum), abs(b.minimum), abs(b.maximum), 1)
                plan = _integer(-bound, bound)
        else:
            plan = self.table["Bool"]
        return self.node(syntax, operation, plan, (left, right))

    def call(self, syntax, environment, expected, refinements):
        function, *arguments = syntax.children
        if function.operation == "name":
            name = function.value
            if name in ("reports", "projected", "cognition"):
                if (
                    len(arguments) != 1
                    or arguments[0].operation != "name"
                    or arguments[0].value not in self.local_views
                ):
                    self.fail(syntax, "UnknownView", "declared local view alias", name)
                alias = arguments[0].value
                view = self.local_views[alias]
                if view.kind != name:
                    self.fail(syntax, "ViewKindMismatch", view.kind, name)
                return self.node(syntax, "local_view", self.table[view.type_name], operand=alias)
            plan = dict(self.table.definitions).get(name)
            if plan is not None:
                return self.construct(syntax, plan, None, arguments, environment, refinements)
            if name == "known":
                if (
                    self.entities is None
                    or len(arguments) != 1
                    or arguments[0].operation != "name"
                    or arguments[0].value not in dict(self.entities.entities)
                ):
                    self.fail(syntax, "InvalidDomain", "known(declared entity sort)", name)
                sort = arguments[0].value
                plan = self.table.collection(self.table.reference(sort).name)
                return self.node(syntax, "known", plan, operand=sort, reference_domains=(sort,))
            if name in _INTRINSICS:
                return self.intrinsic(syntax, name, arguments, environment, expected, refinements)
            if name in self.definitions:
                definition = self.definitions[name]
                if len(arguments) != len(definition.parameters) or any(
                    arg.operation in ("keyword", "lambda") for arg in arguments
                ):
                    self.fail(syntax, "InvalidCall", "positional pure parameters", name)
                children = tuple(
                    self.check(arg, environment, kind, refinements)
                    for arg, (_, kind) in zip(arguments, definition.parameters, strict=True)
                )
                bindings = {
                    key: child
                    for (key, _), child in zip(definition.parameters, children, strict=True)
                }
                reads = _unique(
                    read
                    for body_read in definition.body.reads
                    for read in _substitute(body_read, bindings)
                )
                reads = _unique(
                    (
                        *reads,
                        *(read for child in children for read in child.reads),
                    )
                )
                nested = tuple(
                    replace(
                        dep,
                        arguments=tuple(
                            (key, _unique(read for r in paths for read in _substitute(r, bindings)))
                            for key, paths in dep.arguments
                        ),
                    )
                    for dep in definition.body.dependencies
                )
                dependency = PureDependency(
                    name,
                    self.source.path,
                    syntax.start,
                    tuple((key, child.reads) for key, child in bindings.items()),
                )
                return self.node(
                    syntax,
                    "pure_call",
                    definition.returns,
                    children,
                    operand=definition,
                    reads=reads,
                    dependencies=(
                        *nested,
                        dependency,
                        *(dep for child in children for dep in child.dependencies),
                    ),
                    owner_reads=(
                        *(read for child in children for read in child.owner_reads),
                        *(
                            replace(
                                read,
                                selector=(
                                    None
                                    if read.selector is None
                                    else (
                                        ValueRead(
                                            bindings[read.selector.root].path.root,
                                            (
                                                *bindings[read.selector.root].path.steps,
                                                *read.selector.steps,
                                            ),
                                        )
                                        if bindings[read.selector.root].path is not None
                                        else None
                                    )
                                ),
                            )
                            for read in definition.body.owner_reads
                        ),
                    ),
                    reference_domains=(
                        *definition.body.reference_domains,
                        *(sort for child in children for sort in child.reference_domains),
                    ),
                )
            self.fail(
                syntax, "UnboundName", "declared constructor, intrinsic or pure definition", name
            )
        if function.operation == "field" and function.children[0].operation == "name":
            plan = dict(self.table.definitions).get(function.children[0].value)
            if plan is not None and plan.kind == "variant":
                return self.construct(
                    syntax, plan, function.value, arguments, environment, refinements
                )
            relation = (
                None
                if self.entities is None
                else dict(self.entities.relations).get(function.children[0].value)
            )
            if relation is not None:
                return self.relation(
                    syntax, relation, function.value, arguments, environment, refinements
                )
        self.fail(
            syntax, "InvalidCall", "statically declared pure operation", "dynamic method/call"
        )

    def relation(self, syntax, relation, operation, arguments, environment, refinements):
        count = 2 if operation == "held_by" else 1
        if (
            operation not in ("holder", "held_by", "position")
            or len(arguments) != count
            or any(arg.operation in ("keyword", "lambda") for arg in arguments)
        ):
            self.fail(syntax, "InvalidCall", "carrying holder/held_by/position", operation)
        item = self.check(arguments[0], environment, refinements=refinements)
        if item.value_type.kind != "ref" or not self.table.accepts_sort(
            relation.item, item.value_type.sort
        ):
            self.fail(syntax, "TypeMismatch", relation.item + " Ref", item.value_type.name)
        children = [item]
        holder = self.entities.field(relation.item, relation.holder)
        if operation == "held_by":
            person = self.check(arguments[1], environment, refinements=refinements)
            if person.value_type.kind != "ref" or not self.table.accepts_sort(
                relation.person, person.value_type.sort
            ):
                self.fail(syntax, "TypeMismatch", relation.person + " Ref", person.value_type.name)
            children.append(person)
        if operation == "position":
            request = OwnerRead(relation.item, operation, item.path, relation.name)
            plan = self.entities.field(relation.item, relation.ground)
        else:
            request = OwnerRead(relation.item, relation.holder, item.path)
            plan = self.table["Bool"] if operation == "held_by" else holder
        flow_path = (
            (*item.flow_path, "entity_field", relation.item, relation.holder)
            if operation == "holder" and item.flow_path is not None
            else None
        )
        return self.node(
            syntax,
            "relation",
            refinements.get(flow_path, plan),
            children,
            operand=(relation, operation),
            owner_reads=(*(read for child in children for read in child.owner_reads), request),
            flow_path=flow_path,
        )

    def construct(self, syntax, plan, tag, arguments, environment, refinements):
        if plan.kind in ("set", "sequence") and tag is None:
            if len(arguments) != 1 or arguments[0].operation != "list":
                self.fail(syntax, "InvalidConstructor", "collection literal", plan.name)
            children = tuple(
                self.check(item, environment, plan.element, refinements)
                for item in arguments[0].children
            )
            return self.node(syntax, "collection", plan, children)
        if plan.kind == "variant":
            selected = dict(plan.cases).get(tag)
            if selected is None:
                self.fail(syntax, "InvalidConstructor", "declared Variant case", str(tag))
        elif plan.kind == "record" and tag is None:
            selected = plan
        else:
            self.fail(syntax, "InvalidConstructor", "Record, Variant or collection", plan.name)
        keys = [arg.value for arg in arguments if arg.operation == "keyword"]
        if (
            len(keys) != len(arguments)
            or len(set(keys)) != len(keys)
            or set(keys) != set(dict(selected.fields))
        ):
            self.fail(
                syntax, "InvalidConstructor", "exact named fields", "missing/extra/duplicate field"
            )
        arguments = {arg.value: arg.children[0] for arg in arguments}
        children = tuple(
            self.check(arguments[key], environment, kind, refinements)
            for key, kind in selected.fields
        )
        return self.node(syntax, "construct", plan, children, operand=(tag, selected.fields))

    def lambda_body(self, syntax, argument, first, environment, required, refinements):
        if argument.operation != "lambda":
            self.fail(argument, "InvalidCall", "typed lambda argument", syntax.children[0].value)
        parameter = argument.value
        if (
            parameter in dict(self.table.definitions)
            or parameter in _INTRINSICS
            or parameter in self.definitions
        ):
            self.fail(argument, "InvalidCall", "unambiguous lambda parameter", parameter)
        path = (
            None
            if first.path is None
            else ValueRead(first.path.root, (*first.path.steps, _ELEMENTS))
        )
        variable = self.node(
            argument,
            "variable",
            first.value_type.element,
            operand=parameter,
            path=path,
            reads=(path,) if path is not None else first.reads,
            flow_path=("lambda", self.source.path, syntax.start, parameter),
        )
        body = self.check(
            argument.children[0], {**environment, parameter: variable}, required, refinements
        )
        return parameter, body

    def ranked_selection(self, syntax, name, arguments, environment, refinements):
        if len(arguments) not in (2, 3) or any(arg.operation == "keyword" for arg in arguments):
            self.fail(syntax, "InvalidCall", "collection, key lambda and optional tie lambda", name)
        first = self.check(arguments[0], environment, refinements=refinements)
        if first.value_type.kind not in ("set", "sequence"):
            self.fail(syntax, "TypeMismatch", "Set or Sequence", first.value_type.name)
        bodies, parameters = [], []
        for argument in arguments[1:]:
            parameter, body = self.lambda_body(
                syntax, argument, first, environment, None, refinements
            )
            if body.value_type.kind != "int":
                self.fail(argument, "TypeMismatch", "Integer ranking key", body.value_type.name)
            parameters.append(parameter)
            bodies.append(body)
        element = self.table.expression_type(first.value_type.element)
        return self.node(
            syntax,
            name,
            self.table.optional(element.name),
            (first, *bodies),
            operand=tuple(parameters),
        )

    def intrinsic(self, syntax, name, arguments, environment, expected, refinements):
        if name == "latest_by":
            if len(arguments) != 3 or any(arg.operation == "keyword" for arg in arguments):
                self.fail(syntax, "InvalidCall", "sequence, group key and version lambdas", name)
            first = self.check(arguments[0], environment, refinements=refinements)
            if first.value_type.kind != "sequence":
                self.fail(syntax, "TypeMismatch", "Sequence", first.value_type.name)
            key_name, key = self.lambda_body(
                syntax, arguments[1], first, environment, None, refinements
            )
            version_name, version = self.lambda_body(
                syntax, arguments[2], first, environment, None, refinements
            )
            if version.value_type.kind != "int":
                self.fail(arguments[2], "TypeMismatch", "Integer version", version.value_type.name)
            return self.node(
                syntax,
                name,
                first.value_type,
                (first, key, version),
                operand=(key_name, version_name),
            )
        if name in ("min_by", "max_by"):
            return self.ranked_selection(syntax, name, arguments, environment, refinements)
        if name == "optional_choices":
            if len(arguments) != 2 or any(arg.operation == "keyword" for arg in arguments):
                self.fail(syntax, "InvalidCall", "Set<T> and explicit Bool", name)
            pool = self.check(arguments[0], environment, refinements=refinements)
            if pool.value_type.kind != "set" or pool.value_type.element.kind in (
                "optional",
                "unit",
            ):
                self.fail(
                    arguments[0],
                    "TypeMismatch",
                    "Set of non-Optional, non-Unit values",
                    pool.value_type.name,
                )
            allowed = self.check(arguments[1], environment, self.table["Bool"], refinements)
            element = self.table.expression_type(pool.value_type.element)
            plan = self.table.collection(self.table.optional(element.name).name)
            empty = self.node(syntax, "collection", plan)
            none = self.node(syntax, "literal", self.table["Unit"], operand=None)
            singleton = self.node(syntax, "collection", plan, (none,))
            extra = self.node(syntax, "if", plan, (allowed, singleton, empty))
            return self.node(syntax, "union", plan, (pool, extra))
        count = (
            2
            if name in _LAMBDA_INTRINSICS
            or name
            in (
                "contains",
                "union",
                "difference",
                "at",
                "append",
                "concat",
                "index_of",
                "take",
                "drop",
            )
            else 1
        )
        if len(arguments) != count or any(arg.operation == "keyword" for arg in arguments):
            self.fail(syntax, "InvalidCall", f"{count} intrinsic arguments", name)
        first = self.check(arguments[0], environment, refinements=refinements)
        kind = first.value_type
        if name == "concat":
            if kind.kind != "sequence":
                self.fail(syntax, "TypeMismatch", "Sequence", kind.name)
            second = self.check(arguments[1], environment, refinements=refinements)
            if (
                second.value_type.kind != "sequence"
                or second.value_type.element.type_id != kind.element.type_id
            ):
                self.fail(
                    syntax,
                    "TypeMismatch",
                    "Sequence with the same nominal element",
                    second.value_type.name,
                )
            return self.node(syntax, name, kind, (first, second))
        if name in ("at", "append", "index_of", "take", "drop"):
            if kind.kind != "sequence":
                self.fail(syntax, "TypeMismatch", "Sequence", kind.name)
            second = self.check(
                arguments[1],
                environment,
                kind.element if name in ("append", "index_of") else self.table["Integer<>"],
                refinements,
            )
            path = (
                None
                if first.path is None
                else ValueRead(first.path.root, (*first.path.steps, _ELEMENTS))
            )
            return self.node(
                syntax,
                name,
                kind.element if name == "at" else _integer(0, None) if name == "index_of" else kind,
                (first, second),
                path=path if name == "at" else None,
                reads=(*_selected_reads(first, path), *second.reads),
            )
        if name == "size":
            if kind.kind not in ("text", "set", "sequence"):
                self.fail(syntax, "TypeMismatch", "Text, Set or Sequence", kind.name)
            return self.node(
                syntax, name, _integer(0, kind.maximum if kind.kind == "text" else None), (first,)
            )
        if name == "distinct":
            if kind.kind not in ("set", "sequence"):
                self.fail(syntax, "TypeMismatch", "Set or Sequence", kind.name)
            return self.node(syntax, name, _collection("set", kind.element), (first,))
        if name == "sum":
            if kind.kind != "sequence" or kind.element.kind != "int":
                self.fail(syntax, "TypeMismatch", "Sequence<Integer>", kind.name)
            return self.node(syntax, name, _integer(), (first,))
        if kind.kind not in ("set", "sequence") or (
            name not in _LAMBDA_INTRINSICS and kind.kind != "set"
        ):
            self.fail(syntax, "TypeMismatch", "intrinsic collection type", kind.name)
        if name in _LAMBDA_INTRINSICS:
            required = (
                self.table["Bool"]
                if name in ("filter", "exists", "exactly_one", "forall")
                else (
                    expected.element
                    if name == "map" and expected is not None and expected.kind == kind.kind
                    else None
                )
            )
            parameter, body = self.lambda_body(
                syntax, arguments[1], first, environment, required, refinements
            )
            if name == "sum_by" and body.value_type.kind != "int":
                self.fail(
                    arguments[1], "TypeMismatch", "Integer contribution", body.value_type.name
                )
            plan = (
                self.table["Bool"]
                if name in ("exists", "exactly_one", "forall")
                else (
                    _integer()
                    if name == "sum_by"
                    else (_collection(kind.kind, body.value_type) if name == "map" else kind)
                )
            )
            return self.node(syntax, name, plan, (first, body), operand=parameter)
        second = self.check(
            arguments[1], environment, kind.element if name == "contains" else kind, refinements
        )
        plan = (
            self.table["Bool"] if name == "contains" else _join(self.table, kind, second.value_type)
        )
        if plan is None:
            self.fail(syntax, "TypeMismatch", "compatible collection elements", name)
        return self.node(syntax, name, plan, (first, second))


@dataclass(frozen=True)
class CheckedValueExpression:
    table: TypeTable
    inputs: tuple[tuple[str, ValueInput], ...]
    node: ValueExpression
    result: ValueType
    summary: ExprSummary
    source: ExpressionSource
    limits: ExpressionLimits
    entities: EntityReadLibrary | None = None
    actor: str | None = None
    read_key: str = ""


def _bindings(table, declarations):
    if not isinstance(declarations, Mapping):
        raise C0LawError("expression inputs must be named type bindings")
    values = []
    for name, value in declarations.items():
        if not _identifier(name) or name in dict(table.definitions) or name in _INTRINSICS:
            raise C0LawError("expression input conflicts with a reserved symbol")
        spec = ValueInput(value) if type(value) is str else value
        if type(spec) is not ValueInput:
            raise C0LawError("expression input has an unknown type")
        try:
            table[spec.type_name]
        except KeyError:
            raise C0LawError("expression input has an unknown type") from None
        if spec.exposure not in ("actor", "world") or (
            spec.readable is not None
            and (
                type(spec.readable) is not tuple
                or any(
                    type(path) is not tuple or any(type(step) is not str for step in path)
                    for path in spec.readable
                )
            )
        ):
            raise C0LawError("expression input permission is malformed")
        for steps in spec.readable or ():
            plan = table[spec.type_name]
            for step in steps:
                if plan.kind == "optional":
                    plan = plan.element
                if step == _ELEMENTS and plan.kind in ("set", "sequence"):
                    plan = plan.element
                elif plan.kind == "record" and step in dict(plan.fields):
                    plan = dict(plan.fields)[step]
                else:
                    raise C0LawError("expression input permission names an unknown data path")
        values.append((name, spec))
    return tuple(values)


def compile_value_expression(
    text,
    table,
    inputs,
    *,
    returns,
    library=None,
    context="actor",
    path="expression",
    span=None,
    limits=ExpressionLimits(),
    entities=None,
    actor=None,
    local_views=(),
):
    if type(table) is not TypeTable or type(limits) is not ExpressionLimits:
        raise C0LawError("expression compiler needs a type table and limits")
    try:
        result_type = None if returns is None else table[returns]
    except (KeyError, TypeError, RecursionError):
        raise C0LawError("expression result type is unknown") from None
    if context not in ("actor", "world"):
        raise C0LawError("expression result type or context is unknown")
    if library is not None and (
        type(library) is not PureValueLibrary or library.table is not table
    ):
        raise C0LawError("pure library differs from the expression type table")
    specs = _bindings(table, inputs)
    entities = entities if entities is not None else None if library is None else library.entities
    if entities is not None and (
        type(entities) is not EntityReadLibrary
        or entities.table is not table
        or library is not None
        and library.entities is not entities
    ):
        raise C0LawError("entity library differs from the expression type table/pure library")
    if actor is not None:
        actor_type = table[dict(specs)[actor].type_name] if actor in dict(specs) else None
        if (
            actor_type is None
            or actor_type.kind != "ref"
            or next(sort for sort in table.sorts if sort.name == actor_type.sort).kind != "person"
        ):
            raise C0LawError("actor must name one declared PersonRef input")
    definitions = {} if library is None else dict(library.definitions)
    if set(definitions) & {name for name, _ in specs}:
        raise C0LawError("expression input conflicts with a pure definition")
    source = ExpressionSource(text, path, span)
    relation_names = set() if entities is None else set(dict(entities.relations))
    if relation_names & ({name for name, _ in specs} | set(definitions) | _INTRINSICS):
        raise C0LawError("relation name conflicts with an expression symbol")
    compiler = _Compiler(table, source, limits, definitions, entities, local_views)
    environment = {
        name: ValueExpression(
            "variable",
            table[spec.type_name],
            operand=name,
            path=ValueRead(name),
            reads=(ValueRead(name),),
            flow_path=("input", name),
        )
        for name, spec in specs
    }
    node = compiler.check(
        parse_expression(text, path=path, span=span, limits=limits), environment, result_type
    )
    if result_type is None:
        result_type = table.expression_type(node.value_type)
    for read in node.reads:
        spec = dict(specs)[read.root]
        if (
            context == "actor"
            and spec.exposure == "world"
            or spec.readable is not None
            and not any(read.steps[: len(allowed)] == allowed for allowed in spec.readable)
        ):
            source.fail(
                "InformationBoundary",
                node.offset,
                "permitted input path",
                read.root + "." + ".".join(read.steps),
            )
    summary = ExprSummary(
        result_type.type_id,
        node.reads,
        context,
        node.dependencies,
        _unique(dict(specs)[read.root].exposure for read in node.reads),
        node.owner_reads,
        node.reference_domains,
    )
    for read in node.owner_reads:
        if not entities.permitted(read, context=context, actor=actor):
            source.fail(
                "InformationBoundary",
                node.offset,
                "permitted entity field path",
                read.sort + "." + read.field,
            )
    key = hashlib.sha256(
        json.dumps(
            (
                text,
                [(name, value.type_id.signature) for name, value in table.definitions],
                [(name, spec.type_name, spec.exposure, spec.readable) for name, spec in specs],
                returns,
                context,
                actor,
                None if entities is None else entities.fingerprint,
                [(name, view.kind, view.type_name, view.channel) for name, view in local_views],
                [
                    (
                        name,
                        definition.source.text,
                        tuple(
                            (key, value.type_id.signature) for key, value in definition.parameters
                        ),
                        definition.returns.type_id.signature,
                    )
                    for name, definition in definitions.items()
                ],
            ),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return CheckedValueExpression(
        table, specs, node, result_type, summary, source, limits, entities, actor, key
    )


@dataclass(frozen=True)
class PureValueLibrary:
    table: TypeTable
    definitions: tuple[tuple[str, PureValueDefinition], ...]
    entities: EntityReadLibrary | None = None


def compile_pure_values(
    table,
    declarations,
    *,
    limits=ExpressionLimits(),
    context=None,
    entities=None,
    base_library=None,
    definition_paths=None,
):
    if (
        type(table) is not TypeTable
        or not isinstance(declarations, Mapping)
        or type(limits) is not ExpressionLimits
        or context is not None
        and type(context) is not C0SourceContext
    ):
        raise C0LawError("pure value definitions need a type table and named declarations")
    if len(declarations) > limits.nodes:
        raise C0LawError("pure declaration node budget exceeded")
    if entities is not None and (
        type(entities) is not EntityReadLibrary or entities.table is not table
    ):
        raise C0LawError("pure entity library differs from its type table")
    if base_library is not None and (
        type(base_library) is not PureValueLibrary
        or base_library.table is not table
        or base_library.entities is not entities
    ):
        raise C0LawError("pure base library must use the exact type and entity table")
    inherited = {} if base_library is None else dict(base_library.definitions)
    if set(declarations) & set(inherited):
        raise C0LawError("pure definitions cannot replace an inherited definition")
    parsed = {}
    for name, row in declarations.items():
        if not _identifier(name) or name in dict(table.definitions) or name in _INTRINSICS:
            raise C0LawError("pure definition conflicts with a reserved symbol")
        if not isinstance(row, Mapping) or set(row) != {"parameters", "returns", "expression"}:
            raise C0LawError("pure definition requires parameters, returns and expression")
        specs = _bindings(table, row["parameters"])
        if entities is not None and set(dict(entities.relations)) & (
            {key for key, _ in specs} | {name}
        ):
            raise C0LawError("relation name conflicts with a pure parameter/definition")
        if any(spec.readable is not None or spec.exposure != "actor" for _, spec in specs):
            raise C0LawError("pure parameters declare value types, not caller permissions")
        if row["returns"] not in dict(table.definitions):
            raise C0LawError("pure definition has an unknown result type")
        path = (definition_paths or {}).get(name, "queries." + name + ".expression")
        span = None if context is None else context.locate(path)
        parsed[name] = (
            row,
            specs,
            parse_expression(row["expression"], path=path, span=span, limits=limits),
        )
    built, pending = dict(inherited), set()
    nodes = 0

    def calls(syntax):
        stack = [syntax]
        while stack:
            current = stack.pop()
            if current.operation == "call" and current.children[0].operation == "name":
                yield current.children[0].value
            stack.extend(current.children)

    def build(name):
        nonlocal nodes
        if name in pending or len(pending) >= limits.depth:
            raise C0LawError("recursive pure definition or call depth exceeded: " + name)
        if name in built:
            return built[name]
        pending.add(name)
        row, specs, syntax = parsed[name]
        called_names = tuple(calls(syntax))
        for called in called_names:
            if called in parsed:
                build(called)
        if (set(parsed) | set(inherited)) & {key for key, _ in specs}:
            raise C0LawError("pure parameter conflicts with a definition: " + name)
        path = (definition_paths or {}).get(name, "queries." + name + ".expression")
        source = ExpressionSource(
            row["expression"], path, None if context is None else context.locate(path)
        )
        call_depth = 1 + max(
            (built[called].call_depth for called in called_names if called in built), default=0
        )
        if call_depth > limits.depth:
            source.fail("ExpressionBudget", 0, "bounded pure call graph", "depth limit")
        compiler = _Compiler(table, source, limits, built, entities)
        environment = {
            key: ValueExpression(
                "variable",
                table[spec.type_name],
                operand=key,
                path=ValueRead(key),
                reads=(ValueRead(key),),
                flow_path=("input", key),
            )
            for key, spec in specs
        }
        body = compiler.check(syntax, environment, table[row["returns"]])
        nodes += compiler.nodes
        if nodes > limits.nodes:
            source.fail("ExpressionBudget", 0, "bounded total pure definitions", "node limit")
        built[name] = PureValueDefinition(
            name,
            tuple((key, table[spec.type_name]) for key, spec in specs),
            table[row["returns"]],
            body,
            source,
            call_depth,
        )
        pending.remove(name)
        return built[name]

    for name in parsed:
        build(name)
    return PureValueLibrary(table, tuple(sorted(built.items())), entities)
