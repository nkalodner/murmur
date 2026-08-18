"""Generated audio cues: right length, no clipping, clean fade in/out, and
the on-disk WAV cache + afplay routing behind the macOS system-player path."""
import sys
import threading
import wave
from pathlib import Path

import numpy as np

import murmur.sounds as sounds
from murmur.sounds import CUES, GAINS, SR, VOLUME, Sounds, cue_path, render


def test_every_cue_has_a_gain():
    assert set(CUES) <= set(GAINS)


def test_render_length_matches_durations():
    for name, tones in CUES.items():
        expected = sum(int(SR * ms / 1000) for _, ms in tones)
        assert len(render(name)) == expected


def test_no_clipping_and_float32():
    for name in CUES:
        wav = render(name)
        assert wav.dtype == np.float32
        assert np.max(np.abs(wav)) <= VOLUME * GAINS[name] + 1e-6


def test_edges_fade_to_zero():
    for name in CUES:
        wav = render(name)
        assert abs(wav[0]) < 1e-3 and abs(wav[-1]) < 1e-3


def test_cue_file_is_a_faithful_wav(tmp_path):
    for name in CUES:
        path = cue_path(name, tmp_path)
        with wave.open(str(path), "rb") as f:
            assert f.getnchannels() == 1
            assert f.getsampwidth() == 2
            assert f.getframerate() == SR
            pcm = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")
        expected = render(name)
        assert len(pcm) == len(expected)
        # Round-trips within int16 quantization.
        assert np.max(np.abs(pcm / 32767.0 - expected)) < 1e-4


def test_cue_file_written_once_and_stale_files_pruned(tmp_path):
    stale = tmp_path / "start-deadbeef.wav"
    stale.write_bytes(b"junk")
    path = cue_path("start", tmp_path)
    assert not stale.exists()  # a retuned cue must not leave the old file to replay
    stamp = path.stat().st_mtime_ns
    assert cue_path("start", tmp_path) == path
    assert path.stat().st_mtime_ns == stamp  # second call reuses, never rewrites


def test_play_routes_through_afplay_on_mac(tmp_path, monkeypatch):
    import murmur.config

    monkeypatch.setattr(murmur.config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(sounds.sys, "platform", "darwin")
    monkeypatch.setattr(sounds.shutil, "which", lambda cmd: "/usr/bin/afplay")
    ran = threading.Event()
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        ran.set()

    monkeypatch.setattr(sounds.subprocess, "run", fake_run)
    Sounds().play("start")
    assert ran.wait(2), "afplay thread never ran"
    assert calls[0][0] == "afplay"
    played = Path(calls[0][1])
    assert played.exists() and played.suffix == ".wav" and played.parent == tmp_path / "cues"


def test_play_survives_no_afplay_and_no_audio(monkeypatch):
    # Fallback path: afplay missing on a "mac" (and, on CI, no output device
    # behind sounddevice either) must never raise; failures are swallowed.
    monkeypatch.setattr(sounds.sys, "platform", "darwin")
    monkeypatch.setattr(sounds.shutil, "which", lambda cmd: None)
    Sounds().play("start")
    Sounds(enabled=False).play("start")  # disabled: a plain no-op
    Sounds().play("no-such-cue")
