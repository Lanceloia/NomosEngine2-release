"""Typed opening disclosures and compiler-managed immutable Actor reports."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .projections import compile_projection


@dataclass(frozen=True)
class InformationPlan:
    projection: object
    trigger: str
    access: str
    assurances: tuple = ()
    constraints: tuple = ()

    @property
    def name(self):
        return self.projection.name


def compile_information(
    name,
    definition,
    declaration,
    binding,
    contexts,
    table,
    entities,
    pure,
    actors,
    *,
    context=None,
    facts=None,
    constraints=(),
):
    from .frontend import row

    row(
        declaration,
        {"viewer", "context", "trigger", "audience", "returns", "value", "access"},
        {"assure", "assure_constraints"},
        path="information." + definition,
    )
    if declaration["trigger"] != "opening" or declaration["access"] != "acquired":
        raise C0LawError("UnsupportedFeature: information requires opening/acquired")
    projection = compile_projection(
        name,
        definition,
        {
            key: value
            for key, value in declaration.items()
            if key not in ("trigger", "access", "assure", "assure_constraints")
        },
        binding,
        contexts,
        table,
        entities,
        pure,
        actors,
        context=context,
        category="information",
    )
    from .assurances import compile_assurances
    from .constraints import compile_constraint_assurances

    return InformationPlan(
        projection,
        "opening",
        "acquired",
        compile_assurances(
            declaration.get("assure", {}),
            {} if facts is None else facts,
            table,
            pure,
            entities,
            declaration["returns"],
            "information." + definition + ".assure",
        ),
        compile_constraint_assurances(
            declaration.get("assure_constraints", {}),
            constraints,
            table,
            pure,
            entities,
            declaration["returns"],
            "information." + definition + ".assure_constraints",
        ),
    )
