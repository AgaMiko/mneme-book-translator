"""Fragment translation endpoints (Step 5).

- ``GET  /books/{id}/translation`` — latest run and every stage's text.
- ``GET  /books/{id}/translation/estimate`` — rough cost for the whole book
  or for ``?chapter_id=…`` (repeatable).
- ``POST /books/{id}/translation/run`` — start a run (whole book or chapters).
- ``POST /books/{id}/translation/continue`` — resume a stopped or failed run.
- ``POST /books/{id}/translation/stop`` — cooperative stop; fragments finish
  their current stage first.

Runs execute as ``asyncio`` tasks, like voice extraction.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 - FastAPI resolves path params at runtime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.book import Book, Chapter
from app.schemas.translation import (
    StartTranslationIn,
    TranslationEstimateOut,
    TranslationRunOut,
    TranslationStageEstimateOut,
    TranslationViewResponse,
)
from app.services import translation_service
from app.services.translation_estimate import estimate_translation
from app.services.translation_service import TranslationConflictError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/books", tags=["translation"])

log = get_logger(__name__)

# Keep references so running tasks are not garbage-collected.
_RUNNING_TASKS: set[asyncio.Task[None]] = set()


def _schedule_run(run_id: UUID, settings: Settings) -> None:
    task = asyncio.create_task(
        translation_service.run_translation(run_id=run_id, settings=settings)
    )
    _RUNNING_TASKS.add(task)

    def _on_done(t: asyncio.Task[None]) -> None:
        _RUNNING_TASKS.discard(t)
        try:
            t.result()
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("translation_run_background_unhandled", run_id=str(run_id))

    task.add_done_callback(_on_done)


def _require_key(settings: Settings) -> None:
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )


@router.get(
    "/{book_id}/translation",
    response_model=TranslationViewResponse,
    summary="Latest translation run and translated text per stage",
)
async def get_translation(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TranslationViewResponse:
    if await session.get(Book, book_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    view = await translation_service.build_translation_view(session, book_id=book_id)
    return TranslationViewResponse.model_validate(view)


@router.get(
    "/{book_id}/translation/estimate",
    response_model=TranslationEstimateOut,
    summary="Rough token and cost estimate for translating the book or chapters",
)
async def get_translation_estimate(
    book_id: UUID,
    chapter_id: list[UUID] | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TranslationEstimateOut:
    book = (
        await session.execute(
            select(Book)
            .where(Book.id == book_id)
            .options(selectinload(Book.chapters).selectinload(Chapter.paragraphs))
        )
    ).scalar_one_or_none()
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    wanted = set(chapter_id) if chapter_id else None
    words = sum(
        len((p.text or "").split())
        for c in book.chapters
        if wanted is None or c.id in wanted
        for p in c.paragraphs
    )
    glossary, _ = await translation_service.load_glossary_rows(session, book_id=book_id)
    est = estimate_translation(
        word_count=words, fragment_count=None, glossary_terms=len(glossary), settings=settings
    )
    return TranslationEstimateOut(
        word_count=est.word_count,
        fragment_count=est.fragment_count,
        glossary_terms=est.glossary_terms,
        total_tokens=est.total_tokens,
        cost_usd=est.cost_usd,
        stages=[
            TranslationStageEstimateOut(
                stage=s.stage,  # type: ignore[arg-type]
                model=s.model,
                calls=s.calls,
                input_tokens=s.input_tokens,
                output_tokens=s.output_tokens,
                cost_usd=s.cost_usd,
            )
            for s in est.stages
        ],
    )


@router.post(
    "/{book_id}/translation/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TranslationRunOut,
    summary="Start translating the book or selected chapters (background)",
)
async def start_translation(
    book_id: UUID,
    body: StartTranslationIn,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TranslationRunOut:
    _require_key(settings)
    try:
        run = await translation_service.start_translation_run(
            session,
            book_id=book_id,
            chapter_ids=body.chapter_ids,
            retranslate=body.retranslate,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TranslationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _schedule_run(run.id, settings)
    log.info("translation_run_scheduled", book_id=str(book_id), run_id=str(run.id))
    return TranslationRunOut.model_validate(translation_service.run_json(run))


@router.post(
    "/{book_id}/translation/continue",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TranslationRunOut,
    summary="Continue the latest stopped or failed translation run",
)
async def continue_translation(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TranslationRunOut:
    _require_key(settings)
    try:
        run = await translation_service.resume_translation_run(session, book_id=book_id)
    except TranslationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _schedule_run(run.id, settings)
    log.info("translation_run_resumed", book_id=str(book_id), run_id=str(run.id))
    return TranslationRunOut.model_validate(translation_service.run_json(run))


@router.post(
    "/{book_id}/translation/stop",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask the running translation to stop after the current stages",
)
async def stop_translation(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if not await translation_service.request_stop(session, book_id=book_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No translation is running for this book.",
        )
    return {"book_id": str(book_id)}
