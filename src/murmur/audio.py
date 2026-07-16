"""Microphone capture. Records float32 and hands back mono 16 kHz."""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from murmur.chunking import TARGET_SR

log = logging.getLogger("murmur")


def _sd():
    import sounddevice as sd

    return sd


def input_devices() -> list[dict]:
    """Structured input-device list (used by the settings page)."""
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
    return out


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
    sd = _sd()
    for i, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0 and name.lower() in dev["name"].lower():
            return i
    raise LookupError(f"No input device matching {name!r}. Run: murmur --list-devices")


class Recorder:
    """One InputStream per dictation, opened on hotkey press so the mic light stays honest."""

    def __init__(self, device: int | None = None):
        self._device = device
        self._lock = threading.Lock()
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._sr = TARGET_SR

    @property
    def active(self) -> bool:
        return self._stream is not None

    def set_device(self, device: int | None) -> None:
        """Point future recordings at a different input device."""
        with self._lock:
            self._device = device

    def start(self) -> None:
        sd = _sd()
        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []
            try:
                stream = sd.InputStream(
                    samplerate=TARGET_SR,
                    channels=1,
                    dtype="float32",
                    device=self._device,
                    callback=self._callback,
                )
                self._sr = TARGET_SR
            except Exception:
                # Some devices refuse 16 kHz mono; record at their native format and resample.
                info = sd.query_devices(
                    self._device if self._device is not None else None, "input"
                )
                self._sr = int(info["default_samplerate"])
                channels = max(1, min(int(info["max_input_channels"]), 2))
                log.debug("16 kHz mono unsupported; using %s Hz / %s ch", self._sr, channels)
                stream = sd.InputStream(
                    samplerate=self._sr,
                    channels=channels,
                    dtype="float32",
                    device=self._device,
                    callback=self._callback,
                )
            stream.start()
            self._stream = stream

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("audio status: %s", status)
        self._chunks.append(indata.copy())

    def stop(self) -> tuple[np.ndarray, float]:
        """Close the stream and return (mono float32 at 16 kHz, seconds recorded)."""
        with self._lock:
            stream, self._stream = self._stream, None
            chunks, self._chunks = self._chunks, []
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                log.debug("stream close: %s", e)
        if not chunks:
            return np.zeros(0, dtype=np.float32), 0.0
        data = np.concatenate(chunks)
        if data.ndim > 1:
            data = data.mean(axis=1)
        seconds = len(data) / self._sr
        if self._sr != TARGET_SR:
            import soxr

            data = soxr.resample(data, self._sr, TARGET_SR)
        return np.ascontiguousarray(data, dtype=np.float32), seconds

    def abort(self) -> None:
        self.stop()


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
