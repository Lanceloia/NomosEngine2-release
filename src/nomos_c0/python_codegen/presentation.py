"""Emit display readers, formats and pure hints from a checked presentation plan."""

from nomos_c0.author_abilities.tabletop_components import value_format

from .input_bindings import InputBindings


class DisplayEmitter:
    def __init__(self, emitter):
        self.emitter, self.plan = emitter, emitter.presentation
        self.reads, self.indices = [], {}

    def read(self, plan):
        key = (
            plan.title,
            plan.zone,
            plan.source,
            plan.name,
            plan.field,
            plan.type_name,
            plan.fold,
            plan.select,
            repr(plan.display),
        )
        if key in self.indices:
            return self.indices[key]
        index = self.indices[key] = len(self.reads)
        if plan.source == "reports":
            lines = [f"return frame.reports({plan.name!r})"]
        else:
            kind = plan.source
            name = plan.name if kind in ("information", "projection", "context") else ""
            lines = [
                f"available, value = frame.source({kind!r}, {name!r})",
                "if not available: return False, None",
            ]
            if kind == "context":
                lines.append(f"value = value[{plan.field!r}]")
            elif kind == "self":
                lines.append(f"value = value[{plan.name!r}]")
            elif kind == "ending" and plan.name != "result":
                lines.append(f"value = value.{plan.name}")
            if plan.select is not None:
                lines.append(f"value = value.{plan.select}")
            lines.append(f"return True, frame.encode({plan.type_name!r}, value)")
        name = f"_display_read_{index}"
        self.emitter.function(name, "frame", lines)
        self.reads.append(
            f"DisplayRead({plan.title!r}, {plan.zone!r}, {plan.type_name!r}, {name}, "
            f"{plan.fold!r}, {plan.display!r})"
        )
        return index

    def action(self, index, name, metadata):
        emitter = self.emitter
        plan = next(plan for plan in emitter.program.abilities if plan.name == name)
        views = emitter.action_views[name]
        lines = [
            "controlled = actor",
            "actor = session.actor_reference(controlled)",
            "binding = None if request is None else request_binding(session, controlled, request)",
            f"_, _, record = session._entry(controlled, {name!r}, binding)",
            *InputBindings(emitter).environment(plan, views),
            "environment.update(form.values)",
            "ready = {field.name for field in form.fields if field.ready}",
            "hints, previews = {}, []",
        ]
        inputs = []

        def ready_for(*expressions):
            names = tuple(sorted({name for expr in expressions for name, _ in expr.inputs}))
            return f"set({names!r}) <= environment.keys()"

        for input_name, spec in metadata.inputs:
            item = plan.inputs.definition(input_name)
            kind = emitter.program.table[item.type_name]
            element_type = kind.element.name if item.kind in ("subset", "sequence") else kind.name
            static = {
                "label": spec.label,
                "captions": dict(spec.options),
                "icons": dict(spec.icons),
                "fixed_label": spec.fixed_label,
                "suggest_label": spec.suggest_label or "采用建议值",
                "invalid_label": spec.invalid_label,
                "local_edit": (
                    item.kind == "subset"
                    and len(plan.inputs.inputs) == 1
                    and item.constraint is None
                    and not metadata.previews
                    and spec.allocation is None
                    and spec.suggestion is None
                    and spec.limit is None
                ),
            }
            inputs.append(
                f"DisplayInput({input_name!r}, {kind.name!r}, {element_type!r}, {static!r})"
            )
            hint_lines = ["values = {}"]
            for expr, attribute in ((spec.suggestion, "suggested"), (spec.limit, "limit")):
                if expr is not None:
                    hint_lines.extend(
                        [
                            f"if {ready_for(expr)}:",
                            f"    values[{attribute!r}] = frame.encode({expr.result.name!r}, "
                            f"{emitter.expression(expr)})",
                            "else: values['presentation_pending'] = True",
                        ]
                    )
            if spec.allocation is not None:
                allocation = spec.allocation
                row = allocation.targets.result.element
                key_type = dict(row.fields)[allocation.key].name
                available = ready_for(allocation.targets, allocation.total, allocation.minimum)
                hint_lines.extend(
                    [
                        f"if {available}:",
                        f"    targets = {emitter.expression(allocation.targets)}",
                        f"    rows = [(frame.encode({key_type!r}, item.{allocation.key}), "
                        f"item.{allocation.label}, item.{allocation.capacity}) "
                        "for item in targets]",
                        "    values['allocation'] = frame.allocation(rows, "
                        f"{emitter.expression(allocation.total)}, "
                        f"{emitter.expression(allocation.minimum)}, "
                        f"unordered={allocation.targets.result.kind == 'set'!r})",
                        "else: values['presentation_pending'] = True",
                    ]
                )
            error_label = spec.invalid_label or "当前输入显示配置无效，请检查作者声明。"
            lines.extend(
                [
                    f"if {input_name!r} in ready:",
                    "    try:",
                    *("        " + line for line in hint_lines),
                    "    except InputDisplayError as error:",
                    f"        values = {{'error': {error_label!r}, 'error_code': error.code}}",
                    f"    hints[{input_name!r}] = values",
                ]
            )
        for title, expr in metadata.previews:
            lines.extend(
                [
                    f"if {ready_for(expr)}:",
                    f"    previews.append({{'title': {title!r}, 'type_name': {expr.result.name!r}, "
                    f"'data': frame.encode({expr.result.name!r}, {emitter.expression(expr)})}})",
                ]
            )
        lines.append("return hints, previews")
        function = f"_display_action_{index}"
        emitter.function(function, "session, actor, form, request, frame", lines)
        spec = {
            "title": metadata.title,
            "description": metadata.description,
            "target": metadata.target,
            "icon": metadata.icon,
            "surface": metadata.surface,
            "board": metadata.board,
            "group": metadata.group,
        }
        return (
            f"DisplayAction({name!r}, {spec!r}, "
            f"({', '.join(inputs)}{',' if inputs else ''}), {function})"
        )

    def emit(self):
        plan, emitter = self.plan, self.emitter
        panels = tuple(self.read(panel) for panel in plan.panels)
        marks = tuple((self.read(mark.read), mark.icon, mark.tone) for mark in plan.seat_marks)
        self_badge = None if plan.self_badge is None else self.read(plan.self_badge)
        reveal = None
        if plan.seat_reveal is not None:
            item = plan.seat_reveal
            fields = dict(emitter.program.table[item.read.type_name].element.fields)
            reveal = (
                self.read(item.read),
                item.reference_field,
                item.badge_field,
                fields[item.badge_field].name,
            )
        details = []
        for item in plan.seat_details:
            fields = dict(emitter.program.table[item.read.type_name].element.fields)
            details.append(
                (
                    self.read(item.read),
                    item.reference_field,
                    tuple((name, fields[name].name) for name in item.fields),
                )
            )
        cues = tuple(
            {
                "read": self.read(item.read),
                "mode": item.mode,
                "icon": item.icon,
                "nonempty": item.nonempty,
                "emphasis": item.emphasis,
                "category": item.category,
                "group_label": item.group_label,
                "group_field": item.group_field,
                "group_read": None if item.group_read is None else self.read(item.group_read),
                "actor_field": item.actor_field,
                "source": item.read.source,
            }
            for item in plan.timeline
        )
        boards = tuple(
            {
                "name": item.name,
                "title": item.title,
                "read": self.read(item.read),
                "owner": item.owner,
                "reserve": item.reserve,
                "unit": item.unit,
                "icon": item.icon,
                "motion": item.motion,
                "groups": tuple(
                    {
                        "name": group.name,
                        "title": group.title,
                        "key": group.key,
                        "label": group.label,
                        "quantity": group.quantity,
                        "labels": dict(group.labels),
                    }
                    for group in item.groups
                ),
                "pools": tuple((name, self.read(read)) for name, read in item.pools),
            }
            for item in plan.boards
        )
        actions = [
            self.action(index, name, meta) for index, (name, meta) in enumerate(plan.actions)
        ]
        rules = None
        if plan.rules is not None:
            title, sections, sources = plan.rules
            rules = {
                "title": title,
                "sections": [{"title": t, "text": text} for t, text in sections],
                "sources": [{"title": t, "url": url} for t, url in sources],
            }
        specification = {
            "title": plan.title,
            "description": plan.description,
            "labels": dict(plan.labels),
            "result_label": plan.result_label,
            "rules": rules,
            "cognition_recap": plan.cognition_recap,
        }
        formats = {
            name: value_format(emitter.program.table, name, plan.components, dict(plan.labels))
            for name, _ in emitter.program.table.definitions
        }

        # Anonymous result/record-child types can occur in previews and seat details.
        seen = set()

        def add(kind):
            if kind.name in seen:
                return
            seen.add(kind.name)
            if kind.name not in formats:
                formats[kind.name] = value_format(
                    emitter.program.table, kind.name, plan.components, dict(plan.labels)
                )
            for _, child in (*kind.fields, *kind.cases):
                add(child)
            if kind.element is not None:
                add(kind.element)

        for _, kind in emitter.program.table.definitions:
            add(kind)
        for read in (*plan.panels, *(item.read for item in plan.timeline)):
            if read.type_name is not None:
                add(emitter.program.table[read.type_name])
        for _, metadata in plan.actions:
            for _, expr in metadata.previews:
                add(expr.result)
        cognition = (
            {}
            if emitter.cognition is None
            else {
                binding.name: {"view": binding.view_type, "proposition": binding.proposition_type}
                for binding in emitter.cognition.bindings
            }
        )
        return (
            f"CompiledDisplay(PROGRAM, {specification!r}, {formats!r}, "
            f"({', '.join(self.reads)}{',' if self.reads else ''}), {panels!r}, "
            f"({', '.join(actions)}{',' if actions else ''}), {marks!r}, {self_badge!r}, "
            f"{reveal!r}, {tuple(details)!r}, {cues!r}, {boards!r}, {cognition!r})"
        )


def definition(emitter):
    return "None" if emitter.presentation is None else DisplayEmitter(emitter).emit()
