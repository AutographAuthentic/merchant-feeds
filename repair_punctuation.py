"""Punctuation repair for careerjerseys.com product descriptions.

Second pass over the catalogue, run from backfill_descriptions.py. The
description backfill only rewrote thin products. Everything it skipped kept
whatever punctuation it already had, and a lot of that copy carries em dashes,
which are not allowed in our copy, plus a few en dashes used as em dashes and
some collapsed double spaces.

repair() is pure and text-only. It changes punctuation and nothing else: no
words are added or removed except turning a numeric range into "to".
"""

import re

EM = "—"
EN = "–"


def repair(h: str) -> str:
    if not h:
        return h
    out = h

    # An em dash hard against a tag boundary has nothing to join, so drop it
    # rather than leaving a comma stranded at the start or end of a paragraph.
    out = re.sub(r"(<(?:p|li|div|h[1-6])[^>]*>)\s*" + EM + r"\s*", r"\1", out)
    out = re.sub(r"\s*" + EM + r"\s*(</(?:p|li|div|h[1-6])>)", r"\1", out)

    # Em dash inside a sentence becomes a comma. This is the rule that matters:
    # em dashes are not allowed in our copy anywhere.
    out = re.sub(r"\s*" + EM + r"\s*", ", ", out)

    # "1-5 business days" written with an en dash. The rest of the catalogue now
    # says "1 to 5 business days", so match it.
    out = re.sub(
        r"(\d)\s*" + EN + r"\s*(\d)(?=\s*(?:business\s+days|days|weeks|hours|inches))",
        r"\1 to \2",
        out,
    )

    # A spaced en dash used as an em dash becomes a comma. A year in front of it
    # means it is a date range (born - died) and is left alone.
    out = re.sub(r"(?<!\d{4}) " + EN + r" ", ", ", out)

    # Markdown that was pasted into an HTML field and renders as literal stars.
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out, flags=re.S)

    # Tidy up after the substitutions above.
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r",\s*\.", ".", out)
    out = re.sub(r"[ \t]{2,}", " ", out)

    return out


def text(h: str) -> str:
    return re.sub(r"<[^>]+>", " ", h or "")


def changed(h: str):
    """Return the repaired html, or None if there is nothing to repair."""
    new = repair(h)
    return None if new == h else new


def safe(before: str, after: str) -> bool:
    """A repair may only alter punctuation and spacing.

    Strip everything the rules are allowed to touch from both sides. What is
    left has to be identical, or the repair did something it should not have.
    """
    def skeleton(s):
        s = re.sub(r"<strong>|</strong>", "", s)
        s = re.sub(r"\bto\b", "", s)
        s = re.sub(r"[\s,*" + EM + EN + r"]+", "", s)
        return s
    return skeleton(before) == skeleton(after)
