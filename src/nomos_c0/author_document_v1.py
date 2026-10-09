"""Frozen author locations, separate from semantic data and runtime authority."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import yaml

_MAX_BYTES = 4 * 1024 * 1024
_MAX_NODES = 131072
_MAX_DEPTH = 64
_PATH_PART = re.compile(r"\.([^.[\]]+)|\[([0-9]+)\]")
DocumentPath = tuple[str | int, ...]


def _valid_path(path: object) -> bool:
    return type(path) is tuple and all(
        type(part) is str or type(part) is int and part >= 0 for part in path
    )


@dataclass(frozen=True)
class C0SourceSpan:
    file: str
    digest: str
    path: DocumentPath
    line: int
    column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        if (
            type(self.file) is not str
            or not self.file
            or type(self.digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.digest) is None
            or not _valid_path(self.path)
            or any(
                type(value) is not int or value < 1
                for value in (self.line, self.column, self.end_line, self.end_column)
            )
            or (self.end_line, self.end_column) < (self.line, self.column)
        ):
            raise ValueError("source span is malformed")


@dataclass(frozen=True)
class C0OriginFrame:
    """Compile evidence, not an occurrence or an execution permission."""

    kind: str
    name: str
    path: str
    span: C0SourceSpan | None = None
    arguments: tuple[tuple[str, str | int | bool], ...] = ()

    def __post_init__(self) -> None:
        if (
            any(type(value) is not str for value in (self.kind, self.name, self.path))
            or not self.kind
            or self.span is not None
            and type(self.span) is not C0SourceSpan
            or type(self.arguments) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) not in (str, int, bool)
                for item in self.arguments
            )
            or len({item[0] for item in self.arguments}) != len(self.arguments)
        ):
            raise ValueError("origin frame is malformed")


@dataclass(frozen=True)
class C0SourceIndex:
    """One immutable index shared by compile contexts, never retained by Run."""

    spans: Mapping[DocumentPath, C0SourceSpan]
    original_paths: Mapping[DocumentPath, DocumentPath] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.spans, Mapping)
            or not isinstance(self.original_paths, Mapping)
            or any(
                not _valid_path(key)
                or type(span) is not C0SourceSpan
                or self.original_paths.get(key, key) != span.path
                for key, span in self.spans.items()
            )
            or any(
                key not in self.spans or not _valid_path(path)
                for key, path in self.original_paths.items()
            )
        ):
            raise ValueError("source index is malformed")
        object.__setattr__(self, "spans", MappingProxyType(dict(self.spans)))
        object.__setattr__(self, "original_paths", MappingProxyType(dict(self.original_paths)))


@dataclass(frozen=True)
class C0SourceContext:
    """Compile-only map from logical expression roots to authored structure."""

    index: C0SourceIndex
    aliases: tuple[tuple[str, DocumentPath], ...] = (("", ()),)
    frames: tuple[C0OriginFrame, ...] = ()
    scoped_frames: tuple[tuple[str, tuple[C0OriginFrame, ...]], ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.index) is not C0SourceIndex
            or type(self.aliases) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or not _valid_path(item[1])
                for item in self.aliases
            )
            or len({alias for alias, _ in self.aliases}) != len(self.aliases)
            or type(self.frames) is not tuple
            or any(type(frame) is not C0OriginFrame for frame in self.frames)
            or type(self.scoped_frames) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not tuple
                or any(type(frame) is not C0OriginFrame for frame in item[1])
                for item in self.scoped_frames
            )
            or len({scope for scope, _ in self.scoped_frames}) != len(self.scoped_frames)
        ):
            raise ValueError("source context is not a closed location index")

    def indexed_path(self, logical_path: str) -> DocumentPath | None:
        """Resolve in the assembled index, not in an original document's coordinates."""
        for alias, physical in sorted(self.aliases, key=lambda item: len(item[0]), reverse=True):
            if (
                alias
                and logical_path != alias
                and not logical_path.startswith((alias + ".", alias + "["))
            ):
                continue
            suffix = logical_path[len(alias) :]
            if not alias and suffix:
                suffix = "." + suffix
            position = 0
            parts = []
            for match in _PATH_PART.finditer(suffix):
                if match.start() != position:
                    break
                parts.append(match[1] if match[1] is not None else int(match[2]))
                position = match.end()
            if position != len(suffix):
                return None
            path = physical + tuple(parts)
            # Generated checks and text AST nodes honestly point at their enclosing source.
            while path not in self.index.spans and len(path) > len(physical):
                path = path[:-1]
            if not physical and parts and not path:
                return None
            return path if path in self.index.spans else None
        return None

    def locate(self, logical_path: str) -> C0SourceSpan | None:
        path = self.indexed_path(logical_path)
        return self.index.spans[path] if path is not None else None

    def frames_for(self, path: str) -> tuple[C0OriginFrame, ...]:
        return self.frames + tuple(
            frame
            for scope, frames in sorted(self.scoped_frames, key=lambda item: len(item[0]))
            if path == scope or path.startswith((scope + ".", scope + "["))
            for frame in frames
        )

    def trace(self, path: str) -> tuple[C0OriginFrame, ...]:
        return (*self.frames_for(path), C0OriginFrame("expression", "", path, self.locate(path)))

    def at(self, path: DocumentPath, *, root: str = "") -> C0SourceContext:
        """Use an absolute document path; rebasing does not infer an authored identity."""
        return C0SourceContext(self.index, ((root, path),), self.frames)


