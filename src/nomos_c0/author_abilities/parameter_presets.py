"""Expand explicit, typed fixed-parameter presets into ordinary ability bindings."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace

from .expression_syntax import ExpressionSource, _identifier
from .opening import value_node

_MAX_EXPANDED_ITEMS = 131072


def _fail(context, path, expected, actual):
    span = None if context is None else context.locate(path)
    ExpressionSource("", path, span).fail("ParameterPreset", 0, expected, repr(actual)[:1000])


def preset_definition(lib, source, selected, context, path):
    """Resolve only an explicit preset selection, including before set expansion."""
    name = selected.get("preset")
    presets = source.get("presets", {})
    if (
        "definition" in selected
        or not _identifier(name)
        or not isinstance(presets, Mapping)
        or name not in presets
    ):
        _fail(context, path + ".preset", "one existing preset, without definition", name)
    preset = presets[name]
    if (
        not isinstance(preset, Mapping)
        or set(preset) != {"definition", "with"}
        or type(preset["definition"]) is not str
        or not isinstance(lib.get("abilities"), Mapping)
        or preset["definition"] not in lib["abilities"]
    ):
        _fail(context, "presets." + name, "ordinary ability definition and complete with", preset)
    return preset["definition"]


def expand_parameter_presets(lib, source, table, symbols, context=None):
    """Validate every base and patch; preserve inherited and overridden field origins."""
    presets = source.get("presets", {})
    if not isinstance(presets, Mapping):
        _fail(context, "presets", "named parameter presets", presets)
    aliases = {} if context is None else dict(context.aliases)
    count = 0

    def reserve(path):
        nonlocal count
        count += 1
        if count > _MAX_EXPANDED_ITEMS:
            _fail(context, path, "bounded preset expansion", count)

    def origin(logical, original):
        if context is not None:
            physical = context.indexed_path(original)
            if physical is not None:
                aliases[logical] = physical

    def validate(plan, value, path):
        try:
            value_node(table, plan, value, symbols)
        except ValueError as error:
            diagnostic = getattr(error, "diagnostic", None)
            suffix = "".join(
                f"[{p}]" if type(p) is int else "." + p for p in getattr(diagnostic, "path", ())
            )
            _fail(context, path + suffix, "complete " + plan.name + ": " + str(error), value)

    parameters = {}
    for name, preset in presets.items():
        path = "presets." + str(name)
        if not _identifier(name):
            _fail(context, path, "valid preset name", name)
        reserve(path)
        definition = preset_definition(lib, source, {"preset": name}, context, path)
        declaration = lib["abilities"][definition]
        declared = declaration.get("parameters", {}) if isinstance(declaration, Mapping) else None
        supplied = preset["with"]
        if (
            not isinstance(declared, Mapping)
            or not isinstance(supplied, Mapping)
            or set(supplied) != set(declared)
        ):
            _fail(context, path + ".with", "exact ordinary ability parameter bindings", supplied)
        plans = {}
        for parameter, type_name in declared.items():
            if (
                not _identifier(parameter)
                or type(type_name) is not str
                or type_name not in dict(table.definitions)
            ):
                _fail(context, path + ".with", "declared parameter name/type", parameter)
            plans[parameter] = table[type_name]
            validate(plans[parameter], supplied[parameter], path + ".with." + parameter)
        parameters[name] = plans

    def clone(value, logical, original):
        reserve(logical)
        origin(logical, original)
        if type(value) is dict:
            return {
                key: clone(child, logical + "." + key, original + "." + key)
                for key, child in value.items()
            }
        if type(value) is list:
            return [
                clone(child, f"{logical}[{i}]", f"{original}[{i}]") for i, child in enumerate(value)
            ]
        return deepcopy(value)

    def merge(plan, base, patch, logical, inherited, local):
        if plan.kind != "record":
            validate(plan, patch, local)
            return clone(patch, logical, local)
        fields = dict(plan.fields)
        if not isinstance(patch, Mapping) or set(patch) - set(fields):
            _fail(context, local, "subset of " + plan.name + " record fields", patch)
        reserve(logical)
        origin(logical, local)
        return {
            field: merge(
                child,
                base[field],
                patch[field],
                logical + "." + field,
                inherited + "." + field,
                local + "." + field,
            )
            if field in patch
            else clone(base[field], logical + "." + field, inherited + "." + field)
            for field, child in plan.fields
        }

    result = {key: value for key, value in source.items() if key != "presets"}
    if not isinstance(source.get("use"), Mapping):
        _fail(context, "use", "named ordinary executable selections", source.get("use"))
    result["use"] = dict(source["use"])
    for name, selected in source["use"].items():
        if not isinstance(selected, Mapping) or "preset" not in selected:
            continue
        path = "use." + str(name)
        reserve(path)
        definition = preset_definition(lib, source, selected, context, path)
        preset_name = selected["preset"]
        base = presets[preset_name]["with"]
        patch = selected.get("with", {})
        plans = parameters[preset_name]
        if not isinstance(patch, Mapping) or set(patch) - set(plans):
            _fail(context, path + ".with", "subset of declared preset parameters", patch)
        supplied = {}
        for parameter, plan in plans.items():
            logical = path + ".with." + parameter
            inherited = "presets." + preset_name + ".with." + parameter
            supplied[parameter] = (
                merge(plan, base[parameter], patch[parameter], logical, inherited, logical)
                if parameter in patch
                else clone(base[parameter], logical, inherited)
            )
            validate(plan, supplied[parameter], logical)
        result["use"][name] = {
            **{key: value for key, value in selected.items() if key != "preset"},
            "definition": definition,
            "with": supplied,
        }
        origin(path + ".definition", "presets." + preset_name + ".definition")
    updated = None if context is None else replace(context, aliases=tuple(aliases.items()))
    return result, updated
