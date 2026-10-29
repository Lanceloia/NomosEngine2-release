"""Actor-local display data over generated readers and pure presentation functions."""

import secrets
from dataclasses import dataclass
from types import MappingProxyType

from .errors import AdmissionError, SettlementDefect
from .expressions import ValueBudget
from .ordering import canonical
from .values import wire_key

MAX_SAFE_INTEGER = 2**53 - 1


class InputDisplayError(AdmissionError):
    """An input hint cannot be represented; this is not a world admission result."""


def freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if type(value) in (tuple, list):
        return tuple(freeze(item) for item in value)
    return value


def data(value):
    if isinstance(value, MappingProxyType):
        return {key: data(item) for key, item in value.items()}
    if type(value) is tuple:
        return [data(item) for item in value]
    return value


@dataclass(frozen=True)
class DisplayRead:
    title: str
    zone: str
    type_name: str | None
    evaluate: object
    fold: bool
    display: object

    def __post_init__(self):
        object.__setattr__(self, "display", freeze(self.display))


@dataclass(frozen=True)
class DisplayInput:
    name: str
    type_name: str
    element_type: str
    specification: object

    def __post_init__(self):
        object.__setattr__(self, "specification", freeze(self.specification))


@dataclass(frozen=True)
class DisplayAction:
    name: str
    specification: object
    inputs: tuple
    hints: object

    def __post_init__(self):
        object.__setattr__(self, "specification", freeze(self.specification))


class CompiledDisplay:
    def __init__(
        self,
        program,
        specification,
        formats,
        reads,
        panels,
        actions,
        marks,
        self_badge,
        reveal,
        details,
        cues,
        boards,
        cognition,
    ):
        self.program = program
        self.specification, self.formats = freeze(specification), freeze(formats)
        self.reads, self.panels = tuple(reads), tuple(panels)
        self.actions = MappingProxyType({action.name: action for action in actions})
        self.marks, self.self_badge = tuple(marks), self_badge
        self.reveal, self.details = reveal, freeze(details)
        self.cues, self.boards, self.cognition = freeze(cues), freeze(boards), freeze(cognition)

    def open(self, session, actor):
        if session.program is not self.program:
            raise ValueError("display requires its exact generated Program")
        if type(actor) is not str or actor not in session.program.play.seats:
            raise AdmissionError("WrongController", "display requires a declared table seat")
        session.actor_reference(actor)
        return PlayerDisplay(self, session, actor)


class DisplayFrame:
    def __init__(self, player):
        self.player, self.session, self.actor = player, player.session, player.actor
        self.stamp = self.current_stamp()
        self.check()
        self.codec = self.session.values(self.actor)
        self.budget = ValueBudget(self.codec.limits)
        self.sources, self.reads = {}, {}

    def current_stamp(self):
        session = self.session
        return session._states, session._history, session._time

    def check(self):
        if self.session._busy or self.session._fatal:
            raise SettlementDefect("display is unavailable during settlement or after fatal")
        current = self.current_stamp()
        if (
            current[0] is not self.stamp[0]
            or current[1] is not self.stamp[1]
            or current[2] != self.stamp[2]
        ):
            raise ValueError("display state changed during a read")

    def encode(self, name, value):
        self.check()
        result = self.codec.encode(name, value, reference=self.reference, budget=self.budget)
        self.check()
        return result

    def reference(self, ref):
        self.codec.references.require(ref, ref.sort)
        return self.player._reference(ref)

    def source(self, kind, name):
        self.check()
        key = kind, name
        if key not in self.sources:
            session, actor = self.session, self.actor
            if kind == "self":
                result = True, session.read(actor)
            elif kind == "context":
                result = True, session.read_context(actor, name)
            elif kind == "information":
                item = session.report(actor, name)
                result = item["acquired"], item.get("value")
            elif kind == "projection":
                item = session.project(actor, name)
                result = item["available"], item.get("value")
            elif kind == "ending":
                item = session.ending(actor)
                result = item["available"], item["value"]
            else:
                raise ValueError("unknown generated display source")
            self.check()
            self.sources[key] = result
        return self.sources[key]

    def reports(self, channel):
        key = "reports", channel
        self.check()
        if key not in self.sources:
            item = self.session.reports(self.actor, channel)
            actor = self.session.actor_reference(self.actor)
            values = [
                self.encode(receipt.type_name, receipt.value)
                for receipt in self.session.acquisitions()
                if receipt.recipient == actor and receipt.channel == channel
            ]
            self.sources[key] = item["acquired"], values
        return self.sources[key]

    def read(self, index):
        self.check()
        if index not in self.reads:
            self.reads[index] = self.player.definition.reads[index].evaluate(self)
            self.check()
        return self.reads[index]

    def allocation(self, rows, total, minimum, *, unordered):
        if type(total) is not int or type(minimum) is not int or not 0 <= minimum <= total:
            raise InputDisplayError("InvalidAllocationTotal", "invalid visible allocation total")
        if total > MAX_SAFE_INTEGER:
            raise InputDisplayError(
                "AllocationRangeUnsupported", "allocation total exceeds JS range"
            )
        targets, seen = [], set()
        for key, label, capacity in rows:
            if type(capacity) is not int or capacity < 0:
                raise InputDisplayError("InvalidAllocationCapacity", "invalid visible capacity")
            if capacity > MAX_SAFE_INTEGER or type(key) is int and abs(key) > MAX_SAFE_INTEGER:
                raise InputDisplayError(
                    "AllocationRangeUnsupported", "allocation value exceeds JS range"
                )
            identity = wire_key(key)
            if identity in seen:
                raise InputDisplayError(
                    "DuplicateAllocationTarget", "duplicate visible allocation key"
                )
            seen.add(identity)
            targets.append({"key": key, "label": label, "capacity": capacity})
        if unordered:
            targets.sort(key=lambda item: wire_key(item["key"]))
        return {"targets": targets, "total": total, "minimum": minimum}


