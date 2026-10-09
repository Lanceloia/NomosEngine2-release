"""Author-only CLI for one bounded T0 witness, not a player interface."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import yaml

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.composable_value_v1 import C0ValueRangeError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import _source
from nomos_c0.owner_graph_v1 import compile_owner_graph

from .witness_v0 import (
    T0Defer,
    T0Goal,
    T0LocalEquals,
    T0OfferExists,
    T0OfferSelector,
    T0OwnerFieldEquals,
    T0Report,
    T0Rule,
    T0ScheduledTurn,
    T0SeatPolicy,
    T0SelectOffer,
    T0SourcePublished,
    T0Witness,
    check_witness,
)


class T0CaseError(ValueError):
    """The author-side witness document has an unsupported shape."""


def _mapping(value: object, required: set[str], optional: set[str], name: str) -> dict:
    if type(value) is not dict or not required <= set(value) or set(value) - required - optional:
        raise T0CaseError(f"{name} needs exact declared fields")
    return value


def _selector(value: object) -> T0OfferSelector:
    row = _mapping(value, set(), {"entry", "label", "payload_fields", "ordinal"}, "offer selector")
    payload = row.get("payload_fields", {})
    if type(payload) is not dict:
        raise T0CaseError("selector payload_fields must be a mapping")
    return T0OfferSelector(
        row.get("entry"), row.get("label"), tuple(payload.items()), row.get("ordinal")
    )


def parse_case(value: object) -> tuple[T0Witness, T0Goal]:
    row = _mapping(
        value,
        {"schema", "max_steps", "schedule", "controllers", "goal"},
        {"external_inputs"},
        "T0 case",
    )
    if row["schema"] != "t0.case.v0":
        raise T0CaseError("T0 case schema is unknown")
    if type(row["schedule"]) is not list or type(row["controllers"]) is not dict:
        raise T0CaseError("T0 schedule and controllers need finite containers")
    schedule = []
    for turn in row["schedule"]:
        if type(turn) is str:
            schedule.append(T0ScheduledTurn("decide", turn))
        elif type(turn) is dict and set(turn) == {"continue"}:
            schedule.append(T0ScheduledTurn("continue", turn["continue"]))
        elif type(turn) is dict and set(turn) == {"advance"}:
            advance = _mapping(turn["advance"], {"seat", "to"}, set(), "advance")
            schedule.append(T0ScheduledTurn("advance", advance["seat"], advance["to"]))
        else:
            raise T0CaseError("T0 schedule turn is unknown")
    controllers = []
    for seat, rules in row["controllers"].items():
        if type(seat) is not str or type(rules) is not list:
            raise T0CaseError("T0 seat controller is malformed")
        compiled_rules = []
        for raw in rules:
            rule = _mapping(raw, set(), {"if_view", "if_offer", "select", "defer"}, "rule")
            if ("select" in rule) == ("defer" in rule):
                raise T0CaseError("rule needs exactly one select or defer")
            conditions = []
            if "if_view" in rule:
                if type(rule["if_view"]) is not dict:
                    raise T0CaseError("if_view must be a mapping")
                conditions.extend(
                    T0LocalEquals(path, expected) for path, expected in rule["if_view"].items()
                )
            if "if_offer" in rule:
                conditions.append(T0OfferExists(_selector(rule["if_offer"])))
            if "defer" in rule:
                if rule["defer"] is not True:
                    raise T0CaseError("defer must be true")
                choice = T0Defer()
            else:
                choice = T0SelectOffer(_selector(rule["select"]))
            compiled_rules.append(T0Rule(tuple(conditions), choice))
        controllers.append(T0SeatPolicy(seat, tuple(compiled_rules)))
    external = row.get("external_inputs", [])
    if type(external) is not list:
        raise T0CaseError("external_inputs must be a list")
    witness = T0Witness(tuple(schedule), tuple(controllers), row["max_steps"], tuple(external))

    goal_row = _mapping(row["goal"], {"all"}, set(), "goal")
    if type(goal_row["all"]) is not list:
        raise T0CaseError("goal all must be a finite list")
    clauses = []
    for clause in goal_row["all"]:
        if type(clause) is not dict or len(clause) != 1:
            raise T0CaseError("goal clause is malformed")
        if "source_published" in clause:
            clauses.append(T0SourcePublished(clause["source_published"]))
        elif "owner_field_eq" in clause:
            target = _mapping(
                clause["owner_field_eq"], {"owner", "path", "value"}, set(), "owner goal"
            )
            if type(target["path"]) is not list:
                raise T0CaseError("owner goal path must be a list")
            clauses.append(
                T0OwnerFieldEquals(target["owner"], tuple(target["path"]), target["value"])
            )
        else:
            raise T0CaseError("goal clause kind is unknown")
    return witness, T0Goal(tuple(clauses))


def _failure(reason: str, detail: str) -> T0Report:
    return T0Report("compile", reason, "unknown", 0, None, (), (), detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check one bounded author witness over C0/K0")
    for name in ("lib", "ports", "source", "assets", "case"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="print the complete structured report")
    args = parser.parse_args(argv)
    try:
        source_document = read_author_document(args.source)
        lib = read_author_document(args.lib)
        ports = read_author_document(args.ports)
        assets = read_author_document(args.assets).to_data()
        witness, goal = parse_case(read_author_document(args.case).to_data())
    except (OSError, ValueError, yaml.YAMLError) as error:
        report = _failure("input_rejected", str(error))
    else:
        try:
            source = _source(source_document)
            checked = check_nominal_lib(lib, source.get("actor_domains"))
            program = compile_owner_graph(check_graph_ports(ports, checked), source_document)
        except (C0LawError, C0BindingError, C0ValueRangeError) as error:
            report = _failure("compile_rejected", str(error))
        else:
            report = check_witness(program, assets, witness, goal)
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"{report.stage}: {report.stop_reason} | goal: {report.goal_status}")
        print(
            f"Control steps: {report.steps_completed}; "
            f"published occurrences: {len(report.published)}"
        )
        if report.requested_step is not None:
            print(f"Stopped at requested step {report.requested_step}.")
        if report.detail:
            print(report.detail)
        for item in report.published:
            print(f"  #{item.occurrence} {item.family}: {item.source}")
        for item in report.form_choices:
            print(f"  control at {item.time}: {item.seat} {item.choice}")
    if report.stop_reason in ("settlement_defect",):
        return 4
    if report.stage != "run" or report.stop_reason in (
        "unsupported_program",
        "unsupported_input",
        "unsupported_goal",
        "witness_invalid",
    ):
        return 2
    if report.goal_status == "met" and report.stop_reason in (
        "scheduled_end",
        "game_form_finished",
        "witness_stopped",
    ):
        return 0
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
