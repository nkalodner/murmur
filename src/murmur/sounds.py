"""Tiny audio cues so you know state without looking. All generated, no assets."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("murmur")

SR = 44100
VOLUME = 0.15

CUES: dict[str, list[tuple[float, int]]] = {
    "ready": [(740, 70), (988, 90)],
    "start": [(660, 55), (880, 55)],
    "stop": [(880, 55), (660, 55)],
    "cancel": [(330, 90)],
    "error": [(196, 90), (0, 40), (196, 90)],
}


def _tone(freq: float, ms: int) -> np.ndarray:
    n = int(SR * ms / 1000)
    if freq <= 0:
        return np.zeros(n, dtype=np.float32)
    t = np.arange(n) / SR
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
    ramp = max(1, int(SR * 0.005))
    env = np.ones(n, dtype=np.float32)
    env[:ramp] = np.linspace(0, 1, ramp, dtype=np.float32)
    env[-ramp:] = np.linspace(1, 0, ramp, dtype=np.float32)
    return wave * env * VOLUME


class Sounds:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        try:
            import sounddevice as sd

            buf = np.concatenate([_tone(f, ms) for f, ms in CUES[name]])
            sd.play(buf, SR)
        except Exception as e:
            log.debug("sound %r failed: %s", name, e)
