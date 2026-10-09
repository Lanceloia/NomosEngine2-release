"""Expand explicit offer reuse without sharing seat capabilities."""

from copy import deepcopy

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame, C0SourceContext, DocumentPath
from .compile_budget_v1 import COMPILE_BUDGET


def _check_offer(raw: object) -> None:
    if type(raw) is not dict:
        raise C0LawError("offer set needs ordinary offer declarations")
    if "use_offer_set" in raw:
        raise C0LawError("offer sets cannot contain recursive references")
    entry = "entry_family" if "entry_family" in raw else "entry"
    expected = {entry, "label", "when", "payload"}
    if "fixed_participants" in raw:
        expected.add("fixed_participants")
    elif "for_each_participants" in raw:
        expected.update(("for_each_participants", "visible_when"))
        if "for_each" in raw:
            expected.add("for_each")
    elif "for_each_object" in raw:
        expected.update(("for_each_object", "visible_when"))
    elif "for_each" in raw:
        expected.add("for_each")
    # Source checks these fields before passing the offer to compile_seat_offers.
    expected.update({"availability", "operation"} & set(raw))
    if set(raw) != expected:
        raise C0LawError("offer set offer has missing or unknown fields")


def expand_offer_sets(
    source: dict, source_context: C0SourceContext | None = None
) -> tuple[dict, dict[tuple[int, int], tuple[DocumentPath, tuple[C0OriginFrame, ...]]]]:
    """Return detached Source data and absolute pre-family offer aliases.

    Keys use the original seat index and expanded offer index. Alias paths stay
    in the Source index's coordinates (including assembled-source coordinates).
    Seat permissions and any smaller Ports limit remain downstream checks.
    """
    if type(source) is not dict:
        raise C0LawError("offer sets need a Source mapping")
    declarations = source.get("offer_sets", [])
    if type(declarations) is not list or len(declarations) > 64:
        raise C0LawError("offer sets need at most 64 declarations")
    groups = {}
    for index, row in enumerate(declarations):
        if type(row) is not dict or set(row) != {"name", "offers"}:
            raise C0LawError("offer set declaration has missing or unknown fields")
        name = row["name"]
        if type(name) is not str or not name.isidentifier() or name in groups:
            raise C0LawError("offer set name is malformed or repeated")
        offers = row["offers"]
        if type(offers) is not list or not offers:
            raise C0LawError("offer set needs a nonempty offer list")
        COMPILE_BUDGET.check("finite_offers", len(offers), stage="offer set definition")
        for offer in offers:
            _check_offer(offer)
        groups[name] = (index, offers)

    result = deepcopy({key: value for key, value in source.items() if key != "offer_sets"})
    seats = result.get("seats", [])
    if type(seats) is not list:
        raise C0LawError("offer sets need a seat list")
    origins = {}
    for seat_index, seat in enumerate(seats):
        if type(seat) is not dict or type(seat.get("offers")) is not list:
            raise C0LawError("offer sets need seat offer lists")
        expanded = []
        for offer_index, offer in enumerate(seat["offers"]):
            use_path = ("seats", seat_index, "offers", offer_index)
            logical_use = f"seats[{seat_index}].offers[{offer_index}]"
            frames = source_context.frames_for(logical_use) if source_context else ()
            if type(offer) is dict and "use_offer_set" in offer:
                if set(offer) != {"use_offer_set"}:
                    raise C0LawError("offer set reference has unknown fields")
                name = offer["use_offer_set"]
                if type(name) is not str or name not in groups:
                    raise C0LawError("offer set reference names an unknown set")
                group_index, members = groups[name]
                COMPILE_BUDGET.check(
                    "finite_offers", len(expanded) + len(members), stage="offer set expansion"
                )
                for member_index, member in enumerate(members):
                    path = ("offer_sets", group_index, "offers", member_index)
                    member_frames = (
                        *frames,
                        C0OriginFrame(
                            "offer_set_use",
                            name,
                            repr(use_path),
                            source_context.index.spans.get(use_path) if source_context else None,
                        ),
                        C0OriginFrame(
                            "offer_set_definition",
                            name,
                            repr(path),
                            source_context.index.spans.get(path) if source_context else None,
                        ),
                    )
                    origins[seat_index, len(expanded)] = (path, member_frames)
                    expanded.append(deepcopy(member))
            else:
                COMPILE_BUDGET.check(
                    "finite_offers", len(expanded) + 1, stage="offer set expansion"
                )
                origins[seat_index, len(expanded)] = (use_path, frames)
                expanded.append(offer)
        seat["offers"] = expanded
    return result, origins
