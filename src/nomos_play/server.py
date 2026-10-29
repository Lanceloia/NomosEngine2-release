"""Local HTTP transport and shared tabletop session ownership."""

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock

from nomos_runtime.errors import AdmissionError, SettlementDefect
from nomos_runtime.expressions import ExpressionError, ValueBindingError

from .errors import TableError
from .streaming import stream_control
from .tabletop import TableGame

STATIC = Path(__file__).parent / "static"


def make_server(catalog, port=0):
    games, groups, group_ids, lock = {}, {}, {}, RLock()
    failed_openings = set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, value, content_type="application/json; charset=utf-8"):
            data = (
                json.dumps(value, ensure_ascii=False).encode() if isinstance(value, dict) else value
            )
            self.connection.settimeout(5)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            port = self.server.server_address[1]
            host = self.headers.get("Host")
            return host in (f"127.0.0.1:{port}", f"localhost:{port}") and (
                self.headers.get("Origin") in (None, "http://" + host)
            )

        def do_GET(self):
            if not self.allowed():
                self.send(403, {"code": "WrongOrigin"})
                return
            if self.path == "/api/setup":
                self.send(200, {"games": catalog.listing()})
                return
            files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/widgets.js": ("widgets.js", "text/javascript; charset=utf-8"),
                "/feedback.js": ("feedback.js", "text/javascript; charset=utf-8"),
                "/boards.js": ("boards.js", "text/javascript; charset=utf-8"),
                "/playback.js": ("playback.js", "text/javascript; charset=utf-8"),
                "/stream.js": ("stream.js", "text/javascript; charset=utf-8"),
                "/choices.js": ("choices.js", "text/javascript; charset=utf-8"),
                "/action_controls.js": ("action_controls.js", "text/javascript; charset=utf-8"),
                "/seat_choices.js": ("seat_choices.js", "text/javascript; charset=utf-8"),
                "/coordination.js": ("coordination.js", "text/javascript; charset=utf-8"),
                "/cognition.js": ("cognition.js", "text/javascript; charset=utf-8"),
                "/mental_audit.js": ("mental_audit.js", "text/javascript; charset=utf-8"),
                "/experience_audit.js": ("experience_audit.js", "text/javascript; charset=utf-8"),
                "/information.js": ("information.js", "text/javascript; charset=utf-8"),
                "/journal.js": ("journal.js", "text/javascript; charset=utf-8"),
                "/icons.js": ("icons.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/noto-sans-sc.woff": ("noto-sans-sc.woff", "font/woff"),
            }
            if self.path not in files:
                self.send(404, {"code": "NotFound"})
                return
            filename, mime = files[self.path]
            self.send(200, (STATIC / filename).read_bytes(), mime)

        def do_POST(self):
            if not self.allowed():
                self.send(403, {"code": "WrongOrigin"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    not 0 < length <= 65536
                    or self.headers.get("Content-Type") != "application/json"
                ):
                    raise TableError("InvalidRequest")
                body = json.loads(self.rfile.read(length))
                if type(body) is not dict:
                    raise TableError("InvalidRequest")
                stream = None
                with lock:
                    result, stream = self.dispatch(body)
                    if stream is None:
                        result = json.dumps(result, ensure_ascii=False).encode()
                if stream is None:
                    self.send(200, result)
                else:
                    game, operation = stream
                    stream_control(self, game, operation, lock=lock)
            except TableError as error:
                self.send(409, {"code": error.code})
            except AdmissionError as error:
                self.send(409, {"code": error.code})
            except SettlementDefect:
                self.send(409, {"code": "SettlementError"})
            except (ValueError, TypeError, KeyError):
                self.send(400, {"code": "InvalidChoice"})

        def dispatch(self, body):
            if self.path == "/api/select":
                if set(body) != {"game"}:
                    raise TableError("InvalidRequest")
                return catalog.setup(body["game"]), None
            if self.path == "/api/start":
                if set(body) - {"game", "seat", "group"} or not {"game", "seat"} <= set(body):
                    raise TableError("InvalidRequest")
                if len(games) >= 32:
                    raise TableError("SessionCapacity")
                world = catalog.get(body["game"])
                group_key = body.get("group")
                subject_group = None
                if group_key is not None:
                    if type(group_key) is not str or group_key not in groups:
                        raise TableError("UnknownSubjectGroup")
                    game_id, subject_group = groups[group_key]
                    if game_id != body["game"]:
                        raise TableError("ForeignSubjectGroup")
                elif (
                    len(groups) >= 32
                    and world[3] is not None
                    and any(s.participation is not None for s in world[3].strategies)
                ):
                    raise TableError("GroupCapacity")
                game, opened = None, False
                recovering = group_key in failed_openings
                can_recover = subject_group is not None and (
                    recovering or subject_group.session is None
                )
                try:
                    # Retry the previous failed cleanup before creating another visit.
                    if recovering:
                        subject_group.interrupt()
                        failed_openings.remove(group_key)
                    game = TableGame(*world, body["seat"], subject_group=subject_group)
                    view = game.view()
                    opened = True
                except TableError:
                    if game is not None:
                        game.close()
                    raise
                except (AdmissionError, SettlementDefect):
                    if game is not None:
                        game.close()
                    raise
                except (ValueError, ValueBindingError, ExpressionError) as error:
                    if game is not None:
                        game.close()
                    raise TableError("GameStartFailed") from error
                finally:
                    if not opened and can_recover and subject_group.session is not None:
                        failed_openings.add(group_key)
                if game.subject_group is not None and group_key is None:
                    group_key = secrets.token_urlsafe(24)
                    groups[group_key] = body["game"], game.subject_group
                token = secrets.token_urlsafe(24)
                games[token] = game
                result = {"session": token, "view": view}
                if group_key is not None:
                    group_ids[token] = group_key
                    result["group"] = group_key
                return result, None
            expected = {
                "/api/view": {"session"},
                "/api/draft": {"session", "action", "revision", "inputs"},
                "/api/advice": {"session", "revision"},
                "/api/cognition-audit": {"session", "actor", "offset"},
                "/api/submit": {"session", "action", "revision", "inputs"},
                "/api/continue": {"session", "revision"},
                "/api/coordinate": {"session", "revision"},
                "/api/close": {"session"},
            }
            if self.path not in expected or set(body) != expected[self.path]:
                raise TableError("InvalidRequest")
            if type(body["session"]) is not str or body["session"] not in games:
                raise TableError("UnknownSession")
            game = games[body["session"]]
            controls = {
                "/api/submit": lambda: game.submit(
                    body["action"], body["revision"], body["inputs"]
                ),
                "/api/continue": lambda: game.continue_play(body["revision"]),
                "/api/coordinate": lambda: game.coordinate(body["revision"]),
            }
            if self.path in controls:

                def operate():
                    if games.get(body["session"]) is not game:
                        raise TableError("UnknownSession")
                    return controls[self.path]()

                return None, (game, operate)
            if self.path == "/api/view":
                result = game.view()
            elif self.path == "/api/close":
                game.close()
                del games[body["session"]]
                result = {"closed": True}
                group_key = group_ids.pop(body["session"], None)
                if group_key is not None:
                    result["group"] = group_key
            elif self.path == "/api/advice":
                result = game.advice(body["revision"])
            elif self.path == "/api/cognition-audit":
                result = game.cognition_audit(body["actor"], body["offset"])
            else:
                result = game.draft(
                    body["action"],
                    body["revision"],
                    body["inputs"],
                )
            return result, None

    class Server(ThreadingHTTPServer):
        def server_close(self):
            failures = []
            for close in (
                super().server_close,
                *(game.close for game in games.values()),
                catalog.close,
            ):
                try:
                    close()
                except Exception as error:
                    failures.append(error)
            if failures:
                raise ExceptionGroup("tabletop server cleanup failed", failures)

    return Server(("127.0.0.1", port), Handler)
