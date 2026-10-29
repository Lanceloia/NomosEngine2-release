"""Checked presentation references over existing Actor-local read contracts."""

from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .context_state import context_types


@dataclass(frozen=True)
class TablePanel:
    title: str
    zone: str
    source: str
    name: str
    field: str | None = None
    type_name: str | None = None
    fold: bool = False
    select: str | None = None
    display: object | None = None


@dataclass(frozen=True)
class SeatMark:
    read: TablePanel
    icon: str
    tone: str


@dataclass(frozen=True)
class SeatReveal:
    read: TablePanel
    reference_field: str
    badge_field: str


@dataclass(frozen=True)
class SeatDetail:
    read: TablePanel
    reference_field: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class TableCue:
    read: TablePanel
    mode: str
    icon: str
    nonempty: bool = False
    emphasis: bool = False
    category: str = "事件"
    group_label: str | None = None
    group_field: str | None = None
    group_read: TablePanel | None = None
    actor_field: str | None = None


@dataclass(frozen=True)
class TableInput:
    label: str
    options: tuple = ()
    fixed_label: str | None = None
    suggestion: object | None = None
    limit: object | None = None
    invalid_label: str | None = None
    suggest_label: str | None = None
    icons: tuple = ()
    allocation: object | None = None


@dataclass(frozen=True)
class TableAction:
    title: str
    description: str
    inputs: tuple
    target: str | None = None
    previews: tuple = ()
    icon: str | None = None
    surface: str = "dialog"
    board: str | None = None
    group: str | None = None


@dataclass(frozen=True)
class TablePresentation:
    program: object
    title: str
    description: str
    labels: tuple
    panels: tuple
    actions: tuple
    components: tuple = ()
    result_label: str = "结算结果"
    seat_marks: tuple = ()
    self_badge: TablePanel | None = None
    seat_reveal: SeatReveal | None = None
    timeline: tuple = ()
    boards: tuple = ()
    rules: object | None = None
    seat_details: tuple = ()
    cognition_recap: bool = False


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 2000:
        raise C0LawError("presentation requires bounded, nonempty text")
    return value


def _report_channels(program):
    producers = [(p.channel_name, p) for p in program.abilities]
    producers.extend((p.name, p) for p in program.reactions)
    return {
        f"{name}.{call.label}": call.definition.value.result.name
        for name, plan in producers
        for leaf in plan.resolution.leaves()
        for call in leaf.deliveries
    }


