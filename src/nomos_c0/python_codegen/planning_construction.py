"""Emit pure construction recipes, with nominal carriers from the checked type table."""

from dataclasses import replace


def carrier(emitter, kind):
    scalar = {
        "bool": "bool",
        "unit": "type(None)",
        "int": "int",
        "text": "str",
        "enum": "str",
        "ref": "Reference",
        "set": "frozenset",
        "sequence": "tuple",
    }
    if kind.kind in scalar:
        return scalar[kind.kind]
    if kind.kind == "record":
        return f"RECORDS[{kind.name!r}]"
    children = [child for _, child in kind.cases] if kind.kind == "variant" else [kind.element]
    parts = [carrier(emitter, child) for child in children]
    if kind.kind == "optional":
        parts.append("type(None)")
    return (
        "tuple(t for group in (" + ", ".join(parts) + ",) "
        "for t in (group if type(group) is tuple else (group,)))"
    )


def emit_prepared_expression(emitter, checked, name, *, members=False):
    roots = {read.root for read in checked.summary.reads}
    # The controller identity check is required even in a constant body.
    if checked.actor is not None:
        roots.add(checked.actor)
    checked = replace(checked, inputs=tuple(p for p in checked.inputs if p[0] in roots))
    inputs = tuple(name for name, _ in checked.inputs)
    emitter.function(
        name,
        "reads, value_limits, environment, work",
        [
            "return "
            + emitter.expression(
                checked, reads="reads", limits="value_limits", logical_work="work"
            )
        ],
    )
    return f"ConstructionExpression({name}, {inputs!r}, {members!r})"


def emit_construction(emitter, plan, prefix):
    expressions = []
    for label, checked in plan.expressions:
        members = label in {"choose", "pool"}
        descriptor = emit_prepared_expression(
            emitter, checked, prefix + "_" + label, members=members
        )
        expressions.append(f"({label!r}, {descriptor})")
    children = []
    for index, (name, child) in enumerate(plan.children):
        children.append(
            f"({name!r}, {emit_construction(emitter, child, prefix + '_' + str(index))})"
        )
    make = "None"
    if plan.kind == "fields":
        kind = emitter.program.table[plan.type_name]
        make = prefix + "_make"
        arguments = ", ".join(f"fields[{name!r}]" for name, _ in kind.fields)
        emitter.function(make, "fields", [f"return {carrier(emitter, kind)}({arguments})"])
    return (
        f"Construction({plan.kind!r}, ({', '.join(expressions)}{',' if expressions else ''}), "
        f"({', '.join(children)}{',' if children else ''}), {make}, {plan.prefix!r})"
    )
