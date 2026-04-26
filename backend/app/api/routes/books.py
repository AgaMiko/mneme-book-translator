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

from pathlib import Path
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.book import Book
from app.schemas.book import (
    BookDetail,
    BookSummary,
    GlossaryExtractionEstimateResponse,
    GlossaryExtractionStartResponse,
    GlossaryExtractionStopResponse,
    UploadBookResponse,
)
from app.schemas.glossary import WorkingGlossaryResponse
from app.services import book_service, glossary_service
from app.services.glossary_extraction_estimate import estimate_glossary_extraction
from app.services.manuscript_parser import ParsedManuscript, parse_docx

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
        parsed = parse_docx(storage_path, fallback_title=fallback_title)
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        ) from exc
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
) -> GlossaryExtractionEstimateResponse:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
    return await glossary_service.build_working_glossary_response(
        session, book_id=book_id
    )


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
) -> GlossaryExtractionStartResponse:
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
    if result.rowcount == 0:
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
) -> GlossaryExtractionStartResponse:
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
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Glossary extraction is already running for this book.",
        )

    background.add_task(
        glossary_service.extract_book_glossary,
        book_id=book_id,
        settings=settings,
        continue_extraction=True,
    )
    log.info("glossary_extraction_continue_scheduled", book_id=str(book_id))
    return GlossaryExtractionStartResponse(book_id=book_id)


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
    if result.rowcount == 0:
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


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await book_service.delete_book(session, book_id)
    except NoResultFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        ) from exc
