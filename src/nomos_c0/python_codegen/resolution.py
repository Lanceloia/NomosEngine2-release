"""Generate checked resolution trees, grouped effects and transactional disclosure requests."""

from nomos_c0.author_abilities.effects import ContextEffect, FieldEffect, ForEffect
from nomos_c0.author_contract_v1 import C0LawError

from .carrying import attempt


def unsupported(message):
    raise C0LawError("Python world generation does not yet support " + message)


def check_effects(effects, *, costs=False):
    for effect in effects:
        if type(effect) is ForEffect and not costs:
            check_effects(effect.effects)
        elif type(effect) is ContextEffect and not costs:
            continue
        elif type(effect) is not FieldEffect:
            unsupported("non-field effects")
        elif costs and effect.target.node.operation != "variable":
            unsupported("computed resource-cost targets")
        elif effect.operation != ("consume" if costs else "set"):
            unsupported("field operation " + effect.operation)


def write_targets(world, plan):
    lines = ["targets = set()"]
    leaves = plan.resolution.leaves()
    direct = (
        tuple(effect for effect in leaves[0].effects if type(effect) is FieldEffect)
        if len(leaves) == 1
        else ()
    )
    local_names = {name for name, _ in plan.inputs.base} | {
        item.name for item in plan.inputs.inputs
    }
    if any(not {name for name, _ in effect.target.inputs} <= local_names for effect in direct):
        direct = ()
    for effect in (*plan.costs, *direct):
        lines.extend(
            [
                f"key = ({world.expression(effect.target)}, {effect.field!r})",
                "if key in targets: "
                "raise AdmissionError('AliasedWrite', 'effects select the same actual field')",
                "targets.add(key)",
            ]
        )
    return lines


class ResolutionEmitter:
    """Own module-local temporary numbering and the shared disclosure definition registry."""

    def __init__(self):
        self.disclosures = {}
        self._group_count = 0

    def next_group(self):
        index = self._group_count
        self._group_count += 1
        return index

    def _effect(self, world, effect, environment, context):
        if type(effect) is ContextEffect:
            return [
                f"draft.effect_step({effect.value.source.path!r})",
                f"draft.set_context({context.name!r}, {effect.field!r}, "
                f"{world.expression(effect.value, environment)})",
            ]
        if type(effect) is FieldEffect:
            return [
                f"draft.effect_step({effect.value.source.path!r})",
                f"draft.set({world.expression(effect.target, environment)}, {effect.field!r}, "
                f"{world.expression(effect.value, environment)})",
            ]
        index = self.next_group()
        pool, item, local = f"_pool_{index}", f"_item_{index}", f"_local_{index}"
        body = [
            f"draft.effect_step({effect.pool.source.path!r})",
            f"{local} = {{**{environment}, {effect.variable!r}: {item}}}",
        ]
        for child in effect.effects:
            body.extend(self._effect(world, child, local, context))
        return [
            "draft.effect_step('effects')",
            f"{pool} = {world.expression(effect.pool, environment)}",
            f"for {item} in {pool}:",
            *("    " + line for line in body),
        ]

    def emit(self, world, plan, node=None):
        node = plan.resolution if node is None else node
        if node.draws:
            return self._draws(world, plan, node)
        if node.result is None:
            return self._branch(world, plan, node)
        return self._leaf(world, plan, node)

    def _draws(self, world, plan, node):
        lines = []
        for slot in node.draws:
            expression = slot.pool if slot.pool is not None else slot.sides
            stream = "'main'" if slot.stream is None else world.expression(slot.stream)
            method = "shuffle" if slot.pool is not None else "sample"
            work = "max(1, len(_draw_input) - 1)" if slot.pool is not None else "1"
            lines.extend(
                [
                    f"_draw_input = {world.expression(expression)}",
                    f"draft.random_steps({expression.source.path!r}, {work})",
                    f"environment[{slot.name!r}] = _VALIDATORS[{slot.type_name!r}]("
                    f"draft.random.{method}({expression.source.path!r}, "
                    f"_draw_input, {stream}), "
                    "ValueBudget(session.limits.value, world_reads.references), ())",
                ]
            )
        return [*lines, *self.emit(world, plan, node.then)]

    def _branch(self, world, plan, node):
        prefix, condition = (
            attempt(world, node.attempt, index=self.next_group())
            if node.attempt is not None
            else ([], world.expression(node.condition))
        )
        return [
            *prefix,
            f"if {condition}:",
            *("    " + line for line in self.emit(world, plan, node.then)),
            "else:",
            *("    " + line for line in self.emit(world, plan, node.otherwise)),
        ]

    def _leaf(self, world, plan, node):
        lines = [
            line
            for effect in node.effects
            for line in self._effect(world, effect, "environment", plan.context)
        ]
        lines.append("draft.result = " + world.expression(node.result))
        if node.forms:
            lines.append(f"draft.check_form_count({len(node.forms)})")
            products = []
            for product in node.forms:
                fields = ", ".join(
                    f"{field!r}: {world.expression(value)}" for field, value in product.fields
                )
                products.append(f"({product.schema.name!r}, {{{fields}}})")
            lines.append(f"draft.form(({', '.join(products)},))")
        if node.next_point is not None:
            lines.append(f"draft.next_point = {node.next_point!r}")
        return [*lines, *self._deliveries(world, plan, node.deliveries)]

    def _deliveries(self, world, plan, calls):
        lines = []
        for call in calls:
            key = id(call.definition)
            if key not in self.disclosures:
                self.disclosures[key] = (
                    "_disclosure_" + str(len(self.disclosures)),
                    call.definition,
                )
            projector, definition = self.disclosures[key]
            local = "environment"
            if call.pool is not None:
                index = self.next_group()
                item, local = f"_delivery_item_{index}", f"_delivery_environment_{index}"
                pool = world.expression(call.pool)
                if call.pool.result.kind == "set":
                    pool = f"sorted({pool}, key=_delivery_order)"
                lines.extend(
                    [
                        f"for {item} in {pool}:",
                        f"    draft.effect_step({call.pool.source.path!r})",
                        f"    {local} = {{**environment, {call.variable!r}: {item}}}",
                    ]
                )
            args = ", ".join(world.expression(argument, local) for argument in call.arguments)
            line = (
                f"draft.deliveries.append(Delivery({(plan.channel_name + '.' + call.label)!r}, "
                f"{definition.sample!r}, {projector}, ({args}{',' if args else ''}), "
                f"{definition.value.result.name!r}))"
            )
            lines.append(("    " if call.pool is not None else "") + line)
        return lines
