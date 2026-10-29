"""Compilation-scoped record escape analysis for private pure-query parameters."""

_BINDERS = frozenset(
    {"filter", "map", "sum_by", "exists", "exactly_one", "forall", "min_by", "max_by", "latest_by"}
)


class RecordParameterPlan:
    """Select one flattened signature per query, following acyclic argument flow."""

    def __init__(self):
        self._selected = {}
        self._fields = {}
        self._pending = set()

    def select(self, definition):
        key = id(definition)
        if key in self._selected:
            return self._selected[key][1]
        if key in self._pending:
            return ()
        self._pending.add(key)
        try:
            selected, remaining = [], 64
            for index, (name, plan) in enumerate(definition.parameters):
                used = set()
                safe = plan.kind == "record" and self._fields_only(definition.body, name, used)
                fields = tuple(field for field, _ in plan.fields if field in used)
                size = 1 + len(fields)
                if plan.kind == "record" and len(plan.fields) <= 16 and size <= remaining and safe:
                    selected.append(index)
                    self._fields[key, index] = fields
                    remaining -= size
            result = tuple(selected)
            self._selected[key] = definition, result
            return result
        finally:
            self._pending.remove(key)

    def fields(self, definition, index):
        self.select(definition)
        return self._fields[id(definition), index]

    def _fields_only(self, node, name, used):
        if node.operation == "variable":
            return node.operand != name
        if node.operation == "field":
            child = node.children[0]
            if child.operation == "variable" and child.operand == name:
                used.add(node.operand[1])
                return True
        if node.operation == "pure_call":
            callee = node.operand
            for index, child in enumerate(node.children):
                if child.operation == "variable" and child.operand == name:
                    if index not in self.select(callee):
                        return False
                    used.update(self.fields(callee, index))
                elif not self._fields_only(child, name, used):
                    return False
            return True
        if node.operation == "match":
            if not self._fields_only(node.children[0], name, used):
                return False
            return all(
                binder == name or self._fields_only(child, name, used)
                for (_, binder, _), child in zip(node.operand, node.children[1:], strict=True)
            )
        if node.operation in _BINDERS:
            if not self._fields_only(node.children[0], name, used):
                return False
            names = (
                node.operand
                if node.operation in {"min_by", "max_by", "latest_by"}
                else (node.operand,)
            )
            return all(
                binder == name or self._fields_only(child, name, used)
                for binder, child in zip(names, node.children[1:], strict=True)
            )
        return all(self._fields_only(child, name, used) for child in node.children)
