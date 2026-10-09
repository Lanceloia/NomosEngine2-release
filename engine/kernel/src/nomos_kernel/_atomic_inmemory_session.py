"""Private atomic in-memory K0 session for bounded package-owned consumers."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from types import MappingProxyType, UnionType
from typing import Protocol, Union, get_args, get_origin, get_type_hints, runtime_checkable

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._action_value_abi import (
    _K0_MAX_ACTION_VALUE,
    _K0ActionCostProjector,
    _K0ActionOpportunity,
    _K0ActionValueDueBoundary,
    _K0ActionValueOpening,
    _K0ActionValuePolicy,
    _K0ActionValueProjection,
    _K0ActionValueRecord,
    _K0ActionValueSeat,
    _K0ActionValueState,
)
from nomos_kernel._admission_abi import (
    _admit_source,
    _K0AdmissionCapability,
    _K0RuntimePropositionState,
    _validate_admission_projection,
)
from nomos_kernel._candidate_owner_state_runtime import (
    _K0CandidateOwnerTopology,
    _K0OwnerStateCandidate,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition, _K0PlannedActivation
from nomos_kernel._coordinates import (
    _K0FixedTime,
    _K0OccurrenceCoordinate,
    _K0TemporalAdvanceRequest,
    _K0TemporalInterval,
)
from nomos_kernel._dynamic_actor_abi import (
    _K0ActorBinding,
    _K0ActorDomainPort,
    _K0ActorKind,
    _K0ActorOwnerPort,
    _K0ActorParticipantPort,
    _K0ActorProductSlot,
    _K0ActorRef,
    _K0FormationCandidate,
    _K0OpeningActor,
)
from nomos_kernel._dynamic_owner_abi import (
    _K0ClosedOwnerPort,
    _K0DynamicOwnerKind,
    _K0FixedDueIndividualPort,
    _K0IndividualBinding,
    _K0IndividualOwnerPort,
    _K0IndividualRef,
    _K0OpeningIndividual,
    _K0ReadObjectDomainPort,
    _K0SelectedOwner,
)
from nomos_kernel._event_jump_abi import (
    _K0AdvanceRecord,
    _K0DueFormation,
    _K0DueIndividualSelection,
    _K0DueProjector,
    _K0OrderedTemporalPolicy,
    _K0PendingDue,
    _K0PendingDueKey,
    _K0PeriodicDueKey,
    _K0PeriodicDueOpening,
)
from nomos_kernel._occurrence_formation_abi import _K0CausalFormation
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0ClosedParticipants,
    _K0CrossOwnerInvariant,
    _K0OccurrenceContribution,
    _K0OpeningStateValidator,
    _K0Owner,
    _K0OwnerView,
    _K0SameWaveEffectProofOwner,
    _K0SealedBinding,
    _K0SealedEvidence,
    _validate_closed_host_object,
)
from nomos_kernel._owner_state_runtime import (
    _build_candidate_owner_views,
    _clone_owner_state,
    _copy_closed_state,
    _K0OwnerStateDirectory,
)
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation, _validate_rule_result
from nomos_kernel._settlement_outcome_abi import (
    K0NotAdmitted,
    K0Published,
    K0SettlementDefect,
    _K0TemporalPublished,
    _K0TemporalRejected,
)
from nomos_kernel._state_image_abi import _K0OccurrenceCursor, _K0OwnerState
from nomos_kernel._terminal_settlement_abi import (
    _K0ClosedPeriodicPlan,
    _K0NotReachedDue,
    _K0SessionClosed,
    _K0TerminalPolicy,
    _K0TerminalState,
)

_IN_MEMORY_COORDINATE = _K0OccurrenceCoordinate(None, 0)


@dataclass(frozen=True)
class _K0PreDuePhase:
    interval: _K0TemporalInterval
    due_keys: tuple[object, ...]
    tape_before: int

    def __post_init__(self) -> None:
        if (
            type(self.interval) is not _K0TemporalInterval
            or type(self.due_keys) is not tuple
            or not self.due_keys
            or type(self.tape_before) is not int
            or self.tape_before < 0
        ):
            raise K0ProfileError("pre-due phase is malformed")


@dataclass(frozen=True)
class _K0InMemoryRuleInput:
    occurrence: K0OccurrenceRef
    source: K0SourceSpecKey
    evidence: _K0SealedEvidence
    participants: _K0ClosedParticipants
    bindings: tuple[_K0SealedBinding, ...]
    trigger: K0OccurrenceRef | None
    time: _K0FixedTime | None = None
    pending_due: _K0PendingDue | None = None

    def __post_init__(self) -> None:
        if (
            type(self.occurrence) is not K0OccurrenceRef
            or type(self.source) is not K0SourceSpecKey
            or not isinstance(self.evidence, _K0SealedEvidence)
            or not isinstance(self.participants, _K0ClosedParticipants)
            or type(self.bindings) is not tuple
            or any(not isinstance(item, _K0SealedBinding) for item in self.bindings)
            or (self.trigger is not None and type(self.trigger) is not K0OccurrenceRef)
            or (self.time is not None and type(self.time) is not _K0FixedTime)
            or (self.pending_due is not None and type(self.pending_due) is not _K0PendingDue)
        ):
            raise K0ProfileError("in-memory rule input is not closed")
        self.evidence.validate_for_k0()
        self.participants.validate_for_k0()
        for binding in self.bindings:
            binding.validate_for_k0()
        _validate_closed_host_object(self, "in-memory rule input")


@dataclass(frozen=True)
class _K0InMemoryEvaluation:
    """One occurrence's candidate effects and publication from the same sealed basis."""

    result: K0RuleResult
    envelope: object


@runtime_checkable
class _K0InMemoryRule(Protocol):
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation: ...


def _evaluate_source(
    spec: _K0InMemorySourceSpec, rule_input: _K0InMemoryRuleInput
) -> _K0InMemoryEvaluation:
    evaluation = spec.rule.evaluate(rule_input)
    if type(evaluation) is not _K0InMemoryEvaluation:
        raise K0ProfileError("in-memory rule returned no exact occurrence evaluation")
    if type(evaluation.result) is not K0RuleResult:
        raise K0ProfileError("in-memory evaluation has a malformed rule result")
    return evaluation


@dataclass(frozen=True)
class _K0InMemorySourceSpec:
    key: K0SourceSpecKey
    occurrence_family: K0OccurrenceFamily
    event_type: K0EventTypeKey
    payload_type: type[object]
    evidence_type: type[object]
    participants_type: type[object]
    read_owners: tuple[K0OwnerKey, ...]
    contribution_owners: tuple[K0OwnerKey, ...]
    binding_keys: tuple[str, ...]
    binding_types: tuple[type[object], ...]
    admission_capability: _K0AdmissionCapability | None
    rule: _K0InMemoryRule
    envelope_type: type[object]
    scheduled_due_sources: tuple[K0SourceSpecKey, ...] = ()
    due_projector: _K0DueProjector | None = None
    participant_ports: tuple[
        _K0IndividualOwnerPort | _K0ClosedOwnerPort | _K0ActorParticipantPort, ...
    ] = ()
    form_owner_family: str | None = None
    action_value_owner: K0OwnerKey | None = None
    action_cost_projector: _K0ActionCostProjector | None = None
    due_fixed_individual_ports: tuple[_K0FixedDueIndividualPort, ...] = ()
    actor_self: _K0ActorOwnerPort | None = None
    actor_product: _K0ActorProductSlot | None = None
    actor_domains: tuple[_K0ActorDomainPort, ...] = ()
    # Domain projectors seal object_views; participants/envelopes retain objects pairs.
    read_object_domains: tuple[_K0ReadObjectDomainPort, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.key) is not K0SourceSpecKey
            or type(self.occurrence_family) is not K0OccurrenceFamily
            or type(self.event_type) is not K0EventTypeKey
            or not isinstance(self.payload_type, type)
            or not isinstance(self.evidence_type, type)
            or not isinstance(self.participants_type, type)
            or type(self.read_owners) is not tuple
            or not self.read_owners
            or len(set(self.read_owners)) != len(self.read_owners)
            or type(self.contribution_owners) is not tuple
            or len(set(self.contribution_owners)) != len(self.contribution_owners)
            or type(self.binding_keys) is not tuple
            or type(self.binding_types) is not tuple
            or len(self.binding_keys) != len(self.binding_types)
            or not isinstance(self.rule, _K0InMemoryRule)
            or type(self.rule.capability_ref) is not _K0CapabilityRef
            or not isinstance(self.envelope_type, type)
            or type(self.scheduled_due_sources) is not tuple
            or any(type(key) is not K0SourceSpecKey for key in self.scheduled_due_sources)
            or len(set(self.scheduled_due_sources)) != len(self.scheduled_due_sources)
            or type(self.participant_ports) is not tuple
            or any(
                type(port)
                not in (_K0IndividualOwnerPort, _K0ClosedOwnerPort, _K0ActorParticipantPort)
                for port in self.participant_ports
            )
            or type(self.due_fixed_individual_ports) is not tuple
            or any(
                type(port) is not _K0FixedDueIndividualPort
                for port in self.due_fixed_individual_ports
            )
            or len({port.name for port in self.due_fixed_individual_ports})
            != len(self.due_fixed_individual_ports)
            or len({port.family for port in self.due_fixed_individual_ports})
            != len(self.due_fixed_individual_ports)
            or (
                self.form_owner_family is not None
                and (type(self.form_owner_family) is not str or not self.form_owner_family)
            )
            or (self.action_value_owner is None and self.actor_self is None)
            != (self.action_cost_projector is None)
            or (self.actor_self is not None and type(self.actor_self) is not _K0ActorOwnerPort)
            or (
                self.actor_product is not None
                and type(self.actor_product) is not _K0ActorProductSlot
            )
            or (self.actor_self is not None and self.action_value_owner is not None)
            or type(self.actor_domains) is not tuple
            or any(type(port) is not _K0ActorDomainPort for port in self.actor_domains)
            or type(self.read_object_domains) is not tuple
            or any(type(port) is not _K0ReadObjectDomainPort for port in self.read_object_domains)
            or (
                self.action_value_owner is not None
                and type(self.action_value_owner) is not K0OwnerKey
            )
            or (
                self.action_cost_projector is not None
                and (
                    not isinstance(self.action_cost_projector, _K0ActionCostProjector)
                    or type(self.action_cost_projector.capability_ref) is not _K0CapabilityRef
                )
            )
        ):
            raise K0ProfileError("in-memory source spec is not closed")
        names = tuple(port.name for port in self.participant_ports)
        fields = tuple(port.payload_field for port in self.participant_ports)
        if names != tuple(sorted(set(names))) or len(set(fields)) != len(fields):
            raise K0ProfileError("participant ports require unique canonical names and fields")
        for port in self.participant_ports:
            port.__post_init__()
            try:
                field_type = get_type_hints(self.payload_type).get(port.payload_field)
            except (NameError, TypeError) as error:
                raise K0ProfileError("participant payload type is malformed") from error
            expected = (
                _K0IndividualRef
                if type(port) is _K0IndividualOwnerPort
                else _K0ActorRef
                if type(port) is _K0ActorParticipantPort
                else str
            )
            if type(port) is _K0ClosedOwnerPort and port.nullable:
                arguments = get_args(field_type)
                exact_type = (
                    any(get_origin(field_type) is origin for origin in (UnionType, Union))
                    and len(arguments) == 2
                    and any(argument is str for argument in arguments)
                    and any(argument is type(None) for argument in arguments)
                )
            else:
                exact_type = field_type is expected
            if not exact_type:
                raise K0ProfileError("participant payload field has the wrong exact type")
        if self.occurrence_family is K0OccurrenceFamily.ACTION:
            if not isinstance(self.admission_capability, _K0AdmissionCapability):
                raise K0ProfileError("in-memory Action spec lost its admission capability")
            if self.due_projector is not None:
                raise K0ProfileError("Action source cannot project a temporal due")
            if self.due_fixed_individual_ports:
                raise K0ProfileError("Action source cannot bind a fixed due individual")
        elif self.admission_capability is not None:
            raise K0ProfileError("in-memory Event spec must not declare admission")
        elif self.participant_ports:
            raise K0ProfileError("participant ports currently require an Action source")
        elif self.scheduled_due_sources:
            raise K0ProfileError("Event source cannot directly schedule a temporal due")
        elif self.due_projector is not None and (
            not isinstance(self.due_projector, _K0DueProjector)
            or type(self.due_projector.capability_ref) is not _K0CapabilityRef
        ):
            raise K0ProfileError("temporal due source has no closed projector")
        if self.due_fixed_individual_ports and self.due_projector is None:
            raise K0ProfileError("fixed due individual needs a temporal source")
        if self.read_object_domains:
            if self.due_projector is None:
                raise K0ProfileError("read Object domain requires a temporal due source")
            for port in self.read_object_domains:
                port.__post_init__()
            if (
                len({port.name for port in self.read_object_domains})
                != len(self.read_object_domains)
                or len({port.family for port in self.read_object_domains})
                != len(self.read_object_domains)
                or {port.name for port in self.read_object_domains}
                & {
                    "scene",
                    "due",
                    "time",
                    *names,
                    *(port.name for port in self.due_fixed_individual_ports),
                    *(port.name for port in self.actor_domains),
                }
            ):
                raise K0ProfileError("read Object domains alias a selected root or family")
        if self.form_owner_family is not None and self.due_projector is not None:
            raise K0ProfileError("temporal source cannot declare Object formation")
        if (
            self.occurrence_family is K0OccurrenceFamily.EVENT
            and self.action_value_owner is not None
        ):
            raise K0ProfileError("Event source cannot consume an action-value opportunity")
        if self.action_cost_projector is not None:
            _validate_closed_host_object(self.action_cost_projector, "action-value cost projector")
        if self.actor_self is not None:
            self.actor_self.__post_init__()
            if (
                self.occurrence_family is not K0OccurrenceFamily.ACTION
                or get_type_hints(self.payload_type).get(self.actor_self.payload_field)
                is not _K0ActorRef
            ):
                raise K0ProfileError("Actor self requires an Action and exact Actor ref payload")
        if self.actor_product is not None:
            self.actor_product.__post_init__()
        domain_families = []
        for port in self.actor_domains:
            port.__post_init__()
            domain_families.extend(port.families)
        if (
            len(set(domain_families)) != len(domain_families)
            or len({port.name for port in self.actor_domains}) != len(self.actor_domains)
            or {port.name for port in self.actor_domains} & {"actor", *names}
            or (self.actor_self is not None and self.actor_self.family in domain_families)
            or any(
                port.family in domain_families
                for port in self.participant_ports
                if type(port) is _K0ActorParticipantPort
            )
        ):
            raise K0ProfileError("Actor domain/self ports alias")


