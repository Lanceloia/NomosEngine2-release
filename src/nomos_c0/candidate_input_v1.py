"""Explicit, read-only availability signals over already constructed candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .author_contract_v1 import C0LawError
from .composable_action_v1 import C0ValueActionPorts
from .composable_value_v1 import (
    C0ValuePorts,
    C0ValueProgram,
    C0ValueStateError,
    compile_value_program,
)


@dataclass(frozen=True)
class C0CandidateInputPorts:
    symbol: str
    action_template: str
    value_ports: C0ValuePorts


def check_candidate_input(action: C0ValueActionPorts, ports: C0ValuePorts) -> None:
    authority = action.value_ports
    if (
        dict(ports.roots) != dict(authority.roots)
        or ports.writable_fields
        or ports.writable_paths
        or ports.record_types
        or dict(ports.outputs) != {"allowed": bool}
        or ports.readable_paths != ports.admission_readable_paths
        or ports.readable_fields != ports.admission_readable_fields
        or not ports.readable_paths <= authority.admission_readable_paths
        or any(
            dict(authority.participant_groups).get(name) != members
            for name, members in ports.participant_groups
        )
        or any(
            not names <= authority.admission_readable_fields.get(carrier, frozenset())
            for carrier, names in ports.readable_fields.items()
        )
    ):
        raise C0LawError("candidate input exceeds the selected Action's read-only authority")


@dataclass(frozen=True)
class C0CandidateCheck:
    input_symbol: str
    entry: str
    value: C0ValueProgram

    def allows(self, roots: dict[str, object]) -> bool:
        if type(roots.get("payload")) is not self.value._ports.roots["payload"]:
            raise C0ValueStateError("candidate input needs the selected typed Action payload")
        result = self.value.evaluate_admission_outputs(roots)
        return result is not None and result["allowed"] is True


def compile_candidate_check(
    raw: object,
    inputs: tuple[C0CandidateInputPorts, ...],
    action_template: str,
    action: C0ValueActionPorts,
    entry: str,
) -> C0CandidateCheck:
    if type(raw) is not dict or set(raw) != {"ref", "when"}:
        raise C0LawError("offer availability needs an explicit candidate input and predicate")
    selected = next((port for port in inputs if port.symbol == raw["ref"]), None)
    if selected is None or selected.action_template != action_template:
        raise C0LawError("offer availability input is not bound to this Action template")
    check_candidate_input(action, selected.value_ports)
    value = compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": True,
                "outputs": {"allowed": raw["when"]},
            }
        ),
        selected.value_ports,
        admission_outputs=frozenset({"allowed"}),
    )
    return C0CandidateCheck(selected.symbol, entry, value)
