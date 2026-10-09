"""Checked private singleton completion, separate from public offer permissions."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from .author_contract_v1 import C0LawError
from .checked_value_binding_v1 import C0CheckedValueIR
from .composable_value_v1 import (
    C0ValueProgram,
    C0ValueStateError,
    compile_value_program,
    runtime_value_ports,
)
from .condition_source_v0 import lower_author_expression
from .expression_read_authority_v1 import check_expression_reads


@dataclass(frozen=True)
class C0PrivateActorBinding:
    payload_field: str
    member: str
    condition: C0ValueProgram | None

    def resolve(self, roots: dict[str, object]) -> str | None:
        if self.condition is None:
            return self.member
        values = self.condition.evaluate_admission_outputs(
            {name: roots[name] for name in self.condition._ports.roots}
        )
        if values is None or type(values["included"]) is not bool:
            raise C0ValueStateError("private participant condition has no Boolean result")
        return self.member if values["included"] else None


@dataclass(frozen=True)
class C0PrivateActorBindingIR:
    payload_field: str
    member: str
    condition: C0CheckedValueIR | None


def _condition_ports(action):
    authority = action.value_ports
    excluded = {"payload", *(role.name for role in action.participants if role.nullable)}
    roots = {name: carrier for name, carrier in authority.roots.items() if name not in excluded}
    paths = frozenset(
        path for path in authority.admission_readable_paths if path.split(".")[0] in roots
    )
    return replace(
        authority,
        roots=roots,
        outputs={"included": bool},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=authority.admission_readable_fields,
        writable_fields={},
        record_types={},
        tuple_fields=authority.admission_tuple_fields,
        source_context=None,
    )


def compile_private_binding(row, port, action):
    if (
        type(row) is not dict
        or set(row) not in ({"fixed_actor", "private"}, {"fixed_actor", "private", "when"})
        or row["private"] is not True
        or port.selector != "closed_domain"
        or len(port.members) != 1
        or row["fixed_actor"] != port.members[0][0]
        or ("when" in row and not port.nullable)
    ):
        raise C0LawError("private participant requires an exact singleton and nullable condition")
    condition = None
    if "when" in row:
        expression, _ = lower_author_expression(row["when"], path="private_participant.when")
        condition = compile_value_program(
            json.dumps(
                {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {"included": expression},
                }
            ),
            _condition_ports(action),
            admission_outputs=frozenset({"included"}),
        )
    binding = C0PrivateActorBinding(port.payload_field, row["fixed_actor"], condition)
    check_private_bindings((binding,), action)
    return binding


def check_private_bindings(bindings, action):
    if (
        type(bindings) is not tuple
        or any(type(binding) is not C0PrivateActorBinding for binding in bindings)
        or any(type(binding.payload_field) is not str for binding in bindings)
        or tuple(binding.payload_field for binding in bindings)
        != tuple(sorted({binding.payload_field for binding in bindings}))
    ):
        raise C0LawError("private participant bindings are not canonical checked declarations")
    ports = {role.payload_field: role for role in action.participants}
    for binding in bindings:
        port = ports.get(binding.payload_field)
        if (
            port is None
            or port.selector != "closed_domain"
            or len(port.members) != 1
            or type(binding.member) is not str
            or binding.member != port.members[0][0]
        ):
            raise C0LawError("private participant differs from its exact singleton role")
        condition = binding.condition
        if condition is not None and (
            not port.nullable
            or type(condition) is not C0ValueProgram
            or condition._ports != runtime_value_ports(_condition_ports(action))
            or condition._admission_outputs != frozenset({"included"})
            or condition.effects
            or condition._tree["bindings"]
            or condition.guard_ir.expression.operation != "const"
            or condition.guard_ir.expression.operand is not True
            or set(condition._tree["outputs"]) != {"included"}
            or condition._tree["outputs"]["included"].result_type is not bool
        ):
            raise C0LawError("private participant condition exceeds read-only Action authority")
        if condition is not None:
            check_expression_reads(
                condition._tree["outputs"], condition._ports, frozenset(condition._ports.roots)
            )


def capture_private_bindings(bindings, backend):
    return tuple(
        C0PrivateActorBindingIR(
            binding.payload_field,
            binding.member,
            None if binding.condition is None else backend.capture(binding.condition),
        )
        for binding in bindings
    )


def bind_private_bindings(bindings, backend):
    if type(bindings) is not tuple or any(
        type(binding) is not C0PrivateActorBindingIR for binding in bindings
    ):
        raise C0LawError("private participant IR lacks checked bindings")
    return tuple(
        C0PrivateActorBinding(
            binding.payload_field,
            binding.member,
            None if binding.condition is None else backend.bind(binding.condition),
        )
        for binding in bindings
    )


def check_entry_private_bindings(offers):
    by_entry = {}
    for offer in offers:
        bindings = getattr(offer, "private_actor_fields", ())
        if by_entry.setdefault(offer.entry, bindings) != bindings:
            raise C0LawError("offer entry has ambiguous private participant bindings")