def _read_panel(program, panel):
    """One permission/type check serves panels, seat marks and own badges."""
    if (
        type(panel) is not dict
        or set(panel) - {"title", "zone", "source", "fold", "field", "display"}
        or not {"title", "zone", "source"} <= set(panel)
        or type(panel.get("fold", False)) is not bool
        or panel["zone"] not in ("overview", "board", "private", "history")
        or type(panel["source"]) is not dict
        or len(panel["source"]) != 1
    ):
        raise C0LawError("presentation panel requires a zone and one read source")
    schemas = dict(program.entities.entities)
    seats = [schemas[dict(program.actors)[seat]] for seat in program.play.seats]
    source, name = next(iter(panel["source"].items()))
    field, type_name = None, None
    if source == "context":
        if type(name) is not str or name.count(".") != 1:
            raise C0LawError("context panel requires context.public_field")
        name, field = name.split(".")
        plan = next((p for p in program.contexts if p.name == name), None)
        if plan is None or plan.state is None or field not in plan.state.public:
            raise C0LawError("presentation context field is not public")
        type_name = dict(plan.state.fields)[field].name
    elif source == "self":
        if type(name) is not str or any(name not in s.view for s in seats):
            raise C0LawError("presentation self field is not in every seat's own view")
        types = {dict(s.fields)[name].name for s in seats}
        if len(types) != 1:
            raise C0LawError("presentation self field needs the same nominal type in all seats")
        type_name = types.pop()
    elif source == "information":
        plan = next((p for p in program.information if p.name == name), None)
        if plan is None:
            raise C0LawError("presentation names absent opening information")
        type_name = plan.projection.value.result.name
    elif source == "projection":
        plan = next((p for p in program.projections if p.name == name), None)
        if plan is None:
            raise C0LawError("presentation names absent projection")
        target = program.table[plan.viewer_type].sort
        if any(not program.table.accepts_sort(target, s.name) for s in seats):
            raise C0LawError("presentation projection does not accept every table seat")
        type_name = plan.value.result.name
    elif source == "reports":
        channels = _report_channels(program)
        if type(name) is not str or name not in channels:
            raise C0LawError("presentation names absent acquired report channel")
        type_name = f"Sequence<{channels[name]}>"
    elif source == "ending":
        if program.terminal is None or type(name) is not str:
            raise C0LawError("presentation ending requires an authored terminal")
        value = program.terminal.value.result
        if name == "result":
            type_name = value.name
        elif value.kind == "record" and name in dict(value.fields):
            type_name = dict(value.fields)[name].name
        else:
            raise C0LawError("presentation names absent terminal field")
    else:
        raise C0LawError("presentation read source is unsupported")
    if type_name is None:
        raise C0LawError("presentation read requires a nominal value type")
    select = panel.get("field")
    if "field" in panel:
        value = None if type_name is None else program.table[type_name]
        if (
            type(select) is not str
            or value is None
            or value.kind != "record"
            or select not in dict(value.fields)
        ):
            raise C0LawError("presentation field requires an actual visible record field")
        type_name = dict(value.fields)[select].name
    from .tabletop_components import compile_panel_display

    display = compile_panel_display(program.table, type_name, panel.get("display"))
    return TablePanel(
        _text(panel["title"]),
        panel["zone"],
        source,
        name,
        field,
        type_name,
        panel.get("fold", False),
        select,
        display,
    )


def _default_panels(program, labels):
    panels = []
    for context in program.contexts:
        if context.state is not None:
            for field in context.state.public:
                value = program.table[dict(context.state.fields)[field].name]
                panels.append(
                    {
                        "title": labels.get(field, field),
                        "zone": "board",
                        "fold": value.kind == "sequence",
                        "source": {"context": f"{context.name}.{field}"},
                    }
                )
    schemas = dict(program.entities.entities)
    seats = [schemas[dict(program.actors)[seat]] for seat in program.play.seats]
    for field in seats[0].view:
        if all(
            field in s.view and dict(s.fields)[field] == dict(seats[0].fields)[field] for s in seats
        ):
            panels.append(
                {"title": labels.get(field, field), "zone": "private", "source": {"self": field}}
            )
    for item in program.information:
        panels.append(
            {
                "title": labels.get(item.name, item.name),
                "zone": "private",
                "source": {"information": item.name},
            }
        )
    for item in program.projections:
        sort = program.table[item.viewer_type].sort
        if all(program.table.accepts_sort(sort, s.name) for s in seats):
            panels.append(
                {
                    "title": labels.get(item.name, item.name),
                    "zone": "private",
                    "source": {"projection": item.name},
                }
            )
    for name in _report_channels(program):
        panels.append(
            {
                "title": labels.get(name, name),
                "zone": "private",
                "source": {"reports": name},
                "fold": True,
            }
        )
    return panels


