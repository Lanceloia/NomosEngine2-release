"""Lower explicit YAML tables to data, retaining physical cell locations for compilers."""

import re

import yaml

_COLUMN = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*")
_MAP = "tag:yaml.org,2002:map"
_SEQ = "tag:yaml.org,2002:seq"
_STR = "tag:yaml.org,2002:str"


def lower_tables(node, loader, *, max_depth, max_nodes):
    origins = {}
    count = 0

    def fail(where, message):
        mark = where.start_mark
        raise ValueError(f"author table at {mark.line + 1}:{mark.column + 1}: {message}")

    def tick(where):
        nonlocal count
        count += 1
        if count > max_nodes:
            fail(where, "expanded document exceeds the structure limit")

    def lower(current, path, depth):
        tick(current)
        if depth > max_depth:
            fail(current, "structure depth exceeded")
        origins[id(current)] = path
        if current.tag == "!table":
            if not isinstance(current, yaml.MappingNode):
                fail(current, "columns and rows mapping required")
            entries = {}
            for key, value in current.value:
                name = loader.construct_object(key, deep=True)
                if type(name) is not str or name in entries:
                    fail(key, "duplicate or non-string table key")
                entries[name] = value
            if set(entries) != {"columns", "rows"}:
                fail(current, "exact columns and rows required")
            headers, rows = entries["columns"], entries["rows"]
            if not isinstance(headers, yaml.SequenceNode) or not headers.value:
                fail(headers, "nonempty column list required")
            if not isinstance(rows, yaml.SequenceNode):
                fail(rows, "row list required")
            columns = []
            for header in headers.value:
                value = loader.construct_object(header, deep=True)
                if type(value) is not str or not _COLUMN.fullmatch(value):
                    fail(header, "column must be a named record path")
                column = tuple(value.split("."))
                if any(
                    column[: len(other)] == other or other[: len(column)] == column
                    for other in columns
                ):
                    fail(header, "duplicate or overlapping column paths")
                columns.append(column)
            result = yaml.SequenceNode(_SEQ, [], current.start_mark, current.end_mark)
            origins[id(result)] = path
            for index, row in enumerate(rows.value):
                if not isinstance(row, yaml.SequenceNode) or len(row.value) != len(columns):
                    fail(row, f"row needs exactly {len(columns)} cells")
                physical = (*path, "rows", index)
                record = yaml.MappingNode(_MAP, [], row.start_mark, row.end_mark)
                tick(row)
                origins[id(record)] = physical
                for offset, (column, cell) in enumerate(zip(columns, row.value, strict=True)):
                    target = record
                    for key in column[:-1]:
                        child = next(
                            (value for name, value in target.value if name.value == key), None
                        )
                        if child is None:
                            tick(row)
                            tick(row)
                            child = yaml.MappingNode(_MAP, [], row.start_mark, row.end_mark)
                            origins[id(child)] = physical
                            target.value.append(
                                (yaml.ScalarNode(_STR, key, row.start_mark, row.end_mark), child)
                            )
                        target = child
                    target.value.append(
                        (
                            yaml.ScalarNode(_STR, column[-1], cell.start_mark, cell.end_mark),
                            lower(cell, (*physical, offset), depth + len(column) + 1),
                        )
                    )
                    tick(cell)
                result.value.append(record)
            return result
        if isinstance(current, yaml.MappingNode):
            current.value = [
                (key, lower(value, (*path, loader.construct_object(key, deep=True)), depth + 1))
                for key, value in current.value
            ]
        elif isinstance(current, yaml.SequenceNode):
            current.value = [
                lower(value, (*path, index), depth + 1) for index, value in enumerate(current.value)
            ]
        return current

    return lower(node, (), 0), origins
