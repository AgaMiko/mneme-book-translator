"""Split a book's chapters into translation fragments.

A fragment is a contiguous run of paragraphs inside one chapter. Rules:

- never cross a chapter boundary;
- aim for ``TARGET_WORDS`` source words; cut once a fragment reaches it;
- after ``MIN_WORDS_BEFORE_SCENE_CUT`` words, cut early at a scene break
  (``***`` paragraph), so a new scene starts a new fragment;
- a tail shorter than ``MIN_TAIL_WORDS`` joins the previous fragment of the
  same chapter.

Word counting uses the same whitespace split as the glossary and speaker
windows (``glossary_service._split_manuscript_words``), and offsets count
only non-empty paragraphs, as ``_load_book_plaintext`` does. That keeps
``start_word_offset`` comparable with speaker window numbers.

Pure functions here; the service persists the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

TARGET_WORDS = 1200
MIN_WORDS_BEFORE_SCENE_CUT = 600
MIN_TAIL_WORDS = 250

_SCENE_BREAK = re.compile(r"^\s*(?:#{1,3}\s*)?\*\s*\*\s*\*\s*")


@dataclass(slots=True)
class ParagraphInput:
    id: UUID
    text: str


@dataclass(slots=True)
class ChapterInput:
    id: UUID
    paragraphs: list[ParagraphInput]


@dataclass(slots=True)
class FragmentPlan:
    chapter_id: UUID
    paragraph_ids: list[UUID] = field(default_factory=list)
    word_count: int = 0
    start_word_offset: int = 0


def count_words(text: str) -> int:
    return len(text.split())


def is_scene_break(text: str) -> bool:
    return bool(_SCENE_BREAK.match(text))


def plan_fragments(
    chapters: list[ChapterInput],
    *,
    target_words: int = TARGET_WORDS,
    min_words_before_scene_cut: int = MIN_WORDS_BEFORE_SCENE_CUT,
    min_tail_words: int = MIN_TAIL_WORDS,
) -> list[FragmentPlan]:
    """Return fragments in book order."""
    out: list[FragmentPlan] = []
    offset = 0
    for chapter in chapters:
        chapter_frags: list[FragmentPlan] = []
        current: FragmentPlan | None = None
        for para in chapter.paragraphs:
            words = count_words(para.text.strip())
            if current is not None and current.paragraph_ids:
                full = current.word_count >= target_words
                scene_cut = (
                    is_scene_break(para.text) and current.word_count >= min_words_before_scene_cut
                )
                if full or scene_cut:
                    chapter_frags.append(current)
                    current = None
            if current is None:
                current = FragmentPlan(chapter_id=chapter.id, start_word_offset=offset)
            current.paragraph_ids.append(para.id)
            current.word_count += words
            offset += words
        if current is not None and current.paragraph_ids:
            if chapter_frags and current.word_count < min_tail_words:
                prev = chapter_frags[-1]
                prev.paragraph_ids.extend(current.paragraph_ids)
                prev.word_count += current.word_count
            else:
                chapter_frags.append(current)
        out.extend(chapter_frags)
    return out
