"""Windows start-at-login: the verify-and-fall-back logic.

The registry helpers are patched out, so these run anywhere (no winreg, no real
Startup folder). What is under test is the orchestration in enable(): confirm
the write survived, fall back to a Startup-folder shortcut if not, and refuse to
claim success when both are reverted.
"""
import pytest

from murmur import autostart


def _force_win(monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setattr(
        autostart, "_executable", lambda: r"C:\Users\x\.local\bin\murmurw.exe"
    )


def test_run_key_success_skips_the_shortcut(monkeypatch, tmp_path):
    _force_win(monkeypatch)
    store = {"run": None}
    monkeypatch.setattr(
        autostart, "_win_write_run", lambda exe: store.__setitem__("run", f'"{exe}"')
    )
    monkeypatch.setattr(autostart, "_win_run_value", lambda: store["run"])
    monkeypatch.setattr(autostart, "_win_startup_shortcut", lambda: tmp_path / "Murmur.lnk")
    called = {"shortcut": False}
    monkeypatch.setattr(
        autostart, "_win_create_shortcut", lambda exe: called.__setitem__("shortcut", True)
    )

    autostart.enable()

    assert store["run"] is not None
    assert called["shortcut"] is False  # the happy path never touches the fallback
    assert autostart.is_enabled() is True


def test_falls_back_to_shortcut_when_run_key_is_reverted(monkeypatch, tmp_path):
    _force_win(monkeypatch)
    # A guard that instantly reverts the Run write: the value never sticks.
    monkeypatch.setattr(autostart, "_win_write_run", lambda exe: None)
    monkeypatch.setattr(autostart, "_win_run_value", lambda: None)
    shortcut = tmp_path / "Murmur.lnk"
    monkeypatch.setattr(autostart, "_win_startup_shortcut", lambda: shortcut)
    monkeypatch.setattr(autostart, "_win_create_shortcut", lambda exe: shortcut.write_text("lnk"))

    autostart.enable()

    assert shortcut.exists()
    assert autostart.is_enabled() is True


def test_raises_when_both_mechanisms_are_reverted(monkeypatch, tmp_path):
    _force_win(monkeypatch)
    monkeypatch.setattr(autostart, "_win_write_run", lambda exe: None)
    monkeypatch.setattr(autostart, "_win_run_value", lambda: None)
    shortcut = tmp_path / "Murmur.lnk"
    monkeypatch.setattr(autostart, "_win_startup_shortcut", lambda: shortcut)
    # Shortcut creation "runs" but the file never appears (it was reverted too).
    monkeypatch.setattr(autostart, "_win_create_shortcut", lambda exe: None)

    with pytest.raises(RuntimeError):
        autostart.enable()

    assert autostart.is_enabled() is False


def test_ps_quote_keeps_backslashes_and_escapes_quotes():
    assert autostart._ps_quote(r"C:\a\b.exe") == r"'C:\a\b.exe'"
    assert autostart._ps_quote("o'brien") == "'o''brien'"


def test_startup_shortcut_path_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert autostart._win_startup_shortcut() == (
        tmp_path
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "Murmur.lnk"
    )
