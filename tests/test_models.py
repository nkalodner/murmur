"""The model registry and the save-time model-name check."""

import sys
import types
from typing import Literal

from murmur.models import (
    KNOWN_MODELS,
    _FALLBACK_ALIASES,
    check_model_name,
    known_model_names,
)


def test_curated_models_are_loadable_names():
    # Every curated menu entry must be in the fallback alias set, so the
    # check passes even when onnx-asr can't be asked.
    for m in KNOWN_MODELS:
        assert m.name in _FALLBACK_ALIASES
        assert check_model_name(m.name) is None


def test_default_model_is_first_in_the_menu():
    from murmur.config import Config

    assert KNOWN_MODELS[0].name == Config().model


def test_repo_ids_always_pass():
    assert check_model_name("onnx-community/whisper-large-v3-turbo") is None
    assert check_model_name("alphacep/vosk-model-ru") is None


def test_unknown_bare_name_is_rejected_with_guidance():
    problem = check_model_name("parakeet")  # a likely typo of the real name
    assert problem is not None
    assert "parakeet" in problem
    assert "repo id" in problem


def test_prefers_the_installed_onnx_asr_alias_list(monkeypatch):
    # A stub onnx_asr.loader stands in for the installed library: its
    # alias list is the truth, even when it disagrees with the fallback.
    loader = types.ModuleType("onnx_asr.loader")
    loader.AsrNames = Literal["made-up-model", "whisper-base"]
    pkg = types.ModuleType("onnx_asr")
    monkeypatch.setitem(sys.modules, "onnx_asr", pkg)
    monkeypatch.setitem(sys.modules, "onnx_asr.loader", loader)

    names = known_model_names()
    assert names == frozenset({"made-up-model", "whisper-base"})
    assert check_model_name("made-up-model") is None
    # Present in the fallback list but absent from this "install".
    assert check_model_name("nemo-parakeet-tdt-0.6b-v2") is not None


def test_registry_entries_carry_the_ui_fields():
    for m in KNOWN_MODELS:
        assert m.label and m.languages and m.download and m.note


def test_only_the_multilingual_models_offer_a_language_menu():
    from murmur.models import languages_for

    # Parakeet ignores the code, so the tray has nothing to show.
    assert languages_for("nemo-parakeet-tdt-0.6b-v2") == []
    assert languages_for("nemo-parakeet-tdt-0.6b-v3") == []
    assert languages_for("whisper-base")
    assert languages_for("nemo-canary-1b-v2")


def test_canary_offers_no_chinese_but_whisper_does():
    from murmur.models import languages_for

    # The trap this menu exists to close: Canary's tokenizer carries every
    # ISO code, so <|zh|> resolves and the model emits confident nonsense.
    # It was trained on 25 European languages and must not offer Mandarin.
    canary = dict(languages_for("nemo-canary-1b-v2"))
    assert "zh" not in canary and "ja" not in canary
    assert "en" in canary and "fr" in canary
    assert "zh" in dict(languages_for("whisper-base"))


def test_custom_repo_ids_get_the_full_list():
    from murmur.models import COMMON_LANGUAGES, detects_language, languages_for

    # A custom repo is nearly always a Whisper export, which detects.
    assert languages_for("onnx-community/whisper-large-v3-turbo") == list(COMMON_LANGUAGES)
    assert detects_language("onnx-community/whisper-large-v3-turbo") is True


def test_blank_means_english_on_canary_and_detect_on_whisper():
    from murmur.models import detects_language

    assert detects_language("whisper-base") is True
    assert detects_language("nemo-canary-1b-v2") is False


def test_curated_language_codes_stay_inside_the_common_list():
    from murmur.models import COMMON_LANGUAGES, languages_for

    common = [c for c, _ in COMMON_LANGUAGES]
    assert len(common) == len(set(common))
    for m in KNOWN_MODELS:
        if not m.uses_language:
            continue
        # None means "nothing we restrict", so the whole common list shows.
        expected = (
            common
            if m.language_codes is None
            else [c for c in common if c in m.language_codes]
        )
        assert [c for c, _ in languages_for(m.name)] == expected
