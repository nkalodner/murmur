"""The microphone stream's life, with PortAudio stood in for.

What these pin is that a slow or broken microphone can cost a take, but
never the app: stopping hands the audio back at once, a stream that will not
close is not waited on forever, and a stale device list is refreshed and
retried instead of failing every take until a restart.
"""
import sys
import threading
import time
import types

import numpy as np
import pytest

import murmur.audio as audio
from murmur.audio import Recorder


class FakeStream:
    def __init__(self, sd, device, callback):
        self.sd, self.device, self.callback = sd, device, callback
        self.started = self.closed = False
        self.active = False

    def start(self):
        self.started = self.active = True

    def stop(self):
        if self.sd.hang is not None:
            self.sd.hang.wait(5)

    def close(self):
        self.closed = True


class FakeSD(types.ModuleType):
    """Just enough sounddevice: a device list, streams, and a restart."""

    def __init__(self):
        super().__init__("sounddevice")
        self.devices = [{"name": "Built-in", "max_input_channels": 1, "default_samplerate": 48000}]
        self.default = types.SimpleNamespace(device=(0, 0))
        self.streams: list[FakeStream] = []
        self.fail_opens = 0  # how many InputStream() calls raise first
        self.hang = None  # an Event stop() waits on, to play a stuck device
        self.restarts = 0
        self.queries = 0

    def query_devices(self, *args):
        self.queries += 1
        return self.devices[0] if args else list(self.devices)

    def InputStream(self, device=None, callback=None, **kw):
        if self.fail_opens:
            self.fail_opens -= 1
            raise RuntimeError("Internal PortAudio error [PaErrorCode -9986]")
        stream = FakeStream(self, device, callback)
        self.streams.append(stream)
        return stream

    def _terminate(self):
        pass

    def _initialize(self):
        self.restarts += 1


@pytest.fixture
def sd(monkeypatch):
    fake = FakeSD()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(audio, "_devices", None)
    monkeypatch.setattr(audio, "_open_streams", 0)
    monkeypatch.setattr(audio, "_scan_gen", 0)
    monkeypatch.setattr(audio, "RESCAN", True)  # the macOS behavior
    monkeypatch.setattr(audio, "RESCAN_AGE", 3600.0)  # no rescans unless a test asks
    monkeypatch.setattr(audio, "LINGER", 0.01)  # let go almost at once, unless a test asks
    return fake


def _block(n=160):
    return np.ones((n, 1), dtype=np.float32)


def _feed(sd, n=160, stream=-1):
    sd.streams[stream].callback(_block(n), n, None, None)


