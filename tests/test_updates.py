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

def test_self_update_refuses_while_murmur_is_running(monkeypatch, capsys):
    # Windows holds the running copy's files open, so uv would fail halfway
    # with a permission error nobody can read. Ask instead.
    from murmur.singleton import InstanceLock

    # self_update() looks for uv before it looks at the lock, so without this
    # stub the test passes or fails on whether the machine happens to have uv
    # installed: green on a dev box, red on a CI runner that has no uv.
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")

    lock = InstanceLock()
    assert lock.acquire()
    try:
        assert updates.self_update() == 1
    finally:
        lock.close()
    assert "Quit it first" in capsys.readouterr().out


def test_self_update_without_uv_says_where_to_get_it(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert updates.self_update() == 1
    out = capsys.readouterr().out
    assert "uv" in out and "astral.sh" in out


def test_self_update_runs_the_reinstall(monkeypatch, capsys):
    seen = {}

    class Done:
        returncode = 0

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr("subprocess.run", lambda cmd, *a, **k: (seen.update(cmd=cmd), Done())[1])
    assert updates.self_update() == 0
    assert seen["cmd"][1:4] == ["tool", "install", "--force"]
    assert seen["cmd"][-1] == updates.INSTALL_URL
    assert "Start Murmur again" in capsys.readouterr().out


def test_self_update_passes_the_failure_code_back(monkeypatch, capsys):
    class Done:
        returncode = 2

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr("subprocess.run", lambda cmd, *a, **k: Done())
    assert updates.self_update() == 2
    assert "did not finish" in capsys.readouterr().out