def named_source_paths(
    context: C0SourceContext, value: object, *, root: str = ""
) -> C0SourceContext:
    """Map named list sugar at its actual declaration, before expression lowering."""
    physical = dict(context.aliases).get(root)
    if physical is None:
        if root:
            return context
        # Synthetic value programs can map several independent authored expressions.
        for alias, _ in context.aliases:
            node = value
            suffix = "." + alias
            position = 0
            for match in _PATH_PART.finditer(suffix):
                if match.start() != position:
                    break
                part = match[1] if match[1] is not None else int(match[2])
                try:
                    node = node[part]
                except (KeyError, IndexError, TypeError):
                    break
                position = match.end()
            if position == len(suffix):
                context = named_source_paths(context, node, root=alias)
        return context
    aliases = dict(context.aliases)

    def visit(node, logical, path):
        if isinstance(node, Mapping):
            for key, child in node.items():
                location = f"{logical}.{key}" if logical else key
                if key == "output_families" and type(child) in (list, tuple):
                    for index, entry in enumerate(child):
                        if isinstance(entry, Mapping) and type(entry.get("name")) is str:
                            named = f"{location}.{entry['name']}"
                            actual = (*path, key, index)
                            aliases[named] = actual
                            visit(entry, named, actual)
                elif key in ("require", "effects") and type(child) in (list, tuple):
                    for index, entry in enumerate(child):
                        if isinstance(entry, Mapping) and len(entry) == 1:
                            name, body = next(iter(entry.items()))
                            named = f"{location}.{name}"
                            actual = (*path, key, index, name)
                            aliases[named] = actual
                            visit(body, named, actual)
                else:
                    visit(child, location, (*path, key))
        elif type(node) in (list, tuple):
            for index, child in enumerate(node):
                visit(child, f"{logical}[{index}]", (*path, index))

    visit(value, root, physical)
    return C0SourceContext(
        context.index, tuple(aliases.items()), context.frames, context.scoped_frames
    )


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("author document has a non-string key")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(_freeze(item) for item in value)
    if type(value) in (str, int, bool, type(None)) or type(value) is float and math.isfinite(value):
        return value
    raise ValueError("author document contains a non-data value")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class C0AuthorDocument:
    file: str
    digest: str
    data: Mapping[str, object]
    index: C0SourceIndex

    def __post_init__(self) -> None:
        if not isinstance(self.data, Mapping) or type(self.index) is not C0SourceIndex:
            raise ValueError("author document is malformed")
        object.__setattr__(self, "data", _freeze(self.data))

    @property
    def spans(self) -> Mapping[DocumentPath, C0SourceSpan]:
        return self.index.spans

    def to_data(self) -> dict[str, object]:
        """Each compiler gets ordinary strict data, not mutable access to this snapshot."""
        return _thaw(self.data)

    def context(
        self,
        *,
        aliases: tuple[tuple[str, DocumentPath], ...] = (("", ()),),
        frames: tuple[C0OriginFrame, ...] = (),
    ) -> C0SourceContext:
        return C0SourceContext(self.index, aliases, frames)


