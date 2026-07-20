"""ASR model choices.

Murmur hands ``config.model`` straight to ``onnx_asr.load_model()``, so
anything onnx-asr can load works: a known alias, or any Hugging Face repo
id containing a slash (resolved at load time). ``KNOWN_MODELS`` is the
curated menu the settings page offers directly — the models that make
sense for dictation on a CPU — and everything else rides the custom
field.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    name: str
    label: str
    languages: str
    download: str
    note: str
    # Reads config.language (Whisper-style decoders and Canary do;
    # Parakeet v3 detects the language on its own).
    uses_language: bool = False


KNOWN_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        name="nemo-parakeet-tdt-0.6b-v2",
        label="Parakeet v2 — the default",
        languages="English",
        download="~700 MB",
        note="NVIDIA's English dictation sweet spot: the best accuracy for its speed on a CPU.",
    ),
    ModelInfo(
        name="nemo-parakeet-tdt-0.6b-v3",
        label="Parakeet v3 — multilingual",
        languages="25 European languages",
        download="~700 MB",
        note="Same family and speed as v2, and it detects the spoken language by itself.",
    ),
    ModelInfo(
        name="whisper-base",
        label="Whisper base — small and quick",
        languages="99 languages",
        download="~80 MB",
        note="The lightest download and the widest language list, with noticeably softer accuracy. A language code helps it.",
        uses_language=True,
    ),
    ModelInfo(
        name="nemo-canary-1b-v2",
        label="Canary 1B v2 — most accurate multilingual",
        languages="25 European languages",
        download="~1 GB",
        note="NVIDIA's larger multilingual model. Stronger than Parakeet v3 but slower on a CPU, so the pause after speaking grows.",
        uses_language=True,
    ),
)

# The alias list shipped by onnx-asr 0.12, used only when the installed
# library can't be asked directly (e.g. in the test environment, which
# skips the ML stack). Slash-less names outside this set would make
# load_model() raise ModelNotSupportedError on the next dictation.
_FALLBACK_ALIASES = frozenset(
    {
        "gigaam-v2-ctc",
        "gigaam-v2-rnnt",
        "gigaam-v3-ctc",
        "gigaam-v3-rnnt",
        "gigaam-v3-e2e-ctc",
        "gigaam-v3-e2e-rnnt",
        "gigaam-multilingual-ctc",
        "gigaam-multilingual-large-ctc",
        "nemo-fastconformer-ru-ctc",
        "nemo-fastconformer-ru-rnnt",
        "nemo-parakeet-ctc-0.6b",
        "nemo-parakeet-rnnt-0.6b",
        "nemo-parakeet-tdt-0.6b-v2",
        "nemo-parakeet-tdt-0.6b-v3",
        "nemo-canary-1b-v2",
        "whisper-base",
    }
)


def known_model_names() -> frozenset[str]:
    """Alias names the installed onnx-asr can download by itself.

    Asks the library when possible, since new versions grow the list;
    falls back to the names known at Murmur's release otherwise.
    """
    try:
        from typing import get_args

        from onnx_asr.loader import AsrNames

        names = frozenset(get_args(AsrNames))
        if names:
            return names
    except Exception:
        pass
    return _FALLBACK_ALIASES | {m.name for m in KNOWN_MODELS}


def check_model_name(name: str) -> str | None:
    """A readable problem string when onnx-asr would refuse `name`, else None.

    Anything with a slash is a Hugging Face repo id and resolves at load
    time, so it passes; a bare name must be an alias the library knows.
    """
    if "/" in name:
        return None
    if name in known_model_names():
        return None
    return (
        f'"{name}" is not a model name this install of onnx-asr recognizes. '
        "Pick one from the list, or use a full Hugging Face repo id "
        "(with a slash), like onnx-community/whisper-large-v3-turbo."
    )
