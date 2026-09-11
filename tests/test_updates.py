"""Update checking: version comparison, caching, and failing quietly.

No test here touches the network. fetch_latest is stubbed everywhere, since
the contract that matters is that a failed check costs the user nothing.
"""
import json

import pytest

from murmur import updates


@pytest.fixture(autouse=True)
def cache_in_tmp(tmp_path, monkeypatch):
    """Never read or write the real ~/.murmur/update.json."""
    monkeypatch.setattr(updates, "CACHE_PATH", tmp_path / "update.json")
    # Keep self-update tests offline while production resolves an immutable
    # release tag from the latest-version check.
    monkeypatch.setattr(updates, "_release_source", lambda: updates.INSTALL_URL)
    return tmp_path / "update.json"


# ── version parsing and comparison ──────────────────────────────────────


@pytest.mark.parametrize("text,want", [
    ("0.7.0", (0, 7, 0)),
    ("1.2", (1, 2)),
    ("  0.8.1  ", (0, 8, 1)),
])
def test_parse_version(text, want):
    assert updates.parse_version(text) == want


@pytest.mark.parametrize("text", ["", "abc", "1.0.0rc1", "0.7.x", None, "1.2.3.4.5", "1..2"])
def test_parse_version_rejects_junk(text):
    assert updates.parse_version(text) is None


def test_is_newer_compares_numerically_not_as_strings():
    """0.10.0 beats 0.9.0, which a string compare gets backwards."""
    assert updates.is_newer("0.10.0", "0.9.0") is True
    assert updates.is_newer("0.9.0", "0.10.0") is False


@pytest.mark.parametrize("latest,current,want", [
    ("0.8.0", "0.7.0", True),
    ("0.7.1", "0.7.0", True),
    ("0.7.0", "0.7.0", False),
    ("0.6.0", "0.7.0", False),
    ("garbage", "0.7.0", False),   # unparseable: never claim an update
    ("0.8.0", "garbage", False),
])
def test_is_newer(latest, current, want):
    assert updates.is_newer(latest, current) is want


# ── check() and the cache ───────────────────────────────────────────────


def test_check_stores_the_result(monkeypatch, cache_in_tmp):
    monkeypatch.setattr(updates, "fetch_latest", lambda *a, **k: "9.9.9")
    info = updates.check(now=1000.0)
    assert info["latest"] == "9.9.9" and info["available"] is True
    assert json.loads(cache_in_tmp.read_text())["latest"] == "9.9.9"


def test_check_skips_the_network_while_the_cache_is_fresh(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "fetch_latest", lambda *a, **k: calls.append(1) or "9.9.9")
    updates.check(now=1000.0)
    updates.check(now=1000.0 + 60)  # a minute later
    assert len(calls) == 1


def test_check_refreshes_once_the_cache_is_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "fetch_latest", lambda *a, **k: calls.append(1) or "9.9.9")
    updates.check(now=1000.0)
    updates.check(now=1000.0 + updates.CHECK_INTERVAL + 1)
    assert len(calls) == 2


def test_force_ignores_the_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "fetch_latest", lambda *a, **k: calls.append(1) or "9.9.9")
    updates.check(now=1000.0)
    updates.check(force=True, now=1000.0)
    assert len(calls) == 2


