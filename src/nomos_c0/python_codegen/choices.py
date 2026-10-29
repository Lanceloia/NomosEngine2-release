"""Generate local partial input construction without interpreting an InputPlan at Run."""

from dataclasses import replace

from .input_bindings import InputBindings


def needed(expression):
    names = {read.root for read in expression.summary.reads}
    if expression.actor is not None:
        names.add(expression.actor)
    return replace(expression, inputs=tuple(p for p in expression.inputs if p[0] in names))


def eligibility_function(emitter, prefix, plan, views):
    bindings = InputBindings(emitter)
    guard = needed(plan.where)
    names = tuple(name for name, _ in guard.inputs)
    lines = [
        *bindings.environment(plan, views, actor_only=True),
        f"if not set({names!r}) <= environment.keys(): return None",
        "return " + bindings.expression(guard),
    ]
    name = prefix + "_eligible"
    emitter.function(name, "session, actor, record", lines)
    return name


def choice_function(emitter, prefix, plan, views):
    bindings = InputBindings(emitter)
    lines = bindings.environment(plan, views, actor_only=True)
    chosen = tuple(item.name for item in plan.inputs.inputs if item.kind != "derive")
    lines.extend(
        [
            f"if type(choices) is not dict or set(choices) - set({chosen!r}): "
            "raise AdmissionError('MissingBinding', 'only declared chosen inputs allowed')",
            "fields = []",
        ]
    )
    guard = needed(plan.where)
    guard_names = tuple(name for name, _ in guard.inputs)
    guard_value = bindings.expression(guard)
    lines.append(f"_condition_known = set({guard_names!r}) <= environment.keys()")
    lines.append(
        f"if _condition_known and not {guard_value}: "
        "raise AdmissionError('NotAdmitted', 'Action condition is false')"
    )
    for item in plan.inputs.inputs:
        value = emitter.program.table[item.type_name]
        element = value.element if item.kind in ("subset", "sequence") else value
        descriptor = (
            f"InputField({item.name!r}, {item.type_name!r}, {element.name!r}, "
            f"{item.kind!r}, {item.dependencies!r}, "
        )
        lines.append(f"if not set({item.dependencies!r}) <= environment.keys():")
        lines.extend(
            [
                f"    if {item.name!r} in choices: "
                "raise AdmissionError('MissingBinding', 'bind input dependencies first')",
            ]
        )
        if item.kind != "derive":
            lines.append(
                "    fields.append(" + descriptor + f"False, repetition={item.repetition!r}))"
            )
        lines.append("else:")
        binding = bindings.bind(item)
        if item.kind == "derive":
            lines.extend("    " + line for line in binding)
        else:
            lines.append(f"    if {item.name!r} in choices:")
            lines.extend("        " + line for line in binding)
            lines.append("    else:")
            lines.extend("        " + line for line in bindings.domain(item))
            args = ", ".join(
                attr + "=_" + attr
                for attr in ("pool", "minimum", "maximum", "length")
                if getattr(item, attr) is not None
            )
            lines.append(
                "        fields.append("
                + descriptor
                + "True, "
                + args
                + (", " if args else "")
                + f"repetition={item.repetition!r}))"
            )
    for item in plan.inputs.inputs:
        if item.constraint is not None:
            constraint = needed(item.constraint)
            names = tuple(name for name, _ in constraint.inputs)
            lines.append(
                f"if set({names!r}) <= environment.keys() "
                f"and not {bindings.expression(constraint)}: "
                "raise AdmissionError('InvalidChoice', 'input constraint is false')"
            )
    lines.append(
        f"if not _condition_known and set({guard_names!r}) <= environment.keys() "
        f"and not {guard_value}: "
        "raise AdmissionError('NotAdmitted', 'Action condition is false')"
    )
    all_names = tuple(item.name for item in plan.inputs.inputs)
    lines.append(
        f"return ChoiceForm({plan.name!r}, tuple(fields), "
        f"tuple((name, environment[name]) for name in {all_names!r} if name in environment), "
        f"set({all_names!r}) <= environment.keys(), "
        f"not set({guard_names!r}) <= environment.keys())"
    )
    name = prefix + "_choices"
    emitter.function(name, "session, actor, choices, record", lines)
    return name
