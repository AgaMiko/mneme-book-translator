"""Smoke test for the docx parser."""

from pathlib import Path

import pytest
from docx import Document

from app.services.manuscript_parser import parse_docx


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    doc = Document()
    doc.add_heading("Mneme", level=0)

    doc.add_heading("Rozdział 1", level=1)
    doc.add_paragraph("To był pierwszy akapit.")
    doc.add_paragraph("Drugi akapit był dłuższy i miał kilka słów.")

    doc.add_heading("Rozdział 2", level=1)
    doc.add_paragraph("Akapit z drugiego rozdziału.")

    path = tmp_path / "test.docx"
    doc.save(str(path))
    return path


def test_parse_detects_two_chapters(sample_docx: Path) -> None:
    parsed = parse_docx(sample_docx, fallback_title="Untitled")
    assert len(parsed.chapters) == 2
    assert parsed.chapters[0].title == "Rozdział 1"
    assert parsed.chapters[1].title == "Rozdział 2"


def test_parse_collects_paragraphs(sample_docx: Path) -> None:
    parsed = parse_docx(sample_docx, fallback_title="Untitled")
    assert len(parsed.chapters[0].paragraphs) == 2
    assert len(parsed.chapters[1].paragraphs) == 1


def test_parse_word_count(sample_docx: Path) -> None:
    parsed = parse_docx(sample_docx, fallback_title="Untitled")
    assert parsed.word_count > 0


def test_parse_splits_star_scene_break_inline(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("Pierwszy blok *** Drugi blok")
    path = tmp_path / "stars.docx"
    doc.save(str(path))

    parsed = parse_docx(path, fallback_title="Stars")
    assert len(parsed.chapters[0].paragraphs) == 3
    assert parsed.chapters[0].paragraphs[0].text == "Pierwszy blok"
    assert parsed.chapters[0].paragraphs[1].text == "***"
    assert parsed.chapters[0].paragraphs[2].text == "Drugi blok"


def test_parse_splits_star_scene_break_on_own_line(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("A\n\n***\n\nB")
    path = tmp_path / "stars_nl.docx"
    doc.save(str(path))

    parsed = parse_docx(path, fallback_title="Stars")
    assert len(parsed.chapters[0].paragraphs) == 3
    assert parsed.chapters[0].paragraphs[0].text == "A"
    assert parsed.chapters[0].paragraphs[1].text == "***"
    assert parsed.chapters[0].paragraphs[2].text == "B"


def test_parse_does_not_split_four_stars(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("x **** y")
    path = tmp_path / "four.docx"
    doc.save(str(path))

    parsed = parse_docx(path, fallback_title="Four")
    assert len(parsed.chapters[0].paragraphs) == 1
    assert parsed.chapters[0].paragraphs[0].text == "x **** y"


def test_parse_no_chapters_fallback(tmp_path: Path) -> None:
    """A doc without any headings should yield a single untitled chapter."""
    doc = Document()
    doc.add_paragraph("Just one paragraph, no chapters.")
    path = tmp_path / "flat.docx"
    doc.save(str(path))

    parsed = parse_docx(path, fallback_title="Flat")
    assert len(parsed.chapters) == 1
    assert parsed.chapters[0].title is None
    assert len(parsed.chapters[0].paragraphs) == 1
