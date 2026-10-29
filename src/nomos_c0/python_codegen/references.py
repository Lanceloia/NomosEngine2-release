"""Generate identity projection from already validated value shapes."""

from .syntax import statements


def emit_reference_reader(values, plan):
    """Extract identities from already validated nominal values, without runtime IR."""
    lines = []
    if plan.kind == "ref":
        lines = ["return frozenset((value,))"]
    elif plan.kind != "variant" and not plan.has_references:
        lines = ["return frozenset()"]
    elif plan.kind == "optional":
        lines = [
            "return frozenset() if value is None else "
            f"{values.reference_reader(plan.element)}(value)"
        ]
    elif plan.kind in {"set", "sequence"}:
        if plan.element.kind == "ref":
            lines = ["return frozenset(value)"]
        else:
            lines = [
                "result = set()",
                "for item in value:",
                f"    result.update({values.reference_reader(plan.element)}(item))",
                "return frozenset(result)",
            ]
    elif plan.kind == "record":
        lines = ["result = set()"]
        for name, child in plan.fields:
            if not child.has_references:
                continue
            value = f"value.{values.field(plan, name)}"
            if child.kind == "ref":
                lines.append(f"result.add({value})")
            elif child.kind in {"set", "sequence"} and child.element.kind == "ref":
                lines.append(f"result.update({value})")
            else:
                lines.append(f"result.update({values.reference_reader(child)}({value}))")
        lines.append("return frozenset(result)")
    elif plan.kind == "variant":
        for _, child in plan.cases:
            lines.extend(
                [
                    f"if type(value) is {values.carrier(child)}:",
                    f"    return {values.reference_reader(child)}(value)",
                ]
            )
        lines.append("raise ValueError('unvalidated variant in identity extraction')")
    else:
        lines = ["return frozenset()"]
    return statements(
        f"def {values.reference_reader(plan)}(value):\n"
        + "\n".join("    " + line for line in lines)
    )[0]
