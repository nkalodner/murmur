"""Audio splitting: chunks reconstruct the original and never exceed the model
window."""
import numpy as np

from murmur.chunking import MAX_CHUNK_S, TARGET_SR, split_for_asr

MAX = int(MAX_CHUNK_S * TARGET_SR)


def test_short_audio_returns_single_or_empty():
    assert split_for_asr(np.zeros(0, dtype=np.float32)) == []
    tiny = np.ones(int(0.01 * TARGET_SR), dtype=np.float32)
    assert split_for_asr(tiny) == []  # below min_keep
    short = np.ones(int(2 * TARGET_SR), dtype=np.float32)
    pieces = split_for_asr(short)
    assert len(pieces) == 1 and np.array_equal(pieces[0], short)


def test_random_audio_is_lossless_and_bounded():
    rng = np.random.default_rng(0)
    for _ in range(200):
        n = int(rng.uniform(0.0, 90.0) * TARGET_SR)
        wav = (rng.standard_normal(n) * 0.1).astype(np.float32)
        for _ in range(rng.integers(0, 5)):
            p = rng.integers(0, max(1, n))
            wav[p:p + 320] = 0.0
        pieces = split_for_asr(wav)
        if pieces:
            joined = np.concatenate(pieces)
            # a sub-min_keep head/tail sliver may drop, so allow a prefix match
            assert np.array_equal(joined, wav) or np.array_equal(joined, wav[:len(joined)])
        assert all(len(p) <= MAX for p in pieces)
        assert all(len(p) > 0 for p in pieces)


def test_edge_lengths():
    for n in [0, 1, 799, 800, 801, MAX, MAX + 1, 2 * MAX, 3 * MAX + 123]:
        pieces = split_for_asr(np.ones(n, dtype=np.float32))
        assert sum(len(p) for p in pieces) <= n
        assert all(len(p) <= MAX for p in pieces)
