"""Tell you when a newer Murmur exists.

Murmur updates by pasting a command, which only works if you know there is
something to update to. Nobody re-reads a changelog on a schedule, so this
checks the public repo and says so in the settings page and the tray.

**The one network request Murmur makes.** Everything else runs offline, and
your speech never leaves the machine, so this is worth being precise about:
the check is a plain GET for a version string. It sends no transcript, no
config, no identifier, and nothing comes back but a number. It is a single
toggle away from off, and it never blocks a recording (it runs on its own
thread and every failure is swallowed).

The version check reads the package's __init__ on the mirror's main branch.
Installs resolve that version to an immutable release tag, so a retry always
uses the same source tree even after main advances.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time

from murmur import __version__
from murmur.config import CONFIG_DIR

log = logging.getLogger("murmur")

VERSION_URL = "https://raw.githubusercontent.com/nkalodner/murmur/main/src/murmur/__init__.py"
CHANGELOG_URL = "https://github.com/nkalodner/murmur#whats-new"
TROUBLESHOOTING_URL = "https://github.com/nkalodner/murmur"
CACHE_PATH = CONFIG_DIR / "update.json"
# Release tags are created by the monorepo's mirror workflow. Keep the
# current-version URL as a stable public constant for diagnostics and tests;
# self_update resolves the newest checked version before replacing anything.
RELEASE_ARCHIVE = "https://github.com/nkalodner/murmur/archive/refs/tags/v{version}.zip"
INSTALL_URL = RELEASE_ARCHIVE.format(version=__version__)

CHECK_INTERVAL = 24 * 60 * 60  # once a day is plenty for a hand-updated tool
TIMEOUT = 6.0

_VERSION_RE = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")


def parse_version(text: str) -> tuple[int, ...] | None:
    """'0.10.2' -> (0, 10, 2). None when it is not a plain numeric version."""
    if not isinstance(text, str):
        return None
    parts = text.strip().split(".")
    if not parts or len(parts) > 4:
        return None
    out = []
    for part in parts:
        if not part.isdigit():
            return None  # a suffix like 1.0.0rc1: do not guess, just skip
        out.append(int(part))
    return tuple(out)


def is_newer(latest: str, current: str = __version__) -> bool:
    """True only when both parse and latest sorts above current.

    Numeric tuples, so 0.10.0 correctly beats 0.9.0 where a string compare
    would not.
    """
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def fetch_latest(timeout: float = TIMEOUT) -> str | None:
    """The version on main, or None if the network or the file disagrees."""
    import urllib.request

    req = urllib.request.Request(
        VERSION_URL,
        headers={"User-Agent": f"murmur/{__version__}", "Accept": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        body = res.read(8192).decode("utf-8", "replace")
    match = _VERSION_RE.search(body)
    return match.group(1) if match else None


def load_cache() -> dict:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(data: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        log.debug("could not write %s: %s", CACHE_PATH, e)


def status() -> dict:
    """What the settings page renders. Cache only, never touches the network."""
    cache = load_cache()
    latest = cache.get("latest")
    return {
        "current": __version__,
        "latest": latest,
        "available": bool(latest) and is_newer(latest),
        "checked_at": cache.get("checked_at"),
        "changelog": CHANGELOG_URL,
    }


def check(force: bool = False, now: float | None = None) -> dict:
    """Refresh the cached version if it is stale. Returns status()."""
    stamp = time.time() if now is None else now
    cache = load_cache()
    last = cache.get("checked_at")
    # `last > 0` matters: a missing timestamp reads as 0, and without this the
    # age of a never-checked cache is just `stamp`, which looks fresh for any
    # small clock value. A stamp before `last` (clock moved back) reads as
    # stale, which only costs one extra request.
    fresh = (
        isinstance(last, (int, float))
        and not isinstance(last, bool)
        and last > 0
        and 0 <= stamp - last < CHECK_INTERVAL
    )
    if not force and fresh:
        return status()
    try:
        latest = fetch_latest()
    except Exception as e:
        # Offline, blocked, GitHub down: not worth a word to the user.
        log.debug("update check failed: %s", e)
        return status()
    if latest:
        save_cache({"checked_at": stamp, "latest": latest})
        if is_newer(latest):
            log.info(
                "Murmur %s is available (you have %s). Update: see %s",
                latest,
                __version__,
                CHANGELOG_URL,
            )
    return status()


def check_in_background() -> None:
    """Fire and forget at startup, so nothing waits on the network."""

    def run():
        try:
            check()
        except Exception as e:
            log.debug("background update check failed: %s", e)

    threading.Thread(target=run, name="murmur-update-check", daemon=True).start()


def stop_running_instance(timeout: float = 15.0) -> bool:
    """Ask a running Murmur to quit and wait for it to let go of the lock.

    True when nothing holds the lock any more, which includes the case where
    nothing was running to begin with. The wait matters: uv must not start
    replacing files until the old process is genuinely gone.
    """
    import urllib.request

    from murmur.server import find_running_instance
    from murmur.singleton import InstanceLock

    url = find_running_instance()
    if url:
        try:
            req = urllib.request.Request(
                f"{url}/api/quit",
                data=b"{}",
                headers={"Content-Type": "application/json", "X-Murmur": "1"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            log.debug("quit request failed: %s", e)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lock = InstanceLock()
        if lock.acquire():
            lock.close()
            return True
        time.sleep(0.25)
    return False


def _updated_line(restarted: bool) -> str:
    return (
        "Updated, and Murmur is running again."
        if restarted
        else "Updated. Start Murmur again to run the new version."
    )


def _launcher() -> str | None:
    """The windowless launcher, for putting Murmur back after an update."""
    import shutil

    return shutil.which("murmurw") or shutil.which("murmur")


def self_update(source: str | None = None) -> int:
    """Reinstall Murmur over itself. Returns a process exit code.

    Updating used to be four manual steps (quit, pull, reinstall, relaunch),
    which is three too many for anyone who did not install it themselves, so
    most people simply never updated. Installing from the published archive
    keeps that to one command: there is no checkout to locate and no path to
    remember, and uv fetches, builds, and swaps the tool in place.

    The one step that cannot be automated is the quit: a running copy holds
    its own files open on Windows, so the reinstall would fail halfway. The
    instance lock already knows whether a copy is up, so this asks rather
    than letting uv fail with a file-permission error nobody can read.

    Windows needs one more dodge even with nothing else running: see
    _reinstall_detached.
    """
    import shutil

    from murmur.singleton import InstanceLock

    uv = shutil.which("uv")
    if not uv:
        print("Cannot find uv, which is what installs Murmur.")
        print("Install it from https://docs.astral.sh/uv/, open a new terminal, and try again.")
        return 1

    if source is None:
        try:
            source = _release_source()
        except UpdateUnavailable as e:
            print(str(e))
            return 1

    lock = InstanceLock()
    was_running = not lock.acquire()
    lock.close()  # uv does the work; holding the port would only block the relaunch
    if was_running:
        # Windows cannot replace files the running copy holds open, so it has
        # to go. Closing it here rather than making you do it by hand is the
        # whole point; it comes back by itself once the swap is done.
        print("Closing the running copy...")
        if not stop_running_instance():
            print("Murmur is running and did not close when asked.")
            print("Quit it from the menu bar or tray icon, then run this again.")
            return 1

    print(f"Updating Murmur from {__version__}...")
    if sys.platform == "win32":
        return _reinstall_detached(uv, source, restart=was_running)
    return _reinstall_here(uv, source, restart=was_running)


def _same_python() -> list[str]:
    """`--python` args pinning the update to the interpreter already in use.

    Left to itself uv re-picks a default interpreter, and on Windows that
    is often the Microsoft Store python. Its environments carry reparse
    points uv cannot delete, so the NEXT update dies with os error 4395
    ("the object manager encountered a reparse point") and the launcher
    stops resolving its script path. Staying on the interpreter that is
    demonstrably working avoids inheriting that.
    """
    from pathlib import Path

    base = Path(sys.base_prefix)
    exe = base / ("python.exe" if sys.platform == "win32" else "bin/python3")
    if exe.exists():
        return ["--python", str(exe)]
    return ["--python", f"{sys.version_info.major}.{sys.version_info.minor}"]


def _reinstall_here(uv: str, source: str, restart: bool = False) -> int:
    """Run uv and wait for it. Correct everywhere except Windows."""
    import subprocess

    try:
        done = subprocess.run(
            [uv, "tool", "install", "--force", "--reinstall", *_same_python(), source]
        )
    except Exception as e:  # noqa: BLE001 - any failure here is the same message
        print(f"Could not run uv: {e}")
        return 1
    if done.returncode != 0:
        print()
        print("The update did not finish. Troubleshooting: " + TROUBLESHOOTING_URL)
        return done.returncode

    CACHE_PATH.unlink(missing_ok=True)  # the banner is about a version we just left
    print()
    launcher = _launcher() if restart else None
    if launcher:
        try:
            # start_new_session already detaches it; --foreground stops it
            # bouncing through the handoff a second time on the way up.
            subprocess.Popen([launcher, "--foreground"], start_new_session=True)
            print(_updated_line(True))
        except Exception as e:  # noqa: BLE001 - it updated; only the relaunch failed
            log.debug("relaunch failed: %s", e)
            print(_updated_line(False))
    else:
        print(_updated_line(False))
    print(f"What changed: {CHANGELOG_URL}")
    return 0


class UpdateUnavailable(RuntimeError):
    """Raised when an in-app update cannot even start; the message says why."""


def _release_source() -> str:
    """Resolve the newest published version to its immutable release tag."""
    info = check(force=True)
    latest = info.get("latest")
    if not isinstance(latest, str) or parse_version(latest) is None:
        raise UpdateUnavailable(
            "Could not determine the latest release. Check your connection and try again."
        )
    return RELEASE_ARCHIVE.format(version=latest)


def spawn_detached_update(uv: str, source: str, restart: bool) -> None:
    """Start a process that outlives this one to run the reinstall.

    The current process holds files uv has to replace (Windows refuses to
    delete a running executable; POSIX is happier, but an in-app update is
    replacing the very app that asked for it), so the swap must happen
    after this PID has exited. The helper waits for that, runs uv pinned to
    the interpreter already in use, and puts Murmur back if asked to.

    Windows gets a PowerShell in its own window so the output is visible.
    POSIX gets sh with output appended to ~/.murmur/update.log.
    """
    import os
    import subprocess

    launcher = _launcher() if restart else None
    if sys.platform == "win32":
        def q(value: str) -> str:  # a PowerShell single-quoted literal
            return "'" + value.replace("'", "''") + "'"

        script = "; ".join(
            [
                f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue",
                # The uv trampoline that launched us outlives the python it ran
                # by a beat, and uv is about to overwrite that very file.
                "Start-Sleep -Milliseconds 500",
                " ".join(
                    [f"& {q(uv)} tool install --force --reinstall"]
                    # The flag is a literal; only its value needs quoting.
                    + [a if a.startswith("--") else q(a) for a in _same_python()]
                    + [q(source)]
                ),
                "$code = $LASTEXITCODE",
                # Put Murmur back only if it was up before, and only on a good
                # swap: relaunching a half-replaced install helps nobody.
                (
                    f"if ($code -eq 0) {{ Start-Process -FilePath {q(launcher)} }}"
                    if launcher
                    else "$null = $code"
                ),
                "if ($code -eq 0) {"
                f" Write-Host ''; Write-Host {q(_updated_line(bool(launcher)))};"
                f" Write-Host {q('What changed: ' + CHANGELOG_URL)} "
                "} else {"
                f" Write-Host ''; Write-Host 'The update did not finish.';"
                f" Write-Host {q('Troubleshooting: ' + TROUBLESHOOTING_URL)} "
                "}",
                # A success closes itself: leaving a console parked on Enter
                # forever is worse than a window that blinks. A failure waits,
                # because that output is the only place the reason appears.
                "if ($code -eq 0) { Start-Sleep -Seconds 4 } else {"
                " Write-Host ''; Write-Host 'Press Enter to close.'; Read-Host | Out-Null }",
            ]
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            close_fds=True,
        )
        return

    import shlex

    log_path = CONFIG_DIR / "update.log"
    app_log = CONFIG_DIR / "murmur.log"
    parts = [
        f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done",
        "sleep 0.5",
        " ".join(
            [shlex.quote(uv), "tool", "install", "--force", "--reinstall"]
            + [shlex.quote(a) for a in _same_python()]
            + [shlex.quote(source)]
        ),
    ]
    script = "; ".join(parts)
    if launcher:
        # Relaunched already detached and told so, logging where the app
        # normally logs when it has no terminal.
        script += (
            f" && nohup {shlex.quote(launcher)} --foreground "
            f">> {shlex.quote(str(app_log))} 2>&1 &"
        )
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as out:
        subprocess.Popen(
            ["sh", "-c", script],
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )


def _reinstall_detached(uv: str, source: str, restart: bool = False) -> int:
    r"""The Windows half of `murmur --update`.

    `murmur` runs as Scripts\python.exe INSIDE the tool directory uv has to
    replace, and Windows will not delete a running executable. Waiting on uv
    from here therefore destroys the install every time: uv removes Lib and
    both launchers, reaches its own python.exe, stops with "Access is
    denied", and leaves no working murmur at all. So the work is handed to
    a process that waits for this one to exit first.
    """
    try:
        spawn_detached_update(uv, source, restart)
    except Exception as e:  # noqa: BLE001 - the advice is the same whatever failed
        print(f"Could not start the updater: {e}")
        print(f"Run this yourself instead:  uv tool install --force --reinstall {source}")
        return 1

    CACHE_PATH.unlink(missing_ok=True)  # the banner is about a version we are leaving
    print()
    print("Windows will not let Murmur replace its own files while this command")
    print("is running, so the update is finishing in a new window.")
    if restart and _launcher():
        print("Murmur starts again by itself once it is done.")
    print("You can close this one.")
    return 0


def begin_in_app_update(source: str | None = None) -> None:
    """The settings page's Update button. Spawns the updater and returns;
    the caller then shuts the app down so the swap can happen.

    Resolves the newest published version to its immutable release tag unless
    a source is explicitly supplied (primarily useful to tests). Raises
    UpdateUnavailable with a readable reason when it cannot start.
    """
    import shutil

    if source is None:
        source = _release_source()

    uv = shutil.which("uv")
    if not uv:
        raise UpdateUnavailable(
            "Murmur cannot find uv, the tool that installs it. In a terminal, run: "
            f"uv tool install --force --reinstall {source}"
        )
    try:
        spawn_detached_update(uv, source, restart=True)
    except Exception as e:  # noqa: BLE001 - surfaced verbatim on the page
        raise UpdateUnavailable(f"Could not start the updater: {e}") from e
    CACHE_PATH.unlink(missing_ok=True)
