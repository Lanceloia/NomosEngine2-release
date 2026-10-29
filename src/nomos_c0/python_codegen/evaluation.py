"""Compile evaluation plans into lazy, dependency-specialized Python functions."""


class EvaluationEmitter:
    def __init__(self, emitter, plan):
        self.emitter, self.plan = emitter, plan

    def expression(self, key, environment="environment", *, logical_work=None):
        site = self.plan.site(key)
        name = "_expression_" + str(len(self.emitter.expressions))
        self.emitter.expressions.append((name, site.expression))
        node = self.plan.nodes[site.node]
        if node.lifetime == "batch":
            arguments = name
        else:
            bindings = ", ".join(f"{environment}[{key!r}]" for key, _ in node.dependencies.inputs)
            arguments = f"{name}, ({bindings}{',' if bindings else ''})"
        work = "" if logical_work is None else f", logical_work={logical_work}"
        return f"evaluations[{node.ordinal}]({arguments}{work})"

    def preparation(self):
        lines = ["evaluation_queries = {}"]
        for node in self.plan.nodes:
            index = node.ordinal
            fields = node.dependencies.inputs
            context = "actor_reads" if node.dependencies.mode == "actor" else "world_reads"
            if node.lifetime == "batch":
                values = "{" + ", ".join(f"{k!r}: evaluation_base[{k!r}]" for k, _ in fields) + "}"
                lines.extend(
                    [
                        f"_ready_{index}, _value_{index} = False, None",
                        f"def _evaluate_{index}(function, *, logical_work=None):",
                        f"    nonlocal _ready_{index}, _value_{index}",
                        "    if logical_work is not None: logical_work.spend()",
                        f"    if not _ready_{index}:",
                        "        if logical_work is not None: "
                        f"logical_work.spend({max(1, len(fields))})",
                        f"        _value_{index} = function({values}, {context}, "
                        "value_limits=evaluation_limits, query_values=evaluation_queries, "
                        "logical_work=logical_work)",
                        f"        _ready_{index} = True",
                        f"    return _value_{index}",
                    ]
                )
            else:
                key = ", ".join(f"id(inputs[{i}])" for i in range(len(fields)))
                values = (
                    "{" + ", ".join(f"{k!r}: inputs[{i}]" for i, (k, _) in enumerate(fields)) + "}"
                )
                lines.extend(
                    [
                        f"_results_{index} = {{}}",
                        f"def _evaluate_{index}(function, inputs, *, logical_work=None):",
                        f"    if logical_work is not None: logical_work.spend({1 + len(fields)})",
                        f"    key = ({key},)",
                        f"    if key not in _results_{index}:",
                        f"        value = function({values}, {context}, "
                        "value_limits=evaluation_limits, query_values=evaluation_queries, "
                        "logical_work=logical_work)",
                        f"        _results_{index}[key] = inputs, value",
                        f"    return _results_{index}[key][1]",
                    ]
                )
        lines.append(
            "evaluations = (" + ", ".join(f"_evaluate_{n.ordinal}" for n in self.plan.nodes) + ",)"
        )
        return ["evaluation_limits = session.limits.value", *lines]
