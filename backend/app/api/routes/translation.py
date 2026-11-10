"""Fragment translation endpoints (Step 5).

- ``GET  /books/{id}/translation`` — latest run and every stage's text.
- ``GET  /books/{id}/translation/estimate`` — rough cost for the whole book
  or for ``?chapter_id=…`` (repeatable).
- ``POST /books/{id}/translation/run`` — start a run (whole book or chapters).
- ``POST /books/{id}/translation/continue`` — resume a stopped or failed run.
- ``POST /books/{id}/translation/stop`` — cooperative stop; fragments finish
  their current stage first.
- ``GET  /books/{id}/translation/export?format=pdf|epub|docx&stage=…`` — the
  translated book as a file. Refused while a special passage has no checked
  translation, unless ``draft=true``.

Runs execute as ``asyncio`` tasks, like voice extraction.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 - FastAPI resolves path params at runtime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.constants import models
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.generation.chains.translate_fragment_chain import stage_model, stage_thinking
from app.generation.providers.openai import is_openai_model
from app.models.book import Book, Chapter
from app.models.translation import TRANSLATION_STAGES
from app.schemas.translation import (
    StartTranslationIn,
    TranslationEstimateOut,
    TranslationRunOut,
    TranslationStageEstimateOut,
    TranslationTermsResponse,
    TranslationViewResponse,
)
from app.services import special_passages_service, translation_export, translation_service
from app.services.translation_estimate import estimate_translation
from app.services.translation_service import TranslationConflictError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/books", tags=["translation"])

log = get_logger(__name__)

# Keep references so running tasks are not garbage-collected.
_RUNNING_TASKS: set[asyncio.Task[None]] = set()


def _model_settings(settings: Settings, model: str | None) -> Settings:
    """Settings with ``model`` for every translation stage (422 if unknown)."""
    try:
        return models.settings_for_step(settings, "translation", model)
    except models.UnknownModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _schedule_run(
    run_id: UUID, book_id: UUID, settings: Settings, *, cost_limit: bool = True
) -> None:
    translate = translation_service.run_translation(
        run_id=run_id, settings=settings, cost_limit=cost_limit
    )
    # Special passages (Step 6): scanned once while the book is translated,
    # then checked and corrected when the run ends.
    task = asyncio.create_task(
        special_passages_service.run_around_translation(
            book_id=book_id, settings=settings, translate=translate
        )
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
    """Every provider used by a translation stage needs its API key."""
    models = {stage_model(settings, s) for s in TRANSLATION_STAGES}
    if any(is_openai_model(m) for m in models) and not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured (needed for the gpt-… translation model).",
        )
    if any(not is_openai_model(m) for m in models) and not settings.GEMINI_API_KEY:
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
    model: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TranslationEstimateOut:
    settings = _model_settings(settings, model)
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
    stage_count = len(est.stages)
    return TranslationEstimateOut(
        service_tier=settings.TRANSLATION_OPENAI_SERVICE_TIER or None,
        word_count=est.word_count,
        fragment_count=est.fragment_count,
        glossary_terms=est.glossary_terms,
        total_tokens=est.total_tokens,
        cost_usd=est.cost_usd,
        stages=[
            TranslationStageEstimateOut(
                stage=s.stage,  # type: ignore[arg-type]
                model=s.model,
                thinking=stage_thinking(settings, s.stage),
                stored_as="polish" if i == stage_count - 1 else s.stage,  # type: ignore[arg-type]
                calls=s.calls,
                input_tokens=s.input_tokens,
                output_tokens=s.output_tokens,
                cost_usd=s.cost_usd,
            )
            for i, s in enumerate(est.stages)
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
    settings = _model_settings(settings, body.model)
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
    _schedule_run(run.id, book_id, settings)
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
    # False: "Continue without limit" after a cost pause.
    cost_limit: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TranslationRunOut:
    _require_key(settings)
    try:
        run = await translation_service.resume_translation_run(session, book_id=book_id)
    except TranslationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # Continue on the model the run started with, when it used one model.
    used = set((run.models or {}).values())
    if len(used) == 1 and next(iter(used)) in models.MODEL_IDS:
        settings = _model_settings(settings, next(iter(used)))
    _schedule_run(run.id, book_id, settings, cost_limit=cost_limit)
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


@router.get(
    "/{book_id}/translation/export",
    summary="Download the translated book as PDF, EPUB or DOCX",
    response_class=Response,
)
async def export_translation(
    book_id: UUID,
    format: translation_export.ExportFormat = Query(default="pdf"),
    stage: translation_service.TranslationStageName = Query(default="polish"),
    draft: bool = Query(
        default=False, description="Export even when special passages still need a decision."
    ),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        book = await translation_export.assemble_book(session, book_id=book_id, stage=stage)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not book.chapters:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nothing is translated yet, so there is nothing to export.",
        )
    blocking = await special_passages_service.blocking_flag_count(session, book_id=book_id)
    if blocking and not draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{blocking} special passage(s) break their rule and have no checked "
                "translation. Decide on them in Review, or export a draft."
            ),
        )
    # Rendering is CPU-bound (PDF layout can take a while for a whole book).
    data = await run_in_threadpool(translation_export.render, book, format)
    filename = translation_export.export_filename(book, format)
    if blocking:
        # A draft says so in its name: a special passage still breaks its rule.
        stem, dot, ext = filename.rpartition(".")
        filename = f"{stem}_DRAFT{dot}{ext}"
    return Response(
        content=data,
        media_type=translation_export.MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{book_id}/translation/terms",
    response_model=TranslationTermsResponse,
    summary="Accepted glossary terms and where they occur in the source paragraphs",
)
async def get_translation_terms(
    book_id: UUID,
    include_pending: bool = Query(
        default=False, description="Also return terms still under review (for the manuscript)."
    ),
    session: AsyncSession = Depends(get_session),
) -> TranslationTermsResponse:
    if await session.get(Book, book_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    view = await translation_service.build_term_view(
        session, book_id=book_id, include_pending=include_pending
    )
    return TranslationTermsResponse.model_validate(view)
