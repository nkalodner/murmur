"""Tiny audio cues so you know state without looking. All generated, no assets."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("murmur")

SR = 44100
VOLUME = 0.15  # global ceiling; per-cue gain scales below this

# (frequency Hz, duration ms) sequences. The "start" cue is deliberately low
# and soft (it plays every time you begin talking); the sharper, higher cues
# are for the moments you want to notice (cancel, error).
CUES: dict[str, list[tuple[float, int]]] = {
    "ready": [(523, 80), (659, 110)],
    "start": [(196, 80), (262, 120)],  # low G -> C, gentle rise
    "stop": [(330, 60), (247, 70)],
    "cancel": [(300, 90), (220, 110)],
    "error": [(196, 90), (0, 40), (196, 90)],
}
# Per-cue loudness relative to VOLUME. The start cue is the quietest since it
# fires constantly; keep the alerts full so they still cut through.
GAINS: dict[str, float] = {
    "ready": 0.75,
    "start": 0.4,
    "stop": 0.5,
    "cancel": 0.7,
    "error": 0.9,
}


def _tone(freq: float, ms: int, gain: float = 1.0) -> np.ndarray:
    n = int(SR * ms / 1000)
    if freq <= 0:
        return np.zeros(n, dtype=np.float32)
    t = np.arange(n) / SR
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
    # Raised-cosine attack/release, ~12 ms, so the tone eases in and out
    # instead of clicking. A soft edge is most of what "less aggressive" means.
    ramp = min(n // 2, max(1, int(SR * 0.012)))
    env = np.ones(n, dtype=np.float32)
    rise = 0.5 * (1 - np.cos(np.linspace(0, np.pi, ramp, dtype=np.float32)))
    env[:ramp] = rise
    env[-ramp:] = rise[::-1]
    return wave * env * (VOLUME * gain)


def render(name: str) -> np.ndarray:
    """The waveform for a cue (exposed so tests can inspect it)."""
    gain = GAINS.get(name, 1.0)
    return np.concatenate([_tone(f, ms, gain) for f, ms in CUES[name]])


class Sounds:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def play(self, name: str) -> None:
        if not self.enabled or name not in CUES:
            return
        try:
            import sounddevice as sd

            sd.play(render(name), SR)
        except Exception as e:
            log.debug("sound %r failed: %s", name, e)
