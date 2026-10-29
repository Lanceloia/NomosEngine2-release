"""Check explicit receipt collections without changing information authority."""

from collections.abc import Mapping

from .expression_syntax import ExpressionSource, _identifier


def compile_report_collections(lib, source, table, signatures, context=None):
    def fail(path, expected, actual):
        span = None if context is None else context.locate(path)
        ExpressionSource("", path, span).fail("ReportCollection", 0, expected, repr(actual))

    declarations = source.get("report_collections", {})
    if not isinstance(declarations, Mapping):
        fail("report_collections", "named collections", declarations)
    result = []
    for name, declaration in declarations.items():
        path = f"report_collections.{name}"
        if (
            not _identifier(name)
            or not isinstance(declaration, Mapping)
            or set(declaration) != {"type", "channels"}
            or type(declaration["type"]) is not str
            or declaration["type"] not in dict(table.definitions)
            or type(declaration["channels"]) is not list
            or not declaration["channels"]
        ):
            fail(path, "{type: declared nominal type, channels: nonempty list}", declaration)
        channels = []
        for index, selector in enumerate(declaration["channels"]):
            selected_path = f"{path}.channels[{index}]"
            selected = []
            if type(selector) is str:
                selected.append(selector)
            elif (
                isinstance(selector, Mapping)
                and {"decision_group", "label"} <= set(selector)
                and not set(selector) - {"decision_group", "label", "context"}
                and type(selector["decision_group"]) is str
                and selector["decision_group"] in lib.get("decision_groups", {})
                and _identifier(selector["label"])
            ):
                group = lib["decision_groups"][selector["decision_group"]]
                shared = selector.get("context")
                if "context" in group:
                    binding = (
                        source.get("contexts", {}).get(shared) if type(shared) is str else None
                    )
                    if (
                        not isinstance(binding, Mapping)
                        or binding.get("definition") != group["context"]
                    ):
                        fail(selected_path, "selected instance of the group's context", shared)
                elif "context" in selector:
                    fail(selected_path, "no context for this group", shared)
                for member in group["alternatives"]:
                    matches = [
                        alias
                        for alias, use in source["use"].items()
                        if use.get("definition") == member and use.get("context") == shared
                    ]
                    if len(matches) != 1:
                        fail(selected_path, f"one selected {member} in context {shared!r}", matches)
                    channel = f"{matches[0]}.{selector['label']}"
                    if ("reports", channel) in signatures:
                        selected.append(channel)
                if not selected:
                    fail(selected_path, "at least one member delivering this label", selector)
            else:
                fail(
                    selected_path,
                    "delivery channel or decision_group/context/label selector",
                    selector,
                )
            for channel in selected:
                signature = signatures.get(("reports", channel))
                if signature is None or signature[1].endswith(".opening-information"):
                    fail(selected_path, "selected action delivery channel", channel)
                if table[signature[0]].type_id != table[declaration["type"]].type_id:
                    fail(selected_path, f"nominal type {declaration['type']}", signature[0])
                if channel in channels:
                    fail(selected_path, "non-overlapping delivery channels", channel)
                channels.append(channel)
        result.append((name, declaration["type"], tuple(channels)))
    return tuple(result)
