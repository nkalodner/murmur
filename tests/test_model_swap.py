"""Swapping models must never leave you with nothing.

A bad pick used to mean a Murmur that errored on every dictation with no
visible reason, which is how people ended up reinstalling. The loader now
falls back where it sensibly can and reports where it cannot.
"""

import pytest

from murmur.transcribe import int8_refused, load_with_fallback


def make_factory(outcomes: dict):
    """A Transcriber stand-in whose load() succeeds or raises per precision."""
    calls = []

    class Fake:
        def __init__(self, model, quantization, language):
            self.model_name, self.quantization, self.language = model, quantization, language
            self._model = None

        @property
        def ready(self):
            return self._model is not None

        def load(self):
            calls.append(self.quantization)
            err = outcomes.get(self.quantization)
            if err is not None:
                raise err
            self._model = object()

    return Fake, calls


RUNTIME_REFUSAL = RuntimeError(
    "[ONNXRuntimeError] : 9 : NOT_IMPLEMENTED : Could not find an implementation "
    "for ConvInteger(10) node with name '/conv1/Conv_quant'"
)


def test_int8_refused_recognises_the_runtime_message_and_not_a_download_error():
    assert int8_refused(RUNTIME_REFUSAL)
    assert not int8_refused(RuntimeError("HTTP Error 404: Not Found"))
    assert not int8_refused(OSError("connection reset"))


def test_a_clean_load_needs_no_fallback():
    factory, calls = make_factory({})
    t, notice = load_with_fallback("whisper-base", "int8", "zh", factory=factory)
    assert t.ready and t.quantization == "int8" and t.language == "zh"
    assert notice is None
    assert calls == ["int8"]


def test_a_refused_int8_build_falls_back_to_full_precision_with_a_notice():
    # Noah's whisper-large-v3-turbo case: the files arrived, the CPU said no.
    factory, calls = make_factory({"int8": RUNTIME_REFUSAL})
    t, notice = load_with_fallback("onnx-community/whisper-large-v3-turbo", "int8", None, factory=factory)
    assert t.ready and t.quantization is None
    assert calls == ["int8", None]
    assert notice and "full precision" in notice


def test_a_failed_int8_download_does_not_go_and_download_full_precision_too():
    # Offline is offline; a second, bigger download would not help.
    factory, calls = make_factory({"int8": OSError("connection reset")})
    with pytest.raises(OSError):
        load_with_fallback("whisper-base", "int8", None, factory=factory)
    assert calls == ["int8"]


def test_full_precision_failure_is_final():
    factory, calls = make_factory({None: RuntimeError("no such repo")})
    with pytest.raises(RuntimeError):
        load_with_fallback("onnx-community/nope", None, None, factory=factory)
    assert calls == [None]


def test_the_fallback_is_only_for_int8():
    # A refusal message on a full-precision build has nowhere to fall to.
    factory, calls = make_factory({None: RUNTIME_REFUSAL})
    with pytest.raises(RuntimeError):
        load_with_fallback("whisper-base", None, None, factory=factory)
    assert calls == [None]


def test_the_reason_shown_on_the_page_is_one_tidy_line():
    from murmur.app import _tidy_error

    raw = RuntimeError(
        "401 Client Error. (Request ID: Root=1-6aa1d760-4461594d642fae626deccddc;d649100e)\n\n"
        "Repository Not Found for url: https://huggingface.co/api/models/x/y.\n"
        "Please make sure you specified the correct repo_id."
    )
    text = _tidy_error(raw)
    assert "Request ID" not in text
    assert "\n" not in text
    assert text.startswith("401 Client Error. Repository Not Found")
    assert len(_tidy_error(RuntimeError("x" * 1000))) <= 220
    assert _tidy_error(RuntimeError("")) == "RuntimeError"
