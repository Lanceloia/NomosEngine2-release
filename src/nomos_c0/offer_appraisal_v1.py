"""Compile read-only opportunity meanings separately from world permission."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from .author_contract_v1 import C0LawError
from .composable_value_v1 import C0ValuePorts, C0ValueProgram, compile_value_program


@dataclass(frozen=True)
class C0OfferAppraisal:
    features: tuple[tuple[str, str], ...]
    definitions: Mapping[str, C0ValueProgram]
    bindings: Mapping[str, str]

    def evaluate(self, entry: str, roots: dict[str, object]) -> dict[str, object] | None:
        name = self.bindings.get(entry)
        if name is None:
            return None
        return self.definitions[name].evaluate_admission_outputs(roots)


def compile_offer_appraisal(
    raw: object, *, ports: C0ValuePorts, entries: frozenset[str]
) -> C0OfferAppraisal:
    """Caller supplies only authorized observation ports and actual seat entries."""
    if (
        type(raw) is not dict
        or set(raw) != {"schema", "features", "defaults", "definitions", "bindings", "manual"}
        or raw["schema"] != "c0.offer_appraisal.v1"
    ):
        raise C0LawError("offer appraisal has missing or unknown fields/schema")
    if (
        type(entries) is not frozenset
        or not entries
        or any(type(name) is not str or not name for name in entries)
        or type(ports) is not C0ValuePorts
        or ports.writable_fields
        or ports.writable_paths
    ):
        raise C0LawError("offer appraisal needs read-only ports and current seat entries")
    features, defaults = raw["features"], raw["defaults"]
    definitions, bindings, manual = raw["definitions"], raw["bindings"], raw["manual"]
    if (
        type(features) is not dict
        or not 1 <= len(features) <= 64
        or any(
            type(name) is not str
            or not name.isidentifier()
            or name.startswith("_")
            or type(label) is not str
            or not label
            for name, label in features.items()
        )
        or type(defaults) is not dict
        or set(defaults) != set(ports.outputs)
        or set(features) & set(defaults)
        or any(type(value) not in (int, bool) for value in defaults.values())
        or any(carrier not in (int, bool) for carrier in ports.outputs.values())
    ):
        raise C0LawError("offer appraisal feature/value signature is malformed")
    if (
        type(definitions) is not dict
        or not 1 <= len(definitions) <= 128
        or any(type(name) is not str or not name for name in definitions)
        or type(bindings) is not dict
        or not bindings
        or type(manual) is not list
        or any(type(name) is not str for name in manual)
        or len(manual) != len(set(manual))
        or set(bindings) & set(manual)
        or set(bindings) | set(manual) != entries
        or any(type(name) is not str or name not in definitions for name in bindings.values())
    ):
        raise C0LawError("offer appraisal must classify each actual entry once: binding or manual")
    outputs = {**ports.outputs, **{name: int for name in features}}
    checked_ports = replace(ports, outputs=outputs)
    compiled = {}
    for name, row in definitions.items():
        if type(row) is not dict or set(row) != {"when", "features", "values"}:
            raise C0LawError(f"appraisal definition {name}: malformed fields")
        if (
            type(row["features"]) is not dict
            or not set(row["features"]) <= set(features)
            or type(row["values"]) is not dict
            or not set(row["values"]) <= set(defaults)
        ):
            raise C0LawError(f"appraisal definition {name}: undeclared feature/value")
        body = {
            "schema": "c0.value.v1",
            "bindings": [],
            "guard": row["when"],
            "outputs": {
                **defaults,
                **{feature: 0 for feature in features},
                **row["values"],
                **row["features"],
            },
        }
        try:
            compiled[name] = compile_value_program(
                json.dumps(body), checked_ports, admission_outputs=frozenset(outputs)
            )
        except C0LawError as error:
            raise C0LawError(f"appraisal definition {name}: {error}") from error
    return C0OfferAppraisal(
        tuple(features.items()), MappingProxyType(compiled), MappingProxyType(dict(bindings))
    )
