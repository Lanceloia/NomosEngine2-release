"""Freeze explicit Source parts and compile them through the sole C0 pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .author_contract_v1 import C0LawError
from .author_document_v1 import (
    _MAX_BYTES,
    _MAX_DEPTH,
    _MAX_NODES,
    C0AssembledSource,
    C0AuthorDocument,
    C0SourceIndex,
    parse_author_document,
)
from .source_schema_v1 import (
    SOURCE_LIST_SECTIONS,
    SOURCE_SCHEMA,
    SOURCE_SECTIONS,
)


@dataclass(frozen=True)
class C0SourceBundle:
    lib: C0AuthorDocument
    ports: C0AuthorDocument
    source: C0AssembledSource
    assets: C0AuthorDocument


def _node_count(value, depth=0):
    if depth > _MAX_DEPTH:
        raise C0LawError("Source bundle exceeds the structure depth limit")
    if type(value) is dict:
        return 1 + len(value) + sum(_node_count(child, depth + 1) for child in value.values())
    if type(value) is list:
        return 1 + sum(_node_count(child, depth + 1) for child in value)
    return 1


def _location(document, path):
    span = document.spans[path]
    return f"{span.file}:{span.line}:{span.column}"


def _identity(section, row):
    if type(row) is str:
        return ("symbol", row)
    if type(row) is dict:
        keys = (
            ("kind",)
            if section in {"actor_templates", "opening_constructions"}
            else ("name", "family")
        )
        for key in keys:
            if type(row.get(key)) is str:
                return (key, row[key])
    # Full shape/expanded-identity checking remains the Source compiler's responsibility.
    return None


def read_source_bundle(path: Path) -> C0SourceBundle:
    """Resolve only explicit paths, freeze once, reject duplicate declarations."""
    cache = {}
    total_bytes = total_nodes = 0

    def load(selected):
        nonlocal total_bytes, total_nodes
        selected = selected.resolve()
        if selected in cache:
            raise C0LawError(f"Source bundle selects the same file twice: {selected}")
        if selected.suffix not in {".yaml", ".json"}:
            raise C0LawError(f"Source bundle document must be YAML or JSON: {selected}")
        try:
            text = selected.read_text(encoding="utf-8")
            document = parse_author_document(text, file=str(selected), format=selected.suffix[1:])
        except (OSError, ValueError) as error:
            raise C0LawError(f"Source bundle cannot load {selected}: {error}") from error
        total_bytes += len(text.encode("utf-8"))
        total_nodes += _node_count(document.to_data())
        if total_bytes > _MAX_BYTES or total_nodes > _MAX_NODES:
            raise C0LawError("Source bundle exceeds the aggregate document budget")
        cache[selected] = document
        return document

    manifest = load(Path(path))
    row = manifest.to_data()
    if (
        set(row) != {"schema", "source_schema", "lib", "ports", "assets", "source_parts"}
        or row["schema"] != "c0.source_bundle.v1"
        or row["source_schema"] != SOURCE_SCHEMA
        or type(row["source_parts"]) is not list
        or not 1 <= len(row["source_parts"]) <= 256
    ):
        raise C0LawError(f"Source bundle manifest is malformed: {manifest.file}")

    def resolve(name):
        if type(name) is not str or not name or Path(name).is_absolute():
            raise C0LawError(f"Source bundle requires an explicit relative path: {name!r}")
        return Path(manifest.file).parent / name

    lib, ports, assets = (load(resolve(row[key])) for key in ("lib", "ports", "assets"))
    parts = tuple(load(resolve(name)) for name in row["source_parts"])
    data = {"schema": SOURCE_SCHEMA}
    spans = {(): manifest.spans[()], ("schema",): manifest.spans["source_schema",]}
    original_paths = {("schema",): ("source_schema",)}
    seen = {}

    def copy_spans(document, prefix, destination):
        for original, span in document.spans.items():
            if original[: len(prefix)] == prefix:
                logical = destination + original[len(prefix) :]
                spans[logical] = span
                if logical != original:
                    original_paths[logical] = original

    for part in parts:
        fragment = part.to_data()
        unknown = set(fragment) - SOURCE_SECTIONS
        if unknown:
            key = sorted(unknown)[0]
            raise C0LawError(
                f"Unknown Source fragment section {key!r} at {_location(part, (key,))}"
            )
        for section, value in fragment.items():
            if section not in SOURCE_LIST_SECTIONS:
                if section in data:
                    raise C0LawError(
                        f"Duplicate Source section {section!r} at {_location(part, (section,))}; "
                        f"first at {spans[section,].file}:{spans[section,].line}"
                    )
                data[section] = value
                copy_spans(part, (section,), (section,))
                continue
            if type(value) is not list:
                raise C0LawError(
                    f"Source fragment {section} must be a list at {_location(part, (section,))}"
                )
            if section not in data:
                data[section] = []
                spans[section,] = part.spans[section,]
            for index, declaration in enumerate(value):
                identity = _identity(section, declaration)
                token = (section, identity)
                location = _location(part, (section, index))
                if identity is not None and token in seen:
                    raise C0LawError(
                        f"Duplicate Source declaration {identity!r} at {location}; "
                        f"first at {seen[token]}"
                    )
                if identity is not None:
                    seen[token] = location
                offset = len(data[section])
                data[section].append(declaration)
                copy_spans(part, (section, index), (section, offset))
    if _node_count(data) > _MAX_NODES:
        raise C0LawError("Assembled Source exceeds the structure budget")
    source = C0AssembledSource(manifest, parts, data, C0SourceIndex(spans, original_paths))
    return C0SourceBundle(lib, ports, source, assets)


def compile_source_bundle(bundle: C0SourceBundle):
    """Compile rules without binding the frozen opening Assets."""
    from .declarative_graph_ports_v0 import check_graph_ports
    from .declarative_nominal_v0 import check_nominal_lib
    from .owner_graph_v1 import compile_owner_graph

    if type(bundle) is not C0SourceBundle:
        raise C0LawError("Compilation requires a checked Source bundle")
    checked = check_nominal_lib(bundle.lib, bundle.source.to_data().get("actor_domains"))
    library = check_graph_ports(bundle.ports, checked)
    return compile_owner_graph(library, bundle.source)
