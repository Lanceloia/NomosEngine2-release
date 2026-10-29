"""Typed visual components describe authorized values, not world or execution rules."""

import re
from copy import deepcopy
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

TABLE_ICONS = frozenset(
    (
        "plus",
        "minus",
        "back",
        "restart",
        "check",
        "coins",
        "diamond",
        "star",
        "user",
        "users",
        "x",
        "shield",
        "sword",
        "moon",
        "eye",
        "flask",
        "flag",
        "crown",
    )
)


@dataclass(frozen=True)
class TableComponent:
    type_name: str
    kind: str
    specification: dict


def _check_value_captions(value_type, captions):
    from .tabletop_presentation import _text

    choices = (
        {"true", "false"}
        if value_type.kind == "bool"
        else (set(value_type.choices) if value_type.kind == "enum" else None)
    )
    if choices is None or type(captions) is not dict or set(captions) != choices:
        raise C0LawError("value captions require all boolean or enum choices")
    for caption in captions.values():
        _text(caption)


def _check_sentence(sentence, fields):
    from .tabletop_presentation import _text

    if type(sentence) is not list or not 1 <= len(sentence) <= 32:
        raise C0LawError("sentence requires a bounded list of text and fields")
    for part in sentence:
        if type(part) is str:
            _text(part)
        elif (
            type(part) is not dict
            or set(part) != {"field"}
            or type(part["field"]) is not str
            or part["field"] not in fields
        ):
            raise C0LawError("sentence must name a displayed field")


