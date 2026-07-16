"""Wrapper around onnx-asr models (Parakeet by default)."""

from __future__ import annotations

import logging
import time

import numpy as np

from murmur.chunking import TARGET_SR, split_for_asr

log = logging.getLogger("murmur")

MIN_SECONDS = 0.25  # anything shorter is a key fumble, skip it


class Transcriber:
    def __init__(
        self,
        model_name: str,
        quantization: str | None = "int8",
        language: str | None = None,
    ):
        self.model_name = model_name
        self.quantization = quantization
        self.language = language
        self._model = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        import onnx_asr

        t0 = time.monotonic()
        log.info(
            "Loading %s (%s). The first run downloads the model, which takes a while.",
            self.model_name,
            self.quantization or "fp32",
        )
        self._model = onnx_asr.load_model(self.model_name, quantization=self.quantization)
        log.info("Model ready in %.1fs", time.monotonic() - t0)

    def transcribe(self, wav: np.ndarray) -> str:
        if len(wav) < MIN_SECONDS * TARGET_SR:
            return ""
        self.load()
        chunks = split_for_asr(wav)
        if not chunks:
            return ""
        kwargs = {"language": self.language} if self.language else {}
        t0 = time.monotonic()
        try:
            results = self._model.recognize(chunks, sample_rate=TARGET_SR, **kwargs)
        except TypeError:
            # Model does not take a language option; retry plain.
            results = self._model.recognize(chunks, sample_rate=TARGET_SR)
        if isinstance(results, str):
            results = [results]
        text = " ".join(r.strip() for r in results if r and r.strip())
        log.debug(
            "Transcribed %.1fs of audio in %.2fs (%d chunk(s))",
            len(wav) / TARGET_SR,
            time.monotonic() - t0,
            len(chunks),
        )
        return text
