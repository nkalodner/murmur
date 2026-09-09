"""The settings page's Update button, and the detached updater behind it."""

import os
import subprocess

import pytest

from murmur import updates


def test_posix_updater_waits_for_this_pid_then_reinstalls_then_relaunches(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    monkeypatch.setattr(updates, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(updates, "_launcher", lambda: "/opt/bin/murmur")
    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or object())

    updates.spawn_detached_update("/usr/bin/uv", updates.INSTALL_URL, restart=True)

    assert seen["cmd"][:2] == ["sh", "-c"]
    script = seen["cmd"][-1]
    # The order is the whole point: wait, then swap, then relaunch.
    assert f"kill -0 {os.getpid()}" in script
    assert script.index("kill -0") < script.index("tool install") < script.index("--foreground")
    assert "--python" in script
    assert "/opt/bin/murmur --foreground" in script
    # Detached, so it survives the app it is replacing.
    assert seen["kw"]["start_new_session"] is True
    # Its output goes somewhere a person can read afterwards.
    assert (tmp_path / "update.log").exists()


def test_posix_updater_without_restart_does_not_relaunch(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    monkeypatch.setattr(updates, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(updates, "_launcher", lambda: "/opt/bin/murmur")
    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd) or object())

    updates.spawn_detached_update("/usr/bin/uv", updates.INSTALL_URL, restart=False)
    assert "--foreground" not in seen["cmd"][-1]


def test_windows_updater_goes_through_the_same_door(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates, "_launcher", lambda: r"C:\bin\murmurw.exe")
    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd) or object())

    updates.spawn_detached_update("uv.exe", updates.INSTALL_URL, restart=True)
    assert seen["cmd"][0] == "powershell"
    script = seen["cmd"][-1]
    assert f"Wait-Process -Id {os.getpid()}" in script
    assert "Start-Process -FilePath 'C:\\bin\\murmurw.exe'" in script


def test_in_app_update_explains_itself_when_uv_is_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(updates.UpdateUnavailable) as e:
        updates.begin_in_app_update()
    # The page shows this verbatim, so it has to say what to do instead.
    assert "uv tool install" in str(e.value)


def test_in_app_update_spawns_with_a_restart_and_clears_the_banner(monkeypatch, tmp_path):
    cache = tmp_path / "update.json"
    cache.write_text("{}")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(updates, "CACHE_PATH", cache)
    seen = {}
    monkeypatch.setattr(
        updates, "spawn_detached_update", lambda uv, src, restart: seen.update(uv=uv, restart=restart)
    )

    updates.begin_in_app_update()
    assert seen == {"uv": "/usr/bin/uv", "restart": True}
    assert not cache.exists()  # the banner was about a version we are leaving


def test_in_app_update_wraps_a_spawn_failure_readably(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")

    def boom(*a, **k):
        raise OSError("powershell not found")

    monkeypatch.setattr(updates, "spawn_detached_update", boom)
    with pytest.raises(updates.UpdateUnavailable) as e:
        updates.begin_in_app_update()
    assert "powershell not found" in str(e.value)
