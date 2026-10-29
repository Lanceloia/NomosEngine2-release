"""Typed wire consumption of existing local forms and atomic Action submission."""

from itertools import combinations, permutations, product

from .errors import AdmissionError
from .expressions import ValueBindingError
from .values import wire_key

_ACTION_REJECTIONS = frozenset(
    {
        "NotAdmitted",
        "InvalidChoice",
        "WrongController",
        "WorldClosed",
        "WorldDraining",
        "MissingBinding",
    }
)
_MENU_REJECTIONS = frozenset(
    {
        "NotAdmitted",
        "InvalidChoice",
        "UnknownActor",
        "UnknownAbility",
        "WorldClosed",
        "WorldDraining",
        "WrongController",
    }
)


class ChoiceEnumerationError(ValueError):
    """A complete finite menu cannot be returned within the selected contract."""


class WireActions:
    def __init__(self, session, actor, *, reference=None, resolve_reference=None):
        self.session, self.actor = session, actor
        self.reference, self.resolve_reference = reference, resolve_reference

    def _decode(self, ability, supplied, request):
        if type(supplied) is not dict:
            raise AdmissionError("MissingBinding", "wire choices must be a named object")
        form = self.session.choice_form(self.actor, ability, request=request)
        fields = {field.name: field for field in form.fields}
        if set(supplied) - fields.keys():
            raise AdmissionError("MissingBinding", "only declared chosen inputs allowed")
        codec = self.session.values(self.actor)
        return {
            name: codec.decode(fields[name].type_name, value, reference=self.resolve_reference)
            for name, value in supplied.items()
        }

    def act(self, ability, choices, *, request=None):
        decoded = self._decode(ability, choices, request)
        return self.session.act(self.actor, ability, decoded, request=request)

    def try_act(self, ability, choices, *, request=None):
        """Return publication as bool; binding rejections exclude resource budgets."""
        try:
            result = self.act(ability, choices, request=request)
        except ValueBindingError as error:
            if error.diagnostic.code == "ValueBudget":
                raise
            return False
        except AdmissionError as error:
            if error.code in _ACTION_REJECTIONS:
                return False
            raise
        if result.status == "rejected":
            return False
        if result.status != "published":
            raise RuntimeError(f"unexpected native action status: {result.status}")
        return True

    def available_choices(self, ability, *, prefix=None, limit=256, request=None):
        """Return [] for ordinary unavailable menus; propagate budget/defect errors."""
        try:
            return self.choices(ability, prefix=prefix, limit=limit, request=request)
        except AdmissionError as error:
            if error.code in _MENU_REJECTIONS:
                return []
            raise

    def reports(self, name):
        """Encode an explicitly selected receipt collection using the current actor view."""
        values = self.session.report_collection(self.actor, name)["values"]
        kind, _ = self.session.program.report_collections[name]
        codec = self.session.values(self.actor)
        return [codec.encode(kind, value, reference=self.reference) for value in values]

    def choices(self, ability, *, prefix=None, limit=256, request=None):
        if type(limit) is not int or limit < 1:
            raise ValueError("enumeration limit must be a positive integer")
        codec = self.session.values(self.actor)
        initial = self._decode(ability, {} if prefix is None else prefix, request)
        fields = self.session.choice_form(self.actor, ability, request=request).fields
        kinds = {field.name: field.type_name for field in fields}
        pending, rows, visited = [initial], [], 1

        def encode(kind, value):
            return codec.encode(kind, value, reference=self.reference)

        while pending:
            values = pending.pop()
            try:
                form = self.session.choice_form(self.actor, ability, values, request=request)
            except AdmissionError as error:
                if error.code in {"InvalidChoice", "NotAdmitted"}:
                    continue
                raise
            if form.complete:
                rows.append({name: encode(kinds[name], value) for name, value in values.items()})
                continue
            field = next((field for field in form.fields if field.ready), None)
            if field is None or field.kind == "enter":
                raise ChoiceEnumerationError("non-finite input requires an explicit prefix")
            if field.kind == "member":
                candidates = field.pool
            elif field.kind in {"subset", "sequence"}:
                if field.kind == "subset":
                    items = (
                        selected
                        for count in range(field.minimum, min(field.maximum, len(field.pool)) + 1)
                        for selected in combinations(field.pool, count)
                    )
                elif (
                    field.length
                    and not field.pool
                    or (field.repetition == "forbid" and field.length > len(field.pool))
                ):
                    items = iter(())
                elif field.length > codec.limits.items:
                    raise ChoiceEnumerationError("sequence length exceeds value budget")
                elif field.repetition == "forbid":
                    items = permutations(field.pool, field.length)
                else:
                    items = product(field.pool, repeat=field.length)
                # Collection construction uses canonical native wire, independently of
                # the external reference representation selected for the final rows.
                candidates = (
                    codec.decode(
                        field.type_name, [codec.encode(field.element_type, x) for x in item]
                    )
                    for item in items
                )
            else:
                raise ChoiceEnumerationError(f"unsupported finite form: {field.kind}")
            for candidate in candidates:
                visited += 1
                if visited > limit:
                    raise ChoiceEnumerationError("finite menu exceeds enumeration limit")
                pending.append({**values, field.name: candidate})
        return sorted(rows, key=wire_key)
