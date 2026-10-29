"""Successful nominal input checks shared only inside one current control scan."""

from .expressions import ValueBudget


class InputProofBatch:
    def __init__(self):
        self.active = True
        self.roots = self.schemas = None
        self.values = {}

    def close(self):
        self.active = False
        self.values.clear()
        self.roots = self.schemas = None

    def check(self, reads, validator, value, limits):
        references = reads.references
        if (
            not self.active
            or type(references.references) is not frozenset
            or type(references.allowed) is not frozenset
        ):
            return validator(value, ValueBudget(limits, references), ())
        schemas = references.schemas
        if (
            self.roots is None
            or reads.states is not self.roots[0]
            or reads.reference_readers is not self.roots[1]
            or schemas is not self.roots[2]
            or len(schemas) != len(self.schemas)
            or not self._same_schemas(schemas)
        ):
            self.values.clear()
            self.roots = reads.states, reads.reference_readers, schemas
            self.schemas = tuple(schemas.items())
        key = (
            reads.schema_id,
            reads.mode,
            reads.controller,
            validator,
            id(value),
            id(limits),
            references.references,
            references.allowed,
            references.symbol_key(),
        )
        prior = self.values.get(key)
        if prior is not None:
            return prior[2]
        checked = validator(value, ValueBudget(limits, references), ())
        if len(self.values) < 256:
            # Keep identity-keyed values alive until this scan ends.
            self.values[key] = value, limits, checked
        return checked

    def _same_schemas(self, schemas):
        for name, schema in self.schemas:
            if schemas.get(name) is not schema:
                return False
        return True
