"""Private generated execution for checked admission guards, never K0 configuration."""

from __future__ import annotations

import ast
from types import MappingProxyType

from . import composable_value_v1 as values
from ._execution_emission import FunctionEmission
from .expression_ir_v1 import C0Expression

# Match/second-match branches add at most three blocks beyond an emission boundary.
_MAX_STATIC_BLOCK_DEPTH = 12


def compile_invariant_admission(program):
    if program._tree["bindings"]:
        return program.admits
    nodes = []
    item_plans = {}
    emission = FunctionEmission()
    statements = emission.statements

    def emit(node, depth=0, context="context", env="env", block_depth=0):
        index = len(nodes)
        nodes.append(node)
        result = f"v{index}"
        current = f"nodes[{index}]"
        operation = node.operation
        operand = node.operand
        fallback = statements(f"{result} = values._eval({current}, {context}, {env}, ports)")
        if (
            type(node) is not C0Expression
            or node.stage != "admission"
            or depth >= 6
            or block_depth >= _MAX_STATIC_BLOCK_DEPTH
        ):
            return fallback, result

        def child_plan(child, extra_blocks=0):
            return emit(child, depth + 1, context, env, block_depth + extra_blocks)

        if operation == "const":
            body = statements(f"{result} = {current}.operand")
        elif operation == "ref":
            parts = node.reference_path
            body = statements(f"{result} = {context}[{parts[0]!r}]")
            if parts != ("occurrence",):
                body += statements(
                    f"if type({result}) is values._LazyValue:\n"
                    f"    {result} = {result}.resolve()\n"
                    f"annotation{index} = {env}[{parts[0]!r}]"
                )
                # Fuse forwarding only: getters and current layout/permission checks
                # keep the interpreter's order, including for native records.
                for part in parts[1:]:
                    body += statements(
                        f"if {result} is None:\n"
                        "    raise values.C0ValueStateError("
                        "'nullable value was used without its guard')\n"
                        f"if not isinstance(annotation{index}, type):\n"
                        f"    annotation{index} = values._nonnull(annotation{index}) "
                        f"or annotation{index}\n"
                        f"frozen{index} = values._frozen_record(annotation{index})\n"
                        f"if frozen{index}:\n"
                        f"    {result} = getattr({result}, {part!r})\n"
                        f"    if {part!r} not in ports.readable_fields.get("
                        f"annotation{index}, values._EMPTY_FIELDS):\n"
                        "        raise values.C0LawError("
                        "'record field is not a declared read port')\n"
                        f"    annotation{index} = values._resolved_fields("
                        f"annotation{index}).get({part!r})\n"
                        f"    if annotation{index} is None:\n"
                        "        raise values.C0LawError('record field has no resolved type')\n"
                        "else:\n"
                        f"    {result} = {result}[ports.tuple_fields[annotation{index}]"
                        f"[{part!r}]]\n"
                        f"    projection{index} = ports.tuple_fields.get(annotation{index})\n"
                        f"    if projection{index} is None or {part!r} not in projection{index}:\n"
                        "        raise values.C0LawError("
                        "'tuple field is not a declared projection')\n"
                        f"    annotation{index} = values.get_args(annotation{index})"
                        f"[projection{index}[{part!r}]]"
                    )
            body += statements(
                f"key{index} = ports.collection_keys.get({current}.operand)\n"
                f"if key{index} is not None:\n"
                f"    values._require_unique({result}, key{index}, "
                f"values._tuple_item({current}.result_type), ports)"
            )
        elif operation in ("eq", "le", "lt"):
            body, left = child_plan(operand[0])
            right_body, right = child_plan(operand[1])
            body += right_body
            expression = (
                f"type({left}) is type({right}) and {left} == {right}"
                if operation == "eq"
                else f"{left} {'<=' if operation == 'le' else '<'} {right}"
            )
            body += statements(f"{result} = {expression}")
        elif operation in ("not", "is_none", "not_none"):
            body, child = child_plan(operand)
            expression = (
                f"not {child}"
                if operation == "not"
                else f"{child} is {'not ' if operation == 'not_none' else ''}None"
            )
            body += statements(f"{result} = {expression}")
        elif operation in ("all", "any"):
            body = statements(f"{result} = {operation == 'all'}")
            for part in operand:
                child_body, child = child_plan(part, 1)
                child_body += statements(f"{result} = {child} is True")
                branch = ast.If(
                    test=ast.parse(
                        result if operation == "all" else f"not {result}", mode="eval"
                    ).body,
                    body=child_body,
                    orelse=[],
                )
                body.append(branch)
        elif operation == "if":
            body, condition = child_plan(operand["when"])
            then_body, then_result = child_plan(operand["then"], 1)
            else_body, else_result = child_plan(operand["else"], 1)
            body.append(
                ast.If(
                    test=ast.parse(f"{condition} is True", mode="eval").body,
                    body=then_body + statements(f"{result} = {then_result}"),
                    orelse=else_body + statements(f"{result} = {else_result}"),
                )
            )
        elif operation == "clause":
            body, child = child_plan(operand["test"])
            body += statements(f"{result} = {child}")
        elif operation in ("none_matching", "exists", "exactly_one", "count_matching"):
            collection_node = operand["collection"]
            try:
                item_plans[index] = (
                    collection_node.value_type,
                    values._tuple_item(collection_node.result_type),
                )
            except values.C0LawError:
                # Malformed private IR must fail when reached, not during speculation.
                item_plans[index] = None
            # Preserve the former helper-local expansion budget without helper calls.
            body, collection = emit(collection_node, 0, context, env, block_depth)
            if operation != "none_matching":
                body += statements(
                    f"if type({collection}) is not tuple or len({collection}) > values._MAX_INT:\n"
                    "    raise values.C0ValueStateError("
                    "'bounded quantifier needs an exact bounded tuple')"
                )
            initial = "0" if operation == "count_matching" else str(operation == "none_matching")
            body += statements(
                f"alias{index} = {current}.operand['as']\n"
                f"plan{index} = item_plans[{index}]\n"
                f"item_type{index} = (plan{index}[1] if plan{index} is not None and "
                f"{current}.operand['collection'].value_type is plan{index}[0] else "
                f"values._tuple_item({current}.operand['collection'].result_type))\n"
                f"{result} = {initial}"
            )
            local_context, local_env = f"context{index}", f"env{index}"
            # Each row owns its lexical dictionaries, including for nested/lazy fallback.
            loop_body = statements(
                f"{local_context} = {{**{context}, alias{index}: item{index}}}\n"
                f"{local_env} = {{**{env}, alias{index}: item_type{index}}}"
            )
            # Leave room for the loop's match branch and exactly_one's second-match branch.
            predicate_body, predicate = emit(
                operand["where"], 0, local_context, local_env, block_depth + 1
            )
            loop_body += predicate_body
            if operation == "count_matching":
                matched = statements(f"{result} += 1")
            elif operation == "exactly_one":
                matched = statements(
                    f"if {result}:\n    {result} = False\n    break\n{result} = True"
                )
            else:
                matched = statements(f"{result} = {operation == 'exists'}\nbreak")
            loop_body.append(
                ast.If(
                    test=ast.parse(f"{predicate} is True", mode="eval").body,
                    body=matched,
                    orelse=[],
                )
            )
            body.append(
                ast.For(
                    target=ast.Name(id=f"item{index}", ctx=ast.Store()),
                    iter=ast.Name(id=collection, ctx=ast.Load()),
                    body=loop_body,
                    orelse=[],
                )
            )
        else:
            # Other queries and bounded arithmetic keep their executor.
            return fallback, result
        return body, result

    expression = program.guard_ir.expression
    body, result = emit(expression)
    function = ast.parse("def execute(context, env, ports):\n    pass").body[0]
    function.body = body + statements(f"return {result}")
    module = ast.Module(body=[function], type_ignores=[])
    emission.namespace.update(
        {
            "values": values,
            "nodes": tuple(nodes),
            "item_plans": MappingProxyType(item_plans),
        }
    )
    # Only compiler-selected templates and numeric local names enter this AST.
    # Distinguish generated code objects in profilers; this is not a semantic identity.
    namespace = emission.compile(module, filename=f"<c0-invariant-execution:{id(program):x}>")
    execute = namespace["execute"]

    def admits(roots):
        ports = program._ports
        program._check_roots(roots, ports)
        try:
            return execute(roots, ports.roots, program._admission_ports) is True
        except (AttributeError, IndexError, KeyError, TypeError) as error:
            raise values.C0ValueStateError("compiled value met malformed current state") from error

    return admits
