"""Export the translated book as PDF, EPUB or DOCX.

The book is assembled from the database (not from Markdown files, as
``translations/zaplataczka/build_pdf.py`` did): for every chapter, the
chosen stage's text of each fragment, in order. A fragment without that
stage falls back to the latest earlier stage (polish → line edit →
faithful); a fragment with no translation at all becomes a visible
"[Not translated yet]" line, so gaps are never silent.

Blocks
------
``assemble_book`` turns the text into a small list of blocks that all three
renderers share:

- ``pov``: point-of-view name above the chapter heading;
- ``chapter``: "Chapter 5. A Great Many Herbs";
- ``epigraph``: epigraph lines and the attribution line;
- ``scene_break`` (optionally followed by ``scene_pov``);
- ``paragraph``: body text, with ``*italic*`` and ``**bold**`` markup;
- ``missing``: a fragment that is not translated yet.

The chapter heading comes from the pseudo paragraph ``title:<chapter id>``
that the first fragment of each chapter translates (see
``translation_service``).
"""

from __future__ import annotations

import html
import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.book import Book, Chapter
from app.models.translation import (
    TRANSLATION_STAGES,
    FragmentRendition,
    TranslationFragment,
)
from app.services.narration_pov import CHAPTER_LINE, SCENE_BREAK
from app.services.translation_service import current_renditions

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

ExportFormat = Literal["pdf", "epub", "docx"]
BlockKind = Literal[
    "pov", "chapter", "epigraph", "scene_break", "scene_pov", "paragraph", "missing"
]

_ATTRIBUTION = re.compile(r"^[\u2013\u2014-]\s*")


@dataclass(slots=True)
class Block:
    kind: BlockKind
    text: str = ""


@dataclass(slots=True)
class ExportChapter:
    blocks: list[Block] = field(default_factory=list)


@dataclass(slots=True)
class ExportBook:
    title: str
    author: str
    language: str
    chapters: list[ExportChapter]
    stage: str
    missing_fragments: int


# ─── Assembly ────────────────────────────────────────────


