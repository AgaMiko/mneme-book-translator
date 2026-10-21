# ruff: noqa: RUF001 - typographic dashes and quotes are the point of these tests
"""Tests for translation export: block assembly and the EPUB/DOCX renderers."""

import io
import zipfile

from app.services.translation_export import (
    Block,
    ExportBook,
    ExportChapter,
    body_blocks,
    export_filename,
    heading_blocks,
    inline_runs,
    render_docx,
    render_epub,
)


def _book() -> ExportBook:
    chapter = ExportChapter(
        blocks=[
            *heading_blocks(
                "Mira\n\nChapter 5. A Great Many Herbs\n\n"
                "“The Needle came to life.”\n– A note in the binding"
            ),
            Block("paragraph", "She read the *Songs of Memory* until dawn."),
            *body_blocks("***\n*Kerry*"),
            Block("paragraph", '"Enough!" Boris roared.'),
            Block("missing", "[Not translated yet]"),
        ]
    )
    return ExportBook(
        title="Zapłataczka",
        author="Agnieszka",
        language="en",
        chapters=[chapter],
        stage="polish",
        missing_fragments=1,
    )


def test_heading_blocks_split_pov_chapter_and_epigraph() -> None:
    blocks = heading_blocks("Mira\n\nChapter 5. A Great Many Herbs\n\n“Line one.”\n– Attribution")
    assert [(b.kind, b.text) for b in blocks] == [
        ("pov", "Mira"),
        ("chapter", "Chapter 5. A Great Many Herbs"),
        ("epigraph", "“Line one.”\n– Attribution"),
    ]


def test_body_blocks_scene_break_with_pov() -> None:
    assert [(b.kind, b.text) for b in body_blocks("***\n*Kerry*")] == [
        ("scene_break", ""),
        ("scene_pov", "Kerry"),
    ]
    assert [b.kind for b in body_blocks("One.\n\nTwo.")] == ["paragraph", "paragraph"]


def test_inline_runs_italics_bold_and_quotes() -> None:
    runs = inline_runs('He said "go" to *her* and **left**. A stray * stays.')
    assert ("her", True, False) in runs
    assert ("left", False, True) in runs
    joined = "".join(t for t, _, _ in runs)
    assert "“go”" in joined
    assert "*" in joined


def test_epub_structure() -> None:
    data = render_epub(_book())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        assert names[0] == "mimetype"
        assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        assert "OEBPS/content.opf" in names
        assert "OEBPS/nav.xhtml" in names
        chapter = z.read("OEBPS/ch001.xhtml").decode()
        assert "Chapter 5. A Great Many Herbs" in chapter
        assert "<em>Songs of Memory</em>" in chapter
        assert "Not translated yet" in chapter


def test_docx_renders() -> None:
    from docx import Document

    doc = Document(io.BytesIO(render_docx(_book())))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Chapter 5. A Great Many Herbs" in text
    assert "“Enough!” Boris roared." in text


def test_export_filename_is_ascii() -> None:
    assert export_filename(_book(), "pdf") == "Zap_ataczka_EN_final.pdf"
