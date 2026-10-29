"""Stage-scoped semantic I/O plans; native binding remains a separate compiler pass."""

from dataclasses import dataclass, field

from nomos_c0.author_contract_v1 import C0LawError

from .effects import ContextEffect, FieldEffect, ForEffect, ResolutionPlan
from .entity_reads import OwnerRead
from .expressions import CheckedValueExpression, ValueRead


@dataclass(frozen=True)
class ExpressionUse:
    site: str
    stage: str
    expression: CheckedValueExpression = field(repr=False)


@dataclass(frozen=True)
class ValueUse:
    site: str
    stage: str
    role: str
    read: ValueRead
    context: str | None = None


@dataclass(frozen=True)
class FieldUse:
    site: str
    stage: str
    role: str
    read: OwnerRead


@dataclass(frozen=True)
class FieldChange:
    site: str
    stage: str
    sort: str
    field: str
    selector: ValueRead | None
    target: CheckedValueExpression = field(repr=False)


@dataclass(frozen=True)
class ContextChange:
    site: str
    stage: str
    context: str
    field: str


@dataclass(frozen=True)
class IdentityUse:
    site: str
    stage: str
    role: str
    sort: str


@dataclass(frozen=True)
class InformationUse:
    site: str
    stage: str
    role: str
    holder: str
    alias: str
    definition: object


@dataclass(frozen=True)
class ProtocolUse:
    site: str
    stage: str
    kind: str
    name: str
    details: tuple = ()


@dataclass(frozen=True)
class RuleIOPlan:
    name: str
    kind: str
    source: str | None
    expressions: tuple[ExpressionUse, ...]
    values: tuple[ValueUse, ...]
    field_reads: tuple[FieldUse, ...]
    field_writes: tuple[FieldChange, ...]
    context_writes: tuple[ContextChange, ...]
    identity_domains: tuple[IdentityUse, ...]
    information: tuple[InformationUse, ...]
    protocols: tuple[ProtocolUse, ...]


@dataclass(frozen=True)
class ExecutionIOPlan:
    rules: tuple[RuleIOPlan, ...]
    auxiliary: tuple[RuleIOPlan, ...]

    def rule(self, name):
        return next(rule for rule in self.rules if rule.name == name)


def _reference_sorts(kind):
    if not kind.has_references:
        return ()
    if kind.kind == "ref":
        return (kind.sort,)
    children = [child for _, child in (*kind.fields, *kind.cases)]
    if kind.element is not None:
        children.append(kind.element)
    return tuple(dict.fromkeys(sort for child in children for sort in _reference_sorts(child)))


