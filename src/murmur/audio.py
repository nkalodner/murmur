"""Microphone capture. Records float32 and hands back mono 16 kHz."""

from __future__ import annotations

import logging
import sys
import threading
import time

import numpy as np

from murmur.chunking import TARGET_SR

log = logging.getLogger("murmur")


def _sd():
    import sounddevice as sd

    return sd


# PortAudio reads the list of devices once, when it starts, and never looks
# again. On a Mac that goes stale all the time (AirPods connect, a dock is
# unplugged, the lid closes), and a stale list is how a take fails to open or
# records from a microphone that is no longer the default. The only way to
# look again is to restart PortAudio, which is safe only while no stream is
# open. Windows keeps the old behavior: its chimes are PortAudio streams of
# their own, and a restart would cut one off mid-note.
RESCAN = sys.platform == "darwin"
RESCAN_AGE = 20.0  # seconds a list may sit before a finished take refreshes it
CLOSE_WAIT = 1.0  # how long a new take waits on the last one's stream closing

# One lock for everything that opens, closes or restarts PortAudio. Nothing
# on the menu-bar thread may ever wait on it: the device list those callers
# want is served from _devices, a copy taken at the last scan.
_pa = threading.RLock()
_devices: list[dict] | None = None
_scanned_at = 0.0
_scan_gen = 0  # bumped on every restart; device indexes are only good within one
_open_streams = 0  # open, or still closing


def _scan() -> list[dict]:
    """Ask PortAudio for its input devices. Caller holds _pa."""
    global _devices, _scanned_at
    sd = _sd()
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = -1
    out = []
    for i, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            out.append(
                {
                    "index": i,
                    "name": dev["name"],
                    "channels": int(dev["max_input_channels"]),
                    "samplerate": int(dev["default_samplerate"]),
                    "default": i == default_in,
                }
            )
    _devices = out
    _scanned_at = time.monotonic()
    return out


def input_devices() -> list[dict]:
    """Structured input-device list (the settings page and the tray menu).

    Served from the last scan. PortAudio's own list only changes when it is
    restarted, so the copy is exactly as fresh as asking it would be, and
    reading it can never wait behind a microphone that is slow to open.
    """
    devices = _devices
    if devices is None:
        with _pa:
            devices = _devices if _devices is not None else _scan()
    return [dict(d) for d in devices]


def refresh_devices(max_age: float = 0.0) -> bool:
    """Restart PortAudio so it sees today's devices. True if it did.

    Skipped (False) where restarting is not safe: on Windows, while any
    stream is open, or when someone else is in the middle of an open or
    close. `max_age` skips a list scanned more recently than that.
    """
    global _scan_gen
    if not RESCAN:
        return False
    if not _pa.acquire(blocking=False):
        return False
    try:
        if _open_streams:
            return False
        if max_age and _devices is not None and time.monotonic() - _scanned_at < max_age:
            return False
        sd = _sd()
        try:
            sd._terminate()
        except Exception as e:
            log.debug("PortAudio terminate: %s", e)
        try:
            sd._initialize()
        except Exception as e:
            # Left uninitialized, every later call would fail. One more try,
            # and if that fails too the error surfaces on the next take.
            log.debug("PortAudio initialize failed (%s); retrying", e)
            sd._initialize()
        _scan_gen += 1
        _scan()
        return True
    except Exception as e:
        log.warning("Could not refresh the list of microphones: %s", e)
        return False
    finally:
        _pa.release()


def refresh_devices_async(max_age: float = RESCAN_AGE) -> None:
    """refresh_devices on a throwaway thread, for callers that must not wait."""
    if not RESCAN:
        return
    if _devices is not None and time.monotonic() - _scanned_at < max_age:
        return
    threading.Thread(
        target=refresh_devices, args=(max_age,), name="murmur-mic-scan", daemon=True
    ).start()