def test_a_failed_check_is_swallowed(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(updates, "fetch_latest", boom)
    info = updates.check(now=1000.0)  # must not raise
    assert info["latest"] is None and info["available"] is False


def test_failure_does_not_clobber_a_good_cached_answer(monkeypatch):
    monkeypatch.setattr(updates, "fetch_latest", lambda *a, **k: "9.9.9")
    updates.check(now=1000.0)

    def boom(*a, **k):
        raise OSError("offline now")

    monkeypatch.setattr(updates, "fetch_latest", boom)
    info = updates.check(force=True, now=2000.0)
    assert info["latest"] == "9.9.9"  # the last known answer survives


def test_status_never_hits_the_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("status() must read the cache only")

    monkeypatch.setattr(updates, "fetch_latest", boom)
    info = updates.status()
    assert info["current"] == updates.__version__
    assert info["latest"] is None and info["available"] is False


def test_status_shape_is_what_the_settings_page_expects():
    assert set(updates.status()) == {"current", "latest", "available", "checked_at", "changelog"}


def test_corrupt_cache_is_ignored(cache_in_tmp):
    cache_in_tmp.write_text("not json {")
    assert updates.status()["latest"] is None


def test_cache_holding_a_list_is_ignored(cache_in_tmp):
    cache_in_tmp.write_text("[1, 2, 3]")
    assert updates.load_cache() == {}


# ── parsing the published version file ──────────────────────────────────


def test_version_regex_reads_the_package_init():
    body = '"""Murmur."""\n\n__version__ = "0.8.0"\n'
    assert updates._VERSION_RE.search(body).group(1) == "0.8.0"


def test_version_regex_handles_single_quotes():
    assert updates._VERSION_RE.search("__version__ = '1.2.3'").group(1) == "1.2.3"


def test_version_regex_misses_cleanly_on_an_unexpected_file():
    assert updates._VERSION_RE.search("<html>404</html>") is None


# -- murmur --update ---------------------------------------------------------

def _stub_lock(monkeypatch, acquired: bool):
    """Stand in for the instance lock, so these tests do not depend on
    whether a real Murmur happens to be running on the machine."""
    import murmur.singleton

    class FakeLock:
        def acquire(self):
            return acquired

        def close(self):
            pass

    monkeypatch.setattr(murmur.singleton, "InstanceLock", FakeLock)


def test_self_update_without_uv_says_where_to_get_it(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert updates.self_update() == 1
    out = capsys.readouterr().out
    assert "uv" in out and "astral.sh" in out


def test_in_app_update_resolves_the_latest_release(monkeypatch):
    latest = "https://github.com/nkalodner/murmur/archive/refs/tags/v9.9.9.zip"
    seen = {}
    monkeypatch.setattr(updates, "_release_source", lambda: latest)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(
        updates,
        "spawn_detached_update",
        lambda uv, source, restart: seen.update(
            uv=uv, source=source, restart=restart
        ),
    )

    updates.begin_in_app_update()

    assert seen == {"uv": "/usr/bin/uv", "source": latest, "restart": True}


def test_self_update_runs_the_reinstall(monkeypatch, capsys):
    seen = {}

    class Done:
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda cmd, *a, **k: (seen.update(cmd=cmd), Done())[1])
    assert updates._reinstall_here("/usr/bin/uv", updates.INSTALL_URL) == 0
    assert seen["cmd"][1:4] == ["tool", "install", "--force"]
    assert seen["cmd"][-1] == updates.INSTALL_URL
    assert "Start Murmur again" in capsys.readouterr().out


def test_self_update_passes_the_failure_code_back(monkeypatch, capsys):
    class Done:
        returncode = 2

    monkeypatch.setattr("subprocess.run", lambda cmd, *a, **k: Done())
    assert updates._reinstall_here("/usr/bin/uv", updates.INSTALL_URL) == 2
    assert "did not finish" in capsys.readouterr().out


def test_self_update_picks_the_platform_path(monkeypatch):
    # Windows cannot delete the environment it is running from, so it must
    # never take the branch that waits on uv in-process.
    calls = []
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    _stub_lock(monkeypatch, acquired=True)
    monkeypatch.setattr(updates, "_reinstall_here", lambda *a, **k: calls.append("here") or 0)
    monkeypatch.setattr(updates, "_reinstall_detached", lambda *a, **k: calls.append("detached") or 0)

    monkeypatch.setattr(updates.sys, "platform", "win32")
    updates.self_update()
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    updates.self_update()
    assert calls == ["detached", "here"]


def test_detached_update_waits_for_this_process_before_running_uv(monkeypatch, capsys, tmp_path):
    # The whole point: uv must not start until this PID is gone, or it
    # deletes Lib and both launchers and stops on its own python.exe.
    import os
    import subprocess

    seen = {}
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or object()
    )
    monkeypatch.setattr(updates, "CACHE_PATH", tmp_path / "update.json")
    monkeypatch.setattr(updates.sys, "platform", "win32")
    assert updates._reinstall_detached("uv.exe", updates.INSTALL_URL) == 0

    script = seen["cmd"][-1]
    assert seen["cmd"][0] == "powershell"
    assert f"Wait-Process -Id {os.getpid()}" in script
    assert script.index("Wait-Process") < script.index("tool install")
    assert updates.INSTALL_URL in script
    # Its own window, or the output dies with this console.
    assert seen["kw"]["creationflags"] == getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    assert "new window" in capsys.readouterr().out


