"""Compiler-issued current metadata checks, not cached qualification results."""

import ast


class _ContractExecutionType(type):
    def __setattr__(cls, name, value):
        raise TypeError("compiled qualification checks are read-only")

    def __delattr__(cls, name):
        raise TypeError("compiled qualification checks are read-only")


def compile_contract_execution(dependencies, references):
    namespace = {}
    lines = ["def execute(read, sealed):", "    try:"]

    def bind(value):
        name = f"constant_{len(namespace)}"
        namespace[name] = value
        return name

    for dependency in dependencies:
        carrier = bind(dependency.carrier)
        lines.extend((f"        if not sealed({carrier}):", "            return False"))
        for name, expected in dependency.attributes:
            lines.extend(
                (
                    f"        if read({carrier}, {name!r}) is not {bind(expected)}:",
                    "            return False",
                )
            )
    for carrier, expected in references:
        lines.extend(
            (
                f"        if {bind(carrier)}.__post_init__ is not {bind(expected)}:",
                "            return False",
            )
        )
    lines.extend(
        (
            "        return True",
            "    except StopIteration as error:",
            "        raise RuntimeError('generator raised StopIteration') from error",
        )
    )
    # Only the checked generator's dependency graph is used to issue this code.
    module = ast.parse("\n".join(lines))
    exec(compile(module, "<c0-validation-contract>", "exec"), namespace)
    return _ContractExecutionType(
        "_ContractExecution",
        (),
        {"__module__": __name__, "execute": staticmethod(namespace["execute"])},
    )
