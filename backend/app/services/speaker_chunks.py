"""Chunks, numbered text and window numbers for speaker attribution (Pass 1).

Pure functions; ``speakers_service`` loads the book and stores results.

- ``plan_chunks`` cuts each chapter into parts of about
  ``SPEAKERS_CHUNK_WORDS`` at paragraph boundaries. No overlap, so every
  line is attributed once. Each part carries the last paragraphs before
  it in the same chapter as read-only context.
- ``render_chunk`` writes the text the model sees, with dialogue lines
  numbered ``L1…Ln``.
- ``windows_for_span`` maps a line's word span to the voice-extraction
  windows it falls in, for the derived ``window_speakers`` rows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.services.fragmenter import count_words

if TYPE_CHECKING:
    from uuid import UUID

    from app.services.dialogue_lines import LineCandidate
    from app.services.fragmenter import ChapterInput, ParagraphInput

SPEAKERS_CHUNK_WORDS = 2500
# A chapter's last part shorter than this joins the part before it.
MIN_TAIL_WORDS = 600
CONTEXT_PARAGRAPHS = 3


@dataclass(slots=True)
class Chunk:
    number: int
    chapter_id: UUID
    chapter_index: int
    paragraphs: list[ParagraphInput] = field(default_factory=list)
    lines: list[LineCandidate] = field(default_factory=list)
    context: list[ParagraphInput] = field(default_factory=list)
    word_count: int = 0


def plan_chunks(
    chapters: list[ChapterInput],
    lines: list[LineCandidate],
    *,
    chunk_words: int = SPEAKERS_CHUNK_WORDS,
    min_tail_words: int = MIN_TAIL_WORDS,
    context_paragraphs: int = CONTEXT_PARAGRAPHS,
) -> list[Chunk]:
    """Chunks in book order, numbered from 1. Chunks never cross chapters."""
    line_by_paragraph = {ln.paragraph_id: ln for ln in lines}
    out: list[Chunk] = []
    for chapter_index, chapter in enumerate(chapters):
        parts: list[list[ParagraphInput]] = []
        current: list[ParagraphInput] = []
        words = 0
        for para in chapter.paragraphs:
            current.append(para)
            words += count_words(para.text.strip())
            if words >= chunk_words:
                parts.append(current)
                current, words = [], 0
        if current:
            if parts and words < min_tail_words:
                parts[-1].extend(current)
            else:
                parts.append(current)
        previous: list[ParagraphInput] = []
        for paras in parts:
            chunk = Chunk(
                number=len(out) + 1,
                chapter_id=chapter.id,
                chapter_index=chapter_index,
                paragraphs=paras,
                lines=[line_by_paragraph[p.id] for p in paras if p.id in line_by_paragraph],
                context=previous[-context_paragraphs:] if context_paragraphs else [],
                word_count=sum(count_words(p.text.strip()) for p in paras),
            )
            out.append(chunk)
            previous = paras
    return out


def render_chunk(
    chunk: Chunk,
    *,
    context_labels: dict[UUID, str] | None = None,
) -> tuple[str, str, dict[int, LineCandidate]]:
    """``(chunk_text, context_text, line_by_number)`` for one chunk.

    ``context_labels`` maps a context paragraph to its stored attribution
    (``"Mira → Stein"``); those paragraphs are prefixed with it.
    """
    labels = context_labels or {}
    numbers: dict[int, LineCandidate] = {}
    line_ids = {ln.paragraph_id: ln for ln in chunk.lines}
    body: list[str] = []
    for para in chunk.paragraphs:
        text = para.text.strip()
        line = line_ids.get(para.id)
        if line is None:
            body.append(text)
            continue
        n = len(numbers) + 1
        numbers[n] = line
        body.append(f"L{n}: {text}")
    context = [
        f"[{labels[p.id]}] {p.text.strip()}" if p.id in labels else p.text.strip()
        for p in chunk.context
    ]
    return "\n\n".join(body), "\n\n".join(context), numbers


def windows_for_span(
    start: int,
    length: int,
    *,
    total_windows: int,
    window_words: int = VOICE_EXTRACTION_WINDOW_WORDS,
    overlap_words: int = VOICE_EXTRACTION_OVERLAP_WORDS,
) -> range:
    """1-based voice-extraction windows overlapping words ``[start, start+length)``.

    Same geometry as ``voice_service.make_windows`` and
    ``translation_service.speakers_for_range``.
    """
    if total_windows <= 0:
        return range(0)
    stride = window_words - overlap_words
    end = start + max(1, length)
    first = max(1, math.floor((start - window_words) / stride) + 2)
    last = min(total_windows, math.ceil(end / stride))
    return range(first, last + 1)
