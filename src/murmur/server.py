"""Local settings server: serves the settings page and applies config changes.

Bound to 127.0.0.1 only. Mutating requests must carry the X-Murmur header
(which forces a CORS preflight for any cross-origin caller, and we never
answer preflights) and must not carry a foreign Origin, so a random website
cannot poke the config from the browser.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from murmur import __version__
from murmur.config import HISTORY_PATH

log = logging.getLogger("murmur")

HOST = "127.0.0.1"
PORT_RANGE = range(8766, 8776)


def read_history_tail(n: int = 12) -> list[dict]:
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines[-n:]:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    entries.reverse()
    return entries


class SettingsServer:
    def __init__(self, app):
        self._app = app
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url: str | None = None

    def start(self) -> str | None:
        page = resources.files("murmur").joinpath("ui.html").read_text(encoding="utf-8")
        app = self._app
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # keep the terminal quiet
                log.debug("settings: " + fmt, *args)

            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, payload: dict) -> None:
                self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

            def _guarded(self) -> bool:
                origin = self.headers.get("Origin")
                if origin and origin != f"http://{HOST}:{server.port}" and origin != f"http://localhost:{server.port}":
                    self._json(403, {"error": "forbidden origin"})
                    return False
                if self.headers.get("X-Murmur") != "1":
                    self._json(403, {"error": "missing X-Murmur header"})
                    return False
                return True

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/":
                    self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._json(200, {"app": "murmur", "version": __version__, **app.snapshot()})
                elif path == "/api/history":
                    self._json(200, {"entries": read_history_tail()})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                if not self._guarded():
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length > 1_000_000:
                    self._json(413, {"error": "payload too large"})
                    return
                try:
                    data = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(data, dict):
                        raise ValueError("expected a JSON object")
                except ValueError as e:
                    self._json(400, {"error": f"bad JSON: {e}"})
                    return
                path = self.path.split("?")[0]
                if path == "/api/config":
                    try:
                        warnings = app.apply_config(data)
                    except (ValueError, LookupError) as e:
                        self._json(400, {"error": str(e)})
                        return
                    except Exception:
                        log.exception("apply_config failed")
                        self._json(500, {"error": "internal error applying config"})
                        return
                    self._json(
                        200,
                        {
                            "ok": True,
                            "warnings": warnings,
                            "app": "murmur",
                            "version": __version__,
                            **app.snapshot(),
                        },
                    )
                elif path == "/api/test-sound":
                    from murmur.sounds import CUES

                    cue = data.get("cue", "start")
                    if cue not in CUES:
                        cue = "start"
                    # Honor the test even if cues are turned off, without
                    # changing the persisted setting.
                    was = app.sounds.enabled
                    app.sounds.enabled = True
                    try:
                        app.sounds.play(cue)
                    finally:
                        app.sounds.enabled = was
                    self._json(200, {"ok": True})
                elif path == "/api/test-mic":
                    try:
                        result = app.test_microphone(data.get("device") or None)
                    except (ValueError, LookupError) as e:
                        self._json(400, {"error": str(e)})
                        return
                    except Exception as e:
                        log.debug("mic test failed: %s", e)
                        self._json(400, {"error": f"could not open the microphone: {e}"})
                        return
                    self._json(200, result)
                elif path == "/api/autostart":
                    if "enabled" not in data or not isinstance(data["enabled"], bool):
                        self._json(400, {"error": "expected {\"enabled\": true|false}"})
                        return
                    try:
                        status = app.set_autostart(data["enabled"])
                    except Exception as e:
                        log.debug("autostart change failed: %s", e)
                        self._json(400, {"error": str(e)})
                        return
                    self._json(200, {"ok": True, "autostart": status})
                else:
                    self._json(404, {"error": "not found"})

        last_error: Exception | None = None
        for port in PORT_RANGE:
            try:
                self._httpd = ThreadingHTTPServer((HOST, port), Handler)
                self.port = port
                break
            except OSError as e:
                last_error = e
        if self._httpd is None:
            log.warning("Settings page unavailable: no free port in %s-%s (%s)",
                        PORT_RANGE.start, PORT_RANGE.stop - 1, last_error)
            return None
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="murmur-settings", daemon=True)
        self._thread.start()
        self.url = f"http://{HOST}:{self.port}"
        return self.url

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None


def find_running_instance(timeout: float = 0.4) -> str | None:
    """Return the settings URL of an already-running Murmur, if any."""
    import urllib.request

    for port in PORT_RANGE:
        url = f"http://{HOST}:{port}"
        try:
            with urllib.request.urlopen(f"{url}/api/state", timeout=timeout) as res:
                if json.loads(res.read()).get("app") == "murmur":
                    return url
        except Exception:
            continue
    return None
