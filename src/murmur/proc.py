"""Start the small system helpers (afplay, osascript, defaults) cheaply.

Python's default way of starting a program on a Mac is fork-then-exec: the
whole process is duplicated first, with every other thread frozen out while
that happens. Murmur holds a speech model of several hundred megabytes and
has a live microphone callback, so each chime, volume change and theme check
stalled all of it for the length of that copy. Given a full path and
close_fds=False, subprocess uses posix_spawn on macOS instead, which starts
the helper directly and duplicates nothing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

_paths: dict[str, str | None] = {}


def which(name: str) -> str | None:
    """shutil.which, remembered: these helpers do not move mid-session."""
    if name not in _paths:
        _paths[name] = shutil.which(name)
    return _paths[name]


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run for a short-lived helper, without the fork on macOS."""
    if sys.platform == "darwin":
        full = which(cmd[0])
        if full:
            cmd = [full, *cmd[1:]]
            # Python's own descriptors are close-on-exec already, so nothing
            # of ours leaks into the helper by leaving this off.
            kwargs.setdefault("close_fds", False)
    return subprocess.run(cmd, **kwargs)
