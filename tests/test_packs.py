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
    # Qualtrics feature nouns that are also ordinary English. They belong in
    # the pack only as part of a multi-word phrase ("Question Block"), never
    # on their own, or the pack recases everyday sentences.
    "dashboard", "quota", "distribution", "widget", "ticket", "block",
    "branch", "scoring", "report", "reports", "logic", "flow", "list",
    "engagement", "pulse", "action", "workflow", "project",
}

# Ordinary sentences a PM might dictate that contain no pack term at all. The
# pack must be completely invisible on these.
UNTOUCHED = [
    "we should block off time to review the report before the meeting",
    "the branch is ready and the ticket is closed",
    "there is some slack in the timeline so let us zoom in on the funnel",
    "send the list to the team and flag anything that looks off",
    "the logic here is that a shorter survey gets a better response",
    "i will action that after the sync and update the project",
]


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


def test_a_pack_is_invisible_on_ordinary_speech():
    # The failure that makes a pack unshippable: it fires on sentences that
    # have nothing to do with the domain.
    vocab, pairs = merge(["qualtrics"], [], [])
    for text in UNTOUCHED:
        assert process(text, vocabulary=vocab, replacements=pairs).strip() == text


def test_a_pack_never_loses_a_word_it_did_not_mean_to():
    # Vocabulary snapping fixes spelling; it must not delete the words around
    # what it fixed. (Replacements may join words, so they are excluded here.)
    vocab, _ = merge(["qualtrics"], [], [])
    said = [
        "a matrix table with display logic in the second question block",
        "put the embedded data at the top of the survey flow",
        "an anonymous link and a contact list for the pilot",
        "text iq and stats iq both run nightly",
    ]
    for text in said:
        out = process(text, vocabulary=vocab).strip()
        assert len(out.split()) == len(text.split()), f"{text!r} -> {out!r}"


def test_longer_replacements_win_over_the_shorter_ones_they_contain():
    # Pairs apply in order, so "three sixty" ahead of "three sixty five" would
    # leave "360 five".
    _, pairs = merge(["qualtrics"], [], [])
    assert process("the three sixty five day curve", replacements=pairs).strip() == (
        "the 365 day curve"
    )
    assert process("kicking off a three sixty", replacements=pairs).strip() == (
        "kicking off a 360"
    )
