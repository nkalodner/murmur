"""Generated audio cues: right length, no clipping, clean fade in/out."""
import numpy as np

from murmur.sounds import CUES, GAINS, SR, VOLUME, render


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