@dataclass(frozen=True)
class _K0InMemoryActionBasis:
    source: K0SourceSpecKey

    def __post_init__(self) -> None:
        if type(self.source) is not K0SourceSpecKey:
            raise K0ProfileError("in-memory Action basis has no exact source")


@dataclass(frozen=True)
class _K0InMemoryActionAttempt:
    source: K0SourceSpecKey
    payload: object

    def __post_init__(self) -> None:
        if type(self.source) is not K0SourceSpecKey:
            raise K0ProfileError("in-memory Action attempt has no exact source")


@dataclass(frozen=True)
class _K0InMemoryOccurrence:
    occurrence: K0OccurrenceRef
    family: K0OccurrenceFamily
    source: K0SourceSpecKey
    classification: K0EventTypeKey
    formation_basis: object
    participants: _K0ClosedParticipants
    coordinate: _K0OccurrenceCoordinate
    semantic_envelope: object
    selected_owners: tuple[_K0SelectedOwner, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.occurrence) is not K0OccurrenceRef
            or type(self.family) is not K0OccurrenceFamily
            or type(self.source) is not K0SourceSpecKey
            or type(self.classification) is not K0EventTypeKey
            or not isinstance(self.participants, _K0ClosedParticipants)
            or type(self.coordinate) is not _K0OccurrenceCoordinate
        ):
            raise K0ProfileError("in-memory occurrence is not closed")
        self.participants.validate_for_k0()
        if self.semantic_envelope is None:
            raise K0ProfileError("in-memory occurrence has no semantic envelope")
        validate = getattr(self.semantic_envelope, "validate_for_k0", None)
        if not callable(validate):
            raise K0ProfileError("in-memory envelope has no exact K0 validation")
        validate()
        _validate_closed_host_object(self.semantic_envelope, "in-memory envelope")
        if type(self.selected_owners) is not tuple or any(
            type(item) is not _K0SelectedOwner for item in self.selected_owners
        ):
            raise K0ProfileError("occurrence selected owners are malformed")
        for item in self.selected_owners:
            item.__post_init__()
        names = tuple(item.name for item in self.selected_owners)
        if names != tuple(sorted(set(names))) or len(
            {item.owner for item in self.selected_owners}
        ) != len(self.selected_owners):
            raise K0ProfileError("occurrence selected owners are not canonical")


@dataclass(frozen=True)
class _K0SameWaveProposal:
    source: K0SourceSpecKey
    rule_input: _K0InMemoryRuleInput
    result: K0RuleResult


@runtime_checkable
class _K0SameWavePolicy(Protocol):
    capability_ref: _K0CapabilityRef
    owner: K0OwnerKey
    sources: tuple[K0SourceSpecKey, ...]
    law_keys: tuple[K0CausalLawKey, ...]
    trigger_source: K0SourceSpecKey
    trigger_event: K0EventTypeKey

    def merge(self, prior_state: object, proposals: tuple[_K0SameWaveProposal, ...]) -> object: ...


@dataclass(frozen=True)
class _K0OrderedStep:
    law_key: K0CausalLawKey
    source: K0SourceSpecKey
    required: bool


@runtime_checkable
class _K0OrderedPolicy(Protocol):
    capability_ref: _K0CapabilityRef
    owner: K0OwnerKey
    trigger_source: K0SourceSpecKey
    trigger_event: K0EventTypeKey
    steps: tuple[_K0OrderedStep, ...]

    def validate_current_basis(
        self,
        step: _K0OrderedStep,
        activation: _K0Activation,
        views: tuple[_K0OwnerView, ...],
    ) -> None: ...


@dataclass(frozen=True)
class _K0OrderedFormation:
    trigger: K0OccurrenceRef
    previous_completed: K0OccurrenceRef | None
    law: K0CausalLawKey
    policy: _K0CapabilityRef
    ordinal: int

    def __post_init__(self) -> None:
        if (
            type(self.trigger) is not K0OccurrenceRef
            or (
                self.previous_completed is not None
                and type(self.previous_completed) is not K0OccurrenceRef
            )
            or type(self.law) is not K0CausalLawKey
            or type(self.policy) is not _K0CapabilityRef
            or type(self.ordinal) is not int
            or self.ordinal not in (1, 2)
        ):
            raise K0ProfileError("ordered Event formation is malformed")


