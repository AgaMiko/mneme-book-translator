"""Letter and line checks for special passages (pure functions).

A special passage follows a rule that normal translation breaks: the
first letters of its sentences spell a message, or it is verse with a
fixed number of lines. These functions read letters and lines, which a
language model does badly, so the service can:

- show the model the letter strings of a passage when it works out the
  rule (``letter_strings``);
- check a translation against the rule without a model
  (``hidden_message_problems``, ``line_count_problems``).

Nothing here depends on the source language: a letter is whatever
``str.isalpha`` accepts.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

# Which units carry the letters of a hidden message.
Unit = Literal["sentence", "line", "paragraph", "word", "marked_word"]
UNITS: tuple[Unit, ...] = get_args(Unit)

# Word-initial strings are only useful for short passages.
_WORD_STRING_MAX_WORDS = 80

# The end of a sentence: . ! ? … with any closing quotes or brackets, then a space.
_SENTENCE_END = re.compile("([.!?…][\"'\u201d\u2019»)\\]]*)\\s+")
# *italic*, **bold** or _italic_ spans, as the parser writes them.
_MARKED = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}|(?<!\w)_([^_\n]+?)_(?!\w)")


def split_sentences(text: str) -> list[str]:
    """Sentences of one line. A piece that starts in lower case continues the
    sentence before it (a speech tag after a quoted question)."""
    out: list[str] = []
    for piece in _SENTENCE_END.sub("\\1\n", text).split("\n"):
        piece = piece.strip()
        if not piece:
            continue
        if out and piece[0].islower():
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def split_lines(texts: list[str]) -> list[str]:
    """Lines of a passage: every paragraph, split at its line breaks."""
    return [ln.strip() for t in texts for ln in t.splitlines() if ln.strip()]


def _first_letter(unit: str) -> str:
    return next((ch.upper() for ch in unit if ch.isalpha()), "")


def units_of(texts: list[str], unit: Unit) -> list[str]:
    """The passage cut into ``unit`` pieces, in reading order."""
    if unit == "paragraph":
        return [t.strip() for t in texts if t.strip()]
    if unit == "line":
        return split_lines(texts)
    if unit == "sentence":
        return [s for ln in split_lines(texts) for s in split_sentences(ln)]
    if unit == "word":
        return [w for t in texts for w in t.split()]
    return [m.group(1) or m.group(2) for t in texts for m in _MARKED.finditer(t)]


def extract_message(texts: list[str], unit: Unit) -> str:
    """First letters of the passage's units, as one upper-case string."""
    return "".join(_first_letter(u) for u in units_of(texts, unit))


def normalise_message(message: str) -> str:
    """Letters only, upper case: ``"I am watched"`` → ``"IAMWATCHED"``."""
    return "".join(ch.upper() for ch in message if ch.isalpha())


def letter_strings(texts: list[str]) -> dict[Unit, str]:
    """First-letter strings per unit, leaving out the ones too short to mean anything."""
    out: dict[Unit, str] = {}
    words = sum(len(t.split()) for t in texts)
    for unit in UNITS:
        if unit == "word" and words > _WORD_STRING_MAX_WORDS:
            continue
        s = extract_message(texts, unit)
        if len(s) >= 3:
            out[unit] = s
    # Lines and paragraphs often give the same string; keep one.
    if out.get("line") and out.get("line") == out.get("paragraph"):
        del out["paragraph"]
    return out


def render_letter_strings(texts: list[str]) -> str:
    labels: dict[Unit, str] = {
        "sentence": "First letters of sentences",
        "line": "First letters of lines",
        "paragraph": "First letters of paragraphs",
        "word": "First letters of words",
        "marked_word": "First letters of italic or bold words",
    }
    rows = [f"- {labels[u]}: {s}" for u, s in letter_strings(texts).items()]
    return "\n".join(rows) or "(the passage is too short for letter strings)"


# Letters allowed before and after a message when the source gives no measure.
_DEFAULT_SLACK = 2


def message_slack(
    source_texts: list[str], unit: Unit, source_message: str | None
) -> tuple[int, int]:
    """How many units may stand before and after the message (salutation, sign-off).

    Measured on the source, plus one on each side: a translation may split
    a sentence the source keeps whole.
    """
    got = extract_message(source_texts, unit)
    want = normalise_message(source_message or "")
    start = got.find(want) if want else -1
    if start < 0:
        return _DEFAULT_SLACK, _DEFAULT_SLACK
    return start + 1, len(got) - start - len(want) + 1


def spelled_message(
    texts: list[str],
    unit: Unit,
    messages: list[str],
    slack: tuple[int, int] = (_DEFAULT_SLACK, _DEFAULT_SLACK),
) -> str | None:
    """The first of ``messages`` that the passage spells, or ``None``.

    The message has to appear in order, one letter per unit, with no
    letters in between. At most ``slack`` units may stand before and after
    it (a letter's salutation and sign-off), so a short message cannot
    match by chance in the middle of a long text.
    """
    got = extract_message(texts, unit)
    before, after = slack
    for message in messages:
        want = normalise_message(message)
        start = got.find(want) if want else -1
        while start >= 0:
            if start <= before and len(got) - start - len(want) <= after:
                return message
            start = got.find(want, start + 1)
    return None


# A quoted span: "…", “…”, „…” or «…».
_QUOTED = re.compile('["“„«]([^"“”„«»\n]{3,80})["”»]')


def stated_messages(texts: list[str]) -> list[str]:
    """Quoted spans written in capitals, the way a decoding scene states a message."""
    out: list[str] = []
    for t in texts:
        for m in _QUOTED.finditer(t):
            span = m.group(1).strip()
            if len(normalise_message(span)) >= 5 and span == span.upper() and span not in out:
                out.append(span)
    return out


def hidden_message_problems(
    texts: list[str],
    unit: str,
    target_message: str,
    also: list[str] | None = None,
    slack: tuple[int, int] = (_DEFAULT_SLACK, _DEFAULT_SLACK),
) -> list[str]:
    """Why ``texts`` spells neither ``target_message`` nor any of ``also``; empty when it does.

    Returns an empty list too when the rule is not one the code can read
    (an unknown unit or no target message); the caller then asks a model.
    """
    want = normalise_message(target_message)
    if unit not in UNITS or not want:
        return []
    if spelled_message(texts, unit, [target_message, *(also or [])], slack) is not None:
        return []
    got = extract_message(texts, unit)
    label = unit.replace("_", " ")
    return [
        f"The first letters of the {label}s spell {got or '(nothing)'}. The message {want} "
        f"({len(want)} letters) must appear in them in order, one letter per {label}, with "
        "nothing in between. Only a salutation or sign-off may add letters: at most "
        f"{slack[0]} before the message and {slack[1]} after it."
    ]


def line_count_problems(source_texts: list[str], target_texts: list[str]) -> list[str]:
    """Verse keeps its number of lines."""
    src, tgt = len(split_lines(source_texts)), len(split_lines(target_texts))
    if src == tgt:
        return []
    return [f"The source has {src} lines and the translation has {tgt}."]
