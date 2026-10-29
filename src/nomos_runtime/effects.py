"""Transaction-local effect drafts; publication belongs to Session."""

from types import MappingProxyType

from . import scheduling
from .carrying import opening_states as carrying_opening
from .carrying import validate as validate_carrying
from .entities import ReferenceDomain
from .errors import EffectBudgetExceeded, FormationBudgetExceeded, SettlementDefect
from .expressions import ValueBudget
from .information import ContextKey
from .randomness import RandomBudgetExceeded, RandomCursor


class Draft:
    def __init__(self, session, before, references, limits, occurrence, allocation):
        self.session = session
        self.program, self.before, self.references, self.limits = (
            session.program,
            before,
            references,
            limits,
        )
        self.changes, self.deliveries = {}, []
        self.occurrence, self.supports = occurrence, []
        self.result = None
        self.next_point = None
        self.advanced = True
        self._effect_steps = 0
        self.allocation = allocation
        self.formed = {}
        self._products = []
        self.random = RandomCursor(before, self.changes)
        self.scheduled = []

    def random_steps(self, path, count):
        self._effect_steps += count
        if self._effect_steps > self.limits.nodes:
            raise RandomBudgetExceeded(path, "finite sampling expansion exceeds its node budget")

    def form(self, products):
        ordered = sorted(
            products,
            key=lambda product: (self.program.schemas[product[0]].kind == "person", product[0]),
        )
        for sort, fields in ordered:
            schema = self.program.schemas[sort]
            selected = self.program.actor_kinds if schema.kind == "person" else self.program.objects
            if sort not in selected:
                raise SettlementDefect("formation needs a selected entity sort")
            if set(fields) != set(dict(schema.fields)):
                raise SettlementDefect("formation requires exact declared fields")
            for field, kind in schema.fields:
                self.program.validators[kind](
                    fields[field], ValueBudget(self.limits, self.references), ()
                )
            self._products.append((sort, MappingProxyType(dict(fields))))

    def materialize(self):
        # Stage completion can still reject normally before any product allocation.
        for sort, fields in self._products:
            reference = self.allocation.allocate(sort, self.occurrence)
            scheduling.validate_newborn(self.session, reference, fields, self.before)
            self.formed[reference] = fields
        self._products.clear()

    def check_form_count(self, count):
        if self._effect_steps + count > self.limits.nodes:
            raise FormationBudgetExceeded()

    def effect_step(self, path):
        self._effect_steps += 1
        if self._effect_steps > self.limits.nodes:
            raise EffectBudgetExceeded(path)

    def set(self, reference, field, value):
        self.references.require(reference, reference.sort)
        if any(
            self.references.accepts(plan.item, reference.sort)
            and field in (plan.holder, plan.ground)
            for plan in self.program.relations.values()
        ):
            raise SettlementDefect("managed carrying fields require a relation operation")
        self._set(reference, dict(self.program.schemas[reference.sort].fields), field, value)

    def set_context(self, name, field, value):
        definition = self.program.context_definitions.get(name)
        if definition is None or ContextKey(name) not in self.before:
            raise SettlementDefect("effect names no current shared context")
        self._set(ContextKey(name), dict(definition.fields), field, value)

    def _set(self, reference, fields, field, value):
        key = (reference, field)
        if key in self.changes:
            raise SettlementDefect("multiple effects write the same actual field")
        if field not in fields:
            raise SettlementDefect("effect names no declared state field")
        self.program.validators[fields[field]](value, ValueBudget(self.limits, self.references), ())
        self.changes[key] = value

    def after(self):
        states = dict(self.before)
        for (reference, field), value in self.changes.items():
            states[reference] = MappingProxyType({**states[reference], field: value})
        references = self.references
        if self.formed:
            states.update(self.formed)
            references = references.at(states)
            newborns = ReferenceDomain(self.program.schemas, (), references=self.formed)
            states.update(carrying_opening(self.program, newborns))
        validate_carrying(self.program, references, states)
        return MappingProxyType(states)
