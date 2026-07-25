"""Audio ducking: the volume bookkeeping, with the platform backend stubbed.

The real backends (osascript, Core Audio COM) need a machine with speakers, so
these pin the part that has to be right everywhere: the level always comes
back exactly where it was, and a backend that throws costs you nothing.
"""
import pytest

from murmur.ducking import Ducker, supported


class FakeDucker(Ducker):
    """A Ducker whose backend is a plain number instead of the OS."""

    def __init__(self, level=0.8, percent=20, fail=False):
        self.level = level
        self.fail = fail
        self.sets = []
        super().__init__(percent)  # starts the worker thread

    def _get_volume(self):
        if self.fail:
            raise OSError("no audio backend")
        return self.level

    def _set_volume(self, level):
        if self.fail:
            raise OSError("no audio backend")
        self.level = level
        self.sets.append(round(level, 4))


@pytest.fixture
def ducker():
    made = []

    def make(**kw):
        d = FakeDucker(**kw)
        made.append(d)
        return d

    yield make
    for d in made:
        d.close()


def test_duck_lowers_then_restore_puts_it_back_exactly(ducker):
    d = ducker(level=0.73, percent=20)
    d.duck()
    assert d.wait_idle()
    assert d.level == pytest.approx(0.20)
    d.restore()
    assert d.wait_idle()
    assert d.level == pytest.approx(0.73)  # the exact level, not a rounded guess


def test_second_duck_keeps_the_original_level(ducker):
    """A duck while already ducked must not save the ducked level as 'before'."""
    d = ducker(level=0.9, percent=20)
    d.duck()
    assert d.wait_idle()
    d.duck()
    assert d.wait_idle()
    d.restore()
    assert d.wait_idle()
    assert d.level == pytest.approx(0.9)


def test_restore_without_duck_does_nothing(ducker):
    d = ducker(level=0.5)
    d.restore()
    assert d.wait_idle()
    assert d.sets == []
    assert d.level == pytest.approx(0.5)


def test_double_restore_cannot_strand_the_volume(ducker):
    d = ducker(level=0.6, percent=20)
    d.duck()
    d.restore()
    d.restore()  # a cancel followed by shutdown, say
    assert d.wait_idle()
    assert d.level == pytest.approx(0.6)


def test_already_quieter_than_target_is_left_alone(ducker):
    d = ducker(level=0.1, percent=20)
    d.duck()
    assert d.wait_idle()
    assert d.sets == []  # never turn someone's audio UP to duck it
    d.restore()
    assert d.wait_idle()
    assert d.level == pytest.approx(0.1)


def test_backend_failure_is_swallowed(ducker):
    d = ducker(fail=True)
    d.duck()
    d.restore()
    assert d.wait_idle()  # no exception escapes to the recording path


def test_close_restores_and_stops_the_worker():
    d = FakeDucker(level=0.65, percent=20)
    d.duck()
    assert d.wait_idle()
    assert d.level == pytest.approx(0.20)
    d.close()
    assert d.level == pytest.approx(0.65)  # close() blocks until it is back
    assert not d._thread.is_alive()


def test_percent_change_applies_to_the_next_duck(ducker):
    d = ducker(level=0.9, percent=20)
    d.percent = 50
    d.duck()
    assert d.wait_idle()
    assert d.level == pytest.approx(0.50)


def test_supported_is_a_bool():
    assert isinstance(supported(), bool)
