"""Generate one Actor callback's input bindings and retain only that callback's proofs."""

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.expression_entry_proofs import ExpressionEntryProof

from .fixed_values import fixed_value


class InputBindings:
    """One instance per generated function; bound input proofs never cross callbacks."""

    def __init__(self, world):
        self.world = world
        self.proofs = {}

    def domain(self, item):
        lines = []
        for attribute in ("pool", "minimum", "maximum", "length"):
            expression = getattr(item, attribute)
            if expression is not None:
                lines.append(f"_{attribute} = {self.expression(expression)}")
        if item.kind == "subset":
            lines.append(
                "if _minimum < 0 or _maximum < _minimum: "
                "raise AdmissionError('InvalidDomain', 'invalid current subset bounds')"
            )
        elif item.kind == "sequence":
            lines.append(
                "if _length < 0: "
                "raise AdmissionError('InvalidDomain', 'invalid current sequence length')"
            )
        return lines

    def check(self, type_name, value):
        if self.world.program.table[type_name].kind in {
            "record",
            "variant",
            "optional",
            "set",
            "sequence",
        }:
            return (
                f"actor_reads.checked_input(_VALIDATORS[{type_name!r}], {value}, "
                "session.limits.value)"
            )
        return (
            f"_VALIDATORS[{type_name!r}]({value}, "
            "ValueBudget(session.limits.value, actor_reads.references), ())"
        )

    def expression(self, checked):
        if checked.summary.context != "actor":
            raise C0LawError("prepared input expression requires its Actor context")
        value = self.world.expression(checked)
        bindings = tuple(
            (name, kind.type_id)
            for name, spec in checked.inputs
            if (kind := checked.table[spec.type_name]).type_id == self.proofs.get(name)
        )
        if bindings:
            self.world.expression_entry_proofs[self.world.expressions[-1][0]] = (
                ExpressionEntryProof(checked, bindings)
            )
        return value

    def derived(self, item):
        result = item.derive
        if (
            result is None
            or result.summary.context != "actor"
            or result.result.type_id != self.world.program.table[item.type_name].type_id
        ):
            raise C0LawError("derived input requires its exact Actor result contract")
        value = self.expression(result)
        if self.world.report is not None:
            self.world.derived_result_proofs.append(
                (self.world.expressions[-1][0], result, item.type_name)
            )
        return value

    def bind(self, item):
        # Domains precede value binding, just as in the authored input contract.
        lines = self.domain(item)
        actual = f"environment[{item.name!r}]"
        value = (
            self.derived(item)
            if item.kind == "derive"
            else self.check(item.type_name, f"choices[{item.name!r}]")
        )
        lines.append(f"{actual} = {value}")
        conditions = {
            "member": f"{actual} in _pool",
            "subset": f"{actual} <= _pool and _minimum <= len({actual}) <= _maximum",
            "sequence": (
                f"len({actual}) == _length and all(_element in _pool for _element in {actual})"
                + (
                    f" and len(set({actual})) == len({actual})"
                    if item.repetition == "forbid"
                    else ""
                )
            ),
        }
        if item.kind in conditions:
            lines.append(
                f"if not ({conditions[item.kind]}): "
                "raise AdmissionError('InvalidChoice', 'choice is outside its current domain')"
            )
        self.proofs[item.name] = self.world.program.table[item.type_name].type_id
        return lines

    def environment(self, plan, views, *, actor_only=False):
        lines = [
            "before = session._states",
            "controller = actor",
            "receipts = session._receipts",
            *self.world.context(views, cache_inputs=True, actor_only=actor_only),
        ]
        lines.append(
            "environment = {}"
            if plan.context is None
            else f"environment = session.context_values({plan.context.name!r}, before, local=True)"
        )
        if plan.process is not None and plan.process.point != "begin":
            lines.append("environment.update(record.captures)")
        lines.append(f"environment[{plan.actor!r}] = actor")
        lines.extend(
            f"environment[{p.name!r}] = "
            + fixed_value(self.world.program.table, p, references="actor_reads.references")
            for p in plan.parameters
        )
        for name, kind in plan.inputs.base:
            value = f"environment[{name!r}]"
            if plan.process is not None and plan.process.point != "begin":
                lines.append(
                    f"_VALIDATORS[{kind!r}]({value}, "
                    "ValueBudget(session.limits.value, session.references), ())"
                )
            else:
                lines.append(self.check(kind, value))
                self.proofs[name] = self.world.program.table[kind].type_id
        return lines