def test_detached_update_escapes_a_quote_in_the_uv_path(monkeypatch, tmp_path):
    import subprocess

    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd) or object())
    monkeypatch.setattr(updates, "CACHE_PATH", tmp_path / "update.json")
    monkeypatch.setattr(updates.sys, "platform", "win32")
    updates._reinstall_detached("/opt/o'brien/uv", "src")
    # Doubled, which is how a single quote is escaped in a PowerShell literal.
    assert "'/opt/o''brien/uv'" in seen["cmd"][-1]


def test_the_two_version_strings_agree():
    # __init__ is what --version prints AND what the update check fetches
    # from main, so a bump that misses it means nobody is ever told.
    import re
    from pathlib import Path

    here = Path(updates.__file__).resolve()
    root = next(p for p in here.parents if (p / "pyproject.toml").exists())
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text).group(1)
    assert declared == updates.__version__


def test_the_update_stays_on_the_interpreter_already_in_use():
    # Left to itself uv re-picks a default, and on Windows that can be the
    # Microsoft Store python, whose environments carry reparse points uv
    # cannot delete: the next update then dies with os error 4395.
    import sys

    args = updates._same_python()
    assert args[0] == "--python"
    assert args[1] == sys.base_prefix or args[1].startswith(sys.base_prefix)


def test_both_reinstall_paths_pass_the_interpreter(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(updates, "CACHE_PATH", tmp_path / "update.json")

    seen = {}

    class Done:
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda cmd, *a, **k: (seen.update(cmd=cmd), Done())[1])
    updates._reinstall_here("uv", updates.INSTALL_URL)
    assert "--python" in seen["cmd"]
    assert seen["cmd"][-1] == updates.INSTALL_URL

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(ps=cmd) or object())
    updates._reinstall_detached("uv", updates.INSTALL_URL)
    script = seen["ps"][-1]
    # The flag itself must not be quoted as though it were a path.
    assert " --python '" in script or " --python " in script
    assert "'--python'" not in script


def test_update_closes_the_running_copy_instead_of_refusing(monkeypatch, capsys):
    # Noah's ask: stop making him quit it by hand every time.
    calls = []
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    _stub_lock(monkeypatch, acquired=False)  # something is running
    monkeypatch.setattr(updates, "stop_running_instance", lambda *a, **k: calls.append("stopped") or True)
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    monkeypatch.setattr(
        updates, "_reinstall_here", lambda uv, src, restart=False: calls.append(("here", restart)) or 0
    )

    assert updates.self_update() == 0
    assert calls == ["stopped", ("here", True)]
    assert "Closing the running copy" in capsys.readouterr().out


def test_update_gives_up_when_the_copy_will_not_close(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    _stub_lock(monkeypatch, acquired=False)
    monkeypatch.setattr(updates, "stop_running_instance", lambda *a, **k: False)
    monkeypatch.setattr(updates, "_reinstall_here", lambda *a, **k: 1 / 0)  # must not run

    assert updates.self_update() == 1
    assert "did not close when asked" in capsys.readouterr().out


def test_nothing_running_means_no_restart(monkeypatch):
    seen = {}
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    _stub_lock(monkeypatch, acquired=True)  # nothing was running
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    monkeypatch.setattr(
        updates, "_reinstall_here", lambda uv, src, restart=False: seen.update(restart=restart) or 0
    )
    updates.self_update()
    assert seen["restart"] is False


def test_the_windows_script_relaunches_only_on_a_clean_swap(monkeypatch, tmp_path):
    import subprocess

    seen = {}
    monkeypatch.setattr(updates, "CACHE_PATH", tmp_path / "update.json")
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd) or object())
    monkeypatch.setattr(updates, "_launcher", lambda: "/opt/murmurw")

    updates._reinstall_detached("uv", updates.INSTALL_URL, restart=True)
    script = seen["cmd"][-1]
    assert "Start-Process -FilePath '/opt/murmurw'" in script
    # Guarded by the exit code, so a failed swap does not relaunch a wreck.
    assert "if ($code -eq 0) { Start-Process" in script
    assert "running again" in script

    updates._reinstall_detached("uv", updates.INSTALL_URL, restart=False)
    assert "Start-Process" not in seen["cmd"][-1]


def test_stop_returns_true_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr("murmur.server.find_running_instance", lambda *a, **k: None)
    _stub_lock(monkeypatch, acquired=True)  # not the real one: Murmur may be up
    assert updates.stop_running_instance(timeout=2.0) is True
