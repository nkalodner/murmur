import pytest

from murmur.config import Config, validate
from murmur.packs import PACKS, catalog, merge, unknown_ids
from murmur.textproc import process

# Ordinary English that a vocabulary entry must never recase mid-sentence, and
# that a replacement must never claim as its left side.
COMMON_WORDS = {
    "segment", "notion", "frontline", "lifecycle", "slack", "zoom",
    "amplitude", "workday", "snowflake", "confluence", "the", "and", "sync",
    "stand", "up", "test", "brand", "design", "core", "text", "driver",
    "predict", "discover", "directory", "response", "survey", "feedback",
}


def test_catalog_shape():
    entries = catalog()
    assert entries, "at least one pack ships"
    for entry in entries:
        assert set(entry) == {"id", "name", "description", "vocabulary", "replacements"}
        assert entry["vocabulary"] and entry["replacements"]
        assert all(isinstance(w, str) and w.strip() for w in entry["vocabulary"])
        assert all(set(r) == {"from", "to"} for r in entry["replacements"])


def test_merge_puts_the_user_first():
    # Replacements are applied in order, so leading is what makes a personal
    # fix beat a pack's.
    vocab, pairs = merge(["qualtrics"], ["Photoglobe"], [{"from": "ex em", "to": "XM Platform"}])
    assert vocab[0] == "Photoglobe"
    assert pairs[0] == {"from": "ex em", "to": "XM Platform"}
    assert len(vocab) > 1 and len(pairs) > 1


def test_a_personal_fix_wins_over_the_pack():
    _, pairs = merge(["qualtrics"], [], [{"from": "ex em", "to": "XM Platform"}])
    typed = process("the ex em roadmap", replacements=pairs)
    assert typed.strip() == "the XM Platform roadmap"


def test_merge_without_packs_is_the_users_dictionary():
    vocab, pairs = merge([], ["Photoglobe"], [{"from": "a", "to": "b"}])
    assert vocab == ["Photoglobe"]
    assert pairs == [{"from": "a", "to": "b"}]


def test_merge_skips_an_unknown_pack():
    # A config naming a pack a later version dropped still has to run.
    vocab, pairs = merge(["nope"], ["Mine"], [])
    assert vocab == ["Mine"] and pairs == []


def test_unknown_ids_names_only_the_missing():
    assert unknown_ids(["qualtrics", "nope"]) == ["nope"]
    assert unknown_ids([]) == []
    assert unknown_ids(None) == []


def test_config_rejects_an_unknown_pack():
    with pytest.raises(ValueError, match="unknown dictionary pack"):
        validate(Config(dictionary_packs=["not-a-pack"]))


def test_config_accepts_a_real_pack_and_defaults_to_none():
    validate(Config(dictionary_packs=["qualtrics"]))  # must not raise
    assert Config().dictionary_packs == []


@pytest.mark.parametrize("said, typed", [
    ("we shipped the quality tricks integration", "we shipped the Qualtrics integration"),
    ("the employee x m dashboard", "the EmployeeXM dashboard"),
    ("see sat is up this quarter", "CSAT is up this quarter"),
    ("lets a b test the p zero fix", "lets A/B test the P0 fix"),
    ("stats i q says otherwise", "Stats iQ says otherwise"),
])
def test_qualtrics_pack_end_to_end(said, typed):
    vocab, pairs = merge(["qualtrics"], [], [])
    assert process(said, vocabulary=vocab, replacements=pairs).strip() == typed


def test_pack_terms_avoid_ordinary_english():
    # A single-word entry that is also a normal word would recase it in the
    # middle of a sentence, and a one-word replacement source would rewrite
    # real speech. Both are the failure mode that makes a pack unshippable.
    for pack in PACKS.values():
        for word in pack.vocabulary:
            if " " not in word:
                assert word.lower() not in COMMON_WORDS, f"{pack.id}: {word}"
        for src, _ in pack.replacements:
            assert src == src.lower(), f"{pack.id}: {src!r} must be lowercase"
            if " " not in src:
                assert src not in COMMON_WORDS, f"{pack.id}: {src}"


def test_pack_replacements_have_no_duplicate_sources():
    for pack in PACKS.values():
        sources = [src for src, _ in pack.replacements]
        assert len(sources) == len(set(sources)), f"{pack.id} repeats a source"