def list_input_devices() -> list[str]:
    return [
        f"{'*' if d['default'] else ' '} [{d['index']}] {d['name']}  "
        f"({d['channels']} ch, {d['samplerate']} Hz)"
        for d in input_devices()
    ]


def find_input_device(name: str | None) -> int | None:
    """Map a config device-name substring to a PortAudio index."""
    if not name:
        return None
    for dev in input_devices():
        if name.lower() in dev["name"].lower():
            return dev["index"]
    raise LookupError(f"No input device matching {name!r}. Run: murmur --list-devices")


def _close_async(stream) -> threading.Event:
    """Stop and close a stream off the caller's thread. The event sets when
    it is really closed.

    CoreAudio can take its time giving a device back, and when the device
    vanished mid-take (AirPods handed off to a phone) it can fail to come
    back at all. Whoever stopped the recording already has the audio, so
    there is nothing to wait for, and a close that hangs must not take the
    hotkey or the menu bar down with it.
    """
    done = threading.Event()

    def run() -> None:
        global _open_streams
        try:
            # Not under _pa: if this never returns, the lock must still be
            # there for the next take to open a stream of its own.
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                log.debug("stream close: %s", e)
            with _pa:
                _open_streams = max(0, _open_streams - 1)
            done.set()
            # Between takes is the one moment a rescan is free.
            refresh_devices(max_age=RESCAN_AGE)
        finally:
            done.set()

    threading.Thread(target=run, name="murmur-mic-close", daemon=True).start()
    return done


