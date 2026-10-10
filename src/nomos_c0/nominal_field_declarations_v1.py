"""Normalize compact named field declarations before nominal type checking."""

from __future__ import annotations

import re

from .author_contract_v1 import C0LawError

_DECLARATION = re.compile(r"([A-Za-z][A-Za-z0-9_]*)[ \t]+([A-Za-z][A-Za-z0-9_]*)")


def normalize_record_field(raw: object, *, record: object, index: int) -> dict[str, object]:
    if type(raw) is dict:
        return raw
    if type(raw) is str:
        match = _DECLARATION.fullmatch(raw.strip(" \t"))
        if match is not None:
            type_name, field_name = match.groups()
            return {"name": field_name, "type": type_name}
    raise C0LawError(
        f"Lib record {record!r} field[{index}] needs a 'TypeName field_name' declaration"
    )
