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


@pytest.mark.parametrize("said,written", [
    ("W S A", "WSA"),
    ("the T F T meta", "the TFT meta"),
    ("a game of A R A M", "a game of ARAM"),
    ("the U I looks off", "the UI looks off"),
    ("check the I P address", "check the IP address"),
    ("ask the W S A. Then again", "ask the WSA. Then again"),
    ("the W S A's rules", "the WSA's rules"),
    ("three A M", "3:00 AM"),
    ("four thirty P M", "4:30 PM"),
])
def test_acronyms(said, written):
    assert format_speech(said) == written


@pytest.mark.parametrize("said,written", [
    ("twenty twenty six", "2026"),
    ("back in twenty twenty.", "back in 2020."),
    ("nineteen ninety nine", "1999"),
    ("nineteen ninety", "1990"),
    ("seventeen seventy six", "1776"),
    ("nineteen oh five", "1905"),
    ("twenty ten", "2010"),
    ("since twenty twenty-one", "since 2021"),
])
def test_years(said, written):
    assert format_speech(said) == written


@pytest.mark.parametrize("said,written", [
    ("four thirty", "4:30"),
    ("five thirty", "5:30"),
    ("meet at four thirty tomorrow", "meet at 4:30 tomorrow"),
    ("twelve forty five", "12:45"),
    ("nine fifteen", "9:15"),
    ("three oh five", "3:05"),
    ("ten twenty", "10:20"),
    ("six forty-seven", "6:47"),
])
def test_bare_times(said, written):
    assert format_speech(said) == written


@pytest.mark.parametrize("text", [
    "which one am I",       # bare "am" as a verb must survive
    "section four",
    "one of the reasons",
    "i am happy",
    "Plan A and Plan B",    # lone letters never join
    "A, B, or C",           # the model's own punctuation breaks a letter run
    "a b c",                # lowercase words are words, not spelled letters
    "seven eleven",         # bare ten/eleven/twelve minutes stay spoken
    "four sixty",           # not a valid clock time
    "eighteen nineteen twenty",       # counting run, not the year 1819
    "I was nineteen twenty years ago",  # a quantity, not a year
    "twenty four thirty",   # flanked by a number word: not 4:30
])
def test_left_alone(text):
    assert format_speech(text) == text


def test_no_crashes_on_fuzz():
    words = ["one", "two", "twenty", "five", "thirty", "oh", "am", "pm", "a.m.",
             "p.m.", "hundred", "percent", "dollars", "july", "third", "o'clock",
             "of", "the", "and", "", ".", ",", "am.", "1", "12", "0", "15", "60",
             "four", "nineteen", "fifteen", "years", "W", "S", "A", "I"]
    for combo in itertools.product(words, repeat=3):
        format_speech(" ".join(w for w in combo if w))
