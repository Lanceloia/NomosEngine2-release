"""Generator-issued, operation-local success receipts for pure nominal validation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from .expression_ir_v1 import C0Expression, C0ValueType
from .generated_record_v1 import is_sealed_nominal_record
from .pure_definition_v1 import C0PureDefinition
from .validation_contract_execution_v1 import compile_contract_execution

_READ_ONLY_OPERATIONS = frozenset(
    "const ref eq le lt add sub mul ceil_div is_none not_none not all any if clause "
    "empty_like let call is_case match tuple_at unique_by exists exactly_one "
    "none_matching count_matching collect_matching participant_query collection_query".split()
)
_active: ContextVar[_Operation | None] = ContextVar("c0_nominal_validation_operation", default=None)


@dataclass(frozen=True)
class _RecordDependency:
    carrier: type
    attributes: tuple[tuple[str, object], ...]

    def current(self):
        if not is_sealed_nominal_record(self.carrier):
            return False
        try:
            for name, value in self.attributes:
                if getattr(self.carrier, name) is not value:
                    return False
        except StopIteration as error:
            # Preserve the failure boundary of the original generator traversal.
            raise RuntimeError("generator raised StopIteration") from error
        return True


@dataclass(frozen=True)
class _ValidationContract:
    dependencies: tuple[_RecordDependency, ...]
    references: tuple[tuple[type, object], ...]
    _execution: type | None = dataclass_field(default=None, init=False, repr=False, compare=False)

    def current(self):
        if self._execution is not None:
            return self._execution.execute(getattr, is_sealed_nominal_record)
        try:
            for item in self.dependencies:
                if type(item) is _RecordDependency:
                    carrier = item.carrier
                    if not is_sealed_nominal_record(carrier):
                        return False
                    for name, value in item.attributes:
                        if getattr(carrier, name) is not value:
                            return False
                elif not item.current():
                    return False
            for carrier, callback in self.references:
                if carrier.__post_init__ is not callback:
                    return False
        except StopIteration as error:
            raise RuntimeError("generator raised StopIteration") from error
        return True


class _Operation:
    def __init__(self, contract, owner):
        self.owner = owner
        self.carriers = frozenset(item.carrier for item in contract.dependencies)
        self.successes = {}
        self.enabled = True

    def invalidate(self):
        self.successes.clear()
        self.enabled = False


def wrap_generated_validator(carrier, validate):
    """Only the checked declarative generator installs this wrapper."""

    def execute(value):
        operation = _active.get()
        if operation is None or carrier not in operation.carriers:
            if operation is not None:
                operation.invalidate()
            validate(value)
        else:
            key = id(value) if operation.enabled else None
            prior = operation.successes.get(key) if key is not None else None
            if prior is not None and prior[0] is value and prior[1] is carrier:
                return
            try:
                validate(value)
            except BaseException:
                operation.invalidate()
                raise
            # Validation may invalidate this operation through a nested boundary.
            if operation.enabled:
                operation.successes[key] = (value, carrier)

    return execute


def _pure_tree(value, carriers, reference_types):
    if type(value) is C0ValueType:
        return (
            value.kind in ("tuple", "union", "variadic")
            or value.kind == "nominal"
            and (
                value.carrier in (bool, int, str, type(None))
                or value.carrier in carriers
                or value.carrier in reference_types
            )
        ) and all(_pure_tree(item, carriers, reference_types) for item in value.arguments)
    if type(value) is C0Expression:
        return (
            value.stage == "admission"
            and value.operation in _READ_ONLY_OPERATIONS
            and _pure_tree(value.value_type, carriers, reference_types)
            and _pure_tree(value.operand, carriers, reference_types)
        )
    if type(value) is C0PureDefinition:
        return (
            value.stage == "admission"
            and all(
                _pure_tree(item, carriers, reference_types) for _, item in value.parameter_types
            )
            and _pure_tree(value.result_type, carriers, reference_types)
            and _pure_tree(value.body, carriers, reference_types)
        )
    if isinstance(value, Mapping):
        return all(_pure_tree(item, carriers, reference_types) for item in value.values())
    if type(value) is tuple:
        return all(_pure_tree(item, carriers, reference_types) for item in value)
    return value is None or type(value) in (bool, int, str)


def issue_validation_contracts(records, reference_types):
    """Build eligibility from the actual generator graph, never a class flag alone."""
    carriers = frozenset(records)
    qualified = {}
    leaf_types = {
        "bool": bool,
        "int": int,
        "str": str,
        "enum": str,
        **dict(zip(("ref", "individual_ref", "actor_ref"), reference_types, strict=True)),
    }

    def children(spec):
        if spec.kind in ("record", "variant"):
            return (spec.annotation,)
        if spec.kind in ("optional", "tuple") and spec.item is not None:
            return children(spec.item)
        if spec.annotation is leaf_types.get(spec.kind) and spec.kind in leaf_types:
            return ()
        return None

    def visit(carrier):
        if carrier in qualified:
            return qualified[carrier]
        if carrier not in carriers:
            return None
        dependencies = {carrier}
        for field in carrier.__nomos_fields__:
            nested = children(field.value)
            if nested is None:
                qualified[carrier] = None
                return None
            for child in nested:
                descendants = visit(child)
                if descendants is None:
                    qualified[carrier] = None
                    return None
                dependencies.update(descendants)
        invariant = carrier.__nomos_invariant__
        if invariant is not None and (
            dict(invariant._ports.roots) != {"state": carrier}
            or not _pure_tree(invariant.guard_ir.expression, carriers, reference_types)
            or not _pure_tree(
                tuple(
                    binding
                    for binding in invariant._tree["bindings"]
                    if binding.get("stage", "admission") == "admission"
                ),
                carriers,
                reference_types,
            )
        ):
            qualified[carrier] = None
            return None
        qualified[carrier] = frozenset(dependencies)
        return qualified[carrier]

    snapshots = {
        carrier: _RecordDependency(
            carrier,
            tuple(
                (name, getattr(carrier, name))
                for name in (
                    "validate_for_k0",
                    "__init__",
                    "__eq__",
                    "__hash__",
                    "__nomos_fields__",
                    "__nomos_cases__",
                    "__nomos_invariant__",
                    "__getattribute__",
                    "__setattr__",
                    "__delattr__",
                    "__new__",
                    *carrier.__slots__,
                )
            ),
        )
        for carrier in records
    }
    references = tuple((carrier, carrier.__post_init__) for carrier in reference_types)
    # Install during checked assembly; publication seals this metadata with the class.
    for carrier in records:
        dependencies = visit(carrier)
        contract = (
            None
            if dependencies is None
            else _ValidationContract(
                tuple(snapshots[item] for item in records if item in dependencies), references
            )
        )
        if contract is not None:
            object.__setattr__(
                contract,
                "_execution",
                compile_contract_execution(contract.dependencies, contract.references),
            )
        carrier.__nomos_validation_contract__ = contract


def check_owner_boundary(owner):
    operation = _active.get()
    if operation is not None and operation.owner is not owner:
        operation.invalidate()


@contextmanager
def validation_operation(carrier, owner):
    contract = getattr(carrier, "__nomos_validation_contract__", None)
    parent = _active.get()
    operation = (
        _Operation(contract, owner)
        if type(contract) is _ValidationContract and contract.current()
        else None
    )
    token = _active.set(operation)
    try:
        yield
    finally:
        if operation is not None:
            operation.invalidate()
        _active.reset(token)
        if parent is not None:
            parent.invalidate()
