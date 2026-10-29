"""Sample generated player readbacks only after complete published roots."""

import secrets
from contextlib import contextmanager
from copy import deepcopy


class VisibleTimeline:
    def __init__(self, game):
        self.game = game
        shown = game.snapshot()
        self.previous, self.state = self._sample(shown), self._state(shown)
        self.events, self.recent, self.group_count = [], [], 0
        self._observer = self._submission_observer = None
        self.begin()

    @staticmethod
    def _sample(shown):
        return [(cue["available"], cue["data"], cue["group_value"]) for cue in shown["cues"]]

    @staticmethod
    def _state(shown):
        return {
            "boards": shown["boards"],
            "panels": [panel for panel in shown["panels"] if panel["zone"] != "history"],
            "seats": shown["seats"],
        }

    @contextmanager
    def observe(self, observer, submitted=None):
        if self._observer is not None:
            raise RuntimeError("TimelineAlreadyObserved")
        self._observer, self._submission_observer = observer, submitted
        try:
            yield
        finally:
            self._observer = self._submission_observer = None

    def submitted(self, decision):
        if self._submission_observer is not None:
            self._submission_observer(decision["action"])

    def begin(self):
        self.recent = []
        self.batch = {"id": secrets.token_urlsafe(18), "base": deepcopy(self.state), "groups": []}

    def playback(self):
        return deepcopy({**self.batch, "final": self.state})

    def capture(self):
        shown = self.game.snapshot()
        current, state = self._sample(shown), self._state(shown)
        batch = []
        for cue, before, after in zip(shown["cues"], self.previous, current, strict=True):
            available, value, _ = after
            if not available or before == after or cue["nonempty"] and not value:
                continue
            values, kind, style = [value], "change", cue["format"]
            if cue["mode"] == "append":
                old = before[1] if before[0] else []
                if value[: len(old)] == old:
                    values, kind, style = value[len(old) :], "append", style["element"]
                else:
                    kind = "replace"
            for value in values:
                read = self.game.presentation.reads[cue["read"]]
                batch.append(
                    {
                        "id": f"event-{len(self.events) + len(batch) + 1}",
                        "title": read.title,
                        "icon": cue["icon"],
                        "scope": "public"
                        if cue["source"] == "context"
                        else "result"
                        if cue["source"] == "ending"
                        else "personal",
                        "kind": kind,
                        "emphasis": cue["emphasis"],
                        "category": cue["category"],
                        "actor": value[cue["actor_field"]]
                        if cue["actor_field"] is not None and kind != "replace" else None,
                        "group": None if cue["group_label"] is None else {
                            "label": cue["group_label"],
                            "field": cue["group_field"],
                            "value": value[cue["group_field"]]
                            if cue["group_field"] is not None and kind != "replace"
                            else cue["group_value"],
                        },
                        "data": deepcopy(value),
                        "before": deepcopy(before[1]) if before[0] and kind != "append" else None,
                        "before_available": before[0] and kind != "append",
                        "format": deepcopy(style),
                    }
                )
        self.previous = deepcopy(current)
        self.events.extend(batch)
        self.recent.extend(batch)
        if batch or state != self.state:
            self.group_count += 1
            group = {"id": f"group-{self.group_count}", "events": batch, "state": state}
            self.batch["groups"].append(deepcopy(group))
            self.state = deepcopy(state)
            if self._observer is not None:
                self._observer(self.batch, group)
        return bool(batch)
