"""The suite's own guard rails (conftest.py) hold: no network, no real ~/.murmur."""
from pathlib import Path

import murmur.app
import murmur.config
import murmur.doctor
import murmur.server
from murmur import updates


def test_no_path_points_at_the_real_settings_folder(murmur_home):
    real = Path.home() / ".murmur"
    paths = [
        murmur.config.CONFIG_DIR,
        murmur.config.CONFIG_PATH,
        murmur.config.HISTORY_PATH,
        murmur.config.load.__defaults__[0],
        murmur.config.save.__defaults__[0],
        murmur.app.HISTORY_PATH,
        murmur.doctor.CONFIG_PATH,
        murmur.server.HISTORY_PATH,
        updates.CONFIG_DIR,
        updates.CACHE_PATH,
    ]
    for path in paths:
        assert path == murmur_home or murmur_home in path.parents, path
        assert path != real and real not in path.parents, path


def test_the_version_check_runs_against_the_fake(version_fetches):
    info = updates.check(force=True)
    assert version_fetches, "the real fetch_latest ran"
    assert info["latest"] == updates.__version__ and info["available"] is False