@dataclass(frozen=True)
class _K0InMemoryProfile:
    owners: tuple[_K0Owner, ...]
    source_specs: tuple[_K0InMemorySourceSpec, ...]
    causal_laws: tuple[K0CausalLawDefinition, ...]
    max_events: int
    max_waves: int
    same_wave_policy: _K0SameWavePolicy | None = None
    ordered_policy: _K0OrderedPolicy | None = None
    temporal_policy: _K0OrderedTemporalPolicy | None = None
    dynamic_owner_kinds: tuple[_K0DynamicOwnerKind, ...] = ()
    action_value_policy: _K0ActionValuePolicy | None = None
    terminal_policy: _K0TerminalPolicy | None = None
    actor_kinds: tuple[_K0ActorKind, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.owners) is not tuple
            or not self.owners
            or any(not isinstance(owner, _K0Owner) for owner in self.owners)
            or type(self.source_specs) is not tuple
            or not self.source_specs
            or any(type(spec) is not _K0InMemorySourceSpec for spec in self.source_specs)
            or type(self.causal_laws) is not tuple
            or any(type(law) is not K0CausalLawDefinition for law in self.causal_laws)
            or type(self.max_events) is not int
            or self.max_events < 1
            or type(self.max_waves) is not int
            or self.max_waves < 0
            or (
                self.terminal_policy is not None
                and type(self.terminal_policy) is not _K0TerminalPolicy
            )
            or type(self.dynamic_owner_kinds) is not tuple
            or any(type(kind) is not _K0DynamicOwnerKind for kind in self.dynamic_owner_kinds)
            or type(self.actor_kinds) is not tuple
            or any(type(kind) is not _K0ActorKind for kind in self.actor_kinds)
            or (
                self.action_value_policy is not None
                and type(self.action_value_policy) is not _K0ActionValuePolicy
            )
            or (
                self.temporal_policy is not None
                and type(self.temporal_policy) is not _K0OrderedTemporalPolicy
            )
            or (
                self.same_wave_policy is not None
                and (
                    not isinstance(self.same_wave_policy, _K0SameWavePolicy)
                    or type(self.same_wave_policy.capability_ref) is not _K0CapabilityRef
                    or type(self.same_wave_policy.owner) is not K0OwnerKey
                    or type(self.same_wave_policy.sources) is not tuple
                    or len(self.same_wave_policy.sources) != 2
                    or any(
                        type(source) is not K0SourceSpecKey
                        for source in self.same_wave_policy.sources
                    )
                    or len(set(self.same_wave_policy.sources)) != 2
                    or type(self.same_wave_policy.law_keys) is not tuple
                    or len(self.same_wave_policy.law_keys) != 2
                    or any(
                        type(key) is not K0CausalLawKey for key in self.same_wave_policy.law_keys
                    )
                    or type(self.same_wave_policy.trigger_source) is not K0SourceSpecKey
                    or type(self.same_wave_policy.trigger_event) is not K0EventTypeKey
                )
            )
            or (
                self.ordered_policy is not None
                and (
                    self.same_wave_policy is not None
                    or not isinstance(self.ordered_policy, _K0OrderedPolicy)
                    or type(self.ordered_policy.capability_ref) is not _K0CapabilityRef
                    or type(self.ordered_policy.owner) is not K0OwnerKey
                    or type(self.ordered_policy.trigger_source) is not K0SourceSpecKey
                    or type(self.ordered_policy.trigger_event) is not K0EventTypeKey
                    or type(self.ordered_policy.steps) is not tuple
                    or len(self.ordered_policy.steps) != 2
                    or any(
                        type(step) is not _K0OrderedStep
                        or type(step.law_key) is not K0CausalLawKey
                        or type(step.source) is not K0SourceSpecKey
                        or type(step.required) is not bool
                        for step in self.ordered_policy.steps
                    )
                    or len({step.law_key for step in self.ordered_policy.steps}) != 2
                    or len({step.source for step in self.ordered_policy.steps}) != 2
                )
            )
        ):
            raise K0ProfileError("in-memory profile is not closed")
        owner_keys = tuple(owner.key for owner in self.owners)
        if self.terminal_policy is not None:
            self.terminal_policy.__post_init__()
            if any(
                not set(clause.read_owners) <= set(owner_keys)
                for clause in self.terminal_policy.clauses
            ):
                raise K0ProfileError("terminal policy reads an undeclared owner")
        families = tuple(kind.family for kind in self.dynamic_owner_kinds)
        if len(set(families)) != len(families):
            raise K0ProfileError("dynamic owner families must be unique")
        for kind in self.dynamic_owner_kinds:
            kind.__post_init__()
            _validate_closed_host_object(kind.factory, "dynamic owner factory")
        actor_families = tuple(kind.family for kind in self.actor_kinds)
        if len(set(actor_families)) != len(actor_families) or set(actor_families) & set(families):
            raise K0ProfileError("Actor and Object kind families must be disjoint and unique")
        for kind in self.actor_kinds:
            kind.__post_init__()
            _validate_closed_host_object(kind.factory, "Actor owner factory")
            _validate_closed_host_object(kind.projector, "Actor tempo projector")
        if any(type(key) is not K0OwnerKey for key in owner_keys):
            raise K0ProfileError("in-memory profile owner keys are not exact")
        law_keys = tuple(law.key for law in self.causal_laws)
        event_types = tuple(spec.event_type for spec in self.source_specs)
        if (
            len(set(owner_keys)) != len(owner_keys)
            or len({spec.key for spec in self.source_specs}) != len(self.source_specs)
            or len(set(law_keys)) != len(law_keys)
        ):
            raise K0ProfileError("in-memory profile keys are not unique")
        for spec in self.source_specs:
            if not set(spec.read_owners).issubset(owner_keys) or not set(
                spec.contribution_owners
            ).issubset(owner_keys):
                raise K0ProfileError("in-memory source owner membership is not declared")
            for port in spec.participant_ports:
                if type(port) is _K0ActorParticipantPort and port.family not in actor_families:
                    raise K0ProfileError("Actor participant has no selected kind")
                if type(port) is _K0IndividualOwnerPort and not set(port.families) <= set(families):
                    raise K0ProfileError("individual owner port has no declared family")
                if type(port) is _K0ClosedOwnerPort and not {
                    owner for _, owner in port.members
                } <= set(owner_keys):
                    raise K0ProfileError("closed owner port names an undeclared owner")
            if any(port.family not in families for port in spec.due_fixed_individual_ports):
                raise K0ProfileError("fixed due individual has no declared family")
            if spec.form_owner_family is not None and spec.form_owner_family not in families:
                raise K0ProfileError("owner formation has no declared family")
            if spec.actor_product is not None and spec.actor_product.family not in actor_families:
                raise K0ProfileError("Actor product has no selected kind")
            if spec.actor_self is not None and spec.actor_self.family not in actor_families:
                raise K0ProfileError("Actor self has no selected kind")
            if any(not set(port.families) <= set(actor_families) for port in spec.actor_domains):
                raise K0ProfileError("Actor domain names an unselected kind")
            if any(port.family not in families for port in spec.read_object_domains):
                raise K0ProfileError("read Object domain names an unselected kind")
        events = {
            spec.key: spec
            for spec in self.source_specs
            if spec.occurrence_family is K0OccurrenceFamily.EVENT
        }
        if self.temporal_policy is not None:
            temporal_sources = {
                source for source, spec in events.items() if spec.due_projector is not None
            }
            if set(self.temporal_policy.source_order) != temporal_sources:
                raise K0ProfileError("ordered temporal policy does not cover exact due sources")
            actions = {
                spec.key
                for spec in self.source_specs
                if spec.occurrence_family is K0OccurrenceFamily.ACTION
            }
            if not set(self.temporal_policy.pre_due_action_sources) <= actions:
                raise K0ProfileError("pre-due policy names a non-Action source")
            periodic_sources = {plan.source for plan in self.temporal_policy.periodic_plans}
            scheduled_sources = {
                source for spec in self.source_specs for source in spec.scheduled_due_sources
            }
            if not periodic_sources <= temporal_sources or periodic_sources & scheduled_sources:
                raise K0ProfileError("periodic due source is not exclusively plan-formed")
        if self.action_value_policy is not None:
            action_value = self.action_value_policy
            action_value.__post_init__()
            for seat in action_value.seats:
                _validate_closed_host_object(seat.projector, "action-value seat projector")
                if self.actor_kinds and seat.seat.startswith("actor."):
                    raise K0ProfileError("static seat uses the reserved Actor instance namespace")
            if self.temporal_policy is None:
                raise K0ProfileError("action-value policy needs a selected temporal policy")
            selected_sources = tuple(
                source for seat in action_value.seats for source in seat.action_sources
            ) + tuple(source for kind in self.actor_kinds for source in kind.action_sources)
            if (
                len(set(selected_sources)) != len(selected_sources)
                or not {seat.owner for seat in action_value.seats} <= set(owner_keys)
                or set(self.temporal_policy.pre_due_action_sources) != set(selected_sources)
            ):
                raise K0ProfileError("action-value policy is not bound to exact temporal ports")
            specs = {spec.key: spec for spec in self.source_specs}
            for seat in action_value.seats:
                for source in seat.action_sources:
                    spec = specs.get(source)
                    if (
                        spec is None
                        or spec.occurrence_family is not K0OccurrenceFamily.ACTION
                        or spec.action_value_owner != seat.owner
                        or spec.action_cost_projector is None
                    ):
                        raise K0ProfileError("action-value Action source is not fully bound")
            for kind in self.actor_kinds:
                for source in kind.action_sources:
                    spec = specs.get(source)
                    if (
                        spec is None
                        or spec.actor_self is None
                        or spec.actor_self.family != kind.family
                        or spec.action_cost_projector is None
                    ):
                        raise K0ProfileError("Actor template Action is not instance-relative")
            if {spec.key for spec in self.source_specs if spec.actor_self is not None} != {
                source for kind in self.actor_kinds for source in kind.action_sources
            }:
                raise K0ProfileError("Actor abilities do not cover exact self Action sources")
        elif any(spec.action_value_owner is not None for spec in self.source_specs):
            raise K0ProfileError("action-value Action source has no selected policy")
        elif self.actor_kinds:
            raise K0ProfileError("Actor kinds require an action-value policy")
        for spec in self.source_specs:
            if spec.scheduled_due_sources and self.temporal_policy is None:
                raise K0ProfileError("scheduled due needs a selected temporal policy")
            for due_source in spec.scheduled_due_sources:
                target = events.get(due_source)
                if target is None or target.due_projector is None:
                    raise K0ProfileError("scheduled due names no temporal Event source")
            if spec.due_projector is not None and self.temporal_policy is None:
                raise K0ProfileError("temporal Event needs a selected policy")
        for law in self.causal_laws:
            if law.triggering_event_type not in event_types:
                raise K0ProfileError("in-memory law trigger type is not declared")
            target = events.get(law.resulting_source)
            if target is None:
                raise K0ProfileError("in-memory law result source is not an Event")
            if target.due_projector is not None:
                raise K0ProfileError("temporal due Event cannot be formed by a causal law")
            if not set(law.read_owners).issubset(owner_keys):
                raise K0ProfileError("in-memory law read owners are not declared")
            if not set(law.read_owners).issubset(set(target.read_owners)):
                raise K0ProfileError("in-memory law read set is not covered by its Event")
            if any(
                not any(
                    port.name == selected.name and port.families == selected.families
                    for port in target.actor_domains
                )
                for selected in law.actor_domains
            ):
                raise K0ProfileError("causal Actor read domains are not covered by the Event")
        policy = self.same_wave_policy
        if policy is not None and (
            policy.owner not in owner_keys
            or any(source not in events for source in policy.sources)
            or any(
                events[source].contribution_owners != (policy.owner,) for source in policy.sources
            )
            or not any(
                spec.key == policy.trigger_source and spec.event_type == policy.trigger_event
                for spec in self.source_specs
            )
            or any(
                len(
                    tuple(
                        law
                        for law in self.causal_laws
                        if law.key == key
                        and law.resulting_source == source
                        and law.triggering_event_type == policy.trigger_event
                    )
                )
                != 1
                for key, source in zip(policy.law_keys, policy.sources, strict=True)
            )
        ):
            raise K0ProfileError("same-wave policy is not bound to exact Event owner ports")
        ordered = self.ordered_policy
        if ordered is not None:
            trigger = next(
                (spec for spec in self.source_specs if spec.key == ordered.trigger_source), None
            )
            if (
                ordered.owner not in owner_keys
                or trigger is None
                or trigger.occurrence_family is not K0OccurrenceFamily.ACTION
                or trigger.event_type != ordered.trigger_event
                or sum(
                    spec.occurrence_family is K0OccurrenceFamily.ACTION
                    for spec in self.source_specs
                )
                != 1
                or len(self.causal_laws) != 2
                or self.max_waves < 1
                or self.max_events < 3
                or any(
                    len(
                        tuple(
                            law
                            for law in self.causal_laws
                            if law.key == step.law_key
                            and law.resulting_source == step.source
                            and law.triggering_event_type == ordered.trigger_event
                            and law.max_activations == 1
                        )
                    )
                    != 1
                    or step.source not in events
                    or events[step.source].contribution_owners != (ordered.owner,)
                    or events[step.source].event_type == ordered.trigger_event
                    or ordered.owner
                    not in next(
                        law.read_owners for law in self.causal_laws if law.key == step.law_key
                    )
                    for step in ordered.steps
                )
            ):
                raise K0ProfileError("ordered policy is not bound to exact Action/Event ports")


