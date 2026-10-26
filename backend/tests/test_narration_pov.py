"""Unit tests for reading the narration POV from headings and scene breaks."""

from uuid import uuid4

from app.services.narration_pov import PovChapter, PovParagraph, find_pov_scenes, heading_pov

CHARACTERS = {"mira", "einard", "arianna"}


def _chapter(title: str | None, *texts: str) -> PovChapter:
    return PovChapter(
        id=uuid4(), title=title, paragraphs=[PovParagraph(id=uuid4(), text=t) for t in texts]
    )


def _scenes(*chapters: PovChapter):
    scenes = find_pov_scenes(list(chapters), is_character=lambda n: n.casefold() in CHARACTERS)
    return [(s.name, s.source, len(s.paragraph_ids)) for s in scenes]


def test_heading_pov_is_the_name_above_the_chapter_line() -> None:
    assert heading_pov("Mira\n\nRozdział 1\n\n„Panie, daj mi siłę”") == "Mira"
    assert heading_pov("**Einard**\nRozdział 2. Coś złego") == "Einard"
    assert heading_pov("Rozdział 3") is None
    assert heading_pov("Prolog") is None
    assert heading_pov(None) is None


def test_unnamed_break_keeps_chapter_pov_as_assumed() -> None:
    ch = _chapter("Mira\nRozdział 1", "Tekst.", "***", "Dalej.", "Jeszcze.")
    assert _scenes(ch) == [("Mira", "heading", 1), ("Mira", "assumed", 3)]


def test_break_named_on_its_own_lines_or_next_paragraph() -> None:
    ch = _chapter(
        "Mira\nRozdział 1",
        "Tekst.",
        "***\nEinard",
        "Jego scena.",
        "***",
        "Arianna",
        "Jej scena.",
    )
    assert _scenes(ch) == [
        ("Mira", "heading", 1),
        ("Einard", "scene_break", 2),
        ("Arianna", "scene_break", 3),
    ]


def test_short_line_after_break_is_not_a_name_unless_a_character() -> None:
    ch = _chapter("Mira\nRozdział 1", "***", "Cisza.", "***", "Pum")
    assert [s[:2] for s in _scenes(ch)] == [("Mira", "assumed"), ("Mira", "assumed")]


def test_chapter_without_heading_name_is_unknown() -> None:
    ch = _chapter(None, "Agnieszka Mikołajczyk-Bareła")
    assert _scenes(ch) == [(None, "unknown", 1)]


def test_pov_does_not_carry_across_chapters() -> None:
    a = _chapter("Mira\nRozdział 1", "***\nEinard", "Tekst.")
    b = _chapter("Rozdział 2", "Tekst.")
    assert [s[:2] for s in _scenes(a, b)] == [("Einard", "scene_break"), (None, "unknown")]
