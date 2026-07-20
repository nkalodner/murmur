"""Dictionary export/import: the payload shape and the merge rules."""

import pytest

from murmur.config import (
    Config,
    dictionary_payload,
    extract_dictionary,
    merge_dictionary,
)


def _cfg(**kw) -> Config:
    return Config(**kw)


def test_payload_shape_and_round_trip():
    cfg = _cfg(
        vocabulary=["Wispr", "Kalodner"],
        replacements=[{"from": "site url", "to": "noahkalodner.com"}],
        vocab_threshold=0.9,
    )
    payload = dictionary_payload(cfg)
    assert payload["kind"] == "murmur-dictionary"
    assert payload["version"] == 1
    assert payload["vocabulary"] == ["Wispr", "Kalodner"]
    assert payload["replacements"] == [{"from": "site url", "to": "noahkalodner.com"}]
    assert payload["vocab_threshold"] == 0.9
    # An export must always be importable as-is.
    vocab, repl = extract_dictionary(payload)
    assert vocab == ["Wispr", "Kalodner"]
    assert repl == [{"from": "site url", "to": "noahkalodner.com"}]


def test_payload_copies_do_not_alias_config():
    cfg = _cfg(vocabulary=["A"], replacements=[{"from": "x", "to": "y"}])
    payload = dictionary_payload(cfg)
    payload["vocabulary"].append("B")
    payload["replacements"][0]["to"] = "z"
    assert cfg.vocabulary == ["A"]
    assert cfg.replacements[0]["to"] == "y"


def test_extract_accepts_a_whole_config_file():
    # Importing a config.json someone copied over should just work.
    data = {
        "hotkey": "ctrl_r",
        "model": "nemo-parakeet-tdt-0.6b-v2",
        "vocabulary": ["Afterglow"],
        "replacements": [{"from": "after glow", "to": "Afterglow"}],
    }
    vocab, repl = extract_dictionary(data)
    assert vocab == ["Afterglow"]
    assert repl == [{"from": "after glow", "to": "Afterglow"}]


def test_extract_drops_empty_entries():
    vocab, repl = extract_dictionary(
        {
            "vocabulary": ["  Wispr  ", "", "   "],
            "replacements": [{"from": "  ", "to": "kept?"}, {"from": "a", "to": "b"}],
        }
    )
    assert vocab == ["Wispr"]
    assert repl == [{"from": "a", "to": "b"}]


@pytest.mark.parametrize(
    "bad",
    [
        "just a string",
        ["a", "list"],
        {"vocabulary": "not-a-list"},
        {"vocabulary": [1, 2]},
        {"replacements": [{"from": 1, "to": "x"}]},
        {"replacements": "nope"},
        {},  # nothing to import
        {"vocabulary": [], "replacements": []},
    ],
)
def test_extract_rejects_bad_payloads(bad):
    with pytest.raises(ValueError):
        extract_dictionary(bad)


def test_merge_dedupes_case_insensitively_and_counts():
    cfg = _cfg(vocabulary=["Wispr"], replacements=[{"from": "a", "to": "local"}])
    words, pairs = merge_dictionary(
        cfg,
        ["wispr", "Kalodner", "KALODNER"],
        [{"from": "A", "to": "imported"}, {"from": "b", "to": "c"}],
    )
    assert words == 1
    assert pairs == 1
    assert cfg.vocabulary == ["Wispr", "Kalodner"]
    # The local pair for "a" wins; only "b" arrives.
    assert cfg.replacements == [{"from": "a", "to": "local"}, {"from": "b", "to": "c"}]


def test_merge_into_a_fresh_config():
    cfg = _cfg()
    words, pairs = merge_dictionary(cfg, ["One", "Two"], [{"from": "x", "to": "y"}])
    assert (words, pairs) == (2, 1)
    assert cfg.vocabulary == ["One", "Two"]
    assert cfg.replacements == [{"from": "x", "to": "y"}]


def test_merge_twice_is_a_no_op():
    cfg = _cfg()
    merge_dictionary(cfg, ["One"], [{"from": "x", "to": "y"}])
    words, pairs = merge_dictionary(cfg, ["one"], [{"from": "X", "to": "z"}])
    assert (words, pairs) == (0, 0)
    assert cfg.vocabulary == ["One"]
    assert cfg.replacements == [{"from": "x", "to": "y"}]


def test_merged_config_still_validates():
    from murmur.config import validate

    cfg = _cfg()
    vocab, repl = extract_dictionary(
        {"vocabulary": ["Wispr"], "replacements": [{"from": "a", "to": "b"}]}
    )
    merge_dictionary(cfg, vocab, repl)
    validate(cfg)  # must not raise
