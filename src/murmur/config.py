"""Config file handling (~/.murmur/config.json)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger("murmur")

CONFIG_DIR = Path.home() / ".murmur"
CONFIG_PATH = CONFIG_DIR / "config.json"
HISTORY_PATH = CONFIG_DIR / "history.jsonl"


@dataclass
class Config:
    hotkey: str = "ctrl_r"  # hold to talk; a quick tap locks hands-free
    model: str = "nemo-parakeet-tdt-0.6b-v2"  # v3 is the multilingual variant
    quantization: str | None = "int8"  # null = full precision (bigger download, slower on CPU)
    language: str | None = None  # only read by whisper/canary models; parakeet v3 auto-detects
    device: str | None = None  # input device name substring; null = system default mic
    sounds: bool = True
    paste: bool = True  # false = type character by character instead of pasting
    restore_clipboard_ms: int = 600  # delay before restoring the previous clipboard; -1 = never restore
    tap_lock_ms: int = 350  # a press shorter than this locks hands-free recording
    max_seconds: int = 120  # auto-stop a recording after this long
    trailing_space: bool = True  # append a space so the next dictation flows on
    history: bool = True  # append transcripts to ~/.murmur/history.jsonl
    pill: bool = True  # show the floating recording pill (Windows/Linux)
    # Personal dictionary: words/phrases spelled the way you want them typed
    # (fuzzy-matched against each transcript), plus exact heard->typed pairs.
    vocabulary: list[str] = field(default_factory=list)
    replacements: list[dict] = field(default_factory=list)  # {"from": "...", "to": "..."}
    vocab_threshold: float = 0.82  # 0..1; higher = stricter vocabulary matching


def load(path: Path = CONFIG_PATH) -> Config:
    """Load config, creating the file with defaults on first run."""
    if not path.exists():
        try:
            save(Config(), path)
        except OSError as e:
            log.warning("Could not write default config to %s: %s", path, e)
        return Config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Could not read %s (%s); using defaults", path, e)
        return Config()
    if not isinstance(data, dict):
        log.warning("Config %s is not a JSON object; using defaults", path)
        return Config()
    known = {f.name for f in fields(Config)}
    for key in sorted(set(data) - known):
        log.warning("Ignoring unknown config key %r in %s", key, path)
    return Config(**{k: v for k, v in data.items() if k in known})


def save(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")


def _int_in(name: str, value, lo: int, hi: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{name} must be a whole number between {lo} and {hi}")


def validate(cfg: Config) -> None:
    """Raise ValueError on values the app can't run with (used by the settings server)."""
    if not isinstance(cfg.hotkey, str) or not cfg.hotkey.strip():
        raise ValueError("hotkey must be a non-empty string")
    if not isinstance(cfg.model, str) or not cfg.model.strip():
        raise ValueError("model must be a non-empty string")
    for name in ("quantization", "language", "device"):
        value = getattr(cfg, name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be a string or null")
    for name in ("sounds", "paste", "trailing_space", "history", "pill"):
        if not isinstance(getattr(cfg, name), bool):
            raise ValueError(f"{name} must be true or false")
    _int_in("tap_lock_ms", cfg.tap_lock_ms, 50, 2000)
    _int_in("max_seconds", cfg.max_seconds, 5, 1800)
    _int_in("restore_clipboard_ms", cfg.restore_clipboard_ms, -1, 60000)
    if isinstance(cfg.vocab_threshold, bool) or not isinstance(cfg.vocab_threshold, (int, float)):
        raise ValueError("vocab_threshold must be a number between 0.5 and 1")
    if not 0.5 <= float(cfg.vocab_threshold) <= 1.0:
        raise ValueError("vocab_threshold must be between 0.5 and 1")
    if not isinstance(cfg.vocabulary, list) or not all(isinstance(v, str) for v in cfg.vocabulary):
        raise ValueError("vocabulary must be a list of strings")
    if not isinstance(cfg.replacements, list) or not all(
        isinstance(p, dict)
        and isinstance(p.get("from", ""), str)
        and isinstance(p.get("to", ""), str)
        for p in cfg.replacements
    ):
        raise ValueError('replacements must be a list of {"from": ..., "to": ...} objects')
