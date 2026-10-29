"""Generate nominal term codecs for pure cognition algorithms, not runtime type IR."""

from .syntax import statements


def term_codecs(types):
    functions, entries = [], []
    for plan in types.plans.values():
        index = types.index(plan)

        def pack(child, value):
            return f"_term_pack_{types.index(child)}({value})"

        def unpack(child, value):
            return f"_term_unpack_{types.index(child)}({value})"

        kind = plan.kind
        before, after = [], []
        if kind in {"unit", "bool", "int", "text", "enum"}:
            before, after = ["return value"], ["return wire"]
        elif kind == "ref":
            before = ["return value.scope, value.ordinal, value.sort"]
            after = ["return Reference(*wire)"]
        elif kind == "optional":
            before = [
                f"return (False,) if value is None else (True, {pack(plan.element, 'value')})"
            ]
            after = [
                "if type(wire) is tuple and len(wire) == 1 and wire[0] is False: return None",
                "if type(wire) is not tuple or len(wire) != 2 or wire[0] is not True: "
                "raise ValueError('invalid optional term')",
                f"return {unpack(plan.element, 'wire[1]')}",
            ]
        elif kind == "record":
            before = [
                "return ("
                + ", ".join(pack(child, f"value.{name}") for name, child in plan.fields)
                + ("," if plan.fields else "")
                + ")"
            ]
            after = [
                f"if type(wire) is not tuple or len(wire) != {len(plan.fields)}: "
                "raise ValueError('invalid record term')",
                f"return {types.carrier(plan)}("
                + ", ".join(unpack(child, f"wire[{i}]") for i, (_, child) in enumerate(plan.fields))
                + ")",
            ]
        elif kind == "variant":
            after = [
                "if type(wire) is not tuple or len(wire) != 2: "
                "raise ValueError('invalid variant term')"
            ]
            for tag, child in plan.cases:
                before.append(
                    f"if type(value) is {types.carrier(child)}: "
                    f"return {tag!r}, {pack(child, 'value')}"
                )
                after.append(f"if wire[0] == {tag!r}: return {unpack(child, 'wire[1]')}")
            before.append("raise ValueError('foreign variant term')")
            after.append("raise ValueError('unknown variant term')")
        else:
            before = [f"values = tuple({pack(plan.element, 'item')} for item in value)"]
            before.append(
                "return tuple(sorted(values, key=lambda item: json.dumps(item, ensure_ascii=True)))"
                if kind == "set"
                else "return values"
            )
            after = [
                "if type(wire) is not tuple: raise ValueError('invalid collection term')",
                f"values = tuple({unpack(plan.element, 'item')} for item in wire)",
            ]
            if kind == "set":
                after.extend(
                    [
                        "if len(frozenset(values)) != len(values): "
                        "raise ValueError('duplicate set term')",
                        "return frozenset(values)",
                    ]
                )
            else:
                after.append("return values")
        for name, argument, lines in (
            (f"_term_pack_{index}", "value", before),
            (f"_term_unpack_{index}", "wire", after),
        ):
            functions.extend(
                statements(
                    f"def {name}({argument}):\n" + "\n".join("    " + line for line in lines)
                )
            )
    bindings = {plan.name: plan for plan in types.plans.values()}
    bindings.update((name, types.plans[key]) for name, key in types.names.items())
    for name, plan in bindings.items():
        index = types.index(plan)
        entries.append(
            f"{name!r}: ({plan.type_id.signature!r}, _term_pack_{index}, "
            f"_term_unpack_{index}, {types.validator(plan)})"
        )
    return functions, "{" + ", ".join(entries) + "}"
