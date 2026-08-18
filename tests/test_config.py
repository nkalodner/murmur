"""Config load/save round-trip, unknown-key tolerance, and validation ranges."""
import json

import pytest

from murmur.config import Config, hotkey_specs, load, save, validate
from murmur.hotkey import split_binding


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


# ── hotkeys: split_binding + the two-binding rules ─────────────────────
# Pure string work (no pynput), so these run even on a headless box.


def test_split_binding_single_and_chord():
    assert split_binding("ctrl_r") == ["ctrl_r"]
    assert split_binding("cmd+shift") == ["cmd", "shift"]
    assert split_binding("  CTRL_R + Space ") == ["ctrl_r", "space"]


def test_split_binding_keeps_the_plus_key_itself():
    assert split_binding("+") == ["+"]


@pytest.mark.parametrize("spec", ["", "   ", "ctrl_r+ctrl_r", "a+b+c+d"])
def test_split_binding_rejects(spec):
    with pytest.raises(ValueError):
        split_binding(spec)


def test_validate_accepts_a_second_hotkey():
    validate(Config(hotkey="ctrl_r", hotkey2="cmd+shift"))
    validate(Config(hotkey="ctrl_r", hotkey2=None))
    validate(Config(hotkey="ctrl_r", hotkey2=""))  # blank means "off"


def test_either_slot_can_be_switched_off():
    """Only the chord, no single key: the whole point of making both optional."""
    validate(Config(hotkey=None, hotkey2="cmd+shift"))
    validate(Config(hotkey="", hotkey2="cmd+shift"))
    validate(Config(hotkey="ctrl_r", hotkey2=None))


@pytest.mark.parametrize("cfg", [
    Config(hotkey=None, hotkey2=None),
    Config(hotkey="", hotkey2=""),
    Config(hotkey="   ", hotkey2=None),
])
def test_validate_rejects_both_hotkeys_off(cfg):
    with pytest.raises(ValueError, match="at least one hotkey"):
        validate(cfg)


def test_hotkey_specs_lists_only_the_live_ones():
    assert hotkey_specs(Config(hotkey="ctrl_r", hotkey2="cmd+shift")) == ["ctrl_r", "cmd+shift"]
    assert hotkey_specs(Config(hotkey=None, hotkey2="cmd+shift")) == ["cmd+shift"]
    assert hotkey_specs(Config(hotkey="ctrl_r", hotkey2="")) == ["ctrl_r"]
    assert hotkey_specs(Config(hotkey=None, hotkey2=None)) == []


@pytest.mark.parametrize("cfg", [
    Config(hotkey="ctrl_r", hotkey2="ctrl_r"),          # identical
    Config(hotkey="ctrl_r", hotkey2="ctrl_r+space"),    # primary fires first
    Config(hotkey="ctrl_r+space", hotkey2="ctrl_r"),    # second fires first
    Config(hotkey="ctrl_r", hotkey2=5),                 # not a string
])
def test_validate_rejects_unreachable_hotkey_pairs(cfg):
    with pytest.raises(ValueError):
        validate(cfg)


def test_overlapping_hotkey_error_names_both_keys():
    with pytest.raises(ValueError, match=r"ctrl_r and ctrl_r\+space.*overlap"):
        validate(Config(hotkey="ctrl_r", hotkey2="ctrl_r+space"))


# ── ducking ────────────────────────────────────────────────────────────


def test_validate_accepts_ducking_settings():
    validate(Config(duck_audio=True, duck_percent=0))
    validate(Config(duck_audio=True, duck_percent=100))


@pytest.mark.parametrize("cfg", [
    Config(duck_percent=-1),
    Config(duck_percent=101),
    Config(duck_percent=True),   # a bool is not a level
    Config(duck_audio="yes"),
])
def test_validate_rejects_bad_ducking(cfg):
    with pytest.raises(ValueError):
        validate(cfg)


# ── chime volume ───────────────────────────────────────────────────────


def test_validate_accepts_chime_volume():
    validate(Config(sound_volume=0))
    validate(Config(sound_volume=100))


@pytest.mark.parametrize("cfg", [
    Config(sound_volume=-1),
    Config(sound_volume=101),
    Config(sound_volume=True),   # a bool is not a level
    Config(sound_volume="loud"),
])
def test_validate_rejects_bad_chime_volume(cfg):
    with pytest.raises(ValueError):
        validate(cfg)


def test_new_keys_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(hotkey="f8", hotkey2="cmd+shift", duck_audio=True, duck_percent=35)
    save(cfg, path)
    assert load(path) == cfg


def test_hotkey_off_round_trips(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(hotkey=None, hotkey2="cmd+shift")
    save(cfg, path)
    assert load(path) == cfg
