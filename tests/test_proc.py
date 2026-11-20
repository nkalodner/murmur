"""System helpers start without duplicating the whole process on a Mac.

subprocess only takes its posix_spawn path there when it is given a full
path and close_fds=False; otherwise it forks, which copies a process holding
a speech model and stalls every thread while it does.
"""
import types

from murmur import proc


def _capture(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(cmd=cmd, kwargs=kwargs)
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(proc.subprocess, "run", fake_run)
    return seen


def test_mac_helpers_get_a_full_path_and_no_fd_sweep(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setattr(proc.sys, "platform", "darwin")
    monkeypatch.setattr(proc, "which", lambda name: f"/usr/bin/{name}")
    proc.run(["afplay", "cue.wav"], check=False)
    assert seen["cmd"] == ["/usr/bin/afplay", "cue.wav"]
    assert seen["kwargs"]["close_fds"] is False


def test_a_helper_that_cannot_be_found_runs_as_before(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setattr(proc.sys, "platform", "darwin")
    monkeypatch.setattr(proc, "which", lambda name: None)
    proc.run(["afplay", "cue.wav"])
    assert seen["cmd"] == ["afplay", "cue.wav"] and "close_fds" not in seen["kwargs"]


def test_other_platforms_are_left_alone(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setattr(proc.sys, "platform", "win32")
    proc.run(["osascript", "-e", "x"], timeout=1)
    assert seen["cmd"] == ["osascript", "-e", "x"] and "close_fds" not in seen["kwargs"]


def test_which_looks_once(monkeypatch):
    looks = []
    monkeypatch.setattr(proc, "_paths", {})
    monkeypatch.setattr(proc.shutil, "which", lambda name: looks.append(name) or "/bin/x")
    assert proc.which("x") == proc.which("x") == "/bin/x"
    assert looks == ["x"]
