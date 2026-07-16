"""Transcript cleanup and the personal dictionary.

Two dictionary mechanisms, applied to every transcript before injection:

- Replacements: exact "heard -> typed" pairs, matched case-insensitively on
  word boundaries ("cloud code" -> "Claude Code"). For phrases the model
  reliably gets wrong in the same way.
- Vocabulary: words and phrases spelled the way you want them. Each
  transcript is scanned for stretches that sound close (SequenceMatcher on
  normalized text), and near misses snap to your spelling ("wisper" ->
  "Wispr", "photo globe" -> "Photoglobe"). Exact matches adopt the
  dictionary casing too, so add entries cased exactly how they should be
  typed, and stick to proper nouns and jargon rather than everyday words.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

DEFAULT_VOCAB_THRESHOLD = 0.82


def clean(text: str, trailing_space: bool = True) -> str:
    """Collapse whitespace; optionally add a trailing space so consecutive dictations flow."""
    out = " ".join(text.split())
    if not out:
        return ""
    return out + " " if trailing_space else out


def _match_case(replacement: str, matched: str) -> str:
    """Keep the user's casing if they gave one; else follow the matched text's lead."""
    if any(c.isupper() for c in replacement):
        return replacement
    if matched[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_replacements(text: str, pairs: list[dict]) -> str:
    for pair in pairs or []:
        src = str(pair.get("from") or "").strip()
        dst = str(pair.get("to") or "")
        if not src or not dst:
            continue
        pattern = re.compile(
            r"(?<!\w)" + re.escape(src).replace(r"\ ", r"\s+") + r"(?!\w)",
            re.IGNORECASE,
        )
        text = pattern.sub(lambda m: _match_case(dst, m.group(0)), text)
    return text


def _norm(token: str) -> str:
    return re.sub(r"[^\w']+", "", token.lower())


# Ordinary spoken words the vocabulary must never rewrite. Without this, a
# short entry like a name "Andi" would fuzzy-match "and" (and "and I") and
# rewrite them everywhere. Vocabulary is for names and jargon, so common
# function/filler words are off limits unless the user literally said the entry.
COMMON_WORDS = frozenset(
    """
    a an and the this that these those i me my mine myself you your yours we us our
    ours he him his she her hers it its they them their theirs who whom whose which
    what to of in on at by for with from as into onto up down out off over under
    again is am are was were be been being do does did doing have has had having will
    would shall should can could may might must not no nor so than too very just only
    also then there here where when why how all any both each few more most other some
    such own same about above after before between through during without within if
    because while until unless though although and/or or but yet and i'm i'll i've
    i'd you're we're they're he's she's it's that's don't didn't doesn't isn't aren't
    wasn't weren't won't wouldn't can't couldn't should've would've one two three
    yeah yes ok okay um uh like well now got get go went going gonna wanna kind sort
    """.split()
)


def _is_ordinary(window: list[str]) -> bool:
    """True when every word in the window is a plain, common spoken word."""
    return all(_norm(t) in COMMON_WORDS for t in window)


def apply_vocabulary(
    text: str, vocabulary: list[str], threshold: float = DEFAULT_VOCAB_THRESHOLD
) -> str:
    tokens = text.split()
    entries = sorted(
        {v.strip() for v in vocabulary or [] if v and v.strip()},
        key=lambda v: (-len(v.split()), -len(v)),
    )
    if not tokens or not entries:
        return text

    prepared = []
    for entry in entries:
        parts = [_norm(p) for p in entry.split()]
        norm_space = " ".join(p for p in parts if p)
        norm_joined = "".join(parts)
        if norm_joined:
            prepared.append((entry, len(entry.split()), norm_space, norm_joined))

    out: list[str] = []
    i = 0
    while i < len(tokens):
        best = None  # (window_size, entry, lead, trail)
        for entry, k, norm_space, norm_joined in prepared:
            # A phrase said with one word more or fewer still matches
            # ("photo globe" -> "Photoglobe"), so try nearby window sizes.
            for w in dict.fromkeys([k, k + 1, k - 1]):
                if w < 1 or i + w > len(tokens):
                    continue
                window = tokens[i : i + w]
                win_parts = [_norm(t) for t in window]
                win_space = " ".join(p for p in win_parts if p)
                win_joined = "".join(win_parts)
                if not win_joined:
                    continue
                exact = win_joined == norm_joined
                # Short entries need a near-exact match, so a name like "Andi"
                # doesn't swallow "and" (ratio 0.86). Longer entries use the
                # user's threshold.
                floor = 0.95 if len(norm_joined) <= 4 else threshold
                if len(norm_joined) < 3:
                    matched = exact
                elif w == k:
                    matched = (
                        max(
                            SequenceMatcher(None, win_space, norm_space).ratio(),
                            SequenceMatcher(None, win_joined, norm_joined).ratio(),
                        )
                        >= floor
                    )
                else:
                    # An off-size window absorbs or drops a whole word, so it
                    # must be a near-exact join ("photo globe" -> "Photoglobe"),
                    # or short neighbors get eaten ("to kalodner" -> "Kalodner").
                    matched = (
                        SequenceMatcher(None, win_joined, norm_joined).ratio()
                        >= max(floor, 0.95)
                    )
                # Never rewrite a run of ordinary spoken words, even when they
                # happen to concatenate to an entry ("and" + "I" -> "andi").
                # Vocabulary is for names and jargon, not everyday speech.
                if matched and _is_ordinary(window):
                    matched = False
                if matched:
                    lead = re.match(r"^[^\w']*", window[0]).group(0)
                    trail = re.search(r"[^\w']*$", window[-1]).group(0)
                    if " ".join(window) == lead + entry + trail:
                        continue  # already exactly right, nothing to do
                    best = (w, entry, lead, trail)
                    break
            if best:
                break
        if best:
            w, entry, lead, trail = best
            out.append(lead + entry + trail)
            i += w
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out)


def process(
    text: str,
    *,
    replacements: list[dict] | None = None,
    vocabulary: list[str] | None = None,
    vocab_threshold: float = DEFAULT_VOCAB_THRESHOLD,
    trailing_space: bool = True,
) -> str:
    """Full post-processing pipeline: replacements, then vocabulary, then cleanup."""
    text = apply_replacements(text, replacements or [])
    text = apply_vocabulary(text, vocabulary or [], vocab_threshold)
    return clean(text, trailing_space)