class PlayerDisplay:
    def __init__(self, definition, session, actor):
        self.definition, self.session, self.actor = definition, session, actor
        self.handles = {}

    def encode(self, type_name, value):
        return DisplayFrame(self).encode(type_name, value)

    def decode(self, type_name, wire):
        frame = DisplayFrame(self)

        def reference(value, sort):
            if type(value) is not dict or set(value) != {"reference", "label"}:
                raise AdmissionError(
                    "UnknownVisibleReference", "expected an issued display reference"
                )
            ref = next((ref for ref, shown in self.handles.items() if shown == value), None)
            if ref is None:
                raise AdmissionError(
                    "UnknownVisibleReference", "reference was not issued to this view"
                )
            return ref

        result = frame.codec.decode(type_name, wire, reference=reference)
        frame.check()
        return result

    def _reference(self, ref):
        if ref not in self.handles:
            name = next((name for name, value in self.session.symbols if value == ref), None)
            labels = self.definition.specification["labels"]
            kind = self.session.program.schemas[ref.sort].kind
            label = (
                labels.get(name, name.upper())
                if name is not None
                else (("人物" if kind == "person" else "物件") + " " + str(len(self.handles) + 1))
            )
            self.handles[ref] = {"reference": secrets.token_urlsafe(18), "label": label}
        return dict(self.handles[ref])

    def format(self, type_name):
        return data(self.definition.formats[type_name])

    def panel(self, frame, index):
        available, value = frame.read(index)
        if not available:
            return None
        definition = self.definition.reads[index]
        return {
            "id": f"panel-{index}",
            "title": definition.title,
            "zone": definition.zone,
            "data": value,
            "format": data(definition.display)
            if definition.display
            else self.format(definition.type_name),
            "fold": definition.fold,
        }

    def seats(self, frame):
        people = [
            {
                **frame.reference(dict(self.session.symbols)[seat]),
                "self": seat == self.actor,
                "marks": [],
                "badge": None,
                "details": [],
            }
            for seat in self.session.program.play.seats
        ]
        by_ref = {person["reference"]: person for person in people}
        for index, icon, tone in self.definition.marks:
            available, value = frame.read(index)
            if not available or value is None:
                continue
            for item in value if type(value) is list else [value]:
                if item["reference"] in by_ref:
                    by_ref[item["reference"]]["marks"].append(
                        {
                            "label": self.definition.reads[index].title,
                            "icon": icon,
                            "tone": tone,
                        }
                    )
        if self.definition.self_badge is not None:
            panel = self.panel(frame, self.definition.self_badge)
            if panel is not None:
                next(person for person in people if person["self"])["badge"] = {
                    "data": panel["data"],
                    "format": panel["format"],
                }
        if self.definition.reveal is not None:
            index, ref_field, badge_field, badge_type = self.definition.reveal
            available, records = frame.read(index)
            seen = set()
            for record in records if available else ():
                ref = record[ref_field]["reference"]
                if ref in seen:
                    raise ValueError("AmbiguousRevelation")
                seen.add(ref)
                if ref in by_ref:
                    by_ref[ref]["badge"] = {
                        "data": record[badge_field],
                        "format": self.format(badge_type),
                    }
        for index, ref_field, fields in self.definition.details:
            available, records = frame.read(index)
            seen = set()
            for record in records if available else ():
                ref = record[ref_field]["reference"]
                if ref not in by_ref or ref in seen:
                    raise ValueError("InvalidSeatDetail")
                seen.add(ref)
                by_ref[ref]["details"].append(
                    {
                        "title": self.definition.reads[index].title,
                        "data": {name: record[name] for name, _ in fields},
                        "format": {
                            "kind": "record",
                            "fields": {
                                name: {
                                    "label": self.definition.specification["labels"].get(
                                        name, name
                                    ),
                                    "format": self.format(type_name),
                                }
                                for name, type_name in fields
                            },
                        },
                    }
                )
        return people

    def snapshot(self):
        frame = DisplayFrame(self)
        result = data(self.definition.specification)
        result["schema"] = "nomos.tabletop.readback"
        result["panels"] = [
            panel for index in self.definition.panels if (panel := self.panel(frame, index))
        ]
        result["seats"] = self.seats(frame)
        result["cues"] = [
            {
                **data(cue),
                "available": available,
                "data": value,
                "format": self.format(self.definition.reads[cue["read"]].type_name),
                "group_value": None
                if cue["group_read"] is None
                else frame.read(cue["group_read"])[1],
            }
            for cue in self.definition.cues
            for available, value in [frame.read(cue["read"])]
        ]
        result["boards"] = self.boards(frame)
        ending = self.session.ending(self.actor)
        result["ending"] = {
            **ending,
            "value": None
            if not ending["available"]
            else frame.encode(self.session.program.terminal.result_type, ending["value"]),
        }
        result["cognition"] = None
        try:
            cognition = self.session.cognition(self.actor)
        except AdmissionError as error:
            if error.code != "NoCognition":
                raise
        else:
            types = self.definition.cognition[cognition["binding"]]
            type_name = types["view"]
            result["cognition"] = {
                **self.session.explain_cognition(self.actor, encode=frame.encode),
                "view": frame.encode(type_name, cognition["view"]),
                "format": self.format(type_name),
                "proposition_format": self.format(types["proposition"]),
            }
        frame.check()
        return result

    def boards(self, frame):
        boards = []
        for board in self.definition.boards:
            available, records = frame.read(board["read"])
            if not available:
                continue
            people, seen = [], set()
            for record in records:
                owner = record[board["owner"]]
                if owner["reference"] in seen:
                    raise ValueError("DuplicateBoardOwner")
                seen.add(owner["reference"])
                groups = []
                for group in board["groups"]:
                    sites, keys = [], set()
                    for site in record[group["name"]]:
                        key = wire_key(site[group["key"]])
                        if key in keys:
                            raise ValueError("DuplicateBoardSite")
                        keys.add(key)
                        label = site[group["label"]]
                        captions = {**self.definition.specification["labels"], **group["labels"]}
                        sites.append(
                            {
                                "key": key,
                                "label": captions.get(
                                    "null" if label is None else str(label),
                                    label if label is not None else "暂无",
                                ),
                                "quantity": quantity(site[group["quantity"]]),
                            }
                        )
                    groups.append({"id": group["name"], "title": group["title"], "sites": sites})
                people.append(
                    {**owner, "reserve": quantity(record[board["reserve"]]), "groups": groups}
                )
            pools = [
                {
                    "id": name,
                    "title": self.definition.reads[index].title,
                    "quantity": quantity(value),
                }
                for name, index in board["pools"]
                for available, value in [frame.read(index)]
                if available
            ]
            boards.append(
                {
                    "id": board["name"],
                    "title": board["title"],
                    "unit": board["unit"],
                    "icon": board["icon"],
                    "motion": board["motion"],
                    "people": people,
                    "pools": pools,
                }
            )
        return boards

    def form(self, ability, choices=None, *, request=None):
        return self._form(ability, choices, request=request)[1]

    def _form(self, ability, choices=None, *, request=None):
        """Keep actual choices and their display in one checked construction."""
        frame = DisplayFrame(self)
        action = self.definition.actions.get(ability)
        if action is None:
            raise AdmissionError("UnknownAction", "display action is not selected")
        form = self.session.choice_form(self.actor, ability, choices, request=request)
        hints, previews = action.hints(self.session, self.actor, form, request, frame)
        inputs, fields = {item.name: item for item in action.inputs}, []
        for field in form.fields:
            item = inputs[field.name]
            spec = data(item.specification)
            result = {
                **spec,
                "name": field.name,
                "kind": field.kind,
                "ready": field.ready,
                "dependencies": list(field.dependencies),
                "min": field.minimum,
                "max": field.maximum,
                "length": field.length,
                "repetition": field.repetition,
                "format": self.format(field.type_name),
                **hints.get(field.name, {}),
            }
            if field.ready and field.pool is not None:
                values = [
                    frame.encode(item.element_type, value)
                    for value in sorted(field.pool, key=canonical)
                ]
                result["options"] = [
                    {"index": index, "data": value} for index, value in enumerate(values)
                ]
            fields.append(result)
        frame.check()
        return form, {
            **data(action.specification),
            "ability": ability,
            "complete": form.complete,
            "condition_pending": form.condition_pending,
            "fields": fields,
            "previews": previews,
        }


def quantity(value):
    return value if abs(value) <= MAX_SAFE_INTEGER else str(value)
