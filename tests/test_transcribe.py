"""The Transcriber's language is a decode-time argument, not a load-time one.

That is what lets the tray switch languages on a multi-gigabyte Whisper
without dropping it and reloading on the next dictation.
"""

import sys
import types

import numpy as np
import pytest

from murmur.chunking import TARGET_SR
from murmur.transcribe import Transcriber


class FakeModel:
    def __init__(self):
        self.calls = []

    def recognize(self, chunks, sample_rate=None, **kwargs):
        self.calls.append(kwargs.get("language"))
        return ["ok"] * len(chunks)


@pytest.fixture
def fake_onnx_asr(monkeypatch):
    """Stand in for the ML stack, counting how often a model is loaded."""
    model = FakeModel()
    loads = []
    pkg = types.ModuleType("onnx_asr")

    def load_model(name, quantization=None):
        loads.append((name, quantization))
        return model

    pkg.load_model = load_model
    monkeypatch.setitem(sys.modules, "onnx_asr", pkg)
    return model, loads


def _speech(seconds=1.0):
    return np.zeros(int(seconds * TARGET_SR), dtype=np.float32)


def test_language_change_does_not_reload_the_model(fake_onnx_asr):
    model, loads = fake_onnx_asr
    t = Transcriber("whisper-base", None, None)
    t.transcribe(_speech())
    t.language = "zh"  # what the tray switch does
    t.transcribe(_speech())
    t.language = "en"
    t.transcribe(_speech())

    assert len(loads) == 1, "the model was reloaded on a language change"
    assert model.calls == [None, "zh", "en"]


def test_a_blank_language_is_left_off_the_call(fake_onnx_asr):
    model, _ = fake_onnx_asr
    t = Transcriber("whisper-base", None, None)
    t.transcribe(_speech())
    # Absent, not None: onnx-asr reads a missing key as "detect it".
    assert model.calls == [None]


def test_too_short_audio_never_loads_a_model(fake_onnx_asr):
    _, loads = fake_onnx_asr
    assert Transcriber("whisper-base", None, "zh").transcribe(_speech(0.1)) == ""
    assert loads == []


def test_a_long_take_goes_through_one_piece_at_a_time(fake_onnx_asr, monkeypatch):
    # A two-minute take is six pieces. As one batch the model holds all six
    # in memory at once; in turn it only ever holds one.
    import murmur.transcribe as transcribe

    model, _ = fake_onnx_asr
    sizes = []
    original = model.recognize

    def recognize(chunks, sample_rate=None, **kwargs):
        sizes.append(len(chunks))
        return original(chunks, sample_rate=sample_rate, **kwargs)

    model.recognize = recognize
    monkeypatch.setattr(transcribe, "split_for_asr", lambda wav: [wav[:8000]] * 4)
    assert Transcriber("whisper-base", None, None).transcribe(_speech()) == "ok ok ok ok"
    assert sizes == [1, 1, 1, 1]


def test_a_model_without_a_language_option_is_asked_plainly(fake_onnx_asr, monkeypatch):
    import murmur.transcribe as transcribe

    model, _ = fake_onnx_asr
    seen = []

    def recognize(chunks, sample_rate=None, **kwargs):
        seen.append(dict(kwargs))
        if kwargs:
            raise TypeError("unexpected keyword argument 'language'")
        return ["ok"]

    model.recognize = recognize
    monkeypatch.setattr(transcribe, "split_for_asr", lambda wav: [wav[:8000]] * 3)
    assert Transcriber("parakeet", None, "fr").transcribe(_speech()) == "ok ok ok"
    # Offered once, refused once, then not offered again for this take.
    assert seen == [{"language": "fr"}, {}, {}, {}]
