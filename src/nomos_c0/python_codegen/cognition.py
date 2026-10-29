"""Emit subjective revision and conditional derivation functions from checked models."""

from dataclasses import replace

from .fixed_values import fixed_value


def pure_expression(emitter, checked):
    # The generated wrapper binds the holder; these checked expressions cannot read owners.
    return emitter.expression(replace(checked, actor=None), reads="reads")


def definition(emitter):
    from .analysis import definition as analysis_definition

    plan = emitter.cognition
    if plan is None:
        return None
    definitions = []
    for index, binding in enumerate(plan.bindings):
        prefix = f"_cognition_{index}"
        analysis, analysis_kind = analysis_definition(emitter, prefix + "_analysis", binding)
        view = emit_view(emitter, prefix, binding)
        revisions = []
        for ordinal, rule in enumerate(binding.rules):
            name = f"{prefix}_revision_{ordinal}"
            lines = ["environment = {}", "reads = cognition_reads(session, codec, actor)"]

            def expression(checked):
                lines.extend(environment(emitter, binding, checked, view=view, rule=rule))
                return pure_expression(emitter, checked)

            accepted = expression(rule.accept)
            lines.append(f"if not ({accepted}): return None")
            lines.append(f"slot = codec.term({binding.slot_type!r}, {expression(rule.slot)})")
            enabled = expression(rule.where)
            lines.append(f"enabled = {enabled}")
            lines.append("if enabled:")
            for variable, checked, kind in (
                ("proposition", rule.proposition, binding.proposition_type),
                ("support", rule.support, None),
                ("opposition", rule.opposition, None),
                ("appraisal", rule.appraisal, binding.appraisal_type),
                ("score", rule.score, None),
            ):
                if checked is None:
                    value = "None" if kind else "0"
                else:
                    assignments = environment(emitter, binding, checked, view=view, rule=rule)
                    lines.extend("    " + line for line in assignments)
                    value = pure_expression(emitter, checked)
                    if kind is not None:
                        value = f"codec.term({kind!r}, {value})"
                lines.append(f"    {variable} = {value}")
            lines.extend(
                [
                    "else:",
                    "    proposition = appraisal = None",
                    "    support = opposition = score = 0",
                    f"return Frame({rule.name!r}, slot, evidence, proposition, support, "
                    "opposition, appraisal, score)",
                ]
            )
            emitter.function(name, "session, codec, actor, state, item, evidence", lines)
            revisions.append(
                f"RevisionRule({rule.name!r}, {rule.channel.channel!r}, {rule.channel.source!r}, "
                f"{emitter.program.table[rule.channel.type_name].element.name!r}, {name})"
            )
        derivations = [
            emit_derivation(emitter, f"{prefix}_derive_{ordinal}", binding, derive)
            for ordinal, derive in enumerate(binding.derivations)
        ]
        channels = {(rule.channel.source, rule.channel.channel) for rule in binding.rules}
        analysis_plan = binding.local if binding.local is not None else binding.finite
        if analysis_plan is not None:
            channels.update(
                (item.channel.source, item.channel.channel) for item in analysis_plan.inputs
            )
        definitions.append(
            f"CognitionDefinition({binding.name!r}, {binding.digest!r}, {binding.selector!r}, "
            f"{binding.target!r}, {binding.families!r}, {binding.budget!r}, "
            f"({', '.join(revisions)}{',' if revisions else ''}), "
            f"({', '.join(derivations)}{',' if derivations else ''}), "
            f"{binding.inference_limits!r}, {view}, {analysis}, {analysis_kind!r}, "
            f"{tuple(sorted(channels))!r})"
        )
    return "(" + ", ".join(definitions) + ("," if definitions else "") + ")"


def environment(emitter, binding, expression, *, view=None, rule=None):
    lines = []
    parameters = {p.name: p for p in binding.parameters}
    for key, _ in expression.inputs:
        if key == binding.actor:
            value = "actor"
        elif key == "prior":
            value = f"{view}(session, codec, state, True)"
        elif rule is not None and key == rule.item:
            value = "item"
        elif key in parameters:
            value = fixed_value(
                emitter.program.table, parameters[key], references="codec.references"
            )
        else:
            continue
        lines.append(f"if {key!r} not in environment: environment[{key!r}] = {value}")
    return lines


