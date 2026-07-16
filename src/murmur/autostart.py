"""Start Murmur when you log in. Per-user, no admin, fully reversible.

- Windows: an HKCU ...\\Run registry value pointing at the windowless
  launcher (murmurw.exe), so nothing appears on screen but the tray icon.
- macOS: a LaunchAgent plist in ~/Library/LaunchAgents, loaded with launchctl.
- Linux: unsupported (the app runs there for tests, but has no login story).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger("murmur")

MAC_LABEL = "com.murmur.dictation"
WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WIN_VALUE = "Murmur"


def _executable() -> str | None:
    """The best command to launch at login. Prefer the windowless launcher."""
    names = ["murmurw", "murmur"] if sys.platform == "win32" else ["murmur"]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def supported() -> bool:
    return sys.platform in ("win32", "darwin")


def status() -> dict:
    try:
        return {"supported": supported(), "enabled": is_enabled()}
    except Exception as e:  # never let a status check crash the settings page
        log.debug("autostart status failed: %s", e)
        return {"supported": supported(), "enabled": False}


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY) as key:
                winreg.QueryValueEx(key, WIN_VALUE)
            return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return _mac_plist_path().exists()
    return False


def enable() -> None:
    if not supported():
        raise RuntimeError("Start at login is only available on Windows and macOS.")
    exe = _executable()
    if not exe:
        raise RuntimeError(
            "Could not find the murmur command on PATH. Reinstall with "
            "'uv tool install --reinstall ./murmur', then try again."
        )
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY) as key:
            winreg.SetValueEx(key, WIN_VALUE, 0, winreg.REG_SZ, f'"{exe}"')
    elif sys.platform == "darwin":
        _mac_write_plist(exe)
    log.info("Start at login enabled")


def disable() -> None:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, WIN_VALUE)
        except OSError:
            pass
    elif sys.platform == "darwin":
        path = _mac_plist_path()
        if path.exists():
            subprocess.run(
                ["launchctl", "unload", str(path)],
                capture_output=True,
                check=False,
            )
            path.unlink(missing_ok=True)
    log.info("Start at login disabled")


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def _mac_write_plist(exe: str) -> None:
    log_path = Path.home() / ".murmur" / "murmur.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{MAC_LABEL}</string>
  <key>ProgramArguments</key><array><string>{escape(exe)}</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>{escape(str(log_path))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log_path))}</string>
</dict>
</plist>
"""
    path = _mac_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")
    # Reload so it takes effect now, not just next login.
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
    result = subprocess.run(
        ["launchctl", "load", str(path)], capture_output=True, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"launchctl load failed: {detail or 'unknown error'}")
