"""Emit finite/local callbacks over acquired public parameters, never hidden realizations."""

from dataclasses import replace

from .cognition import environment
from .syntax import statements


def expression_function(emitter, binding, name, checked):
    needed = {read.root for read in checked.summary.reads}
    checked = replace(
        checked, inputs=tuple(v for v in checked.inputs if v[0] in needed), actor=None
    )
    emitter.function(
        name,
        "session, codec, actor, values",
        [
            "environment = dict(values)",
            "reads = cognition_reads(session, codec, actor, mode='world')",
            *environment(emitter, binding, checked),
            "return " + emitter.expression(checked, reads="reads"),
        ],
    )
    return name


def input_definition(emitter, binding, prefix, plan, *, local):
    guarantee = plan.guarantee
    kind = "constraint" if local else plan.kind
    signature = (
        guarantee.definition.signature if kind == "constraint" else guarantee.predicate.read_key
    )
    identity = guarantee.definition.name if kind == "constraint" else guarantee.fact
    parameters = tuple(
        (name, value.result.name, value.result.type_id.signature)
        for name, value in guarantee.arguments
    )
    evaluate, dependencies = "None", ()
    if not local:
        if kind == "fact":
            evaluate = expression_function(
                emitter, binding, prefix + "_interpret", plan.interpretation
            )
            expressions = (plan.interpretation,)
        else:
            expressions = tuple(value for _, value in plan.bindings)
            functions = [
                (key, expression_function(emitter, binding, prefix + "_bind_" + str(i), value))
                for i, (key, value) in enumerate(plan.bindings)
            ]
            holds = expression_function(
                emitter, binding, prefix + "_holds", guarantee.definition.holds
            )
            lines = ["bound = {"]
            lines.extend(
                f"    {key!r}: {function}(session, codec, actor, values),"
                for key, function in functions
            )
            lines.extend(["}", f"return {holds}(session, codec, actor, {{**values, **bound}})"])
            evaluate = prefix + "_interpret"
            emitter.function(evaluate, "session, codec, actor, values", lines)
        dependencies = tuple(
            sorted({read.root for expr in expressions for read in expr.summary.reads})
        )
    sample = "opening" if plan.history == "opening" else plan.producer.sample
    exports = (
        () if local else tuple((p, a, emitter.program.table[t].name) for p, a, t in plan.expose)
    )
    return (
        f"AnalysisInput({plan.name!r}, {plan.channel.channel!r}, {plan.channel.source!r}, "
        f"{emitter.program.table[plan.channel.type_name].element.name!r}, {kind!r}, "
        f"{identity!r}, {signature!r}, {parameters!r}, {plan.history!r}, {sample!r}, "
        f"{plan.required!r}, {exports!r}, {evaluate}, {dependencies!r})"
    )


