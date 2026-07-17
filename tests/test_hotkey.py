"""Hotkey parsing and live retargeting. Needs a display for pynput's backend,
so the whole module skips where none is available (e.g. a headless box without
Xvfb); CI runs it under xvfb-run."""
import pytest

try:
    import pynput.keyboard  # noqa: F401  (loads the backend; fails without a display)

    from murmur.hotkey import HotkeyListener, parse_hotkey
except Exception as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"pynput backend unavailable: {exc}", allow_module_level=True)


def test_parse_valid_names():
    for name in ("ctrl_r", "alt_r", "cmd_r", "f8", "a"):
        assert parse_hotkey(name) is not None


def test_parse_rejects_bad_names():
    with pytest.raises(ValueError):
        parse_hotkey("")
    with pytest.raises(ValueError):
        parse_hotkey("not_a_key")


def test_retarget_swaps_key_and_resets_down():
    listener = HotkeyListener("ctrl_r", lambda: None, lambda: None, lambda: None)
    original = listener._target
    listener._down = True
    listener.retarget("f8")
    assert listener._target != original
    assert listener._down is False


def test_retarget_bad_name_raises_before_mutating():
    listener = HotkeyListener("ctrl_r", lambda: None, lambda: None, lambda: None)
    target = listener._target
    with pytest.raises(ValueError):
        listener.retarget("bogus_key")
    assert listener._target == target  # unchanged on failure
