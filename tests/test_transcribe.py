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
