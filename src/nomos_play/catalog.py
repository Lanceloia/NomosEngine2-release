"""Registered generated artifacts, explicit opening files and owned module lifetimes."""

import logging
import re
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from nomos_runtime.artifacts import load_world
from nomos_runtime.documents import read_data
from nomos_runtime.errors import SettlementDefect
from nomos_runtime.expressions import ExpressionError, ValueBindingError
from nomos_runtime.presentation import data

from .errors import TableError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GameEntry:
    id: str
    title: str
    description: str
    world: Path
    assets: Path


@contextmanager
def open_game(entry):
    with load_world(entry.world) as module:
        yield module.PROGRAM, read_data(entry.assets), module.DISPLAY, module.CONTROLLERS


class GameCatalog:
    def __init__(self, entries, loader=open_game):
        self.entries = tuple(entries)
        if not 1 <= len(self.entries) <= 32:
            raise ValueError("game catalog requires 1..32 entries")
        seen = set()
        for entry in self.entries:
            if (
                type(entry.id) is not str
                or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", entry.id) is None
                or entry.id in seen
                or type(entry.title) is not str
                or not 1 <= len(entry.title.strip()) <= 128
                or type(entry.description) is not str
                or len(entry.description) > 1200
            ):
                raise ValueError("invalid or repeated game catalog entry")
            seen.add(entry.id)
        self._entries = {entry.id: entry for entry in self.entries}
        self._loader, self._compiled, self._lock = loader, {}, RLock()
        self._resources, self._closed = ExitStack(), False

    @classmethod
    def read(cls, path):
        path = Path(path).resolve()
        declaration = read_data(path)
        if (
            set(declaration) != {"schema", "games"}
            or declaration["schema"] != "nomos.play.catalog"
            or type(declaration["games"]) is not list
        ):
            raise ValueError("expected nomos.play.catalog with games")
        entries = []
        for item in declaration["games"]:
            if type(item) is not dict or set(item) != {
                "id",
                "title",
                "description",
                "world",
                "assets",
            }:
                raise ValueError("game entry requires id/title/description/world/assets")
            if any(
                type(item[key]) is not str or not item[key].strip() for key in ("world", "assets")
            ):
                raise ValueError("game entry needs explicit artifact and opening paths")
            entries.append(
                GameEntry(
                    item["id"],
                    item["title"],
                    item["description"],
                    (path.parent / item["world"]).resolve(),
                    (path.parent / item["assets"]).resolve(),
                )
            )
        return cls(entries)

    def listing(self):
        return [
            {"id": entry.id, "title": entry.title, "description": entry.description}
            for entry in self.entries
        ]

    def get(self, game_id):
        if type(game_id) is not str or game_id not in self._entries:
            raise TableError("UnknownGame")
        with self._lock:
            if self._closed:
                raise TableError("CatalogClosed")
            if game_id not in self._compiled:
                try:
                    with ExitStack() as pending:
                        world = pending.enter_context(self._loader(self._entries[game_id]))
                        program, assets, display, controllers = world
                        if program.play is None or program.play.mechanism != "tabletop":
                            raise TableError("NoTabletopMechanism")
                        if display is None or display.program is not program:
                            raise TableError("WrongPresentation")
                        self._resources.enter_context(pending.pop_all())
                        self._compiled[game_id] = world
                except TableError:
                    raise
                except (
                    OSError,
                    ValueError,
                    ValueBindingError,
                    ExpressionError,
                    SettlementDefect,
                ) as error:
                    logger.error("Game %s failed to load: %s", game_id, error)
                    raise TableError("GameLoadFailed") from error
            return self._compiled[game_id]

    def setup(self, game_id):
        program, _, display, _ = self.get(game_id)
        spec = display.specification
        return {
            "game": game_id,
            "title": spec["title"],
            "description": spec["description"],
            "rules": data(spec["rules"]),
            "seats": [
                {"id": seat, "label": spec["labels"].get(seat, seat.upper())}
                for seat in program.play.seats
            ],
        }

    def close(self):
        with self._lock:
            self._closed = True
            self._compiled.clear()
            self._resources.close()
