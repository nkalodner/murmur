"""Config load/save round-trip, unknown-key tolerance, and validation ranges."""
import json

import pytest

from murmur.config import Config, load, save, validate


def test_load_creates_default_file(tmp_path):
    path = tmp_path / "config.json"
    cfg = load(path)
    assert path.exists()
    assert cfg.hotkey == "ctrl_r" and cfg.model.startswith("nemo-parakeet")


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(hotkey="f8", vocab_threshold=0.9, vocabulary=["Wispr"],
                 replacements=[{"from": "a", "to": "b"}])
    save(cfg, path)
    assert load(path) == cfg


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": "alt_r", "made_up": 1}), encoding="utf-8")
    cfg = load(path)
    assert cfg.hotkey == "alt_r"
    assert not hasattr(cfg, "made_up")


def test_bad_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("not json {", encoding="utf-8")
    assert load(path) == Config()


def test_validate_accepts_defaults():
    validate(Config())  # must not raise


@pytest.mark.parametrize("cfg", [
    Config(hotkey=""),
    Config(model=""),
    Config(tap_lock_ms=10),          # below 50
    Config(max_seconds=99999),       # above 1800
    Config(restore_clipboard_ms=-2), # below -1
    Config(vocab_threshold=0.4),     # below 0.5
    Config(vocab_threshold=True),    # bool is not a number
    Config(sounds="yes"),            # not a bool
    Config(vocabulary=[1, 2]),       # not strings
    Config(replacements=["nope"]),   # not {from,to} dicts
])
def test_validate_rejects_bad_values(cfg):
    with pytest.raises(ValueError):
        validate(cfg)
