"""Book service — persistence and retrieval, plus async metadata enrichment.

Routers stay thin; all DB orchestration happens here. The service takes
a ParsedManuscript (parser layer) and writes Book/Chapter/Paragraph rows.
Retrieval helpers eager-load the right depth for each endpoint.

``enrich_book_metadata`` is the background task that runs *after* upload
returns: it calls the LLM chain, updates the book row, and flips
``metadata_status`` so the frontend can stop polling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import selectinload

from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.generation import (
    GenerationDisabledError,
    extract_manuscript_metadata,
)
from app.models.book import Book, Chapter, Paragraph

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings
    from app.services.manuscript_parser import ParsedManuscript

log = get_logger(__name__)


async def create_book_from_parsed(
    session: AsyncSession,
    *,
    parsed: ParsedManuscript,
    original_filename: str,
    storage_path: Path,
    source_language: str = "pl",
    target_language: str = "en",
) -> Book:
    """Persist a freshly-parsed manuscript.

    No metadata is set here. ``metadata_status`` defaults to ``"pending"``
    via the model; the caller schedules ``enrich_book_metadata`` as a
    background task and returns immediately.
    """
    book = Book(
        title=parsed.title,
        original_filename=original_filename,
        storage_path=str(storage_path),
        source_language=source_language,
        target_language=target_language,
        word_count=parsed.word_count,
    )

    for c_idx, parsed_chapter in enumerate(parsed.chapters):
        chapter = Chapter(position=c_idx, title=parsed_chapter.title)
        for p_idx, parsed_para in enumerate(parsed_chapter.paragraphs):
            chapter.paragraphs.append(
                Paragraph(
                    position=p_idx,
                    text=parsed_para.text,
                    style=parsed_para.style,
                )
            )
        book.chapters.append(chapter)

    session.add(book)
    await session.commit()
    await session.refresh(book)
    return book


async def enrich_book_metadata(
    *,
    book_id: UUID,
    sample: str,
    settings: Settings,
) -> None:
    """Background task: extract metadata via the LLM chain, update the row.

    Opens its own DB session because background tasks don't share the
    request-scoped session. Failure modes are swallowed — every error
    path flips ``metadata_status`` to ``"failed"`` so the frontend stops
    polling, then re-raises nothing. The user-visible error path is the
    failed pill in the reader UI plus the structured log line here.
    """
    SessionLocal = get_sessionmaker()
    async with SessionLocal() as session:
        book = await session.get(Book, book_id)
        if book is None:
            log.warning("book_not_found_for_enrichment", book_id=str(book_id))
            return

        try:
            metadata = await extract_manuscript_metadata(
                sample=sample,
                settings=settings,
            )
        except GenerationDisabledError:
            book.metadata_status = "failed"
            log.warning("metadata_skipped_no_key", book_id=str(book_id))
            await session.commit()
            return
        except Exception:
            book.metadata_status = "failed"
            log.exception("metadata_extraction_failed", book_id=str(book_id))
            await session.commit()
            return

        # Only overwrite the title when the LLM found one in the sample —
        # otherwise the docx-derived title (filename or core property) wins.
        if metadata.book_title:
            book.title = metadata.book_title
        book.author = metadata.author
        book.manuscript_language = metadata.manuscript_language
        book.language_style_note = metadata.language_style_note
        book.metadata_model = settings.GEMINI_MODEL
        book.metadata_status = "ready"

        await session.commit()
        log.info(
            "metadata_extracted",
            book_id=str(book_id),
            language=metadata.manuscript_language,
            has_author=metadata.author is not None,
            has_title=metadata.book_title is not None,
        )


async def list_books(session: AsyncSession) -> list[Book]:
    result = await session.execute(select(Book).order_by(Book.created_at.desc()))
    return list(result.scalars().all())


async def get_book_detail(session: AsyncSession, book_id: UUID) -> Book:
    """Eager-load chapters + paragraphs for the reader view."""
    stmt = (
        select(Book)
        .where(Book.id == book_id)
        .options(selectinload(Book.chapters).selectinload(Chapter.paragraphs))
    )
    result = await session.execute(stmt)
    book = result.scalar_one_or_none()
    if book is None:
        raise NoResultFound(f"Book {book_id} not found")
    return book


async def delete_book(session: AsyncSession, book_id: UUID) -> None:
    book = await session.get(Book, book_id)
    if book is None:
        raise NoResultFound(f"Book {book_id} not found")
    await session.delete(book)
    await session.commit()
