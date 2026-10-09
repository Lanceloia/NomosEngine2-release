"""Trusted author diagnostics; never an admission decision or a player view."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from .composable_value_v1 import C0GuardFailure


@dataclass(frozen=True)
class C0AuthorGuardReport:
    entry: str
    source: str
    status: Literal[
        "false_predicates", "no_false_predicates", "basis_unavailable", "evaluation_fault"
    ]
    failures: tuple[C0GuardFailure, ...] = ()


def render_author_guard_report(report: C0AuthorGuardReport) -> tuple[str, ...]:
    """Render frozen evidence, without reading source files or guessing a root cause."""
    lines = [f"Author guard check {report.entry} by {report.source}: {report.status}"]
    if not report.failures:
        lines.append("No false predicate evidence; this does not establish K0 admission.")
        return tuple(lines)
    for failure in report.failures:
        if failure.alternatives:
            lines.append(
                "  Failed alternative: "
                + " -> ".join(
                    f"{alternative.path} (branch {alternative.index + 1})"
                    for alternative in failure.alternatives
                )
                + " (all alternatives failed; not independent errors)"
            )
        if failure.branches:
            lines.append("  Selected branch: " + " -> ".join(failure.branches))
        named = "/".join(failure.names)
        lines.append(f"  {named or failure.path} = false: {failure.expression}")
        if not failure.provenance:
            lines.append("    Source location unavailable.")
        for frame in failure.provenance:
            if frame.span is None:
                location = "location unavailable"
            else:
                span = frame.span
                location = f"{span.file}:{span.line}:{span.column} sha256={span.digest}"
            arguments = (
                " " + json.dumps(dict(frame.arguments), sort_keys=True, ensure_ascii=False)
                if frame.arguments
                else ""
            )
            lines.append(f"    {frame.kind} {frame.name}{arguments} @ {location} [{frame.path}]")
    return tuple(lines)