class _K0InMemorySession:
    """One private in-memory session with a single atomic publication boundary."""

    def __init__(
        self,
        profile: _K0InMemoryProfile,
        states: tuple[_K0OwnerState, ...],
        invariants: tuple[_K0CrossOwnerInvariant, ...],
        initial_time: _K0FixedTime | None,
    ) -> None:
        self._profile = profile
        self._topology = _K0CandidateOwnerTopology(profile.owners)
        self._invariants = invariants
        self._states = states
        self._directory: _K0OwnerStateDirectory | None = None
        self._sources_by_key = MappingProxyType({spec.key: spec for spec in profile.source_specs})
        self._laws_by_key = MappingProxyType({law.key: law for law in profile.causal_laws})
        laws_by_event: dict[object, list[K0CausalLawDefinition]] = {}
        for law in profile.causal_laws:
            laws_by_event.setdefault(law.triggering_event_type, []).append(law)
        self._laws_by_event = MappingProxyType(
            {event: tuple(laws) for event, laws in laws_by_event.items()}
        )
        self._individual_scope = secrets.token_hex(16)
        self._individual_bindings: tuple[_K0IndividualBinding, ...] = ()
        self._actor_bindings: tuple[_K0ActorBinding, ...] = ()
        self._action_seats = (
            () if profile.action_value_policy is None else profile.action_value_policy.seats
        )
        self._fixed_due_selections: dict[
            K0SourceSpecKey, tuple[_K0DueIndividualSelection, ...]
        ] = {}
        self._next_individual = 1
        self._cursor = _K0OccurrenceCursor(1)
        self._tape: tuple[_K0InMemoryOccurrence, ...] = ()
        self._time = initial_time
        self._pending_due: tuple[_K0PendingDue, ...] = ()
        self._pre_due_phase: _K0PreDuePhase | None = None
        self._advance_history: tuple[_K0AdvanceRecord, ...] = ()
        self._action_values: tuple[_K0ActionValueState, ...] = ()
        self._action_opportunity: _K0ActionOpportunity | None = None
        self._action_value_history: tuple[_K0ActionValueRecord, ...] = ()
        self._same_time_actions = 0
        self._terminal: _K0TerminalState | None = None
        self._fatal = False
        self._settling = False

    def _current_owner_directory(self) -> _K0OwnerStateDirectory:
        directory = self._directory
        if (
            directory is None
            or directory.topology is not self._topology
            or directory.owner_states is not self._states
        ):
            directory = _K0OwnerStateDirectory(self._topology, self._states)
            self._directory = directory
        return directory

    @classmethod
    def create(
        cls,
        profile: _K0InMemoryProfile,
        opening_owner_states: tuple[_K0OwnerState, ...],
        invariants: tuple[_K0CrossOwnerInvariant, ...] = (),
        initial_time: _K0FixedTime | None = None,
        opening_individuals: tuple[_K0OpeningIndividual, ...] = (),
        opening_periodic_dues: tuple[_K0PeriodicDueOpening, ...] = (),
        opening_action_values: tuple[_K0ActionValueOpening, ...] = (),
        opening_actors: tuple[_K0OpeningActor, ...] = (),
    ) -> _K0InMemorySession:
        if type(profile) is not _K0InMemoryProfile or type(opening_owner_states) is not tuple:
            raise K0ProfileError("in-memory session needs one exact profile and owner states")
        if type(opening_individuals) is not tuple or any(
            type(item) is not _K0OpeningIndividual for item in opening_individuals
        ):
            raise K0ProfileError("opening individuals are malformed")
        if type(opening_actors) is not tuple or any(
            type(item) is not _K0OpeningActor for item in opening_actors
        ):
            raise K0ProfileError("opening Actors are malformed")
        if type(opening_periodic_dues) is not tuple or any(
            type(item) is not _K0PeriodicDueOpening for item in opening_periodic_dues
        ):
            raise K0ProfileError("opening periodic dues are malformed")
        if type(opening_action_values) is not tuple or any(
            type(item) is not _K0ActionValueOpening for item in opening_action_values
        ):
            raise K0ProfileError("opening action values are malformed")
        if len(profile.owners) != len(opening_owner_states):
            raise K0ProfileError("in-memory opening owner topology is not closed")
        if (profile.temporal_policy is None) != (initial_time is None) or (
            initial_time is not None and type(initial_time) is not _K0FixedTime
        ):
            raise K0ProfileError("temporal opening does not match the selected profile")
        if any(
            type(entry) is not _K0OwnerState or entry.owner != owner.key
            for owner, entry in zip(profile.owners, opening_owner_states, strict=True)
        ):
            raise K0ProfileError("in-memory opening owner order is not the profile order")
        w0 = tuple(
            _K0OwnerState(owner.key, _clone_owner_state(owner, entry.state))
            for owner, entry in zip(profile.owners, opening_owner_states, strict=True)
        )
        for owner, entry in zip(profile.owners, w0, strict=True):
            if isinstance(owner, _K0OpeningStateValidator):
                owner.validate_opening_state(_copy_closed_state(entry.state))
        session = cls(profile, w0, invariants, initial_time)
        if initial_time is not None and profile.temporal_policy is not None:
            plans = profile.temporal_policy.periodic_plans
            openings = {opening.plan: opening for opening in opening_periodic_dues}
            if len(openings) != len(opening_periodic_dues) or set(openings) != {
                plan.capability_ref for plan in plans
            }:
                raise K0ProfileError("periodic due openings do not fill the selected plans")
            if any(
                openings[plan.capability_ref].first_at.ordinal <= initial_time.ordinal
                for plan in plans
            ):
                raise K0ProfileError("periodic due must begin after opening time")
            session._pending_due = tuple(
                _K0PendingDue(
                    _K0PeriodicDueKey(plan.capability_ref, 0),
                    openings[plan.capability_ref].first_at,
                    plan.source,
                    plan.subject,
                )
                for plan in plans
            )
        elif opening_periodic_dues:
            raise K0ProfileError("periodic due opening has no selected temporal plan")
        if profile.action_value_policy is not None:
            openings = {opening.seat: opening for opening in opening_action_values}
            seats = {seat.seat: seat for seat in profile.action_value_policy.seats}
            if (
                len(openings) != len(opening_action_values)
                or set(openings) != set(seats)
                or len({opening.tie_priority for opening in openings.values()}) != len(openings)
                or initial_time is None
                or (
                    profile.action_value_policy.end_at is not None
                    and initial_time.ordinal >= profile.action_value_policy.end_at.ordinal
                )
            ):
                raise K0ProfileError("action-value openings do not fill the selected policy")
            session._action_values = tuple(
                _K0ActionValueState(name, openings[name].debt, openings[name].tie_priority)
                for name in sorted(openings)
            )
        elif opening_action_values:
            raise K0ProfileError("action-value opening has no selected policy")
        if opening_individuals:
            candidate = _K0OwnerStateCandidate(
                session._topology,
                profile.source_specs,
                profile.causal_laws,
                invariants,
                w0,
                session._cursor,
                initial_time,
                _K0RuntimePropositionState(),
            )
            bindings: tuple[_K0IndividualBinding, ...] = ()
            for opening in opening_individuals:
                opening.__post_init__()
                bindings += (
                    session._stage_individual(
                        candidate,
                        opening.family,
                        opening.initial_state,
                        None,
                        session._next_individual + len(bindings),
                        bindings,
                    ),
                )
            session._topology = candidate.topology
            session._states = candidate._snapshot_states()
            session._individual_bindings = bindings
            session._next_individual += len(bindings)
        if opening_actors:
            candidate = _K0OwnerStateCandidate(
                session._topology,
                profile.source_specs,
                profile.causal_laws,
                invariants,
                session._states,
                session._cursor,
                initial_time,
                _K0RuntimePropositionState(),
            )
            formation = session._formation_candidate()
            for opening in opening_actors:
                opening.__post_init__()
                session._stage_actor(
                    candidate,
                    formation,
                    opening.family,
                    opening.initial_state,
                    None,
                    initial_time,
                    opening.debt,
                )
            session._topology = candidate.topology
            session._states = candidate._snapshot_states()
            session._actor_bindings = formation.actor_bindings
            session._next_individual = formation.next_ordinal
            session._action_seats = formation.seats
            session._action_values = formation.debts
        for spec in profile.source_specs:
            if not spec.due_fixed_individual_ports:
                continue
            selected = []
            for port in spec.due_fixed_individual_ports:
                matches = tuple(
                    binding
                    for binding in session._individual_bindings
                    if binding.individual.family == port.family and binding.formed_by is None
                )
                if len(matches) != 1:
                    raise K0ProfileError("fixed due individual needs exactly one opening instance")
                selected.append(
                    _K0DueIndividualSelection(port.name, matches[0].individual, matches[0].owner)
                )
            session._fixed_due_selections[spec.key] = tuple(selected)
        opening_candidate = _K0OwnerStateCandidate(
            session._topology,
            profile.source_specs,
            profile.causal_laws,
            invariants,
            session._states,
            session._cursor,
            initial_time,
            _K0RuntimePropositionState(),
        )
        opening_candidate.validate_cross_owner_invariants()
        session._terminal = session._terminal_at(
            opening_candidate,
            "opening",
            initial_time,
            None,
            session._pending_due,
            (),
        )
        if session._terminal is not None:
            session._pending_due = ()
        session._refresh_action_opportunity()
        return session

    def terminal_state(self) -> _K0TerminalState | None:
        return self._terminal

    def _terminal_at(
        self,
        candidate: _K0OwnerStateCandidate,
        checkpoint: str,
        time: _K0FixedTime | None,
        trigger: K0OccurrenceRef | None,
        pending: tuple[_K0PendingDue, ...],
        tape: tuple[_K0InMemoryOccurrence, ...],
    ) -> _K0TerminalState | None:
        policy = self._profile.terminal_policy
        if policy is None:
            return None
        for index, clause in enumerate(policy.clauses):
            result = clause.projector.project(candidate.owner_views(clause.read_owners))
            if type(result) is not bool:
                raise K0ProfileError("terminal projection must return an exact bool")
            if not result:
                continue
            plans = (
                ()
                if self._profile.temporal_policy is None
                else self._profile.temporal_policy.periodic_plans
            )
            closed = []
            for plan in plans:
                last = next(
                    (
                        item.occurrence
                        for item in reversed(tape)
                        if type(item.formation_basis) is _K0DueFormation
                        and type(item.formation_basis.key) is _K0PeriodicDueKey
                        and item.formation_basis.key.plan == plan.capability_ref
                    ),
                    None,
                )
                closed.append(_K0ClosedPeriodicPlan(plan.capability_ref, last))
            return _K0TerminalState(
                policy.capability_ref,
                index,
                clause.outcome,
                checkpoint,
                time,
                trigger,
                tuple(_K0NotReachedDue(item) for item in pending),
                tuple(closed),
            )
        return None

    def _stage_individual(
        self,
        candidate: _K0OwnerStateCandidate,
        family: str,
        initial_state: object,
        formed_by: K0OccurrenceRef | None,
        ordinal: int,
        prior_bindings: tuple[_K0IndividualBinding, ...],
    ) -> _K0IndividualBinding:
        kind = next(
            (item for item in self._profile.dynamic_owner_kinds if item.family == family), None
        )
        if kind is None or type(initial_state) is not kind.state_type:
            raise K0ProfileError("formed owner has no declared kind or state")
        if sum(item.individual.family == family for item in prior_bindings) >= kind.max_instances:
            raise K0ProfileError("dynamic owner limit exceeded")
        individual = _K0IndividualRef(self._individual_scope, ordinal, family)
        key = K0OwnerKey(f"dynamic.{self._individual_scope}.{ordinal}")
        owner = kind.factory.build(key)
        if (
            not isinstance(owner, _K0Owner)
            or type(owner.key) is not K0OwnerKey
            or owner.key != key
            or owner.state_type is not kind.state_type
        ):
            raise K0ProfileError("dynamic owner factory returned a foreign owner")
        _validate_closed_host_object(owner, "dynamic owner instance")
        if formed_by is None and isinstance(owner, _K0OpeningStateValidator):
            owner.validate_opening_state(initial_state)
        candidate.stage_owner(owner, initial_state)
        return _K0IndividualBinding(individual, key, formed_by)

    def individuals(self) -> tuple[_K0IndividualBinding, ...]:
        return self._individual_bindings

    def actors(self) -> tuple[_K0ActorBinding, ...]:
        return self._actor_bindings

    def _actor_binding_for(self, actor: object) -> _K0ActorBinding | None:
        if type(actor) is not _K0ActorRef or actor.scope != self._individual_scope:
            return None
        try:
            actor.__post_init__()
        except (AttributeError, TypeError, K0ProfileError):
            return None
        return next((binding for binding in self._actor_bindings if binding.actor == actor), None)

    def read_actor(self, actor: _K0ActorRef) -> _K0OwnerView:
        binding = self._actor_binding_for(actor)
        if binding is None:
            raise K0ProfileError("Actor is not in this Session")
        return self.read_owner(binding.owner)

    def _formation_candidate(self) -> _K0FormationCandidate:
        return _K0FormationCandidate(
            self._individual_bindings,
            self._actor_bindings,
            self._next_individual,
            self._action_seats,
            self._action_values,
        )

    def _actor_domain_views(
        self,
        candidate: _K0OwnerStateCandidate,
        ports: tuple[_K0ActorDomainPort, ...],
        bindings: tuple[_K0ActorBinding, ...],
    ) -> tuple[tuple[_K0OwnerView, ...], tuple[K0OwnerKey, ...]]:
        views, writes = [], []
        for port in ports:
            for binding in bindings:
                if binding.actor.family not in port.families:
                    continue
                view = candidate.owner_views((binding.owner,))[0]
                views.append(_K0OwnerView(view.owner, view.view, port.name, binding.actor))
                if port.write:
                    writes.append(binding.owner)
        return tuple(views), tuple(sorted(writes))

    def _object_domain_views(self, candidate, ports, bindings):
        views = []
        for port in sorted(ports, key=lambda item: item.name):
            for binding in sorted(bindings, key=lambda item: item.individual.ordinal):
                if binding.individual.family != port.family:
                    continue
                binding.__post_init__()
                if binding.individual.scope != self._individual_scope:
                    raise K0ProfileError("read Object domain has a foreign individual scope")
                view = candidate.owner_views((binding.owner,))[0]
                views.append(
                    _K0OwnerView(
                        view.owner, view.view, port.name, individual_ref=binding.individual
                    )
                )
        if len({view.owner for view in views}) != len(views) or len(
            {view.individual_ref for view in views}
        ) != len(views):
            raise K0ProfileError("read Object domain aliases an actual binding")
        return tuple(views)

    def _stage_actor(
        self,
        candidate: _K0OwnerStateCandidate,
        formation: _K0FormationCandidate,
        family: str,
        state: object,
        formed_by: K0OccurrenceRef | None,
        at: _K0FixedTime | None,
        opening_debt: int | None = None,
    ) -> None:
        kind = next((item for item in self._profile.actor_kinds if item.family == family), None)
        if kind is None or type(state) is not kind.state_type or type(at) is not _K0FixedTime:
            raise K0ProfileError("formed Actor lacks its declared kind, state or time")
        if (
            sum(item.actor.family == family for item in formation.actor_bindings)
            >= kind.max_instances
        ):
            raise K0ProfileError("Actor formation capacity exceeded")
        ordinal = formation.next_ordinal
        ref = _K0ActorRef(self._individual_scope, ordinal, family)
        key = K0OwnerKey(f"dynamic_actor.{self._individual_scope}.{ordinal}")
        owner = kind.factory.build(key)
        if (
            not isinstance(owner, _K0Owner)
            or owner.key != key
            or owner.state_type is not kind.state_type
        ):
            raise K0ProfileError("Actor factory returned a foreign owner")
        _validate_closed_host_object(owner, "Actor instance owner")
        if formed_by is None and isinstance(owner, _K0OpeningStateValidator):
            owner.validate_opening_state(state)
        candidate.stage_owner(owner, state)
        projection = kind.projector.project(candidate.owner_views((key,))[0])
        if type(projection) is not _K0ActionValueProjection:
            raise K0ProfileError("Actor template returned a foreign tempo projection")
        projection.__post_init__()
        seat = f"actor.{family}.{ordinal}"
        if any(item.seat == seat for item in formation.seats):
            raise K0ProfileError("Actor formation would create an aliased seat")
        formation.actor_bindings += (_K0ActorBinding(ref, key, formed_by, at, seat, kind.control),)
        formation.seats += (_K0ActionValueSeat(seat, key, kind.action_sources, kind.projector),)
        formation.debts += (
            _K0ActionValueState(
                seat,
                kind.initial_debt if opening_debt is None else opening_debt,
                kind.tie_priority,
                ordinal,
            ),
        )
        formation.next_ordinal += 1

    def _stage_products(
        self,
        candidate: _K0OwnerStateCandidate,
        formation: _K0FormationCandidate,
        result: K0RuleResult,
        occurrence: K0OccurrenceRef,
        at: _K0FixedTime | None,
    ) -> None:
        for request in result.formed_owners:
            binding = self._stage_individual(
                candidate,
                request.family,
                request.initial_state,
                occurrence,
                formation.next_ordinal,
                formation.individual_bindings,
            )
            formation.individual_bindings += (binding,)
            formation.next_ordinal += 1
        for product in result.formed_actors:
            if product.initial_state is not None:
                self._stage_actor(
                    candidate, formation, product.family, product.initial_state, occurrence, at
                )

    def _binding_for(self, individual: object) -> _K0IndividualBinding | None:
        if type(individual) is not _K0IndividualRef:
            return None
        try:
            individual.__post_init__()
        except (AttributeError, TypeError, K0ProfileError):
            return None
        if individual.scope != self._individual_scope:
            return None
        return next(
            (item for item in self._individual_bindings if item.individual == individual), None
        )

    def read_individual(self, individual: _K0IndividualRef) -> _K0OwnerView:
        binding = self._binding_for(individual)
        if binding is None:
            raise K0ProfileError("individual is not in this Session")
        return self.read_owner(binding.owner)

    def read_owner(self, actor_owner_key: K0OwnerKey) -> _K0OwnerView:
        if type(actor_owner_key) is not K0OwnerKey:
            raise K0ProfileError("in-memory read needs one exact owner key")
        return _build_candidate_owner_views(self._current_owner_directory(), (actor_owner_key,))[0]

    def read_time(self) -> _K0FixedTime:
        if self._time is None:
            raise K0ProfileError("session has no selected temporal policy")
        return self._time

    def temporal_history(self) -> tuple[_K0AdvanceRecord, ...]:
        if self._time is None:
            raise K0ProfileError("session has no selected temporal policy")
        return self._advance_history

    def action_opportunity(self) -> _K0ActionOpportunity | None:
        if self._profile.action_value_policy is None:
            raise K0ProfileError("session has no selected action-value policy")
        return self._action_opportunity

    def action_value_history(self) -> tuple[_K0ActionValueRecord, ...]:
        if self._profile.action_value_policy is None:
            raise K0ProfileError("session has no selected action-value policy")
        return self._action_value_history

    def action_value_state(self) -> tuple[_K0ActionValueState, ...]:
        if self._profile.action_value_policy is None:
            raise K0ProfileError("session has no selected action-value policy")
        return self._action_values

    def _action_value_projections(self) -> dict[str, object]:
        policy = self._profile.action_value_policy
        if policy is None:
            raise K0ProfileError("session has no selected action-value policy")
        projections = {}
        for seat in self._action_seats:
            view = self.read_owner(seat.owner)
            projection = seat.projector.project(view)
            projection.__post_init__()
            projections[seat.seat] = projection
        return projections

    def _refresh_action_opportunity(self) -> dict[str, object] | None:
        policy = self._profile.action_value_policy
        if (
            policy is None
            or self._terminal is not None
            or self._time is None
            or (policy.end_at is not None and self._time.ordinal >= policy.end_at.ordinal)
        ):
            self._action_opportunity = None
            return
        projections = self._action_value_projections()
        states = {item.seat: item for item in self._action_values}
        ready = tuple(
            item
            for item in self._action_values
            if projections[item.seat].eligible and item.debt <= 0
        )
        if not ready:
            self._action_opportunity = None
            return projections
        selected = min(ready, key=lambda item: (item.tie_priority, item.formation_order, item.seat))
        seat = next(item for item in self._action_seats if item.seat == selected.seat)
        if selected.seat not in states:
            raise K0ProfileError("action-value state lost its selected seat")
        self._action_opportunity = _K0ActionOpportunity(selected.seat, seat.owner, self._time)
        return projections

    def continue_action_value(
        self,
    ) -> _K0ActionOpportunity | _K0ActionValueDueBoundary | _K0SessionClosed | None:
        """Advance until an Actor is ready, a due Event settles, or the Session closes."""
        if self._terminal is not None:
            return _K0SessionClosed(self._terminal)
        if self._fatal:
            raise K0SettlementDefect("fatal in-memory session cannot continue")
        policy = self._profile.action_value_policy
        if policy is None or self._time is None:
            raise K0ProfileError("session has no selected action-value policy")
        for _ in range(1024):
            projections = self._refresh_action_opportunity()
            if self._action_opportunity is not None:
                return self._action_opportunity
            if policy.end_at is not None and self._time.ordinal >= policy.end_at.ordinal:
                return None
            if self._pre_due_phase is not None:
                self.resolve_pre_due()
                if self._terminal is not None:
                    return _K0SessionClosed(self._terminal)
                return _K0ActionValueDueBoundary(self._time)

            # Reuse only this decision's current projections, before any world transition.
            if projections is None:
                raise K0SettlementDefect("action-value scheduler lost its current projections")
            actor_deltas = tuple(
                (state.debt + projections[state.seat].tempo - 1) // projections[state.seat].tempo
                for state in self._action_values
                if projections[state.seat].eligible and state.debt > 0
            )
            actor_delta = min(actor_deltas, default=None)
            next_due = self.next_due_time()
            candidates = (
                [policy.end_at.ordinal - self._time.ordinal] if policy.end_at is not None else []
            )
            if actor_delta is not None:
                candidates.append(actor_delta)
            if next_due is not None:
                candidates.append(next_due.ordinal - self._time.ordinal)
            if not candidates:
                return None
            delta = min(candidates)
            if delta <= 0:
                raise K0SettlementDefect("action-value scheduler cannot make progress")
            target = _K0FixedTime(self._time.ordinal + delta)
            before = self._action_values
            after = tuple(
                _K0ActionValueState(
                    state.seat,
                    state.debt - delta * projections[state.seat].tempo
                    if projections[state.seat].eligible
                    else state.debt,
                    state.tie_priority,
                    state.formation_order,
                )
                for state in before
            )
            if any(abs(state.debt) > _K0_MAX_ACTION_VALUE for state in after):
                raise K0SettlementDefect("action-value debt exceeded its finite range")
            request = _K0TemporalAdvanceRequest(_K0TemporalInterval(self._time, target))
            due_here = next_due == target
            ready_here = any(
                projections[state.seat].eligible and state.debt <= 0 for state in after
            )
            record = _K0ActionValueRecord(target, "advance", None, before, after)
            result = (
                self.begin_pre_due(request, _action_value_record=record)
                if due_here and ready_here
                else self.advance(request, _action_value_record=record)
            )
            if isinstance(result, _K0TemporalRejected):
                raise K0SettlementDefect("action-value temporal transition was rejected")
            if self._terminal is not None:
                return _K0SessionClosed(self._terminal)
            if due_here and not ready_here:
                return _K0ActionValueDueBoundary(self._time)
        raise K0SettlementDefect("action-value scheduler exceeded its transition bound")

    def _advanced_action_values(
        self,
        record: _K0ActionValueRecord | None,
        boundary: _K0FixedTime,
    ) -> tuple[tuple[_K0ActionValueState, ...], tuple[_K0ActionValueRecord, ...]]:
        if record is None:
            return self._action_values, self._action_value_history
        if (
            type(record) is not _K0ActionValueRecord
            or self._time is None
            or record.at != boundary
            or record.kind != "advance"
            or record.seat is not None
            or record.cost is not None
            or record.debt_before != self._action_values
        ):
            raise K0ProfileError("action-value advance lost its current scheduler basis")
        delta = boundary.ordinal - self._time.ordinal
        projections = self._action_value_projections()
        expected = tuple(
            replace(state, debt=state.debt - delta * projections[state.seat].tempo)
            if projections[state.seat].eligible
            else state
            for state in self._action_values
        )
        if delta <= 0 or record.debt_after != expected:
            raise K0ProfileError("action-value advance debt does not match the selected interval")
        return expected, self._action_value_history + (record,)

    def next_due_time(self) -> _K0FixedTime | None:
        if self._time is None:
            raise K0ProfileError("session has no selected temporal policy")
        return min((pending.at for pending in self._pending_due), default=None)

    def in_pre_due_phase(self) -> bool:
        if self._time is None:
            raise K0ProfileError("session has no selected temporal policy")
        return self._pre_due_phase is not None

    def occurrence_history(self) -> tuple[_K0InMemoryOccurrence, ...]:
        return self._tape

    def settle(
        self, attempt: _K0InMemoryActionAttempt
    ) -> K0NotAdmitted | K0Published | _K0SessionClosed:
        if self._terminal is not None:
            return _K0SessionClosed(self._terminal)
        if self._fatal:
            raise K0SettlementDefect("fatal in-memory session cannot settle")
        if self._settling:
            raise K0SettlementDefect("an in-memory session cannot start a nested settlement")
        if type(attempt) is not _K0InMemoryActionAttempt:
            raise K0ProfileError("in-memory attempt has the wrong carrier")
        spec = self._sources_by_key.get(attempt.source)
        if spec is None or spec.occurrence_family is not K0OccurrenceFamily.ACTION:
            raise K0ProfileError("in-memory attempt names no declared Action source")
        if type(attempt.payload) is not spec.payload_type:
            raise K0ProfileError("in-memory Action payload has the wrong exact type")
        action_value_seat = None
        action_cost = None
        action_value_after = None
        action_value_policy = self._profile.action_value_policy
        if action_value_policy is not None:
            opportunity = self._action_opportunity
            action_value_seat = next(
                (
                    seat
                    for seat in self._action_seats
                    if opportunity is not None
                    and seat.seat == opportunity.seat
                    and seat.owner == opportunity.owner
                    and spec.key in seat.action_sources
                    and (
                        spec.action_value_owner == seat.owner
                        or (
                            spec.actor_self is not None
                            and any(
                                binding.owner == seat.owner
                                and binding.actor.family == spec.actor_self.family
                                and binding.actor
                                == getattr(attempt.payload, spec.actor_self.payload_field)
                                for binding in self._actor_bindings
                            )
                        )
                    )
                ),
                None,
            )
            if action_value_seat is None or opportunity.at != self._time:
                return K0NotAdmitted(spec.key)
            if self._same_time_actions >= action_value_policy.max_same_time_actions:
                raise K0SettlementDefect("action-value same-time action bound exceeded")
        if self._time is not None:
            unresolved = tuple(
                pending for pending in self._pending_due if pending.at.ordinal <= self._time.ordinal
            )
            allowed_pre_due = (
                self._pre_due_phase is not None
                and unresolved
                and all(pending.at == self._time for pending in unresolved)
                and attempt.source in self._profile.temporal_policy.pre_due_action_sources
                and action_value_seat is not None
            )
            if unresolved and not allowed_pre_due:
                return K0NotAdmitted(spec.key)
        self._settling = True
        admitted = False
        try:
            selected: dict[K0OwnerKey, str] = {}
            actor_refs: dict[K0OwnerKey, _K0ActorRef] = {}
            selected_owners: list[_K0SelectedOwner] = []
            read_owners = list(spec.read_owners)
            contribution_owners = list(spec.contribution_owners)
            if spec.actor_self is not None:
                actor = self._actor_binding_for(
                    getattr(attempt.payload, spec.actor_self.payload_field)
                )
                if actor is None or actor.actor.family != spec.actor_self.family:
                    return K0NotAdmitted(spec.key)
                if actor.owner in read_owners or actor.owner in contribution_owners:
                    return K0NotAdmitted(spec.key)
                selected[actor.owner] = "actor"
                actor_refs[actor.owner] = actor.actor
                read_owners.append(actor.owner)
                if spec.actor_self.write:
                    contribution_owners.append(actor.owner)
            for port in spec.participant_ports:
                value = getattr(attempt.payload, port.payload_field, None)
                if type(port) is _K0IndividualOwnerPort:
                    binding = self._binding_for(value)
                    if binding is None or binding.individual.family not in port.families:
                        return K0NotAdmitted(spec.key)
                    owner = binding.owner
                elif type(port) is _K0ActorParticipantPort:
                    binding = self._actor_binding_for(value)
                    if binding is None or binding.actor.family != port.family:
                        return K0NotAdmitted(spec.key)
                    owner = binding.owner
                    actor_refs[owner] = binding.actor
                else:
                    if value is None and port.nullable:
                        continue
                    if type(value) is not str:
                        return K0NotAdmitted(spec.key)
                    owner = dict(port.members).get(value)
                    if owner is None:
                        return K0NotAdmitted(spec.key)
                if owner in selected or owner in read_owners or owner in contribution_owners:
                    return K0NotAdmitted(spec.key)
                selected[owner] = port.name
                selected_owners.append(_K0SelectedOwner(port.name, value, owner))
                read_owners.append(owner)
                if port.write:
                    contribution_owners.append(owner)
            runtime_propositions = _K0RuntimePropositionState()
            w0_views = tuple(
                _K0OwnerView(
                    view.owner, view.view, selected.get(view.owner), actor_refs.get(view.owner)
                )
                for view in _build_candidate_owner_views(
                    self._current_owner_directory(), tuple(sorted(read_owners))
                )
            )
            input_candidate = _K0OwnerStateCandidate(
                self._topology,
                self._profile.source_specs,
                self._profile.causal_laws,
                self._invariants,
                self._states,
                self._cursor,
                self._time,
                runtime_propositions,
            )
            domain_views, domain_writes = self._actor_domain_views(
                input_candidate,
                spec.actor_domains,
                self._actor_bindings,
            )
            w0_views += domain_views
            contribution_owners.extend(domain_writes)
            projection = _admit_source(
                spec.admission_capability,
                attempt.payload,
                w0_views,
                runtime_propositions,
                self._time,
            )
            if projection is None:
                return K0NotAdmitted(spec.key)
            _validate_admission_projection(
                projection,
                spec.evidence_type,
                spec.participants_type,
                spec.binding_keys,
                spec.binding_types,
            )
            if action_value_seat is not None:
                action_cost = spec.action_cost_projector.project_cost(attempt.payload, projection)
                if (
                    type(action_cost) is not int
                    or action_cost < 1
                    or action_cost > _K0_MAX_ACTION_VALUE
                ):
                    return K0NotAdmitted(spec.key)
                current_debt = next(
                    item.debt for item in self._action_values if item.seat == action_value_seat.seat
                )
                if current_debt + action_cost > _K0_MAX_ACTION_VALUE:
                    return K0NotAdmitted(spec.key)
                action_value_after = tuple(
                    _K0ActionValueState(
                        item.seat,
                        item.debt + action_cost
                        if item.seat == action_value_seat.seat
                        else item.debt,
                        item.tie_priority,
                        item.formation_order,
                    )
                    for item in self._action_values
                )
            admitted = True
            candidate = _K0OwnerStateCandidate(
                self._topology,
                self._profile.source_specs,
                self._profile.causal_laws,
                self._invariants,
                self._states,
                self._cursor,
                self._time,
                runtime_propositions,
            )
            occurrence_ref = candidate.allocate_occurrence()
            formation = self._formation_candidate()
            rule_input = _K0InMemoryRuleInput(
                occurrence_ref,
                spec.key,
                projection.evidence,
                projection.participants,
                projection.bindings,
                None,
                self._time,
            )
            evaluation = _evaluate_source(spec, rule_input)
            result = evaluation.result
            if result.local_output_requests:
                raise K0ProfileError("this slice does not allow local output requests")
            _validate_rule_result(
                candidate.owners,
                result,
                (),
                tuple(sorted(contribution_owners)),
                spec.scheduled_due_sources,
                () if spec.form_owner_family is None else (spec.form_owner_family,),
                spec.actor_product,
            )
            new_due = tuple(
                _K0PendingDue(
                    _K0PendingDueKey(occurrence_ref, ordinal),
                    request.at,
                    request.source,
                    request.subject,
                )
                for ordinal, request in enumerate(result.scheduled_due)
            )
            if new_due:
                if self._time is None or any(
                    request.at.ordinal <= self._time.ordinal for request in result.scheduled_due
                ):
                    raise K0ProfileError("scheduled due must be in the future")
                policy = self._profile.temporal_policy
                if policy is None:
                    raise K0ProfileError("scheduled due has no selected temporal policy")
                all_due = self._pending_due + new_due
                if (
                    len(all_due) > policy.max_pending
                    or any(item.source not in policy.source_order for item in all_due)
                    or len({item.source for item in all_due}) != len(all_due)
                ):
                    raise K0ProfileError("scheduled dues exceed the declared temporal binding")
            envelope = evaluation.envelope
            if type(envelope) is not spec.envelope_type:
                raise K0ProfileError("in-memory envelope has the wrong exact type")
            self._stage_products(candidate, formation, result, occurrence_ref, self._time)
            _apply_contributions(
                candidate, occurrence_ref, result, tuple(sorted(contribution_owners))
            )
            candidate.validate_cross_owner_invariants()
            occurrences: list[_K0InMemoryOccurrence] = [
                _K0InMemoryOccurrence(
                    occurrence_ref,
                    spec.occurrence_family,
                    spec.key,
                    spec.event_type,
                    _K0InMemoryActionBasis(spec.key),
                    projection.participants,
                    _IN_MEMORY_COORDINATE,
                    envelope,
                    tuple(selected_owners),
                )
            ]
            self._settle_causal_waves(candidate, occurrences, formation)
            if len(occurrences) > self._profile.max_events:
                raise K0ProfileError("in-memory settlement exceeded the event bound")
            w1_states = candidate._snapshot_states()
            tape = self._tape + tuple(occurrences)
            receipt = K0Published(tuple(occurrences))
            next_cursor = _K0OccurrenceCursor(self._cursor.next_value + len(occurrences))
            next_pending = self._pending_due + new_due
            terminal = self._terminal_at(
                candidate, "action", self._time, occurrence_ref, next_pending, tape
            )
            next_advance_history = self._advance_history
            next_phase = self._pre_due_phase
            if terminal is not None:
                next_pending = ()
                if next_phase is not None:
                    next_advance_history += (
                        _K0AdvanceRecord(
                            next_phase.interval,
                            next_phase.tape_before,
                            len(tape),
                            (),
                            self._profile.temporal_policy.capability_ref,
                        ),
                    )
                    next_phase = None
            next_action_values = formation.debts
            next_opportunity = self._action_opportunity
            next_same_time_actions = self._same_time_actions
            next_action_history = self._action_value_history
            if action_value_seat is not None:
                assert (
                    action_cost is not None
                    and action_value_after is not None
                    and self._time is not None
                )
                charged = {item.seat: item for item in action_value_after}
                next_action_values = tuple(charged.get(item.seat, item) for item in formation.debts)
                next_opportunity = None
                next_same_time_actions += 1
                next_action_history += (
                    _K0ActionValueRecord(
                        self._time,
                        "action",
                        action_value_seat.seat,
                        self._action_values,
                        next_action_values,
                        action_cost,
                    ),
                )
            if terminal is not None:
                next_opportunity = None
            (
                self._topology,
                self._states,
                self._cursor,
                self._tape,
                self._pending_due,
                self._individual_bindings,
                self._actor_bindings,
                self._action_seats,
                self._next_individual,
                self._action_values,
                self._action_opportunity,
                self._same_time_actions,
                self._action_value_history,
                self._terminal,
                self._advance_history,
                self._pre_due_phase,
            ) = (
                candidate.topology,
                w1_states,
                next_cursor,
                tape,
                next_pending,
                formation.individual_bindings,
                formation.actor_bindings,
                formation.seats,
                formation.next_ordinal,
                next_action_values,
                next_opportunity,
                next_same_time_actions,
                next_action_history,
                terminal,
                next_advance_history,
                next_phase,
            )
            return receipt
        except K0SettlementDefect:
            self._fatal = True
            raise
        except Exception as error:
            if admitted:
                self._fatal = True
                raise K0SettlementDefect("K0 engine defect during in-memory settlement") from error
            if isinstance(error, K0ProfileError):
                raise
            raise K0ProfileError("in-memory preflight failed") from error
        finally:
            self._settling = False

    def advance(
        self,
        request: _K0TemporalAdvanceRequest,
        *,
        _action_value_record: _K0ActionValueRecord | None = None,
    ) -> _K0TemporalRejected | _K0TemporalPublished | _K0SessionClosed:
        if self._terminal is not None:
            return _K0SessionClosed(self._terminal)
        if self._fatal:
            raise K0SettlementDefect("fatal in-memory session cannot advance")
        if self._settling:
            raise K0SettlementDefect("an in-memory session cannot start a nested advance")
        if self._time is None or self._profile.temporal_policy is None:
            raise K0ProfileError("session has no selected temporal policy")
        if type(request) is not _K0TemporalAdvanceRequest:
            raise K0ProfileError("temporal advance has the wrong carrier")
        if request.interval.t0 != self._time or self._pre_due_phase is not None:
            return _K0TemporalRejected()

        self._settling = True
        admitted = False
        try:
            due_group = self._due_group_through(request.interval.t1)
            boundary = request.interval.t1 if not due_group else due_group[0].at
            if boundary.ordinal <= self._time.ordinal:
                return _K0TemporalRejected()
            interval = _K0TemporalInterval(self._time, boundary)
            admitted = True
            if not due_group:
                receipt = _K0TemporalPublished(interval, ())
                record = _K0AdvanceRecord(
                    interval,
                    len(self._tape),
                    len(self._tape),
                    (),
                    self._profile.temporal_policy.capability_ref,
                )
                history = self._advance_history + (record,)
                values, value_history = self._advanced_action_values(_action_value_record, boundary)
                (
                    self._time,
                    self._advance_history,
                    self._action_values,
                    self._action_value_history,
                ) = (
                    boundary,
                    history,
                    values,
                    value_history,
                )
                if _action_value_record is not None:
                    self._same_time_actions = 0
                return receipt
            return self._settle_due_group(
                interval, due_group, len(self._tape), _action_value_record
            )
        except K0SettlementDefect:
            self._fatal = True
            raise
        except Exception as error:
            if admitted:
                self._fatal = True
                raise K0SettlementDefect("K0 engine defect during temporal settlement") from error
            if isinstance(error, K0ProfileError):
                raise
            raise K0ProfileError("in-memory temporal preflight failed") from error
        finally:
            self._settling = False

    def begin_pre_due(
        self,
        request: _K0TemporalAdvanceRequest,
        *,
        _action_value_record: _K0ActionValueRecord | None = None,
    ) -> _K0TemporalRejected | _K0TemporalPublished | _K0SessionClosed:
        """Reach the next due boundary without settling it for Actor-first GameForms."""
        if self._terminal is not None:
            return _K0SessionClosed(self._terminal)
        if self._fatal:
            raise K0SettlementDefect("fatal in-memory session cannot advance")
        if self._settling:
            raise K0SettlementDefect("an in-memory session cannot start a nested advance")
        if self._time is None or self._profile.temporal_policy is None:
            raise K0ProfileError("session has no selected temporal policy")
        if type(request) is not _K0TemporalAdvanceRequest:
            raise K0ProfileError("temporal advance has the wrong carrier")
        if request.interval.t0 != self._time or self._pre_due_phase is not None:
            return _K0TemporalRejected()
        due_group = self._due_group_through(request.interval.t1)
        if not due_group:
            return _K0TemporalRejected()
        boundary = due_group[0].at
        interval = _K0TemporalInterval(self._time, boundary)
        phase = _K0PreDuePhase(
            interval,
            tuple(item.key for item in due_group),
            len(self._tape),
        )
        values, history = self._advanced_action_values(_action_value_record, boundary)
        self._time, self._pre_due_phase, self._action_values, self._action_value_history = (
            boundary,
            phase,
            values,
            history,
        )
        if _action_value_record is not None:
            self._same_time_actions = 0
        return _K0TemporalPublished(interval, ())

    def resolve_pre_due(self) -> _K0TemporalPublished | _K0SessionClosed:
        """Close an Actor-first boundary and atomically settle its exact due group."""
        if self._terminal is not None:
            return _K0SessionClosed(self._terminal)
        if self._fatal:
            raise K0SettlementDefect("fatal in-memory session cannot resolve due")
        if self._settling:
            raise K0SettlementDefect("an in-memory session cannot start nested due resolution")
        if self._time is None or self._profile.temporal_policy is None:
            raise K0ProfileError("session has no selected temporal policy")
        phase = self._pre_due_phase
        if phase is None or phase.interval.t1 != self._time:
            raise K0ProfileError("session has no open pre-due phase")
        due_group = tuple(item for item in self._pending_due if item.key in set(phase.due_keys))
        due_group = tuple(
            sorted(
                due_group,
                key=lambda item: self._profile.temporal_policy.source_order.index(item.source),
            )
        )
        if tuple(item.key for item in due_group) != phase.due_keys or any(
            item.at != self._time for item in due_group
        ):
            raise K0SettlementDefect("pre-due obligations changed before resolution")
        self._settling = True
        try:
            receipt = self._settle_due_group(
                phase.interval,
                due_group,
                phase.tape_before,
            )
            return receipt
        except Exception as error:
            self._fatal = True
            if isinstance(error, K0SettlementDefect):
                raise
            raise K0SettlementDefect("K0 engine defect during pre-due resolution") from error
        finally:
            self._settling = False

    def _due_group_through(self, target: _K0FixedTime) -> tuple[_K0PendingDue, ...]:
        policy = self._profile.temporal_policy
        if policy is None:
            raise K0ProfileError("session has no selected temporal policy")
        next_due = min(self._pending_due, key=lambda item: item.at.ordinal, default=None)
        due_group = (
            tuple(item for item in self._pending_due if item.at == next_due.at)
            if next_due is not None and next_due.at.ordinal <= target.ordinal
            else ()
        )
        return tuple(sorted(due_group, key=lambda item: policy.source_order.index(item.source)))

    def _settle_due_group(
        self,
        interval: _K0TemporalInterval,
        due_group: tuple[_K0PendingDue, ...],
        tape_before: int,
        action_value_record: _K0ActionValueRecord | None = None,
    ) -> _K0TemporalPublished:
        policy = self._profile.temporal_policy
        if policy is None or not due_group:
            raise K0ProfileError("temporal due settlement lacks a selected group")
        boundary = interval.t1
        candidate = _K0OwnerStateCandidate(
            self._topology,
            self._profile.source_specs,
            self._profile.causal_laws,
            self._invariants,
            self._states,
            self._cursor,
            boundary,
            _K0RuntimePropositionState(),
        )
        occurrences: list[_K0InMemoryOccurrence] = []
        formation = self._formation_candidate()
        debt_before = self._action_values
        value_history = self._action_value_history
        if action_value_record is not None:
            formation.debts, value_history = self._advanced_action_values(
                action_value_record, boundary
            )
        consumed = []
        terminal = None
        for pending in due_group:
            spec = self._sources_by_key.get(pending.source)
            if spec is None or spec.due_projector is None:
                raise K0ProfileError("pending due has no selected Event source")
            selections = self._fixed_due_selections.get(spec.key, ())
            if len(selections) != len(spec.due_fixed_individual_ports):
                raise K0ProfileError("fixed due individual binding was not sealed at Start")
            for selection, port in zip(selections, spec.due_fixed_individual_ports, strict=True):
                binding = self._binding_for(selection.individual)
                if (
                    selection.name != port.name
                    or selection.individual.family != port.family
                    or binding is None
                    or binding.owner != selection.owner
                ):
                    raise K0ProfileError("fixed due individual binding is no longer current")
            selected_pending = replace(pending, selected_individuals=selections)
            read_owners = spec.read_owners + tuple(item.owner for item in selections)
            views = candidate.owner_views(read_owners)
            by_owner = {view.owner: view for view in views}
            for selection in selections:
                view = by_owner[selection.owner]
                by_owner[selection.owner] = _K0OwnerView(view.owner, view.view, selection.name)
            domain_views, domain_writes = self._actor_domain_views(
                candidate,
                spec.actor_domains,
                formation.actor_bindings,
            )
            expected_writes = tuple(sorted((*spec.contribution_owners, *domain_writes)))
            object_views = self._object_domain_views(
                candidate, spec.read_object_domains, formation.individual_bindings
            )
            projection = spec.due_projector.project_due(
                selected_pending,
                boundary,
                tuple(by_owner[owner] for owner in read_owners) + domain_views + object_views,
            )
            _validate_admission_projection(
                projection,
                spec.evidence_type,
                spec.participants_type,
                spec.binding_keys,
                spec.binding_types,
            )
            if spec.read_object_domains and (
                getattr(projection.evidence, "object_views", None) != object_views
                or getattr(projection.participants, "objects", None)
                != tuple((view.participant, view.individual_ref) for view in object_views)
            ):
                raise K0ProfileError(
                    "due Object domain projection changed its actual binding basis"
                )
            occurrence_ref = candidate.allocate_occurrence()
            rule_input = _K0InMemoryRuleInput(
                occurrence_ref,
                spec.key,
                projection.evidence,
                projection.participants,
                projection.bindings,
                None,
                boundary,
                selected_pending,
            )
            evaluation = _evaluate_source(spec, rule_input)
            result = evaluation.result
            _validate_rule_result(
                candidate.owners,
                result,
                (),
                expected_writes,
                expected_actor_product=spec.actor_product,
            )
            envelope = evaluation.envelope
            if type(envelope) is not spec.envelope_type:
                raise K0ProfileError("temporal envelope has the wrong exact type")
            if spec.read_object_domains and getattr(envelope, "objects", None) != tuple(
                (view.participant, view.individual_ref) for view in object_views
            ):
                raise K0ProfileError("due envelope changed its actual Object domain members")
            self._stage_products(candidate, formation, result, occurrence_ref, boundary)
            _apply_contributions(candidate, occurrence_ref, result, expected_writes)
            candidate.validate_cross_owner_invariants()
            step_occurrences = [
                _K0InMemoryOccurrence(
                    occurrence_ref,
                    K0OccurrenceFamily.EVENT,
                    spec.key,
                    spec.event_type,
                    _K0DueFormation(pending.key, pending.at),
                    projection.participants,
                    _IN_MEMORY_COORDINATE,
                    envelope,
                    tuple(
                        _K0SelectedOwner(item.name, item.individual, item.owner)
                        for item in selections
                    ),
                )
            ]
            self._settle_causal_waves(candidate, step_occurrences, formation)
            occurrences.extend(step_occurrences)
            consumed.append(pending)
            consumed_keys = {item.key for item in consumed}
            terminal = self._terminal_at(
                candidate,
                "due",
                boundary,
                occurrence_ref,
                tuple(item for item in self._pending_due if item.key not in consumed_keys),
                self._tape + tuple(occurrences),
            )
            if terminal is not None:
                break
        if len(occurrences) > self._profile.max_events:
            raise K0ProfileError("temporal settlement exceeded the event bound")
        states = candidate._snapshot_states()
        tape = self._tape + tuple(occurrences)
        cursor = _K0OccurrenceCursor(self._cursor.next_value + len(occurrences))
        consumed_keys = tuple(item.key for item in consumed)
        pending_after = tuple(item for item in self._pending_due if item.key not in consumed_keys)
        if len(pending_after) != len(self._pending_due) - len(consumed_keys):
            raise K0ProfileError("temporal dues were not consumed exactly once")
        plans = {plan.capability_ref: plan for plan in policy.periodic_plans}
        renewed = []
        for item in () if terminal is not None else consumed:
            if type(item.key) is not _K0PeriodicDueKey:
                continue
            plan = plans.get(item.key.plan)
            next_ordinal = item.key.ordinal + 1
            if plan is None:
                raise K0ProfileError("periodic due lost its selected plan")
            if plan.max_occurrences is None or next_ordinal < plan.max_occurrences:
                renewed.append(
                    _K0PendingDue(
                        _K0PeriodicDueKey(plan.capability_ref, next_ordinal),
                        _K0FixedTime(item.at.ordinal + plan.interval),
                        plan.source,
                        plan.subject,
                    )
                )
        pending_after += tuple(renewed)
        if terminal is not None:
            pending_after = ()
        if len(pending_after) > policy.max_pending or len(
            {item.source for item in pending_after}
        ) != len(pending_after):
            raise K0ProfileError("renewed periodic dues exceed the temporal binding")
        record = _K0AdvanceRecord(
            interval, tape_before, len(tape), consumed_keys, policy.capability_ref
        )
        receipt = _K0TemporalPublished(interval, tuple(occurrences))
        history = self._advance_history + (record,)
        if action_value_record is not None:
            value_history = self._action_value_history + (
                replace(action_value_record, debt_after=formation.debts),
            )
        elif self._pre_due_phase is not None and self._profile.action_value_policy is not None:
            value_history += (
                _K0ActionValueRecord(boundary, "due", None, debt_before, formation.debts),
            )
        (
            self._topology,
            self._states,
            self._cursor,
            self._tape,
            self._time,
            self._pending_due,
            self._advance_history,
            self._terminal,
            self._action_opportunity,
            self._individual_bindings,
            self._actor_bindings,
            self._next_individual,
            self._action_seats,
            self._action_values,
            self._action_value_history,
            self._pre_due_phase,
            self._same_time_actions,
        ) = (
            candidate.topology,
            states,
            cursor,
            tape,
            boundary,
            pending_after,
            history,
            terminal,
            None if terminal is not None else self._action_opportunity,
            formation.individual_bindings,
            formation.actor_bindings,
            formation.next_ordinal,
            formation.seats,
            formation.debts,
            value_history,
            None,
            0,
        )
        return receipt

    def _settle_causal_waves(
        self,
        candidate: _K0OwnerStateCandidate,
        occurrences: list[_K0InMemoryOccurrence],
        formation: _K0FormationCandidate,
    ) -> None:
        if self._profile.ordered_policy is not None:
            self._settle_ordered_microsteps(candidate, occurrences, formation)
            return
        frontier = (occurrences[0],)
        depth = 0
        while frontier:
            wave_actor_bindings = formation.actor_bindings
            planned: list[_K0PlannedActivation] = []
            seen: set[tuple[object, K0OccurrenceRef, str]] = set()
            for trigger in frontier:
                matching_laws = self._laws_by_event.get(trigger.classification, ())
                if not matching_laws:
                    continue
                states = candidate._snapshot_states()
                directory = _K0OwnerStateDirectory(candidate.topology, states)
                for law in matching_laws:
                    views = _build_candidate_owner_views(
                        directory, law.read_owners
                    )
                    domain_views, _ = self._actor_domain_views(
                        candidate, law.actor_domains, wave_actor_bindings
                    )
                    views += domain_views
                    activations = law.activation_projector.project(trigger, views)
                    if type(activations) is not tuple:
                        raise K0ProfileError("in-memory activations must be an exact tuple")
                    if len(activations) > law.max_activations:
                        raise K0ProfileError("in-memory activation exceeded the law bound")
                    for activation in activations:
                        if type(activation) is not _K0Activation:
                            raise K0ProfileError("in-memory activation has the wrong carrier")
                        if type(activation.binding_key) is not str or not activation.binding_key:
                            raise K0ProfileError("in-memory activation binding key is malformed")
                        if not isinstance(activation.participants, _K0ClosedParticipants):
                            raise K0ProfileError("in-memory activation participants are not closed")
                        if type(activation.bindings) is not tuple or any(
                            not isinstance(item, _K0SealedBinding) for item in activation.bindings
                        ):
                            raise K0ProfileError("in-memory activation bindings are not closed")
                        if not isinstance(activation.evidence, _K0SealedEvidence):
                            raise K0ProfileError("in-memory activation evidence is not closed")
                        activation.evidence.validate_for_k0()
                        activation.participants.validate_for_k0()
                        for binding in activation.bindings:
                            binding.validate_for_k0()
                        key = (law.key, trigger.occurrence, activation.binding_key)
                        if key in seen:
                            raise K0ProfileError("in-memory activation is duplicated")
                        seen.add(key)
                        planned.append(_K0PlannedActivation(law, trigger, activation))
            if not planned:
                return
            depth += 1
            if depth > self._profile.max_waves:
                raise K0ProfileError("in-memory settlement exceeded the wave bound")
            counts: dict[object, int] = {}
            for item in planned:
                counts[item.law.key] = counts.get(item.law.key, 0) + 1
            for key, count in counts.items():
                if count > self._laws_by_key[key].max_activations:
                    raise K0ProfileError("in-memory activation exceeded the law bound")
            coordinate = _K0OccurrenceCoordinate(None, depth)
            wave: list[_K0InMemoryOccurrence] = []
            proposals: list[tuple[_K0SameWaveProposal, tuple[K0OwnerKey, ...]]] = []
            wave_priors: dict[K0OwnerKey, object] = {}
            wave_writes: dict[K0OwnerKey, list[_K0OccurrenceContribution]] = {}
            policy = self._profile.same_wave_policy
            prior_state = (
                candidate.owner_views((policy.owner,))[0].view if policy is not None else None
            )
            for item in planned:
                law = item.law
                activation = item.activation
                target = self._sources_by_key.get(law.resulting_source)
                if target is None or target.occurrence_family is not K0OccurrenceFamily.EVENT:
                    raise K0ProfileError("in-memory activation names no declared Event source")
                if (
                    type(activation.evidence) is not target.evidence_type
                    or type(activation.participants) is not target.participants_type
                ):
                    raise K0ProfileError("in-memory activation does not match its Event source")
                if tuple(binding.key for binding in activation.bindings) != (
                    target.binding_keys
                ) or tuple(type(binding) for binding in activation.bindings) != (
                    target.binding_types
                ):
                    raise K0ProfileError("in-memory activation bindings do not match")
                event_ref = candidate.allocate_occurrence()
                rule_input = _K0InMemoryRuleInput(
                    event_ref,
                    target.key,
                    activation.evidence,
                    activation.participants,
                    activation.bindings,
                    item.trigger.occurrence,
                )
                evaluation = _evaluate_source(target, rule_input)
                result = evaluation.result
                if result.local_output_requests:
                    raise K0ProfileError("this slice does not allow local output requests")
                _, domain_writes = self._actor_domain_views(
                    candidate, target.actor_domains, wave_actor_bindings
                )
                expected_writes = tuple(sorted((*target.contribution_owners, *domain_writes)))
                _validate_rule_result(
                    candidate.owners,
                    result,
                    (),
                    expected_writes,
                    expected_form_families=()
                    if target.form_owner_family is None
                    else (target.form_owner_family,),
                    expected_actor_product=target.actor_product,
                )
                envelope = evaluation.envelope
                if type(envelope) is not target.envelope_type:
                    raise K0ProfileError("in-memory Event envelope has the wrong exact type")
                self._stage_products(candidate, formation, result, event_ref, candidate.time)
                if policy is None:
                    _record_unselected_wave_writes(
                        candidate,
                        event_ref,
                        result,
                        expected_writes,
                        wave_priors,
                        wave_writes,
                    )
                    _apply_contributions(candidate, event_ref, result, expected_writes)
                    candidate.validate_cross_owner_invariants()
                else:
                    proposals.append(
                        (
                            _K0SameWaveProposal(target.key, rule_input, result),
                            expected_writes,
                        )
                    )
                wave.append(
                    _K0InMemoryOccurrence(
                        event_ref,
                        target.occurrence_family,
                        target.key,
                        target.event_type,
                        _K0CausalFormation(item.trigger.occurrence, law.key),
                        activation.participants,
                        coordinate,
                        envelope,
                    )
                )
            if policy is not None:
                selected = tuple(
                    proposal for proposal, owners in proposals if policy.owner in owners
                )
                if any(item.source not in policy.sources for item in selected):
                    raise K0ProfileError("same-wave policy saw an undeclared owner write")
                if len(selected) == 1:
                    only = selected[0]
                    _apply_contributions(
                        candidate,
                        only.rule_input.occurrence,
                        only.result,
                        (policy.owner,),
                    )
                elif len(selected) == 2 and set(item.source for item in selected) == set(
                    policy.sources
                ):
                    trigger = selected[0].rule_input.trigger
                    if (
                        trigger is None
                        or any(item.rule_input.trigger != trigger for item in selected)
                        or len({item.rule_input.occurrence for item in selected}) != 2
                    ):
                        raise K0ProfileError("same-wave proposals lack one exact trigger/ref set")
                    merged = policy.merge(prior_state, selected)
                    candidate.apply_verified_same_wave_state(policy.owner, merged)
                elif selected:
                    raise K0ProfileError("same-wave policy cannot cover this wave")
                for proposal, owners in proposals:
                    remaining = tuple(owner for owner in owners if owner != policy.owner)
                    if remaining:
                        _record_unselected_wave_writes(
                            candidate,
                            proposal.rule_input.occurrence,
                            proposal.result,
                            remaining,
                            wave_priors,
                            wave_writes,
                        )
                        _apply_contributions(
                            candidate, proposal.rule_input.occurrence, proposal.result, remaining
                        )
                candidate.validate_cross_owner_invariants()
            _prove_unselected_wave_effects(candidate, candidate.owners, wave_priors, wave_writes)
            occurrences.extend(wave)
            if len(occurrences) > self._profile.max_events:
                raise K0ProfileError("in-memory settlement exceeded the event bound")
            frontier = tuple(wave)

    def _settle_ordered_microsteps(
        self,
        candidate: _K0OwnerStateCandidate,
        occurrences: list[_K0InMemoryOccurrence],
        formation: _K0FormationCandidate,
    ) -> None:
        policy = self._profile.ordered_policy
        trigger = occurrences[0]
        if policy is None or trigger.source != policy.trigger_source:
            raise K0ProfileError("ordered settlement lacks its exact Action trigger")
        previous: K0OccurrenceRef | None = None
        for ordinal, step in enumerate(policy.steps, start=1):
            law = self._laws_by_key[step.law_key]
            views = candidate.owner_views(law.read_owners)
            domain_views, _ = self._actor_domain_views(
                candidate, law.actor_domains, formation.actor_bindings
            )
            views += domain_views
            activations = law.activation_projector.project(trigger, views)
            if type(activations) is not tuple or len(activations) > 1:
                raise K0ProfileError("ordered step projected malformed activations")
            if not activations:
                if step.required:
                    raise K0ProfileError("required ordered step did not activate")
                continue
            activation = activations[0]
            target = self._sources_by_key.get(step.source)
            if (
                type(activation) is not _K0Activation
                or type(activation.binding_key) is not str
                or not activation.binding_key
                or not isinstance(activation.evidence, _K0SealedEvidence)
                or not isinstance(activation.participants, _K0ClosedParticipants)
                or type(activation.bindings) is not tuple
                or any(not isinstance(binding, _K0SealedBinding) for binding in activation.bindings)
                or target is None
                or type(activation.evidence) is not target.evidence_type
                or type(activation.participants) is not target.participants_type
                or tuple(binding.key for binding in activation.bindings) != target.binding_keys
                or tuple(type(binding) for binding in activation.bindings) != target.binding_types
            ):
                raise K0ProfileError("ordered step activation violates its Event source")
            activation.evidence.validate_for_k0()
            activation.participants.validate_for_k0()
            for binding in activation.bindings:
                binding.validate_for_k0()
            policy.validate_current_basis(step, activation, views)
            event_ref = candidate.allocate_occurrence()
            rule_input = _K0InMemoryRuleInput(
                event_ref,
                target.key,
                activation.evidence,
                activation.participants,
                activation.bindings,
                trigger.occurrence,
            )
            evaluation = _evaluate_source(target, rule_input)
            result = evaluation.result
            if result.local_output_requests:
                raise K0ProfileError("ordered step cannot request local output")
            _, domain_writes = self._actor_domain_views(
                candidate, target.actor_domains, formation.actor_bindings
            )
            expected_writes = tuple(sorted((*target.contribution_owners, *domain_writes)))
            _validate_rule_result(
                candidate.owners,
                result,
                (),
                expected_writes,
                expected_form_families=()
                if target.form_owner_family is None
                else (target.form_owner_family,),
                expected_actor_product=target.actor_product,
            )
            envelope = evaluation.envelope
            if type(envelope) is not target.envelope_type:
                raise K0ProfileError("ordered step Event envelope has the wrong type")
            self._stage_products(candidate, formation, result, event_ref, candidate.time)
            _apply_contributions(candidate, event_ref, result, expected_writes)
            candidate.validate_cross_owner_invariants()
            occurrences.append(
                _K0InMemoryOccurrence(
                    event_ref,
                    target.occurrence_family,
                    target.key,
                    target.event_type,
                    _K0OrderedFormation(
                        trigger.occurrence,
                        previous,
                        law.key,
                        policy.capability_ref,
                        ordinal,
                    ),
                    activation.participants,
                    _K0OccurrenceCoordinate(None, 1),
                    envelope,
                )
            )
            previous = event_ref
            if len(occurrences) > self._profile.max_events:
                raise K0ProfileError("ordered settlement exceeded the Event bound")


