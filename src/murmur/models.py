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


# The 25 European languages NVIDIA trained Canary v2 and Parakeet v3 on.
# Curated on purpose: Canary's tokenizer carries the whole ISO 639-1 list,
# so <|zh|> resolves fine and the model then emits confident nonsense.
# Checking a code against the vocab would prove nothing.
EUROPEAN_25 = frozenset(
    "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro ru sk sl es sv uk".split()
)

# (code, English name) for the languages Murmur offers in a menu, in menu
# order. Short by design: Whisper knows 99 and a tray submenu has to stay
# readable, so this is the common set, not the complete one. The settings
# page still takes any code by hand.
COMMON_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("zh", "Chinese (Mandarin)"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("tr", "Turkish"),
    ("vi", "Vietnamese"),
)


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
    # The codes the model was actually trained on, or None for "nothing we
    # restrict" (Whisper's 99 cover everything in COMMON_LANGUAGES).
    language_codes: frozenset[str] | None = None
    # Whether leaving the language blank means "work it out". Whisper runs
    # a real detection pass; Canary just decodes as English, which is how
    # spoken Mandarin came out as English words.
    detects_language: bool = False


KNOWN_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        name="nemo-parakeet-tdt-0.6b-v2",
        label="Parakeet v2 — the default",
        languages="English",
        download="~700 MB",
        note="NVIDIA's English dictation sweet spot: the best accuracy for its speed on a CPU.",
        language_codes=frozenset({"en"}),
    ),
    ModelInfo(
        name="nemo-parakeet-tdt-0.6b-v3",
        label="Parakeet v3 — multilingual",
        languages="25 European languages",
        download="~700 MB",
        note="Same family and speed as v2, and it detects the spoken language by itself.",
        language_codes=EUROPEAN_25,
        detects_language=True,
    ),
    ModelInfo(
        name="whisper-base",
        label="Whisper base — small and quick",
        languages="99 languages",
        download="~80 MB",
        note="The lightest download and the widest language list, with noticeably softer accuracy. A language code helps it.",
        uses_language=True,
        detects_language=True,
    ),
    ModelInfo(
        name="nemo-canary-1b-v2",
        label="Canary 1B v2 — most accurate multilingual",
        languages="25 European languages",
        download="~1 GB",
        note="NVIDIA's larger multilingual model. Stronger than Parakeet v3 but slower on a CPU, so the pause after speaking grows.",
        uses_language=True,
        language_codes=EUROPEAN_25,
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


def model_info(name: str) -> ModelInfo | None:
    """The curated entry for `name`, or None for a custom repo id."""
    return next((m for m in KNOWN_MODELS if m.name == name), None)


def languages_for(name: str) -> list[tuple[str, str]]:
    """(code, English name) rows to offer for `name`, in menu order.

    Empty when the model ignores the language code, which is what keeps
    the menu off Parakeet. A custom repo id is unknown to us and almost
    always a Whisper export, so it gets the full list.
    """
    info = model_info(name)
    if info is None:
        return list(COMMON_LANGUAGES)
    if not info.uses_language:
        return []
    allowed = info.language_codes
    return [(c, n) for c, n in COMMON_LANGUAGES if allowed is None or c in allowed]


def detects_language(name: str) -> bool:
    """Whether a blank language code means "detect it" for this model."""
    info = model_info(name)
    return info.detects_language if info is not None else True


# The settings page asks what you speak, not which model you want. Europe goes
# to Parakeet v3, which works out the language by itself and is as quick as
# the default; everything else goes to the big Whisper, the only one that has
# held up for Mandarin, with the language pinned, because Whisper's own guess
# is what turned spoken Mandarin into English words in the first place.
SIMPLE_MODELS = {
    "english": "nemo-parakeet-tdt-0.6b-v2",
    "european": "nemo-parakeet-tdt-0.6b-v3",
    "world": "onnx-community/whisper-large-v3-turbo",
}


def simple_choices() -> list[dict]:
    """Rows for the "What do you speak?" picker: code, name, model, language.

    A European pick stores its code even though Parakeet ignores it, so the
    picker can show "French" back. A Parakeet v3 config with no language
    (from before this picker existed) has no row here on purpose: a generic
    "European" entry would sit right next to the languages it stands for,
    so the page shows one only when that is the current setup.
    """
    rows = [
        {"code": "en", "name": "English", "model": SIMPLE_MODELS["english"], "language": None},
    ]
    for code, name in COMMON_LANGUAGES:
        if code == "en":
            continue
        model = SIMPLE_MODELS["european"] if code in EUROPEAN_25 else SIMPLE_MODELS["world"]
        rows.append({"code": code, "name": name, "model": model, "language": code})
    return rows
