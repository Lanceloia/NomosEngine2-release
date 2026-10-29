"""Emit producer checks; only public content arguments survive in acquired evidence."""


def public_arguments(arguments):
    entries = [
        f"({name!r}, {expr.result.name!r}, {expr.result.type_id.signature!r}, parameters[{name!r}])"
        for name, expr in arguments
    ]
    return "(" + ", ".join(entries) + ("," if entries else "") + ")"


def constraint_checker(emitter, definition):
    if definition.signature in emitter.constraint_functions:
        return emitter.constraint_functions[definition.signature]
    name = "_constraint_check_" + str(len(emitter.constraint_functions))
    emitter.constraint_functions[definition.signature] = name
    lines = [
        "realized = {"
        + ", ".join(
            f"{key!r}: {emitter.expression(expr, reads='reads', limits='value_limits')}"
            for key, expr in definition.realization
        )
        + "}",
        "environment = {**environment, **realized}",
        f"if not {emitter.expression(definition.holds, reads='reads', limits='value_limits')}:",
        f"    raise InformationViolation('ConstraintViolation', {definition.name!r})",
    ]
    if definition.local is not None:
        check = emitter.expression(definition.local.check, reads="reads", limits="value_limits")
        lines.extend(
            [
                f"if not {check}:",
                f"    raise InformationViolation('ConstraintViolation', {definition.name!r})",
            ]
        )
    emitter.function(name, "environment, reads, value_limits", lines)
    return name


def certification(emitter, plan):
    name = "_certify_" + str(emitter.certification_count)
    emitter.certification_count += 1
    lines = ["environment = {'content': content}", "claims, constraints = [], []"]
    for assurance in plan.assurances:
        args = ", ".join(
            f"{key!r}: {emitter.expression(expr, reads='reads', limits='value_limits')}"
            for key, expr in assurance.arguments
        )
        predicate = emitter.expression(
            assurance.predicate, environment="parameters", reads="reads", limits="value_limits"
        )
        lines.extend(
            [
                f"parameters = {{{args}}}",
                f"if not {predicate}:",
                f"    raise InformationViolation('AssuranceViolation', {assurance.fact!r})",
                f"claims.append(CheckedFact({assurance.fact!r}, {assurance.predicate.read_key!r}, "
                f"{public_arguments(assurance.arguments)}))",
            ]
        )
    for assurance in plan.constraints:
        definition = assurance.definition
        checker = constraint_checker(emitter, definition)
        args = ", ".join(
            f"{key!r}: {emitter.expression(expr, reads='reads', limits='value_limits')}"
            for key, expr in assurance.arguments
        )
        lines.extend(
            [
                f"parameters = {{{args}}}",
                f"{checker}(parameters, reads, value_limits)",
                f"constraints.append(CheckedConstraint({definition.name!r}, "
                f"{definition.signature!r}, "
                f"{definition.variables!r}, {definition.formula!r}, "
                f"{public_arguments(assurance.arguments)}))",
            ]
        )
    lines.append("return tuple(claims), tuple(constraints)")
    emitter.function(name, "content, reads, value_limits", lines)
    return name
