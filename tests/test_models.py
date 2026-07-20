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
