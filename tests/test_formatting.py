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
    ("the N P S score dropped", "the NPS score dropped"),
    ("we need an S L A here", "we need an SLA here"),
    ("sync with C S and P S", "sync with CS and PS"),
    ("I R S integration", "IRS integration"),   # a leading I can be the acronym
    ("our K P I s are green", "our KPIs are green"),   # the plural joins on
    # After an auxiliary, a leading "I" is the pronoun, not the first letter.
    ("Can I A B test the onboarding", "Can I AB test the onboarding"),
    ("Should I C C the team", "Should I CC the team"),
    ("did I O K that", "did I OK that"),
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


@pytest.mark.parametrize("text", [
    # A unit noun after the pair means an amount was said, not a clock.
    "three thirty minute meetings this week",
    "two fifteen minute demos",
    "book two thirty minute slots",
    "we ran five thirty second ads",
    "four thirty day trials",
    "two thirty-minute sessions",   # the model's own hyphen still counts
    # A label word before it means the number names something.
    "we're on version three twenty",
    "see section four fifteen",
    "step four thirty",
    "room nine fifteen",
])
def test_quantities_and_labels_are_not_times(text):
    assert format_speech(text) == text


@pytest.mark.parametrize("said, written", [
    # The guards must not swallow an ordinary time.
    ("let's meet at four thirty", "let's meet at 4:30"),
    ("push standup to nine forty five", "push standup to 9:45"),
    ("the review is at eleven thirty tomorrow", "the review is at 11:30 tomorrow"),
    ("the twenty twenty five roadmap", "the 2025 roadmap"),
])
def test_real_times_still_convert(said, written):
    assert format_speech(said) == written


@pytest.mark.parametrize("text", [
    "Can I C",              # too little left to be sure it was spelled at all
    "I think A and B are fine",
])
def test_acronym_leaves_pronouns_alone(text):
    assert format_speech(text) == text


@pytest.mark.parametrize("text", [
    # Murmur does not compose hundreds, so it leaves the whole amount spoken
    # rather than converting the tail and stranding the rest.
    "one hundred forty percent",
    "two hundred thirty dollars",
    "a hundred and fifty dollars",
])
def test_partial_hundreds_stay_spoken(text):
    assert format_speech(text) == text


@pytest.mark.parametrize("said, written", [
    ("ninety five percent", "95%"),
    ("a hundred percent", "100%"),
    ("twenty dollars", "$20"),
])
def test_plain_amounts_still_convert(said, written):
    assert format_speech(said) == written


def test_no_crashes_on_fuzz():
    words = ["one", "two", "twenty", "five", "thirty", "oh", "am", "pm", "a.m.",
             "p.m.", "hundred", "percent", "dollars", "july", "third", "o'clock",
             "of", "the", "and", "", ".", ",", "am.", "1", "12", "0", "15", "60",
             "four", "nineteen", "fifteen", "years", "W", "S", "A", "I"]
    for combo in itertools.product(words, repeat=3):
        format_speech(" ".join(w for w in combo if w))
