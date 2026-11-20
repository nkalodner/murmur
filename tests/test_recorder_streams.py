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

    def start(self):
        self.started = True

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
    return fake


def _block(n=160):
    return np.ones((n, 1), dtype=np.float32)


def test_stop_hands_back_audio_without_waiting_for_the_device(sd, monkeypatch):
    sd.hang = threading.Event()  # the device never lets go
    rec = Recorder()
    rec.start()
    sd.streams[0].callback(_block(8000), 8000, None, None)
    wav, seconds = rec.stop()  # returns although stop() on the stream is stuck
    assert len(wav) == 8000 and seconds == pytest.approx(0.5)
    assert not rec.wait_closed(0.05)

    # A close that hangs costs that one stream, not every take after it.
    monkeypatch.setattr(audio, "CLOSE_WAIT", 0.05)
    rec.start()
    assert len(sd.streams) == 2 and rec.active
    sd.streams[1].callback(_block(), 160, None, None)
    sd.hang.set()
    assert len(rec.stop()[0]) == 160
    assert rec.wait_closed(2)


def test_a_closing_stream_cannot_leak_into_the_next_take(sd):
    rec = Recorder()
    rec.start()
    old = sd.streams[0]
    rec.stop()
    assert rec.wait_closed(2)
    rec.start()
    old.callback(_block(), 160, None, None)  # a straggler from the old stream
    sd.streams[1].callback(_block(), 160, None, None)
    wav, _ = rec.stop()
    assert len(wav) == 160


def test_a_failed_open_refreshes_the_device_list_and_tries_again(sd):
    resolved = []
    rec = Recorder(0, resolve=lambda: resolved.append(1) or 0)
    sd.fail_opens = 2  # 16 kHz and the native-rate fallback, on the stale list
    rec.start()
    assert sd.restarts == 1 and resolved, "PortAudio was not restarted and re-resolved"
    assert rec.active
    rec.abort()
    assert rec.wait_closed(2)


def test_a_microphone_that_is_really_gone_still_raises(sd):
    rec = Recorder()
    sd.fail_opens = 99
    with pytest.raises(RuntimeError):
        rec.start()
    assert not rec.active and audio._open_streams == 0
    # The lock was given back: the device list is still readable.
    assert audio._pa.acquire(timeout=1)
    audio._pa.release()


def test_no_restart_while_a_stream_is_open_or_off_macos(sd, monkeypatch):
    rec = Recorder()
    rec.start()
    assert audio.refresh_devices() is False  # it would cut the take off
    rec.abort()
    assert rec.wait_closed(2)
    assert audio.refresh_devices() is True
    monkeypatch.setattr(audio, "RESCAN", False)  # Windows: chimes are streams too
    assert audio.refresh_devices() is False


def test_a_finished_take_refreshes_an_old_list_and_the_device_is_found_again(sd, monkeypatch):
    monkeypatch.setattr(audio, "RESCAN_AGE", 0.0)
    indexes = iter([3, 5])
    rec = Recorder(1, resolve=lambda: next(indexes))
    rec.start()
    assert sd.streams[0].device == 1  # same list as when it was resolved
    rec.stop()
    assert rec.wait_closed(2)
    end = time.monotonic() + 2
    while sd.restarts < 1 and time.monotonic() < end:  # the rescan follows the close
        time.sleep(0.005)
    assert sd.restarts == 1
    rec.start()  # everything was renumbered by the restart
    assert sd.streams[1].device == 3
    rec.abort()
    assert rec.wait_closed(2)


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