def compile_components(table, declarations):
    from .frontend import row
    from .tabletop_presentation import _text

    if type(declarations) is not dict:
        raise C0LawError("components require named value types")
    result = []
    for name, spec in declarations.items():
        if type(name) is not str or name not in dict(table.definitions) or type(spec) is not dict:
            raise C0LawError("component requires a declared value type")
        value_type = table[name]
        kind = spec.get("kind")
        fields = dict(value_type.fields)
        if kind == "resources":
            row(spec, {"kind", "fields"}, path="component." + name)
            if value_type.kind != "record" or type(spec["fields"]) is not dict:
                raise C0LawError("resources require a record")
            if set(spec["fields"]) != set(fields) or any(
                p.kind != "int" or p.minimum is None or p.minimum < 0 for p in fields.values()
            ):
                raise C0LawError("resources require exact nonnegative integer fields")
            for style in spec["fields"].values():
                row(style, {"label", "color", "symbol"}, path="resource")
                _text(style["label"])
                if (
                    type(style["color"]) is not str
                    or re.fullmatch(r"#[0-9a-fA-F]{6}", style["color"]) is None
                    or style["symbol"]
                    not in ("diamond", "square", "triangle", "hexagon", "circle", "star")
                ):
                    raise C0LawError("resource requires a hex color and supported token symbol")
        elif kind == "card":
            row(spec, {"kind", "label", "fields"}, {"resources"}, path="component." + name)
            _text(spec["label"])
            columns = spec["fields"]
            if (
                value_type.kind != "record"
                or type(columns) is not dict
                or set(columns) - {"identity", "score", "group", "bonus", "cost"}
                or not {"identity", "score"} <= set(columns)
                or any(type(f) is not str or f not in fields for f in columns.values())
            ):
                raise C0LawError("card fields must name actual record fields")
            if any(fields[columns[k]].kind != "int" for k in ("identity", "score")):
                raise C0LawError("card identity and score require integer fields")
            if "group" in columns and fields[columns["group"]].kind not in ("int", "enum"):
                raise C0LawError("card group requires an integer or enum")
            if "bonus" in columns and fields[columns["bonus"]].kind != "enum":
                raise C0LawError("card bonus requires an enum")
            if "cost" in columns or "bonus" in columns or "resources" in spec:
                resource_name = spec.get("resources")
                if type(resource_name) is not str:
                    raise C0LawError("card needs a named resource component")
                resources = declarations.get(resource_name, {})
                if resources.get("kind") != "resources":
                    raise C0LawError("card needs its declared resource component")
                if "cost" in columns and fields[columns["cost"]].name != spec["resources"]:
                    raise C0LawError("card cost has the wrong resource type")
                if "bonus" in columns and not set(fields[columns["bonus"]].choices) <= set(
                    resources.get("fields", {})
                ):
                    raise C0LawError("card bonus is absent from its resource palette")
        elif kind == "resource_choice":
            row(spec, {"kind", "resources"}, path="component." + name)
            if type(spec["resources"]) is not str:
                raise C0LawError("resource choice needs a named resource component")
            resources = declarations.get(spec["resources"], {})
            if (
                value_type.kind != "enum"
                or resources.get("kind") != "resources"
                or not set(value_type.choices) <= set(resources.get("fields", {}))
            ):
                raise C0LawError("resource choice requires compatible enum and palette")
        elif kind == "allocation":
            from .tabletop_allocation import allocation_shape

            row(spec, {"kind", "fields"}, path="component." + name)
            allocation_shape(value_type, spec["fields"])
        elif kind == "table":
            row(spec, {"kind", "columns"}, path="component." + name)
            columns = spec["columns"]
            if (
                value_type.kind != "record"
                or type(columns) is not dict
                or not columns
                or set(columns) - set(fields)
            ):
                raise C0LawError("table columns must name actual record fields")
            for field, style in columns.items():
                if type(style) is str:
                    _text(style)
                    continue
                row(style, {"label", "values"}, path="component." + name + "." + field)
                _text(style["label"])
                choices = (
                    {"true", "false"}
                    if fields[field].kind == "bool"
                    else set(fields[field].choices)
                    if fields[field].kind == "enum"
                    else None
                )
                if (
                    choices is None
                    or type(style["values"]) is not dict
                    or set(style["values"]) != choices
                ):
                    raise C0LawError("table value captions require all boolean or enum choices")
                for caption in style["values"].values():
                    _text(caption)
        elif kind == "record":
            row(spec, {"kind", "fields"}, {"sentence"}, path="component." + name)
            if (
                value_type.kind != "record"
                or type(spec["fields"]) is not dict
                or not spec["fields"]
                or set(spec["fields"]) - set(fields)
            ):
                raise C0LawError("record component needs actual named fields")
            for field, style in spec["fields"].items():
                row(
                    style,
                    {"label"},
                    {"omit_empty", "values"},
                    path="component." + name + "." + field,
                )
                _text(style["label"])
                if "values" in style:
                    _check_value_captions(fields[field], style["values"])
                if (
                    type(style.get("omit_empty", False)) is not bool
                    or style.get("omit_empty", False)
                    and fields[field].kind not in ("optional", "set", "sequence")
                ):
                    raise C0LawError("omit_empty requires a collection or optional field")
            if "sentence" in spec:
                _check_sentence(spec["sentence"], spec["fields"])
        elif kind == "variant":
            row(spec, {"kind", "cases"}, path="component." + name)
            cases = dict(value_type.cases)
            if (
                value_type.kind != "variant"
                or type(spec["cases"]) is not dict
                or set(spec["cases"]) != set(cases)
            ):
                raise C0LawError("variant component requires exact declared cases")
            for tag, style in spec["cases"].items():
                row(
                    style,
                    {"label"},
                    {"description", "fields", "sentence"},
                    path="component." + name + "." + tag,
                )
                _text(style["label"])
                if "description" in style:
                    _text(style["description"])
                captions = style.get("fields", {})
                if type(captions) is not dict or set(captions) - set(dict(cases[tag].fields)):
                    raise C0LawError("variant captions must name actual case fields")
                for caption in captions.values():
                    _text(caption)
                if "sentence" in style:
                    _check_sentence(style["sentence"], dict(cases[tag].fields))
        elif kind == "badge":
            if value_type.kind == "ref":
                row(spec, {"kind", "icon"}, path="component." + name)
                if type(spec["icon"]) is not str or spec["icon"] not in TABLE_ICONS:
                    raise C0LawError("badge requires a supported icon")
            elif value_type.kind == "enum":
                row(spec, {"kind", "items"}, path="component." + name)
                if type(spec["items"]) is not dict or set(spec["items"]) != set(value_type.choices):
                    raise C0LawError("enum badges require exact declared choices")
                for style in spec["items"].values():
                    row(style, {"icon"}, {"label", "color", "description"}, path="badge")
                    if type(style["icon"]) is not str or style["icon"] not in TABLE_ICONS:
                        raise C0LawError("badge requires a supported icon")
                    if "label" in style:
                        _text(style["label"])
                    if "description" in style:
                        _text(style["description"])
                    if "color" in style and (
                        type(style["color"]) is not str
                        or re.fullmatch(r"#[0-9a-fA-F]{6}", style["color"]) is None
                    ):
                        raise C0LawError("badge color requires a hex color")
            else:
                raise C0LawError("badges require nominal enums or references")
        else:
            raise C0LawError("unsupported visual component")
        result.append(TableComponent(name, kind, deepcopy(spec)))
    return tuple(result)


