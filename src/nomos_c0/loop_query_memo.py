"""Select invocation-local query memoization keyed by checked scalar arguments."""

from dataclasses import dataclass, field

from .query_fields import HASHABLE_SCALARS

_LOOPS = frozenset(
    {"filter", "map", "sum_by", "exists", "exactly_one", "forall", "min_by", "max_by", "latest_by"}
)
_RESULTS = frozenset({"bool", "unit", "int", "text", "enum"})


@dataclass(frozen=True)
class LoopQueryMemoSite:
    ordinal: int
    call: object = field(repr=False)
    varying: tuple[int, ...]
    depth_bound: int


def _stable(node, names):
    if node.operation == "variable":
        return node.operand in names
    if node.operation == "literal":
        return True
    return node.operation == "field" and _stable(node.children[0], names)


def plan_loop_query_memo(node, parameters, analysis, *, shared=()):
    sites = []

    def scan(value, stable, loops, unique=frozenset()):
        if value.operation in _LOOPS:
            scan(value.children[0], stable, loops, unique)
            names = (
                value.operand
                if value.operation in {"min_by", "max_by", "latest_by"}
                else (value.operand,)
            )
            for name, child in zip(names, value.children[1:], strict=True):
                scan(
                    child,
                    stable - {name},
                    loops + 1,
                    {name} if not loops and value.children[0].value_type.kind == "set" else set(),
                )
            return
        if value.operation == "match":
            scan(value.children[0], stable, loops, unique)
            for (_, binder, _), child in zip(value.operand, value.children[1:], strict=True):
                scan(child, stable - {binder}, loops, unique - {binder})
            return
        for child in value.children:
            scan(child, stable, loops, unique)
        if not loops or value.operation != "pure_call" or id(value) in shared:
            return
        definition = value.operand
        facts = analysis.facts(definition.body)
        if (
            definition.returns.kind not in _RESULTS
            or facts.external_reads
            or not (
                facts.iteration_dependent or facts.step_bound is not None and facts.step_bound >= 64
            )
        ):
            return
        varying = tuple(
            index for index, arg in enumerate(value.children) if not _stable(arg, stable)
        )
        if not 1 <= len(varying) <= 4 or any(
            definition.parameters[index][1].kind not in HASHABLE_SCALARS for index in varying
        ):
            return
        if loops == 1 and any(
            value.children[index].operation == "variable"
            and value.children[index].operand in unique
            for index in varying
        ):
            return
        sites.append(LoopQueryMemoSite(len(sites), value, varying, facts.depth_bound))

    scan(node, frozenset(parameters), 0)
    return tuple(sites)
