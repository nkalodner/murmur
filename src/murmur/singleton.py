"""One Murmur at a time.

Two copies running means every dictation gets typed twice, which is exactly
what happens when someone setting Murmur up runs `murmur` again in a second
terminal instead of using the tray. The guard is a socket bound to a fixed
loopback port: the OS hands it to exactly one process, releases it the moment
that process dies (so there is no stale lock file to clean up), and costs
nothing to hold.

Deliberately NOT SO_REUSEADDR: on Windows that flag lets a second process bind
the same address, which would defeat the whole thing. Plain bind fails with
EADDRINUSE on every platform we ship.
"""

from __future__ import annotations

import logging
import socket

log = logging.getLogger("murmur")

HOST = "127.0.0.1"
# Just below the settings server's range (8766-8775) so the two never collide.
LOCK_PORT = 8765


class InstanceLock:
    """Held for the life of the process; released on close() or exit."""

    def __init__(self, port: int = LOCK_PORT):
        self.port = port
        self._sock: socket.socket | None = None

    def acquire(self) -> bool:
        """True if we are the only copy; False if another one holds the lock."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((HOST, self.port))
            sock.listen(1)
        except OSError as e:
            sock.close()
            log.debug("instance lock busy on %s: %s", self.port, e)
            return False
        self._sock = sock
        return True

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
