"""Lower checked carrying reads and paid attempts into native Python branches."""

import ast

from .syntax import statements


def query(emitter, node, body, depth, *, environment, source, nested, roles):
    relation, operation = node.operand
    item = emitter.emit(
        node.children[0],
        body,
        depth + 1,
        environment=environment,
        source=source,
        nested=nested,
        roles=roles,
    )
    index = emitter.count
    emitter.count += 1
    target = f"_relation_item_{index}"
    holder = f"_relation_holder_{index}"
    result = f"_relation_value_{index}"
    body.append(emitter.assign(target, item))
    body.extend(
        statements(f"{holder} = reads.read({target}, {relation.item!r}, {relation.holder!r})")
    )
    if operation == "holder":
        body.extend(statements(f"{result} = {holder}"))
    elif operation == "held_by":
        person = emitter.emit(
            node.children[1],
            body,
            depth + 1,
            environment=environment,
            source=source,
            nested=nested,
            roles=roles,
        )
        body.append(
            emitter.assign(
                result,
                ast.Compare(
                    left=ast.Name(id=holder, ctx=ast.Load()),
                    ops=[ast.Eq()],
                    comparators=[person],
                ),
            )
        )
    else:
        body.extend(
            statements(
                f"if {holder} is None:\n"
                f"    {result} = reads.read({target}, {relation.item!r}, {relation.ground!r})\n"
                "else:\n"
                f"    {result} = reads.read({holder}, {relation.person!r}, {relation.position!r})"
            )
        )
    return ast.Name(id=result, ctx=ast.Load())


def attempt(emitter, effect, *, index):
    plan, operation = effect.relation, effect.operation
    names = [f"_relation_arg_{index}_{i}" for i in range(len(effect.arguments))]
    lines = [
        f"draft.effect_step({effect.arguments[0].source.path!r})",
        *(f"{name} = {emitter.expression(arg)}" for name, arg in zip(names, effect.arguments)),
    ]
    item, person = names[:2]
    holder, success = f"_holder_{index}", f"_success_{index}"
    lines.append(f"{holder} = world_reads.read({item}, {plan.item!r}, {plan.holder!r})")
    if operation == "take":
        lines.append(
            f"{success} = {holder} is None and "
            f"world_reads.read({item}, {plan.item!r}, {plan.ground!r}) == "
            f"world_reads.read({person}, {plan.person!r}, {plan.position!r})"
        )
        updates = [f"set_field(draft, {plan.name!r}, {item}, {plan.holder!r}, {person})"]
    elif operation == "drop":
        lines.append(f"{success} = {holder} == {person}")
        updates = [
            f"set_field(draft, {plan.name!r}, {item}, {plan.holder!r}, None)",
            f"set_field(draft, {plan.name!r}, {item}, {plan.ground!r}, "
            f"world_reads.read({person}, {plan.person!r}, {plan.position!r}))",
        ]
    else:
        recipient = names[2]
        lines.append(
            f"{success} = {holder} == {person} and {person} != {recipient} and "
            f"world_reads.read({person}, {plan.person!r}, {plan.position!r}) == "
            f"world_reads.read({recipient}, {plan.person!r}, {plan.position!r})"
        )
        if operation == "offer":
            updates = [
                f"set_proposal(draft, {plan.name!r}, {item}, "
                f"CarryOffer({person}, {recipient}, draft.occurrence))"
            ]
        else:
            offer = f"_offer_{index}"
            lines.extend(
                [
                    f"{offer} = proposal(draft, {plan.name!r}, {item})",
                    f"{success} = {success} and {offer} is not None and "
                    f"{offer}.giver == {person} and {offer}.recipient == {recipient}",
                ]
            )
            updates = [
                f"set_field(draft, {plan.name!r}, {item}, {plan.holder!r}, {recipient})",
                f"draft.supports.append({offer}.source)",
            ]
    if operation != "offer":
        updates.append(f"set_proposal(draft, {plan.name!r}, {item}, None)")
    lines.extend([f"if {success}:", *("    " + line for line in updates)])
    return lines, success