def _released(rec, timeout=2.0):
    """Wait until the recorder has really let go of the microphone."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if rec._stream is None and rec.wait_closed(0.01):
            return True
        time.sleep(0.005)
    return False


# ── tapping the hotkey on and off ───────────────────────────────────────


def test_takes_in_quick_succession_share_one_open_microphone(sd, monkeypatch):
    # Opening and closing the device several times a second is what made
    # it refuse to open at all: two error beeps per press, then nothing.
    monkeypatch.setattr(audio, "LINGER", 30.0)
    rec = Recorder()
    for _ in range(12):
        rec.start()
        _feed(sd)
        wav, _ = rec.stop()
        assert len(wav) == 160
    assert len(sd.streams) == 1 and not sd.streams[0].closed
    rec.close()
    assert _released(rec) and sd.streams[0].closed


def test_nothing_is_recorded_between_takes(sd, monkeypatch):
    monkeypatch.setattr(audio, "LINGER", 30.0)
    rec = Recorder()
    rec.start()
    _feed(sd)
    rec.stop()
    _feed(sd, 8000)  # the stream is still open, but nobody is dictating
    assert rec.current_level() == 0.0
    rec.start()
    _feed(sd)
    wav, _ = rec.stop()
    assert len(wav) == 160
    rec.close()


def test_the_microphone_is_let_go_once_the_burst_is_over(sd):
    rec = Recorder()  # the fixture's LINGER is a few milliseconds
    rec.start()
    rec.stop()
    assert _released(rec) and sd.streams[0].closed
    rec.start()  # a later take opens a fresh one
    assert len(sd.streams) == 2
    rec.close()
    assert _released(rec)


def test_a_lingering_stream_on_the_wrong_microphone_is_not_reused(sd, monkeypatch):
    monkeypatch.setattr(audio, "LINGER", 30.0)
    rec = Recorder(0)
    rec.start()
    rec.stop()
    rec.set_device(4)  # picked another mic in the tray between takes
    rec.start()
    assert len(sd.streams) == 2 and sd.streams[1].device == 4
    rec.close()
    assert _released(rec) and sd.streams[0].closed


def test_a_lingering_stream_that_died_is_replaced(sd, monkeypatch):
    monkeypatch.setattr(audio, "LINGER", 30.0)
    rec = Recorder()
    rec.start()
    rec.stop()
    sd.streams[0].active = False  # AirPods went back in their case
    rec.start()
    assert len(sd.streams) == 2
    rec.close()


# ── a device that misbehaves ────────────────────────────────────────────


def test_stop_hands_back_audio_without_waiting_for_the_device(sd, monkeypatch):
    sd.hang = threading.Event()  # the device never lets go
    monkeypatch.setattr(audio, "CLOSE_WAIT", 0.05)
    rec = Recorder()
    rec.start()
    _feed(sd, 8000)
    wav, seconds = rec.stop()
    assert len(wav) == 8000 and seconds == pytest.approx(0.5)
    rec.close()  # returns although stop() on the stream is stuck
    assert not rec.wait_closed(0.05)

    # A close that hangs costs that one stream, not every take after it.
    rec.start()
    assert len(sd.streams) == 2 and rec.active
    _feed(sd)
    assert len(rec.stop()[0]) == 160
    sd.hang.set()
    rec.close()
    assert _released(rec)


def test_a_closing_stream_cannot_leak_into_the_next_take(sd):
    rec = Recorder()
    rec.start()
    rec.close()
    assert _released(rec)
    rec.start()
    _feed(sd, stream=0)  # a straggler from the old stream
    _feed(sd, stream=1)
    wav, _ = rec.stop()
    assert len(wav) == 160
    rec.close()


def test_a_failed_open_refreshes_the_device_list_and_tries_again(sd):
    resolved = []
    rec = Recorder(0, resolve=lambda: resolved.append(1) or 0)
    sd.fail_opens = 2  # 16 kHz and the native-rate fallback, on the stale list
    rec.start()
    assert sd.restarts == 1 and resolved, "PortAudio was not restarted and re-resolved"
    assert rec.active
    rec.close()
    assert _released(rec)


def test_a_microphone_that_is_really_gone_still_raises(sd):
    rec = Recorder()
    sd.fail_opens = 99
    with pytest.raises(RuntimeError):
        rec.start()
    assert not rec.active and audio._open_streams == 0
    # The lock was given back: the device list is still readable.
    assert audio._pa.acquire(timeout=1)
    audio._pa.release()
    sd.fail_opens = 0
    rec.start()  # and it works again the moment the device does
    assert rec.active
    rec.close()


def test_no_restart_while_a_stream_is_open_or_off_macos(sd, monkeypatch):
    rec = Recorder()
    rec.start()
    assert audio.refresh_devices() is False  # it would cut the take off
    rec.close()
    assert _released(rec)
    assert audio.refresh_devices() is True
    monkeypatch.setattr(audio, "RESCAN", False)  # Windows: chimes are streams too
    assert audio.refresh_devices() is False


def test_a_finished_take_refreshes_an_old_list_and_the_device_is_found_again(sd, monkeypatch):
    monkeypatch.setattr(audio, "RESCAN_AGE", 0.0)
    indexes = iter([3, 5])
    rec = Recorder(1, resolve=lambda: next(indexes))
    rec.start()
    assert sd.streams[0].device == 1  # same list as when it was resolved
    rec.close()
    assert _released(rec)
    end = time.monotonic() + 2
    while sd.restarts < 1 and time.monotonic() < end:
        time.sleep(0.005)
    assert sd.restarts == 1
    rec.start()  # everything was renumbered by the restart
    assert sd.streams[1].device == 3
    rec.close()
    assert _released(rec)


def test_the_device_list_is_served_from_the_last_scan(sd):
    first = audio.input_devices()
    assert first[0]["name"] == "Built-in" and first[0]["default"]
    asked = sd.queries
    for _ in range(5):  # the tray asks on every redraw, on the menu-bar thread
        audio.input_devices()
    assert sd.queries == asked
    first[0]["name"] = "scribbled"  # callers get copies
    assert audio.input_devices()[0]["name"] == "Built-in"
    assert audio.find_input_device("built") == 0
    with pytest.raises(LookupError):
        audio.find_input_device("AirPods")
