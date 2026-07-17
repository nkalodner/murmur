"""Windows start-at-login: the verify-and-fall-back logic.

The registry helpers are patched out, so these run anywhere (no winreg, no real
Startup folder). What is under test is the orchestration in enable(): lead with
the Startup-folder shortcut, fall back to the Run key if the shortcut is
blocked, and refuse to claim success when both are reverted.
"""
import pytest

from murmur import autostart


def _force_win(monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setattr(
        autostart, "_executable", lambda: r"C:\Users\x\.local\bin\murmurw.exe"
    )


def test_shortcut_success_skips_the_run_key(monkeypatch, tmp_path):
    _force_win(monkeypatch)
    shortcut = tmp_path / "Murmur.lnk"
    monkeypatch.setattr(autostart, "_win_startup_shortcut", lambda: shortcut)
    monkeypatch.setattr(autostart, "_win_create_shortcut", lambda exe: shortcut.write_text("lnk"))
    monkeypatch.setattr(autostart, "_win_run_value", lambda: None)
    wrote_run = {"called": False}
    monkeypatch.setattr(
        autostart, "_win_write_run", lambda exe: wrote_run.__setitem__("called", True)
    )
    deleted_run = {"called": False}
    monkeypatch.setattr(
        autostart, "_win_delete_run", lambda: deleted_run.__setitem__("called", True)
    )

    autostart.enable()

    assert shortcut.exists()
    assert wrote_run["called"] is False  # the happy path never writes the Run key
    assert deleted_run["called"] is True  # clears any stale Run entry (no double launch)
    assert autostart.is_enabled() is True


def test_falls_back_to_run_key_when_startup_folder_is_blocked(monkeypatch, tmp_path):
    _force_win(monkeypatch)
    shortcut = tmp_path / "Murmur.lnk"
    monkeypatch.setattr(autostart, "_win_startup_shortcut", lambda: shortcut)
    monkeypatch.setattr(autostart, "_win_create_shortcut", lambda exe: None)  # never appears
    store = {"run": None}
    monkeypatch.setattr(
        autostart, "_win_write_run", lambda exe: store.__setitem__("run", f'"{exe}"')
    )
    monkeypatch.setattr(autostart, "_win_run_value", lambda: store["run"])

    autostart.enable()

    assert not shortcut.exists()
    assert store["run"] is not None
    assert autostart.is_enabled() is True


def test_raises_when_both_mechanisms_are_reverted(monkeypatch, tmp_path):
    _force_win(monkeypatch)
    shortcut = tmp_path / "Murmur.lnk"
    monkeypatch.setattr(autostart, "_win_startup_shortcut", lambda: shortcut)
    monkeypatch.setattr(autostart, "_win_create_shortcut", lambda exe: None)  # never appears
    monkeypatch.setattr(autostart, "_win_write_run", lambda exe: None)
    monkeypatch.setattr(autostart, "_win_run_value", lambda: None)

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
