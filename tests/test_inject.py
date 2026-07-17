"""Clipboard injection: the restore timer must put the old clipboard back, but
never clobber something the user copied during the restore window (0.5.3)."""
import contextlib
import sys
import time
import types

import pytest


@pytest.fixture
def clipboard(monkeypatch):
    """Stub pyperclip + pynput so Injector can run headless."""
    clip = {"v": ""}
    fake_clip = types.ModuleType("pyperclip")
    fake_clip.paste = lambda: clip["v"]
    fake_clip.copy = lambda x: clip.__setitem__("v", x)
    monkeypatch.setitem(sys.modules, "pyperclip", fake_clip)

    pynput = types.ModuleType("pynput")
    keyboard = types.ModuleType("pynput.keyboard")

    class _Key:
        cmd = object()
        ctrl = object()

    class _Controller:
        def pressed(self, *a):
            return contextlib.nullcontext()

        def tap(self, *a):
            pass

        def type(self, *a):
            pass

    keyboard.Key = _Key
    keyboard.Controller = _Controller
    pynput.keyboard = keyboard
    monkeypatch.setitem(sys.modules, "pynput", pynput)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", keyboard)
    return clip


def test_restore_puts_previous_back(clipboard):
    from murmur.inject import Injector

    clipboard["v"] = "ORIGINAL"
    Injector(paste=True, restore_clipboard_ms=40).inject("typed text ")
    assert clipboard["v"] == "typed text "  # pasted immediately
    time.sleep(0.12)
    assert clipboard["v"] == "ORIGINAL"      # restored after the delay


def test_restore_does_not_clobber_a_fresh_copy(clipboard):
    from murmur.inject import Injector

    clipboard["v"] = "ORIGINAL"
    Injector(paste=True, restore_clipboard_ms=40).inject("dictation ")
    clipboard["v"] = "USER COPIED THIS"      # user copies during the window
    time.sleep(0.12)
    assert clipboard["v"] == "USER COPIED THIS"


def test_restore_disabled_keeps_transcript(clipboard):
    from murmur.inject import Injector

    clipboard["v"] = "ORIGINAL"
    Injector(paste=True, restore_clipboard_ms=-1).inject("kept ")
    time.sleep(0.1)
    assert clipboard["v"] == "kept "
