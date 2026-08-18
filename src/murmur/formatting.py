"""Spoken-form formatting: things said aloud come out in their written shapes.
"one pm" types as "1:00 PM", "four thirty" as "4:30", "july third" as
"July 3rd", "twenty twenty six" as "2026", "fifty percent" as "50%", and
letters spelled out one at a time join into an acronym ("W S A" -> "WSA").
Deterministic regex rules, no model involved. Ambiguity resolves the way
dictation usually means it (a bare "four thirty" is a clock time), but the
grammar the model itself wrote is trusted: its punctuation breaks a letter
run ("A, B, or C" keeps its commas), "which one am I" is never a time, and
a number flanked by other number words stays a spoken counting run. Proper
nouns are the dictionary's job (textproc.apply_vocabulary), not this
module's.
"""

from __future__ import annotations

import re

_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_MONTHS = (
    "january february march april may june july august "
    "september october november december"
).split()
_ORD_UNITS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}

_alt = lambda words: "|".join(sorted(words, key=len, reverse=True))
_UNITS_A, _TEENS_A, _TENS_A = _alt(_UNITS), _alt(_TEENS), _alt(_TENS)
_HOUR_A = _alt(list(_UNITS) + ["ten", "eleven", "twelve"])
_MONTH_A = _alt(_MONTHS)
# a spoken two-digit figure: "oh five" -> 05, teens, tens, compounds
_TWO_DIGIT_A = rf"oh[ -](?:{_UNITS_A})|(?:{_TENS_A})(?:[ -](?:{_UNITS_A}))?|{_TEENS_A}"
# minutes: the same word forms, or two literal digits
_MIN_A = rf"{_TWO_DIGIT_A}|[0-5]\d"
_ORD_A = (
    rf"(?:{_alt(_TENS)})[ -](?:{_alt(_ORD_UNITS)})|{_alt(_ORD_UNITS)}"
)


def _word_num(text: str) -> int:
    """'twenty five' / 'twenty-five' / 'oh seven' / '45' -> int."""
    text = text.strip().lower().replace("-", " ")
    if text.isdigit():
        return int(text)
    total = 0
    for part in text.split():
        if part == "oh":
            continue
        total += _UNITS.get(part) or _TEENS.get(part) or _TENS.get(part) or 0
    return total


def _ord_num(text: str) -> int:
    text = text.strip().lower().replace("-", " ")
    total = 0
    for part in text.split():
        total += _ORD_UNITS.get(part) or _TENS.get(part) or 0
    return total