class Recorder:
    """One InputStream per dictation, opened on hotkey press so the mic light stays honest."""

    def __init__(self, device: int | None = None, resolve=None):
        self._device = device
        # Finds the configured device again after a rescan, since PortAudio
        # renumbers everything when it restarts. None means "keep the index".
        self._resolve = resolve
        self._device_gen = _scan_gen
        self._lock = threading.Lock()
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._sr = TARGET_SR
        self._level = 0.0  # smoothed input level, 0..1, for the recording pill
        self._mute_samples = 0  # head-of-take samples to silence (the start chime)
        self._take = 0  # which take the live stream belongs to
        self._closed = threading.Event()  # the previous take's stream is gone
        self._closed.set()

    @property
    def active(self) -> bool:
        return self._stream is not None

    def current_level(self) -> float:
        """Latest smoothed mic level (0..1). A plain float read, GIL-safe."""
        return self._level

    def mute_for(self, seconds: float) -> None:
        """Silence the next `seconds` of captured audio.

        Murmur's own start chime sounds while this stream is already open, so
        the mic records it and the model hears the low hum as "mm"/"mmhmm".
        Counting samples rather than watching the clock keeps the window exact
        whatever the block size. The count is written once per take here and
        only drained by the audio callback, so the two never race in practice.
        """
        if seconds <= 0:
            return
        self._mute_samples = int(seconds * self._sr)

    def set_device(self, device: int | None) -> None:
        """Point future recordings at a different input device."""
        with self._lock:
            self._device = device
            self._device_gen = _scan_gen

    def _open(self, sd, callback):
        """An unstarted InputStream on the current device."""
        try:
            stream = sd.InputStream(
                samplerate=TARGET_SR,
                channels=1,
                dtype="float32",
                device=self._device,
                callback=callback,
            )
            self._sr = TARGET_SR
        except Exception:
            # Some devices refuse 16 kHz mono; record at their native format and resample.
            info = sd.query_devices(self._device if self._device is not None else None, "input")
            self._sr = int(info["default_samplerate"])
            channels = max(1, min(int(info["max_input_channels"]), 2))
            log.debug("16 kHz mono unsupported; using %s Hz / %s ch", self._sr, channels)
            stream = sd.InputStream(
                samplerate=self._sr,
                channels=channels,
                dtype="float32",
                device=self._device,
                callback=callback,
            )
        return stream

    def _open_started(self, sd, callback):
        stream = self._open(sd, callback)
        try:
            stream.start()
        except Exception:
            try:
                stream.close()
            except Exception:
                pass
            raise
        return stream

    def start(self) -> None:
        global _open_streams
        sd = _sd()
        with self._lock:
            if self._stream is not None:
                return
            # The last take's stream closes in the background. Give it a
            # moment to finish; if it has not, open anyway. Refusing here
            # (0.15.8) meant one close that hung cost every take after it.
            if not self._closed.wait(CLOSE_WAIT):
                log.warning("The last microphone stream is slow to close; opening a new one anyway")
            if not _pa.acquire(timeout=CLOSE_WAIT * 3):
                raise RuntimeError("the audio system is busy; try again in a moment")
            try:
                self._chunks = []
                self._mute_samples = 0
                self._take += 1
                take = self._take

                def callback(indata, frames, time_info, status, _take=take):
                    # A stream that is on its way out can still deliver a
                    # block or two; those belong to no take.
                    if _take == self._take:
                        self._callback(indata, frames, time_info, status)

                if self._resolve is not None and self._device_gen != _scan_gen:
                    self._device = self._resolve()
                    self._device_gen = _scan_gen
                try:
                    stream = self._open_started(sd, callback)
                except Exception as first:
                    # Most often a stale device list. Look again and retry
                    # once; if nothing can be refreshed, the first error is
                    # the one worth reporting.
                    if not refresh_devices():
                        raise
                    log.info("The microphone would not open (%s); refreshed the device list", first)
                    if self._resolve is not None:
                        self._device = self._resolve()
                    self._device_gen = _scan_gen
                    stream = self._open_started(sd, callback)
                _open_streams += 1
                self._stream = stream
            finally:
                _pa.release()

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("audio status: %s", status)
        block = indata.copy()
        if self._mute_samples > 0:
            # Zero rather than drop, so the take's timing (and the max-seconds
            # timer) still match the wall clock.
            n = min(self._mute_samples, len(block))
            block[:n] = 0.0
            self._mute_samples -= n
        self._chunks.append(block)
        # Track a smoothed level for the overlay meter. sqrt spreads quiet
        # speech across the meter; the blend keeps the bars from flickering.
        # Reading the muted block keeps the chime from bouncing the pill too.
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))) if block.size else 0.0
        target = min(1.0, rms**0.5 * 3.2)
        self._level = self._level * 0.5 + target * 0.5

    def stop(self) -> tuple[np.ndarray, float]:
        """Hand back (mono float32 at 16 kHz, seconds recorded) right away.

        The stream itself is closed in the background (see _close_async), so
        the transcript starts the moment the key comes up.
        """
        with self._lock:
            stream, self._stream = self._stream, None
            chunks, self._chunks = self._chunks, []
            sr = self._sr
            self._take += 1  # anything the old stream still delivers is dropped
            if stream is not None:
                self._closed = _close_async(stream)
        self._level = 0.0
        if not chunks:
            return np.zeros(0, dtype=np.float32), 0.0
        data = np.concatenate(chunks)
        if data.ndim > 1:
            data = data.mean(axis=1)
        seconds = len(data) / sr
        if sr != TARGET_SR:
            import soxr

            data = soxr.resample(data, sr, TARGET_SR)
        return np.ascontiguousarray(data, dtype=np.float32), seconds

    def abort(self) -> None:
        self.stop()

    def wait_closed(self, timeout: float = 3.0) -> bool:
        """Block until the last stream is really closed. For shutdown and tests."""
        return self._closed.wait(timeout)


def preflight(device: int | None) -> None:
    """Open the mic briefly so macOS asks for permission at launch and device problems show early."""
    rec = Recorder(device)
    rec.start()
    time.sleep(0.15)
    rec.abort()


def record_sample(device: int | None, seconds: float = 1.4) -> tuple[np.ndarray, float]:
    """Capture a short clip from a device for the settings-page mic test."""
    rec = Recorder(device)
    rec.start()
    time.sleep(seconds)
    return rec.stop()