def _compile_timeline(program, declaration, labels):
    from .tabletop_components import TABLE_ICONS

    if declaration is None:
        declaration = []
        for item in _default_panels(program, labels):
            read = _read_panel(program, item)
            value = None if read.type_name is None else program.table[read.type_name]
            if read.source == "reports":
                mode = "append"
            elif read.source == "context" and value.kind == "sequence":
                mode = "append"
            elif read.source == "context" and (
                value.kind == "enum"
                or value.kind == "ref"
                or value.kind == "set"
                and value.element.kind == "ref"
            ):
                mode = "change"
            else:
                continue
            declaration.append({"source": item["source"], "title": item["title"], "mode": mode})
    if type(declaration) is not list:
        raise C0LawError("timeline requires an ordered list")
    result = []
    for cue in declaration:
        if (
            type(cue) is not dict
            or set(cue) - {
                "source", "field", "title", "mode", "icon", "nonempty", "emphasis",
                "category", "group_by", "actor_field",
            }
            or not {"source", "title", "mode"} <= set(cue)
        ):
            raise C0LawError("timeline cue requires a source, title and mode")
        read = _read_panel(
            program,
            {
                "source": cue["source"],
                "title": cue["title"],
                "zone": "private",
                **({"field": cue["field"]} if "field" in cue else {}),
            },
        )
        if (
            cue["mode"] not in ("append", "change")
            or type(cue.get("nonempty", False)) is not bool
            or type(cue.get("emphasis", False)) is not bool
            or type(cue.get("icon", "flag")) is not str
            or cue.get("icon", "flag") not in TABLE_ICONS
        ):
            raise C0LawError("timeline cue requires a valid mode and icon")
        if (
            cue["mode"] == "append"
            and read.source != "reports"
            and (read.type_name is None or program.table[read.type_name].kind != "sequence")
        ):
            raise C0LawError("append timeline requires an ordered sequence or acquired reports")
        if (
            cue.get("nonempty", False)
            and read.source != "reports"
            and (
                read.type_name is None
                or program.table[read.type_name].kind not in ("set", "sequence")
            )
        ):
            raise C0LawError("nonempty timeline requires a collection")
        category = _text(cue.get("category", "事件"))
        actor_field = cue.get("actor_field")
        if "actor_field" in cue:
            value_type = program.table[read.type_name]
            if cue["mode"] == "append":
                value_type = value_type.element
            fields = dict(value_type.fields)
            if (
                type(actor_field) is not str or actor_field not in fields
                or fields[actor_field].kind != "ref"
            ):
                raise C0LawError("timeline actor field requires a visible individual reference")
        group_label = group_field = group_read = None
        if "group_by" in cue:
            grouping = cue["group_by"]
            if (
                type(grouping) is not dict
                or set(grouping) not in ({"label", "field"}, {"label", "source"})
            ):
                raise C0LawError("timeline grouping requires a label and field or source")
            group_label = _text(grouping["label"])
            if "field" in grouping:
                group_field = grouping["field"]
                value_type = program.table[read.type_name]
                if cue["mode"] == "append":
                    value_type = value_type.element
                fields = dict(value_type.fields)
                if type(group_field) is not str or group_field not in fields:
                    raise C0LawError("timeline grouping field must exist on the event value")
                group_type = fields[group_field]
            else:
                group_read = _read_panel(program, {
                    "source": grouping["source"], "title": group_label, "zone": "private",
                })
                group_type = program.table[group_read.type_name]
            if group_type.kind not in ("int", "enum", "str"):
                raise C0LawError("timeline grouping requires a scalar key")
        result.append(
            TableCue(
                read,
                cue["mode"],
                cue.get("icon", "flag"),
                cue.get("nonempty", False),
                cue.get("emphasis", False),
                category,
                group_label,
                group_field,
                group_read,
                actor_field,
            )
        )
    if program.terminal is not None:
        result.append(
            TableCue(
                _read_panel(
                    program,
                    {"title": "对局结束", "zone": "private", "source": {"ending": "result"}},
                ),
                "change",
                "flag",
            )
        )
    return tuple(result)