def _record_unselected_wave_writes(
    candidate: _K0OwnerStateCandidate,
    occurrence: K0OccurrenceRef,
    result: K0RuleResult,
    contribution_owners: tuple[K0OwnerKey, ...],
    priors: dict[K0OwnerKey, object],
    writes: dict[K0OwnerKey, list[_K0OccurrenceContribution]],
) -> None:
    for owner_key in contribution_owners:
        owned = tuple(
            _K0OccurrenceContribution(occurrence, item, ())
            for item in result.contributions
            if item.owner == owner_key
        )
        if owned:
            if owner_key not in priors:
                priors[owner_key] = candidate.isolated_owner_state(owner_key)
            writes.setdefault(owner_key, []).extend(owned)


def _prove_unselected_wave_effects(
    candidate: _K0OwnerStateCandidate,
    owners: tuple[_K0Owner, ...],
    priors: dict[K0OwnerKey, object],
    writes: dict[K0OwnerKey, list[_K0OccurrenceContribution]],
) -> None:
    for owner in owners:
        contributions = tuple(writes.get(owner.key, ()))
        if len({item.occurrence for item in contributions}) < 2:
            continue
        if not isinstance(owner, _K0SameWaveEffectProofOwner):
            raise K0ProfileError("same-wave owner writes lack an effect-preservation proof")
        result = owner.prove_same_wave_effects(
            priors[owner.key], contributions, candidate.isolated_owner_state(owner.key)
        )
        if result is not None:
            raise K0ProfileError("same-wave owner proof returned a value")


def _apply_contributions(
    candidate: _K0OwnerStateCandidate,
    occurrence: K0OccurrenceRef,
    result: K0RuleResult,
    contribution_owners: tuple[K0OwnerKey, ...],
) -> None:
    for owner_key in tuple(sorted(contribution_owners)):
        owned = tuple(
            _K0OccurrenceContribution(occurrence, item, ())
            for item in result.contributions
            if item.owner == owner_key
        )
        if owned:
            candidate.apply_owner_contributions(owner_key, owned)
