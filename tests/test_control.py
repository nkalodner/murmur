"""The hotkey's path through the app: noted on the listener's thread, done
on another.

On a Mac the listener's callback runs inside the system's keyboard tap. Work
done there (opening the microphone, closing it) is how the tap got switched
off mid-take, leaving Murmur showing "recording" with a hotkey that no
longer answered. These pin the replacement: the callbacks only queue, the
timing still comes from the keypresses themselves, and nothing that goes
wrong mid-take can strand the recording state.
"""
import threading
import time

import numpy as np
import pytest

from murmur.app import App, State
from murmur.config import Config


class FakeRecorder:
    def __init__(self):
        self.starts = self.stops = 0
        self.fail_stop = False
        self.gate = None  # start() waits on this, to play a slow microphone

    def start(self):
        if self.gate is not None:
            self.gate.wait(5)
        self.starts += 1

    def stop(self):
        self.stops += 1
        if self.fail_stop:
            raise MemoryError("no room for the take")
        return np.zeros(16000, dtype=np.float32), 1.0

    def abort(self):
        self.stops += 1

    def mute_for(self, seconds):
        pass

    def current_level(self):
        return 0.0


@pytest.fixture
def app():
    a = App(Config(sounds=False))
    a.recorder = FakeRecorder()
    yield a
    a._stopping.set()
    a._cancel_max_timer()
    a._events.put((None, 0.0, None))


def _wait(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_the_listener_callbacks_return_before_the_microphone_opens(app):
    app.recorder.gate = threading.Event()  # a microphone that takes its time
    app._control.start()
    t0 = time.monotonic()
    app.on_press()
    assert time.monotonic() - t0 < 0.2, "the keyboard tap was kept waiting"
    assert app._state == State.IDLE  # still opening, on the control thread
    app.recorder.gate.set()
    assert _wait(lambda: app._state == State.RECORDING)


def test_a_quick_tap_locks_even_when_the_microphone_was_slow(app):
    # Tap-or-hold is decided by the gap between the two key events, not by
    # when the app got round to them.
    now = time.monotonic()
    app._handle_event("press", now)
    app._handle_event("release", now + 0.1)  # handled late, but a 100 ms tap
    assert app._state == State.LOCKED
    app._handle_event("press", now + 2)
    assert app._state == State.BUSY and app.recorder.stops == 1


def test_a_hold_finishes_on_release(app):
    now = time.monotonic()
    app._handle_event("press", now)
    app._handle_event("release", now + 1.0)
    assert app._state == State.BUSY


def test_a_press_that_waited_too_long_starts_nothing(app):
    app._handle_event("press", time.monotonic() - 5)
    assert app._state == State.IDLE and app.recorder.starts == 0
    app._handle_event("release", time.monotonic())  # its release is a no-op
    assert app._state == State.IDLE


def test_a_failure_mid_take_goes_back_to_idle_not_stuck_recording(app):
    now = time.monotonic()
    app._handle_event("press", now)
    assert app._state == State.RECORDING
    app.recorder.fail_stop = True
    app._handle_event("release", now + 1.0)  # must not raise, must not strand
    assert app._state == State.IDLE
    app.recorder.fail_stop = False
    app._handle_event("press", time.monotonic())  # and the hotkey still works
    assert app._state == State.RECORDING


def test_a_time_limit_from_an_earlier_take_does_not_end_this_one(app):
    now = time.monotonic()
    app._handle_event("press", now)
    first = app._take
    app._handle_event("cancel", now + 0.5)
    app._handle_event("press", time.monotonic())
    app._handle_event("max", time.monotonic(), first)  # fired late, for take one
    assert app._state == State.RECORDING
    app._handle_event("max", time.monotonic(), app._take)
    assert app._state == State.BUSY


def test_keys_work_without_a_control_thread(app):
    # Before run() starts it, or if it ever died: handled in place.
    app.on_press()
    assert app._state == State.RECORDING


def test_a_shutdown_that_hangs_still_ends_the_process(app, monkeypatch):
    # Quit has to mean gone: a copy that hangs on its way out keeps the
    # microphone, the single-instance port and a ghost menu on screen.
    import murmur.app as app_mod

    exits = []
    monkeypatch.setattr(app_mod.os, "_exit", exits.append)
    app.exit_deadline = 0.05
    app.shutdown()
    assert _wait(lambda: exits == [0])


def test_shutdown_never_force_exits_unless_asked(app, monkeypatch):
    import murmur.app as app_mod

    exits = []
    monkeypatch.setattr(app_mod.os, "_exit", exits.append)
    app.shutdown()  # exit_deadline is None outside main()
    time.sleep(0.1)
    assert exits == []
