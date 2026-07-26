"""Drop spoken filler words from a transcript.

Speech is full of "um" and "uh" that nobody wants typed. The model hears them
faithfully, so they land in the paste unless something removes them.

Deliberately tiny and deliberately dumb. The default list is only the sounds
that are never English content words, because the cost of a wrong removal
(silently deleting a word you said) is far worse than the cost of leaving a
stray "um" in. Same lesson as the dictionary's "andi" bug: when in doubt, do
nothing. Anyone who wants a longer list can add to `filler_words` in
~/.murmur/config.json, which is where the aggressive choices belong.

The one guarantee worth holding onto: a transcript containing no fillers comes
back byte for byte unchanged.
"""

from __future__ import annotations

import re

# Never real words in English, so removing them cannot eat content.
# "like", "you know", "I mean", "sort of" are all real usages and stay out.
DEFAULT_FILLERS: tuple[str, ...] = ("um", "uh", "erm", "uhm")

# Punctuation left dangling once a word is lifted out of the middle of a
# sentence. Applied only when something was actually removed.
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
_REPEAT_PUNCT = re.compile(r"([,;:])\s*(?=[,.;:!?])")
_COLLAPSE_SPACE = re.compile(r"\s{2,}")
_LEADING_JUNK = re.compile(r"^[\s,;:]+")


def build_pattern(words) -> re.Pattern | None:
    """Match a filler plus the commas that were only there to fence it in.

    Eating the adjacent commas is what turns "a great, um, idea" into "a great
    idea" instead of leaving "a great, idea". The lookarounds keep hyphenated
    words whole, so "uh-huh" (which means yes) survives intact.
    """
    cleaned = sorted({w.strip().lower() for w in words if w and w.strip()}, key=len, reverse=True)
    if not cleaned:
        return None
    alternation = "|".join(re.escape(w) for w in cleaned)
    # The lookarounds hug the filler itself, NOT the optional leading comma:
    # anchoring them any wider stops the match from starting before the comma
    # in "a great, um, idea", which then strands it as "a great, idea".
    return re.compile(
        rf"(?:\s*,)?\s*(?<![\w'-])(?:{alternation})(?![\w'-])\s*,?\s*",
        re.IGNORECASE,
    )


def remove_fillers(text: str, words=DEFAULT_FILLERS) -> str:
    """Strip filler words, tidying the punctuation they leave behind."""
    if not text or not text.strip():
        return text
    pattern = build_pattern(words)
    if pattern is None or not pattern.search(text):
        return text  # nothing to do: return the original untouched

    out = pattern.sub(" ", text)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    out = _REPEAT_PUNCT.sub("", out)
    out = _COLLAPSE_SPACE.sub(" ", out)
    out = _LEADING_JUNK.sub("", out).strip()

    if not out or not re.search(r"\w", out):
        # The whole take was filler. Hand back the original rather than
        # paste nothing and leave someone wondering where their words went.
        return text
    # Removing a leading "Um," would otherwise leave the sentence lowercase.
    if text.lstrip()[:1].isupper() and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out
