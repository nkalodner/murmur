"""`murmur` runs in the background; the one-shot commands still print here."""

import sys
import types

from murmur.app import _relaunch_detached, _should_detach


def _args(**over):
    base = {"foreground": False, "no_tray": False, "verbose": False}
    base.update(over)
    return types.SimpleNamespace(**base)


def test_a_plain_run_hands_off(monkeypatch):
    monkeypatch.setattr(sys, "stderr", object())  # a console is attached
    assert _should_detach(_args()) is True


def test_the_handed_off_copy_does_not_hand_off_again(monkeypatch):
    # It is started with --foreground, and under pythonw stderr is None.
    # Either alone has to be enough.
    monkeypatch.setattr(sys, "stderr", object())
    assert _should_detach(_args(foreground=True)) is False
    monkeypatch.setattr(sys, "stderr", None)
    assert _should_detach(_args()) is False


def test_watching_it_work_stays_in_the_foreground(monkeypatch):
    monkeypatch.setattr(sys, "stderr", object())
    # Both of these exist to watch output, which detaching would throw away.
    assert _should_detach(_args(verbose=True)) is False
    assert _should_detach(_args(no_tray=True)) is False


def test_relaunch_passes_the_arguments_through_and_detaches(monkeypatch):
    import subprocess

    seen = {}
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/murmurw" if name == "murmurw" else None)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or object())

    assert _relaunch_detached(["--hotkey", "f8"]) is True
    assert seen["cmd"] == ["/usr/bin/murmurw", "--foreground", "--hotkey", "f8"]
    # Detached, or it dies with the terminal that started it.
    assert seen["kw"].get("start_new_session") or seen["kw"].get("creationflags")


def test_relaunch_reports_failure_rather_than_raising(monkeypatch):
    import subprocess

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/murmurw")

    def boom(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(subprocess, "Popen", boom)
    assert _relaunch_detached([]) is False
