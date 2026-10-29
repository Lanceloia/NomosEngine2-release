"""Local identities and immutable stage reads for generated world rules."""

from dataclasses import dataclass, field, replace
from types import MappingProxyType

from .errors import AdmissionError
from .expressions import ExpressionError, ValueBindingError, ValueBudget, fail_value

_CONSTRUCT_CACHE = object()
_CONSTRUCT_LIMIT = 256
_PROOF_SCHEMAS = object()


@dataclass(frozen=True)
class Reference:
    scope: str
    ordinal: int
    sort: str


@dataclass(frozen=True)
class EntitySchema:
    name: str
    kind: str
    parents: tuple
    fields: tuple
    view: tuple
    public: tuple
    reference: str
    initial: tuple = ()


class ReferenceDomain:
    def __init__(self, schemas, symbols, *, references=None, allowed=None):
        self.schemas = schemas
        self.symbols = MappingProxyType(dict(symbols))
        self._symbol_source = self.symbols
        self._symbol_key = object()
        self._symbol_values = frozenset(self.symbols.values())
        self.references = self._symbol_values if references is None else frozenset(references)
        if not self._symbol_values <= self.references:
            raise ValueError("opening symbols must belong to the current identity domain")
        self.allowed = self.references if allowed is None else frozenset(allowed)
        if not self.allowed <= self.references:
            raise ValueError("identifying domain contains foreign references")

    def at(self, states):
        return self._derive(frozenset(ref for ref in states if type(ref) is Reference), None)

    def restricted(self, allowed):
        return self._derive(frozenset(self.references), frozenset(allowed))

    def symbol_key(self):
        if self.symbols is self._symbol_source:
            return self._symbol_key
        return tuple(self.symbols.items())

    def _derive(self, references, allowed):
        # Only the privately copied opening map is immutable enough to share.
        if self.symbols is not self._symbol_source:
            return ReferenceDomain(
                self.schemas, self.symbols, references=references, allowed=allowed
            )
        if not self._symbol_values <= references:
            raise ValueError("opening symbols must belong to the current identity domain")
        if allowed is not None and not allowed <= references:
            raise ValueError("identifying domain contains foreign references")
        result = object.__new__(ReferenceDomain)
        result.schemas = self.schemas
        result.symbols = result._symbol_source = self.symbols
        result._symbol_key = self._symbol_key
        result._symbol_values = self._symbol_values
        result.references = references
        result.allowed = references if allowed is None else allowed
        return result

    def accepts(self, expected, actual):
        if actual == expected:
            return True
        pending, seen = [actual], set()
        while pending:
            name = pending.pop()
            if name == expected:
                return True
            if name in self.schemas and name not in seen:
                seen.add(name)
                pending.extend(self.schemas[name].parents)
        return False

    def require(self, value, sort):
        if type(value) is not Reference:
            fail_value(sort, (), "TypeMismatch", "local reference", "wrong carrier")
        if value not in self.references:
            fail_value(sort, (), "UnknownIdentity", "current local binding", "unknown or foreign")
        if not self.accepts(sort, value.sort):
            fail_value(sort, (), "TypeMismatch", sort, value.sort)
        if value not in self.allowed:
            fail_value(sort, (), "InformationBoundary", "authorized identity", "not authorized")
        return value

    def resolve(self, kind, symbol):
        value = self.symbols.get(symbol) if type(symbol) is str else None
        if value is None or self.schemas[value.sort].kind != kind:
            fail_value(
                kind, (), "UnknownIdentity", "declared opening symbol", "unknown or wrong kind"
            )
        return value

    def known(self, sort):
        return frozenset(ref for ref in self.allowed if self.accepts(sort, ref.sort))


@dataclass(frozen=True)
class _CapturedLocalValue:
    value: object = None
    failure: tuple | None = None

    def __call__(self):
        if self.failure is not None:
            kind, arguments = self.failure
            raise kind(*arguments)
        return self.value


def detached_reads(reads, aliases):
    """Capture ports without forcing failures in short-circuited expressions."""
    values = {}
    for name in aliases:
        try:
            values[name] = _CapturedLocalValue(reads.local_value(name))
        except AdmissionError as error:
            values[name] = _CapturedLocalValue(failure=(type(error), (error.code, error.message)))
        except (ExpressionError, ValueBindingError) as error:
            values[name] = _CapturedLocalValue(failure=(type(error), (error.diagnostic,)))
    return replace(
        reads,
        local_values=values,
        _checked_inputs={},
        _input_batch=None,
    )


