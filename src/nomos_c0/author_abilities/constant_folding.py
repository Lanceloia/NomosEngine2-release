"""Fold closed author constants during compilation; never evaluate a live world."""

import operator
from collections.abc import Mapping

from nomos_c0.author_contract_v1 import C0LawError

from .constant_values import ConstantValues
from .expression_syntax import ExpressionError
from .expressions import NORMALIZED_OPERATIONS
from .values import ValueBindingError, _Budget


def fold_constant(expression, values, environment):
    if type(values) is not ConstantValues or values.table is not expression.table:
        raise C0LawError("constant folding needs its checked declaration values")
    if (
        expression.summary.owner_reads
        or expression.summary.reference_domains
        or expression.actor is not None
    ):
        expression.source.fail(
            "InvalidConstant", 0, "closed compile-time value", "world dependency"
        )
    if not isinstance(environment, Mapping) or set(environment) != {
        name for name, _ in expression.inputs
    }:
        expression.source.fail(
            "MissingBinding", 0, "exact declared value inputs", "missing or extra input"
        )
    bound = {
        name: values.bind(spec.type_name, environment[name]).value
        for name, spec in expression.inputs
    }
    result = ConstantFolder(values, expression.limits).evaluate(
        expression.node, bound, expression.source
    )
    try:
        return values.bind(expression.result.name, result)
    except ValueBindingError as error:
        expression.source.fail(
            "ExpressionBudget" if error.diagnostic.code == "ValueBudget" else error.diagnostic.code,
            expression.node.offset,
            expression.result.name,
            error.diagnostic.code,
        )


