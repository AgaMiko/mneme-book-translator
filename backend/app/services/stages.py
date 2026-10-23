"""Whether a book's glossary and voices stages count as finished.

A stage is finished when its extraction completed, or when the author
marked it finished by hand (``Book.stages_marked_finished``). A stopped or
failed glossary run keeps its terms, so it also counts. A stage whose
extraction is running never counts.

Frontend mirror: ``glossaryUsable`` and ``voicesFinished`` in
``frontend/src/components/book/tabs.ts``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.constants.glossary_extraction import GLOSSARY_USABLE_STATUSES

if TYPE_CHECKING:
    from app.models.book import Book

Stage = Literal["glossary", "voices"]
STAGES: tuple[Stage, ...] = ("glossary", "voices")


class StageConflictError(RuntimeError):
    """The stage's extraction is running, so it cannot be marked or unmarked."""


def set_marked_finished(book: Book, stage: Stage, finished: bool) -> None:
    """Mark or unmark ``stage`` as finished by hand. The caller commits."""
    if stage_running(book, stage):
        raise StageConflictError("Wait for the running extraction to finish or stop it first.")
    marks = [s for s in book.stages_marked_finished or [] if s != stage]
    if finished:
        marks.append(stage)
    # A new list, so SQLAlchemy sees the change to the ARRAY column.
    book.stages_marked_finished = sorted(marks)


def stage_running(book: Book, stage: Stage) -> bool:
    if stage == "glossary":
        return book.glossary_extraction_status == "running"
    return "running" in (book.voice_extraction_status, book.speakers_extraction_status)


def glossary_ready(book: Book) -> bool:
    if stage_running(book, "glossary"):
        return False
    marked = "glossary" in (book.stages_marked_finished or [])
    return marked or book.glossary_extraction_status in GLOSSARY_USABLE_STATUSES


def voices_ready(book: Book) -> bool:
    if stage_running(book, "voices"):
        return False
    marked = "voices" in (book.stages_marked_finished or [])
    return marked or book.voice_extraction_status == "completed"
