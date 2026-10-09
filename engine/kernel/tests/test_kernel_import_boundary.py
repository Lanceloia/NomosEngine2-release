"""K0 imports only itself, never the compiler or retired foundational packages.

A scan that matched nothing would pass forever, and a checker that never flagged anything would too,
so both directions are pinned: a floor on the number of scanned modules, synthetic violating imports
the checker must report - including a repository `tools/` import, the shape an earlier revision
missed - and a synthetic legal module it must accept.

Coverage limit, stated rather than implied: the closed set is the `nomos_*` namespace plus the
repository's own top-level packages, read from the checkout instead of hard-coded. A future project
layer package that is neither named `nomos_*` nor rooted at the repository top level must be added
to `FORBIDDEN_REPOSITORY_PACKAGES` for this guard to see it.

"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "engine" / "kernel" / "src" / "nomos_kernel"

ALLOWED_PROJECT_IMPORTS = frozenset({"nomos_kernel"})

# Rules 7 and 8 name `proofs/` and repository `tools/` whether or not those directories carry
# `__init__.py`; the layout is then read from the checkout so that a new repository package cannot
# become the silent hole `tools` was in the first revision of this guard.
FORBIDDEN_REPOSITORY_PACKAGES = frozenset(
    {"proofs", "tools"}
    | {
        child.name
        for child in ROOT.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    }
)

# The package holds 22 production modules at the time of writing. The floor only has to be low
# enough not to break on a rename and high enough that an empty scan cannot pass.
MINIMUM_SCANNED_MODULES = 20


def production_modules() -> list[Path]:
    return sorted(path for path in PACKAGE.rglob("*.py") if path.is_file())


def project_imports(source: str, filename: str) -> set[str]:
    """The repository modules one module's source imports, as written and dotted.

    Relative imports stay inside the importing package by definition and are skipped. For
    ``from X import name`` the recorded module is ``X``: a name can itself be a submodule, but its
    parent layer is what the dependency table assigns, and the parent is what this guard judges.
    """

    tree = ast.parse(source, filename=filename)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.add(node.module or "")
    return {name for name in names if name}


def violations(source: str, filename: str) -> set[str]:
    """The project imports the kernel layer may not make."""

    offenders: set[str] = set()
    for name in project_imports(source, filename):
        top = name.split(".")[0]
        if top in ALLOWED_PROJECT_IMPORTS:
            continue
        if top.startswith("nomos_") or top in FORBIDDEN_REPOSITORY_PACKAGES:
            offenders.add(name)
    return offenders


def test_the_scan_finds_the_kernel_production_modules() -> None:
    modules = production_modules()

    assert len(modules) >= MINIMUM_SCANNED_MODULES, len(modules)


def test_the_checker_reports_a_synthetic_violating_import() -> None:
    # Negative control: the same function the repository check uses must fail on a module that
    # really does reach another project layer or the repository tools, or its silence below would
    # mean nothing. The `tools` row is the shape an earlier revision reported as no violation.
    source = (
        "from nomos_mind import K0Profile\n"
        "import tools.ne2_twin_ledger\n"
        "from nomos_dawn import k0\n"
        "from nomos_ontology import ObjectSortRef\n"
        "from nomos_c0.nominal_types_v1 import ObjectSortRef\n"
    )

    assert violations(source, "<synthetic>") == {
        "nomos_mind",
        "tools.ne2_twin_ledger",
        "nomos_dawn",
        "nomos_ontology",
        "nomos_c0.nominal_types_v1",
    }


def test_the_checker_accepts_a_synthetic_legal_module() -> None:
    # Positive control: a checker that flagged every import would also pass the negative control.
    source = "from nomos_kernel._owner_abi import _K0Owner\nimport nomos_kernel\n"

    assert violations(source, "<synthetic>") == set()


def test_every_kernel_production_module_imports_only_kernel() -> None:
    offenders = {
        str(path.relative_to(ROOT)): sorted(violations(path.read_text(encoding="utf-8"), str(path)))
        for path in production_modules()
    }

    assert {name: found for name, found in offenders.items() if found} == {}
