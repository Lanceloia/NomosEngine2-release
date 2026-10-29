"""Emit statically selected query reuse as local values, without runtime lookup."""

from .syntax import statements


class QueryReuseEmitter:
    def __init__(self, plan):
        self.plan = plan
        self.sites, self.positions, self.producers = {}, {}, {}
        for group in plan.groups:
            for index, node in enumerate(group.calls):
                self.sites.setdefault(id(node), []).append((group, index == 0))

    def initializers(self):
        return [
            statement
            for group in self.plan.groups
            if group.loop_invariant
            for statement in statements(f"_nomos_invariant_{group.ordinal}_ready = False")
        ]

    def emit(self, emitter, node, body, name, call, logical_depth):
        sites = self.sites.get(id(node))
        if sites is None:
            body.append(emitter.assign(name, call))
            return
        index = self.positions.get(id(node), 0)
        self.positions[id(node)] = index + 1
        group, producer = sites[index]
        body.extend(statements("_budget.lookup_work(1)"))
        if group.loop_invariant:
            prefix = f"_nomos_invariant_{group.ordinal}"
            start, cost, value, ready = (
                prefix + suffix for suffix in ("_start", "_cost", "_value", "_ready")
            )
            branch = statements(
                f"if {ready} and _budget.steps + {cost} <= _budget.source_limits.steps and "
                f"({logical_depth}) + {group.depth_bound} <= _budget.source_limits.depth:\n"
                f"    _budget.replay_source({cost})\n"
                f"    {name} = {value}\n"
                "else:\n    pass"
            )[0]
            branch.orelse = [
                *statements(f"{start} = _budget.steps"),
                emitter.assign(name, call),
                *statements(f"{cost} = _budget.steps - {start}\n{value} = {name}\n{ready} = True"),
            ]
            body.append(branch)
            return
        if producer:
            start, cost = name + "_start", name + "_cost"
            body.extend(statements(f"{start} = _budget.steps"))
            body.append(emitter.assign(name, call))
            body.extend(statements(f"{cost} = _budget.steps - {start}"))
            self.producers[group.ordinal] = name, cost
        else:
            value, cost = self.producers[group.ordinal]
            branch = statements(
                f"if _budget.steps + {cost} <= _budget.source_limits.steps and "
                f"({logical_depth}) + {group.depth_bound} <= _budget.source_limits.depth:\n"
                f"    _budget.replay_source({cost})\n"
                f"    {name} = {value}\n"
                "else:\n    pass"
            )[0]
            branch.orelse = [emitter.assign(name, call)]
            body.append(branch)
