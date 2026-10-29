"""Version the generated world/runtime calling convention, independently of game rules."""

import ast

ARTIFACT_ABI = 1


def require_artifact_abi(source):
    versions = [
        node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "NOMOS_ARTIFACT_ABI"
            for target in node.targets
        )
    ]
    if (
        len(versions) != 1
        or not isinstance(versions[0], ast.Constant)
        or type(versions[0].value) is not int
        or versions[0].value != ARTIFACT_ABI
    ):
        raise ValueError(
            "generated artifact ABI is missing or incompatible; recompile author sources"
        )
