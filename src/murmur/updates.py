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