@dataclass(frozen=True)
class ReadContext:
    schema_id: str
    references: ReferenceDomain
    states: object
    mode: str
    reference_readers: object
    controller: Reference | None = None
    local_values: object = None
    _checked_inputs: dict | None = field(default=None, compare=False, repr=False)
    _input_batch: object = field(default=None, compare=False, repr=False)

    def _proof_schemas(self):
        schemas = self.references.schemas
        previous = self._checked_inputs.get(_PROOF_SCHEMAS)
        if previous is not None:
            if len(previous) == len(schemas) and all(
                schemas.get(name, _PROOF_SCHEMAS) is schema for name, schema in previous
            ):
                return previous
            self._checked_inputs.clear()
        return tuple(schemas.items())

    def checked_input(self, validator, value, limits):
        if self._checked_inputs is not None and self._input_batch is not None:
            return self._input_batch.check(self, validator, value, limits)
        if (
            self._checked_inputs is None
            or type(self.references.references) is not frozenset
            or type(self.references.allowed) is not frozenset
        ):
            return validator(value, ValueBudget(limits, self.references), ())
        schemas = self._proof_schemas()
        domain = self.references.schemas, self.references.references, self.references.allowed
        key = validator, id(value), id(limits), *(id(part) for part in domain)
        if key not in self._checked_inputs:
            checked = validator(value, ValueBudget(limits, self.references), ())
            # Each proof belongs to this exact permission domain; keep ids alive.
            self._checked_inputs[key] = value, limits, domain, checked
            self._checked_inputs[_PROOF_SCHEMAS] = schemas
        return self._checked_inputs[key][3]

    def checked_construct(self, validator, constructor, arguments, limits):
        """Reuse immutable nominal construction inside one checked read scope."""
        if (
            self._checked_inputs is None
            or type(self.references.references) is not frozenset
            or type(self.references.allowed) is not frozenset
        ):
            return validator(constructor(*arguments), ValueBudget(limits, self.references), ())
        schemas = self._proof_schemas()
        domain = self.references.schemas, self.references.references, self.references.allowed
        cache = self._checked_inputs.get(_CONSTRUCT_CACHE)
        key = (
            self.schema_id,
            self.mode,
            self.controller,
            validator,
            constructor,
            tuple(id(value) for value in arguments),
            id(limits),
            *(id(part) for part in domain),
        )
        if cache is not None and key in cache:
            return cache[key][3]
        value = constructor(*arguments)
        checked = validator(value, ValueBudget(limits, self.references), ())
        if cache is None:
            cache = self._checked_inputs[_CONSTRUCT_CACHE] = {}
        if len(cache) < _CONSTRUCT_LIMIT:
            # Retain fields and scope objects so none of the identity keys can be recycled.
            cache[key] = arguments, limits, domain, checked
            self._checked_inputs[_PROOF_SCHEMAS] = schemas
        return checked

    def local_value(self, alias):
        if self.controller is None or self.local_values is None or alias not in self.local_values:
            fail_value(alias, (), "MissingBinding", "declared local information", "unavailable")
        return self.local_values[alias]()

    def read(self, reference, sort, field, *, own=False):
        self.references.require(reference, sort)
        schema = self.references.schemas[sort]
        if own and reference != self.controller:
            fail_value(sort, (field,), "WrongController", "actual controlling Actor", "other Actor")
        if self.mode == "actor":
            allowed = (
                schema.view
                if (schema.kind == "object" or own and reference == self.controller)
                else schema.public
            )
            if field not in allowed:
                fail_value(sort, (field,), "InformationBoundary", "permitted field", "not public")
        if field == "id":
            return reference
        fields = dict(schema.fields)
        if field not in fields:
            fail_value(sort, (field,), "InvalidValue", "declared entity field", "unknown")
        value = self.states[reference][field]
        # Stored fields are typed at Start/write; contained identities still need read authority.
        if self.mode == "actor":
            for contained in self.reference_readers[fields[field]](value):
                self.references.require(contained, contained.sort)
        return value
