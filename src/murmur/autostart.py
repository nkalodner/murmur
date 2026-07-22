"""Start Murmur when you log in. Per-user, no admin, fully reversible.

- Windows: a shortcut to the windowless launcher (murmurw.exe) in the Startup
  folder, with an HKCU ...\\Run registry value as a fallback. Some antivirus /
  "startup manager" tools silently revert Run-key changes from apps they do not
  recognize but leave the Startup folder alone (a sibling app's shortcut
  persists there untouched), so enable() leads with the shortcut and only uses
  the Run key if the shortcut is blocked. It verifies whichever it wrote and
  raises a clear error if both are reverted, so it never reports a success that
  did not actually happen.
- macOS: a LaunchAgent plist in ~/Library/LaunchAgents, loaded with launchctl.
- Linux: unsupported (the app runs there for tests, but has no login story).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger("murmur")

MAC_LABEL = "com.murmur.dictation"
WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WIN_VALUE = "Murmur"

# Shown when both the Startup folder shortcut and the Run key are reverted the
# instant they are written. That is almost always a security tool, so point the
# user at the fix instead of leaving them to guess (the exact hole this whole
# feature fell into once).
_WIN_BLOCKED_MSG = (
    "Windows removed Murmur's startup entry right after it was written (both a "
    "Startup folder shortcut and the registry Run key were reverted). This is "
    "almost always antivirus or a 'startup manager' blocking startup changes "
    "from an app it does not recognize. Allow Murmur (murmurw.exe) in that "
    "tool, or add the shortcut by hand: press Win+R, run 'shell:startup', and "
    "drop a shortcut to murmurw.exe in the folder that opens."
)


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
        # Either mechanism counts: the Run key, or the Startup folder fallback.
        return _win_run_value() is not None or _win_startup_shortcut().exists()
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
        _win_enable(exe)
    elif sys.platform == "darwin":
        _mac_write_plist(exe)
        log.info("Start at login enabled")


def disable() -> None:
    if sys.platform == "win32":
        _win_delete_run()
        _win_startup_shortcut().unlink(missing_ok=True)
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


# -- Windows ---------------------------------------------------------------


def _win_enable(exe: str) -> None:
    """Prefer a Startup-folder shortcut, fall back to the Run key, and raise if
    both are reverted. Security "startup manager" tools watch the Run key far
    more aggressively than the Startup folder (a sibling app's shortcut
    persists there untouched), so leading with the shortcut dodges the revert
    instead of racing it. Never report a success that did not happen."""
    try:
        _win_create_shortcut(exe)
    except Exception as e:
        log.debug("shortcut creation raised: %s", e)
    if _win_startup_shortcut().exists():
        # Drop any old Run-key entry so login does not launch Murmur twice.
        _win_delete_run()
        log.info("Start at login enabled (Startup folder)")
        return
    # The Startup folder was blocked too; try the Run key as a fallback.
    log.warning("Startup folder shortcut did not stick; trying the Run key")
    _win_startup_shortcut().unlink(missing_ok=True)
    _win_write_run(exe)
    if _win_run_value() is not None:
        log.info("Start at login enabled (Run key)")
        return
    raise RuntimeError(_WIN_BLOCKED_MSG)


def _win_run_value() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, WIN_VALUE)
            return value
    except OSError:
        return None


def _win_write_run(exe: str) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY) as key:
        winreg.SetValueEx(key, WIN_VALUE, 0, winreg.REG_SZ, f'"{exe}"')


def _win_delete_run() -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, WIN_VALUE)
    except OSError:
        pass


def _win_startup_shortcut() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return (
        base
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "Murmur.lnk"
    )


def _ps_quote(s: str) -> str:
    """Wrap a string as a PowerShell single-quoted literal: backslashes stay
    literal (so Windows paths survive) and embedded single quotes are doubled."""
    return "'" + s.replace("'", "''") + "'"


def _win_create_shortcut(exe: str) -> None:
    """Create Startup\\Murmur.lnk pointing at murmurw.exe via WScript.Shell.
    Uses PowerShell so we need no pywin32 dependency."""
    shortcut = _win_startup_shortcut()
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(str(shortcut))}); "
        f"$s.TargetPath = {_ps_quote(exe)}; "
        "$s.Save()"
    )
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ],
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        log.debug(
            "shortcut creation exited %s: %s",
            result.returncode,
            result.stderr.decode(errors="replace").strip(),
        )


# -- macOS -----------------------------------------------------------------


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
