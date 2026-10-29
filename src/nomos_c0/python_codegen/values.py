"""Register checked value plans and assemble their carriers, helpers and registries."""

import ast

from . import codecs, nominal, references, syntax


def _children(plan):
    if plan.kind in {"optional", "set", "sequence"}:
        return (plan.element,)
    if plan.kind in {"record", "variant"}:
        return tuple(child for _, child in (*plan.fields, *plan.cases))
    return ()


class ValueEmitter:
    def __init__(self, source, *, references=False):
        self.source = source
        self.references = references
        self.plans = {}
        self.names = {}
        self.shapes = {}
        self.validation_keys = {}
        self.private_plans = set()

    def equivalent_validation(self, left, right):
        return left.type_id == right.type_id or self.validation_key(left) == self.validation_key(
            right
        )

    def validation_key(self, plan):
        if plan.type_id not in self.validation_keys:
            kind = plan.kind
            if kind in {"set", "sequence", "optional"}:
                key = kind, self.validation_key(plan.element)
            elif kind == "int":
                key = kind, plan.minimum, plan.maximum
            elif kind == "text":
                key = kind, plan.maximum
            elif kind in {"bool", "unit"}:
                key = (kind,)
            else:
                # Enum, Ref, record and variant identities remain nominal.
                key = kind, plan.type_id
            self.validation_keys[plan.type_id] = key
        return self.validation_keys[plan.type_id]

    def add_shape(self, plan):
        if plan.type_id in self.shapes:
            return
        self.shapes[plan.type_id] = plan
        if plan.kind in {"set", "sequence", "optional"}:
            self.add_shape(plan.element)
        elif plan.kind in {"record", "variant"}:
            self.add(plan)
            for _, child in (*plan.fields, *plan.cases):
                self.add_shape(child)

    def shape(self, plan):
        return "_shape_" + str(tuple(self.shapes).index(plan.type_id))

    def add(self, plan, *, public=True):
        key = plan.type_id
        if key in self.plans:
            if public and key in self.private_plans:
                self.private_plans.remove(key)
                self.names[plan.name] = key
                for child in _children(plan):
                    self.add(child)
            return self.index(plan)
        if not (plan.kind == "ref" and self.references) and plan.kind not in {
            "bool",
            "unit",
            "int",
            "text",
            "enum",
            "record",
            "variant",
            "optional",
            "set",
            "sequence",
        }:
            self.source.fail(
                "UnsupportedFeature", 0, "implemented Python value lowering", plan.kind
            )
        self.plans[key] = plan
        if public:
            self.names[plan.name] = key
        else:
            self.private_plans.add(key)
        for child in _children(plan):
            self.add(child, public=public)
        return self.index(plan)

    def index(self, plan):
        return tuple(self.plans).index(plan.type_id)

    def field(self, plan, field):
        if field not in dict(plan.fields):
            raise KeyError(field)
        return field

    def validator(self, plan):
        return "_check_" + str(self.index(plan))

    def carrier(self, plan):
        return "_Record" + str(self.index(plan))

    def emit(self, *, decoders=False):
        body = []
        for plan in self.plans.values():
            if plan.kind == "record":
                fields = "\n".join(
                    f"    {self.field(plan, name)}: object" for name, _ in plan.fields
                )
                body.extend(
                    syntax.statements(
                        f"@dataclass(frozen=True, slots=True)\nclass {self.carrier(plan)}:\n"
                        + (fields or "    pass")
                    )
                )
        for plan in self.plans.values():
            body.append(nominal.emit_validator(self, plan))
            if decoders:
                body.append(codecs.emit_decoder(self, plan))
                body.append(codecs.emit_encoder(self, plan))
                body.append(references.emit_reference_reader(self, plan))
            if plan.kind == "record":
                body.append(nominal.emit_constructor(self, plan))
        body.extend(nominal.emit_shape(self, plan) for plan in self.shapes.values())
        entries = [(name, self.plans[key]) for name, key in self.names.items()]
        body.append(
            ast.Assign(
                targets=[ast.Name(id="_VALIDATORS", ctx=ast.Store())],
                value=ast.Dict(
                    keys=[syntax.constant(name) for name, _ in entries],
                    values=[
                        ast.Name(id=self.validator(plan), ctx=ast.Load()) for _, plan in entries
                    ],
                ),
            )
        )
        if decoders:
            body.append(
                ast.Assign(
                    targets=[ast.Name(id="_ENCODERS", ctx=ast.Store())],
                    value=ast.Dict(
                        keys=[syntax.constant(name) for name, _ in entries],
                        values=[
                            ast.Name(id=self.encoder(plan), ctx=ast.Load()) for _, plan in entries
                        ],
                    ),
                )
            )
            body.append(
                ast.Assign(
                    targets=[ast.Name(id="_DECODERS", ctx=ast.Store())],
                    value=ast.Dict(
                        keys=[syntax.constant(name) for name, _ in entries],
                        values=[
                            ast.Name(id=self.decoder(plan), ctx=ast.Load()) for _, plan in entries
                        ],
                    ),
                )
            )
            body.append(
                ast.Assign(
                    targets=[ast.Name(id="_REFERENCES", ctx=ast.Store())],
                    value=ast.Dict(
                        keys=[syntax.constant(name) for name, _ in entries],
                        values=[
                            ast.Name(id=self.reference_reader(plan), ctx=ast.Load())
                            for _, plan in entries
                        ],
                    ),
                )
            )
        records = [(name, plan) for name, plan in entries if plan.kind == "record"]
        for registry, prefix in (("RECORDS", "_Record"), ("_CONSTRUCTORS", "_make_")):
            body.append(
                ast.Assign(
                    targets=[ast.Name(id=registry, ctx=ast.Store())],
                    value=ast.Dict(
                        keys=[syntax.constant(name) for name, _ in records],
                        values=[
                            ast.Name(id=prefix + str(self.index(plan)), ctx=ast.Load())
                            for _, plan in records
                        ],
                    ),
                )
            )
        body.extend(
            syntax.statements("""
def bind(name, value, *, value_limits=ValueLimits()):
    return _VALIDATORS[name](value, ValueBudget(value_limits), ())

def construct(name, fields, *, value_limits=ValueLimits()):
    return _CONSTRUCTORS[name](fields, ValueBudget(value_limits))
""")
        )
        return body

    def reference_reader(self, plan):
        return "_references_" + str(self.index(plan))

    def decoder(self, plan):
        return "_decode_" + str(self.index(plan))

    def encoder(self, plan):
        return "_encode_" + str(self.index(plan))