class _Builder:
    def __init__(self, program, name, kind, source=None):
        self.program, self.name, self.kind, self.source = program, name, kind, source
        self.expressions, self.values, self.reads, self.writes = [], [], [], []
        self.context_writes, self.identities, self.information, self.protocols = [], [], [], []

    def protocol(self, site, stage, kind, name, details=()):
        self.protocols.append(ProtocolUse(site, stage, kind, name, details))

    def owner_read(self, site, stage, role, read):
        if read.relation:
            relation = dict(self.program.entities.relations)[read.relation]
            self.owner_read(
                site, stage, role, OwnerRead(relation.item, relation.holder, read.selector)
            )
            self.owner_read(
                site, stage, role, OwnerRead(relation.item, relation.ground, read.selector)
            )
            self.owner_read(site, stage, role, OwnerRead(relation.person, relation.position, None))
            self.protocol(site, stage, "relation_read", relation.name, (read,))
            return
        self.program.entities.field(read.sort, read.field)
        self.reads.append(FieldUse(site, stage, role, read))
        self.identities.append(IdentityUse(site, stage, role, read.sort))

    def expression(self, expression, site, stage, context=None, views=(), holder=None):
        if type(expression) is not CheckedValueExpression:
            raise C0LawError("ExecutionIO: unsupported expression at " + site)
        self.expressions.append(ExpressionUse(site, stage, expression))
        role = expression.summary.context
        context_fields = (
            set() if context is None or context.state is None else dict(context.state.fields)
        )
        inputs = dict(expression.inputs)
        for read in expression.summary.reads:
            shared = context.name if read.root in context_fields else None
            self.values.append(ValueUse(site, stage, role, read, shared))
            spec = inputs.get(read.root)
            if spec is not None:
                for sort in _reference_sorts(expression.table[spec.type_name]):
                    self.identities.append(IdentityUse(site, stage, role, sort))
        for read in expression.summary.owner_reads:
            self.owner_read(site, stage, role, read)
        for sort in expression.summary.reference_domains:
            self.identities.append(IdentityUse(site, stage, role, sort))
        pending, visited = [expression.node], set()
        while pending:
            node = pending.pop()
            if id(node) in visited:
                continue
            visited.add(id(node))
            pending.extend(node.children)
            if node.operation == "pure_call":
                pending.append(node.operand.body)
            if node.operation != "local_view":
                continue
            view = dict(views).get(node.operand)
            if view is None or holder is None:
                raise C0LawError("ExecutionIO: unbound local view at " + site)
            self.information.append(InformationUse(site, stage, role, holder, node.operand, view))
            if view.kind == "projected":
                projection = next(
                    (p for p in self.program.projections if p.name == view.channel), None
                )
                if projection is None:
                    raise C0LawError("ExecutionIO: missing projection " + view.channel)
                self.projection(projection, site + ".projection", stage)
            elif view.kind not in ("reports", "cognition"):
                raise C0LawError("ExecutionIO: unknown local view kind at " + site)

    def projection(self, plan, site, stage):
        self.expression(plan.audience, site + ".audience", stage, plan.context)
        self.expression(plan.value, site + ".value", stage, plan.context)

    def guarantees(self, plans, constraints, site, stage):
        for index, assurance in enumerate(plans):
            prefix = f"{site}.assure[{index}]"
            for name, expression in assurance.arguments:
                self.expression(expression, prefix + "." + name, stage)
            self.expression(assurance.predicate, prefix + ".holds", stage)
        for index, assurance in enumerate(constraints):
            prefix = f"{site}.constraint[{index}]"
            for name, expression in assurance.arguments:
                self.expression(expression, prefix + "." + name, stage)
            self.expression(assurance.definition.holds, prefix + ".holds", stage)
            for name, expression in assurance.definition.realization:
                self.expression(expression, prefix + ".realize." + name, stage)
            if assurance.definition.local is not None:
                self.expression(assurance.definition.local.check, prefix + ".local_check", stage)

    def effect(self, effect, site, stage, context, views, holder, *, cost=False):
        if type(effect) is ForEffect:
            if cost:
                raise C0LawError("ExecutionIO: loop cost is not a supported cost node")
            self.expression(effect.pool, site + ".pool", stage, context, views, holder)
            self.protocol(site, stage, "iteration", effect.variable, (effect.pool.read_key,))
            for index, child in enumerate(effect.effects):
                self.effect(child, f"{site}.effects[{index}]", stage, context, views, holder)
            return
        if type(effect) is ContextEffect:
            if context is None or context.state is None or cost:
                raise C0LawError("ExecutionIO: context update has no selected context")
            self.expression(effect.value, site + ".value", stage, context, views, holder)
            self.context_writes.append(ContextChange(site, stage, context.name, effect.field))
            return
        if type(effect) is not FieldEffect:
            raise C0LawError("ExecutionIO: unknown effect node at " + site)
        if effect.operation != ("consume" if cost else "set"):
            raise C0LawError("ExecutionIO: unsupported field operation at " + site)
        self.expression(effect.target, site + ".target", stage, context, views, holder)
        self.expression(effect.value, site + ".value", stage, context, views, holder)
        sort, selector = effect.target.result.sort, effect.target.node.path
        self.writes.append(FieldChange(site, stage, sort, effect.field, selector, effect.target))
        self.identities.append(IdentityUse(site, stage, "world", sort))
        if cost:
            self.owner_read(site, stage, "actor", OwnerRead(sort, effect.field, selector))

    def relation(self, attempt, site, stage, context, views, holder):
        relation, operation = attempt.relation, attempt.operation
        if operation not in ("take", "drop", "offer", "transfer"):
            raise C0LawError("ExecutionIO: unsupported relation operation at " + site)
        for index, expression in enumerate(attempt.arguments):
            self.expression(expression, f"{site}.args[{index}]", stage, context, views, holder)
        item, *people = attempt.arguments
        self.owner_read(
            site, stage, "world", OwnerRead(relation.item, relation.holder, item.node.path)
        )
        if operation == "take":
            self.owner_read(
                site, stage, "world", OwnerRead(relation.item, relation.ground, item.node.path)
            )
        for person in people:
            self.owner_read(
                site,
                stage,
                "world",
                OwnerRead(relation.person, relation.position, person.node.path),
            )
        if operation != "offer":
            self.writes.append(
                FieldChange(site, stage, relation.item, relation.holder, item.node.path, item)
            )
        if operation == "drop":
            self.writes.append(
                FieldChange(site, stage, relation.item, relation.ground, item.node.path, item)
            )
        self.protocol(site, stage, "carrying", relation.name, (operation, relation.offer_field))

    def resolution(self, plan, site, stage, context, views, holder):
        if type(plan) is not ResolutionPlan:
            raise C0LawError("ExecutionIO: unknown resolution node at " + site)

        def run(expr, label):
            self.expression(expr, site + label, stage, context, views, holder)

        if plan.result is None:
            if plan.draws:
                for slot in plan.draws:
                    for label, expression in (
                        ("pool", slot.pool),
                        ("sides", slot.sides),
                        ("stream", slot.stream),
                    ):
                        if expression is not None:
                            run(expression, ".draw." + slot.name + "." + label)
                    self.protocol(
                        site,
                        stage,
                        "random",
                        slot.name,
                        (
                            slot.type_name,
                            "shuffle" if slot.pool is not None else "die",
                            "main" if slot.stream is None else slot.stream.read_key,
                        ),
                    )
            elif plan.condition is not None:
                run(plan.condition, ".when")
            elif plan.attempt is not None:
                self.relation(plan.attempt, site + ".attempt", stage, context, views, holder)
            else:
                raise C0LawError("ExecutionIO: unresolved branch at " + site)
            self.resolution(plan.then, site + ".then", stage, context, views, holder)
            if plan.otherwise is not None:
                self.resolution(plan.otherwise, site + ".else", stage, context, views, holder)
            return
        run(plan.result, ".result")
        for index, effect in enumerate(plan.effects):
            self.effect(effect, f"{site}.effects[{index}]", stage, context, views, holder)
        for index, form in enumerate(plan.forms):
            for name, expression in form.fields:
                run(expression, f".form[{index}].{name}")
            self.protocol(site, stage, "formation", form.schema.name, (form.schema.kind,))
        if plan.next_point is not None:
            self.protocol(site, stage, "successor", plan.next_point)
        for index, delivery in enumerate(plan.deliveries):
            prefix = f"{site}.deliver[{index}]"
            if delivery.pool is not None:
                self.expression(delivery.pool, prefix + ".in", stage, context, views, holder)
                self.protocol(
                    prefix,
                    stage,
                    "delivery_each",
                    delivery.variable,
                    (delivery.pool.result.element.name,),
                )
            for (name, _), expression in zip(
                delivery.definition.parameters, delivery.arguments, strict=True
            ):
                self.expression(expression, prefix + ".args." + name, stage, context, views, holder)
            definition = delivery.definition
            sample = definition.sample
            if sample not in ("before", "after"):
                raise C0LawError("ExecutionIO: unsupported disclosure sample at " + prefix)
            sampled_stage = "disclosure." + sample
            self.expression(definition.recipients, prefix + ".to", sampled_stage)
            self.expression(definition.value, prefix + ".value", sampled_stage)
            self.guarantees(definition.assurances, definition.constraints, prefix, sampled_stage)
            self.protocol(
                prefix,
                sampled_stage,
                "delivery",
                delivery.label,
                (definition.name, tuple(definition.parameters)),
            )

    def finish(self):
        def unique(values):
            return tuple(dict.fromkeys(values))

        return RuleIOPlan(
            self.name,
            self.kind,
            self.source,
            tuple(self.expressions),
            unique(self.values),
            unique(self.reads),
            tuple(self.writes),
            unique(self.context_writes),
            unique(self.identities),
            unique(self.information),
            unique(self.protocols),
        )


