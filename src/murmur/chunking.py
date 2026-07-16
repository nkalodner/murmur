"""Split long recordings at quiet points so each piece fits the model window.

Parakeet ONNX exports handle roughly 25 seconds per pass, so longer
recordings get cut at the quietest 20 ms frame near each boundary and
transcribed piece by piece.
"""

from __future__ import annotations

import numpy as np

TARGET_SR = 16000
MAX_CHUNK_S = 22.0  # keep a margin under the ~25 s model window
SEARCH_S = 6.0  # hunt for silence in the last stretch of each window
FRAME_S = 0.02


def split_for_asr(
    wav: np.ndarray, sr: int = TARGET_SR, max_chunk_s: float = MAX_CHUNK_S
) -> list[np.ndarray]:
    max_len = int(max_chunk_s * sr)
    min_keep = int(0.05 * sr)
    if len(wav) < min_keep:
        return []
    if len(wav) <= max_len:
        return [wav]
    frame = int(FRAME_S * sr)
    pieces: list[np.ndarray] = []
    start = 0
    while len(wav) - start > max_len:
        win_end = start + max_len
        search_start = max(start + frame, win_end - int(SEARCH_S * sr))
        seg = wav[search_start:win_end]
        n = len(seg) // frame
        if n > 0:
            rms = np.sqrt((seg[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
            cut = search_start + int(rms.argmin()) * frame + frame // 2
        else:
            cut = win_end
        if cut <= start + min_keep:
            cut = win_end
        pieces.append(wav[start:cut])
        start = cut
    pieces.append(wav[start:])
    return [p for p in pieces if len(p) >= min_keep]
