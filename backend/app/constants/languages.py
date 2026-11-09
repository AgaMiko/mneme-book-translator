"""Facts about each source language that the code needs.

The prompts carry no source-language examples: they are written once, in
English, and name the source language only through ``{source_language}``.
What stays per language are facts the checks and the parser need:

- the English name, for the prompts;
- the letters that must not be left in the English translation (the
  ``source_letters`` QA check);
- chapter-heading words, in ``manuscript_parser._CHAPTER_MARKERS_BY_LANGUAGE``.

Status: Polish is tested on a full manuscript. German (#4) has not been run
on a German manuscript yet. Kannada (#5) has its script only; its chapter
markers and the suffix lengths in ``term_matching`` need a native reader.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceLanguage:
    code: str
    name: str
    # Regex character-class body (without brackets). Empty: no check.
    source_letters: str = ""


_LANGUAGES: dict[str, SourceLanguage] = {
    lang.code: lang
    for lang in (
        SourceLanguage("pl", "Polish", "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"),
        SourceLanguage("de", "German", "äöüßÄÖÜ"),
        SourceLanguage("kn", "Kannada", "ಀ-೿"),
    )
}

SUPPORTED_SOURCE_LANGUAGES: tuple[str, ...] = tuple(_LANGUAGES)


def _lookup(language: str | None) -> SourceLanguage | None:
    key = (language or "").strip().lower()
    return _LANGUAGES.get(key) or next(
        (lang for lang in _LANGUAGES.values() if lang.name.lower() == key), None
    )


def language_name(language: str | None) -> str:
    """English name for a code or name: "pl" → "Polish", "en" → "English".

    Unknown values are returned as given, so a prompt still names them.
    """
    if (language or "").strip().lower() == "en":
        return "English"
    lang = _lookup(language)
    if lang is not None:
        return lang.name
    return (language or "").strip() or "the source language"


def resolve_source_language(stored: str, detected: str | None) -> str:
    """The language a book is written in, as a code when it is a known one.

    ``stored`` is the upload's ``source_language``, which defaults to "pl"
    because the upload screen has no language picker. ``detected`` is the
    ``manuscript_language`` metadata extraction read from the text ("German").
    When the two name different languages the detected one wins.
    """
    if not detected or not detected.strip():
        return stored
    if language_name(detected).lower() == language_name(stored).lower():
        return stored
    found = _lookup(detected)
    return found.code if found is not None else detected.strip()


def source_letters(language: str | None) -> str:
    """Letters of this source language that must not appear in the English."""
    lang = _lookup(language)
    return lang.source_letters if lang is not None else ""


def _mark_ranges() -> str:
    """Regex class body of every combining mark (Mn, Mc, Me) in the Basic Multilingual Plane.

    The BMP holds the scripts of living languages (Kannada, Devanagari,
    Arabic, Hebrew…). Scanning only its 65,536 code points instead of all
    1.1 million keeps the import cheap (a few ms).
    """
    ranges: list[tuple[int, int]] = []
    for cp in range(0x10000):
        if unicodedata.category(chr(cp)) in ("Mn", "Mc", "Me"):
            if ranges and ranges[-1][1] == cp - 1:
                ranges[-1] = (ranges[-1][0], cp)
            else:
                ranges.append((cp, cp))
    return "".join(
        re.escape(chr(a)) if a == b else f"{re.escape(chr(a))}-{re.escape(chr(b))}"
        for a, b in ranges
    )


# ``\w`` does not match combining marks, so it splits words in scripts that
# write vowels as marks: Kannada ರಾಮನಿಗೆ would become ರ, ಮನ, ಗ. Use these
# instead of a bare ``\w`` wherever a source-language word is matched.
WORD_CHARS = r"\w" + _mark_ranges()
WORD = re.compile(f"[{WORD_CHARS}]+")