def compile_tabletop_presentation(program, declaration):
    """Display declarations select permission-checked reads, never raw owner fields."""
    if (
        type(declaration) is not dict
        or set(declaration)
        - {
            "schema",
            "title",
            "description",
            "labels",
            "panels",
            "actions",
            "components",
            "result_label",
            "seats",
            "timeline",
            "boards",
            "rules",
            "recap",
        }
        or "schema" not in declaration
        or declaration["schema"] != "nomos.tabletop.presentation"
        or program.play is None
        or program.play.mechanism != "tabletop"
    ):
        raise C0LawError("tabletop presentation requires its schema and compiled play plan")
    labels = declaration.get("labels", {})
    if type(labels) is not dict or any(type(k) is not str for k in labels):
        raise C0LawError("presentation labels require string keys")
    labels = tuple((k, _text(v)) for k, v in labels.items())
    from .tabletop_components import TABLE_ICONS, compile_components

    components = compile_components(program.table, declaration.get("components", {}))
    schemas = dict(program.entities.entities)
    actor_schemas = [schemas[dict(program.actors)[seat]] for seat in program.play.seats]
    if any(schema.reference != "public" for schema in actor_schemas):
        raise C0LawError("tabletop seat selection requires public Actor references")
    panels = []
    declared_panels = (
        declaration["panels"] if "panels" in declaration else _default_panels(program, dict(labels))
    )
    if type(declared_panels) is not list:
        raise C0LawError("presentation panels require an ordered list")
    for panel in declared_panels:
        panels.append(_read_panel(program, panel))
    seat_spec = declaration.get("seats", {})
    if type(seat_spec) is not dict or set(seat_spec) - {"marks", "self_badge", "reveal", "details"}:
        raise C0LawError("seats require marks and optional self_badge")
    marks = seat_spec.get("marks", [])
    if type(marks) is not list:
        raise C0LawError("seat marks require an ordered list")
    seat_marks = []
    for mark in marks:
        if (
            type(mark) is not dict
            or set(mark) - {"source", "field", "label", "icon", "tone"}
            or not {"source", "label", "icon", "tone"} <= set(mark)
        ):
            raise C0LawError("seat mark requires a read source, label, icon and tone")
        read = _read_panel(
            program,
            {
                "title": mark["label"],
                "zone": "private",
                "source": mark["source"],
                **({"field": mark["field"]} if "field" in mark else {}),
            },
        )
        value = None if read.type_name is None else program.table[read.type_name]
        if value is not None and value.kind in ("set", "sequence", "optional"):
            value = value.element
        if (
            value is None
            or value.kind != "ref"
            or any(not program.table.accepts_sort(value.sort, s.name) for s in actor_schemas)
        ):
            raise C0LawError("seat mark must return references compatible with table seats")
        if (
            type(mark["icon"]) is not str
            or mark["icon"] not in TABLE_ICONS
            or type(mark["tone"]) is not str
            or mark["tone"] not in ("neutral", "positive", "danger", "attention")
        ):
            raise C0LawError("seat mark requires a supported icon and tone")
        seat_marks.append(SeatMark(read, mark["icon"], mark["tone"]))
    self_badge = None
    if "self_badge" in seat_spec:
        badge_source = seat_spec["self_badge"]
        if type(badge_source) is not dict:
            raise C0LawError("self_badge needs one acquired read source")
        self_badge = _read_panel(
            program,
            {
                "title": "你的标记",
                "zone": "private",
                "source": {k: v for k, v in badge_source.items() if k != "field"},
                **({"field": badge_source["field"]} if "field" in badge_source else {}),
            },
        )
        if self_badge.type_name is None or program.table[self_badge.type_name].kind != "enum":
            raise C0LawError("self_badge must return a visible enum")
    seat_reveal = None
    if "reveal" in seat_spec:
        spec = seat_spec["reveal"]
        if (
            type(spec) is not dict
            or set(spec) != {"source", "reference", "badge"}
            or type(spec["reference"]) is not str
            or type(spec["badge"]) is not str
        ):
            raise C0LawError("seat reveal requires a terminal source and named record fields")
        read = _read_panel(
            program, {"title": "身份揭晓", "zone": "private", "source": spec["source"]}
        )
        value = None if read.type_name is None else program.table[read.type_name]
        if (
            read.source != "ending"
            or value is None
            or value.kind not in ("set", "sequence")
            or value.element.kind != "record"
        ):
            raise C0LawError("seat reveal requires terminal records")
        fields = dict(value.element.fields)
        reference, badge = fields.get(spec["reference"]), fields.get(spec["badge"])
        if (
            reference is None
            or reference.kind != "ref"
            or any(not program.table.accepts_sort(reference.sort, s.name) for s in actor_schemas)
            or badge is None
            or badge.kind != "enum"
        ):
            raise C0LawError("seat reveal needs compatible seat references and an enum badge")
        seat_reveal = SeatReveal(read, spec["reference"], spec["badge"])
    seat_details = []
    details = seat_spec.get("details", [])
    if type(details) is not list:
        raise C0LawError("seat details require an ordered list")
    for spec in details:
        if type(spec) is not dict or set(spec) != {"source", "reference", "fields", "title"}:
            raise C0LawError("seat detail requires source, reference, fields and title")
        read = _read_panel(
            program, {"title": spec["title"], "zone": "private", "source": spec["source"]}
        )
        value = None if read.type_name is None else program.table[read.type_name]
        if value is None or value.kind not in ("set", "sequence") or value.element.kind != "record":
            raise C0LawError("seat detail requires visible records")
        fields = dict(value.element.fields)
        reference = fields.get(spec["reference"]) if type(spec["reference"]) is str else None
        shown = spec["fields"]
        if (
            reference is None
            or reference.kind != "ref"
            or any(not program.table.accepts_sort(reference.sort, s.name) for s in actor_schemas)
            or type(shown) is not list
            or not shown
            or any(type(f) is not str or f not in fields or f == spec["reference"] for f in shown)
            or len(shown) != len(set(shown))
        ):
            raise C0LawError("seat detail requires a seat Ref and unique visible fields")
        seat_details.append(SeatDetail(read, spec["reference"], tuple(shown)))
    declared_actions = declaration.get("actions", {})
    abilities = {p.name: p for p in program.abilities}
    if type(declared_actions) is not dict or set(declared_actions) - set(abilities):
        raise C0LawError("presentation names an absent Action")
    actions = []
    for name, plan in abilities.items():
        chosen = {p.name for p in plan.inputs.inputs if p.kind != "derive"}
        body = declared_actions.get(name, {})
        if type(body) is not dict:
            raise C0LawError("presentation action requires a mapping")
        body = {"title": dict(labels).get(name, name), "description": "", "inputs": {}, **body}
        if type(body["description"]) is not str or len(body["description"]) > 2000:
            raise C0LawError("presentation description requires bounded text")
        if (
            type(body) is not dict
            or set(body)
            - {"title", "description", "inputs", "target", "preview", "icon", "surface", "group"}
            or not {"title", "description", "inputs"} <= set(body)
        ):
            raise C0LawError("presentation action requires title, description and inputs")
        inputs = body["inputs"]
        if "icon" in body and (type(body["icon"]) is not str or body["icon"] not in TABLE_ICONS):
            raise C0LawError("action requires a supported icon")
        if type(inputs) is not dict or set(inputs) - chosen:
            raise C0LawError("presentation names an absent chosen input")
        if any(type(item) is not dict for item in inputs.values()):
            raise C0LawError("presentation input requires a mapping")
        inputs = {
            key: {"label": dict(labels).get(key, key), **inputs.get(key, {})} for key in chosen
        }
        checked = []
        plan = abilities[name]
        from .effects import EffectCompiler

        local_base = (
            {} if plan.context is None else context_types(plan.context, local=True)
        ) | dict(plan.inputs.base)
        bindings = {**local_base, **{i.name: i.type_name for i in plan.inputs.inputs}}
        compiler = EffectCompiler(
            program.table,
            bindings,
            library=program.queries,
            entities=program.entities,
            actor=plan.actor,
            local_views=plan.views,
        )

        def expression(text, returns, available, location):
            expr = compiler.expression(text, returns, location, context="actor")
            used = {r.root for r in expr.summary.reads} | {plan.actor}
            if used - available:
                raise C0LawError("presentation expression must follow input dependencies")
            return replace(expr, inputs=tuple(i for i in expr.inputs if i[0] in used))

        available = set(local_base)
        for key in plan.inputs.order:
            input_plan = plan.inputs.definition(key)
            if input_plan.kind == "derive":
                available.add(key)
                continue
            item = inputs[key]
            if (
                type(item) is not dict
                or set(item)
                - {
                    "label",
                    "options",
                    "fixed_label",
                    "suggest",
                    "limit",
                    "invalid_label",
                    "suggest_label",
                    "icons",
                    "allocation",
                }
                or "label" not in item
            ):
                raise C0LawError("presentation input requires label and optional value captions")
            options = item.get("options", {})
            if type(options) is not dict or any(type(k) is not str for k in options):
                raise C0LawError("presentation input captions require string value keys")
            icons = item.get("icons", {})
            if (
                type(icons) is not dict
                or set(icons) - set(options)
                or any(type(i) is not str or i not in TABLE_ICONS for i in icons.values())
            ):
                raise C0LawError("input icons require captioned choices and supported icons")
            allocation = None
            component = next((c for c in components if c.type_name == input_plan.type_name), None)
            if "allocation" in item:
                from .tabletop_allocation import compile_allocation

                allocation = compile_allocation(
                    program.table,
                    input_plan,
                    components,
                    item["allocation"],
                    expression,
                    available,
                    f"presentation.{name}.{key}.allocation",
                )
            elif component is not None and component.kind == "allocation":
                raise C0LawError("allocation input requires explicit target metadata")
            checked.append(
                (
                    key,
                    TableInput(
                        _text(item["label"]),
                        tuple((k, _text(v)) for k, v in options.items()),
                        _text(item["fixed_label"]) if "fixed_label" in item else None,
                        expression(
                            item["suggest"],
                            input_plan.type_name,
                            available,
                            f"presentation.{name}.{key}.suggest",
                        )
                        if "suggest" in item
                        else None,
                        expression(
                            item["limit"],
                            input_plan.type_name,
                            available,
                            f"presentation.{name}.{key}.limit",
                        )
                        if "limit" in item
                        else None,
                        _text(item["invalid_label"]) if "invalid_label" in item else None,
                        _text(item["suggest_label"]) if "suggest_label" in item else None,
                        tuple(icons.items()),
                        allocation,
                    ),
                )
            )
            available.add(key)
        first = next((key for key in plan.inputs.order if key in chosen), None)
        inferred_target = (
            first
            if first is not None
            and (
                plan.inputs.definition(first).kind == "member"
                and program.table[plan.inputs.definition(first).type_name].kind in ("ref", "record")
                or body.get("surface") == "seats"
                and plan.inputs.definition(first).kind == "subset"
            )
            else None
        )
        target = body.get("target", inferred_target)
        if target is not None and (
            type(target) is not str
            or target not in chosen
            or plan.inputs.definition(target).kind not in ("member", "subset")
            or next(i for i in plan.inputs.order if i in chosen) != target
        ):
            raise C0LawError("presentation target must be its first chosen member or subset input")
        previews = []
        surface = body.get("surface", "dialog")
        board = None
        if type(surface) is dict and set(surface) == {"board"} and type(surface["board"]) is str:
            board, surface = surface["board"], "board"
        elif surface not in ("dialog", "inline", "choices", "seats", "buttons"):
            raise C0LawError(
                "action surface requires dialog, inline, choices, seats, buttons or a named board"
            )
        if (
            target is not None
            and plan.inputs.definition(target).kind == "subset"
            and surface != "seats"
        ):
            raise C0LawError("subset target requires the seat selection surface")
        if surface == "choices" and (
            target is None or plan.inputs.definition(target).kind != "member"
        ):
            raise C0LawError("choice surface requires its first chosen member target")
        if surface == "buttons" and (
            len(chosen) != 1
            or plan.inputs.definition(first).kind != "member"
            or program.table[plan.inputs.definition(first).type_name].kind not in ("bool", "enum")
        ):
            raise C0LawError("buttons surface requires one boolean or enum member input")
        if surface == "seats":
            if target is None:
                raise C0LawError("seat surface requires a first member or subset target")
            value = program.table[plan.inputs.definition(target).type_name]
            reference = value.element if value.kind == "set" else value
            if reference.kind != "ref" or any(
                not program.table.accepts_sort(reference.sort, schema.name)
                for schema in actor_schemas
            ):
                raise C0LawError("seat target requires compatible table seat references")
        if surface == "board" and (
            len(chosen) != 1
            or next(iter(chosen)) not in dict(checked)
            or dict(checked)[next(iter(chosen))].allocation is None
        ):
            raise C0LawError("board action requires one complete allocation input")
        if type(body.get("preview", {})) is not dict:
            raise C0LawError("presentation preview requires named pure expressions")
        for label, text in body.get("preview", {}).items():
            previews.append(
                (_text(label), expression(text, None, available, f"presentation.{name}.preview"))
            )
        if surface == "buttons" and any(
            read.root not in local_base for _, expr in previews for read in expr.summary.reads
        ):
            raise C0LawError("buttons preview must be available before selecting an input")
        actions.append(
            (
                name,
                TableAction(
                    _text(body["title"]),
                    _text(body["description"]) if body["description"] else "",
                    tuple(checked),
                    target,
                    tuple(previews),
                    body.get("icon", "check"),
                    surface,
                    board,
                    _text(body["group"]) if "group" in body else None,
                ),
            )
        )
    description = declaration.get("description", "")
    if type(description) is not str or len(description) > 2000:
        raise C0LawError("presentation description requires bounded text")
    from .tabletop_boards import compile_boards

    recap = declaration.get("recap", {})
    if (
        type(recap) is not dict
        or set(recap) - {"cognition"}
        or type(recap.get("cognition", False)) is not bool
    ):
        raise C0LawError("recap accepts an explicit boolean cognition option")

    boards = compile_boards(program, declaration.get("boards", {}), _read_panel, _text, TABLE_ICONS)
    for _, action in actions:
        if action.board is None:
            continue
        bound = next((b for b in boards if b.name == action.board), None)
        allocation = action.inputs[0][1].allocation
        key_type = dict(allocation.targets.result.element.fields)[allocation.key].name
        if bound is None or any(group.key_type != key_type for group in bound.groups):
            raise C0LawError("board action requires its board and matching nominal target keys")
    return TablePresentation(
        program,
        _text(declaration.get("title", program.name)),
        description,
        labels,
        tuple(panels),
        tuple(actions),
        components,
        _text(declaration.get("result_label", "结算结果")),
        tuple(seat_marks),
        self_badge,
        seat_reveal,
        _compile_timeline(program, declaration.get("timeline"), dict(labels)),
        boards,
        _compile_rules(declaration.get("rules")),
        tuple(seat_details),
        recap.get("cognition", False),
    )


