"""The one-copy-at-a-time lock.

Two Murmurs typing every dictation twice is the bug this prevents, so the
contract worth pinning is narrow: the second acquire fails while the first
holds the port, and the port frees up the moment the holder lets go.
"""
import socket

from murmur.singleton import InstanceLock


def _free_port() -> int:
    """A port nothing is using, so the tests never fight the real 8765."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_first_acquire_wins_and_second_fails():
    port = _free_port()
    first, second = InstanceLock(port), InstanceLock(port)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.close()
        second.close()


def test_close_releases_for_the_next_copy():
    port = _free_port()
    first = InstanceLock(port)
    assert first.acquire() is True
    first.close()
    second = InstanceLock(port)
    try:
        assert second.acquire() is True  # quitting frees the lock, no stale file
    finally:
        second.close()


def test_close_is_idempotent():
    lock = InstanceLock(_free_port())
    assert lock.acquire() is True
    lock.close()
    lock.close()  # must not raise on the second pass (shutdown can run twice)


def test_context_manager_releases():
    port = _free_port()
    with InstanceLock(port) as lock:
        assert lock.acquire() is True
    assert InstanceLock(port).acquire() is True


def test_acquire_fails_against_a_foreign_listener():
    """A non-Murmur process on the port still counts as taken."""
    port = _free_port()
    squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squatter.bind(("127.0.0.1", port))
    squatter.listen(1)
    try:
        assert InstanceLock(port).acquire() is False
    finally:
        squatter.close()
