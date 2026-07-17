"""Spoken-form formatting: correct conversions, conservative guards, no crashes."""
import itertools

import pytest

from murmur.formatting import format_speech


@pytest.mark.parametrize("said,written", [
    ("one pm", "1:00 PM"),
    ("three oh five p.m.", "3:05 PM"),
    ("meet at 10 15 am", "meet at 10:15 AM"),
    ("july third", "July 3rd"),
    ("the third of july", "the 3rd of July"),
    ("december thirty first", "December 31st"),
    ("fifty percent", "50%"),
    ("a hundred percent", "100%"),
    ("twenty dollars", "$20"),
    ("twenty five", "25"),
    ("eight o'clock", "8:00"),
    ("five o'clock pm", "5:00 PM"),
])
def test_conversions(said, written):
    assert format_speech(said) == written


@pytest.mark.parametrize("text", [
    "which one am I",       # bare "am" as a verb must survive
    "five thirty",          # ambiguous time, no meridiem
    "twenty twenty six",    # spoken year
    "nineteen ninety nine",
    "section four",
    "one of the reasons",
    "i am happy",
])
def test_left_alone(text):
    assert format_speech(text) == text


def test_no_crashes_on_fuzz():
    words = ["one", "two", "twenty", "five", "thirty", "oh", "am", "pm", "a.m.",
             "p.m.", "hundred", "percent", "dollars", "july", "third", "o'clock",
             "of", "the", "and", "", ".", ",", "am.", "1", "12", "0", "15", "60"]
    for combo in itertools.product(words, repeat=3):
        format_speech(" ".join(w for w in combo if w))
