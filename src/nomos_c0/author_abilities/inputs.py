"""Entry-time named inputs, dependent domains and bounded construction protocols."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import C0SourceContext, C0SourceSpan

from .expression_syntax import _identifier, parse_expression
from .expressions import _INTRINSICS, CheckedValueExpression, ValueInput, compile_value_expression
from .value_types import TypeTable


@dataclass(frozen=True)
class InputDiagnostic:
    code: str
    path: str
    expected: str
    actual: str
    stage: str = "Compile"
    span: C0SourceSpan | None = None


class InputError(C0LawError):
    def __init__(self, code, path, expected, actual, *, stage="Compile", span=None):
        self.diagnostic = InputDiagnostic(code, path, expected, actual, stage, span)
        location = path if span is None else f"{span.file}:{span.line}:{span.column} ({path})"
        super().__init__(f"{code}: {location}: {expected}; {actual}")


def _free_names(syntax, bound=frozenset()):
    if syntax.operation == "name":
        return set() if syntax.value in bound else {syntax.value}
    if syntax.operation == "lambda":
        return _free_names(syntax.children[0], bound | {syntax.value})
    if syntax.operation == "match":
        names = _free_names(syntax.children[0], bound)
        for case in syntax.children[1:]:
            binder = case.value[1]
            names |= _free_names(case.children[0], bound if binder is None else bound | {binder})
        return names
    return set().union(*(_free_names(child, bound) for child in syntax.children))


@dataclass(frozen=True)
class InputDef:
    name: str
    type_name: str
    kind: str
    dependencies: tuple[str, ...]
    pool: CheckedValueExpression | None = None
    minimum: CheckedValueExpression | None = None
    maximum: CheckedValueExpression | None = None
    length: CheckedValueExpression | None = None
    repetition: str = "forbid"
    derive: CheckedValueExpression | None = None
    constraint: CheckedValueExpression | None = None


@dataclass(frozen=True)
class InputPlan:
    table: TypeTable
    base: tuple[tuple[str, str], ...]
    inputs: tuple[InputDef, ...]
    order: tuple[str, ...]

    def definition(self, name):
        return next(item for item in self.inputs if item.name == name)


def compile_inputs(
    table,
    declarations,
    base,
    *,
    library=None,
    entities=None,
    actor=None,
    path="inputs",
    context=None,
    local_views=(),
):
    if context is not None and type(context) is not C0SourceContext:
        raise C0LawError("input source context is malformed")
    try:
        return _compile_inputs(
            table,
            declarations,
            base,
            library=library,
            entities=entities,
            actor=actor,
            path=path,
            context=context,
            local_views=local_views,
        )
    except InputError as error:
        diagnostic = error.diagnostic
        if context is None:
            raise
        raise InputError(
            diagnostic.code,
            diagnostic.path,
            diagnostic.expected,
            diagnostic.actual,
            stage=diagnostic.stage,
            span=context.locate(diagnostic.path),
        ) from None


def _compile_inputs(
    table, declarations, base, *, library, entities, actor, path, context, local_views
):
    if (
        type(table) is not TypeTable
        or not isinstance(declarations, Mapping)
        or not isinstance(base, Mapping)
    ):
        raise C0LawError("inputs require the common table and named bindings")
    reserved = set(dict(table.definitions)) | _INTRINSICS | set(dict(local_views))
    reserved |= set() if library is None else set(dict(library.definitions))
    entities = entities if entities is not None else None if library is None else library.entities
    reserved |= (
        set() if entities is None else set(dict(entities.relations)) | set(dict(entities.entities))
    )
    base = dict(base)
    if any(
        not _identifier(name)
        or name in reserved
        or type(type_name) is not str
        or type_name not in dict(table.definitions)
        for name, type_name in base.items()
    ):
        raise C0LawError("base input bindings are malformed")
    rows, specs = {}, dict(base)
    for name, row in declarations.items():
        if (
            not _identifier(name)
            or name in reserved
            or name in specs
            or not isinstance(row, Mapping)
        ):
            raise InputError("DuplicateName", path, "unambiguous named input", str(name))
        if (
            "type" not in row
            or type(row["type"]) is not str
            or row["type"] not in dict(table.definitions)
        ):
            raise InputError(
                "UnknownType", path + "." + name, "declared named type", str(row.get("type"))
            )
        if set(row) - {"type", "choose", "enter", "derive", "constraint", "sample", "at"}:
            raise InputError(
                "UnsupportedFeature", path + "." + name, "selected Entry input", "extra fields"
            )
        if row.get("at", "entry") != "entry" or row.get("sample", "actor") != "actor":
            raise InputError(
                "UnsupportedFeature",
                path + "." + name,
                "Entry actor sample",
                "decision point or world derive",
            )
        bindings = set(row) & {"choose", "enter", "derive"}
        if len(bindings) != 1 or "sample" in row and "derive" not in row:
            raise InputError(
                "MultipleBindings", path + "." + name, "exactly one binding", str(bindings)
            )
        specs[name] = row["type"]
        rows[name] = row
    built, graph = {}, {}
    for name, row in rows.items():
        location = path + "." + name
        parts = {}
        refs = set()

        def expression(label, text, returns, *, self_allowed=False):
            if type(text) is int:
                text = str(text)
            if type(text) is not str:
                raise InputError(
                    "InvalidDomain",
                    location + "." + label,
                    "pure expression text",
                    type(text).__name__,
                )
            names = _free_names(parse_expression(text, path=location + "." + label)) - reserved
            if not self_allowed:
                refs.update(names & set(rows))
            bound_names = names & set(specs)
            return compile_value_expression(
                text,
                table,
                {key: ValueInput(specs[key]) for key in sorted(bound_names)},
                returns=returns,
                library=library,
                entities=entities,
                actor=actor if actor in bound_names else None,
                path=location + "." + label,
                span=None if context is None else context.locate(location + "." + label),
                local_views=local_views,
            )

        value_type = table[row["type"]]
        if "choose" in row:
            choice = row["choose"]
            if type(choice) is str:
                kind = "member"
                parts["pool"] = expression("choose", choice, table.collection(row["type"]).name)
            elif (
                isinstance(choice, Mapping)
                and set(choice) == {"subset", "min", "max"}
                and value_type.kind == "set"
            ):
                kind = "subset"
                parts["pool"] = expression(
                    "choose.subset",
                    choice["subset"],
                    table.collection(value_type.element.name).name,
                )
                parts["minimum"] = expression("choose.min", choice["min"], "Integer<>")
                parts["maximum"] = expression("choose.max", choice["max"], "Integer<>")
            elif (
                isinstance(choice, Mapping)
                and set(choice) == {"sequence", "length", "repetition"}
                and value_type.kind == "sequence"
                and choice["repetition"] in ("allow", "forbid")
            ):
                kind = "sequence"
                parts["pool"] = expression(
                    "choose.sequence",
                    choice["sequence"],
                    table.collection(value_type.element.name).name,
                )
                parts["length"] = expression("choose.length", choice["length"], "Integer<>")
                parts["repetition"] = choice["repetition"]
            else:
                raise InputError(
                    "InvalidDomain",
                    location,
                    "typed member/subset/sequence binding",
                    "wrong choice form",
                )
        elif "enter" in row:
            kind = "enter"
            if row["enter"] != "typed":
                raise InputError("InvalidDomain", location, "enter: typed", str(row["enter"]))
        else:
            kind = "derive"
            parts["derive"] = expression("derive", row["derive"], row["type"])
        if "constraint" in row:
            parts["constraint"] = expression(
                "constraint", row["constraint"], "Bool", self_allowed=True
            )
        graph[name] = tuple(sorted(refs))
        built[name] = InputDef(name, row["type"], kind, graph[name], **parts)
    order, pending = [], set()

    def visit(name):
        if name in pending:
            raise InputError("InputCycle", path + "." + name, "acyclic Entry dependencies", "cycle")
        if name in order:
            return
        pending.add(name)
        for dependency in graph[name]:
            visit(dependency)
        pending.remove(name)
        order.append(name)

    for name in sorted(rows):
        visit(name)
    return InputPlan(
        table, tuple(sorted(base.items())), tuple(built[name] for name in order), tuple(order)
    )
