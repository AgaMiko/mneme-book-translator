"""Parse a `.docx` manuscript into a structured ParsedManuscript.

Heuristics, in order of preference:

1. Word "Heading 1" style markers split chapters. This is what
   well-formatted manuscripts use.
2. Fallback: lines matching chapter markers for the manuscript's
   ``source_language`` (see ``_CHAPTER_MARKERS_BY_LANGUAGE``), plus
   English markers, which are always included since translated
   drafts often mix in English chapter words regardless of source
   language.
3. Final fallback: a single chapter with all paragraphs.

The parser is intentionally conservative — it never rewrites text,
only segments it. Anything ambiguous becomes a normal paragraph
under the previous chapter, which is reversible at the DB layer.

4. Within a single Word paragraph, ``***`` (three asterisks, not part of
   a longer run of stars) acts as a scene break: the paragraph is split
   into multiple stored paragraphs, and the marker itself is kept as its
   own paragraph so it survives in the reader and in downstream plaintext
   (glossary windows, etc.). Whitespace around the marker is discarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING

from docx import Document

if TYPE_CHECKING:
    from pathlib import Path

# Chapter/prologue/epilogue keywords by source_language. English is always
# merged in on top of these (see _chapter_marker_pattern) since translated
# drafts often keep English chapter words regardless of source language.
# Numeral suffix covers "Rozdział 1" / "Rozdział IV" style headings.
_NUMBER = r"\s+[\divxlcdm]+"
_CHAPTER_MARKERS_BY_LANGUAGE: dict[str, list[str]] = {
    "pl": [
        r"rozdzia[łl]" + _NUMBER,
        r"prolog(?:\s+.*)?$",
        r"epilog(?:\s+.*)?$",
    ],
    "de": [
        r"kapitel" + _NUMBER,
        r"prolog(?:\s+.*)?$",
        r"epilog(?:\s+.*)?$",
    ],
}

_EN_CHAPTER_MARKERS = [
    r"chapter" + _NUMBER,
    r"prologue(?:\s+.*)?$",
    r"epilogue(?:\s+.*)?$",
]


@cache
def _chapter_marker_pattern(source_language: str) -> re.Pattern[str]:
    """Compile the chapter-marker regex for a source language.

    Unknown languages still get the English markers, so behavior degrades
    to "recognize English headings only" rather than "recognize nothing."
    """
    keywords = _CHAPTER_MARKERS_BY_LANGUAGE.get(source_language.lower(), []) + _EN_CHAPTER_MARKERS
    return re.compile(rf"^\s*({'|'.join(keywords)})", re.IGNORECASE)


@cache
def chapter_number_pattern() -> re.Pattern[str]:
    """A numbered chapter line in any language listed above ("Rozdział 4", "Kapitel IV").

    Prologue and epilogue lines are not included. Used to find the chapter
    line inside a heading that also holds a point-of-view name or an epigraph.
    """
    numbered = [
        marker
        for markers in (*_CHAPTER_MARKERS_BY_LANGUAGE.values(), _EN_CHAPTER_MARKERS)
        for marker in markers
        if marker.endswith(_NUMBER)
    ]
    return re.compile(rf"^({'|'.join(numbered)})\b", re.IGNORECASE)


# Scene / section break inside one docx paragraph (exactly three stars).
_STAR_SCENE_BREAK = re.compile(r"\s*(?<!\*)\*{3}(?!\*)\s*")


def _split_scene_break_paragraphs(text: str) -> list[str]:
    """Turn one docx paragraph into logical paragraphs at ``***`` breaks.

    Each delimiter becomes its own stored segment ``\"***\"`` so scene breaks
    stay visible between text blocks.
    """
    parts = _STAR_SCENE_BREAK.split(text)
    out: list[str] = []
    for i, part in enumerate(parts):
        s = part.strip()
        if s:
            out.append(s)
        if i < len(parts) - 1:
            out.append("***")
    return out


@dataclass(slots=True)
class ParsedParagraph:
    text: str
    style: str | None = None


@dataclass(slots=True)
class ParsedChapter:
    title: str | None
    paragraphs: list[ParsedParagraph] = field(default_factory=list)


@dataclass(slots=True)
class ParsedManuscript:
    title: str
    chapters: list[ParsedChapter] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(len(p.text.split()) for c in self.chapters for p in c.paragraphs)

    @property
    def paragraph_count(self) -> int:
        return sum(len(c.paragraphs) for c in self.chapters)

    def text_sample(self, max_chars: int) -> str:
        """Return the first source-text characters across parsed paragraphs."""
        parts: list[str] = []
        remaining = max_chars
        for chapter in self.chapters:
            for paragraph in chapter.paragraphs:
                if remaining <= 0:
                    return "\n\n".join(parts)
                text = paragraph.text[:remaining]
                parts.append(text)
                remaining -= len(text)
        return "\n\n".join(parts)


def _looks_like_chapter_heading(text: str, style_name: str | None, source_language: str) -> bool:
    if style_name and style_name.lower().startswith("heading 1"):
        return True
    return bool(_chapter_marker_pattern(source_language).match(text.strip()))


def _looks_like_document_title(style_name: str | None) -> bool:
    return bool(style_name and style_name.lower() == "title")


def parse_docx(path: Path, fallback_title: str, source_language: str = "pl") -> ParsedManuscript:
    """Parse a `.docx` file from disk into a ParsedManuscript."""
    document = Document(str(path))

    title = (document.core_properties.title or fallback_title).strip() or fallback_title
    manuscript = ParsedManuscript(title=title)

    current = ParsedChapter(title=None)
    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            # Skip blank paragraphs — they don't survive translation
            # alignment anyway.
            continue

        style_name = para.style.name if para.style else None

        if (
            _looks_like_document_title(style_name)
            and not manuscript.chapters
            and not current.paragraphs
            and current.title is None
        ):
            manuscript.title = text
            continue

        if _looks_like_chapter_heading(text, style_name, source_language):
            # Close out the previous chapter if it had content; otherwise
            # we're at the very top of the doc.
            if current.paragraphs or current.title is not None:
                manuscript.chapters.append(current)
            current = ParsedChapter(title=text)
            continue

        for segment in _split_scene_break_paragraphs(text):
            current.paragraphs.append(
                ParsedParagraph(text=segment, style=style_name),
            )

    # Flush the trailing chapter
    if current.paragraphs or current.title is not None:
        manuscript.chapters.append(current)

    # Edge case: doc had zero detected chapters (no headings, no markers).
    # Wrap everything in a single untitled chapter.
    if not manuscript.chapters:
        manuscript.chapters.append(ParsedChapter(title=None))

    return manuscript
