# ruff: noqa: RUF001, RUF002 - typographic dashes and quotes are what this module finds
"""Find dialogue lines in a book's paragraphs (voice pipeline, step 1).

No LLM. The output is the numbered list of lines that speaker attribution
(Pass 1) assigns to characters; see ``docs/voice-pipeline-redesign.md``.

Unit
----
One line is one paragraph. The whole paragraph is kept, because the
narration inside it ("szepnęła", "wzruszyła ramionami") shows tone.
``speech_text`` holds only the spoken parts, for word counts.

Conventions
-----------
A book marks dialogue in one of two ways, detected per book:

- ``dash`` (Polish, French, Russian…): a speech paragraph starts with a
  dash, and narration inside it is set off by dashes::

      – Rozeszły się. – Hania wzruszyła ramionami. – Po tym…

  Parts alternate speech, narration, speech. A dash between two letters
  (``T–tak``, ``Następny–a``) is a stutter or a range, not a separator.
  A dash inside speech that is not followed by narration is read as a
  separator too; ``speech_text`` is only a word count, so this is
  accepted.
- ``quotes`` (English and others): speech is the text between quote marks.

In a ``dash`` book, quote marks mostly wrap titles, read-out letters or
scare quotes. Only paragraphs that *start* with a quote mark become
candidates there (letters, remembered speech, thoughts); attribution
decides their ``kind``. Quotes in the middle of narration are skipped.

Word offsets count words the same way as ``fragmenter`` so a line can be
placed in the voice-extraction windows that translation still reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.services.fragmenter import count_words

if TYPE_CHECKING:
    from uuid import UUID

    from app.services.fragmenter import ChapterInput

Convention = Literal["dash", "quotes"]
Marker = Literal["dash", "quote"]

# A dash-convention book needs at least this share of dash-start paragraphs
# among all paragraphs that look like dialogue either way.
_DASH_SHARE = 0.5

_DASHES = "–—"
# Paragraph opens with a dash (a hyphen counts only when a space follows).
_DASH_START = re.compile(rf"^\s*(?:[{_DASHES}]|-(?=\s))")
# A dash not between two letters or digits, or a hyphen typed with spaces
# on both sides in place of a dash.
_DASH_SEPARATOR = re.compile(rf"(?<!\w)[{_DASHES}]|[{_DASHES}](?!\w)|(?<=\s)-(?=\s)")

_OPEN_QUOTES = '„"“«»'
_QUOTE_START = re.compile(rf"^\s*[{_OPEN_QUOTES}]")
# Text between a pair of quote marks, any of the common pairs.
_QUOTED = re.compile(r"„([^”\"]*)[”\"]|“([^”]*)”|\"([^\"]*)\"|«([^»]*)»|»([^«]*)«")


@dataclass(frozen=True, slots=True)
class LineCandidate:
    """One paragraph that may hold speech."""

    paragraph_id: UUID
    chapter_id: UUID
    text: str
    speech_text: str
    marker: Marker
    word_offset: int


def starts_with_dash(text: str) -> bool:
    return bool(_DASH_START.match(text))


def detect_convention(chapters: list[ChapterInput]) -> Convention:
    """``dash`` when dash-start paragraphs dominate, else ``quotes``."""
    dash = quote = 0
    for chapter in chapters:
        for para in chapter.paragraphs:
            if starts_with_dash(para.text):
                dash += 1
            elif _QUOTED.search(para.text):
                quote += 1
    if dash == 0:
        return "quotes"
    return "dash" if dash / (dash + quote) >= _DASH_SHARE else "quotes"


def split_dash_paragraph(text: str) -> tuple[list[str], list[str]]:
    """Split a dash paragraph into ``(speech_parts, narration_parts)``."""
    body = _DASH_START.sub("", text, count=1)
    parts = [p.strip() for p in _DASH_SEPARATOR.split(body)]
    speech = [p for i, p in enumerate(parts) if i % 2 == 0 and p]
    narration = [p for i, p in enumerate(parts) if i % 2 == 1 and p]
    return speech, narration


def quoted_spans(text: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None).strip() for m in _QUOTED.finditer(text)]


def _line_for(text: str, convention: Convention) -> tuple[Marker, str] | None:
    if convention == "dash":
        if starts_with_dash(text):
            speech, _ = split_dash_paragraph(text)
            return "dash", " ".join(speech)
        if _QUOTE_START.match(text):
            return "quote", " ".join(quoted_spans(text)) or text.strip()
        return None
    spans = quoted_spans(text)
    if spans:
        return "quote", " ".join(spans)
    return None


def find_dialogue_lines(
    chapters: list[ChapterInput],
    *,
    convention: Convention | None = None,
) -> list[LineCandidate]:
    """Dialogue candidates in book order.

    ``chapters`` must be in book order with non-empty paragraphs only, as
    the fragmenter receives them.
    """
    conv = convention or detect_convention(chapters)
    out: list[LineCandidate] = []
    offset = 0
    for chapter in chapters:
        for para in chapter.paragraphs:
            text = para.text.strip()
            found = _line_for(text, conv)
            if found is not None:
                marker, speech_text = found
                out.append(
                    LineCandidate(
                        paragraph_id=para.id,
                        chapter_id=chapter.id,
                        text=text,
                        speech_text=speech_text,
                        marker=marker,
                        word_offset=offset,
                    )
                )
            offset += count_words(text)
    return out
