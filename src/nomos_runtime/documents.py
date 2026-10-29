"""Bounded closed YAML/JSON data with shared author table and alias semantics."""

import re
from pathlib import Path

import yaml

from .document_tables import lower_tables

MAX_BYTES = 4 * 1024 * 1024
MAX_NODES = 131072
MAX_DEPTH = 64


class DocumentLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self._completed_nodes = set()
        self._document_nodes = 0
        self._document_depth = 0

    def _count_node(self):
        self._document_nodes += 1
        if self._document_nodes > MAX_NODES:
            raise ValueError("document exceeds the structure limit")

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.get_event()
            original = self.anchors.get(event.anchor)
            if original is None or id(original) not in self._completed_nodes:
                raise ValueError("document has an undefined or recursive alias")

            def expand(node, depth=0):
                if self._document_depth + depth > MAX_DEPTH + 1:
                    raise ValueError("document exceeds the structure limit")
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

            return expand(original)
        self._count_node()
        self._document_depth += 1
        try:
            if self._document_depth > MAX_DEPTH + 1:
                raise ValueError("document exceeds the structure limit")
            node = super().compose_node(parent, index)
            self._completed_nodes.add(id(node))
            return node
        finally:
            self._document_depth -= 1

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if type(key) is not str or key in result:
                raise ValueError("document has a non-string or duplicate key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


# Words such as on/off remain ordinary identifiers.
DocumentLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in rules if tag != "tag:yaml.org,2002:bool"]
    for first, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
DocumentLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"), list("tTfF")
)


def closed_data(value, *, depth=0, remaining=None):
    remaining = [MAX_NODES] if remaining is None else remaining
    remaining[0] -= 1
    if depth > MAX_DEPTH or remaining[0] < 0:
        raise ValueError("document exceeds the structure limit")
    if type(value) in (str, int, bool, type(None)):
        return
    if type(value) not in (dict, list):
        raise ValueError("document requires closed text/integer/boolean/null/record/list values")
    for child in value.values() if type(value) is dict else value:
        closed_data(child, depth=depth + 1, remaining=remaining)


def read_data(path):
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
        raise ValueError("document is empty or exceeds the byte limit")
    return parse_data(content.decode("utf-8"))


def parse_data(content):
    """Read bounded closed input data without any compiler or filesystem access."""
    if type(content) is not str or not content or len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("document is empty or exceeds the byte limit")
    loader = DocumentLoader(content)
    try:
        node = loader.get_single_node()
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("document must be a mapping")
        node, _ = lower_tables(node, loader, max_depth=MAX_DEPTH, max_nodes=MAX_NODES)
        data = loader.construct_object(node, deep=True)
        closed_data(data)
        return data
    except (yaml.YAMLError, RecursionError) as error:
        raise ValueError("document could not be parsed") from error
    finally:
        loader.dispose()
