"""Personal dictionary: vocabulary snapping, replacements, and the guards that
keep ordinary speech from being rewritten."""
import itertools

from murmur.textproc import apply_replacements, apply_vocabulary, clean, process

VOCAB = ["Wispr", "Photoglobe", "Kalodner", "Claude Code"]


def test_vocabulary_snaps_near_misses():
    assert apply_vocabulary("i love wisper", VOCAB) == "i love Wispr"
    assert apply_vocabulary("open photo globe now", VOCAB) == "open Photoglobe now"


def test_vocabulary_leaves_ordinary_words_alone():
    # the "Andi" bug: a short name must not rewrite "and" / "and i"
    assert apply_vocabulary("me and i went", ["Andi"]) == "me and i went"
    assert apply_vocabulary("cats and dogs", ["Andi"]) == "cats and dogs"


def test_vocabulary_noop_without_entries():
    assert apply_vocabulary("hello there", []) == "hello there"


def test_replacements_case_insensitive_word_boundary():
    pairs = [{"from": "cloud code", "to": "Claude Code"}]
    assert apply_replacements("open cloud code please", pairs) == "open Claude Code please"
    assert apply_replacements("Cloud code rocks", pairs) == "Claude Code rocks"


def test_clean_trailing_space():
    assert clean("  hi   there ", trailing_space=True) == "hi there "
    assert clean("  hi   there ", trailing_space=False) == "hi there"
    assert clean("   ") == ""


def test_process_pipeline_no_crash():
    pairs = [{"from": "cloud code", "to": "Claude Code"}]
    for combo in itertools.product(
        ["photo", "globe", "wisper", "and", "i", "me", "the", "cloud", "code", "", "a"], repeat=3
    ):
        process(" ".join(w for w in combo if w), replacements=pairs, vocabulary=VOCAB)
