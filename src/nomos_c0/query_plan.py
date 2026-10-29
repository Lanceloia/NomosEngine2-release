"""Static value numbering and dominance for repeated pure query calls."""

from dataclasses import dataclass, field

from .expression_analysis import ExpressionAnalysis


@dataclass(frozen=True)
class ControlBlock:
    ordinal: int
    parent: int | None
    kind: str
    offset: int


@dataclass(frozen=True)
class QueryReuseGroup:
    ordinal: int
    definition: str
    depth_bound: int
    calls: tuple = field(repr=False)
    call_blocks: tuple
    loop_invariant: bool = False


@dataclass(frozen=True)
class QueryReuseDecision:
    status: str
    definition: str
    offsets: tuple
    reason: str


@dataclass(frozen=True)
class QueryReusePlan:
    groups: tuple[QueryReuseGroup, ...]
    blocks: tuple[ControlBlock, ...] = ()
    decisions: tuple[QueryReuseDecision, ...] = ()

    def manifest(self):
        return (
            tuple((b.ordinal, b.parent, b.kind, b.offset) for b in self.blocks),
            tuple(
                (
                    g.ordinal,
                    g.definition,
                    g.depth_bound,
                    tuple(n.offset for n in g.calls),
                    g.call_blocks,
                    g.loop_invariant,
                )
                for g in self.groups
            ),
        )


def _parameter_value(key):
    if key is None:
        return False
    if key[0] == "literal":
        return True
    if key[0] == "variable":
        return key[2][0] == "parameter"
    return key[0] == "field" and all(_parameter_value(child) for child in key[3])


def _loop_invariant(definition, children, analysis):
    facts = analysis.facts(definition.body)
    return (
        all(_parameter_value(child) for child in children)
        and not facts.external_reads
        and (facts.iteration_dependent or facts.step_bound is not None and facts.step_bound >= 24)
    )


def plan_query_reuse(node, parameters, *, actor=None, query=False, analysis=None, explain=False):
    """Only stable values and dominating successful calls can become local producers."""
    analysis = ExpressionAnalysis() if analysis is None else analysis
    observed = []
    groups, blocks = [], [ControlBlock(0, None, "entry", node.offset)]
    initial = {name: ("parameter", name) for name in parameters}
    roles = {name: ("role", name) if query else name == actor for name in parameters}

    def own(path, roles):
        return False if path is None or path.steps else roles.get(path.root, False)

    def block(parent, kind, offset):
        ordinal = len(blocks)
        blocks.append(ControlBlock(ordinal, parent, kind, offset))
        return ordinal

    def scan(value, environment, roles, available, current, loops=0):
        operation = value.operation
        if operation in {"if", "and", "or"}:
            scan(value.children[0], environment, roles, available, current, loops)
            for index, child in enumerate(value.children[1:]):
                inside = block(current, f"{operation}.branch{index}", child.offset)
                scan(child, environment, roles, dict(available), inside, loops)
            return None
        if operation == "match":
            scan(value.children[0], environment, roles, available, current, loops)
            for (tag, name, _), child in zip(value.operand, value.children[1:], strict=True):
                inside = block(current, "case." + tag, child.offset)
                local, local_roles = dict(environment), dict(roles)
                if name is not None:
                    local[name], local_roles[name] = ("case", inside, name), False
                scan(child, local, local_roles, dict(available), inside, loops)
            return None
        if operation in {
            "filter",
            "map",
            "sum_by",
            "exists",
            "exactly_one",
            "forall",
            "min_by",
            "max_by",
            "latest_by",
        }:
            scan(value.children[0], environment, roles, available, current, loops)
            nested = block(current, operation + ".body", value.offset)
            token, inside = ("element", nested), dict(available)
            names = (
                value.operand
                if operation in {"min_by", "max_by", "latest_by"}
                else (value.operand,)
            )
            for name, child in zip(names, value.children[1:], strict=True):
                scan(
                    child,
                    {**environment, name: token},
                    {**roles, name: False},
                    inside,
                    nested,
                    loops + 1,
                )
            return None
        children = tuple(
            scan(child, environment, roles, available, current, loops) for child in value.children
        )
        kind = value.value_type.type_id
        if operation == "variable":
            return operation, kind, environment[value.operand]
        if operation == "literal":
            return operation, kind, type(value.operand), value.operand
        if operation == "local_view":
            return operation, kind, value.operand
        if operation in {"field", "entity_field"} and all(child is not None for child in children):
            if operation == "field":
                plan, name = value.operand
                key = plan.type_id, name
            else:
                request = value.operand
                key = request.sort, request.field, own(request.selector, roles)
            return operation, kind, key, children
        if operation == "pure_call" and all(child is not None for child in children):
            definition = value.operand
            key = definition.name, children, tuple(own(c.path, roles) for c in value.children)
            if key not in available:
                available[key] = len(groups)
                groups.append([definition, [], [], False])
            selected = groups[available[key]]
            selected[1].append(value)
            selected[2].append(current)
            selected[3] |= bool(loops and _loop_invariant(definition, children, analysis))
            if explain:
                observed.append((value, available[key]))
        elif operation == "pure_call" and explain:
            observed.append((value, None))
        # Computed containers or query results are not stable input objects by proof.
        return None

    scan(node, initial, roles, {}, 0)
    selected = [
        (definition, calls, call_blocks, invariant)
        for definition, calls, call_blocks, invariant in groups
        if len(calls) > 1 or invariant
    ]
    decisions = []
    if explain:
        from collections import Counter

        counts = Counter(value.operand.name for value, _ in observed)
        for definition, calls, _, invariant in selected:
            decisions.append(
                QueryReuseDecision(
                    "Passed",
                    definition.name,
                    tuple(call.offset for call in calls),
                    "lazy-loop-invariant-parameters" if invariant else "dominating-stable-inputs",
                )
            )
        for value, group in observed:
            if counts[value.operand.name] > 1 and (
                group is None or len(groups[group][1]) == 1 and not groups[group][3]
            ):
                decisions.append(
                    QueryReuseDecision(
                        "Missed",
                        value.operand.name,
                        (value.offset,),
                        "argument-identity-unproven"
                        if group is None
                        else "no-dominating-equivalent-call",
                    )
                )
    return QueryReusePlan(
        tuple(
            QueryReuseGroup(
                index,
                definition.name,
                analysis.facts(definition.body).depth_bound,
                tuple(calls),
                tuple(call_blocks),
                invariant,
            )
            for index, (definition, calls, call_blocks, invariant) in enumerate(selected)
        ),
        tuple(blocks),
        tuple(decisions),
    )
