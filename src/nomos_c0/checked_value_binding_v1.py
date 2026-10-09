"""Checked world values bind only to a generated nominal layout and fixed intrinsics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .author_contract_v1 import C0LawError
from .composable_value_v1 import C0ValueProgram
from .nominal_signatures_v1 import C0NominalSignatures
from .value_symbols_v1 import C0SymbolicValueProgram, bind_value_programs, symbolize_value_programs

if TYPE_CHECKING:
    from .declarative_nominal_v0 import C0NominalRecordLayout
    from .nominal_owner_layout_v1 import C0NominalOwnerLayout


def _intrinsic_carriers() -> dict[str, type]:
    # Fixed backend contracts are not author record declarations or type adapters.
    from .direct_actor_event_v1 import C0EventTrigger
    from .scheduled_scene_event_v1 import C0DueValue, C0TimeValue

    return {"event_trigger": C0EventTrigger, "due": C0DueValue, "time": C0TimeValue}


@dataclass(frozen=True)
class C0CheckedValueIR:
    signatures: C0NominalSignatures
    value: C0SymbolicValueProgram


@dataclass(frozen=True)
class C0NamedWorldValueIR:
    formation: str
    symbol: str
    body: C0CheckedValueIR

    def __post_init__(self) -> None:
        if self.formation not in ("submit", "after_occurrence", "due") or (
            type(self.symbol) is not str or not self.symbol
        ):
            raise C0LawError("world value has no finite formation identity")


@dataclass(frozen=True)
class C0ValueBackend:
    layout: C0NominalRecordLayout
    owner_layout: C0NominalOwnerLayout | None = None

    def __post_init__(self) -> None:
        from .declarative_nominal_v0 import C0NominalRecordLayout

        if type(self.layout) is not C0NominalRecordLayout:
            raise C0LawError("value backend needs a generated nominal layout")
        self.layout.check(self.layout.signatures)
        if self.owner_layout is not None:
            from .nominal_owner_layout_v1 import C0NominalOwnerLayout

            if (
                type(self.owner_layout) is not C0NominalOwnerLayout
                or self.owner_layout.record_layout is not self.layout
            ):
                raise C0LawError("world backend needs the same generated owner layout")
            self.owner_layout.check(self.layout.signatures)

    def capture(self, value: C0ValueProgram) -> C0CheckedValueIR:
        return self.capture_many((value,))[0]

    def capture_many(self, values: tuple[C0ValueProgram, ...]) -> tuple[C0CheckedValueIR, ...]:
        if type(values) is not tuple:
            raise C0LawError("value batch requires a closed tuple")
        for value in values:
            if type(value) is not C0ValueProgram:
                raise C0LawError("value symbols require a checked frontend program")
            self.layout.check(self.layout.signatures)
        return tuple(
            C0CheckedValueIR(self.layout.signatures, value)
            for value in symbolize_value_programs(
                values, dict(self.layout.records), intrinsics=_intrinsic_carriers()
            )
        )

    def bind(self, ir: C0CheckedValueIR) -> C0ValueProgram:
        return self.bind_many((ir,))[0]

    def bind_many(self, values: tuple[C0CheckedValueIR, ...]) -> tuple[C0ValueProgram, ...]:
        if type(values) is not tuple:
            raise C0LawError("value batch requires a closed tuple")
        for ir in values:
            if type(ir) is not C0CheckedValueIR or type(ir.value) is not C0SymbolicValueProgram:
                raise C0LawError("value backend needs a checked symbolic program")
            self.layout.check(ir.signatures)
        return bind_value_programs(
            tuple(ir.value for ir in values),
            dict(self.layout.records),
            intrinsics=_intrinsic_carriers(),
        )


class _WorldValueBuilder:
    """Compile-only collector for checked symbolic values and their formation identities."""

    def __init__(self, backend: C0ValueBackend) -> None:
        if type(backend) is not C0ValueBackend:
            raise C0LawError("world value builder has an unsupported backend")
        self.backend = backend
        self._entries: dict[tuple[str, str], C0ValueProgram] = {}

    @property
    def entries(self) -> tuple[C0NamedWorldValueIR, ...]:
        bodies = self.backend.capture_many(tuple(self._entries.values()))
        return tuple(
            C0NamedWorldValueIR(formation, symbol, body)
            for (formation, symbol), body in zip(self._entries, bodies, strict=True)
        )

    def transition(self, symbol: str, program):
        formation = program.ir.formation.value
        key = formation, symbol
        if key in self._entries:
            raise C0LawError("world value formation identities alias")
        self._entries[key] = program.ir.value
        return program