@dataclass(frozen=True)
class C0AssembledSource:
    """A compilation input with original document spans, not a synthetic file."""

    manifest: C0AuthorDocument
    parts: tuple[C0AuthorDocument, ...]
    data: Mapping[str, object]
    index: C0SourceIndex

    def __post_init__(self) -> None:
        if (
            type(self.manifest) is not C0AuthorDocument
            or type(self.parts) is not tuple
            or not self.parts
            or any(type(part) is not C0AuthorDocument for part in self.parts)
            or not isinstance(self.data, Mapping)
            or type(self.index) is not C0SourceIndex
        ):
            raise ValueError("assembled Source is malformed")
        object.__setattr__(self, "data", _freeze(self.data))

    def to_data(self) -> dict[str, object]:
        return _thaw(self.data)

    def context(self) -> C0SourceContext:
        return C0SourceContext(self.index)


class _DocumentLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self._completed_nodes = set()
        self._document_nodes = 0

    def _count_node(self):
        self._document_nodes += 1
        if self._document_nodes > _MAX_NODES:
            raise ValueError("author document exceeds the structure limit")

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.get_event()
            original = self.anchors.get(event.anchor)
            if original is None or id(original) not in self._completed_nodes:
                raise ValueError("author document has an undefined or recursive alias")

            def expand(node, depth=0):
                if depth > _MAX_DEPTH:
                    raise ValueError("author document exceeds the structure limit")
                self._count_node()
                if isinstance(node, yaml.ScalarNode):
                    return yaml.ScalarNode(node.tag, node.value, event.start_mark, event.end_mark)
                if isinstance(node, yaml.SequenceNode):
                    value = [expand(child, depth + 1) for child in node.value]
                    return yaml.SequenceNode(node.tag, value, event.start_mark, event.end_mark)
                value = [
                    (expand(key, depth + 1), expand(child, depth + 1)) for key, child in node.value
                ]
                return yaml.MappingNode(node.tag, value, event.start_mark, event.end_mark)

            # Expanded nodes point at the alias token, not invented child coordinates.
            return expand(original)
        self._count_node()
        node = super().compose_node(parent, index)
        self._completed_nodes.add(id(node))
        return node

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if type(key) is not str or key in result:
                raise ValueError("author document has a non-string or duplicate key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("author document has a duplicate key")
        result[key] = value
    return result


def parse_author_document(text: str, *, file: str, format: str) -> C0AuthorDocument:
    if type(text) is not str or type(file) is not str or not file or format not in ("yaml", "json"):
        raise ValueError("author document input is malformed")
    encoded = text.encode("utf-8")
    if not encoded or len(encoded) > _MAX_BYTES:
        raise ValueError("author document is empty or exceeds the byte limit")
    digest = hashlib.sha256(encoded).hexdigest()
    loader = _DocumentLoader(text)
    spans = {}
    seen = set()

    def visit(node, path, depth=0):
        if depth > _MAX_DEPTH or len(seen) >= _MAX_NODES:
            raise ValueError("author document exceeds the structure limit")
        if id(node) in seen:
            raise ValueError("author document aliases are not supported")
        seen.add(id(node))
        spans[path] = C0SourceSpan(
            file,
            digest,
            path,
            node.start_mark.line + 1,
            node.start_mark.column + 1,
            node.end_mark.line + 1,
            node.end_mark.column + 1,
        )
        if isinstance(node, yaml.MappingNode):
            keys = set()
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=True)
                if type(key) is not str or key in keys:
                    raise ValueError("author document has a non-string or duplicate key")
                keys.add(key)
                visit(value_node, (*path, key), depth + 1)
        elif isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                visit(item, (*path, index), depth + 1)

    try:
        node = loader.get_single_node()
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("author document must be a mapping")
        visit(node, ())
        data = (
            json.loads(text, object_pairs_hook=_unique_pairs)
            if format == "json"
            else loader.construct_object(node, deep=True)
        )
        if type(data) is not dict:
            raise ValueError("author document must be a mapping")
        return C0AuthorDocument(file, digest, data, C0SourceIndex(spans))
    except (yaml.YAMLError, RecursionError) as error:
        raise ValueError("author document could not be parsed") from error
    finally:
        loader.dispose()


def read_author_document(path: Path) -> C0AuthorDocument:
    if path.suffix not in (".yaml", ".json"):
        raise ValueError("author document must be .json or .yaml")
    return parse_author_document(
        path.read_text(encoding="utf-8"), file=str(path), format=path.suffix[1:]
    )