def heading_blocks(text: str) -> list[Block]:
    """Split a translated chapter heading into POV, chapter line and epigraph."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    idx = next((i for i, ln in enumerate(lines) if CHAPTER_LINE.match(_strip_marks(ln))), None)
    if idx is None:
        # No "Chapter N" line: first line is the heading, the rest an epigraph.
        idx = 0
    blocks = [Block("pov", _strip_marks(ln)) for ln in lines[:idx]]
    blocks.append(Block("chapter", _strip_marks(lines[idx])))
    epigraph = lines[idx + 1 :]
    if epigraph:
        blocks.append(Block("epigraph", "\n".join(epigraph)))
    return blocks


def body_blocks(text: str) -> list[Block]:
    """One translated paragraph → blocks (scene breaks carry an optional POV)."""
    lines = [ln.strip() for ln in text.split("\n")]
    if lines and SCENE_BREAK.match(lines[0]):
        out = [Block("scene_break")]
        rest = " ".join(ln for ln in lines[1:] if ln)
        if rest:
            out.append(Block("scene_pov", _strip_marks(rest)))
        return out
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [Block("paragraph", p) for p in paragraphs]


def _strip_marks(text: str) -> str:
    return text.strip().strip("*_").strip()


async def assemble_book(
    session: AsyncSession, *, book_id: UUID, stage: str = "polish"
) -> ExportBook:
    if stage not in TRANSLATION_STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    book = (
        await session.execute(
            select(Book).where(Book.id == book_id).options(selectinload(Book.chapters))
        )
    ).scalar_one_or_none()
    if book is None:
        raise LookupError("Book not found")
    fragments = (
        (
            await session.execute(
                select(TranslationFragment)
                .where(TranslationFragment.book_id == book_id)
                .order_by(TranslationFragment.position)
            )
        )
        .scalars()
        .all()
    )
    renditions = (
        (
            await session.execute(
                select(FragmentRendition)
                .join(TranslationFragment, TranslationFragment.id == FragmentRendition.fragment_id)
                .where(TranslationFragment.book_id == book_id)
                .order_by(FragmentRendition.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    latest = current_renditions(renditions)
    allowed = TRANSLATION_STAGES[: TRANSLATION_STAGES.index(stage) + 1][::-1]

    by_chapter: dict[UUID, list[TranslationFragment]] = {}
    for f in fragments:
        by_chapter.setdefault(f.chapter_id, []).append(f)

    chapters: list[ExportChapter] = []
    missing = 0
    for chapter in sorted(book.chapters, key=lambda c: c.position):
        frags = by_chapter.get(chapter.id, [])
        picked = [
            next((latest[(f.id, s)] for s in allowed if (f.id, s) in latest), None) for f in frags
        ]
        if not any(picked):
            continue
        ec = ExportChapter()
        title_id = f"title:{chapter.id}"
        for r in picked:
            if r is None:
                missing += 1
                ec.blocks.append(Block("missing", "[Not translated yet]"))
                continue
            for p in r.paragraphs:
                text = str(p.get("text", ""))
                if p.get("paragraph_id") == title_id:
                    ec.blocks.extend(heading_blocks(text))
                else:
                    ec.blocks.extend(body_blocks(text))
        if not any(b.kind == "chapter" for b in ec.blocks):
            ec.blocks.insert(0, Block("chapter", _chapter_label(chapter)))
        chapters.append(ec)

    return ExportBook(
        title=book.title,
        author=book.author or "",
        language=book.target_language or "en",
        chapters=chapters,
        stage=stage,
        missing_fragments=missing,
    )


def _chapter_label(chapter: Chapter) -> str:
    return f"Chapter {chapter.position + 1}"


# ─── Inline markup ───────────────────────────────────────


def smart_quotes(t: str) -> str:
    t = re.sub(r'(^|[\s(\[\u2014\u2013*])"', "\\1\u201c", t)
    t = t.replace('"', "\u201d")
    t = re.sub(r"(^|[\s(\[\u2014\u2013*])'", "\\1\u2018", t)
    return t.replace("'", "\u2019")


def inline_runs(text: str) -> list[tuple[str, bool, bool]]:
    """Split ``*italic*`` / ``**bold**`` markup into ``(text, italic, bold)`` runs.

    An unmatched asterisk stays literal.
    """
    text = smart_quotes(re.sub(r"\\([!.*_#\[\]()-])", r"\1", text))
    runs: list[tuple[str, bool, bool]] = []
    pattern = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            runs.append((text[pos : m.start()], False, False))
        if m.group(1) is not None:
            runs.append((m.group(1), False, True))
        else:
            runs.append((m.group(2), True, False))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False, False))
    return [r for r in runs if r[0]]


def inline_html(text: str) -> str:
    out = []
    for t, italic, bold in inline_runs(text):
        s = html.escape(t, quote=False)
        if bold:
            s = f"<strong>{s}</strong>"
        if italic:
            s = f"<em>{s}</em>"
        out.append(s)
    return "".join(out)


# ─── HTML (shared by PDF and EPUB) ───────────────────────

BOOK_CSS = """
body { font-family: 'EB Garamond', Georgia, 'Times New Roman', serif; line-height: 1.42; color: #111; }
p { margin: 0; text-indent: 1.4em; text-align: justify; orphans: 2; widows: 2; hyphens: auto; }
p.first, p.pov, p.break, p.scene-pov, p.missing { text-indent: 0; }
p.pov { text-align: center; font-style: italic; font-size: 1.05em; margin-bottom: .3em; }
h2.chapter { text-align: center; font-weight: 500; font-size: 1.5em; letter-spacing: .03em; margin: 0 0 1.1em; }
div.epigraph { text-align: center; font-size: .88em; margin: 0 1.2em 2em; line-height: 1.35; color: #333; }
div.epigraph p { text-indent: 0; text-align: center; }
p.break { text-align: center; margin: .9em 0; letter-spacing: .3em; }
p.scene-pov { text-align: center; font-style: italic; margin-bottom: .6em; }
p.missing { text-align: center; color: #888; font-style: italic; margin: 1em 0; }
.titlepage { text-align: center; }
.titlepage h1 { font-size: 2.4em; font-weight: 500; letter-spacing: .06em; margin: 0 0 .4em; }
.titlepage .author { font-size: 1.15em; font-style: italic; }
"""

PRINT_CSS = """
@page { size: 5.5in 8.5in; margin: 0.8in 0.7in 0.85in 0.7in;
  @bottom-center { content: counter(page); font: 9pt 'EB Garamond', Georgia, serif; color: #555; } }
@page :first { @bottom-center { content: none; } }
html { font-size: 11.2pt; }
.titlepage { height: 6.6in; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }
section.chapter { page-break-before: always; padding-top: 1.1in; }
"""


def chapter_html(chapter: ExportChapter) -> str:
    out: list[str] = []
    indent_next = False
    for b in chapter.blocks:
        if b.kind == "pov":
            out.append(f'<p class="pov">{inline_html(b.text)}</p>')
            indent_next = False
        elif b.kind == "chapter":
            out.append(f'<h2 class="chapter">{inline_html(b.text)}</h2>')
            indent_next = False
        elif b.kind == "epigraph":
            lines = "<br/>".join(inline_html(ln) for ln in b.text.split("\n"))
            out.append(f'<div class="epigraph"><p>{lines}</p></div>')
            indent_next = False
        elif b.kind == "scene_break":
            out.append('<p class="break">*</p>')
            indent_next = False
        elif b.kind == "scene_pov":
            out.append(f'<p class="scene-pov">{inline_html(b.text)}</p>')
            indent_next = False
        elif b.kind == "missing":
            out.append(f'<p class="missing">{html.escape(b.text)}</p>')
            indent_next = False
        else:
            cls = "" if indent_next else ' class="first"'
            body = inline_html(b.text).replace("\n", "<br/>")
            out.append(f"<p{cls}>{body}</p>")
            indent_next = True
    return "\n".join(out)


def book_html(book: ExportBook, *, for_print: bool) -> str:
    css = BOOK_CSS + (PRINT_CSS if for_print else "")
    parts = [
        f'<div class="titlepage"><h1>{html.escape(book.title)}</h1>'
        f'<div class="author">{html.escape(book.author)}</div></div>'
    ]
    parts += [f'<section class="chapter">{chapter_html(c)}</section>' for c in book.chapters]
    return (
        f"<!doctype html><html lang='{html.escape(book.language)}'><head><meta charset='utf-8'>"
        f"<title>{html.escape(book.title)}</title><style>{css}</style></head><body>"
        + "\n".join(parts)
        + "</body></html>"
    )


# ─── PDF ─────────────────────────────────────────────────


def render_pdf(book: ExportBook) -> bytes:
    from weasyprint import HTML  # imported lazily: needs system libraries

    return HTML(string=book_html(book, for_print=True)).write_pdf()


# ─── EPUB 3 ──────────────────────────────────────────────


def _xhtml(title: str, body: str, lang: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{lang}" xml:lang="{lang}"><head><meta charset="utf-8"/>'
        f'<title>{html.escape(title)}</title><link rel="stylesheet" href="book.css"/></head>'
        f"<body>{body}</body></html>"
    )


def _chapter_title(chapter: ExportChapter) -> str:
    return next((b.text for b in chapter.blocks if b.kind == "chapter"), "Chapter")


def render_epub(book: ExportBook) -> bytes:
    lang = book.language
    uid = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    files: dict[str, str] = {
        "OEBPS/book.css": BOOK_CSS,
        "OEBPS/title.xhtml": _xhtml(
            book.title,
            f'<div class="titlepage"><h1>{html.escape(book.title)}</h1>'
            f'<p class="author">{html.escape(book.author)}</p></div>',
            lang,
        ),
    }
    manifest = [
        '<item id="css" href="book.css" media-type="text/css"/>',
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine = ['<itemref idref="title"/>']
    nav_items = []
    for i, ch in enumerate(book.chapters, start=1):
        name = f"ch{i:03d}.xhtml"
        files[f"OEBPS/{name}"] = _xhtml(_chapter_title(ch), chapter_html(ch), lang)
        manifest.append(f'<item id="ch{i}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="ch{i}"/>')
        nav_items.append(f'<li><a href="{name}">{html.escape(_chapter_title(ch))}</a></li>')
    files["OEBPS/nav.xhtml"] = _xhtml(
        "Contents",
        '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>' + "".join(nav_items) + "</ol></nav>",
        lang,
    )
    files["OEBPS/content.opf"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="uid">{uid}</dc:identifier>'
        f"<dc:title>{html.escape(book.title)}</dc:title>"
        f"<dc:creator>{html.escape(book.author)}</dc:creator>"
        f"<dc:language>{html.escape(lang)}</dc:language>"
        f'<meta property="dcterms:modified">{modified}</meta>'
        "</metadata><manifest>" + "".join(manifest) + "</manifest>"
        "<spine>" + "".join(spine) + "</spine></package>"
    )
    files["META-INF/container.xml"] = (
        '<?xml version="1.0"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # The mimetype entry must come first and be stored uncompressed.
        z.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        for path, content in files.items():
            z.writestr(path, content, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# ─── DOCX ────────────────────────────────────────────────


def render_docx(book: ExportBook) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Pt

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "EB Garamond"
    normal.font.size = Pt(12)

    def add_runs(par, text: str) -> None:  # type: ignore[no-untyped-def]
        for t, italic, bold in inline_runs(text):
            run = par.add_run(t)
            run.italic = italic or None
            run.bold = bold or None

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run(book.title)
    r.font.size = Pt(28)
    author = doc.add_paragraph()
    author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ar = author.add_run(book.author)
    ar.italic = True

    for chapter in book.chapters:
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        first_body = True
        for b in chapter.blocks:
            if b.kind == "pov":
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run(b.text).italic = True
            elif b.kind == "chapter":
                h = doc.add_heading(level=1)
                h.alignment = WD_ALIGN_PARAGRAPH.CENTER
                add_runs(h, b.text)
                first_body = True
            elif b.kind == "epigraph":
                for line in b.text.split("\n"):
                    p = doc.add_paragraph()
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    add_runs(p, line)
                    for run in p.runs:
                        run.font.size = Pt(10.5)
                first_body = True
            elif b.kind == "scene_break":
                p = doc.add_paragraph("*")
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                first_body = True
            elif b.kind == "scene_pov" or b.kind == "missing":
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run(b.text).italic = True
            else:
                p = doc.add_paragraph()
                if not first_body:
                    p.paragraph_format.first_line_indent = Pt(18)
                add_runs(p, b.text)
                first_body = False

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


RENDERERS = {"pdf": render_pdf, "epub": render_epub, "docx": render_docx}
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def render(book: ExportBook, fmt: ExportFormat) -> bytes:
    return RENDERERS[fmt](book)


# File-name words for each stage. The last stage is "final", not "polish",
# so the name can't be read as the Polish language.
_STAGE_FILE_NAMES = {"faithful": "faithful", "line_edit": "line-edit", "polish": "final"}


def export_filename(book: ExportBook, fmt: ExportFormat) -> str:
    """ASCII file name, e.g. ``Zaplataczka_EN_final.pdf``."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", book.title).strip("_") or "translation"
    lang = re.sub(r"[^A-Za-z]", "", book.language).upper() or "EN"
    return f"{base}_{lang}_{_STAGE_FILE_NAMES.get(book.stage, book.stage)}.{fmt}"
