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
    formatting: bool = True  # spoken times/dates/numbers -> written forms (1:00 PM)
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


# ── Dictionary transfer ────────────────────────────────────────────────
# The personal dictionary is the one part of the config worth carrying to
# another machine, so it exports as a small standalone file and imports as
# a merge (existing entries always win, duplicates are skipped).

DICTIONARY_KIND = "murmur-dictionary"


def dictionary_payload(cfg: Config) -> dict:
    """The portable dictionary file: what export writes and import reads.

    vocab_threshold rides along for reference, but import leaves the
    local tuning alone.
    """
    return {
        "kind": DICTIONARY_KIND,
        "version": 1,
        "vocabulary": list(cfg.vocabulary),
        "replacements": [
            {"from": p.get("from", ""), "to": p.get("to", "")} for p in cfg.replacements
        ],
        "vocab_threshold": cfg.vocab_threshold,
    }


def extract_dictionary(data) -> tuple[list[str], list[dict]]:
    """Pull (vocabulary, replacements) out of an uploaded JSON object.

    Accepts a dictionary export or a whole config.json — anything carrying
    the two keys. Raises ValueError with a readable message otherwise.
    Empty entries and pairs with an empty "from" are dropped.
    """
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object (a Murmur dictionary export)")
    vocab = data.get("vocabulary", [])
    repl = data.get("replacements", [])
    if not isinstance(vocab, list) or not all(isinstance(v, str) for v in vocab):
        raise ValueError("vocabulary must be a list of strings")
    if not isinstance(repl, list) or not all(
        isinstance(p, dict)
        and isinstance(p.get("from", ""), str)
        and isinstance(p.get("to", ""), str)
        for p in repl
    ):
        raise ValueError('replacements must be a list of {"from": ..., "to": ...} objects')
    words = [v.strip() for v in vocab if v.strip()]
    pairs = [
        {"from": p.get("from", "").strip(), "to": p.get("to", "")}
        for p in repl
        if p.get("from", "").strip()
    ]
    if not words and not pairs:
        raise ValueError(
            "no vocabulary or replacements found in that file — "
            "export one from Murmur's settings page on the other device"
        )
    return words, pairs


def merge_dictionary(cfg: Config, vocab: list[str], repl: list[dict]) -> tuple[int, int]:
    """Fold imported entries into cfg in place; returns (words, pairs) added.

    Case-insensitive dedupe, and this machine's entries always win — a
    replacement whose "from" already exists here keeps the local "to".
    """
    have_words = {v.lower() for v in cfg.vocabulary}
    words_added = 0
    for word in vocab:
        if word.lower() not in have_words:
            cfg.vocabulary.append(word)
            have_words.add(word.lower())
            words_added += 1
    have_from = {p.get("from", "").strip().lower() for p in cfg.replacements}
    pairs_added = 0
    for pair in repl:
        key = pair["from"].lower()
        if key not in have_from:
            cfg.replacements.append({"from": pair["from"], "to": pair["to"]})
            have_from.add(key)
            pairs_added += 1
    return words_added, pairs_added


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
    for name in ("sounds", "paste", "trailing_space", "history", "pill", "formatting"):
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
