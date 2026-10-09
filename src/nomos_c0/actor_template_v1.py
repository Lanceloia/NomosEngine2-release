"""Checked finite Actor templates; instances never register new executable rules."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import get_type_hints

from nomos_kernel._dynamic_actor_abi import _K0ActorKind
from nomos_kernel._owner_abi import _K0CapabilityRef

from .author_contract_v1 import C0LawError
from .candidate_input_v1 import C0CandidateCheck, compile_candidate_check
from .checked_value_binding_v1 import C0CheckedValueIR, C0ValueBackend
from .compile_budget_v1 import COMPILE_BUDGET
from .composable_action_v1 import C0SelfActorPorts
from .composable_value_v1 import C0ValuePorts, _complete_value_fields, compile_value_program
from .control_binding_v1 import _C0ActionCostProjector, _C0ActionValueProjector
from .control_ir_v1 import C0AppraisalProfileIR, C0AppraisalRuleIR
from .expression_read_authority_v1 import check_expression_reads
from .finite_appraisal_v1 import C0AppraisalRule, C0FiniteAppraisalProfile, compile_finite_appraisal
from .private_actor_binding_v1 import (
    C0PrivateActorBinding,
    C0PrivateActorBindingIR,
    bind_private_bindings,
    capture_private_bindings,
    check_private_bindings,
    compile_private_binding,
)
from .seat_offers_v0 import C0SeatOffer
from .visibility_binding_v1 import _bind_candidate_check
from .visibility_ir_v1 import C0CandidateCheckIR


@dataclass(frozen=True)
class C0ActorOfferIR:
    entry: str
    label: str
    value: C0CheckedValueIR
    private_actor_fields: tuple[C0PrivateActorBindingIR, ...] = ()
    candidate_check: C0CandidateCheckIR | None = None


@dataclass(frozen=True)
class C0ActorTemplateIR:
    kind: str
    entries: tuple[str, ...]
    read_paths: tuple[str, ...]
    offers: tuple[C0ActorOfferIR, ...]
    projection: C0CheckedValueIR
    costs: tuple[tuple[str, C0CheckedValueIR], ...]
    first_debt: int
    tie_priority: int
    mode: str
    appraisal: C0AppraisalProfileIR | None


def _local_ports(kind, outputs, pure_definitions=()):
    paths = frozenset(f"actor.{path}" for path in kind.seat_readable_paths)
    fields = _complete_value_fields(kind.factory.state_type)
    return C0ValuePorts(
        roots={"actor": kind.factory.state_type},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs=outputs,
        pure_definitions=pure_definitions,
    )


def _value(outputs, guard, ports):
    return compile_value_program(
        json.dumps({"schema": "c0.value.v1", "bindings": [], "guard": guard, "outputs": outputs}),
        ports,
        admission_outputs=frozenset(outputs),
    )


def _private_actor_fields(raw, action):
    if type(raw) is not dict:
        raise C0LawError("Actor offer private bindings must name selected singleton roles")
    ports = {port.name: port for port in action.ports.participants}
    result = []
    for name, row in raw.items():
        port = ports.get(name)
        if (
            port is None
            or port.selector != "closed_domain"
            or len(port.members) != 1
            or type(row) is not dict
            or set(row) not in ({"fixed_actor", "private"}, {"fixed_actor", "private", "when"})
            or row["private"] is not True
            or row["fixed_actor"] != port.members[0][0]
        ):
            raise C0LawError("Actor offer private binding requires an exact static singleton")
        result.append(compile_private_binding(row, port, action.ports))
    return tuple(sorted(result, key=lambda binding: binding.payload_field))


def _check_private_actor_fields(fields, action):
    check_private_bindings(fields, action.ports)


def capture_actor_templates(
    raws, kinds, actions, backend, pure_definitions=(), candidate_inputs=(), action_templates=()
):
    """Compile-only capture; no author AST survives into instance execution."""
    result = []
    for raw in raws:
        if type(raw) is not dict or set(raw) != {
            "kind",
            "entries",
            "read",
            "offers",
            "tempo",
            "eligible",
            "costs",
            "first_debt",
            "tie_priority",
            "controller",
        }:
            raise C0LawError("Actor template has missing or unknown fields")
        kind = kinds[raw["kind"]]
        entries, paths = raw["entries"], raw["read"]
        if (
            type(entries) is not list
            or not entries
            or len(entries) > 64
            or any(type(entry) is not str or entry not in actions for entry in entries)
            or len(set(entries)) != len(entries)
            or any(
                type(actions[entry].actor_owner) is not C0SelfActorPorts
                or actions[entry].actor_owner.family != kind.symbol
                for entry in entries
            )
            or type(paths) is not list
            or any(type(path) is not str for path in paths)
            or len(set(paths)) != len(paths)
            or not set(paths) <= {f"actor.{path}" for path in kind.seat_readable_paths}
            or type(raw["costs"]) is not dict
            or set(raw["costs"]) != set(entries)
        ):
            raise C0LawError("Actor template crosses its self or local read authority")
        projection = _value(
            {"tempo": raw["tempo"], "eligible": raw["eligible"]},
            {"const": True},
            _local_ports(kind, {"tempo": int, "eligible": bool}, pure_definitions),
        )
        costs = tuple(
            (
                entry,
                backend.capture(
                    _value(
                        {"cost": raw["costs"][entry]},
                        {"const": True},
                        replace(actions[entry].value._ports, outputs={"cost": int}),
                    )
                ),
            )
            for entry in entries
        )
        offers = []
        if type(raw["offers"]) is not list or len(raw["offers"]) > COMPILE_BUDGET.finite_offers:
            raise C0LawError("Actor template offers are not finite")
        for index, offer in enumerate(raw["offers"]):
            if (
                type(offer) is not dict
                or not {"entry", "label", "when", "payload"} <= set(offer)
                or set(offer)
                - {"entry", "label", "when", "payload", "for_each_participants", "availability"}
                or type(offer["entry"]) is not str
                or offer["entry"] not in entries
                or type(offer["label"]) is not str
                or not offer["label"]
                or type(offer["payload"]) is not dict
            ):
                raise C0LawError("Actor template offer is malformed")
            action = actions[offer["entry"]]
            private = _private_actor_fields(offer.get("for_each_participants", {}), action)
            payload = get_type_hints(action.payload_type)
            payload.pop(action.payload_actor_field)
            for binding in private:
                payload.pop(binding.payload_field)
            if (
                "offered" in payload
                or set(payload) != set(offer["payload"])
                or any(annotation not in (str, int, bool) for annotation in payload.values())
            ):
                raise C0LawError("Actor local offer needs exact finite non-identity fields")
            value = _value(
                {**offer["payload"], "offered": {"const": True}},
                offer["when"],
                _local_ports(kind, {**payload, "offered": bool}, pure_definitions),
            )
            check = None
            if "availability" in offer:
                check = compile_candidate_check(
                    offer["availability"],
                    candidate_inputs,
                    dict(action_templates)[offer["entry"]],
                    action.ports,
                    offer["entry"],
                )
                check = C0CandidateCheckIR(
                    index, check.input_symbol, check.entry, backend.capture(check.value)
                )
            offers.append(
                C0ActorOfferIR(
                    offer["entry"],
                    offer["label"],
                    backend.capture(value),
                    capture_private_bindings(private, backend),
                    check,
                )
            )
        controller = raw["controller"]
        if type(controller) is not dict or controller.get("mode") not in (
            "human_prompt",
            "finite_appraisal",
        ):
            raise C0LawError("Actor template requires an explicit controller")
        mode = controller["mode"]
        expected = {"mode"} if mode == "human_prompt" else {"mode", "profile"}
        if set(controller) != expected:
            raise C0LawError("Actor template controller has unknown fields")
        appraisal = None
        if mode == "finite_appraisal":
            profile = compile_finite_appraisal(
                controller["profile"],
                seat=kind.symbol,
                actor_type=kind.factory.state_type,
                readable_paths=frozenset(f"actor.{path}" for path in kind.seat_readable_paths),
                entries=tuple(entries),
                actions=actions,
                pure_definitions=pure_definitions,
            )
            appraisal = C0AppraisalProfileIR(
                profile.name,
                profile.seat,
                profile.fallback_entry,
                profile.tie_order,
                tuple(
                    C0AppraisalRuleIR(
                        rule.entry,
                        rule.mode,
                        None if rule.value is None else backend.capture(rule.value),
                    )
                    for rule in profile.rules
                ),
            )
        result.append(
            C0ActorTemplateIR(
                kind.symbol,
                tuple(entries),
                tuple(paths),
                tuple(offers),
                backend.capture(projection),
                costs,
                raw["first_debt"],
                raw["tie_priority"],
                mode,
                appraisal,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class C0BoundActorOffer:
    entry: str
    label: str
    value: object
    private_actor_fields: tuple[C0PrivateActorBinding, ...]
    candidate_check: C0CandidateCheck | None

    def project(self, actor):
        outputs = self.value.evaluate_admission_outputs({"actor": actor})
        if outputs is None:
            return None
        return C0SeatOffer(
            self.entry,
            self.label,
            tuple((key, value) for key, value in outputs.items() if key != "offered"),
        )


@dataclass(frozen=True)
class C0BoundActorTemplate:
    ir: C0ActorTemplateIR
    kind: _K0ActorKind
    offers: tuple[C0BoundActorOffer, ...]
    costs: tuple[tuple[str, _C0ActionCostProjector], ...]
    appraisal: C0FiniteAppraisalProfile | None

    def project_offers(self, actor):
        result = []
        for declaration in self.offers:
            offered = declaration.project(actor)
            if offered is not None and offered not in result:
                result.append(offered)
        return tuple(result)


def bind_actor_templates(irs, world):
    backend = C0ValueBackend(world.layout.owners.record_layout, world.layout.owners)
    kinds = {kind.symbol: kind for kind in world.layout.owners.actor_kinds}
    actions = dict(world.actions)
    result = []
    if tuple(ir.kind for ir in irs) != world.ir.selected_actor_kinds:
        raise C0LawError("Actor templates do not cover the exact selected kinds")
    for ir in irs:
        kind = kinds[ir.kind]
        if (
            type(ir) is not C0ActorTemplateIR
            or not ir.entries
            or len(set(ir.entries)) != len(ir.entries)
            or any(
                entry not in actions
                or type(actions[entry].actor_owner) is not C0SelfActorPorts
                or actions[entry].actor_owner.family != ir.kind
                for entry in ir.entries
            )
            or not set(ir.read_paths) <= {f"actor.{path}" for path in kind.seat_readable_paths}
            or tuple(entry for entry, _ in ir.costs) != ir.entries
            or ir.mode not in ("human_prompt", "finite_appraisal")
            or (ir.appraisal is not None) != (ir.mode == "finite_appraisal")
            or type(ir.offers) is not tuple
            or len(ir.offers) > COMPILE_BUDGET.finite_offers
            or type(ir.first_debt) is not int
            or not 0 < ir.first_debt <= (1 << 63) - 1
            or type(ir.tie_priority) is not int
            or ir.tie_priority < 0
        ):
            raise C0LawError("checked Actor template has incompatible entries or authority")
        projection = backend.bind(ir.projection)
        expected = _local_ports(
            kind, {"tempo": int, "eligible": bool}, projection._ports.pure_definitions
        )
        if projection._ports != expected or projection._admission_outputs != frozenset(
            expected.outputs
        ):
            raise C0LawError("Actor tempo projection has foreign roots or outputs")
        costs = []
        for entry, value in ir.costs:
            cost, action = backend.bind(value), actions[entry]
            if cost._ports != replace(action.value._ports, outputs={"cost": int}) or (
                cost._admission_outputs != frozenset({"cost"})
            ):
                raise C0LawError("Actor cost differs from its compiled Action basis")
            costs.append(
                (
                    entry,
                    _C0ActionCostProjector(
                        action._cost_basis(),
                        cost,
                        _K0CapabilityRef(f"c0.actor_cost.{ir.kind}.{entry}.v1"),
                    ),
                )
            )
        offers = []
        private_by_entry = {}
        for index, offer in enumerate(ir.offers):
            if (
                type(offer) is not C0ActorOfferIR
                or offer.entry not in ir.entries
                or type(offer.label) is not str
                or not offer.label
            ):
                raise C0LawError("Actor offer has a foreign entry")
            value = backend.bind(offer.value)
            action = actions[offer.entry]
            private = bind_private_bindings(offer.private_actor_fields, backend)
            _check_private_actor_fields(private, action)
            if private_by_entry.setdefault(offer.entry, private) != private:
                raise C0LawError("Actor offer entry has ambiguous private bindings")
            payload = get_type_hints(action.payload_type)
            payload.pop(action.payload_actor_field)
            for binding in private:
                payload.pop(binding.payload_field)
            payload["offered"] = bool
            if (
                any(annotation not in (str, int, bool) for field, annotation in payload.items())
                or value._ports != _local_ports(kind, payload, value._ports.pure_definitions)
                or (value._admission_outputs != frozenset(payload))
            ):
                raise C0LawError("Actor offer exceeds its local projection port")
            check_expression_reads(
                (value.guard_ir.expression, value._tree["outputs"]),
                value._ports,
                frozenset({"actor"}),
            )
            check = offer.candidate_check
            if check is not None:
                if (
                    type(check) is not C0CandidateCheckIR
                    or type(check.index) is not int
                    or check.index != index
                    or check.entry != offer.entry
                    or type(check.input_symbol) is not str
                    or not check.input_symbol
                ):
                    raise C0LawError("Actor candidate input differs from its offer Action")
                _, check = _bind_candidate_check(check, backend, world)
            offers.append(C0BoundActorOffer(offer.entry, offer.label, value, private, check))
        appraisal = None
        if ir.appraisal is not None:
            profile = ir.appraisal
            if (
                profile.seat != ir.kind
                or profile.fallback_entry not in ir.entries
                or set(profile.tie_order) != set(ir.entries)
                or len(profile.tie_order) != len(ir.entries)
                or len(profile.rules) != len(ir.entries)
                or {rule.entry for rule in profile.rules} != set(ir.entries)
            ):
                raise C0LawError("Actor appraisal does not cover its template")
            rules = []
            for rule in profile.rules:
                value = None if rule.value is None else backend.bind(rule.value)
                if rule.mode not in ("score", "ignore", "default") or (
                    (value is not None) != (rule.mode == "score")
                ):
                    raise C0LawError("Actor appraisal rule is malformed")
                if value is not None:
                    action = actions[rule.entry]
                    if (
                        value._ports.roots
                        != {"actor": kind.factory.state_type, "payload": action.payload_type}
                        or not value._ports.readable_paths
                        <= (
                            {f"actor.{path}" for path in kind.seat_readable_paths}
                            | {f"payload.{name}" for name in get_type_hints(action.payload_type)}
                        )
                        or value._ports.outputs != {"score": int}
                        or value._admission_outputs != frozenset({"score"})
                        or value._ports.admission_readable_paths != value._ports.readable_paths
                        or value._ports.writable_fields
                        or value.effects
                    ):
                        raise C0LawError("Actor appraisal score exceeds its local basis")
                rules.append(C0AppraisalRule(rule.entry, rule.mode, value))
            if (
                next(rule for rule in rules if rule.entry == profile.fallback_entry).mode
                != "default"
            ):
                raise C0LawError("Actor appraisal fallback is not a world default Action")
            appraisal = C0FiniteAppraisalProfile(
                profile.name, profile.seat, profile.fallback_entry, profile.tie_order, tuple(rules)
            )
        k0_kind = _K0ActorKind(
            ir.kind,
            kind.max_instances,
            kind.factory.state_type,
            kind.factory,
            tuple(actions[entry].source_key for entry in ir.entries),
            _C0ActionValueProjector(projection, _K0CapabilityRef(f"c0.actor_tempo.{ir.kind}.v1")),
            ir.first_debt,
            ir.tie_priority,
            _K0CapabilityRef(f"c0.actor_control.{ir.kind}.v1"),
        )
        result.append(C0BoundActorTemplate(ir, k0_kind, tuple(offers), tuple(costs), appraisal))
    selected_sources = {entry for ir in irs for entry in ir.entries}
    if any(
        type(action.actor_owner) is C0SelfActorPorts and name not in selected_sources
        for name, action in world.actions
    ):
        raise C0LawError("instance-relative Action lacks an Actor control template")
    return tuple(result)
