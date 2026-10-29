"""Assemble author declarations with original-file provenance, before compilation."""

from collections.abc import Mapping
from pathlib import Path

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import (
    C0AssembledSource,
    C0SourceIndex,
    read_author_document,
)

_NAMED = {
    "nomos.author.lib": frozenset(
        {
            "values",
            "entities",
            "abilities",
            "relations",
            "queries",
            "contexts",
            "projections",
            "information",
            "disclosures",
            "processes",
            "terminals",
            "reactions",
            "activities",
            "periodic",
            "schedules",
            "facts",
            "constraints",
            "decision_groups",
            "scopes",
        }
    ),
    "nomos.author.source": frozenset(
        {
            "actors",
            "use",
            "contexts",
            "opening",
            "report_collections",
            "scopes",
            "ability_sets",
            "presets",
        }
    ),
    "nomos.author.ai": frozenset(
        {"strategies", "control", "queries", "predictors", "rankings", "semantics"}
    ),
    "nomos.author.cognition": frozenset({"models", "bindings"}),
    "nomos.tabletop.presentation": frozenset({"labels", "components", "actions", "boards"}),
}
_SINGLE = {
    "nomos.author.lib": frozenset(),
    "nomos.author.source": frozenset({"name", "settlement", "time", "random", "play"}),
    "nomos.author.ai": frozenset(),
    "nomos.author.cognition": frozenset(),
    "nomos.tabletop.presentation": frozenset(
        {"title", "description", "result_label", "seats", "rules", "recap"}
    ),
}
_ORDERED = {"nomos.tabletop.presentation": frozenset({"panels", "timeline"})}
_MAX_FILES = 128
_MAX_BYTES = 8 * 1024 * 1024
_MAX_NODES = 131072


def read_author_modules(path):
    """Load one closed declaration tree; imports never become runtime instructions."""
    path = Path(path).resolve()
    root = path.parent
    active, seen, parts = [], set(), []
    spans, originals, data, origins = {}, {}, {}, {}
    size, nodes = 0, 0

    def fail(file, message):
        raise C0LawError(f"Assembly {file}: {message}")

    def copy_spans(document, source, target):
        for key, span in document.spans.items():
            if key[: len(source)] == source:
                logical = target + key[len(source) :]
                if logical not in spans:
                    spans[logical] = span
                    originals[logical] = span.path
        if len(spans) > _MAX_NODES:
            fail(document.file, "structure budget exceeded")

    def reserve(document, key, value):
        if key in origins:
            fail(document.file, f"duplicate declaration {'.'.join(key)}; first in {origins[key]}")
        origins[key] = document.file
        return value

    def visit(file, expected=None):
        nonlocal size, nodes
        if file in active:
            fail(file, "cyclic imports: " + " -> ".join(str(item) for item in (*active, file)))
        if file in seen:
            fail(file, "module imported more than once")
        if len(seen) >= _MAX_FILES:
            fail(file, "file budget exceeded")
        if not file.is_relative_to(root):
            fail(file, "import escapes the entry directory")
        try:
            size += file.stat().st_size
            if size > _MAX_BYTES:
                fail(file, "byte budget exceeded")
            document = read_author_document(file)
        except (OSError, ValueError) as error:
            fail(file, str(error))
        row = document.to_data()
        nodes += len(document.spans)
        if nodes > _MAX_NODES:
            fail(file, "structure budget exceeded")
        schema = row.get("schema")
        if type(schema) is not str or schema not in _NAMED or expected not in (None, schema):
            fail(file, "expected matching author declaration schema")
        allowed = (
            {"schema", "imports"}
            | _NAMED[schema]
            | _SINGLE[schema]
            | _ORDERED.get(schema, frozenset())
        )
        if schema == "nomos.author.source":
            allowed.update(("objects", "actor_kinds"))
        if set(row) - allowed:
            fail(file, "unsupported declaration sections: " + ", ".join(sorted(set(row) - allowed)))
        imports = row.get("imports", [])
        if type(imports) is not list or any(
            type(item) is not str or not item.strip() or Path(item).is_absolute()
            for item in imports
        ):
            fail(file, "imports requires relative file paths")
        seen.add(file)
        active.append(file)
        parts.append(document)
        for item in imports:
            visit((file.parent / item).resolve(), schema)
        active.pop()
        data["schema"] = schema
        copy_spans(document, ("schema",), ("schema",))
        if () not in spans:
            spans[()] = document.spans[()]
            originals[()] = ()
        for section in sorted(_NAMED[schema]):
            if section not in row:
                continue
            values = row[section]
            if not isinstance(values, Mapping):
                fail(file, section + " requires named declarations")
            merged = data.setdefault(section, {})
            copy_spans(document, (section,), (section,))
            for name, value in values.items():
                merged[name] = reserve(document, (section, name), value)
        for section in sorted(_SINGLE[schema]):
            if section in row:
                data[section] = reserve(document, (section,), row[section])
                copy_spans(document, (section,), (section,))
        for section in sorted(_ORDERED.get(schema, ())):
            if section not in row:
                continue
            entries = row[section]
            if type(entries) is not list:
                fail(file, section + " requires an ordered list")
            merged = data.setdefault(section, [])
            if (section,) not in spans:
                spans[(section,)] = document.spans[(section,)]
                originals[(section,)] = (section,)
            for index, value in enumerate(entries):
                copy_spans(document, (section, index), (section, len(merged)))
                merged.append(value)
        for selection in ("objects", "actor_kinds"):
            if selection not in row:
                continue
            objects = row[selection]
            if type(objects) is not list or any(type(item) is not str for item in objects):
                fail(file, selection + " requires selected sort names")
            selected = data.setdefault(selection, [])
            if (selection,) not in spans:
                spans[(selection,)] = document.spans[(selection,)]
                originals[(selection,)] = (selection,)
            for index, name in enumerate(objects):
                reserve(document, (selection, name), name)
                logical = (selection, len(selected))
                span = document.spans[(selection, index)]
                spans[logical], originals[logical] = span, span.path
                selected.append(name)
        return document

    manifest = visit(path)
    return C0AssembledSource(manifest, tuple(parts), data, C0SourceIndex(spans, originals))


def compile_author_files(lib_path, source_path):
    """Compile declarations only; Assets remain a separate Start input."""
    from .frontend import compile_author_world

    lib, source = read_author_modules(lib_path), read_author_modules(source_path)
    return compile_author_world(
        lib.to_data(), source.to_data(), context=lib.context(), source_context=source.context()
    )
