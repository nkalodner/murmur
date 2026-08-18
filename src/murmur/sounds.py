"""Tiny audio cues so you know state without looking. All generated, no assets.

On macOS the cues play through the system's own player (afplay) instead of a
PortAudio output stream: the start cue fires while the microphone stream is
open, and two PortAudio streams competing in one process is what made the cue
crackle. The 0.5.4 buffer tuning (latency="high", silence tail) softened it
but never fully cleared it on every Mac; a separate process going through the
system mixer is immune. Windows and Linux keep the in-process path, which is
also the fallback if afplay ever misbehaves.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import wave
import zlib
from pathlib import Path

import numpy as np

log = logging.getLogger("murmur")

SR = 44100
VOLUME = 0.15  # global ceiling; per-cue gain scales below this

# (frequency Hz, duration ms) sequences. The "ready" and "start" cues are
# deliberately low and warm (ready greets you once at launch; start plays every
# time you begin talking); the sharper, higher cues are for the moments you want
# to notice (cancel, error).
CUES: dict[str, list[tuple[float, int]]] = {
    "ready": [(262, 90), (392, 130)],  # C -> G, warm rise in the start/stop register
    "start": [(196, 80), (262, 120)],  # low G -> C, gentle rise
    "stop": [(330, 60), (247, 70)],
    "cancel": [(300, 90), (220, 110)],
    "error": [(196, 90), (0, 40), (196, 90)],
}
# Per-cue loudness relative to VOLUME. The start cue is the quietest since it
# fires constantly; keep the alerts full so they still cut through.
GAINS: dict[str, float] = {
    "ready": 0.5,
    "start": 0.4,
    "stop": 0.5,
    "cancel": 0.6,
    "error": 0.75,
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


def cue_path(name: str, directory: Path | None = None) -> Path:
    """The cue rendered to an int16 WAV on disk, written once and reused.

    The filename carries a checksum of the samples, so a retuned cue in a new
    version writes a fresh file instead of replaying a stale one; older files
    for the same cue are pruned as the new one lands.
    """
    if directory is None:
        from murmur.config import CONFIG_DIR

        directory = CONFIG_DIR / "cues"
    pcm = (np.clip(render(name), -1.0, 1.0) * 32767).astype("<i2").tobytes()
    path = directory / f"{name}-{zlib.crc32(pcm):08x}.wav"
    if not path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob(f"{name}-*.wav"):
            stale.unlink(missing_ok=True)
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes(pcm)
    return path


class Sounds:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._paths: dict[str, Path] = {}

    def play(self, name: str) -> None:
        if not self.enabled or name not in CUES:
            return
        if sys.platform == "darwin" and self._play_system(name):
            return
        try:
            import sounddevice as sd

            # In-process path (Windows/Linux, and the macOS fallback). The
            # start cue plays while the mic input stream is open; an output
            # stream competing with it tends to underrun (crackle) and pop as
            # it tears down, so give the output a roomier buffer
            # (latency="high") and a tail of silence, so the stream stops on
            # silence instead of on the tone's release.
            buf = np.concatenate([render(name), np.zeros(int(SR * 0.06), dtype=np.float32)])
            try:
                sd.play(buf, SR, latency="high")
            except TypeError:  # older sounddevice without the latency kwarg
                sd.play(buf, SR)
        except Exception as e:
            log.debug("sound %r failed: %s", name, e)

    def _play_system(self, name: str) -> bool:
        """Play a cue through afplay; False falls back to the in-process path.

        Runs in a throwaway daemon thread so play() never waits on the ~50 ms
        process spawn, and the thread reaps the process when the cue ends.
        """
        if not shutil.which("afplay"):
            return False
        try:
            path = self._paths.get(name) or cue_path(name)
            self._paths[name] = path
        except Exception as e:
            log.debug("cue file for %r failed (%s); falling back to sounddevice", name, e)
            return False

        def _run() -> None:
            try:
                subprocess.run(
                    ["afplay", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception as e:
                log.debug("afplay %r failed: %s", name, e)

        threading.Thread(target=_run, name="murmur-cue", daemon=True).start()
        return True
