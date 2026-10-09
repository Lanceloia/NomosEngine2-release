"""Finite Actor-local scoring of already published seat offers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame, C0SourceContext
from .composable_action_v1 import C0ValueActionProgram
from .composable_value_v1 import (
    C0ValuePorts,
    C0ValueProgram,
    C0ValueRangeError,
    C0ValueStateError,
    _complete_value_fields,
    compile_value_program,
)
from .seat_offers_v0 import C0SeatOffer


@dataclass(frozen=True)
class C0AppraisalRule:
    entry: str
    mode: Literal["score", "ignore", "default"]
    value: C0ValueProgram | None


@dataclass(frozen=True)
class C0FiniteAppraisalProfile:
    name: str
    seat: str
    fallback_entry: str
    tie_order: tuple[str, ...]
    rules: tuple[C0AppraisalRule, ...]


@dataclass(frozen=True)
class C0AppraisalCandidate:
    offer: C0SeatOffer
    score: int | None


@dataclass(frozen=True)
class C0AppraisalProposal:
    time: int
    seat: str
    profile: str
    candidates: tuple[C0AppraisalCandidate, ...]
    chosen: C0SeatOffer


@dataclass(frozen=True)
class C0AppraisalRecord:
    proposal: C0AppraisalProposal
    outcome: str


def check_finite_appraisal_shape(
    raw: object,
    *,
    seat: str,
    entries: tuple[str, ...],
) -> tuple[str, str, list[str], list[dict]]:
    """Check complete Action coverage before any score expression is bound."""
    if type(raw) is not dict or set(raw) != {
        "name",
        "seat",
        "fallback_entry",
        "tie_order",
        "rules",
    }:
        raise C0LawError("appraisal profile has missing or unknown fields")
    name, selected, fallback, tie_order, rules = (
        raw["name"],
        raw["seat"],
        raw["fallback_entry"],
        raw["tie_order"],
        raw["rules"],
    )
    if (
        type(name) is not str
        or not name
        or selected != seat
        or type(fallback) is not str
        or fallback not in entries
        or type(tie_order) is not list
        or any(type(entry) is not str for entry in tie_order)
        or len(tie_order) != len(entries)
        or set(tie_order) != set(entries)
        or type(rules) is not list
        or len(rules) != len(entries)
    ):
        raise C0LawError("appraisal profile does not cover its exact seat")
    seen: set[str] = set()
    for item in rules:
        if type(item) is not dict or item.get("mode") not in ("score", "ignore", "default"):
            raise C0LawError("appraisal rule is malformed")
        mode = item["mode"]
        required = {"entry", "mode", "value"} if mode == "score" else {"entry", "mode"}
        entry = item.get("entry")
        if set(item) != required or type(entry) is not str or entry not in entries or entry in seen:
            raise C0LawError("appraisal rules must cover each Action exactly once")
        seen.add(entry)
        if entry == fallback and mode != "default":
            raise C0LawError("appraisal fallback Action must use default scoring")
    return name, fallback, tie_order, rules


def compile_finite_appraisal(
    raw: object,
    *,
    seat: str,
    actor_type: type,
    readable_paths: frozenset[str],
    entries: tuple[str, ...],
    actions: dict[str, C0ValueActionProgram],
    source_context: C0SourceContext | None = None,
    pure_definitions: tuple | None = None,
) -> C0FiniteAppraisalProfile:
    name, fallback, tie_order, rules = check_finite_appraisal_shape(raw, seat=seat, entries=entries)
    checked: list[C0AppraisalRule] = []
    for rule_index, item in enumerate(rules):
        entry, mode = item["entry"], item["mode"]
        value = None
        if mode == "score":
            context = None
            if source_context is not None:
                logical_path = f"rules[{rule_index}].value"
                span = source_context.locate(logical_path)
                context = C0SourceContext(
                    source_context.index,
                    (("outputs.score", source_context.indexed_path(logical_path)),)
                    if span is not None
                    else (),
                    (
                        *source_context.frames,
                        C0OriginFrame("appraisal_rule", entry, logical_path, span),
                    ),
                )
            action = actions[entry]
            payload_type = action.payload_type
            actor_fields = _complete_value_fields(actor_type)
            payload_fields = _complete_value_fields(payload_type)
            ports = C0ValuePorts(
                roots={"actor": actor_type, "payload": payload_type},
                readable_paths=readable_paths
                | frozenset(f"payload.{name}" for name in payload_type.__dataclass_fields__),
                admission_readable_paths=readable_paths
                | frozenset(f"payload.{name}" for name in payload_type.__dataclass_fields__),
                readable_fields={**actor_fields, **payload_fields},
                admission_readable_fields={**actor_fields, **payload_fields},
                writable_fields={},
                record_types={},
                tuple_fields={},
                admission_tuple_fields={},
                collection_keys={},
                outputs={"score": int},
                pure_definitions=pure_definitions
                if pure_definitions is not None
                else action.ports.value_ports.pure_definitions,
                source_context=context,
            )
            value = compile_value_program(
                json.dumps(
                    {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": {"const": True},
                        "outputs": {"score": item["value"]},
                    }
                ),
                ports,
                admission_outputs=frozenset({"score"}),
            )
        checked.append(C0AppraisalRule(entry, mode, value))
    return C0FiniteAppraisalProfile(name, seat, fallback, tuple(tie_order), tuple(checked))


def score_offers(
    profile: C0FiniteAppraisalProfile,
    offers: tuple[C0SeatOffer, ...],
    *,
    actor: object,
    payloads: tuple[object, ...],
    time: int,
) -> C0AppraisalProposal:
    if len(offers) != len(payloads):
        raise C0ValueStateError("appraisal candidates lack their current Action payloads")
    rules = {rule.entry: rule for rule in profile.rules}
    candidates: list[C0AppraisalCandidate] = []
    for offer, payload in zip(offers, payloads, strict=True):
        rule = rules[offer.entry]
        if rule.mode == "ignore":
            candidates.append(C0AppraisalCandidate(offer, None))
            continue
        if rule.mode == "default":
            score = 0
        else:
            assert rule.value is not None
            try:
                result = rule.value.evaluate_admission_outputs({"actor": actor, "payload": payload})
            except C0ValueRangeError as error:
                raise C0ValueStateError("appraisal score exceeded its integer range") from error
            if result is None:
                raise C0ValueStateError("appraisal score lost its total Actor-local basis")
            score = result["score"]
        candidates.append(C0AppraisalCandidate(offer, score))
    scored = tuple(item for item in candidates if item.score is not None)
    if not scored:
        raise C0ValueStateError("appraisal has no scored current offer")
    rank = {entry: index for index, entry in enumerate(profile.tie_order)}
    chosen = min(
        enumerate(scored),
        key=lambda pair: (-pair[1].score, rank[pair[1].offer.entry], pair[0]),
    )[1].offer
    return C0AppraisalProposal(time, profile.seat, profile.name, tuple(candidates), chosen)
