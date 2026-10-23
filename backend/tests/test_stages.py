"""Tests for when the glossary and voices stages count as finished."""

import pytest

from app.models.book import Book
from app.services.stages import (
    StageConflictError,
    glossary_ready,
    set_marked_finished,
    voices_ready,
)


def _book(glossary: str = "idle", voices: str = "idle", speakers: str = "idle") -> Book:
    return Book(
        title="Book",
        original_filename="book.docx",
        storage_path="book.docx",
        glossary_extraction_status=glossary,
        voice_extraction_status=voices,
        speakers_extraction_status=speakers,
    )


def test_stopped_glossary_counts_but_running_or_unstarted_does_not() -> None:
    assert glossary_ready(_book("completed"))
    assert glossary_ready(_book("cancelled"))
    assert not glossary_ready(_book("idle"))
    assert not glossary_ready(_book("running"))


def test_marking_a_stage_finished_and_unmarking_it() -> None:
    book = _book(voices="cancelled")
    assert not voices_ready(book)
    set_marked_finished(book, "voices", True)
    assert voices_ready(book)
    assert book.stages_marked_finished == ["voices"]
    set_marked_finished(book, "voices", True)
    assert book.stages_marked_finished == ["voices"]
    set_marked_finished(book, "voices", False)
    assert not voices_ready(book)
    assert book.stages_marked_finished == []


def test_a_running_stage_cannot_be_marked_and_never_counts() -> None:
    book = _book(speakers="running")
    with pytest.raises(StageConflictError):
        set_marked_finished(book, "voices", True)
    book.stages_marked_finished = ["glossary"]
    book.glossary_extraction_status = "running"
    assert not glossary_ready(book)
