"""Flush committed local captures without holding the world writer during socket I/O."""

import json
import logging
from contextlib import nullcontext
from copy import deepcopy
from queue import SimpleQueue
from threading import Thread

from .errors import TableError


def _capture(game, operation, emit):
    emitted = False
    batch_id = None
    revision = game.revision

    def send(frame):
        nonlocal emitted
        emit(frame)
        emitted = True

    def observe(batch, group):
        nonlocal batch_id
        if batch_id != batch["id"]:
            batch_id = batch["id"]
            send({"type": "begin", "id": batch_id, "base": deepcopy(batch["base"])})
        send({"type": "group", "group": deepcopy(group)})

    try:
        with game.timeline.observe(
            observe, submitted=lambda action: send({"type": "accepted", "action": action})
        ):
            result = operation()
        send({"type": "final", "view": result})
    except Exception as error:
        progressed = game.revision != revision
        if isinstance(error, TableError):
            code = error.code
        else:
            code = "SettlementError"
            logging.getLogger(__name__).exception("Tabletop control failed after partial progress")
        if progressed or not isinstance(error, TableError):
            game.status, game.code = "blocked", code
            game._tickets.clear()
        if not emitted and not progressed:
            raise TableError(code) from error
        send({"type": "error", "code": code})


def stream_control(handler, game, operation, *, lock=None):
    frames = SimpleQueue()
    failures = []

    def transmit():
        started, connected = False, True
        while (data := frames.get()) is not None:
            if not connected:
                continue
            try:
                if not started:
                    handler.connection.settimeout(5)
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                    handler.send_header("Cache-Control", "no-store")
                    handler.send_header("X-Content-Type-Options", "nosniff")
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    handler.close_connection = True
                    started = True
                handler.wfile.write(data)
                handler.wfile.flush()
            except OSError:
                # Display disconnection cannot undo or repeat a committed Action.
                connected = False
            except Exception as error:
                connected = False
                failures.append(error)

    def emit(frame):
        # Freeze bytes under the writer before another request can change the game.
        frames.put((json.dumps(frame, ensure_ascii=False) + "\n").encode())

    sender = Thread(target=transmit, name="nomos-stream-sender")
    sender.start()
    try:
        with lock if lock is not None else nullcontext():
            _capture(game, operation, emit)
    finally:
        frames.put(None)
        # Join outside the world lock, including error and disconnect paths.
        sender.join()
    if failures:
        raise failures[0]
