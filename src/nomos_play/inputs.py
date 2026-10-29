"""Browser selections bind current generated forms, without compiler input plans."""

import json
from dataclasses import dataclass

from nomos_runtime.errors import AdmissionError
from nomos_runtime.expressions import ValueBindingError
from nomos_runtime.ordering import canonical


def describe(value, labels, style=None):
    style = style or {}
    if style.get("kind") == "optional":
        return (
            describe(value, labels, style["value"])
            if value is not None
            else labels.get("null", "暂无")
        )
    if style.get("kind") == "reference" or style.get("reference"):
        return value["label"]
    if type(value) is dict:
        fields = style.get("fields", {}) if style.get("kind") == "record" else {}
        return {
            labels.get(key, key): describe(item, labels, fields.get(key, {}).get("format", {}))
            for key, item in value.items()
        }
    if type(value) is list:
        return [describe(item, labels, style.get("element", {})) for item in value]
    if value is None:
        return labels.get("null", "暂无")
    if type(value) is bool:
        return labels.get("true" if value else "false", "是" if value else "否")
    return labels.get(value, value) if type(value) is str else value


def caption(spec, value):
    return spec["captions"].get(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


@dataclass
class Construction:
    fields: list
    choices: dict
    complete: bool
    previews: list


def construct(display, ability, selections, request=None, *, tolerant=False):
    metadata = display.definition.actions[ability]
    items = {item.name: item for item in metadata.inputs}
    if type(selections) is not dict or set(selections) - items.keys():
        raise AdmissionError("InvalidInputs", "only declared selected fields allowed")
    fields, chosen = [], {}
    labels = display.definition.specification["labels"]

    def result(form, complete):
        return Construction(
            fields,
            chosen,
            complete,
            [
                {"title": p["title"], "data": p["data"], "format": display.format(p["type_name"])}
                for p in form["previews"]
            ],
        )

    for _ in range(len(items) + 1):
        native, form = display._form(ability, chosen, request=request)
        if native.complete:
            return result(form, True)
        current = next((field for field in native.fields if field.ready), None)
        if current is None:
            raise AdmissionError("MissingBinding", "no input has satisfied dependencies")
        spec = next(field for field in form["fields"] if field["name"] == current.name)
        field = {
            key: value for key, value in spec.items() if key not in ("options", "captions", "icons")
        }
        if "error_code" in field:
            if not tolerant:
                raise AdmissionError(field["error_code"], "current input display is invalid")
            fields.append(field)
            return result(form, False)
        pool = None if current.pool is None else sorted(current.pool, key=canonical)
        if pool is None:
            field["type"] = current.type_name
        else:
            field["options"] = [
                {
                    "id": option["index"],
                    "data": option["data"],
                    "label": caption(spec, option["data"])
                    or describe(
                        option["data"], labels, display.format(items[current.name].element_type)
                    ),
                    "format": display.format(items[current.name].element_type),
                    "icon": spec["icons"].get(
                        json.dumps(option["data"], ensure_ascii=False, separators=(",", ":"))
                    ),
                }
                for option in spec["options"]
            ]
        fixed = pool is not None and (
            current.kind == "member"
            and len(pool) == 1
            or current.kind == "subset"
            and current.minimum == min(current.maximum, len(pool))
            and current.minimum in (0, len(pool))
        )
        forced = None
        if fixed:
            forced = (
                pool[0] if current.kind == "member" else frozenset(pool if current.maximum else ())
            )
            shown = display.encode(current.type_name, forced)
            field.update(
                fixed=True,
                value=describe(shown, labels, field["format"]),
                data=shown,
                fixed_label=spec["fixed_label"] or caption(spec, shown),
            )
        fields.append(field)
        if current.name not in selections and not fixed:
            return result(form, False)
        try:
            if current.name not in selections:
                selected = forced
            elif pool is None:
                selected = display.decode(current.type_name, selections[current.name])
            else:
                indexes = (
                    [selections[current.name]]
                    if current.kind == "member"
                    else selections[current.name]
                )
                if type(indexes) is not list or any(
                    type(i) is not int or not 0 <= i < len(pool) for i in indexes
                ):
                    raise AdmissionError("InvalidSelection", "select current option indices")
                if current.kind == "subset" and len(indexes) != len(set(indexes)):
                    raise AdmissionError("DuplicateSelection", "select each member once")
                values = [pool[index] for index in indexes]
                selected = (
                    values[0]
                    if current.kind == "member"
                    else frozenset(values)
                    if current.kind == "subset"
                    else tuple(values)
                )
            candidate = {**chosen, current.name: selected}
            display.session.choice_form(display.actor, ability, candidate, request=request)
        except (AdmissionError, ValueBindingError) as error:
            if not tolerant:
                raise
            field.update(
                error=spec["invalid_label"] or "当前输入不符合规则，请调整。",
                error_code=error.code
                if isinstance(error, AdmissionError)
                else error.diagnostic.code,
            )
            return result(form, False)
        chosen = candidate
    raise AdmissionError("MissingBinding", "input construction did not terminate")
