"""murmur --doctor: check mic, model cache, permissions, clipboard."""

from __future__ import annotations

import platform
import sys

from murmur import __version__
from murmur.config import CONFIG_PATH, Config


def _line(ok: bool | None, label: str, detail: str = "") -> None:
    mark = {True: "ok", False: "FAIL", None: "--"}[ok]
    print(f"  [{mark:>4}] {label}" + (f": {detail}" if detail else ""))


def run(cfg: Config) -> int:
    print(f"murmur {__version__} on {platform.platform()} / Python {sys.version.split()[0]}")
    print(f"  config: {CONFIG_PATH}")
    print(f"  model: {cfg.model} ({cfg.quantization or 'fp32'})  hotkey: {cfg.hotkey}")

    try:
        from murmur.audio import find_input_device, list_input_devices

        devices = list_input_devices()
        if devices:
            _line(True, f"{len(devices)} input device(s)", "run --list-devices for the list")
        else:
            _line(False, "no input devices found")
        find_input_device(cfg.device)
        if cfg.device:
            _line(True, f"configured device {cfg.device!r} found")
    except Exception as e:
        _line(False, "audio", str(e))

    try:
        from huggingface_hub import scan_cache_dir

        tail = cfg.model.split("/")[-1].replace("nemo-", "")
        cached = [
            f"{r.repo_id} ({r.size_on_disk / 1e6:.0f} MB)"
            for r in scan_cache_dir().repos
            if tail in r.repo_id
        ]
        if cached:
            _line(True, "model cached", ", ".join(cached))
        else:
            _line(None, "model not downloaded yet", "run: murmur --download")
    except Exception as e:
        _line(None, "model cache scan failed", str(e))

    if sys.platform == "darwin":
        from murmur.macos import preflight

        problems = preflight()
        if problems:
            for p in problems:
                lines = p.splitlines()
                _line(False, lines[0])
                for extra in lines[1:]:
                    print("        " + extra.strip())
        else:
            _line(True, "macOS permissions look good")

    try:
        import pyperclip

        try:
            before = pyperclip.paste()
        except Exception:
            before = None
        pyperclip.copy("murmur-doctor")
        ok = pyperclip.paste() == "murmur-doctor"
        if before is not None:
            pyperclip.copy(before)
        _line(ok, "clipboard round trip")
    except Exception as e:
        _line(False, "clipboard", str(e))

    try:
        from murmur.hotkey import parse_hotkey

        parse_hotkey(cfg.hotkey)
        _line(True, f"hotkey {cfg.hotkey!r} parses")
    except Exception as e:
        _line(False, f"hotkey {cfg.hotkey!r}", str(e))

    from murmur import autostart

    status = autostart.status()
    if status["supported"]:
        _line(status["enabled"] or None, "start at login", "on" if status["enabled"] else "off")
    else:
        _line(None, "start at login", "not available on this OS")

    from murmur.server import find_running_instance

    running = find_running_instance()
    if running:
        _line(True, "already running", f"settings at {running}")
    else:
        _line(None, "not running", "start it with: murmur")

    print("Doctor checks the environment only. For a live test, run murmur and dictate into a text box.")
    return 0