def _compile_rules(declaration):
    """Public author-written help, never extracted from execution state or comments."""
    from urllib.parse import urlsplit

    if declaration is None:
        return None
    if (
        type(declaration) is not dict
        or set(declaration) != {"title", "sections", "sources"}
        or type(declaration["sections"]) is not list
        or not 1 <= len(declaration["sections"]) <= 24
        or type(declaration["sources"]) is not list
        or len(declaration["sources"]) > 8
    ):
        raise C0LawError("rules require a title, bounded sections and sources")
    sections, sources = [], []
    for section in declaration["sections"]:
        if type(section) is not dict or set(section) != {"title", "text"}:
            raise C0LawError("rule section requires title and public text")
        sections.append((_text(section["title"]), _text(section["text"])))
    for source in declaration["sources"]:
        if type(source) is not dict or set(source) != {"title", "url"}:
            raise C0LawError("rule source requires title and HTTPS URL")
        url = _text(source["url"])
        try:
            parts = urlsplit(url)
            valid = (
                parts.scheme == "https"
                and parts.hostname
                and not parts.username
                and not parts.password
            )
        except ValueError:
            valid = False
        if not valid or any(c.isspace() or ord(c) < 32 for c in url):
            raise C0LawError("rule source requires a public HTTPS URL")
        sources.append((_text(source["title"]), url))
    return (_text(declaration["title"]), tuple(sections), tuple(sources))
