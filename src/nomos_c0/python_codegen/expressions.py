"""Generate direct Python statements for a checked expression, never an IR runner."""

import ast

from nomos_c0.author_abilities.expressions import CheckedValueExpression
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.correlated_sum_plan import plan_correlated_sum
from nomos_c0.expression_analysis import ExpressionAnalysis
from nomos_c0.expression_entry_proofs import ExpressionEntryProof
from nomos_c0.grouped_latest_plan import plan_grouped_latest
from nomos_c0.query_inline import QueryInlinePlan
from nomos_c0.query_plan import plan_query_reuse
from nomos_c0.record_parameters import RecordParameterPlan
from nomos_c0.record_projection import VirtualRecord, can_project_record
from nomos_c0.variant_query_plan import plan_constant_variant

from ..loop_query_memo import plan_loop_query_memo
from .correlated_sum import correlated_sum
from .finite import collection_operation, filtered_count, latest_by, quantifier, ranking
from .grouped_latest import grouped_latest
from .iteration_order import ordered_pool
from .loop_query_memo import LoopQueryMemoEmitter
from .pipeline import ModuleOptimizer
from .proofs import ValueProofs
from .query_reuse import QueryReuseEmitter
from .syntax import constant, statements
from .values import ValueEmitter
from .variant_queries import constant_variant_call, emit_constant_variant_tables

SUPPORTED_OPERATIONS = frozenset(
    {
        "literal",
        "variable",
        "field",
        "construct",
        "collection",
        "pure_call",
        "filter",
        "map",
        "size",
        "contains",
        "sum",
        "sum_by",
        "exists",
        "exactly_one",
        "forall",
        "min_by",
        "max_by",
        "latest_by",
        "distinct",
        "union",
        "difference",
        "at",
        "append",
        "concat",
        "index_of",
        "take",
        "drop",
        "if",
        "match",
        "and",
        "or",
        "not",
        "unary",
        "is",
        "is not",
        "in",
        "not in",
        "+",
        "-",
        "*",
        "//",
        "%",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
    }
)
_BINARY = {"+": ast.Add, "-": ast.Sub, "*": ast.Mult, "//": ast.FloorDiv, "%": ast.Mod}
_COMPARE = {
    "==": ast.Eq,
    "!=": ast.NotEq,
    "<": ast.Lt,
    "<=": ast.LtE,
    ">": ast.Gt,
    ">=": ast.GtE,
    "in": ast.In,
    "not in": ast.NotIn,
    "is": ast.Is,
    "is not": ast.IsNot,
}


