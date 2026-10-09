"""Compile-only scoring definitions with explicit Action slots and scalar formals."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame, C0SourceContext, C0SourceIndex
from .composable_value_v1 import _MAX_INT
from .finite_appraisal_v1 import check_finite_appraisal_shape
from .lawdef_binding_v1 import _expand, _references, _row

_SCALARS = {"bool": bool, "int": int, "str": str}


@dataclass(frozen=True)
class _Definition:
    formals: tuple[tuple[str, str], ...]
    entries: tuple[str, ...]
    profile: str
    context: C0SourceContext | None


class C0AppraisalDefinitions:
    """Templates lower to ordinary finite profiles; Run never evaluates a template."""

    def __init__(
        self,
        declarations: object,
        *,
        contexts: tuple[C0SourceContext | None, ...] | None = None,
    ) -> None:
        if type(declarations) is not list or len(declarations) > 64:
            raise C0LawError("appraisal definitions must be a finite list")
        contexts = (None,) * len(declarations) if contexts is None else contexts
        if (
            type(contexts) is not tuple
            or len(contexts) != len(declarations)
            or any(item is not None and type(item) is not C0SourceContext for item in contexts)
        ):
            raise C0LawError("appraisal definition origins do not match declarations")
        self._definitions: dict[str, _Definition] = {}
        for raw, context in zip(declarations, contexts, strict=True):
            row = _row(
                raw,
                {"name", "formals", "entries", "fallback_entry", "tie_order", "rules"},
                "appraisal definition",
            )
            name, formals, entries = row["name"], row["formals"], row["entries"]
            if (
                type(name) is not str
                or not name
                or name in self._definitions
                or type(formals) is not dict
                or len(formals) > 64
                or any(
                    type(key) is not str or not key or type(tag) is not str or tag not in _SCALARS
                    for key, tag in formals.items()
                )
                or type(entries) is not list
                or not 1 <= len(entries) <= 128
                or any(type(entry) is not str or not entry for entry in entries)
                or len(set(entries)) != len(entries)
            ):
                raise C0LawError("appraisal definition signature is malformed or repeated")
            profile = {
                "name": name,
                "seat": name,
                "fallback_entry": row["fallback_entry"],
                "tie_order": row["tie_order"],
                "rules": row["rules"],
            }
            check_finite_appraisal_shape(profile, seat=name, entries=tuple(entries))
            if _references(profile) != set(formals):
                raise C0LawError("appraisal definition formal use is not closed")
            self._definitions[name] = _Definition(
                tuple(formals.items()), tuple(entries), json.dumps(profile), context
            )

    def bind(
        self, raw: object, *, source_context: C0SourceContext | None = None
    ) -> tuple[dict, C0SourceContext | None]:
        row = _row(raw, {"name", "seat", "definition", "entries"}, "appraisal binding")
        if any(type(row[key]) is not str or not row[key] for key in ("name", "seat")):
            raise C0LawError("appraisal binding needs a profile name and seat")
        use = _row(row["definition"], {"ref", "args"}, "appraisal definition use")
        definition = self._definitions.get(use["ref"]) if type(use["ref"]) is str else None
        args, entries = use["args"], row["entries"]
        if definition is None or type(args) is not dict or type(entries) is not dict:
            raise C0LawError("appraisal binding names an undeclared definition or malformed inputs")
        if set(args) != {name for name, _ in definition.formals}:
            raise C0LawError("appraisal binding has missing or extra arguments")
        for name, tag in definition.formals:
            value = args[name]
            if type(value) is not _SCALARS[tag] or (tag == "int" and not 0 <= value <= _MAX_INT):
                raise C0LawError("appraisal argument has the wrong type or range")
        if (
            set(entries) != set(definition.entries)
            or any(type(value) is not str or not value for value in entries.values())
            or len(set(entries.values())) != len(entries)
        ):
            raise C0LawError("appraisal binding must map each Action slot once")
        profile = _expand(json.loads(definition.profile), args)
        profile.update(name=row["name"], seat=row["seat"])
        profile["fallback_entry"] = entries[profile["fallback_entry"]]
        profile["tie_order"] = [entries[slot] for slot in profile["tie_order"]]
        for rule in profile["rules"]:
            rule["entry"] = entries[rule["entry"]]
        context = definition.context
        if context is not None or source_context is not None:
            binding_span = source_context.locate("definition") if source_context else None
            frames = (
                *(source_context.frames if source_context else ()),
                C0OriginFrame(
                    "appraisal_binding",
                    row["name"],
                    "definition",
                    binding_span,
                    tuple(sorted(args.items())),
                ),
                C0OriginFrame(
                    "appraisal_entries",
                    row["seat"],
                    "entries",
                    source_context.locate("entries") if source_context else None,
                    tuple(sorted(entries.items())),
                ),
                C0OriginFrame(
                    "appraisal_definition",
                    use["ref"],
                    "appraisal_definitions",
                    context.locate("") if context else None,
                ),
            )
            context = C0SourceContext(
                context.index if context else C0SourceIndex({}),
                context.aliases if context else (),
                frames,
            )
        return profile, context