def value_format(table, type_name, components, labels, depth=0):
    """Only value structure is exported; there are no entity-owner dereferences."""
    if depth > 64:
        raise C0LawError("component type depth exceeded")
    plan = table[type_name]
    by_name = {component.type_name: component for component in components}
    if plan.kind in ("set", "sequence"):
        return {
            "kind": "collection",
            "element": value_format(table, plan.element.name, components, labels, depth + 1),
        }
    component = by_name.get(type_name)
    if component is not None:
        spec = component.specification
        result = {**spec}
        if plan.kind == "ref":
            result["reference"] = True
        if spec.get("resources"):
            result["palette"] = by_name[spec["resources"]].specification["fields"]
        if component.kind == "table":
            result["columns"] = {
                field: style if type(style) is str else style["label"]
                for field, style in spec["columns"].items()
            }
            result["cells"] = {
                field: {
                    **value_format(
                        table, dict(plan.fields)[field].name, components, labels, depth + 1
                    ),
                    **({"value_labels": style["values"]} if type(style) is dict else {}),
                }
                for field, style in spec["columns"].items()
            }
        if component.kind == "allocation":
            fields = dict(plan.fields)
            row_fields = dict(fields[spec["fields"]["rows"]].element.fields)
            result["target_format"] = value_format(
                table, row_fields[spec["fields"]["target"]].name, components, labels, depth + 1
            )
        if component.kind == "record":
            result["fields"] = {
                field: {
                    **style,
                    "format": value_format(
                        table, dict(plan.fields)[field].name, components, labels, depth + 1
                    ),
                    **({"value_labels": style["values"]} if "values" in style else {}),
                }
                for field, style in spec["fields"].items()
            }
        if component.kind == "variant":
            result["cases"] = {
                tag: {
                    "label": spec["cases"][tag]["label"],
                    "description": spec["cases"][tag].get("description"),
                    "sentence": spec["cases"][tag].get("sentence"),
                    "field_labels": spec["cases"][tag].get("fields", {}),
                    "fields": {
                        field: value_format(table, type_.name, components, labels, depth + 1)
                        for field, type_ in case.fields
                    },
                }
                for tag, case in plan.cases
            }
        return result
    if plan.kind == "record":
        return {
            "kind": "record",
            "fields": {
                name: {
                    "label": labels.get(name, name),
                    "format": value_format(table, field.name, components, labels, depth + 1),
                }
                for name, field in plan.fields
            },
        }
    if plan.kind == "int":
        return {"kind": "number", "min": plan.minimum, "max": plan.maximum}
    if plan.kind == "bool":
        return {"kind": "boolean"}
    if plan.kind == "enum":
        return {
            "kind": "enum",
            "options": [{"value": v, "label": labels.get(v, v)} for v in plan.choices],
        }
    if plan.kind == "ref":
        return {"kind": "reference", "icon": "user"}
    if plan.kind == "optional":
        return {
            "kind": "optional",
            "value": value_format(table, plan.element.name, components, labels, depth + 1),
        }
    if plan.kind == "variant":
        return {
            "kind": "variant",
            "cases": {
                tag: {
                    "label": labels.get(tag, tag),
                    "fields": {
                        field: value_format(table, type_.name, components, labels, depth + 1)
                        for field, type_ in child.fields
                    },
                }
                for tag, child in plan.cases
            },
        }
    return {"kind": "scalar"}


def compile_panel_display(table, type_name, spec):
    """Per-read styling cannot change a value type or acquire another read."""
    from .frontend import row
    from .tabletop_presentation import _text

    if spec is None:
        return None
    if type(spec) is not dict or type_name is None:
        raise C0LawError("panel display requires a typed visible value")
    value = table[type_name]
    kind = spec.get("kind")
    if kind == "track":
        row(spec, {"kind", "steps", "icon", "tone"}, path="panel.display")
        if (
            value.kind != "int"
            or value.minimum is None
            or value.minimum < 0
            or type(spec["steps"]) is not int
            or not 1 <= spec["steps"] <= 64
        ):
            raise C0LawError("track needs a nonnegative integer and 1..64 display steps")
    elif kind == "indicator":
        row(spec, {"kind", "items"}, path="panel.display")
        if (
            value.kind != "bool"
            or type(spec["items"]) is not dict
            or set(spec["items"]) != {"true", "false"}
        ):
            raise C0LawError("indicator needs a Boolean and both public captions")
        for style in spec["items"].values():
            row(style, {"label", "icon", "tone"}, path="panel.display.indicator")
            _text(style["label"])
    else:
        raise C0LawError("panel display requires track or indicator")
    styles = [spec] if kind == "track" else list(spec["items"].values())
    for style in styles:
        if (
            type(style["icon"]) is not str
            or style["icon"] not in TABLE_ICONS
            or style["tone"] not in ("neutral", "positive", "danger", "attention")
        ):
            raise C0LawError("panel display requires a supported icon and tone")
    return deepcopy(spec)