def compile_execution_io(program):
    from .activities import CancellationPlan
    from .program import AbilityPlan
    from .reactions import ReactionPlan

    builders = []
    plans = [
        *((plan, "action") for plan in program.abilities),
        *((plan, "event") for plan in program.reactions),
        *((activity.completion, "due") for activity in program.activities),
        *(
            (activity.cancellation, "cancellation")
            for activity in program.activities
            if activity.cancellation is not None
        ),
        *((periodic.event, "periodic") for periodic in program.periodic),
    ]
    for plan, kind in plans:
        if type(plan) not in (AbilityPlan, ReactionPlan, CancellationPlan):
            raise C0LawError("ExecutionIO: unknown executable plan")
        builder = _Builder(program, plan.name, kind, plan.source)
        context, views = plan.context, plan.views if type(plan) is AbilityPlan else ()
        holder = plan.actor if type(plan) in (AbilityPlan, CancellationPlan) else None
        builder.protocol("native", "before", "identity", "actual_bindings")
        builder.protocol("native", "before", "world_control", "session")
        if holder is not None:
            builder.protocol("native", "before", "actor_information", holder)
            for sort in _reference_sorts(program.table[plan.actor_type]):
                builder.identities.append(IdentityUse("actor", "before", "actor", sort))
        if type(plan) is AbilityPlan:
            for item in plan.inputs.inputs:
                if item.kind not in ("enter", "member", "subset", "sequence", "derive"):
                    raise C0LawError("ExecutionIO: unknown input domain")
                builder.protocol(
                    "inputs." + item.name,
                    "before",
                    "input",
                    item.name,
                    (item.type_name, item.kind, item.dependencies, item.repetition),
                )
                for sort in _reference_sorts(program.table[item.type_name]):
                    builder.identities.append(
                        IdentityUse("inputs." + item.name, "before", "actor", sort)
                    )
                for label in ("pool", "minimum", "maximum", "length", "derive", "constraint"):
                    expression = getattr(item, label)
                    if expression is not None:
                        builder.expression(
                            expression,
                            "inputs." + item.name + "." + label,
                            "before",
                            context,
                            views,
                            holder,
                        )
            if plan.epoch is not None:
                builder.expression(plan.epoch, "epoch", "before", context, views, holder)
        if type(plan) in (AbilityPlan, CancellationPlan):
            builder.expression(plan.where, "where", "before", context, views, holder)
            for index, cost in enumerate(plan.costs):
                builder.effect(cost, f"cost[{index}]", "before", context, views, holder, cost=True)
            if plan.time_cost is not None:
                builder.expression(plan.time_cost, "time_cost", "before", context, views, holder)
                builder.protocol("time_cost", "before", "schedule", "action_cost")
        else:
            builder.expression(plan.when, "when", "before", context)
            builder.protocol("native", "before", "captures", plan.name, tuple(plan.captures))
        builder.resolution(plan.resolution, "resolve", "before", context, views, holder)
        if type(plan) is AbilityPlan and plan.process is not None:
            node = plan.process
            process = next(p for p in program.processes if p.name == node.process)
            builder.protocol(
                "process",
                "before",
                "process",
                node.process,
                (node.point, node.prefix, node.inputs, node.resets, process.stage, node.window),
            )
            if node.completion is not None:
                builder.expression(
                    node.completion,
                    "process.complete_when",
                    "after_effects",
                    context,
                    views,
                    holder,
                )
        if kind in ("due", "periodic", "cancellation"):
            builder.protocol("native", "before", "due", plan.name)
        builders.append(builder)
    by_source = {builder.source: builder for builder in builders}
    if len(by_source) != len(builders):
        raise C0LawError("ExecutionIO: duplicate executable source")
    for activity in program.activities:
        for trigger in activity.completion.triggers:
            builder = by_source[trigger]
            builder.expression(
                activity.duration,
                "activity." + activity.completion.name + ".duration",
                "before",
                activity.completion.context,
                holder=activity.actor,
            )
            builder.protocol(
                "activity",
                "before",
                "schedule_due",
                activity.completion.name,
                tuple(activity.completion.captures),
            )
    for periodic in program.periodic:
        by_source[periodic.event.source].protocol(
            "periodic",
            "opening",
            "periodic",
            periodic.event.name,
            (periodic.interval, periodic.first_after, periodic.key),
        )
    auxiliary = []
    for plan in program.projections:
        builder = _Builder(program, plan.name, "projection")
        builder.projection(plan, "projection", "query")
        auxiliary.append(builder.finish())
    for plan in program.information:
        builder = _Builder(program, plan.name, "opening_information")
        builder.projection(plan.projection, "opening", "opening")
        builder.guarantees(plan.assurances, plan.constraints, "opening", "opening")
        builder.protocol("opening", "opening", "delivery", plan.name)
        auxiliary.append(builder.finish())
    for plan in program.contexts:
        if plan.assertion is not None:
            builder = _Builder(program, plan.name, "context_assertion")
            builder.expression(plan.assertion, "assertion", "opening", plan)
            auxiliary.append(builder.finish())
    if program.terminal is not None:
        plan = program.terminal
        builder = _Builder(program, plan.name, "terminal")
        for stage in ("opening", "closure"):
            for name in ("when", "value", "to"):
                builder.expression(getattr(plan, name), name, stage, plan.context)
        builder.protocol("terminal", "closure", "process", "terminal_registry")
        auxiliary.append(builder.finish())
    if program.time is not None:
        for plan in program.time.schedules:
            builder = _Builder(program, plan.family, "schedule")
            builder.expression(plan.speed, "speed", "schedule")
            builder.expression(plan.eligible, "eligible", "schedule")
            builder.protocol("schedule", "schedule", "identity", plan.family)
            auxiliary.append(builder.finish())
    return ExecutionIOPlan(tuple(builder.finish() for builder in builders), tuple(auxiliary))
