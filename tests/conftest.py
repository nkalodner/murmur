"""Guard rails for the whole suite: no network, and never the real ~/.murmur.

Every Murmur path that names the settings folder is pointed at a fresh temp
folder for each test, and the version check is faked, so the tests pass
offline and cannot overwrite someone's config, history or update cache.
Tests that care about either still set their own on top of this.
"""
import pytest

import murmur.app
import murmur.config
import murmur.doctor
import murmur.server
import murmur.updates


@pytest.fixture(autouse=True)
def murmur_home(tmp_path, monkeypatch):
    """Point the settings folder, and every name bound to it, at tmp_path."""
    home = tmp_path / "murmur-home"
    config_path = home / "config.json"
    history_path = home / "history.jsonl"

    monkeypatch.setattr(murmur.config, "CONFIG_DIR", home)
    monkeypatch.setattr(murmur.config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(murmur.config, "HISTORY_PATH", history_path)
    # load() and save() took the real path as a default argument at import.
    monkeypatch.setattr(murmur.config.load, "__defaults__", (config_path,))
    monkeypatch.setattr(murmur.config.save, "__defaults__", (config_path,))
    # Modules that imported the paths by name keep their own copies.
    monkeypatch.setattr(murmur.app, "HISTORY_PATH", history_path)
    monkeypatch.setattr(murmur.doctor, "CONFIG_PATH", config_path)
    monkeypatch.setattr(murmur.server, "HISTORY_PATH", history_path)
    monkeypatch.setattr(murmur.updates, "CONFIG_DIR", home)
    monkeypatch.setattr(murmur.updates, "CACHE_PATH", home / "update.json")
    return home


@pytest.fixture(autouse=True)
def version_fetches(monkeypatch):
    """Stand in for the one network request: the latest release is this one.

    Returns the list of calls, so a test can check the fake was what ran.
    """
    calls = []

    def fake_fetch_latest(*args, **kwargs):
        calls.append((args, kwargs))
        return murmur.updates.__version__

    monkeypatch.setattr(murmur.updates, "fetch_latest", fake_fetch_latest)
    return calls
