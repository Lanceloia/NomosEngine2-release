"""Compiler mechanics do not become an extra runtime execution layer."""

import ast

import pytest

from nomos_c0._execution_emission import FunctionEmission


def test_bind_preserves_identity_without_comparing_or_deduplicating_values():
    class HostileEquality:
        def __eq__(self, other):
            pytest.fail("constant binding must not compare native objects")

    value = HostileEquality()
    emission = FunctionEmission({"constant_0": object(), "item_0": object()})
    first, second = emission.bind(value), emission.bind(value)
    assert first != second and first != "constant_0"
    assert emission.namespace[first] is value and emission.namespace[second] is value
    assert emission.fresh() != "item_0"


def test_emitted_function_uses_the_actual_namespace_and_late_invariant_binding():
    emission = FunctionEmission({"invariant": None})
    function = ast.parse("def execute(value):\n    return invariant(value)").body[0]
    namespace = emission.compile(ast.Module(body=[function], type_ignores=[]), filename="<probe>")
    execute = namespace["execute"]
    assert namespace is emission.namespace and execute.__globals__ is namespace
    namespace["invariant"] = lambda value: value + 1
    assert execute(3) == 4
    assert execute.__code__.co_filename == "<probe>"
    assert execute.__code__.co_names == ("invariant",)
    namespace["invariant"] = lambda value: value * 2
    assert execute(3) == 6


def test_emission_preserves_native_exception_and_does_not_run_callbacks_at_compile():
    calls = []

    def fail():
        calls.append("called")
        raise LookupError("native failure")

    emission = FunctionEmission({"callback": fail})
    namespace = emission.compile(
        ast.parse("def execute():\n    return callback()"), filename="<probe>"
    )
    assert calls == []
    with pytest.raises(LookupError, match="native failure"):
        namespace["execute"]()
    assert calls == ["called"]


@pytest.mark.parametrize("prefix", ["bad name", "a;pass", "1item", "\u4e2d"])
def test_generated_local_names_reject_non_identifier_templates(prefix):
    with pytest.raises(ValueError, match="ASCII identifier"):
        FunctionEmission().fresh(prefix)
