"""Generated audio cues: right length, no clipping, clean fade in/out, and
the on-disk WAV cache + afplay routing behind the macOS system-player path."""
import sys
import threading
import wave
from pathlib import Path

import numpy as np
import pytest

import murmur.sounds as sounds
from murmur.sounds import (
    CUES, GAINS, SR, TAIL_MARGIN, VOLUME, Sounds, cue_path, duration, render,
)


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


# ── volume ─────────────────────────────────────────────────────────────


def test_volume_scales_amplitude_linearly():
    for name in CUES:
        full = np.max(np.abs(render(name)))
        assert np.max(np.abs(render(name, 0.5))) == pytest.approx(full / 2, rel=1e-5)
        assert not render(name, 0.0).any()


def test_volume_is_clamped_not_trusted():
    # A config edited by hand must not be able to push a cue past the ceiling.
    for name in CUES:
        loud = render(name, 5.0)
        assert np.max(np.abs(loud)) <= VOLUME * GAINS[name] + 1e-6
        assert not render(name, -1.0).any()


def test_volume_change_writes_its_own_cue_file(tmp_path):
    quiet = cue_path("start", tmp_path, volume=0.3)
    loud = cue_path("start", tmp_path, volume=1.0)
    assert quiet != loud  # the checksum in the name keeps them apart
    assert loud.exists()  # and the newer one really landed


def test_silent_settings_play_nothing(monkeypatch):
    played = []
    monkeypatch.setattr(sounds.sys, "platform", "darwin")
    monkeypatch.setattr(sounds.shutil, "which", lambda cmd: "/usr/bin/afplay")
    monkeypatch.setattr(sounds.subprocess, "run", lambda cmd, **kw: played.append(cmd))
    Sounds(volume=0.0).play("start")
    Sounds(enabled=False, volume=1.0).play("start")
    threading.Event().wait(0.2)
    assert played == []


# ── chime bleed ────────────────────────────────────────────────────────


def test_bleed_covers_the_whole_cue_plus_margin():
    # What the recorder mutes has to outlast what the speaker plays, or the
    # tail of the chime still lands in the take.
    s = Sounds(volume=1.0)
    assert s.bleed_seconds("start") == pytest.approx(duration("start") + TAIL_MARGIN)
    assert s.bleed_seconds("start") > duration("start")


def test_bleed_stays_close_to_the_cue():
    # The window is muted speech as well as muted chime, so it must not run
    # far past the cue. A player's start-up delay is handled by re-anchoring
    # (on_audible), never by padding this out.
    s = Sounds(volume=1.0)
    assert s.bleed_seconds("start") - duration("start") <= 0.08


def test_on_audible_fires_before_the_player_runs(monkeypatch, tmp_path):
    import murmur.config

    monkeypatch.setattr(murmur.config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(sounds.sys, "platform", "darwin")
    monkeypatch.setattr(sounds.shutil, "which", lambda cmd: "/usr/bin/afplay")
    order, done = [], threading.Event()

    def fake_run(cmd, **kwargs):
        order.append("play")
        done.set()

    monkeypatch.setattr(sounds.subprocess, "run", fake_run)
    Sounds().play("start", on_audible=lambda: order.append("mute"))
    assert done.wait(2)
    # Muting after the sound started would leave the chime's head in the take.
    assert order == ["mute", "play"]


def test_on_audible_is_skipped_when_nothing_sounds(monkeypatch):
    monkeypatch.setattr(sounds.sys, "platform", "darwin")
    monkeypatch.setattr(sounds.shutil, "which", lambda cmd: "/usr/bin/afplay")
    monkeypatch.setattr(sounds.subprocess, "run", lambda cmd, **kw: None)
    fired = []
    Sounds(volume=0.0).play("start", on_audible=lambda: fired.append(1))
    Sounds(enabled=False).play("start", on_audible=lambda: fired.append(1))
    threading.Event().wait(0.2)
    assert fired == []


def test_nothing_audible_means_nothing_muted():
    # No cue, no bleed: muting the head of a take is tied to a real chime.
    assert Sounds(enabled=False).bleed_seconds("start") == 0.0
    assert Sounds(volume=0.0).bleed_seconds("start") == 0.0
    assert Sounds().bleed_seconds("no-such-cue") == 0.0
