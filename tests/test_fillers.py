"""Filler-word removal.

The bar here is asymmetric: leaving a stray "um" in is a small annoyance,
silently deleting a word someone actually said is a bug they may not notice
until it matters. So most of these pin what must NOT be touched.
"""
import pytest

from murmur.fillers import DEFAULT_FILLERS, build_pattern, remove_fillers


@pytest.mark.parametrize("src,want", [
    ("um, I think this works", "I think this works"),
    ("So um the thing", "So the thing"),
    ("one um two um three", "one two three"),
    ("I think, um.", "I think."),
    ("Well, um... maybe", "Well... maybe"),
    ("uh what about this", "what about this"),
])
def test_removes_fillers(src, want):
    assert remove_fillers(src) == want


def test_comma_fenced_filler_takes_its_commas_with_it():
    """'a great, um, idea' must not be left as 'a great, idea'."""
    assert remove_fillers("That's a great, um, idea") == "That's a great idea"


def test_leading_filler_hands_the_capital_to_the_next_word():
    assert remove_fillers("Um, hello there") == "Hello there"
    assert remove_fillers("Uh, um, hello") == "Hello"


def test_lowercase_input_keeps_its_case():
    """Never invent capitalization the model did not produce."""
    assert remove_fillers("uh, hello there") == "hello there"


@pytest.mark.parametrize("text", [
    "umbrella umpire",          # filler as a prefix
    "a drum and a scrum",       # filler inside a word
    "Send it to Umeå",          # accented letter right after
    "uh-huh, that works",       # hyphenated, and it means yes
    "no fillers at all here",
    "The sum of the numbers",
])
def test_leaves_real_words_alone(text):
    assert remove_fillers(text) == text


def test_filler_free_text_is_returned_byte_for_byte():
    """The strong safety property: no match means no rewriting at all."""
    text = "Two  spaces , odd  punctuation .  Left exactly as it came."
    assert remove_fillers(text) is text or remove_fillers(text) == text


def test_all_filler_take_keeps_the_original():
    """Better to paste 'Um.' than to paste nothing and lose the take."""
    assert remove_fillers("Um.") == "Um."
    assert remove_fillers("um uh um") == "um uh um"


def test_case_insensitive():
    assert remove_fillers("The UM standard") == "The standard"
    assert remove_fillers("Um the thing") == "The thing"


def test_custom_word_list():
    assert remove_fillers("I like, like, this", ["like"]) == "I this"
    # And the defaults stop applying when a custom list is given.
    assert remove_fillers("um hello", ["like"]) == "um hello"


def test_empty_word_list_is_a_no_op():
    assert remove_fillers("um hello", []) == "um hello"
    assert build_pattern([]) is None
    assert build_pattern(["", "  "]) is None


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_blank_input(text):
    assert remove_fillers(text) == text


def test_defaults_are_only_non_words():
    """Guard the list itself: nothing here may be a real English word."""
    assert set(DEFAULT_FILLERS) == {"um", "uh", "erm", "uhm"}


def test_never_crashes_on_odd_input():
    for text in ["um" * 200, "...", "um,,,um", "a" * 5000 + " um", "um\num\num"]:
        assert isinstance(remove_fillers(text), str)


def test_pipeline_order_lets_formatting_still_see_the_time():
    """um before a spoken time must not block the 1:00 PM rewrite."""
    from murmur.textproc import process

    assert process("um, one pm", trailing_space=False) == "1:00 PM"


def test_pipeline_toggle_off():
    """With the toggle off the filler survives, exactly as the model said it."""
    from murmur.textproc import process

    assert process("um, hello", remove_fillers=False, trailing_space=False) == "um, hello"
