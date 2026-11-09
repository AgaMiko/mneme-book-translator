"""Whose point of view each scene's narration follows, read from the text.

No model call: the POV comes from markers the author wrote.

- A chapter heading that starts with a name ("Mira / Rozdział 1") sets
  the POV of the chapter's first scene.
- A scene break (``***``) starts a new scene. When the break names a
  character, on the lines after the stars or as the next paragraph on
  its own, that character is the POV.
- A scene after a break with no name inherits the chapter's POV, but is
  marked ``assumed``: books often switch POV at an unnamed break.
- A scene with nothing to go on is ``unknown``.

Names are matched to glossary characters so the manuscript can use the
same colour for a character's narration and their dialogue lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.constants.languages import WORD_CHARS
from app.models.book import Book, Chapter
from app.models.glossary import INACTIVE_STATUSES
from app.schemas.speakers import NarrationPovResponse, NarrationSceneOut
from app.services.glossary_service import load_working_glossary_for_latest_run
from app.services.manuscript_parser import chapter_number_pattern

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

CHAPTER_LINE = chapter_number_pattern()
SCENE_BREAK = re.compile(r"^\s*(?:#{1,3}\s*)?\*\s*\*\s*\*\s*$")

# A paragraph that is only a name: up to three words, no sentence punctuation.
_BARE_NAME = re.compile(rf"^[^\W\d_][{WORD_CHARS}'\u2019\- ]{{0,40}}$")

PovSource = Literal["heading", "scene_break", "assumed", "unknown"]


@dataclass(slots=True)
class PovParagraph:
    id: UUID
    text: str


@dataclass(slots=True)
class PovChapter:
    id: UUID
    title: str | None
    paragraphs: list[PovParagraph]


@dataclass(slots=True)
class PovScene:
    chapter_id: UUID
    name: str | None
    source: PovSource
    paragraph_ids: list[UUID] = field(default_factory=list)


def strip_marks(text: str) -> str:
    return text.strip().strip("*_").strip()


def heading_pov(title: str | None) -> str | None:
    """The name on the lines above "Rozdział N" in a chapter heading, if any."""
    lines = [strip_marks(ln) for ln in (title or "").split("\n") if ln.strip()]
    idx = next((i for i, ln in enumerate(lines) if CHAPTER_LINE.match(ln)), None)
    if not idx:
        return None
    return " ".join(lines[:idx])


def _bare_name(text: str) -> str | None:
    t = strip_marks(text)
    if _BARE_NAME.match(t) and len(t.split()) <= 3:
        return t
    return None


def find_pov_scenes(
    chapters: list[PovChapter], *, is_character: Callable[[str], bool]
) -> list[PovScene]:
    """Split each chapter into scenes and give each its POV and how it was found.

    ``is_character`` decides whether a paragraph that is only a name after
    a break is a POV marker (it must be a glossary character), so a one-word
    line like "Cisza." is not taken for one.
    """
    scenes: list[PovScene] = []
    for ch in chapters:
        chapter_pov = heading_pov(ch.title)
        scene = PovScene(ch.id, chapter_pov, "heading" if chapter_pov else "unknown")
        scenes.append(scene)
        expect_name = False
        for p in ch.paragraphs:
            lines = [ln.strip() for ln in p.text.split("\n")]
            if lines and SCENE_BREAK.match(lines[0]):
                named = " ".join(ln for ln in lines[1:] if ln)
                if named:
                    scene = PovScene(ch.id, strip_marks(named), "scene_break")
                else:
                    scene = PovScene(ch.id, chapter_pov, "assumed" if chapter_pov else "unknown")
                    expect_name = True
                scenes.append(scene)
                scene.paragraph_ids.append(p.id)
                continue
            if expect_name:
                expect_name = False
                name = _bare_name(p.text)
                if name and is_character(name):
                    scene.name, scene.source = name, "scene_break"
            scene.paragraph_ids.append(p.id)
    return [s for s in scenes if s.paragraph_ids]


async def build_narration_pov(session: AsyncSession, *, book_id: UUID) -> NarrationPovResponse:
    book = (
        await session.execute(
            select(Book)
            .where(Book.id == book_id)
            .options(selectinload(Book.chapters).selectinload(Chapter.paragraphs))
        )
    ).scalar_one()
    _run, entries = await load_working_glossary_for_latest_run(session, book_id=book_id)
    character_ids: dict[str, UUID] = {}
    for e in entries:
        if e.term_type != "character_name" or e.status in INACTIVE_STATUSES:
            continue
        for form in [e.canonical_form, *(e.variants or [])]:
            character_ids.setdefault(form.strip().casefold(), e.id)

    chapters = [
        PovChapter(
            id=c.id,
            title=c.title,
            paragraphs=[PovParagraph(id=p.id, text=p.text or "") for p in c.paragraphs],
        )
        for c in book.chapters
    ]
    scenes = find_pov_scenes(chapters, is_character=lambda n: n.casefold() in character_ids)
    return NarrationPovResponse(
        scenes=[
            NarrationSceneOut(
                chapter_id=s.chapter_id,
                pov_name=s.name,
                pov_id=character_ids.get(s.name.casefold()) if s.name else None,
                source=s.source,
                paragraph_ids=s.paragraph_ids,
            )
            for s in scenes
        ]
    )
