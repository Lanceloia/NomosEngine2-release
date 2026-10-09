"""Bind author Event-sort claims to one selected causal and due K0 profile."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0SourceSpecKey,
)
from nomos_kernel._atomic_inmemory_session import _K0InMemoryOccurrence, _K0InMemoryProfile
from nomos_kernel._event_jump_abi import _K0DueFormation
from nomos_kernel._occurrence_formation_abi import _K0CausalFormation

from .author_contract_v1 import C0LawError
from .event_formation_binding_v2 import (
    EventFormationPlan,
    EventFormationPlanError,
    EventFormationPort,
    bind_event_formation_ports,
)
from .event_formation_ir_v2 import (
    EVENT_FORMATION_VERSION,
    EventFormationProgram,
    EventFormationRule,
    FormationMechanism,
    FormationTriggerKind,
)
from .nominal_types_v1 import EventSortRef, IRValidationError, SemanticIdentity


class C0FormationTraceError(ValueError):
    """Published K0 history disagrees with the checked formation plan."""


@dataclass(frozen=True, eq=False)
class C0FormationSessionScope:
    """An in-process comparison boundary, not a persistent world identity."""


@dataclass(frozen=True)
class C0FormationEntry:
    name: str
    source: K0SourceSpecKey
    event_type: K0EventTypeKey
    family: K0OccurrenceFamily
    causal_law: K0CausalLawKey | None = None
    trigger_entry: str | None = None


@dataclass(frozen=True)
class C0FormedEventView:
    scope: C0FormationSessionScope
    occurrence: K0OccurrenceRef
    event_sort: EventSortRef
    source: K0SourceSpecKey
    event_type: K0EventTypeKey
    mechanism: FormationMechanism
    causal_law: K0CausalLawKey | None
    predecessor: K0OccurrenceRef
    scheduled_at: int | None


def _exact_row(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise C0LawError(f"{label} has missing or unknown fields")
    return value


def compile_event_formations(
    raw: object,
    entries: tuple[C0FormationEntry, ...],
    profile: _K0InMemoryProfile,
) -> EventFormationPlan:
    return bind_event_formations(check_event_formations(raw), entries, profile)


def check_event_formations(raw: object) -> EventFormationProgram:
    """Check semantic declarations without any executable K0 profile."""
    row = _exact_row(raw, {"schema", "event_sorts", "formations"}, "ontology formation")
    if row["schema"] != EVENT_FORMATION_VERSION:
        raise C0LawError("ontology formation schema is unknown")
    sorts_raw, rules_raw = row["event_sorts"], row["formations"]
    if (
        type(sorts_raw) is not list
        or not 1 <= len(sorts_raw) <= 64
        or type(rules_raw) is not list
        or not 1 <= len(rules_raw) <= 64
    ):
        raise C0LawError("ontology formation declarations are not finite lists")
    sorts: dict[str, EventSortRef] = {}
    try:
        for item in sorts_raw:
            declaration = _exact_row(item, {"symbol", "identity"}, "Event sort")
            symbol = declaration["symbol"]
            if type(symbol) is not str or not symbol or symbol in sorts:
                raise C0LawError("Event sort symbol is malformed or repeated")
            sorts[symbol] = EventSortRef(SemanticIdentity(declaration["identity"]))
        if len(set(sorts.values())) != len(sorts):
            raise C0LawError("Event sort identity is repeated")
        rules = []
        for item in rules_raw:
            if type(item) is not dict:
                raise C0LawError("Event formation rule is malformed")
            kind = FormationTriggerKind(item.get("trigger_kind"))
            mechanism = FormationMechanism(item.get("mechanism"))
            keys = {"entry", "sort", "trigger", "trigger_kind", "mechanism"}
            if kind is FormationTriggerKind.EVENT:
                keys.add("trigger_sort")
            rule = _exact_row(item, keys, "Event formation rule")
            if rule["sort"] not in sorts or (
                kind is FormationTriggerKind.EVENT and rule["trigger_sort"] not in sorts
            ):
                raise C0LawError("Event formation names an undeclared sort")
            rules.append(
                EventFormationRule(
                    rule["entry"],
                    sorts[rule["sort"]],
                    rule["trigger"],
                    kind,
                    mechanism,
                    sorts[rule["trigger_sort"]] if kind is FormationTriggerKind.EVENT else None,
                )
            )
        semantic = EventFormationProgram(
            tuple(sorted(sorts.values())),
            tuple(sorted(rules, key=lambda rule: rule.result_entry)),
        )
    except C0LawError:
        raise
    except (IRValidationError, TypeError, ValueError, KeyError) as error:
        raise C0LawError("ontology Event formation declaration is invalid") from error
    return semantic


def bind_event_formations(
    semantic: EventFormationProgram,
    entries: tuple[C0FormationEntry, ...],
    profile: _K0InMemoryProfile,
) -> EventFormationPlan:
    """Prove the checked declaration against the actual registered profile."""
    if type(semantic) is not EventFormationProgram:
        raise C0LawError("ontology binding needs a checked Event formation program")

    by_name = {entry.name: entry for entry in entries}
    specs = {spec.key: spec for spec in profile.source_specs}
    laws = {law.key: law for law in profile.causal_laws}
    event_types: dict[K0EventTypeKey, set[K0SourceSpecKey]] = {}
    for spec in profile.source_specs:
        event_types.setdefault(spec.event_type, set()).add(spec.key)
    ports = []
    selected_laws: dict[K0SourceSpecKey, set[K0CausalLawKey]] = {}
    for rule in semantic.rules:
        result, trigger = by_name.get(rule.result_entry), by_name.get(rule.trigger_entry)
        if (
            result is None
            or trigger is None
            or result.family is not K0OccurrenceFamily.EVENT
            or result.trigger_entry != rule.trigger_entry
            or trigger.family.value != rule.trigger_kind.value
        ):
            raise C0LawError("ontology rule disagrees with the selected Source formation")
        result_spec, trigger_spec = specs.get(result.source), specs.get(trigger.source)
        if (
            result_spec is None
            or trigger_spec is None
            or result_spec.occurrence_family is not K0OccurrenceFamily.EVENT
            or result_spec.event_type != result.event_type
            or trigger_spec.event_type != trigger.event_type
            or len(result_spec.contribution_owners) != 1
        ):
            raise C0LawError("ontology rule cannot bind the final K0 source")
        if rule.mechanism is FormationMechanism.CAUSAL:
            law = laws.get(result.causal_law)
            if (
                result.causal_law is None
                or law is None
                or event_types[trigger.event_type] != {trigger.source}
                or result_spec.due_projector is not None
                or law.resulting_source != result.source
                or law.triggering_event_type != trigger.event_type
            ):
                raise C0LawError("ontology rule cannot bind the final K0 causal law")
            selected_laws.setdefault(result.source, set()).add(result.causal_law)
        else:
            schedulers = {
                spec.key
                for spec in profile.source_specs
                if result.source in spec.scheduled_due_sources
            }
            if (
                result.causal_law is not None
                or rule.trigger_kind is not FormationTriggerKind.ACTION
                or result_spec.due_projector is None
                or result.source not in trigger_spec.scheduled_due_sources
                or schedulers != {trigger.source}
                or profile.temporal_policy is None
                or result.source not in profile.temporal_policy.source_order
                or any(law.resulting_source == result.source for law in profile.causal_laws)
            ):
                raise C0LawError("ontology rule cannot bind the final K0 due scheduler")
        ports.append(
            EventFormationPort(
                rule.result_entry,
                result.source.value,
                result.event_type.value,
                result_spec.contribution_owners[0].value,
                rule.trigger_entry,
                trigger.source.value,
                trigger.event_type.value,
                None if result.causal_law is None else result.causal_law.value,
            )
        )
    for source in selected_laws:
        if selected_laws[source] != {
            law.key for law in profile.causal_laws if law.resulting_source == source
        }:
            raise C0LawError("ontology proof omits a formation edge for a selected source")
    try:
        return bind_event_formation_ports(semantic, tuple(ports))
    except EventFormationPlanError as error:
        raise C0LawError("Event formation port binding failed") from error


def project_formed_events(
    plan: EventFormationPlan,
    history: tuple[_K0InMemoryOccurrence, ...],
    scope: C0FormationSessionScope,
) -> tuple[C0FormedEventView, ...]:
    if (
        type(plan) is not EventFormationPlan
        or type(history) is not tuple
        or type(scope) is not C0FormationSessionScope
    ):
        raise C0FormationTraceError("formation audit needs one plan, history and Session scope")
    sources = {edge.port.result_source for edge in plan.edges}
    seen: dict[K0OccurrenceRef, _K0InMemoryOccurrence] = {}
    projected: set[K0OccurrenceRef] = set()
    result = []
    for record in history:
        if type(record) is not _K0InMemoryOccurrence or record.occurrence in seen:
            raise C0FormationTraceError("formation history has a foreign or repeated occurrence")
        if record.source.value in sources:
            basis = record.formation_basis
            predecessor_ref = (
                basis.predecessor
                if type(basis) is _K0CausalFormation
                else basis.key.formation
                if type(basis) is _K0DueFormation
                else None
            )
            predecessor = seen.get(predecessor_ref)
            matches = [
                edge
                for edge in plan.edges
                if edge.port.result_source == record.source.value
                and edge.port.result_event_type == record.classification.value
                and predecessor is not None
                and edge.port.trigger_source == predecessor.source.value
                and edge.port.trigger_event_type == predecessor.classification.value
                and predecessor.family.value == edge.trigger_kind.value
                and (
                    (
                        edge.mechanism is FormationMechanism.CAUSAL
                        and type(basis) is _K0CausalFormation
                        and edge.port.causal_law == basis.causal_law.value
                    )
                    or (
                        edge.mechanism is FormationMechanism.DUE
                        and type(basis) is _K0DueFormation
                        and edge.port.causal_law is None
                    )
                )
            ]
            if (
                record.family is not K0OccurrenceFamily.EVENT
                or len(matches) != 1
                or (
                    matches[0].trigger_kind is FormationTriggerKind.EVENT
                    and predecessor.occurrence not in projected
                )
            ):
                raise C0FormationTraceError("published Event violates the formation plan")
            result.append(
                C0FormedEventView(
                    scope,
                    record.occurrence,
                    matches[0].result_sort,
                    record.source,
                    record.classification,
                    matches[0].mechanism,
                    basis.causal_law if type(basis) is _K0CausalFormation else None,
                    predecessor_ref,
                    basis.scheduled_at.ordinal if type(basis) is _K0DueFormation else None,
                )
            )
            projected.add(record.occurrence)
        seen[record.occurrence] = record
    return tuple(result)