def emit_view(emitter, prefix, binding):
    name = prefix + "_view"
    lines = [
        "beliefs, appraisals = judgments(state, provisional=prior)",
        "budget = ValueBudget(session.limits.value, codec.references)",
        "def make(name, values): return RECORDS[name](**values)",
    ]
    for prior, kind in ((True, binding.prior_type), (False, binding.view_type)):
        fields = dict(emitter.program.table[kind].fields)
        prefix_lines = [
            f"if prior is {prior!r}:",
            "    values = {",
            "        'complete': True if prior else not state.pending,",
            f"        'beliefs': tuple(make({fields['beliefs'].element.name!r}, {{",
            "            'proposition': codec.value(key),",
            "            'support': support, 'opposition': opposition,",
            "            'status': ('conflict' if support and opposition else 'supported' "
            "if support else 'opposed' if opposition else 'unknown'),",
            "        }) for key, support, opposition in beliefs),",
            f"        'appraisals': tuple(make({fields['appraisals'].element.name!r}, {{",
            "            'key': codec.value(key), 'score': score,",
            "        }) for key, score in appraisals),",
            "    }",
        ]
        if not prior:
            prefix_lines.extend(
                [
                    "    values['inferences'] = tuple(make("
                    f"{fields['inferences'].element.name!r}, {{",
                    "        'proposition': codec.value(argument.proposition),",
                    "        'polarity': argument.polarity, 'relation': argument.relation,",
                    "        'argument': argument.id, 'conditional': True,",
                    "    }) for argument in (() if state.pending or state.reasoning is None "
                    "else state.reasoning.arguments))",
                ]
            )
            prefix_lines.extend(analysis_view(emitter, binding))
        prefix_lines.append(f"    return _VALIDATORS[{kind!r}](make({kind!r}, values), budget, ())")
        lines.extend(prefix_lines)
    emitter.function(name, "session, codec, state, prior", lines)
    return name


def analysis_view(emitter, binding):
    if binding.finite is None and binding.local is None:
        return []
    local = binding.local is not None
    plan = binding.local if local else binding.finite
    fields = dict(emitter.program.table[plan.view_type].fields)
    if local:
        row = fields["bounds"].element.name
        return [
            "    analysis = state.local",
            "    status = 'pending' if analysis is None else analysis.status",
            f"    values['local'] = make({plan.view_type!r}, {{",
            "        'status': status, 'complete': status == 'complete',",
            f"        'bounds': tuple(make({row!r}, {{",
            "            'members': frozenset(codec.value(t) for t in bound.members),",
            "            'category': codec.value(bound.category),",
            "            'minimum': bound.minimum, 'maximum': bound.maximum,",
            "        }) for bound in (() if analysis is None else analysis.bounds)),",
            "    })",
            "    values['complete'] = values['complete'] and status == 'complete'",
        ]
    row = fields["answers"].element.name
    return [
        "    analysis = state.analysis",
        "    status = 'pending' if analysis is None else analysis.status",
        f"    values['analysis'] = make({plan.view_type!r}, {{",
        "        'status': status, 'complete': status != 'pending',",
        "        'models': tuple(codec.value(t) "
        "for t in (() if analysis is None else analysis.models)),",
        f"        'answers': tuple(make({row!r}, {{",
        "            'key': codec.value(answer.key), 'entailed': answer.entailed,",
        "            'possible': answer.possible, 'refuted': answer.refuted,",
        "        }) for answer in (() if analysis is None else analysis.answers)),",
        "    })",
        "    values['complete'] = values['complete'] and status != 'pending'",
    ]


def emit_derivation(emitter, prefix, binding, plan):
    constants = []
    for index, checked in enumerate(plan.constants):
        name = prefix + f"_constant_{index}"
        lines = [
            "environment = {}",
            "reads = cognition_reads(session, codec, actor)",
            *environment(emitter, binding, checked),
            f"return codec.term({checked.result.name!r}, {pure_expression(emitter, checked)})",
        ]
        emitter.function(name, "session, codec, actor", lines)
        constants.append(name)
    lines = [
        "reads = cognition_reads(session, codec, actor)",
        "environment = {name: codec.value(value) for name, value in bindings}",
    ]
    indent = ""
    for index, (variable, checked) in enumerate(plan.each):
        lines.append(indent + "meter.spend(work=1)")
        lines.extend(indent + line for line in environment(emitter, binding, checked))
        value = pure_expression(emitter, checked)
        lines.append(indent + f"seen_{index} = set()")
        lines.append(indent + f"for item_{variable} in {value}:")
        indent += "    "
        lines.extend(
            [
                indent + "meter.spend(work=1)",
                indent + f"if item_{variable} in seen_{index}: continue",
                indent + f"seen_{index}.add(item_{variable})",
                indent + f"environment[{variable!r}] = item_{variable}",
            ]
        )
    lines.append(indent + "meter.spend(work=1)")
    lines.extend(indent + line for line in environment(emitter, binding, plan.where))
    lines.append(indent + f"if {pure_expression(emitter, plan.where)}:")
    indent += "    "
    lines.extend(indent + line for line in environment(emitter, binding, plan.conclusion))
    values = ", ".join(
        f"({key!r}, codec.term({kind!r}, environment[{key!r}]))" for key, kind in plan.variables
    )
    lines.append(
        indent
        + f"yield tuple(sorted(({values}{',' if values else ''}))), {plan.polarity!r}, "
        + f"codec.term({plan.conclusion.result.name!r}, "
        + pure_expression(emitter, plan.conclusion)
        + ")"
    )
    emitter.function(prefix + "_resolve", "session, codec, actor, bindings, meter", lines)
    return (
        f"Derivation({plan.rule!r}, ({', '.join(constants)}{',' if constants else ''}), "
        f"{prefix}_resolve)"
    )
