"""Books endpoints.

Upload is split into two concerns:

1. **Synchronous, returned to the client immediately**: parse the docx,
   persist Book + Chapter + Paragraph, return the book with
   ``metadata_status="pending"``. This keeps the spinner short — the user
   sees the manuscript almost as fast as we can read the file.

2. **Asynchronous, in the background**: extract metadata via the LLM
   chain, update the same book row, flip ``metadata_status``. The client
   polls until the status changes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import NoResultFound

from app.constants import models
from app.core.config import Settings, get_settings
from app.core.db import get_session, rowcount
from app.core.logging import get_logger
from app.generation import GenerationDisabledError
from app.models.book import Book
from app.models.glossary import INACTIVE_STATUSES, GlossaryEntry
from app.schemas.book import (
    BookDetail,
    BookSummary,
    GlossaryExtractionEstimateResponse,
    GlossaryExtractionStartResponse,
    GlossaryExtractionStopResponse,
    UploadBookResponse,
    VoiceExtractionEstimateResponse,
    VoicePassEstimateResponse,
)
from app.schemas.glossary import (
    GlossaryImportIn,
    GlossaryImportResponse,
    GlossaryImportSourceOut,
    GlossaryImportSourcesResponse,
    GlossaryWorkingEntryOut,
    GlossaryWorkingEntryPatchIn,
    WorkingGlossaryResponse,
)
from app.schemas.speakers import WorkingSpeakersResponse
from app.schemas.voice import (
    VoiceWorkingProfileOut,
    VoiceWorkingProfilePatchIn,
    WorkingVoicesResponse,
)
from app.services import (
    book_service,
    glossary_llm_review,
    glossary_service,
    speakers_service,
    stages,
    voice_service,
)
from app.services.glossary_extraction_estimate import estimate_glossary_extraction
from app.services.manuscript_parser import ParsedManuscript, parse_docx
from app.services.voice_extraction_estimate import (
    VoicePassEstimate,
    estimate_voice_extraction,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/books", tags=["books"])

log = get_logger(__name__)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _opening_sample(parsed: ParsedManuscript, max_chars: int = 1000) -> str:
    """Concatenate paragraphs from the start until we hit ``max_chars``.

    Returns an empty string when the manuscript has no extractable text,
    in which case the route skips the LLM call entirely and marks the
    book as ``ready`` so the frontend doesn't poll forever.
    """
    out: list[str] = []
    total = 0
    for chapter in parsed.chapters:
        for para in chapter.paragraphs:
            if total >= max_chars:
                break
            text = para.text.strip()
            if not text:
                continue
            out.append(text)
            total += len(text) + 2  # +2 for the joining "\n\n"
        if total >= max_chars:
            break
    joined = "\n\n".join(out)
    return joined[:max_chars]


@router.post(
    "",
    response_model=UploadBookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a .docx manuscript",
)
async def upload_book(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    source_language: str = Form("pl"),
    target_language: str = Form("en"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UploadBookResponse:
    """Accept a `.docx`, parse, persist, and kick off async metadata extraction."""

    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .docx files are accepted.",
        )

    if file.content_type and file.content_type not in {_DOCX_MIME, "application/octet-stream"}:
        log.warning("unexpected_content_type", content_type=file.content_type)

    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = settings.UPLOAD_DIR / f"{uuid4()}.docx"
    storage_path.write_bytes(contents)

    fallback_title = Path(file.filename).stem
    try:
        parsed = parse_docx(
            storage_path, fallback_title=fallback_title, source_language=source_language
        )
    except Exception as exc:
        storage_path.unlink(missing_ok=True)
        log.exception("parse_failed", filename=file.filename)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse .docx: {exc}",
        ) from exc

    book = await book_service.create_book_from_parsed(
        session,
        parsed=parsed,
        original_filename=file.filename,
        storage_path=storage_path,
        source_language=source_language,
        target_language=target_language,
    )

    sample = _opening_sample(parsed)
    if sample:
        # FastAPI runs background tasks after the response is sent; the
        # client gets the book back immediately and the LLM call happens
        # behind the scenes. Errors inside enrich_book_metadata are
        # captured there — they never bubble to the client.
        background.add_task(
            book_service.enrich_book_metadata,
            book_id=book.id,
            sample=sample,
            settings=settings,
        )
    else:
        # Empty manuscript — flip status now so the frontend stops polling.
        book.metadata_status = "ready"
        await session.commit()
        await session.refresh(book)

    log.info(
        "book_uploaded",
        book_id=str(book.id),
        title=book.title,
        chapters=len(parsed.chapters),
        paragraphs=parsed.paragraph_count,
        word_count=parsed.word_count,
        metadata_scheduled=bool(sample),
    )

    return UploadBookResponse(
        book=BookSummary.model_validate(book),
        chapter_count=len(parsed.chapters),
        paragraph_count=parsed.paragraph_count,
    )


def _step_settings(settings: Settings, step: models.Step, model: str | None) -> Settings:
    """Settings with the model picked for this run or estimate (422 if unknown)."""
    try:
        return models.settings_for_step(settings, step, model)
    except models.UnknownModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


class StepModelsOut(BaseModel):
    default: str
    recommended: str
    note: str


class ModelOptionOut(BaseModel):
    id: str
    label: str
    provider: str


class ModelsOut(BaseModel):
    options: list[ModelOptionOut]
    steps: dict[str, StepModelsOut]


@router.get(
    "/models", response_model=ModelsOut, summary="Models per step, with the recommended one"
)
async def list_models(settings: Settings = Depends(get_settings)) -> ModelsOut:
    return ModelsOut(
        options=[
            ModelOptionOut(id=m.id, label=m.label, provider=m.provider)
            for m in models.MODEL_OPTIONS
        ],
        steps={
            step: StepModelsOut(
                default=models.default_model(settings, step),
                recommended=models.RECOMMENDED[step][0],
                note=models.RECOMMENDED[step][1],
            )
            for step in models.STEPS
        },
    )


@router.get("", response_model=list[BookSummary])
async def list_books(
    session: AsyncSession = Depends(get_session),
) -> list[BookSummary]:
    books = await book_service.list_books(session)
    return [BookSummary.model_validate(b) for b in books]


@router.get("/{book_id}", response_model=BookDetail)
async def get_book(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> BookDetail:
    try:
        book = await book_service.get_book_detail(session, book_id)
    except NoResultFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found") from exc
    return BookDetail.model_validate(book)


@router.get(
    "/{book_id}/glossary-extraction-estimate",
    response_model=GlossaryExtractionEstimateResponse,
    summary="Predict glossary extraction tokens and cost",
)
async def get_glossary_extraction_estimate(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: str | None = Query(default=None),
) -> GlossaryExtractionEstimateResponse:
    settings = _step_settings(settings, "glossary", model)
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    result = estimate_glossary_extraction(word_count=book.word_count, settings=settings)
    return GlossaryExtractionEstimateResponse(
        model=result.model,
        window_count=result.window_count,
        window_words=result.window_words,
        overlap_words=result.overlap_words,
        estimated_input_tokens=result.estimated_input_tokens,
        estimated_output_tokens=result.estimated_output_tokens,
        estimated_total_tokens=result.estimated_total_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        pricing_input_usd_per_mtok=result.pricing_input_usd_per_mtok,
        pricing_output_usd_per_mtok=result.pricing_output_usd_per_mtok,
    )


def _pass_estimate_response(pe: VoicePassEstimate) -> VoicePassEstimateResponse:
    return VoicePassEstimateResponse(
        model=pe.model,
        window_count=pe.window_count,
        character_count=pe.character_count,
        estimated_input_tokens=pe.estimated_input_tokens,
        estimated_output_tokens=pe.estimated_output_tokens,
        estimated_total_tokens=pe.estimated_total_tokens,
        estimated_cost_usd=pe.estimated_cost_usd,
    )


@router.get(
    "/{book_id}/voice-extraction-estimate",
    response_model=VoiceExtractionEstimateResponse,
    summary="Predict voice pipeline tokens and cost (Pass 1 + Pass 2)",
)
async def get_voice_extraction_estimate(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    speakers_model: str | None = Query(default=None),
    voices_model: str | None = Query(default=None),
) -> VoiceExtractionEstimateResponse:
    settings = _step_settings(settings, "speakers", speakers_model)
    settings = _step_settings(settings, "voices", voices_model)
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    character_count = int(
        await session.scalar(
            select(func.count())
            .select_from(GlossaryEntry)
            .where(
                GlossaryEntry.book_id == book_id,
                GlossaryEntry.term_type == "character_name",
                GlossaryEntry.status.not_in(INACTIVE_STATUSES),
            ),
        )
        or 0,
    )
    result = estimate_voice_extraction(
        word_count=book.word_count,
        character_count=character_count,
        settings=settings,
    )
    return VoiceExtractionEstimateResponse(
        model=result.model,
        window_words=result.window_words,
        overlap_words=result.overlap_words,
        character_count=result.character_count,
        pass1=_pass_estimate_response(result.pass1),
        pass2=_pass_estimate_response(result.pass2),
        estimated_total_tokens=result.estimated_total_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        pricing_input_usd_per_mtok=result.pricing_input_usd_per_mtok,
        pricing_output_usd_per_mtok=result.pricing_output_usd_per_mtok,
    )


@router.get(
    "/{book_id}/glossary-working",
    response_model=WorkingGlossaryResponse,
    summary="Latest glossary extraction run and working entries",
)
async def get_working_glossary(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> WorkingGlossaryResponse:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return await glossary_service.build_working_glossary_response(session, book_id=book_id)


class StageFinishedIn(BaseModel):
    finished: bool


@router.put(
    "/{book_id}/stages/{stage}/finished",
    response_model=BookDetail,
    summary="Mark a stage (glossary or voices) as finished by hand, or unmark it",
)
async def set_stage_finished(
    book_id: UUID,
    stage: stages.Stage,
    body: StageFinishedIn,
    session: AsyncSession = Depends(get_session),
) -> BookDetail:
    try:
        book = await book_service.get_book_detail(session, book_id)
    except NoResultFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found") from exc
    try:
        stages.set_marked_finished(book, stage, body.finished)
    except stages.StageConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return BookDetail.model_validate(book)


@router.get(
    "/{book_id}/glossary-working/review-estimate",
    summary="Tokens and cost of reviewing the pending glossary terms with the LLM",
)
async def estimate_glossary_review(
    book_id: UUID,
    model: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    settings = _step_settings(settings, "glossary_review", model)
    return await glossary_llm_review.estimate_review(session, book_id=book_id, settings=settings)


@router.post(
    "/{book_id}/glossary-working/review",
    summary="Decide the pending glossary terms with the LLM, for the author to check",
)
async def review_pending_glossary_terms(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: str | None = Query(default=None),
) -> dict[str, float]:
    settings = _step_settings(settings, "glossary_review", model)
    try:
        return await glossary_llm_review.review_pending_terms(
            session, book_id=book_id, settings=settings
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except glossary_llm_review.ReviewConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GenerationDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        ) from exc


@router.post(
    "/{book_id}/glossary-working/confirm-auto",
    summary="Confirm every automatic glossary decision that is still unconfirmed",
)
async def confirm_auto_glossary_reviews(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    if await session.get(Book, book_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    try:
        confirmed = await glossary_service.confirm_auto_reviews(session, book_id=book_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No glossary extraction run exists for this book.",
        ) from exc
    return {"confirmed": confirmed}


@router.patch(
    "/{book_id}/glossary-working/entries/{entry_id}",
    response_model=GlossaryWorkingEntryOut,
    summary="Update a working glossary entry (translation and/or accept)",
)
async def patch_working_glossary_entry(
    book_id: UUID,
    entry_id: UUID,
    body: GlossaryWorkingEntryPatchIn,
    session: AsyncSession = Depends(get_session),
) -> GlossaryWorkingEntryOut:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    try:
        return await glossary_service.patch_working_glossary_entry(
            session,
            book_id=book_id,
            entry_id=entry_id,
            patch=body,
        )
    except LookupError as exc:
        code = exc.args[0] if exc.args else ""
        if code == "no_run":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No glossary extraction run exists for this book.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Glossary entry not found for this book's latest run.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{book_id}/glossary-extraction/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Start glossary extraction (background)",
)
async def run_glossary_extraction(
    book_id: UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    settings = _step_settings(settings, "glossary", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    result = await session.execute(
        update(Book)
        .where(
            Book.id == book_id,
            Book.glossary_extraction_status != "running",
        )
        .values(
            glossary_extraction_status="running",
            glossary_extraction_cancel_requested=False,
            glossary_extraction_windows_total=None,
            glossary_extraction_windows_completed=None,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Glossary extraction is already running for this book.",
        )

    background.add_task(
        glossary_service.extract_book_glossary,
        book_id=book_id,
        settings=settings,
    )
    log.info("glossary_extraction_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


@router.post(
    "/{book_id}/glossary-extraction/continue",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Resume glossary extraction from the last failed or stopped run",
)
async def continue_glossary_extraction(
    book_id: UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    # False: "Continue without limit" after a cost pause.
    cost_limit: bool = Query(default=True),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    settings = _step_settings(settings, "glossary", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.glossary_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Glossary extraction is already running for this book.",
        )
    if not await glossary_service.can_continue_glossary_extraction(
        session,
        book_id=book_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No interrupted extraction to continue, the manuscript changed since that run, "
                "or the run is already complete. Start a new run if you need a fresh pass."
            ),
        )

    result = await session.execute(
        update(Book)
        .where(Book.id == book_id, Book.glossary_extraction_status != "running")
        .values(
            glossary_extraction_status="running",
            glossary_extraction_cancel_requested=False,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Glossary extraction is already running for this book.",
        )

    background.add_task(
        glossary_service.extract_book_glossary,
        book_id=book_id,
        settings=settings,
        continue_extraction=True,
        cost_limit=cost_limit,
    )
    log.info("glossary_extraction_continue_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


@router.post(
    "/{book_id}/glossary-extraction/expand",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Read the manuscript again and add missing terms to the current glossary",
)
async def expand_glossary(
    book_id: UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    """Runs every window on the latest glossary run in place. Reviewed terms
    are kept as they are; only new terms (as proposals) and variants are added.
    """
    settings = _step_settings(settings, "glossary", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    run, _entries = await glossary_service.load_working_glossary_for_latest_run(
        session, book_id=book_id
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This book has no glossary yet. Run an extraction or import one first.",
        )

    result = await session.execute(
        update(Book)
        .where(Book.id == book_id, Book.glossary_extraction_status != "running")
        .values(
            glossary_extraction_status="running",
            glossary_extraction_cancel_requested=False,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Glossary extraction is already running for this book.",
        )

    background.add_task(
        glossary_service.extract_book_glossary,
        book_id=book_id,
        settings=settings,
        expand=True,
    )
    log.info("glossary_expand_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


@router.get(
    "/{book_id}/glossary-import-sources",
    response_model=GlossaryImportSourcesResponse,
    summary="Other books with reviewed glossary terms to import",
)
async def list_glossary_import_sources(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> GlossaryImportSourcesResponse:
    sources = await glossary_service.list_glossary_import_sources(session, book_id=book_id)
    return GlossaryImportSourcesResponse(
        sources=[GlossaryImportSourceOut.model_validate(s) for s in sources]
    )


@router.post(
    "/{book_id}/glossary-import",
    response_model=GlossaryImportResponse,
    summary="Copy the reviewed terms of another book's glossary into this book's",
)
async def import_glossary(
    book_id: UUID,
    body: GlossaryImportIn,
    session: AsyncSession = Depends(get_session),
) -> GlossaryImportResponse:
    if body.source_book_id == book_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a different book to import from.",
        )
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    if book.glossary_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Wait for the glossary extraction to finish, or stop it, before importing.",
        )
    try:
        counts = await glossary_service.import_glossary_from_book(
            session, book_id=book_id, source_book_id=body.source_book_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GlossaryImportResponse(**counts)


@router.post(
    "/{book_id}/glossary-extraction/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStopResponse,
    summary="Request cooperative cancel of glossary extraction",
)
async def stop_glossary_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> GlossaryExtractionStopResponse:
    result = await session.execute(
        update(Book)
        .where(
            Book.id == book_id,
            Book.glossary_extraction_status == "running",
        )
        .values(glossary_extraction_cancel_requested=True),
    )
    await session.commit()
    if rowcount(result) == 0:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Glossary extraction is not running for this book.",
        )
    log.info("glossary_extraction_stop_requested", book_id=str(book_id))
    return GlossaryExtractionStopResponse(book_id=book_id)


def _schedule_extract_book_voices(
    book_id: UUID,
    settings: Settings,
    *,
    continue_extraction: bool = False,
    cost_limit: bool = True,
) -> None:
    """Run voice extraction in the current event loop (not after HTTP response only).

    Starlette's ``BackgroundTasks`` run only after the response is fully sent. In some
    setups (reload, proxy buffering, or client behavior) that path is unreliable. Using
    ``asyncio.create_task`` matches glossary-style fire-and-forget and starts work as
    soon as the request commits.
    """
    task = asyncio.create_task(
        voice_service.extract_book_voices(
            book_id=book_id,
            settings=settings,
            continue_extraction=continue_extraction,
            cost_limit=cost_limit,
        )
    )

    def _on_done(t: asyncio.Task[object]) -> None:
        try:
            t.result()
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception(
                "voice_extraction_background_unhandled",
                book_id=str(book_id),
            )

    task.add_done_callback(_on_done)


def _voice_extraction_has_partial_progress(book: Book) -> bool:
    tw = book.voice_extraction_windows_total
    done = book.voice_extraction_windows_completed
    return tw is not None and done is not None and tw > 0 and 0 < done < tw


@router.get(
    "/{book_id}/speakers-working",
    response_model=WorkingSpeakersResponse,
    summary="Pass 1 speaker map (characters x window numbers)",
)
async def get_working_speakers(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> WorkingSpeakersResponse:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    return await speakers_service.build_working_speakers_response(session, book_id=book_id)


@router.get(
    "/{book_id}/voices-working",
    response_model=WorkingVoicesResponse,
    summary="Character voice profiles for review",
)
async def get_working_voices(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> WorkingVoicesResponse:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    return await voice_service.build_working_voices_response(session, book_id=book_id)


@router.patch(
    "/{book_id}/voices-working/profiles/{voice_id}",
    response_model=VoiceWorkingProfileOut,
    summary="Update a voice profile (accept/reject or edit baseline)",
)
async def patch_working_voice_profile(
    book_id: UUID,
    voice_id: UUID,
    body: VoiceWorkingProfilePatchIn,
    session: AsyncSession = Depends(get_session),
) -> VoiceWorkingProfileOut:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    try:
        return await voice_service.patch_working_voice_profile(
            session,
            book_id=book_id,
            voice_id=voice_id,
            patch=body,
        )
    except LookupError as exc:
        if exc.args and exc.args[0] == "voice":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile not found for this book.",
            ) from exc
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{book_id}/voice-extraction/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Start voice extraction (background)",
)
async def run_voice_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    settings = _step_settings(settings, "voices", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.voice_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction is already running for this book.",
        )
    if book.voice_extraction_status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction already completed for this book.",
        )
    if _voice_extraction_has_partial_progress(book):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An interrupted extraction exists — use Continue to resume.",
        )

    ok, reason = await voice_service.can_run_voice_extraction(session, book_id=book_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=reason or "Voice extraction cannot start.",
        )

    result = await session.execute(
        update(Book)
        .where(
            Book.id == book_id,
            Book.voice_extraction_status != "running",
        )
        .values(
            voice_extraction_status="running",
            voice_extraction_cancel_requested=False,
            voice_extraction_windows_total=None,
            voice_extraction_windows_completed=None,
            voice_extraction_last_error=None,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction is already running for this book.",
        )

    _schedule_extract_book_voices(book_id, settings, continue_extraction=False)
    log.info("voice_extraction_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


@router.post(
    "/{book_id}/voice-extraction/continue",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Resume voice extraction after failure or cancel",
)
async def continue_voice_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    # False: "Continue without limit" after a cost pause.
    cost_limit: bool = Query(default=True),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    settings = _step_settings(settings, "voices", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.voice_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction is already running for this book.",
        )
    if not await voice_service.can_continue_voice_extraction(session, book_id=book_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No interrupted voice extraction to continue, the manuscript changed since that run, "
                "or the run is already complete."
            ),
        )

    result = await session.execute(
        update(Book)
        .where(Book.id == book_id, Book.voice_extraction_status != "running")
        .values(
            voice_extraction_status="running",
            voice_extraction_cancel_requested=False,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction is already running for this book.",
        )

    _schedule_extract_book_voices(
        book_id, settings, continue_extraction=True, cost_limit=cost_limit
    )
    log.info("voice_extraction_continue_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


def _schedule_regenerate_flagged_voices(
    book_id: UUID,
    settings: Settings,
) -> None:
    task = asyncio.create_task(
        voice_service.regenerate_flagged_voices(
            book_id=book_id,
            settings=settings,
        )
    )

    def _on_done(t: asyncio.Task[object]) -> None:
        try:
            t.result()
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception(
                "voice_regeneration_background_unhandled",
                book_id=str(book_id),
            )

    task.add_done_callback(_on_done)


@router.post(
    "/{book_id}/voice-extraction/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Re-extract flagged voice profiles in their speaker windows only",
)
async def regenerate_flagged_voice_profiles(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    settings = _step_settings(settings, "voices", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.voice_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction is already running for this book.",
        )

    ok, reason = await voice_service.can_regenerate_flagged_voices(session, book_id=book_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=reason or "Voice regeneration cannot start.",
        )

    result = await session.execute(
        update(Book)
        .where(
            Book.id == book_id,
            Book.voice_extraction_status != "running",
        )
        .values(
            voice_extraction_status="running",
            voice_extraction_cancel_requested=False,
            voice_extraction_windows_total=None,
            voice_extraction_windows_completed=None,
            voice_extraction_last_error=None,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction is already running for this book.",
        )

    _schedule_regenerate_flagged_voices(book_id, settings)
    log.info("voice_regeneration_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


@router.post(
    "/{book_id}/voice-extraction/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStopResponse,
    summary="Request cooperative cancel of voice extraction",
)
async def stop_voice_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> GlossaryExtractionStopResponse:
    result = await session.execute(
        update(Book)
        .where(
            Book.id == book_id,
            Book.voice_extraction_status == "running",
        )
        .values(voice_extraction_cancel_requested=True),
    )
    await session.commit()
    if rowcount(result) == 0:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice extraction is not running for this book.",
        )
    log.info("voice_extraction_stop_requested", book_id=str(book_id))
    return GlossaryExtractionStopResponse(book_id=book_id)


@router.post(
    "/{book_id}/voice-extraction/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all character voice data and reset extraction state",
)
async def reset_voice_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.voice_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stop voice extraction before resetting.",
        )
    await voice_service.reset_book_voice_data(session, book=book)
    log.info("voice_extraction_reset", book_id=str(book_id))


# ─── Speaker identification (Pass 1, runs before voice extraction) ──


def _schedule_extract_book_speakers(
    book_id: UUID,
    settings: Settings,
    *,
    continue_extraction: bool = False,
    cost_limit: bool = True,
) -> None:
    """Fire-and-forget Pass 1. Same scheduling shape as voices."""
    task = asyncio.create_task(
        speakers_service.extract_book_speakers(
            book_id=book_id,
            settings=settings,
            continue_extraction=continue_extraction,
            cost_limit=cost_limit,
        )
    )

    def _on_done(t: asyncio.Task[object]) -> None:
        try:
            t.result()
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception(
                "speakers_extraction_background_unhandled",
                book_id=str(book_id),
            )

    task.add_done_callback(_on_done)


def _speakers_extraction_has_partial_progress(book: Book) -> bool:
    tw = book.speakers_extraction_windows_total
    done = book.speakers_extraction_windows_completed
    return tw is not None and done is not None and tw > 0 and 0 < done < tw


@router.post(
    "/{book_id}/speaker-extraction/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Start speaker identification (Pass 1, background)",
)
async def run_speakers_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    settings = _step_settings(settings, "speakers", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.speakers_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker identification is already running for this book.",
        )
    if book.speakers_extraction_status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker identification already completed for this book.",
        )
    if _speakers_extraction_has_partial_progress(book):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An interrupted speaker identification exists — use Continue to resume.",
        )

    ok, reason = await speakers_service.can_run_speakers_extraction(session, book_id=book_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=reason or "Speaker identification cannot start.",
        )

    result = await session.execute(
        update(Book)
        .where(
            Book.id == book_id,
            Book.speakers_extraction_status != "running",
        )
        .values(
            speakers_extraction_status="running",
            speakers_extraction_cancel_requested=False,
            speakers_extraction_windows_total=None,
            speakers_extraction_windows_completed=None,
            speakers_extraction_last_error=None,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker identification is already running for this book.",
        )

    _schedule_extract_book_speakers(book_id, settings, continue_extraction=False)
    log.info("speakers_extraction_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


@router.post(
    "/{book_id}/speaker-extraction/continue",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStartResponse,
    summary="Resume speaker identification after failure or cancel",
)
async def continue_speakers_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    # False: "Continue without limit" after a cost pause.
    cost_limit: bool = Query(default=True),
    model: str | None = Query(default=None),
) -> GlossaryExtractionStartResponse:
    settings = _step_settings(settings, "speakers", model)
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.speakers_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker identification is already running for this book.",
        )
    if not await speakers_service.can_continue_speakers_extraction(session, book_id=book_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No interrupted speaker identification to continue, the manuscript "
                "changed since that run, or the run is already complete."
            ),
        )

    result = await session.execute(
        update(Book)
        .where(Book.id == book_id, Book.speakers_extraction_status != "running")
        .values(
            speakers_extraction_status="running",
            speakers_extraction_cancel_requested=False,
        ),
    )
    await session.commit()
    if rowcount(result) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker identification is already running for this book.",
        )

    _schedule_extract_book_speakers(
        book_id, settings, continue_extraction=True, cost_limit=cost_limit
    )
    log.info("speakers_extraction_continue_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


@router.post(
    "/{book_id}/speaker-extraction/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GlossaryExtractionStopResponse,
    summary="Request cooperative cancel of speaker identification",
)
async def stop_speakers_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> GlossaryExtractionStopResponse:
    result = await session.execute(
        update(Book)
        .where(
            Book.id == book_id,
            Book.speakers_extraction_status == "running",
        )
        .values(speakers_extraction_cancel_requested=True),
    )
    await session.commit()
    if rowcount(result) == 0:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker identification is not running for this book.",
        )
    log.info("speakers_extraction_stop_requested", book_id=str(book_id))
    return GlossaryExtractionStopResponse(book_id=book_id)


@router.post(
    "/{book_id}/speaker-extraction/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all speaker identification data and reset extraction state",
)
async def reset_speakers_extraction(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.speakers_extraction_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stop speaker identification before resetting.",
        )
    await speakers_service.reset_book_speakers_data(session, book=book)
    log.info("speakers_extraction_reset", book_id=str(book_id))


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await book_service.delete_book(session, book_id)
    except NoResultFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found") from exc
