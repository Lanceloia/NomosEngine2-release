"""Emit bounded local memo tables after ordinary query argument checks."""

import ast
from copy import deepcopy

from .syntax import statements


def _small_scalar(kind, value):
    if kind == "int":
        return ast.Compare(
            left=ast.Call(
                func=ast.Attribute(value=deepcopy(value), attr="bit_length", ctx=ast.Load()),
                args=[],
                keywords=[],
            ),
            ops=[ast.LtE()],
            comparators=[ast.Constant(value=8192)],
        )
    if kind in {"text", "enum"}:
        return ast.Compare(
            left=ast.Call(
                func=ast.Name(id="len", ctx=ast.Load()), args=[deepcopy(value)], keywords=[]
            ),
            ops=[ast.LtE()],
            comparators=[ast.Constant(value=1024)],
        )
    return None


class LoopQueryMemoEmitter:
    def __init__(self, sites):
        self.sites = {id(site.call): site for site in sites}

    def initializers(self):
        return [
            statement
            for site in self.sites.values()
            for statement in statements(f"_nomos_loop_memo_{site.ordinal} = {{}}")
        ]

    def emit(self, emitter, node, body, name, call, arguments, logical_depth):
        site = self.sites.get(id(node))
        if site is None:
            return False
        cache = f"_nomos_loop_memo_{site.ordinal}"
        key, entry, start, cost = (
            cache + suffix for suffix in ("_key", "_entry", "_start", "_cost")
        )
        computation = statements(f"_budget.lookup_work({1 + len(site.varying)})")
        computation.append(
            emitter.assign(
                key, ast.Tuple(elts=[deepcopy(arguments[i]) for i in site.varying], ctx=ast.Load())
            )
        )
        computation.extend(statements(f"{entry} = {cache}.get({key})"))
        branch = statements(
            f"if {entry} is not None and "
            f"_budget.steps + {entry}[1] <= _budget.source_limits.steps and "
            f"({logical_depth}) + {site.depth_bound} <= _budget.source_limits.depth:\n"
            f"    _budget.replay_source({entry}[1])\n"
            f"    {name} = {entry}[0]\n"
            "else:\n    pass"
        )[0]
        branch.orelse = [
            *statements(f"{start} = _budget.steps"),
            emitter.assign(name, call),
            *statements(
                f"{cost} = _budget.steps - {start}\n"
                f"if {cost} >= 32 and len({cache}) < 64:\n"
                f"    {cache}[{key}] = ({name}, {cost})"
            ),
        ]
        result_guard = _small_scalar(node.operand.returns.kind, ast.Name(id=name, ctx=ast.Load()))
        if result_guard is not None:
            branch.orelse[-1].test.values.append(result_guard)
        computation.append(branch)
        guards = [
            guard
            for index in site.varying
            if (guard := _small_scalar(node.operand.parameters[index][1].kind, arguments[index]))
            is not None
        ]
        if guards:
            body.append(
                ast.If(
                    test=guards[0] if len(guards) == 1 else ast.BoolOp(op=ast.And(), values=guards),
                    body=computation,
                    orelse=[emitter.assign(name, deepcopy(call))],
                )
            )
        else:
            body.extend(computation)
        return True
