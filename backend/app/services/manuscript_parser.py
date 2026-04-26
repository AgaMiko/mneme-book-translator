"""Parse a `.docx` manuscript into a structured ParsedManuscript.

Heuristics, in order of preference:

1. Word "Heading 1" style markers split chapters. This is what
   well-formatted manuscripts use.
2. Fallback: lines matching common Polish chapter markers
   (`Rozdział 1`, `Rozdział I`, `Prolog`, `Epilog`, plus their
   English equivalents for translated drafts).
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
from typing import TYPE_CHECKING

from docx import Document

if TYPE_CHECKING:
    from pathlib import Path

# Matches: "Rozdział 1", "Rozdział I", "Chapter 1", "Prolog", "Epilog",
# optionally followed by a title on the same line.
_CHAPTER_MARKER = re.compile(
    r"""^\s*
    (
        rozdział\s+[\divxlcdm]+      # Rozdział 1 / Rozdział IV
      | chapter\s+[\divxlcdm]+        # Chapter 1
      | prolog (?:\s+.*)?$            # Prolog [optional title]
      | epilog (?:\s+.*)?$            # Epilog
      | prologue (?:\s+.*)?$
      | epilogue (?:\s+.*)?$
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

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
        return sum(
            len(p.text.split())
            for c in self.chapters
            for p in c.paragraphs
        )

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


def _looks_like_chapter_heading(text: str, style_name: str | None) -> bool:
    if style_name and style_name.lower().startswith("heading 1"):
        return True
    return bool(_CHAPTER_MARKER.match(text.strip()))


def _looks_like_document_title(style_name: str | None) -> bool:
    return bool(style_name and style_name.lower() == "title")


def parse_docx(path: Path, fallback_title: str) -> ParsedManuscript:
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

        if _looks_like_chapter_heading(text, style_name):
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
