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


# -- the matcher must never destroy an ordinary word --------------------------

def test_an_off_size_window_never_eats_an_article():
    # "a matrix table" joins to within 0.96 of "matrixtable", which cleared the
    # off-size bar and deleted the article.
    assert apply_vocabulary("a matrix table with ten rows", ["Matrix Table"]) == (
        "a Matrix Table with ten rows"
    )
    assert apply_vocabulary("an anonymous link please", ["Anonymous Link"]) == (
        "an Anonymous Link please"
    )


def test_a_short_entry_word_never_replaces_a_function_word():
    # "iQ" is within threshold of "in", so "Text in the link" was typing as
    # "Text iQ the link" with the preposition gone.
    assert apply_vocabulary("Piped Text in the link", ["Text iQ"]) == (
        "Piped Text in the link"
    )
    # The real thing still matches.
    assert apply_vocabulary("text iq runs nightly", ["Text iQ"]) == (
        "Text iQ runs nightly"
    )


def test_off_size_matching_still_works_where_it_is_meant_to():
    # The case k+1 exists for: one entry word said as two.
    assert apply_vocabulary("the photo globe dashboard", ["Photoglobe"]) == (
        "the Photoglobe dashboard"
    )
