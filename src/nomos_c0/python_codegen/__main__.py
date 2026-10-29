"""Compile existing author documents to an inspectable Python world module."""

import argparse
from pathlib import Path

from nomos_c0.author_abilities.assembly import read_author_modules
from nomos_c0.author_abilities.cognition import compile_cognition
from nomos_c0.author_abilities.frontend import compile_author_world
from nomos_c0.author_abilities.scenario_planning import compile_opportunity_planning
from nomos_c0.author_abilities.strategies import compile_controllers
from nomos_c0.author_abilities.tabletop_presentation import compile_tabletop_presentation
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.optimization_report import OptimizationReport

from .world import emit_world_module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lib", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ai", type=Path)
    parser.add_argument("--cognition", type=Path)
    parser.add_argument("--presentation", type=Path)
    parser.add_argument(
        "--subject-planning",
        type=Path,
        help="select an atomic opportunity plan for Subject control",
    )
    parser.add_argument("--assets", type=Path, help="independent opening for a playable package")
    parser.add_argument("--playable", type=Path, help="export a new generated tabletop package")
    parser.add_argument(
        "--optimization-report", type=Path, help="write a Markdown compilation report"
    )
    arguments = parser.parse_args()
    if (arguments.assets is None) != (arguments.playable is None):
        parser.error("--playable and --assets must be supplied together")
    inputs = [
        p
        for p in (
            arguments.lib,
            arguments.source,
            arguments.ai,
            arguments.cognition,
            arguments.presentation,
            arguments.subject_planning,
            arguments.assets,
        )
        if p is not None
    ]
    outputs = [p for p in (arguments.output, arguments.optimization_report) if p is not None]

    def protect(paths):
        def same(left, right):
            return left.resolve() == right.resolve() or (
                left.exists() and right.exists() and left.samefile(right)
            )

        if any(same(output, source) for output in outputs for source in paths) or (
            len(outputs) == 2 and same(*outputs)
        ):
            parser.error("output paths must differ from author inputs and each other")

    protect(inputs)
    documents = {
        name: read_author_modules(path)
        for name, path in (
            ("lib", arguments.lib),
            ("source", arguments.source),
            ("ai", arguments.ai),
            ("cognition", arguments.cognition),
            ("presentation", arguments.presentation),
        )
        if path is not None
    }
    protect([Path(part.file) for document in documents.values() for part in document.parts])
    lib, source = documents["lib"], documents["source"]
    program = compile_author_world(
        lib.to_data(), source.to_data(), context=lib.context(), source_context=source.context()
    )
    cognition = None
    if "cognition" in documents:
        document = documents["cognition"]
        cognition = compile_cognition(program, document.to_data(), context=document.context())
    controllers = None
    if "ai" in documents:
        document = documents["ai"]
        controllers = compile_controllers(
            program, document.to_data(), context=document.context(), cognition=cognition
        )
    presentation = (
        None
        if "presentation" not in documents
        else compile_tabletop_presentation(program, documents["presentation"].to_data())
    )
    report = None if arguments.optimization_report is None else OptimizationReport()
    code = emit_world_module(
        program,
        controllers=controllers,
        cognition=cognition,
        presentation=presentation,
        report=report,
        planning=None
        if arguments.subject_planning is None
        else compile_opportunity_planning(
            program, read_author_document(arguments.subject_planning).to_data()
        ),
        subject_planning=arguments.subject_planning is not None,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(code, encoding="utf-8")
    if report is not None:
        arguments.optimization_report.parent.mkdir(parents=True, exist_ok=True)
        arguments.optimization_report.write_text(report.render(), encoding="utf-8")
    if arguments.playable is not None:
        from nomos_play.package import export_package

        export_package(arguments.output, arguments.assets, arguments.playable)
    print(arguments.output)


if __name__ == "__main__":
    main()
