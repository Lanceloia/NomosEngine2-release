"""Check typed, finite value-construction recipes for detached planning models."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier
from .expressions import _INTRINSICS, compile_value_expression
from .frontend import row


@dataclass(frozen=True)
class ConstructionPlan:
    type_name: str
    kind: str
    expressions: tuple = ()
    children: tuple = ()
    prefix: str | None = None


def compile_construction(program, type_name, body, bindings, *, path):
    table = program.table
    kind = table[type_name]
    if type(body) is not dict:
        raise C0LawError(f"{path}: construction needs a typed recipe")
    forms = set(body) & {"choose", "value", "fields", "cases", "sequence", "set", "subset"}
    if len(forms) != 1:
        raise C0LawError(f"{path}: construction needs one recipe form")
    form = next(iter(forms))
    row(body, {form}, {"when", "min", "max"} if form == "subset" else {"when"}, path=path)
    expressions = []

    def expression(label, text, returns):
        if type(text) is int:
            text = str(text)
        checked = compile_value_expression(
            text,
            table,
            bindings,
            returns=returns,
            library=program.queries,
            entities=program.entities,
            context="actor",
            path=path + "." + label,
        )
        if checked.summary.owner_reads or checked.summary.reference_domains:
            raise C0LawError(f"{path}: construction accepts supplied local values only")
        expressions.append((label, checked))

    if "when" in body:
        expression("when", body["when"], "Bool")
    children, prefix = [], None
    if form in {"choose", "value"}:
        expected = table.collection(type_name).name if form == "choose" else type_name
        expression(form, body[form], expected)
    elif form == "subset":
        if kind.kind != "set" or not {"min", "max"} <= set(body):
            raise C0LawError(f"{path}: subset construction needs a set and both bounds")
        expression("pool", body[form], table.collection(kind.element.name).name)
        for label in ("min", "max"):
            expression(label, body[label], "Integer<>")
    elif form in {"fields", "cases"}:
        expected = "record" if form == "fields" else "variant"
        entries = dict(kind.fields if form == "fields" else kind.cases)
        supplied = body[form]
        if (
            kind.kind != expected
            or type(supplied) is not dict
            or (
                set(supplied) != set(entries)
                if form == "fields"
                else not supplied or set(supplied) - set(entries)
            )
        ):
            raise C0LawError(f"{path}: construction must match declared {expected} fields/cases")
        scope = dict(bindings)
        for name, child in supplied.items():
            if form == "fields" and name in scope:
                raise C0LawError(f"{path}: construction field shadows an enclosing binding: {name}")
            children.append(
                (
                    name,
                    compile_construction(
                        program,
                        entries[name].name,
                        child,
                        scope,
                        path=path + "." + name,
                    ),
                )
            )
            if form == "fields":
                scope[name] = entries[name].name
    else:
        if kind.kind != form:
            raise C0LawError(f"{path}: collection construction has the wrong declared type")
        collection = body[form]
        row(collection, {"min", "max", "item"}, {"prefix"}, path=path + "." + form)
        for label in ("min", "max"):
            expression(label, collection[label], "Integer<>")
        scope = dict(bindings)
        if "prefix" in collection:
            prefix = collection["prefix"]
            reserved = set(scope) | set(dict(table.definitions)) | _INTRINSICS
            reserved |= set(dict(program.queries.definitions)) | {"state"}
            if not _identifier(prefix) or prefix in reserved:
                raise C0LawError(f"{path}: construction prefix shadows a model binding")
            scope[prefix] = type_name
        children.append(
            (
                "item",
                compile_construction(
                    program,
                    kind.element.name,
                    collection["item"],
                    scope,
                    path=path + ".item",
                ),
            )
        )
    return ConstructionPlan(type_name, form, tuple(expressions), tuple(children), prefix)