def _suffix(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# hour + optional minutes + meridiem ("one pm", "three oh five p.m.", "10 15 am").
# A dotted meridiem ("a.m.") owns its dots; a bare "am"/"pm" must not swallow
# the sentence period that follows it.
_MER = r"(?P<mer>[ap])(?:(?P<dots>\.)m\.?|m)(?=\W|$)"
_TIME = re.compile(
    rf"\b(?P<hour>{_HOUR_A}|1[0-2]|[1-9])"
    rf"(?:[ ](?P<min>{_MIN_A}))?"
    rf"[ ]?{_MER}",
    re.IGNORECASE,
)
_OCLOCK = re.compile(
    rf"\b(?P<hour>{_HOUR_A}|1[0-2]|[1-9])[ ]o'?clock"
    rf"(?:[ ](?P<omer>[ap])(?:\.m\.?|m))?(?=\W|$)",
    re.IGNORECASE,
)
_MONTH_DAY = re.compile(rf"\b(?P<month>{_MONTH_A})[ ](?P<ord>{_ORD_A})\b", re.IGNORECASE)
_DAY_OF_MONTH = re.compile(
    rf"\b(?P<ord>{_ORD_A})[ ]of[ ](?P<month>{_MONTH_A})\b", re.IGNORECASE
)
_NUM_PHRASE = rf"(?:{_TENS_A})(?:[ -](?:{_UNITS_A}))?|{_TEENS_A}|{_UNITS_A}"
_PERCENT = re.compile(rf"\b(?P<num>a hundred|(?:{_NUM_PHRASE})(?: hundred)?)[ ]percent(?=\W|$)", re.IGNORECASE)
_DOLLARS = re.compile(rf"\b(?P<num>a hundred|(?:{_NUM_PHRASE})(?: hundred)?)[ ]dollars(?=\W|$)", re.IGNORECASE)
_COMPOUND = re.compile(rf"\b(?P<tens>{_TENS_A})[ -](?P<unit>{_UNITS_A})\b", re.IGNORECASE)

# Letters spelled out one at a time join into an acronym ("W S A" -> "WSA").
# Only runs of bare capitals count — that is how the model writes letter
# names — so the words "a" and "I" never join into anything, and punctuation
# between letters breaks the run, keeping lists like "A, B, or C" intact.
_ACRONYM = re.compile(r"(?<![A-Za-z0-9.])(?:[A-Z] )+[A-Z](?![A-Za-z0-9])")

# Spoken years pair a century word with a two-digit tail: "twenty twenty six"
# -> 2026, "nineteen oh five" -> 1905, "seventeen seventy six" -> 1776.
# Centuries run thirteen through twenty; below that the words are far more
# often a clock time, which the bare-time rule owns ("ten thirty" -> 10:30).
_CENTURY_A = _alt([w for w, n in _TEENS.items() if n >= 13] + ["twenty"])
_YEAR = re.compile(
    rf"\b(?P<century>{_CENTURY_A})[ ](?P<tail>{_TWO_DIGIT_A})\b", re.IGNORECASE
)

# A bare hour + minutes is a clock time even with no am/pm ("four thirty" ->
# 4:30). The minutes have to sound like minutes: tens through fifty (with an
# optional unit), teens from thirteen up, or "oh five". A bare "ten",
# "eleven", or "twelve" after the hour stays spoken, so "seven eleven" is
# not turned into a time.
_BARE_MIN_A = (
    rf"oh[ -](?:{_UNITS_A})"
    rf"|(?:{_alt(['twenty', 'thirty', 'forty', 'fifty'])})(?:[ -](?:{_UNITS_A}))?"
    rf"|{_alt([w for w, n in _TEENS.items() if n >= 13])}"
)
_BARE_TIME = re.compile(
    rf"\b(?P<hour>{_HOUR_A})[ ](?P<min>{_BARE_MIN_A})\b", re.IGNORECASE
)

_NUMBER_WORDS = frozenset(_UNITS) | frozenset(_TEENS) | frozenset(_TENS)
# Another number word next to a match means a counting run or a larger spoken
# figure ("eighteen nineteen twenty"), and a quantity word after means an
# amount was said, not a clock or calendar ("nineteen twenty years ago").
_QUANTITY_AFTER = _NUMBER_WORDS | {"percent", "dollars", "years"}


def _neighbors(m: re.Match) -> tuple[str, str]:
    """The words immediately before and after a match, lowercased ("" if none)."""
    before = re.search(r"([a-z']+)\s+$", m.string[: m.start()], re.IGNORECASE)
    after = re.match(r"\s+([a-z']+)", m.string[m.end() :], re.IGNORECASE)
    return (
        before.group(1).lower() if before else "",
        after.group(1).lower() if after else "",
    )

# A bare "am" is a real word ("which one am I"), so without dots it only counts
# as a meridiem when minutes were said, or it ends the clause, or a clearly
# time-flavored word follows. "pm" and "a.m."/"p.m." are never ambiguous.
_AM_FOLLOWERS = {
    "tomorrow", "today", "tonight", "yesterday", "sharp", "on", "this", "next",
    "every", "and", "or", "to", "until", "till", "instead", "then", "for",
}


def _bare_am_ok(text: str, end: int, has_minutes: bool) -> bool:
    if has_minutes:
        return True
    rest = text[end:]
    if not rest or not rest.lstrip():
        return True
    stripped = rest.lstrip()
    if stripped[0] in ".,!?;:)":
        return True
    if rest[0] in ".,!?;:":
        return True
    next_word = re.match(r"[A-Za-z']+", stripped)
    return bool(next_word) and next_word.group(0).lower() in _AM_FOLLOWERS


def _amount(raw: str) -> int:
    raw = raw.lower()
    if raw == "a hundred":
        return 100
    if raw.endswith(" hundred"):
        return _word_num(raw[: -len(" hundred")]) * 100
    return _word_num(raw)


def format_speech(text: str) -> str:
    def time_sub(m: re.Match) -> str:
        mer = m.group("mer").upper() + "M"
        if mer == "AM" and not m.group("dots"):
            if not _bare_am_ok(m.string, m.end(), bool(m.group("min"))):
                return m.group(0)
        hour = _word_num(m.group("hour"))
        minute = _word_num(m.group("min")) if m.group("min") else 0
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            return m.group(0)
        return f"{hour}:{minute:02d} {mer}"

    def oclock_sub(m: re.Match) -> str:
        hour = _word_num(m.group("hour"))
        if not 1 <= hour <= 12:
            return m.group(0)
        mer = f" {m.group('omer').upper()}M" if m.group("omer") else ""
        return f"{hour}:00{mer}"

    def month_day_sub(m: re.Match) -> str:
        day = _ord_num(m.group("ord"))
        if not 1 <= day <= 31:
            return m.group(0)
        return f"{m.group('month').capitalize()} {day}{_suffix(day)}"

    def day_of_month_sub(m: re.Match) -> str:
        day = _ord_num(m.group("ord"))
        if not 1 <= day <= 31:
            return m.group(0)
        return f"{day}{_suffix(day)} of {m.group('month').capitalize()}"

    def year_sub(m: re.Match) -> str:
        before, after = _neighbors(m)
        if before in _NUMBER_WORDS or after in _QUANTITY_AFTER:
            return m.group(0)
        return f"{_word_num(m.group('century'))}{_word_num(m.group('tail')):02d}"

    def bare_time_sub(m: re.Match) -> str:
        before, after = _neighbors(m)
        if before in _NUMBER_WORDS or after in _QUANTITY_AFTER:
            return m.group(0)
        hour = _word_num(m.group("hour"))
        minute = _word_num(m.group("min"))
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            return m.group(0)
        return f"{hour}:{minute:02d}"

    def compound_sub(m: re.Match) -> str:
        # Flanked by another tens/teens word it is part of a larger spoken
        # figure — a counting run, or a year fragment the year rule declined.
        before, after = _neighbors(m)
        year_words = set(_TENS) | set(_TEENS)
        if before in year_words or after in year_words:
            return m.group(0)
        return str(_word_num(m.group(0)))

    # Acronyms join first so a spelled "P M" reads as a meridiem to the time
    # rules; explicit am/pm times go before bare ones; years before bare
    # times and compounds so "twenty twenty six" is never split up.
    text = _ACRONYM.sub(lambda m: m.group(0).replace(" ", ""), text)
    text = _TIME.sub(time_sub, text)
    text = _OCLOCK.sub(oclock_sub, text)
    text = _MONTH_DAY.sub(month_day_sub, text)
    text = _DAY_OF_MONTH.sub(day_of_month_sub, text)
    text = _YEAR.sub(year_sub, text)
    text = _BARE_TIME.sub(bare_time_sub, text)
    text = _PERCENT.sub(lambda m: f"{_amount(m.group('num'))}%", text)
    text = _DOLLARS.sub(lambda m: f"${_amount(m.group('num'))}", text)
    text = _COMPOUND.sub(compound_sub, text)
    return text