class _Emitter:
    def __init__(self, checked, *, world=False, report=None):
        self.checked = checked
        self.world = world
        self.types = ValueEmitter(checked.source, references=world)
        self.count = 0
        self.inputs = {name: f"_input_{index}" for index, (name, _) in enumerate(checked.inputs)}
        self.definitions = {}
        self.sources = [checked.source]
        self.pending = set()
        self.query_reuse = None
        self.query_plans = []
        self.analysis = ExpressionAnalysis()
        self.proofs = ValueProofs(self.types, self.analysis, checked.table)
        self.report = report
        self.function_name = None
        self.inline_operands = False
        self.record_parameters = RecordParameterPlan()
        self.grouped_latest_used = False
        self.constant_variant_tables = {}
        if report is not None:
            report.begin()

    def note(self, status, optimization, source, offsets, reason, detail):
        if self.report is not None:
            self.report.remark(
                status, optimization, self.function_name, source, offsets, reason, detail
            )

    def plan_function(self, name, node, environment, source, *, mode, query=False, actor=None):
        self.function_name = name
        self.query_inline = QueryInlinePlan(self.analysis)
        self.record_projection_remaining = 64
        plan = plan_query_reuse(
            node,
            environment,
            query=query,
            actor=actor,
            analysis=self.analysis,
            explain=self.report is not None,
        )
        self.query_reuse = QueryReuseEmitter(plan)
        self.query_memo = LoopQueryMemoEmitter(
            plan_loop_query_memo(node, environment, self.analysis, shared=self.query_reuse.sites)
        )
        if plan.groups:
            self.query_plans.append((name, source.path, *plan.manifest()))
        if self.report is not None:
            self.report.analyze(name, source, mode, self.analysis.facts(node))
            for site in self.query_memo.sites.values():
                self.note(
                    "Passed",
                    "query-loop-memo",
                    source,
                    (site.call.offset,),
                    "invocation-local-checked-scalar-keys",
                    "Memoize a heavy pure query by varying checked scalar arguments; "
                    "stable complex arguments remain fixed; retain checks and logical costs.",
                )
            for decision in plan.decisions:
                self.note(
                    decision.status,
                    "query-reuse",
                    source,
                    decision.offsets,
                    decision.reason,
                    f"Query {decision.definition}; sharing stays inside this invocation "
                    "and preserves first use, source diagnostics and logical budgets.",
                )

    def prepare(self, node, source):
        if node.operation not in SUPPORTED_OPERATIONS and not (
            self.world and node.operation in {"known", "entity_field", "local_view", "relation"}
        ):
            source.fail(
                "UnsupportedFeature",
                node.offset,
                "implemented Python expression lowering",
                node.operation,
            )
        if node.operation in {"construct", "collection", "known"}:
            self.types.add(node.value_type)
        if node.operation == "match":
            self.types.add(node.children[0].value_type)
        if node.operation == "latest_by":
            for child in node.children:
                self.types.add(child.value_type, public=False)
        if node.operation in {
            "filter",
            "map",
            "distinct",
            "union",
            "difference",
            "append",
            "concat",
            "take",
            "drop",
        }:
            self.types.add_shape(node.value_type)
        if node.operation == "append":
            self.types.add(self.checked.table.expression_type(node.value_type.element))
        if node.operation == "local_view":
            self.types.add(node.value_type)
        if node.operation == "pure_call":
            definition = node.operand
            if definition.name in self.pending:
                source.fail("InvalidCall", node.offset, "acyclic pure definitions", definition.name)
            if definition.name not in self.definitions:
                self.definitions[definition.name] = definition
                if definition.source not in self.sources:
                    self.sources.append(definition.source)
                self.pending.add(definition.name)
                for _, plan in definition.parameters:
                    self.types.add(plan)
                self.types.add(definition.returns)
                self.prepare(definition.body, definition.source)
                self.pending.remove(definition.name)
        for child in node.children:
            self.prepare(child, source)

    def assign(self, name, value):
        return ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=value)

    def source_name(self, source):
        return "_SOURCE_" + str(self.sources.index(source))

    def definition_name(self, definition):
        return "_query_" + definition.name

    def note_branch_proof(self, node, source, offset):
        while node.operation == "field":
            node = node.children[0]
        if node.operation in {"if", "match"}:
            self.note(
                "Passed",
                "nominal-branch-result",
                source,
                (offset,),
                "all-selected-results-checked",
                "Reuse the validated result contract on every selected branch; "
                "retain condition/dispatch, first checks, failures and logical work.",
            )

    def note_validation_congruence(self, node, plan, source, offset):
        if node.value_type.type_id != plan.type_id:
            self.note(
                "Passed",
                "value-validation-congruence",
                source,
                (offset,),
                "identical-python-validation-contract",
                f"Reuse checked {node.value_type.name} for {plan.name}; preserve nominal "
                "identities, first checks, current read domain and logical budgets.",
            )

    def note_collection_proof(self, node, source, offset):
        if node.operation in {"map", "distinct", "union", "concat", "append"}:
            self.note(
                "Passed",
                "collection-result-validation",
                source,
                (offset,),
                "checked-elements-and-original-structure-budget",
                f"Reuse {node.operation} elements' existing contracts after its original "
                "structural check; retain production, first failures and logical work.",
            )

    def branch(self, generate):
        with self.proofs.branch():
            return generate()

    def scalar_result_proven(self, node, plan, source, offset, body, *, environment, bindings=None):
        # Inferred collection element ranges need an actual provenance proof: an
        # append insertion boundary can validate a wider native integer contract.
        if not self.proofs.scalar_result_proven(node, plan, environment, bindings=bindings):
            return False
        return self.scalar_check_proven(
            node, plan, source, offset, body, optimization="scalar-result-validation"
        )

    def scalar_parameter_proven(self, node, plan, source, offset, body, *, environment):
        # A local lambda/match binder may come from an unvalidated external value.
        # Unlike query results, this boundary has not checked its operands yet.
        if not self.proofs.checked_operands(node, environment):
            return False
        return self.scalar_check_proven(
            node, plan, source, offset, body, optimization="scalar-parameter-validation"
        )

    def scalar_check_proven(self, node, plan, source, offset, body, *, optimization):
        native = self.analysis.scalar_result_with_checked_inputs(node, plan)
        bounded = not native and self.analysis.bounded_integer_result_with_checked_inputs(
            node, plan
        )
        if not native and not bounded:
            return False
        # Retain the limits ABI failure at this exact check site, including zero-input
        # queries whose evaluation may fail before reaching their first value check.
        body.extend(
            statements(
                "if type(value_limits) is not ValueLimits:\n"
                "    raise TypeError('generated value needs ValueLimits')"
            )
        )
        self.note(
            "Passed",
            optimization,
            source,
            (offset,),
            "checked-input-integer-range" if bounded else "checked-input-native-scalar",
            f"Prove exact {plan.kind} value and a total fresh scalar value check; "
            "retain input checks, evaluation, failures and logical budgets.",
        )
        return True

    def emit(
        self,
        node,
        body,
        depth=1,
        *,
        environment=None,
        source=None,
        nested=False,
        roles=None,
        virtual_record=False,
    ):
        environment = self.inputs if environment is None else environment
        source = self.checked.source if source is None else source
        origin = self.source_name(source)

        def emit(child, block=body):
            return self.emit(
                child,
                block,
                depth + 1,
                environment=environment,
                source=source,
                nested=nested,
                roles=roles,
            )

        logical_depth = f"_depth + {depth}" if nested else str(depth)
        name = f"_v{self.count}"
        self.count += 1
        result = ast.Name(id=name, ctx=ast.Load())
        body.extend(statements(f"_budget.visit({origin}, {node.offset}, {logical_depth})"))
        operation = node.operation
        if operation == "variable" and isinstance(environment[node.operand], VirtualRecord):
            return environment[node.operand]
        if self.inline_operands and operation in {"literal", "variable"}:
            # These operands cannot fail or change; retain their visit, not a copy local.
            return (
                constant(node.operand)
                if operation == "literal"
                else ast.Name(id=environment[node.operand], ctx=ast.Load())
            )
        if operation == "literal":
            value = constant(node.operand)
        elif operation == "variable":
            value = ast.Name(id=environment[node.operand], ctx=ast.Load())
        elif operation in {"and", "or", "if"}:
            condition = emit(node.children[0])
            left, right = [], []
            if operation == "if":
                left.append(self.assign(name, self.branch(lambda: emit(node.children[1], left))))
                right.append(self.assign(name, self.branch(lambda: emit(node.children[2], right))))
            else:
                branch = left if operation == "and" else right
                branch.append(
                    self.assign(name, self.branch(lambda: emit(node.children[1], branch)))
                )
                (right if operation == "and" else left).append(self.assign(name, condition))
            body.append(ast.If(test=condition, body=left, orelse=right))
            return result
        elif operation == "match":
            return self.match(
                node,
                body,
                name,
                emit(node.children[0]),
                depth,
                environment=environment,
                source=source,
                nested=nested,
                roles=roles,
            )
        elif operation == "pure_call":
            definition = node.operand
            flattened = self.record_parameters.select(definition)
            projections = [
                can_project_record(
                    child,
                    plan,
                    parameter,
                    definition.body,
                    shared=id(child) in self.query_reuse.sites,
                )
                for (parameter, plan), child in zip(
                    definition.parameters, node.children, strict=True
                )
            ]
            # A flattened parameter can cross query boundaries without carrying
            # a record object. Fresh construction still needs its own proof.
            for index, child in enumerate(node.children):
                if index in flattened:
                    parameter, plan = definition.parameters[index]
                    projections[index] = can_project_record(
                        child,
                        plan,
                        parameter,
                        definition.body,
                        shared=id(child) in self.query_reuse.sites,
                        forwarded=True,
                    )
            if self.world:
                for index, (_, plan) in enumerate(definition.parameters):
                    if not projections[index]:
                        continue
                    child = node.children[index]
                    construct = child.operand.body if child.operation == "pure_call" else child
                    parameters = (
                        {name: name for name, _ in child.operand.parameters}
                        if child.operation == "pure_call"
                        else environment
                    )
                    bindings = set(parameters) if child.operation == "pure_call" else None
                    if not self.proofs.record_fields_proven(
                        construct, parameters, bindings=bindings
                    ):
                        # The read scope already reuses the successful composite
                        # constructor proof. Virtualizing it would deep-check its
                        # fields at every call instead of reusing that proof.
                        projections[index] = False
                        self.note(
                            "Missed",
                            "record-scalar-replacement",
                            source,
                            (node.children[index].offset,),
                            "checked-constructor-reuse",
                            "Keep composite construction proof reuse; "
                            "still pass selected fields across queries.",
                        )
            available = self.record_projection_remaining
            for index, (_, plan) in enumerate(definition.parameters):
                cost = 1 + len(plan.fields)
                if projections[index] and cost <= available:
                    available -= cost
                else:
                    projections[index] = False
            decision = (
                self.query_inline.select(
                    definition,
                    shared=id(node) in self.query_reuse.sites or id(node) in self.query_memo.sites,
                )
                if any(projections) and not virtual_record
                else None
            )
            if flattened and not virtual_record:
                self.record_projection_remaining = available
            elif decision and decision.selected:
                self.record_projection_remaining = available
            children = []
            for index, ((_, plan), child) in enumerate(
                zip(definition.parameters, node.children, strict=True)
            ):
                argument = self.emit(
                    child,
                    body,
                    depth + 1,
                    environment=environment,
                    source=source,
                    nested=nested,
                    roles=roles,
                    virtual_record=bool(
                        projections[index]
                        and not virtual_record
                        and (index in flattened or decision and decision.selected)
                    ),
                )
                argument_proven = self.proofs.validated_argument(child, plan, environment)
                if argument_proven:
                    self.note_branch_proof(child, source, node.offset)
                    self.note_validation_congruence(child, plan, source, node.offset)
                    self.note_collection_proof(child, source, node.offset)
                if not argument_proven and not self.scalar_parameter_proven(
                    child, plan, source, node.offset, body, environment=environment
                ):
                    self.validate_result(
                        plan,
                        argument,
                        node.offset,
                        body,
                        origin=origin,
                        reusable=child.operation == "local_view",
                    )
                    if child.operation == "local_view" and self.types.equivalent_validation(
                        child.value_type, plan
                    ):
                        self.proofs.local_views.add((child.operand, child.value_type.type_id))
                elif child.operation == "local_view":
                    self.note(
                        "Passed",
                        "local-validation",
                        source,
                        (child.offset,),
                        "dominating-exact-type-check",
                        "Reuse the successful local input proof.",
                    )
                children.append(argument)
            if virtual_record:
                return self.inline_query(
                    definition, children, body, name, depth, nested=nested, virtual_record=True
                )
            call_arguments = []
            for index, (argument, (_, plan)) in enumerate(
                zip(children, definition.parameters, strict=True)
            ):
                if index in flattened:
                    call_arguments.extend(
                        dict(argument.fields)[field]
                        if isinstance(argument, VirtualRecord)
                        else ast.Attribute(
                            value=argument, attr=self.types.field(plan, field), ctx=ast.Load()
                        )
                        for field in self.record_parameters.fields(definition, index)
                    )
                else:
                    call_arguments.append(argument)
            call = (
                None
                if any(isinstance(child, VirtualRecord) for child in call_arguments)
                else ast.Call(
                    func=ast.Name(id=self.definition_name(definition), ctx=ast.Load()),
                    args=[
                        ast.Name(id="_budget", ctx=ast.Load()),
                        ast.Name(id="value_limits", ctx=ast.Load()),
                        ast.parse(logical_depth, mode="eval").body,
                        *(
                            [
                                ast.Name(id="reads", ctx=ast.Load()),
                                ast.Tuple(
                                    elts=[
                                        self.own_role(child.path, roles) for child in node.children
                                    ],
                                    ctx=ast.Load(),
                                ),
                            ]
                            if self.world
                            else []
                        ),
                        *call_arguments,
                    ],
                    keywords=[],
                )
            )
            decision = decision or self.query_inline.select(
                definition,
                shared=id(node) in self.query_reuse.sites or id(node) in self.query_memo.sites,
            )
            if decision.selected:
                self.inline_query(definition, children, body, name, depth, nested=nested)
                self.note(
                    "Passed",
                    "query-inline",
                    source,
                    (node.offset,),
                    decision.reason,
                    f"Inline query {definition.name} ({decision.size} body nodes); "
                    "keep argument checks, body source, return checks and logical depth.",
                )
            else:
                variant_plan = (
                    None
                    if id(node) in self.query_reuse.sites
                    else plan_constant_variant(definition)
                )
                if variant_plan is not None:
                    normal = []
                    if not self.query_memo.emit(
                        self, node, normal, name, call, children, logical_depth
                    ):
                        normal.append(self.assign(name, call))
                    constant_variant_call(
                        self,
                        definition,
                        variant_plan,
                        children,
                        body,
                        name,
                        normal,
                        depth,
                        nested=nested,
                    )
                    self.note(
                        "Passed",
                        "variant-query-dispatch",
                        source,
                        (node.offset,),
                        "constant-nominal-arms",
                        f"Bypass query {definition.name}: {len(variant_plan.cases)} literal arms; "
                        "retain argument checks, original visits and call-site return checks.",
                    )
                else:
                    if not self.query_memo.emit(
                        self, node, body, name, call, children, logical_depth
                    ):
                        self.query_reuse.emit(self, node, body, name, call, logical_depth)
                self.note(
                    "Missed",
                    "query-inline",
                    source,
                    (node.offset,),
                    decision.reason,
                    f"Keep query {definition.name} as a direct generated function call.",
                )
            parameters = {name: name for name, _ in definition.parameters}
            result_proven = self.proofs.validated_argument(
                definition.body, definition.returns, parameters, bindings=set(parameters)
            )
            if result_proven:
                self.note_branch_proof(definition.body, source, node.offset)
                self.note_validation_congruence(
                    definition.body, definition.returns, source, node.offset
                )
                self.note_collection_proof(definition.body, source, node.offset)
            if not result_proven and not self.scalar_result_proven(
                definition.body,
                definition.returns,
                source,
                node.offset,
                body,
                environment=parameters,
                bindings=set(parameters),
            ):
                self.validate_result(definition.returns, result, node.offset, body, origin=origin)
            return result
        elif operation == "local_view":
            load = statements(
                "if '' not in _local_values:\n    _local_values[''] = reads.local_value('')"
            )[0]
            load.test.left = constant(node.operand)
            load.body[0].targets[0].slice = constant(node.operand)
            load.body[0].value.args[0] = constant(node.operand)
            guard = statements(
                "try:\n    pass\nexcept ValueBindingError as error:\n"
                f"    {origin}.value_failure(error, {node.offset})"
            )[0]
            guard.body = [load]
            body.append(guard)
            value = ast.Subscript(
                value=ast.Name(id="_local_values", ctx=ast.Load()),
                slice=constant(node.operand),
                ctx=ast.Load(),
            )
        elif operation == "relation":
            from .carrying import query

            return query(
                self,
                node,
                body,
                depth,
                environment=environment,
                source=source,
                nested=nested,
                roles=roles,
            )
        elif operation == "known":
            value = ast.Call(
                func=ast.Attribute(
                    value=ast.Attribute(
                        value=ast.Name(id="reads", ctx=ast.Load()),
                        attr="references",
                        ctx=ast.Load(),
                    ),
                    attr="known",
                    ctx=ast.Load(),
                ),
                args=[constant(node.operand)],
                keywords=[],
            )
        elif operation in {"filter", "map", "sum_by", "sum"}:
            return self.iteration(
                node,
                body,
                name,
                emit(node.children[0]),
                depth,
                environment=environment,
                source=source,
                nested=nested,
                roles=roles,
            )
        elif operation in {"exists", "exactly_one", "forall", "min_by", "max_by", "latest_by"}:
            generator = (
                latest_by
                if operation == "latest_by"
                else ranking
                if operation in {"min_by", "max_by"}
                else quantifier
            )
            return generator(
                self,
                node,
                body,
                name,
                emit(node.children[0]),
                depth,
                environment=environment,
                source=source,
                nested=nested,
                roles=roles,
            )
        elif (
            operation == "size"
            and node.children[0].operation == "filter"
            and self.proofs.proven_subset(node.children[0], environment)
        ):
            self.note(
                "Passed",
                "filter-count-fusion",
                source,
                (node.offset,),
                "checked-subset",
                "Generate one count loop without an intermediate collection.",
            )
            return filtered_count(
                self,
                node.children[0],
                body,
                name,
                depth,
                environment=environment,
                source=source,
                nested=nested,
                roles=roles,
            )
        else:
            if operation == "size" and node.children[0].operation == "filter":
                self.note(
                    "Missed",
                    "filter-count-fusion",
                    source,
                    (node.offset,),
                    "input-proof-unavailable",
                    "Keep materialization and structural validation.",
                )
            children = [
                emit(child)
                for child in (node.children[:1] if operation in {"is", "is not"} else node.children)
            ]
            if operation in {
                "distinct",
                "union",
                "difference",
                "at",
                "append",
                "concat",
                "index_of",
                "take",
                "drop",
            }:
                if self.proofs.proven_subset(node, environment):
                    self.note(
                        "Passed",
                        "subset-validation",
                        source,
                        (node.offset,),
                        "checked-same-contract-subset",
                        "Keep original elements and their input proof.",
                    )
                return collection_operation(
                    self,
                    node,
                    children,
                    body,
                    name,
                    source,
                    subset_proven=self.proofs.proven_subset(node, environment),
                )
            if operation == "entity_field":
                request = node.operand
                value = ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="reads", ctx=ast.Load()), attr="read", ctx=ast.Load()
                    ),
                    args=[children[0], constant(request.sort), constant(request.field)],
                    keywords=[ast.keyword(arg="own", value=self.own_role(request.selector, roles))],
                )
            elif operation == "field":
                plan, field = node.operand
                value = (
                    dict(children[0].fields)[field]
                    if isinstance(children[0], VirtualRecord)
                    else ast.Attribute(
                        value=children[0], attr=self.types.field(plan, field), ctx=ast.Load()
                    )
                )
            elif operation in _BINARY:
                value = ast.BinOp(left=children[0], op=_BINARY[operation](), right=children[1])
            elif operation in _COMPARE:
                value = ast.Compare(
                    left=children[0],
                    ops=[_COMPARE[operation]()],
                    comparators=[constant(None) if operation in {"is", "is not"} else children[1]],
                )
            elif operation == "size":
                value = ast.Call(
                    func=ast.Name(id="len", ctx=ast.Load()), args=children, keywords=[]
                )
            elif operation == "contains":
                value = ast.Compare(left=children[1], ops=[ast.In()], comparators=[children[0]])
            elif operation in {"not", "unary"}:
                operator = (
                    ast.Not if operation == "not" else ast.UAdd if node.operand == "+" else ast.USub
                )
                value = ast.UnaryOp(op=operator(), operand=children[0])
            elif operation == "collection":
                value = ast.Tuple(elts=children, ctx=ast.Load())
                if node.value_type.kind == "set":
                    value = ast.Call(
                        func=ast.Name(id="frozenset", ctx=ast.Load()), args=[value], keywords=[]
                    )
            elif operation == "construct":
                tag, _ = node.operand
                plan = node.value_type if tag is None else dict(node.value_type.cases)[tag]
                if virtual_record:
                    scalar_fields = self.proofs.record_fields_proven(node, environment)
                    self.validate_record_fields(
                        plan,
                        children,
                        node.offset,
                        body,
                        origin=origin,
                        scalar_fields=scalar_fields,
                    )
                    self.note(
                        "Passed",
                        "record-scalar-replacement",
                        source,
                        (node.offset,),
                        "non-escaping-field-only-argument",
                        "Keep field evaluation and value-budget failures; omit the carrier. "
                        + (
                            "Prove scalar field checks total when structural limits fit."
                            if scalar_fields
                            else "Retain full field validation."
                        ),
                    )
                    return VirtualRecord(
                        tuple(zip((field for field, _ in plan.fields), children, strict=True))
                    )
                value = ast.Call(
                    func=ast.Name(id=self.types.carrier(plan), ctx=ast.Load()),
                    args=children,
                    keywords=[],
                )
                if self.world:
                    value = ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="reads", ctx=ast.Load()),
                            attr="checked_construct",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Name(id=self.types.validator(node.value_type), ctx=ast.Load()),
                            value.func,
                            ast.Tuple(elts=children, ctx=ast.Load()),
                            ast.Name(id="value_limits", ctx=ast.Load()),
                        ],
                        keywords=[],
                    )
                    guard = statements(
                        "try:\n    pass\nexcept ValueBindingError as error:\n"
                        f"    {origin}.value_failure(error, {node.offset})"
                    )[0]
                    guard.body = [self.assign(name, value)]
                    body.append(guard)
                    return result
            else:
                raise AssertionError(operation)
        assignment = self.assign(name, value)
        if operation in {"//", "%"}:
            guard = statements(
                "try:\n    pass\nexcept ZeroDivisionError:\n"
                f"    {origin}.fail('InvalidValue', {node.offset}, "
                "'nonzero divisor', 'division by zero')"
            )[0]
            guard.body = [assignment]
            body.append(guard)
        else:
            body.append(assignment)
        if operation in {"construct", "collection", "known"}:
            self.validate_result(node.value_type, result, node.offset, body, origin=origin)
        return result

    def validate_record_fields(self, plan, fields, offset, body, *, origin, scalar_fields):
        budget = f"_v{self.count}_record_budget"
        self.count += 1
        reference = ", reads.references" if self.world else ""
        guard = statements(
            f"try:\n    {budget} = ValueBudget(value_limits{reference})\n"
            "except ValueBindingError as error:\n"
            f"    {origin}.value_failure(error, {offset})"
        )[0]
        check = statements(f"{budget}.check('', ())")[0]
        check.value.args[0] = constant(plan.name)
        guard.body.append(check)
        for (field, child), value in zip(plan.fields, fields, strict=True):
            guard.body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id=self.types.validator(child), ctx=ast.Load()),
                        args=[value, ast.Name(id=budget, ctx=ast.Load()), constant((field,))],
                        keywords=[],
                    )
                )
            )
        if scalar_fields:
            fast = statements(
                "if not (type(value_limits) is ValueLimits and "
                f"value_limits.nodes >= {1 + len(plan.fields)} and value_limits.depth >= 1):\n"
                "    pass"
            )[0]
            fast.body = [guard]
            body.append(fast)
        else:
            body.append(guard)

    def inline_query(
        self, definition, arguments, body, name, depth, *, nested, virtual_record=False
    ):
        # Arguments have already been evaluated and checked in their original order.
        prepared = []
        for argument in arguments:
            if not isinstance(argument, (ast.Name, VirtualRecord)):
                local = f"_nomos_inline_argument_{self.count}"
                self.count += 1
                body.append(self.assign(local, argument))
                argument = ast.Name(id=local, ctx=ast.Load())
            prepared.append(argument)
        environment = {
            parameter: argument if isinstance(argument, VirtualRecord) else argument.id
            for (parameter, _), argument in zip(definition.parameters, prepared, strict=True)
        }
        previous = self.inline_operands
        self.inline_operands = True
        try:
            with self.proofs.call(environment.values()):
                value = self.emit(
                    definition.body,
                    body,
                    depth + 1,
                    environment=environment,
                    source=definition.source,
                    nested=nested,
                    roles={parameter: constant(False) for parameter in environment},
                    virtual_record=virtual_record,
                )
        finally:
            self.inline_operands = previous
        if virtual_record:
            return value
        body.append(self.assign(name, value))

    def match(self, node, body, name, subject, depth, *, environment, source, nested, roles):
        origin = self.source_name(source)
        cases = dict(node.children[0].value_type.cases)
        kind = name + "_case_type"
        dispatch = ast.Match(
            subject=ast.Call(func=ast.Name(id="type", ctx=ast.Load()), args=[subject], keywords=[]),
            cases=[],
        )
        for (tag, binder, _), branch in zip(node.operand, node.children[1:], strict=True):
            branch_body = []
            value = (
                self.branch(
                    lambda: self.emit(
                        branch,
                        branch_body,
                        depth + 1,
                        environment=environment,
                        source=source,
                        nested=nested,
                        roles=roles,
                    )
                )
                if binder is None
                else self.bound_expression(
                    branch,
                    binder,
                    subject.id,
                    branch_body,
                    depth,
                    environment=environment,
                    source=source,
                    nested=nested,
                    roles=roles,
                    validated=self.proofs.validated_argument(
                        node.children[0], node.children[0].value_type, environment
                    ),
                )
            )
            branch_body.append(self.assign(name, value))
            dispatch.cases.append(
                ast.match_case(
                    pattern=ast.MatchAs(pattern=None, name=kind),
                    guard=ast.Compare(
                        left=ast.Name(id=kind, ctx=ast.Load()),
                        ops=[ast.Is()],
                        comparators=[ast.Name(id=self.types.carrier(cases[tag]), ctx=ast.Load())],
                    ),
                    body=branch_body,
                )
            )
        dispatch.cases.append(
            ast.match_case(
                pattern=ast.MatchAs(pattern=None, name=None),
                guard=None,
                body=statements(
                    f"{origin}.fail('InvalidValue', {node.offset}, "
                    "'declared variant case', 'foreign carrier')"
                ),
            )
        )
        body.append(dispatch)
        return ast.Name(id=name, ctx=ast.Load())

    def latest_plan(self, node, environment, source):
        plan = plan_grouped_latest(node)
        if plan is not None and self.proofs.proven_subset(node, environment):
            self.note(
                "Passed",
                "grouped-latest",
                source,
                (node.offset,),
                "checked-strict-anti-dominance",
                "Generate a grouped version index with exact virtual scan costs; "
                "prepay index execution work; retain original order, ties, duplicates "
                "and resource diagnostics.",
            )
            return plan
        return None

    def iteration(self, node, body, name, pool, depth, *, environment, source, nested, roles):
        aggregate = plan_correlated_sum(node)
        argument_binding = object()
        argument_environment = {**environment, node.operand: argument_binding}
        if (
            aggregate is not None
            and all(
                self.proofs.validated_argument(value, value.value_type, environment)
                for value in (node.children[0], aggregate.rows)
            )
            and all(
                self.proofs.validated_argument(
                    value,
                    value.value_type,
                    argument_environment,
                    bindings=self.proofs.bindings | {argument_binding},
                )
                for value in aggregate.arguments
            )
        ):
            self.note(
                "Passed",
                "correlated-sum-index",
                source,
                (node.offset,),
                "checked-query-equality-correlated-integer-sum"
                if aggregate.query is not None
                else "checked-equality-correlated-integer-sum",
                "Group validated rows by nominal keys, preserve duplicate contributions "
                "and exact short-circuit scan costs; fold checked empty rows to zero "
                "with original fixed costs; prepay index execution work and retain "
                "cold resource diagnostics.",
            )
            return correlated_sum(
                self,
                node,
                aggregate,
                body,
                name,
                pool,
                depth,
                environment=environment,
                source=source,
                nested=nested,
                normal=lambda block: self.iteration_loop(
                    node,
                    block,
                    name,
                    pool,
                    depth,
                    environment=environment,
                    source=source,
                    nested=nested,
                    roles=roles,
                ),
            )
        plan = self.latest_plan(node, environment, source)
        if plan is not None:
            return grouped_latest(
                self,
                node,
                plan,
                body,
                name,
                pool,
                depth,
                source=source,
                nested=nested,
                normal=lambda block: self.iteration_loop(
                    node,
                    block,
                    name,
                    pool,
                    depth,
                    environment=environment,
                    source=source,
                    nested=nested,
                    roles=roles,
                ),
            )
        return self.iteration_loop(
            node,
            body,
            name,
            pool,
            depth,
            environment=environment,
            source=source,
            nested=nested,
            roles=roles,
        )

    def iteration_loop(self, node, body, name, pool, depth, *, environment, source, nested, roles):
        operation = node.operation
        origin = self.source_name(source)
        item = name + "_item"
        output = name + "_output"
        body.append(
            self.assign(
                output,
                constant(0)
                if operation in {"sum", "sum_by"}
                else ast.List(elts=[], ctx=ast.Load()),
            )
        )
        members = ordered_pool(node.children[0], pool, body, name)
        loop = ast.For(target=ast.Name(id=item, ctx=ast.Store()), iter=members, body=[], orelse=[])
        if operation == "sum":
            loop.body.extend(
                statements(
                    "_budget.steps += 1\n"
                    "if _budget.steps > _budget.limits.steps:\n"
                    f"    {origin}.fail('ExpressionBudget', {node.offset}, "
                    "'bounded sum', 'step limit')"
                )
            )
            value = ast.Name(id=item, ctx=ast.Load())
        else:
            value = self.bound_expression(
                node.children[1],
                node.operand,
                item,
                loop.body,
                depth,
                environment=environment,
                source=source,
                nested=nested,
                roles=roles,
                validated=self.proofs.validated_argument(
                    node.children[0], node.children[0].value_type, environment
                ),
            )
        if operation in {"sum", "sum_by"}:
            loop.body.append(
                ast.AugAssign(
                    target=ast.Name(id=output, ctx=ast.Store()), op=ast.Add(), value=value
                )
            )
        else:
            append = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id=output, ctx=ast.Load()), attr="append", ctx=ast.Load()
                    ),
                    args=[ast.Name(id=item, ctx=ast.Load()) if operation == "filter" else value],
                    keywords=[],
                )
            )
            loop.body.append(
                ast.If(test=value, body=[append], orelse=[]) if operation == "filter" else append
            )
        body.append(loop)
        if operation in {"sum", "sum_by"}:
            body.append(self.assign(name, ast.Name(id=output, ctx=ast.Load())))
        else:
            subset_proven = self.proofs.proven_subset(node, environment)
            if subset_proven:
                self.note(
                    "Passed",
                    "subset-validation",
                    source,
                    (node.offset,),
                    "checked-same-contract-subset",
                    "Skip the repeated structural traversal.",
                )
            if not subset_proven:
                body.extend(
                    statements(
                        f"if len({output}) > value_limits.items:\n"
                        f"    {origin}.fail('ExpressionBudget', {node.offset}, "
                        "'bounded collection', 'member limit')"
                    )
                )
            body.append(
                self.assign(
                    name,
                    ast.Call(
                        func=ast.Name(
                            id="frozenset" if node.value_type.kind == "set" else "tuple",
                            ctx=ast.Load(),
                        ),
                        args=[ast.Name(id=output, ctx=ast.Load())],
                        keywords=[],
                    ),
                )
            )
            if not subset_proven:
                self.validate_structure(node.value_type, name, node.offset, body, origin=origin)
        return ast.Name(id=name, ctx=ast.Load())

    def bound_expression(
        self,
        node,
        parameter,
        item,
        body,
        depth,
        *,
        environment,
        source,
        nested,
        roles,
        validated=False,
    ):
        local_roles = (
            {key: constant(key == self.checked.actor) for key in environment}
            if roles is None
            else dict(roles)
        )
        local_roles[parameter] = constant(False)
        with self.proofs.bound(item, validated=validated):
            return self.emit(
                node,
                body,
                depth + 1,
                environment={**environment, parameter: item},
                source=source,
                nested=nested,
                roles=local_roles,
            )

    def validate_structure(self, plan, name, offset, body, *, origin):
        body.extend(
            statements(
                f"try:\n    {self.types.shape(plan)}({name}, "
                f"ValueBudget(value_limits{', reads.references' if self.world else ''}), ())\n"
                "except ValueBindingError as error:\n"
                f"    {origin}.value_failure(error, {offset})"
            )
        )

    def own_role(self, path, roles):
        if path is None or path.steps:
            return constant(False)
        if roles is None:
            return constant(path.root == self.checked.actor)
        return roles.get(path.root, constant(False))

    def validate_result(
        self,
        plan,
        value,
        offset,
        body,
        *,
        expected="valid pure value",
        origin=None,
        reusable=False,
    ):
        origin = self.source_name(self.checked.source) if origin is None else origin
        budget = (
            "ValueBudget(value_limits, reads.references)"
            if self.world
            else "ValueBudget(value_limits)"
        )
        guard = statements(
            f"try:\n    {self.types.validator(plan)}(None, {budget}, ())\n"
            "except ValueBindingError as error:\n"
            f"    {origin}.value_failure(error, {offset}, '')"
        )[0]
        if reusable and self.world:
            guard.body[0].value = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="reads", ctx=ast.Load()), attr="checked_input", ctx=ast.Load()
                ),
                args=[
                    ast.Name(id=self.types.validator(plan), ctx=ast.Load()),
                    value,
                    ast.Name(id="value_limits", ctx=ast.Load()),
                ],
                keywords=[],
            )
        else:
            guard.body[0].value.args[0] = value
        guard.handlers[0].body[0].value.args[-1] = constant(expected)
        body.append(guard)

    def module(
        self, expressions=None, *, input_proofs=None, frame_queries=(), finalize_locations=True
    ):
        expressions = (("evaluate", self.checked),) if expressions is None else expressions
        input_proofs = {} if input_proofs is None else input_proofs
        roots = dict(expressions)
        if (
            not self.world
            and input_proofs
            or any(
                name not in roots or type(proof) is not ExpressionEntryProof
                for name, proof in input_proofs.items()
            )
        ):
            raise C0LawError("input proofs require private generated world expressions")
        proven_inputs = {
            name: proof.checked_names(roots[name]) for name, proof in input_proofs.items()
        }
        for _, checked in expressions:
            for _, spec in checked.inputs:
                self.types.add(checked.table[spec.type_name])
            self.types.add(checked.result)
            if checked.source not in self.sources:
                self.sources.append(checked.source)
            self.prepare(checked.node, checked.source)
        for name, plan in self.checked.table.definitions:
            if plan.type_id in self.types.plans:
                self.types.names[name] = plan.type_id
        body = statements('''
"""C0-generated expression and nominal values. Rule execution needs no compiler."""
from collections.abc import Mapping
from dataclasses import dataclass
from nomos_runtime.expressions import (
    ExpressionBudget, ExpressionError, ExpressionLimits, Source, SourceSpan,
    ValueBindingError, ValueBudget, ValueLimits, fail_value,
)
from nomos_runtime.ordering import ordered_members as _ordered_members
''')
        body.extend(self.types.emit(decoders=self.world))
        if self.world:
            body.extend(statements("from nomos_runtime.entities import ReadContext"))
        for source in self.sources:
            body.append(self.assign(self.source_name(source), self.emit_source(source)))
        body.append(self.assign("DEPENDENCIES", constant(tuple(self.definitions))))
        for definition in self.definitions.values():
            environment = {
                name: f"_argument_{index}" for index, (name, _) in enumerate(definition.parameters)
            }
            flattened = self.record_parameters.select(definition)
            arguments = []
            for index, (parameter, plan) in enumerate(definition.parameters):
                if index in flattened:
                    fields = tuple(
                        (field, ast.Name(id=f"_argument_{index}_field_{field}", ctx=ast.Load()))
                        for field in self.record_parameters.fields(definition, index)
                    )
                    environment[parameter] = VirtualRecord(fields)
                    arguments.extend(value.id for _, value in fields)
                else:
                    arguments.append(environment[parameter])
            self.proofs.reset(environment.values())
            self.plan_function(
                self.definition_name(definition),
                definition.body,
                environment,
                definition.source,
                mode="query",
                query=True,
            )
            function = statements("def _query(_budget, value_limits, _depth):\n    pass")[0]
            function.name = self.definition_name(definition)
            if self.world:
                function.args.args.extend([ast.arg(arg="reads"), ast.arg(arg="_roles")])
            function.args.args.extend(ast.arg(arg=name) for name in arguments)
            function.body = [*self.query_reuse.initializers(), *self.query_memo.initializers()]
            result = self.emit(
                definition.body,
                function.body,
                environment=environment,
                source=definition.source,
                nested=True,
                roles={
                    name: ast.parse(f"_roles[{index}]", mode="eval").body
                    for index, (name, _) in enumerate(definition.parameters)
                }
                if self.world
                else None,
            )
            function.body.append(ast.Return(value=result))
            if self.world and definition.name in frame_queries:
                from .frame_queries import share_query

                share_query(self, definition, function, arguments)
            body.append(function)
        for name, checked in expressions:
            self.checked = checked
            self.proofs.table = checked.table
            self.inputs = {key: f"_input_{index}" for index, (key, _) in enumerate(checked.inputs)}
            body.append(self.expression_function(name, checked, proven_inputs.get(name, ())))
        body.append(self.assign("PURE_QUERY_REUSE_PLANS", constant(tuple(self.query_plans))))
        body.extend(emit_constant_variant_tables(self))
        if self.grouped_latest_used:
            body.insert(
                1,
                ast.ImportFrom(
                    module="bisect",
                    names=[ast.alias(name="bisect_right", asname="_bisect_right")],
                    level=0,
                ),
            )
        function_sources = {
            self.definition_name(definition): definition.source
            for definition in self.definitions.values()
        }
        function_sources.update((name, checked.source) for name, checked in expressions)
        ModuleOptimizer(self.types, self.sources, function_sources, self.report).run(body)
        from .logical_work import meter_expression

        roots = {name for name, _ in expressions}
        for function in body:
            if isinstance(function, ast.FunctionDef) and function.name in roots:
                meter_expression(function)
        module = ast.Module(body=body, type_ignores=[])
        return ast.fix_missing_locations(module) if finalize_locations else module

    def expression_function(self, name, checked, proven_inputs=()):
        self.proofs.reset(self.inputs.values())
        self.plan_function(
            name,
            checked.node,
            self.inputs,
            checked.source,
            mode=checked.summary.context,
            actor=checked.actor,
        )
        origin = self.source_name(checked.source)
        function = statements(
            "def evaluate(values, *, "
            f"limits=ExpressionLimits({checked.limits.steps}, {checked.limits.depth}), "
            "value_limits=ValueLimits(), query_values=None, logical_work=None):\n    pass"
        )[0]
        function.name = name
        if self.world:
            function.args.args.append(ast.arg(arg="reads"))
        inputs_check = statements(
            "if not isinstance(values, Mapping) or set(values) != set(()):\n"
            f"    {origin}.fail('MissingBinding', 0, 'exact declared value inputs', "
            "'missing or extra input')"
        )[0]
        inputs_check.test.values[1].comparators[0].args[0] = constant(tuple(self.inputs))
        function.body = [inputs_check]
        budget = (
            "ValueBudget(value_limits, reads.references)"
            if self.world
            else "ValueBudget(value_limits)"
        )
        for name, spec in checked.inputs:
            plan = checked.table[spec.type_name]
            if name in proven_inputs:
                function.body.extend(statements(f"{self.inputs[name]} = values[{name!r}]"))
                self.note(
                    "Passed",
                    "expression-entry-input",
                    checked.source,
                    (checked.node.offset,),
                    "same-call-actor-binding",
                    f"Use caller-checked {name}: {plan.name}; retain context, controller, "
                    "result checks and all logical expression work.",
                )
                continue
            binding = statements(
                f"{self.inputs[name]} = {self.types.validator(plan)}(values[''], {budget}, ())"
            )[0]
            binding.value.args[0].slice = constant(name)
            if self.world and plan.kind in {"record", "variant", "optional", "set", "sequence"}:
                binding.value = ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="reads", ctx=ast.Load()),
                        attr="checked_input",
                        ctx=ast.Load(),
                    ),
                    args=[
                        ast.Name(id=self.types.validator(plan), ctx=ast.Load()),
                        ast.Subscript(
                            value=ast.Name(id="values", ctx=ast.Load()),
                            slice=constant(name),
                            ctx=ast.Load(),
                        ),
                        ast.Name(id="value_limits", ctx=ast.Load()),
                    ],
                    keywords=[],
                )
            function.body.append(binding)
        if self.world:
            function.body.extend(statements("_local_values = {}"))
            guard = statements(
                "if type(reads) is not ReadContext or reads.schema_id != '' or reads.mode != '':\n"
                f"    {origin}.fail('MissingBinding', 0, 'checked read context', 'wrong context')"
            )[0]
            guard.test.values[1].comparators[0] = constant(checked.entities.fingerprint)
            guard.test.values[2].comparators[0] = constant(checked.summary.context)
            function.body.insert(0, guard)
            if checked.actor is not None:
                actor_guard = statements(
                    "if reads.controller != values['']:\n"
                    f"    {origin}.fail('WrongController', 0, 'controlling Actor', 'wrong actor')"
                )[0]
                actor_guard.test.comparators[0].slice = constant(checked.actor)
                function.body.append(actor_guard)
        function.body.extend(
            statements("_budget = ExpressionBudget(limits)\n_budget.query_values = query_values")
        )
        function.body.extend(self.query_reuse.initializers())
        function.body.extend(self.query_memo.initializers())
        result = self.emit(checked.node, function.body)
        result_proven = self.proofs.validated_argument(checked.node, checked.result, self.inputs)
        if result_proven:
            self.note_branch_proof(checked.node, checked.source, checked.node.offset)
            self.note_validation_congruence(
                checked.node, checked.result, checked.source, checked.node.offset
            )
            self.note_collection_proof(checked.node, checked.source, checked.node.offset)
        if not result_proven and not self.scalar_result_proven(
            checked.node,
            checked.result,
            checked.source,
            checked.node.offset,
            function.body,
            environment=self.inputs,
        ):
            self.validate_result(
                checked.result,
                result,
                checked.node.offset,
                function.body,
                expected=checked.result.name,
            )
        function.body.append(ast.Return(value=result))
        return function

    def emit_source(self, source):
        span = source.span
        return ast.Call(
            func=ast.Name(id="Source", ctx=ast.Load()),
            args=[
                constant(source.text),
                constant(source.path),
                constant(None)
                if span is None
                else ast.Call(
                    func=ast.Name(id="SourceSpan", ctx=ast.Load()),
                    args=[
                        constant(getattr(span, field))
                        for field in (
                            "file",
                            "digest",
                            "path",
                            "line",
                            "column",
                            "end_line",
                            "end_column",
                        )
                    ],
                    keywords=[],
                ),
            ],
            keywords=[],
        )


def emit_expression_module(checked, *, report=None):
    """Return importable source for the supported slice; never fall back to evaluation."""
    if type(checked) is not CheckedValueExpression:
        raise C0LawError("Python generation needs an existing checked value expression")
    module = _Emitter(checked, report=report).module()
    compile(module, "<c0-generated-expression>", "exec")
    return ast.unparse(module) + "\n"