class ConstantFolder:
    def __init__(self, codec, limits):
        self.codec, self.limits = codec, limits
        self.steps = self.depth = 0

    def evaluate(self, node, environment, source):
        self.steps += 1
        self.depth += 1
        if self.steps > self.limits.steps or self.depth > self.limits.depth:
            source.fail(
                "ExpressionBudget",
                node.offset,
                "bounded evaluation",
                "step/depth limit",
                stage="Compile",
            )
        try:
            return self._evaluate(node, environment, source)
        except ZeroDivisionError:
            source.fail(
                "InvalidValue", node.offset, "nonzero divisor", "division by zero", stage="Compile"
            )
        except ValueBindingError as error:
            source.fail(
                "ExpressionBudget"
                if error.diagnostic.code == "ValueBudget"
                else error.diagnostic.code,
                node.offset,
                "valid pure value",
                error.diagnostic.code,
                stage="Compile",
            )
        finally:
            self.depth -= 1

    def iteration_step(self, node, source):
        self.steps += 1
        if self.steps > self.limits.steps:
            source.fail(
                "ExpressionBudget", node.offset, "bounded iteration", "step limit", stage="Compile"
            )

    def check_collection(self, plan, value):
        """Check intermediate structural resources without turning them into named data types."""
        budget = _Budget(self.codec.limits)

        def walk(kind, item, path):
            budget.check(kind, path)
            if kind.kind == "optional" and item is not None:
                walk(kind.element, item, path)
            elif kind.kind in ("set", "sequence"):
                budget.collection(kind, item, path)
                for index, member in enumerate(item):
                    walk(kind.element, member, (*path, index))
            elif kind.kind == "record":
                for field, child in kind.fields:
                    walk(
                        child,
                        object.__getattribute__(item, kind.storage_field(field)),
                        (*path, field),
                    )
            elif kind.kind == "variant":
                child = next(child for _, child in kind.cases if type(item) is child.annotation)
                walk(child, item, path)

        walk(plan, value, ())
        return value

    def _evaluate(self, node, environment, source):
        operation, children = node.operation, node.children

        if operation not in NORMALIZED_OPERATIONS:
            source.fail("InvalidConstant", node.offset, "declared normalized operation", operation)
        if (
            node.owner_reads
            or node.reference_domains
            or operation in {"local_view", "known", "entity_field", "relation"}
        ):
            source.fail("InvalidConstant", node.offset, "closed compile-time value", operation)

        def evaluate(child):
            return self.evaluate(child, environment, source)

        if operation == "literal":
            return node.operand
        if operation == "variable":
            return environment[node.operand]
        if operation == "field":
            plan, name = node.operand
            return object.__getattribute__(evaluate(children[0]), plan.storage_field(name))
        if operation == "if":
            return evaluate(children[1] if evaluate(children[0]) else children[2])
        if operation == "match":
            subject = evaluate(children[0])
            index, binding = next(
                (index, binding)
                for index, binding in enumerate(node.operand)
                if type(subject) is binding[2]
            )
            _, binder, _ = binding
            local = environment if binder is None else {**environment, binder: subject}
            return self.evaluate(children[index + 1], local, source)
        if operation == "and":
            return evaluate(children[0]) and evaluate(children[1])
        if operation == "or":
            return evaluate(children[0]) or evaluate(children[1])
        if operation == "not":
            return not evaluate(children[0])
        if operation == "unary":
            value = evaluate(children[0])
            return value if node.operand == "+" else -value
        if operation in ("is", "is not"):
            result = evaluate(children[0]) is None
            return result if operation == "is" else not result
        if operation in ("in", "not in"):
            result = evaluate(children[0]) in evaluate(children[1])
            return result if operation == "in" else not result
        functions = {
            "+": operator.add,
            "-": operator.sub,
            "*": operator.mul,
            "//": operator.floordiv,
            "%": operator.mod,
            "==": operator.eq,
            "!=": operator.ne,
            "<": operator.lt,
            "<=": operator.le,
            ">": operator.gt,
            ">=": operator.ge,
        }
        if operation in functions:
            return functions[operation](*(evaluate(child) for child in children))
        if operation == "construct":
            tag, fields = node.operand
            values = {
                key: evaluate(child) for (key, _), child in zip(fields, children, strict=True)
            }
            return self.codec.construct(node.value_type.name, values, tag=tag).value
        if operation == "collection":
            values = (evaluate(child) for child in children)
            result = frozenset(values) if node.value_type.kind == "set" else tuple(values)
            return self.codec.bind(node.value_type.name, result).value
        if operation == "pure_call":
            definition = node.operand
            values = {
                key: self.codec.bind(plan.name, evaluate(child)).value
                for (key, plan), child in zip(definition.parameters, children, strict=True)
            }
            result = self.evaluate(definition.body, values, definition.source)
            return self.codec.bind(definition.returns.name, result).value
        first = evaluate(children[0])
        if operation == "at":
            index = evaluate(children[1])
            if not 0 <= index < len(first):
                source.fail(
                    "InvalidValue",
                    node.offset,
                    "current sequence bounds",
                    "index out of bounds",
                    stage="Compile",
                )
            return first[index]
        if operation in ("take", "drop"):
            count = evaluate(children[1])
            if count < 0:
                source.fail(
                    "InvalidValue",
                    node.offset,
                    "nonnegative prefix length",
                    str(count),
                    stage="Compile",
                )
            return self.check_collection(
                node.value_type, first[:count] if operation == "take" else first[count:]
            )
        if operation == "append":
            element = self.codec.table.expression_type(node.value_type.element)
            item = self.codec.bind(element.name, evaluate(children[1])).value
            return self.check_collection(node.value_type, (*first, item))
        if operation == "concat":
            return self.check_collection(node.value_type, (*first, *evaluate(children[1])))
        if operation == "index_of":
            item = evaluate(children[1])
            for index, candidate in enumerate(first):
                if candidate == item:
                    return index
            source.fail(
                "MissingSequenceMember",
                node.offset,
                "member of the current sequence",
                "absent",
                stage="Compile",
            )
        if operation == "size":
            return len(first)
        if operation == "distinct":
            return self.check_collection(node.value_type, frozenset(first))
        if operation == "contains":
            return evaluate(children[1]) in first
        if operation in ("union", "difference"):
            second = evaluate(children[1])
            result = first | second if operation == "union" else first - second
            return self.check_collection(node.value_type, result)
        if operation == "sum":
            total = 0
            for value in first:
                self.steps += 1
                if self.steps > self.limits.steps:
                    source.fail(
                        "ExpressionBudget",
                        node.offset,
                        "bounded sum",
                        "step limit",
                        stage="Compile",
                    )
                total += value
            return total
        if operation == "latest_by":
            rows, maxima = [], {}
            for item in first:
                self.iteration_step(node, source)
                key, version = (
                    self.evaluate(body, {**environment, parameter: item}, source)
                    for body, parameter in zip(children[1:], node.operand, strict=True)
                )
                rows.append((item, key, version))
                if key not in maxima or version > maxima[key]:
                    maxima[key] = version
            output = []
            for item, key, version in rows:
                self.iteration_step(node, source)
                if version == maxima[key]:
                    output.append(item)
            return self.check_collection(node.value_type, tuple(output))
        if operation in ("min_by", "max_by"):
            found, best, best_key, tied = False, None, None, False
            better = operator.lt if operation == "min_by" else operator.gt
            for item in first:
                keys = []
                for body, parameter in zip(children[1:], node.operand, strict=True):
                    keys.append(self.evaluate(body, {**environment, parameter: item}, source))
                key = tuple(keys)
                if not found or better(key, best_key):
                    found, best, best_key, tied = True, item, key, False
                elif key == best_key and children[0].value_type.kind == "set" and item != best:
                    tied = True
            if tied:
                source.fail(
                    "AmbiguousSelection",
                    node.offset,
                    "unique best Set element or explicit distinguishing tie key",
                    "multiple equally ranked elements",
                    stage="Compile",
                )
            return best
        output, total, failure = [], 0, None

        def failure_key(error):
            return (error.diagnostic.path, error.diagnostic.offset, error.diagnostic.actual)

        for item in first:
            try:
                value = self.evaluate(children[1], {**environment, node.operand: item}, source)
            except ExpressionError as error:
                if (
                    operation not in ("exists", "exactly_one", "forall")
                    or error.diagnostic.code != "InvalidValue"
                ):
                    raise
                # A decisive Boolean witness dominates a partial predicate failure.
                # Deferring value failures keeps an unordered Set independent of traversal order.
                if failure is None or failure_key(error) < failure_key(failure):
                    failure = error
                continue
            if operation == "exists" and value:
                return True
            if operation == "forall" and not value:
                return False
            if operation == "exactly_one" and value:
                total += 1
                if total == 2:
                    return False
            if operation == "sum_by":
                total += value
            elif operation == "filter" and value:
                output.append(item)
            elif operation == "map":
                output.append(value)
        if operation in ("exists", "exactly_one", "forall"):
            if failure is not None:
                raise failure
            return total == 1 if operation == "exactly_one" else operation == "forall"
        if operation == "sum_by":
            return total
        if len(output) > self.codec.limits.items:
            source.fail(
                "ExpressionBudget",
                node.offset,
                "bounded collection",
                "member limit",
                stage="Compile",
            )
        result = frozenset(output) if node.value_type.kind == "set" else tuple(output)
        return self.check_collection(node.value_type, result)
