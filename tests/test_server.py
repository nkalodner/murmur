"""The settings server answers only requests addressed to this machine.

A hostile page can point its own name at 127.0.0.1 (DNS rebinding) and then
read from the server as though it were same-origin. The browser still sends
that name in Host, so the server refuses anything not addressed to
127.0.0.1 or localhost on its own port, before any handler runs. Writes keep
their own guard on top: the X-Murmur header and a same-origin Origin.

Requests are written by hand over a socket so a test can set Host to
anything, send two, or leave it out.
"""
from __future__ import annotations

import json
import socket

import pytest

from murmur import server

SECRET = "a private dictation"


class FakeApp:
    def __init__(self):
        self.applied = []

    def snapshot(self):
        return {"config": {"hotkey": "ctrl_r"}}

    def dictionary_export(self):
        return {"kind": "murmur-dictionary", "vocabulary": ["Murmur"]}

    def apply_config(self, data):
        self.applied.append(data)
        return []


def _free_port() -> int:
    """A port nothing is using. Never one in the app's own range: on Windows
    a second server can bind a port a running Murmur already holds, and the
    write test below would then reach the real settings."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((server.HOST, 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def started():
    # One server for the module: stopping one waits out a half-second poll.
    app = FakeApp()
    settings = server.SettingsServer(app)
    port_range = server.PORT_RANGE
    port = _free_port()
    server.PORT_RANGE = range(port, port + 1)
    try:
        assert settings.start(), "no free port for the settings server"
    finally:
        server.PORT_RANGE = port_range
    try:
        yield settings, app
    finally:
        settings.stop()


@pytest.fixture
def running(started, monkeypatch, tmp_path):
    settings, app = started
    history = tmp_path / "history.jsonl"
    history.write_text(json.dumps({"text": SECRET}) + "\n", encoding="utf-8")
    monkeypatch.setattr(server, "HISTORY_PATH", history)
    app.applied.clear()
    return settings, app


def ask(port: int, lines: list[str], body: bytes = b"") -> tuple[int, bytes]:
    """Send a raw request and return (status, body)."""
    head = "\r\n".join(lines) + "\r\n\r\n"
    with socket.create_connection((server.HOST, port), timeout=5) as sock:
        sock.sendall(head.encode("latin-1") + body)
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    status = int(data.split(b" ", 2)[1])
    return status, data.split(b"\r\n\r\n", 1)[1]


def get(port: int, host: str | None, path: str = "/api/history") -> tuple[int, bytes]:
    lines = [f"GET {path} HTTP/1.1"]
    if host is not None:
        lines.append(f"Host: {host}")
    return ask(port, lines)


def post(port: int, headers: list[str], path: str = "/api/config") -> tuple[int, bytes]:
    body = b'{"sounds": false}'
    lines = [f"POST {path} HTTP/1.1", *headers, "Content-Type: application/json",
             f"Content-Length: {len(body)}"]
    return ask(port, lines, body)


def test_history_is_readable_from_the_page_itself(running):
    settings, _ = running
    for host in (f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"):
        status, body = get(settings.port, host)
        assert status == 200
        assert json.loads(body)["entries"][0]["text"] == SECRET


def test_history_is_refused_to_a_foreign_host(running):
    settings, _ = running
    status, body = get(settings.port, f"evil.example:{settings.port}")
    assert status == 403
    assert SECRET.encode() not in body


@pytest.mark.parametrize(
    "host",
    [
        "evil.example:{port}",
        "127.0.0.1",  # no port
        "localhost",
        "127.0.0.1:{other}",  # the right machine, someone else's port
        "localhost.:{port}",  # trailing dot
        "LOCALHOST:{port}",  # browsers lowercase the name; only a hand-made request would not
        "LOCALHOST.evil.example:{port}",
        "127.0.0.1:{port}.evil.example",
        "[::1]:{port}",  # the server never binds IPv6
        "0.0.0.0:{port}",
        "",
    ],
)
def test_every_read_is_refused_unless_addressed_here(running, host):
    settings, _ = running
    host = host.format(port=settings.port, other=settings.port + 1)
    for path in ("/api/history", "/api/state", "/api/dictionary", "/"):
        status, body = get(settings.port, host, path)
        assert status == 403, (host, path)
        assert SECRET.encode() not in body and b"murmur-dictionary" not in body


def test_a_missing_host_is_refused(running):
    settings, _ = running
    assert get(settings.port, None)[0] == 403


def test_a_second_host_header_is_refused(running):
    settings, _ = running
    status, _ = ask(
        settings.port,
        ["GET /api/history HTTP/1.1", f"Host: 127.0.0.1:{settings.port}", "Host: evil.example"],
    )
    assert status == 403


def test_an_absolute_form_target_is_refused(running):
    # It names its own host, which a server is meant to prefer over Host.
    settings, _ = running
    status, body = ask(
        settings.port,
        ["GET http://evil.example/api/history HTTP/1.1", f"Host: 127.0.0.1:{settings.port}"],
    )
    assert status == 403 and SECRET.encode() not in body


def test_other_methods_meet_the_same_check(running):
    settings, app = running
    for method in ("PUT", "DELETE", "OPTIONS", "HEAD"):
        status, _ = ask(settings.port, [f"{method} /api/config HTTP/1.1", "Host: evil.example"])
        assert status == 403, method
    status, _ = post(settings.port, ["Host: evil.example", "X-Murmur: 1"])
    assert status == 403
    assert app.applied == []


def test_a_write_without_the_custom_header_is_still_refused(running):
    settings, app = running
    status, body = post(settings.port, [f"Host: 127.0.0.1:{settings.port}"])
    assert status == 403 and b"X-Murmur" in body
    assert app.applied == []


def test_a_write_from_a_foreign_origin_is_still_refused(running):
    settings, app = running
    status, _ = post(
        settings.port,
        [f"Host: 127.0.0.1:{settings.port}", "X-Murmur: 1", "Origin: http://evil.example"],
    )
    assert status == 403
    assert app.applied == []


def test_a_write_from_the_page_goes_through(running):
    settings, app = running
    status, _ = post(
        settings.port,
        [
            f"Host: 127.0.0.1:{settings.port}",
            "X-Murmur: 1",
            f"Origin: http://127.0.0.1:{settings.port}",
        ],
    )
    assert status == 200
    assert app.applied == [{"sounds": False}]


def test_find_running_instance_still_finds_it(running, monkeypatch):
    # murmur --settings and --update locate the running copy this way.
    settings, _ = running
    monkeypatch.setattr(server, "PORT_RANGE", range(settings.port, settings.port + 1))
    assert server.find_running_instance(timeout=2) == settings.url
