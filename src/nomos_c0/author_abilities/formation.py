"""Entity formation declarations and nominal producer dependencies."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError


@dataclass(frozen=True)
class EntityFormation:
    schema: object
    fields: tuple

    def expressions(self):
        return tuple(expression for _, expression in self.fields)


@dataclass(frozen=True)
class FormedSelector:
    sort: str


def compile_formations(rows, compiler, path):
    if type(rows) is not list:
        raise C0LawError(path + ": entity formation requires an ordered list")
    schemas = dict(compiler.entities.entities)
    result = []
    for index, row in enumerate(rows):
        location = f"{path}[{index}]"
        if (
            type(row) is not dict
            or set(row) != {"type", "fields"}
            or type(row["type"]) is not str
            or row["type"] not in schemas
            or type(row["fields"]) is not dict
        ):
            raise C0LawError(location + ": declared entity type and initialization fields required")
        schema = schemas[row["type"]]
        if set(row["fields"]) != set(dict(schema.fields)):
            raise C0LawError(location + ": formation requires exactly its declared fields")
        result.append(
            EntityFormation(
                schema,
                tuple(
                    (
                        name,
                        compiler.expression(row["fields"][name], kind.name, location + "." + name),
                    )
                    for name, kind in schema.fields
                ),
            )
        )
    return tuple(result)


def formation_sorts(plan, *, kind="object"):
    """Selected nominal sorts required by any possible formation branch."""
    return tuple(
        sorted(
            {
                form.schema.name
                for leaf in plan.resolution.leaves()
                for form in leaf.forms
                if form.schema.kind == kind
            }
        )
    )
