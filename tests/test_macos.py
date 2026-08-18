"""macOS permission helpers: the pure restart rule, and safe non-mac behavior."""
import pytest

from murmur.macos import permission_status, restart_needed


def test_permission_status_shape():
    # On any platform the keys exist; off macOS both are None (unknown), and
    # the call must never raise or prompt.
    status = permission_status()
    assert set(status) == {"accessibility", "input_monitoring"}
    for v in status.values():
        assert v is None or isinstance(v, bool)


@pytest.mark.parametrize("at_start,now,needed", [
    ({"input_monitoring": False}, {"input_monitoring": True}, True),   # granted after launch
    ({"input_monitoring": False}, {"input_monitoring": False}, False), # still missing
    ({"input_monitoring": True}, {"input_monitoring": True}, False),   # fine all along
    ({"input_monitoring": None}, {"input_monitoring": True}, False),   # unknown at start
    ({"input_monitoring": False}, {"input_monitoring": None}, False),  # unknown now
    ({}, {}, False),                                                   # not macOS
    # Accessibility is checked per event, so it never forces a restart.
    ({"accessibility": False}, {"accessibility": True}, False),
])
def test_restart_needed(at_start, now, needed):
    assert restart_needed(at_start, now) is needed
