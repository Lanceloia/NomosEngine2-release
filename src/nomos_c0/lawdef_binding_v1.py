"""Expand finite authored LawDefs before family-specific C0 type checking."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame, C0SourceContext, C0SourceIndex
from .compile_budget_v1 import COMPILE_BUDGET
from .composable_value_v1 import _MAX_INT

_FAMILIES = frozenset({"action", "direct_event", "direct_actor_event", "due_event", "seat_view"})
_TYPES = {"bool": bool, "int": int, "str": str}
_MAX_TEMPLATE_DEPTH = 64


def _row(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise C0LawError(f"{label} has missing or unknown fields")
    return value


def _references(value: object, depth: int = 0) -> set[str]:
    if depth > _MAX_TEMPLATE_DEPTH:
        raise C0LawError("LawDef body is too deeply nested")
    if type(value) is dict:
        if set(value) == {"arg"}:
            name = value["arg"]
            if type(name) is not str or not name:
                raise C0LawError("LawDef formal reference is malformed")
            return {name}
        result: set[str] = set()
        for item in value.values():
            result.update(_references(item, depth + 1))
        return result
    if type(value) is list:
        result: set[str] = set()
        for item in value:
            result.update(_references(item, depth + 1))
        return result
    return set()


def _expand(value: object, arguments: dict[str, object], depth: int = 0) -> object:
    if depth > _MAX_TEMPLATE_DEPTH:
        raise C0LawError("LawDef body is too deeply nested")
    if type(value) is dict:
        if set(value) == {"arg"}:
            return {"const": arguments[value["arg"]]}
        return {key: _expand(item, arguments, depth + 1) for key, item in value.items()}
    if type(value) is list:
        return [_expand(item, arguments, depth + 1) for item in value]
    return value


@dataclass(frozen=True)
class _Definition:
    family: str
    formals: dict[str, str]
    body: dict[str, object]
    context: C0SourceContext | None


@dataclass(frozen=True)
class C0LawInstantiation:
    body: dict[str, object]
    context: C0SourceContext | None


class C0LawDefinitions:
    """A closed set of definitions used only while constructing a Program."""

    def __init__(
        self,
        declarations: object,
        *,
        contexts: tuple[C0SourceContext | None, ...] | None = None,
    ) -> None:
        if type(declarations) is not list or not declarations:
            raise C0LawError("Program needs finite LawDefs")
        COMPILE_BUDGET.check("law_definitions", len(declarations), stage="LawDef binding")
        if contexts is None:
            contexts = (None,) * len(declarations)
        if (
            type(contexts) is not tuple
            or len(contexts) != len(declarations)
            or any(
                context is not None and type(context) is not C0SourceContext for context in contexts
            )
        ):
            raise C0LawError("LawDef origins do not match declarations")
        definitions: dict[str, _Definition] = {}
        for raw, context in zip(declarations, contexts, strict=True):
            row = _row(raw, {"name", "family", "formals", "body"}, "LawDef")
            name, family = row["name"], row["family"]
            formals, body = row["formals"], row["body"]
            if (
                type(name) is not str
                or not name
                or name in definitions
                or type(family) is not str
                or family not in _FAMILIES
                or type(formals) is not dict
                or any(
                    type(key) is not str or not key or type(value) is not str or value not in _TYPES
                    for key, value in formals.items()
                )
                or type(body) is not dict
            ):
                raise C0LawError("LawDef declaration is malformed or repeated")
            expected = {"value"} if family in ("action", "seat_view") else {"law"}
            if set(body) != expected or _references(body) != set(formals):
                raise C0LawError("LawDef body or formal use is not closed")
            definitions[name] = _Definition(family, dict(formals), body, context)
        self._definitions = definitions

    def instantiate(self, family: str, use: object) -> dict[str, object]:
        row = _row(use, {"ref", "args"}, "LawDef use")
        ref, arguments = row["ref"], row["args"]
        definition = self._definitions.get(ref) if type(ref) is str else None
        if definition is None or definition.family != family or type(arguments) is not dict:
            raise C0LawError("LawDef use names a foreign family or malformed arguments")
        if set(arguments) != set(definition.formals):
            raise C0LawError("LawDef use has missing or extra arguments")
        for name, tag in definition.formals.items():
            value = arguments[name]
            if type(value) is not _TYPES[tag] or (tag == "int" and not 0 <= value <= _MAX_INT):
                raise C0LawError("LawDef argument has the wrong type or range")
        return _expand(definition.body, arguments)

    def bind(
        self,
        family: str,
        use: object,
        *,
        binding: C0OriginFrame | None = None,
        port: C0OriginFrame | None = None,
        origins: tuple[C0OriginFrame, ...] = (),
    ) -> C0LawInstantiation:
        body = self.instantiate(family, use)
        ref = use["ref"]
        definition = self._definitions[ref]
        context = definition.context
        if type(origins) is not tuple or any(type(frame) is not C0OriginFrame for frame in origins):
            raise C0LawError("LawDef binding origins are malformed")
        if context is None and binding is None and port is None and not origins:
            return C0LawInstantiation(body, None)
        frames = []
        if binding is not None:
            frames.append(replace(binding, arguments=tuple(sorted(use["args"].items()))))
        frames.extend(origins)
        if port is not None:
            frames.append(port)
        frames.append(
            C0OriginFrame(
                "law_definition", ref, f"lawdefs.{ref}", context.locate("") if context else None
            )
        )
        if context is not None:
            physical = dict(context.aliases)[""]
            value_key = "value" if family in ("action", "seat_view") else "law"
            context = C0SourceContext(
                context.index, (("", (*physical, "body", value_key)),), tuple(frames)
            )
        else:
            # An unlocated definition must not borrow its caller's coordinates.
            context = C0SourceContext(C0SourceIndex({}), frames=tuple(frames))
        return C0LawInstantiation(body, context)
