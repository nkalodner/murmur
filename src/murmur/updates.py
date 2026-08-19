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

There are no GitHub releases to read, since the mirror is a force-pushed
subtree split, so the version comes from the one file that always holds the
truth: the package's __init__.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

from murmur import __version__
from murmur.config import CONFIG_DIR

log = logging.getLogger("murmur")

VERSION_URL = "https://raw.githubusercontent.com/nkalodner/murmur/main/src/murmur/__init__.py"
CHANGELOG_URL = "https://github.com/nkalodner/murmur#whats-new"
CACHE_PATH = CONFIG_DIR / "update.json"
# What `murmur --update` reinstalls from. The archive rather than the git URL,
# so updating needs no git and no clone to find: the tarball is the same
# subtree split the mirror publishes, with pyproject.toml at its root.
INSTALL_URL = "https://github.com/nkalodner/murmur/archive/refs/heads/main.zip"

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


def self_update(source: str = INSTALL_URL) -> int:
    """Reinstall Murmur over itself. Returns a process exit code.

    Updating used to be four manual steps (quit, pull, reinstall, relaunch),
    which is three too many for anyone who did not install it themselves, so
    most people simply never updated. Installing from the published archive
    keeps that to one command: there is no checkout to locate and no path to
    remember, and uv fetches, builds, and swaps the tool in place.

    The one step that cannot be automated is the quit: on Windows the running
    copy holds its own files open, so the reinstall would fail halfway. The
    instance lock already knows whether a copy is up, so this asks rather
    than letting uv fail with a file-permission error nobody can read.
    """
    import shutil
    import subprocess

    from murmur.singleton import InstanceLock

    uv = shutil.which("uv")
    if not uv:
        print("Cannot find uv, which is what installs Murmur.")
        print("Install it from https://docs.astral.sh/uv/, open a new terminal, and try again.")
        return 1

    lock = InstanceLock()
    if not lock.acquire():
        print("Murmur is running, and it cannot replace its own files while it is.")
        print("Quit it first (menu bar or tray icon > Quit Murmur), then run this again.")
        return 1
    lock.close()  # uv does the work; holding the port would only block the relaunch

    print(f"Updating Murmur from {__version__}...")
    try:
        done = subprocess.run([uv, "tool", "install", "--force", "--reinstall", source])
    except Exception as e:  # noqa: BLE001 - any failure here is the same message
        print(f"Could not run uv: {e}")
        return 1
    if done.returncode != 0:
        print()
        print("The update did not finish. Troubleshooting: " + CHANGELOG_URL.split("#")[0])
        return done.returncode

    CACHE_PATH.unlink(missing_ok=True)  # the banner is about a version we just left
    print()
    print("Updated. Start Murmur again to run the new version.")
    print(f"What changed: {CHANGELOG_URL}")
    return 0
