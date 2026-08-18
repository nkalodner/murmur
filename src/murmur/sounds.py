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
VOLUME = 0.15  # global ceiling; per-cue gain and the user's volume scale below this

# The start cue sounds while the microphone is already open, so the mic hears
# it and the model transcribes the low hum as "mm" / "mmhmm". The take's head
# is muted for the cue's length plus this tail, which covers the trip from
# speaker to mic and any ring-out.
#
# Deliberately short: every millisecond muted past the chime is a millisecond
# of speech lost from someone who talks the instant the cue ends. The player's
# own start-up delay is NOT budgeted here — play() re-anchors the window when
# playback actually begins (see `on_audible`), which is what keeps this tight.
TAIL_MARGIN = 0.06

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


def render(name: str, volume: float = 1.0) -> np.ndarray:
    """The waveform for a cue (exposed so tests can inspect it).

    `volume` is the user's setting as a 0..1 scale on top of the per-cue gain.
    """
    gain = GAINS.get(name, 1.0) * max(0.0, min(1.0, volume))
    return np.concatenate([_tone(f, ms, gain) for f, ms in CUES[name]])


def duration(name: str) -> float:
    """Seconds of sound in a cue."""
    return sum(ms for _, ms in CUES[name]) / 1000.0


def cue_path(name: str, directory: Path | None = None, volume: float = 1.0) -> Path:
    """The cue rendered to an int16 WAV on disk, written once and reused.

    The filename carries a checksum of the samples, so a retuned cue in a new
    version writes a fresh file instead of replaying a stale one; older files
    for the same cue are pruned as the new one lands.
    """
    if directory is None:
        from murmur.config import CONFIG_DIR

        directory = CONFIG_DIR / "cues"
    pcm = (np.clip(render(name, volume), -1.0, 1.0) * 32767).astype("<i2").tobytes()
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
    def __init__(self, enabled: bool = True, volume: float = 1.0):
        self.enabled = enabled
        self.volume = volume  # 0..1, the user's chime volume
        # Keyed by (cue, volume): a volume change renders a different file.
        self._paths: dict[tuple[str, float], Path] = {}

    def bleed_seconds(self, name: str) -> float:
        """How long the mic should ignore itself after this cue starts.

        Zero when nothing will actually sound, so muting the head of a take is
        tied to a cue really playing rather than assumed.
        """
        if not self.enabled or self.volume <= 0 or name not in CUES:
            return 0.0
        return duration(name) + TAIL_MARGIN

    def play(self, name: str, on_audible=None) -> None:
        """Play a cue. `on_audible` fires just before the sound really starts.

        Players do not begin the instant they are asked (spawning afplay, or
        filling PortAudio's buffer), so the caller gets this hook to re-anchor
        a mic mute to the moment the cue becomes audible instead of padding
        the window with a worst-case guess.
        """
        if not self.enabled or self.volume <= 0 or name not in CUES:
            return
        if sys.platform == "darwin" and self._play_system(name, on_audible):
            return
        try:
            import sounddevice as sd

            # In-process path (Windows/Linux, and the macOS fallback). The
            # start cue plays while the mic input stream is open; an output
            # stream competing with it tends to underrun (crackle) and pop as
            # it tears down, so give the output a roomier buffer
            # (latency="high") and a tail of silence, so the stream stops on
            # silence instead of on the tone's release.
            buf = np.concatenate(
                [render(name, self.volume), np.zeros(int(SR * 0.06), dtype=np.float32)]
            )
            if on_audible:
                on_audible()
            try:
                sd.play(buf, SR, latency="high")
            except TypeError:  # older sounddevice without the latency kwarg
                sd.play(buf, SR)
        except Exception as e:
            log.debug("sound %r failed: %s", name, e)

    def _play_system(self, name: str, on_audible=None) -> bool:
        """Play a cue through afplay; False falls back to the in-process path.

        Runs in a throwaway daemon thread so play() never waits on the ~50 ms
        process spawn, and the thread reaps the process when the cue ends.
        """
        if not shutil.which("afplay"):
            return False
        try:
            key = (name, self.volume)
            path = self._paths.get(key) or cue_path(name, volume=self.volume)
            self._paths[key] = path
        except Exception as e:
            log.debug("cue file for %r failed (%s); falling back to sounddevice", name, e)
            return False

        def _run() -> None:
            try:
                if on_audible:
                    on_audible()
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
