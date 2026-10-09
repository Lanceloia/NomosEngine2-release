"""Author-declared, read-only forecasts attached to current finite seat offers."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .composable_value_v1 import C0ValuePorts, C0ValueProgram, C0ValueStateError
from .seat_offers_v0 import C0SeatOffer


@dataclass(frozen=True)
class C0SeatOfferPreviewPorts:
    symbol: str
    scene_owner: str
    actor: str
    action_template: str
    collection_field: str
    current_field: str
    candidate_origin_field: str
    candidate_type: type
    candidate_key: str
    offer_payload_key: str
    object_root: str
    object_kind: str
    value_ports: C0ValuePorts
    max_candidates: int


@dataclass(frozen=True)
class C0SeatOfferPreview:
    entry: str
    ports: C0SeatOfferPreviewPorts
    value: C0ValueProgram

    def project(
        self, scene: object, actor: object, selected_object: object, offer: C0SeatOffer
    ) -> C0SeatOffer:
        current = getattr(actor, self.ports.current_field)
        known = getattr(actor, self.ports.collection_field)
        if (
            type(current) is not str
            or type(known) is not tuple
            or len(known) > self.ports.max_candidates
        ):
            raise C0ValueStateError("offer preview candidates have a foreign nominal shape")
        key = dict(offer.payload).get(self.ports.offer_payload_key)
        if offer.entry != self.entry or type(key) is not str:
            raise C0ValueStateError("offer preview has a foreign entry or payload")
        candidates = tuple(
            item
            for item in known
            if type(item) is self.ports.candidate_type
            and getattr(item, self.ports.candidate_origin_field) == current
            and getattr(item, self.ports.candidate_key) == key
        )
        if len(candidates) != 1 or any(
            type(item) is not self.ports.candidate_type for item in known
        ):
            raise C0ValueStateError("offer preview lacks one Actor-local candidate")
        result = self.value.evaluate_admission_outputs(
            {
                "scene": scene,
                "actor": actor,
                "candidate": candidates[0],
                self.ports.object_root: selected_object,
            }
        )
        return replace(offer, preview=() if result is None else tuple(sorted(result.items())))
