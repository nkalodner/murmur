"""Recorder head-muting: Murmur's own start chime never reaches the model.

The mic stream is already open when the cue sounds, so without this the take
begins with a low hum the model transcribes as "mm"/"mmhmm".
"""
import numpy as np

from murmur.audio import Recorder


def _feed(rec, blocks, size=100):
    """Push `blocks` blocks of all-ones audio through the audio callback."""
    for _ in range(blocks):
        rec._callback(np.ones((size, 1), dtype=np.float32), size, None, None)
    return np.concatenate(rec._chunks)


def test_mute_silences_exactly_the_requested_head():
    rec = Recorder()
    rec._sr = 1000  # 1 sample per ms, so the maths is readable
    rec.mute_for(0.25)  # 250 samples
    captured = _feed(rec, 5)  # 500 samples
    assert not captured[:250].any()  # the chime window is gone
    assert (captured[250:] == 1.0).all()  # speech after it is untouched


def test_mute_spans_block_boundaries():
    # The window rarely lines up with the block size; the leftover has to
    # carry into the next callback rather than being rounded away.
    rec = Recorder()
    rec._sr = 1000
    rec.mute_for(0.15)  # 150 samples, mid-block at 100
    captured = _feed(rec, 3)
    assert not captured[:150].any()
    assert (captured[150:] == 1.0).all()


def test_no_mute_keeps_every_sample():
    rec = Recorder()
    rec._sr = 1000
    rec.mute_for(0)  # sounds off: nothing to hide from
    assert (_feed(rec, 2) == 1.0).all()


def test_mute_does_not_touch_the_callers_buffer():
    # PortAudio reuses its input buffer; zeroing it in place would corrupt
    # whatever the driver does with it next.
    rec = Recorder()
    rec._sr = 1000
    rec.mute_for(0.1)
    block = np.ones((100, 1), dtype=np.float32)
    rec._callback(block, 100, None, None)
    assert (block == 1.0).all()


def test_start_clears_a_leftover_mute():
    rec = Recorder()
    rec._sr = 1000
    rec.mute_for(10)  # a take canceled before the window ran out
    rec._chunks = []
    rec._mute_samples = 0  # what start() does before opening the stream
    assert (_feed(rec, 2) == 1.0).all()


def test_muted_head_does_not_move_the_level_meter():
    rec = Recorder()
    rec._sr = 1000
    rec.mute_for(1.0)
    _feed(rec, 3)
    assert rec.current_level() == 0.0