def definition(emitter, prefix, binding):
    plan = binding.local if binding.local is not None else binding.finite
    if plan is None:
        return "None", None
    local = binding.local is not None
    inputs = [
        input_definition(emitter, binding, prefix + f"_input_{i}", value, local=local)
        for i, value in enumerate(plan.inputs)
    ]
    inputs = "(" + ", ".join(inputs) + ",)"
    if local:
        normalize = prefix + "_normalize"
        lines = ["values = acquired.values"]
        for i, input in enumerate(plan.inputs):
            contract = input.guarantee.definition.local
            start = prefix + f"_normal_{i}"
            members = expression_function(emitter, binding, start + "_members", contract.members)
            labels = expression_function(emitter, binding, start + "_labels", contract.labels)
            lines.extend(
                [
                    f"if acquired.definition.name == {input.name!r}:",
                    "    members = tuple(sorted((codec.term("
                    f"{contract.members.result.element.name!r}, v) "
                    f"for v in {members}(session, codec, actor, values)), "
                    "key=lambda v: repr(v.wire)))",
                    f"    labels = tuple(codec.term({contract.labels.result.element.name!r}, v) "
                    f"for v in {labels}(session, codec, actor, values))",
                ]
            )
            if contract.kind == "allocation":
                lines.append("    return Allocation(context, acquired.ground, members, labels)")
            else:
                low = expression_function(emitter, binding, start + "_low", contract.minimum)
                high = "len(members)"
                if contract.maximum is not None:
                    fn = expression_function(emitter, binding, start + "_high", contract.maximum)
                    high = f"{fn}(session, codec, actor, values)"
                lines.extend(
                    [
                        "    labels = tuple(dict.fromkeys(labels))",
                        f"    return Count(context, acquired.ground, members, labels, "
                        f"{low}(session, codec, actor, values), {high})",
                    ]
                )
        lines.append("raise ValueError('unknown local input')")
        emitter.function(normalize, "session, codec, actor, acquired, context", lines)
        categories = []
        for i, category in enumerate(plan.categories):
            key = expression_function(emitter, binding, prefix + f"_category_{i}", category.key)
            matching = expression_function(
                emitter, binding, prefix + f"_matching_{i}", category.matching
            )
            categories.append(
                f"(codec.term({category.key.result.name!r}, {key}(session, codec, actor, {{}})), "
                f"tuple(dict.fromkeys(codec.term({category.matching.result.element.name!r}, v) "
                f"for v in {matching}(session, codec, actor, {{}}))))"
            )
        emitter.function(
            prefix + "_categories",
            "session, codec, actor",
            ["return (" + ", ".join(categories) + ",)"],
        )
        relation = plan.inputs[0].guarantee.definition.local.relation
        spec = f"LocalDefinition({inputs}, {plan.universe!r}, {normalize}, {prefix}_categories, "
        spec += (
            f"{plan.period!r}, {plan.assumptions!r}, {relation!r}, "
            f"LocalLimits(**{vars(plan.limits)!r}))"
        )
        algorithm, kind = "analyze_local", "local"
    else:
        variables = []
        for i, variable in enumerate(plan.variables):
            start = prefix + f"_variable_{i}"
            choose = expression_function(emitter, binding, start + "_choose", variable.choose)
            each, build, collection = "None", "None", "None"
            if variable.each is not None:
                each = expression_function(emitter, binding, start + "_each", variable.each)
                build = expression_function(emitter, binding, start + "_build", variable.value)
                collection = (
                    "frozenset"
                    if emitter.program.table[variable.type_name].kind == "set"
                    else "tuple"
                )
            target = emitter.program.table[variable.type_name]
            variables.append(
                f"FiniteVariable({variable.name!r}, {target.name!r}, {target.type_id.signature!r}, "
                f"{variable.choose.result.element.name!r}, {choose}, {each}, "
                f"{variable.item!r}, {variable.choice!r}, "
                f"{build}, {collection}, {variable.allocation!r})"
            )
        queries = []
        for i, query in enumerate(plan.queries):
            start = prefix + f"_query_{i}"
            each = (
                "None"
                if query.each is None
                else expression_function(emitter, binding, start + "_each", query.each)
            )
            key = expression_function(emitter, binding, start + "_key", query.key)
            holds = expression_function(emitter, binding, start + "_holds", query.holds)
            dependencies = tuple(sorted({r.root for r in query.holds.summary.reads}))
            queries.append(
                f"FiniteQuery({each}, {query.item!r}, {key}, {query.key.result.name!r}, "
                f"{holds}, {dependencies!r})"
            )
        model = expression_function(emitter, binding, prefix + "_model", plan.model_value)
        spec = (
            f"FiniteDefinition({inputs}, ({', '.join(variables)},), "
            f"({', '.join(queries)}{',' if queries else ''}), "
            f"{model}, {plan.model_value.result.name!r}, "
            f"{plan.assumptions!r}, FiniteLimits(**{vars(plan.limits)!r}))"
        )
        algorithm, kind = "analyze_finite", "finite"
    emitter.functions.extend(statements(f"{prefix}_spec = {spec}"))
    emitter.function(
        prefix + "_analyze",
        "session, codec, actor, receipts",
        [f"return {algorithm}({prefix}_spec, {binding.digest!r}, session, codec, actor, receipts)"],
    )
    return prefix + "_analyze", kind
