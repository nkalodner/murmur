"""Config file handling (~/.murmur/config.json)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
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
