"""Hotkey parsing, chords, and live retargeting. Needs a display for pynput's
backend, so the whole module skips where none is available (e.g. a headless box
without Xvfb); CI runs it under xvfb-run.

split_binding is pure string work and is covered in test_config.py, which runs
everywhere."""
import pytest

try:
    import pynput.keyboard  # noqa: F401  (loads the backend; fails without a display)

    from murmur.hotkey import Binding, HotkeyListener, parse_hotkey
except Exception as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"pynput backend unavailable: {exc}", allow_module_level=True)


def key(name):
    return parse_hotkey(name)


def test_parse_valid_names():
    for name in ("ctrl_r", "alt_r", "cmd_r", "f8", "a"):
        assert parse_hotkey(name) is not None


def test_parse_rejects_bad_names():
    with pytest.raises(ValueError):
        parse_hotkey("")
    with pytest.raises(ValueError):
        parse_hotkey("not_a_key")


# ── single-key bindings ────────────────────────────────────────────────


def test_single_key_completes_and_breaks():
    b = Binding("ctrl_r")
    assert b.press(key("ctrl_r"), None) == (True, True)
    assert b.complete and b.any_down
    assert b.release(key("ctrl_r"), None) is True
    assert not b.complete and not b.any_down


def test_key_repeat_does_not_re_fire():
    b = Binding("ctrl_r")
    b.press(key("ctrl_r"), None)
    # The OS repeats a held key; only the first press may report "complete".
    assert b.press(key("ctrl_r"), None) == (True, False)


def test_unrelated_key_is_ignored():
    b = Binding("ctrl_r")
    assert b.press(key("f8"), None) == (False, False)
    assert not b.complete


# ── chords ──────────────────────────────────────────────────────────────


def test_chord_needs_every_key_before_it_fires():
    b = Binding("ctrl_r+space")
    assert b.press(key("ctrl_r"), None) == (True, False)  # half of it is not enough
    assert not b.complete
    assert b.press(key("space"), None) == (True, True)
    assert b.complete


def test_chord_breaks_when_any_key_lifts():
    b = Binding("ctrl_r+space")
    b.press(key("ctrl_r"), None)
    b.press(key("space"), None)
    assert b.release(key("space"), None) is True
    assert not b.complete
    assert b.any_down  # ctrl_r is still held, so pasting must still wait


def test_chord_order_does_not_matter():
    b = Binding("ctrl_r+space")
    b.press(key("space"), None)
    assert b.press(key("ctrl_r"), None)[1] is True


def test_releasing_a_key_that_never_completed_reports_nothing():
    b = Binding("ctrl_r+space")
    b.press(key("ctrl_r"), None)
    assert b.release(key("ctrl_r"), None) is False


def test_binding_rejects_too_many_keys_and_repeats():
    with pytest.raises(ValueError):
        Binding("ctrl_r+space+f8+alt_r")
    with pytest.raises(ValueError):
        Binding("ctrl_r+ctrl_r")


# ── the listener: two bindings at once ──────────────────────────────────


class Spy:
    def __init__(self):
        self.presses = self.releases = self.cancels = 0

    def listener(self, hotkey="ctrl_r", hotkey2=None):
        return HotkeyListener(
            hotkey,
            lambda: setattr(self, "presses", self.presses + 1),
            lambda: setattr(self, "releases", self.releases + 1),
            lambda: setattr(self, "cancels", self.cancels + 1),
            hotkey2=hotkey2,
        )


def test_either_binding_starts_a_take():
    spy = Spy()
    ear = spy.listener("ctrl_r", "cmd+shift")
    ear._handle_press(key("ctrl_r"))
    assert spy.presses == 1
    ear._handle_release(key("ctrl_r"))
    assert spy.releases == 1
    # Now the chord, on the same listener.
    ear._handle_press(key("cmd"))
    assert spy.presses == 1  # half a chord does nothing
    ear._handle_press(key("shift"))
    assert spy.presses == 2
    ear._handle_release(key("shift"))
    assert spy.releases == 2


def test_second_binding_mid_take_does_not_double_fire():
    spy = Spy()
    ear = spy.listener("ctrl_r", "f8")
    ear._handle_press(key("ctrl_r"))
    ear._handle_press(key("f8"))
    assert spy.presses == 1  # one recording, not two
    ear._handle_release(key("f8"))
    assert spy.releases == 0  # the take belongs to ctrl_r
    ear._handle_release(key("ctrl_r"))
    assert spy.releases == 1


def test_hotkey_down_waits_for_every_chord_key():
    """The injector waits on this; a held modifier would mangle Cmd+V."""
    spy = Spy()
    ear = spy.listener("ctrl_r+space")
    ear._handle_press(key("ctrl_r"))
    ear._handle_press(key("space"))
    ear._handle_release(key("space"))
    assert ear.hotkey_down is True  # ctrl_r still physically down
    ear._handle_release(key("ctrl_r"))
    assert ear.hotkey_down is False


def test_esc_cancels_but_not_when_it_is_the_hotkey():
    spy = Spy()
    ear = spy.listener("ctrl_r")
    ear._handle_press(key("esc"))
    assert spy.cancels == 1
    # A binding that uses a key must own it; esc here belongs to the chord.
    spy2 = Spy()
    ear2 = spy2.listener("ctrl_r", "esc+space")
    ear2._handle_press(key("esc"))
    assert spy2.cancels == 0


def test_retarget_swaps_bindings_and_clears_state():
    spy = Spy()
    ear = spy.listener("ctrl_r")
    ear._handle_press(key("ctrl_r"))
    assert ear.hotkey_down is True
    ear.retarget("f8", "cmd+shift")
    assert ear.hotkey_down is False  # stale held state is dropped
    assert len(ear._bindings) == 2
    ear._handle_press(key("f8"))
    assert spy.presses == 2


def test_retarget_bad_name_raises_before_mutating():
    spy = Spy()
    ear = spy.listener("ctrl_r")
    before = ear._bindings
    with pytest.raises(ValueError):
        ear.retarget("bogus_key")
    assert ear._bindings is before  # unchanged on failure


def test_retarget_can_drop_the_second_binding():
    spy = Spy()
    ear = spy.listener("ctrl_r", "f8")
    ear.retarget("ctrl_r", None)
    assert len(ear._bindings) == 1
    ear._handle_press(key("f8"))
    assert spy.presses == 0
