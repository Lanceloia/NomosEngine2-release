"""Typed field/resource effects and resolutions share the common expression compiler."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .entity_reads import CarryingRead, EntityReadLibrary
from .expression_syntax import ExpressionSource, _identifier, parse_expression
from .expressions import _INTRINSICS, CheckedValueExpression, ValueRead, compile_value_expression


@dataclass(frozen=True)
class FieldWrite:
    sort: str
    field: str
    selector: ValueRead | None


@dataclass(frozen=True)
class FieldEffect:
    operation: str
    target: CheckedValueExpression
    field: str
    value: CheckedValueExpression

    @property
    def write(self):
        return FieldWrite(self.target.result.sort, self.field, self.target.node.path)

    def expressions(self):
        return self.target, self.value


@dataclass(frozen=True)
class ContextEffect:
    field: str
    value: CheckedValueExpression

    def expressions(self):
        return (self.value,)


@dataclass(frozen=True)
class ForEffect:
    variable: str
    pool: CheckedValueExpression
    effects: tuple

    def expressions(self):
        return (self.pool, *(expr for child in self.effects for expr in child.expressions()))


def field_effects(effects):
    for effect in effects:
        if type(effect) is ForEffect:
            yield from field_effects(effect.effects)
        else:
            yield effect


@dataclass(frozen=True)
class RelationEffect:
    relation: CarryingRead
    operation: str
    arguments: tuple[CheckedValueExpression, ...]


@dataclass(frozen=True)
class DrawSlot:
    name: str
    type_name: str
    sides: CheckedValueExpression | None
    stream: CheckedValueExpression | None = None
    pool: CheckedValueExpression | None = None


@dataclass(frozen=True)
class ResolutionPlan:
    result: CheckedValueExpression | None = None
    effects: tuple[FieldEffect | ContextEffect | ForEffect, ...] = ()
    condition: CheckedValueExpression | None = None
    attempt: RelationEffect | None = None
    then: ResolutionPlan | None = None
    otherwise: ResolutionPlan | None = None
    deliveries: tuple = ()
    next_point: str | None = None
    draws: tuple[DrawSlot, ...] = ()
    forms: tuple = ()

    def walk(self):
        yield self
        if self.result is None:
            yield from self.then.walk()
            if self.otherwise is not None:
                yield from self.otherwise.walk()

    def leaves(self):
        if self.result is not None:
            return (self,)
        return tuple(node for node in self.walk() if node.result is not None)

    def expressions(self):
        if self.result is not None:
            return (
                self.result,
                *(expression for effect in self.effects for expression in effect.expressions()),
                *(expression for form in self.forms for expression in form.expressions()),
            )
        prefix = (
            tuple(
                expr
                for slot in self.draws
                for expr in (
                    slot.pool if slot.pool is not None else slot.sides,
                    *(() if slot.stream is None else (slot.stream,)),
                )
            )
            if self.draws
            else (self.condition,)
            if self.condition is not None
            else self.attempt.arguments
        )
        return (
            *prefix,
            *self.then.expressions(),
            *(() if self.otherwise is None else self.otherwise.expressions()),
        )


@dataclass(frozen=True)
class EffectSummary:
    writes: tuple[FieldWrite, ...]
    expressions: tuple[CheckedValueExpression, ...]
    relations: tuple[RelationEffect, ...]
    context_writes: tuple[str, ...] = ()


class EffectCompiler:
    def __init__(
        self,
        table,
        bindings,
        *,
        library,
        entities,
        actor,
        path="ability",
        context=None,
        local_views=(),
        disclosures=(),
        actor_bindings=None,
        successors=None,
        shared_context=None,
        effect_depth=0,
    ):
        if (
            type(entities) is not EntityReadLibrary
            or entities.table is not table
            or actor is not None
            and actor not in bindings
        ):
            raise C0LawError(
                "effects need their compiled entity table and declared actor parameter"
            )
        self.table, self.bindings = table, dict(bindings)
        self.library, self.entities, self.actor, self.path = library, entities, actor, path
        self.context = context
        self.local_views, self.disclosures = local_views, dict(disclosures)
        self.actor_bindings = self.bindings if actor_bindings is None else dict(actor_bindings)
        self.successors = successors
        self.shared_context = shared_context
        self.effect_depth = effect_depth
        if actor is not None:
            actor_type = table[bindings[actor]]
            if (
                actor_type.kind != "ref"
                or dict(entities.entities)[actor_type.sort].kind != "person"
            ):
                raise C0LawError("effect actor must be a declared Person reference")

    def expression(self, text, returns, path, *, context="world"):
        expression = compile_value_expression(
            text,
            self.table,
            self.actor_bindings if context == "actor" else self.bindings,
            returns=returns,
            library=self.library,
            entities=self.entities,
            actor=self.actor,
            context=context,
            path=path,
            span=None if self.context is None else self.context.locate(path),
            local_views=self.local_views,
        )
        needed = {read.root for read in expression.summary.reads}
        if self.actor is not None:
            needed.add(self.actor)
        return replace(
            expression, inputs=tuple(item for item in expression.inputs if item[0] in needed)
        )

    def fields(self, rows, *, costs=False, path=None):
        if costs and self.actor is None:
            raise C0LawError("automatic effects cannot consume a controlling Actor resource")
        path = path or self.path + (".cost" if costs else ".effects")
        if type(rows) is not list:
            raise C0LawError(f"{path}: effects require an ordered declaration list")
        if self.effect_depth > 64:
            raise C0LawError(f"{path}: effect nesting exceeds its compilation depth")
        result = []
        for index, text in enumerate(rows):
            location = f"{path}[{index}]"
            if isinstance(text, Mapping):
                if costs or set(text) != {"for", "in", "effects"}:
                    raise C0LawError(f"{location}: finite groups require World for/in/effects")
                variable = text["for"]
                reserved = (
                    set(self.bindings)
                    | set(dict(self.table.definitions))
                    | set(dict(self.library.definitions))
                    | set(dict(self.entities.relations))
                    | set(dict(self.local_views))
                    | _INTRINSICS
                )
                if not _identifier(variable) or variable in reserved:
                    raise C0LawError(f"{location}: group binder conflicts with its lexical scope")
                pool = self.expression(text["in"], None, location + ".in")
                if pool.result.kind not in ("set", "sequence"):
                    raise C0LawError(f"{location}: group requires a finite Set or Sequence")
                nested = EffectCompiler(
                    self.table,
                    {**self.bindings, variable: pool.result.element.name},
                    library=self.library,
                    entities=self.entities,
                    actor=self.actor,
                    path=self.path,
                    context=self.context,
                    local_views=self.local_views,
                    disclosures=self.disclosures.items(),
                    actor_bindings=self.actor_bindings,
                    successors=self.successors,
                    shared_context=self.shared_context,
                    effect_depth=self.effect_depth + 1,
                ).fields(text["effects"], path=location + ".effects")
                if any(type(effect) is ContextEffect for effect in field_effects(nested)):
                    raise C0LawError(
                        f"{location}: shared aggregate assignments belong outside a group"
                    )
                result.append(ForEffect(variable, pool, nested))
                continue
            syntax = parse_expression(text, path=location)
            expected = "consume" if costs else "set"
            if (
                syntax.operation != "call"
                or syntax.children[0].operation != "name"
                or syntax.children[0].value != expected
                or len(syntax.children) != 3
            ):
                raise C0LawError(f"{location}: expected {expected}(entity.field, value)")
            target, value = syntax.children[1:]
            if target.operation == "name" and not costs:
                schema = None if self.shared_context is None else self.shared_context.state
                if schema is None or target.value not in dict(schema.fields):
                    raise C0LawError(f"{location}: effect target is not a declared context field")
                amount = self.expression(
                    text[value.start : value.end],
                    dict(schema.fields)[target.value].name,
                    location + ".value",
                )
                result.append(ContextEffect(target.value, amount))
                continue
            if target.operation != "field":
                raise C0LawError(f"{location}: effect target must be a declared entity field")
            source = ExpressionSource(text, location)
            target_expression = self.expression(
                text[target.children[0].start : target.children[0].end],
                None,
                location + ".target",
                context="actor" if costs else "world",
            )
            if target_expression.result.kind != "ref":
                source.fail(
                    "UnauthorizedWrite",
                    target.start,
                    "entity reference field",
                    "data record or scalar",
                )
            sort, field = target_expression.result.sort, target.value
            try:
                plan = self.entities.field(sort, field)
            except C0LawError:
                source.fail("UnknownField", target.start, "declared entity field", field)
            for _, relation in self.entities.relations:
                if self.table.accepts_sort(relation.item, sort) and field in (
                    relation.holder,
                    relation.ground,
                ):
                    source.fail(
                        "UnauthorizedWrite",
                        target.start,
                        "carrying operation for managed fields",
                        field,
                    )
            if costs and (
                target_expression.node.path != ValueRead(self.actor) or plan.kind != "int"
            ):
                source.fail(
                    "UnauthorizedWrite", target.start, "controlling actor integer resource", field
                )
            if costs and field not in dict(self.entities.entities)[sort].view:
                source.fail(
                    "InformationBoundary", target.start, "actor-visible cost resource", field
                )
            amount = self.expression(
                text[value.start : value.end],
                "Integer<>" if costs else plan.name,
                location + ".value",
                context="actor" if costs else "world",
            )
            result.append(FieldEffect(expected, target_expression, field, amount))
        return tuple(result)

    def relation(self, text, path):
        if self.actor is None:
            raise C0LawError("relation attempts require an actual controlling Actor")
        syntax = parse_expression(text, path=path)
        if (
            syntax.operation != "call"
            or syntax.children[0].operation != "field"
            or syntax.children[0].children[0].operation != "name"
        ):
            raise C0LawError(f"{path}: expected a declared relation attempt")
        relation = dict(self.entities.relations).get(syntax.children[0].children[0].value)
        operation = syntax.children[0].value
        count = 2 if operation in ("take", "drop") else 3
        if (
            relation is None
            or operation not in ("take", "drop", "offer", "transfer")
            or len(syntax.children) != count + 1
        ):
            raise C0LawError(f"{path}: unknown relation operation or wrong arity")
        arguments = tuple(
            self.expression(text[arg.start : arg.end], None, f"{path}.arguments[{index}]")
            for index, arg in enumerate(syntax.children[1:])
        )
        for index, argument in enumerate(arguments):
            expected = relation.item if index == 0 else relation.person
            if argument.result.kind != "ref" or not self.table.accepts_sort(
                expected, argument.result.sort
            ):
                raise C0LawError(f"{path}: incompatible relation argument")
        chooser = arguments[-1] if operation == "transfer" else arguments[1]
        if chooser.node.path != ValueRead(self.actor):
            raise C0LawError(f"{path}: take/drop/offer by chooser; transfer accepted by recipient")
        return RelationEffect(relation, operation, arguments)

    def resolution(self, row, outcome, *, path=None, depth=0):
        path = path or self.path + ".resolve"
        if not isinstance(row, Mapping) or depth > 64:
            raise C0LawError(f"{path}: bounded complete resolution required")
        if set(row) == {"draw", "then"}:
            from .randomness import MAX_SIDES

            declarations = row["draw"]
            if not isinstance(declarations, Mapping) or not declarations:
                raise C0LawError(f"{path}.draw: unique typed dice declarations required")
            bindings, actor_bindings, slots = dict(self.bindings), dict(self.actor_bindings), []
            reserved = (
                set(bindings)
                | set(dict(self.table.definitions))
                | set(dict(self.library.definitions))
                | set(dict(self.entities.relations))
                | set(dict(self.local_views))
                | _INTRINSICS
            )
            for name, declaration in declarations.items():
                if not _identifier(name) or name in reserved:
                    raise C0LawError(f"{path}.draw: random binder conflicts with lexical scope")
                if (
                    not isinstance(declaration, Mapping)
                    or "type" not in declaration
                    or len(set(declaration) & {"sides", "shuffle"}) != 1
                    or set(declaration) - {"type", "sides", "shuffle", "stream"}
                ):
                    raise C0LawError(
                        f"{path}.draw.{name}: type, sides and optional stream required"
                    )
                kind = (
                    dict(self.table.definitions).get(declaration["type"])
                    if type(declaration["type"]) is str
                    else None
                )
                pool = (
                    self.expression(
                        declaration["shuffle"], declaration["type"], f"{path}.draw.{name}.shuffle"
                    )
                    if "shuffle" in declaration
                    else None
                )
                sides = (
                    self.expression(declaration["sides"], None, f"{path}.draw.{name}.sides")
                    if pool is None
                    else None
                )
                bounds = None if sides is None else sides.node.value_type
                if pool is not None:
                    if kind is None or kind.kind != "sequence":
                        raise C0LawError(
                            f"{path}.draw.{name}: shuffle requires a declared Sequence"
                        )
                elif (
                    kind is None
                    or kind.kind != "int"
                    or kind.minimum is None
                    or kind.maximum is None
                    or kind.minimum > 1
                    or kind.maximum < 2
                    or bounds.kind != "int"
                    or bounds.minimum is None
                    or bounds.minimum < 2
                    or bounds.maximum is None
                    or bounds.maximum > min(kind.maximum, MAX_SIDES)
                ):
                    raise C0LawError(
                        f"{path}.draw.{name}: finite sides and covering result range required"
                    )
                stream = (
                    self.expression(declaration["stream"], None, f"{path}.draw.{name}.stream")
                    if "stream" in declaration
                    else None
                )
                slots.append(DrawSlot(name, kind.name, sides, stream, pool))
                bindings[name] = actor_bindings[name] = kind.name
                reserved.add(name)
            compiler = EffectCompiler(
                self.table,
                bindings,
                library=self.library,
                entities=self.entities,
                actor=self.actor,
                path=self.path,
                context=self.context,
                local_views=self.local_views,
                disclosures=self.disclosures.items(),
                actor_bindings=actor_bindings,
                successors=self.successors,
                shared_context=self.shared_context,
                effect_depth=self.effect_depth,
            )
            return ResolutionPlan(
                draws=tuple(slots),
                then=compiler.resolution(
                    row["then"], outcome, path=path + ".then", depth=depth + 1
                ),
            )
        leaf_fields = {"result", "effects", "deliver", "form"}
        if self.successors is not None:
            leaf_fields.add("next")
        if "result" in row and set(row) <= leaf_fields:
            from .disclosures import compile_deliveries
            from .formation import compile_formations

            next_point = row.get("next")
            if self.successors is not None and next_point not in self.successors:
                raise C0LawError(f"{path}.next: expected an explicit declared successor")
            return ResolutionPlan(
                result=self.expression(row["result"], outcome, path + ".result"),
                effects=self.fields(row.get("effects", []), path=path + ".effects"),
                deliveries=compile_deliveries(row.get("deliver", {}), self, path),
                next_point=next_point,
                forms=compile_formations(row.get("form", []), self, path + ".form"),
            )
        if set(row) == {"when", "then", "else"}:
            return ResolutionPlan(
                condition=self.expression(row["when"], "Bool", path + ".when"),
                then=self.resolution(row["then"], outcome, path=path + ".then", depth=depth + 1),
                otherwise=self.resolution(
                    row["else"], outcome, path=path + ".else", depth=depth + 1
                ),
            )
        if set(row) == {"attempt", "success", "failure"}:
            return ResolutionPlan(
                attempt=self.relation(row["attempt"], path + ".attempt"),
                then=self.resolution(
                    row["success"], outcome, path=path + ".success", depth=depth + 1
                ),
                otherwise=self.resolution(
                    row["failure"], outcome, path=path + ".failure", depth=depth + 1
                ),
            )
        raise C0LawError(f"{path}: incomplete or unsupported resolution")

    def summary(self, costs, resolution):
        expressions = (
            *resolution.expressions(),
            *(expr for effect in costs for expr in (effect.target, effect.value)),
        )
        writes = tuple(
            dict.fromkeys(
                effect.write
                for effect in (
                    *costs,
                    *(
                        effect
                        for leaf in resolution.leaves()
                        for effect in field_effects(leaf.effects)
                    ),
                )
                if type(effect) is FieldEffect
            )
        )
        relations = []
        for selected in resolution.walk():
            if selected.attempt is not None:
                relations.append(selected.attempt)
        context_writes = tuple(
            dict.fromkeys(
                effect.field
                for leaf in resolution.leaves()
                for effect in leaf.effects
                if type(effect) is ContextEffect
            )
        )
        return EffectSummary(writes, expressions, tuple(relations), context_writes)
