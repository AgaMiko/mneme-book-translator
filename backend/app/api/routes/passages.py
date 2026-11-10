"""Special passages and their flags (Step 6).

- ``GET   /books/{id}/passages`` — passages, their text and flags, run state.
- ``POST  /books/{id}/passages/scan`` — find passages in the manuscript.
- ``POST  /books/{id}/passages/check`` — check translated passages and
  correct the ones that break their rule (``?passage_id=…`` for one).
- ``POST  /books/{id}/passages`` — the author marks a passage by hand.
- ``PATCH /books/{id}/passages/{passage_id}`` — the author changes the rule
  or the target message; the passage is checked again at the next check.
- ``POST  /books/{id}/passages/{passage_id}/resolve`` — accept, restore the
  first translation, use another version, edit, or dismiss.

Scan and check run as ``asyncio`` tasks, like translation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID  # noqa: TC003 - FastAPI resolves path params at runtime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.generation.providers.openai import is_openai_model
from app.models.passages import SpecialPassage
from app.schemas.passages import (
    CreatePassageIn,
    PassagesViewResponse,
    ResolvePassageIn,
    UpdatePassageIn,
)
from app.services import special_passages_service as service
from app.services.special_passages_service import PassageConflictError

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/books", tags=["passages"])

log = get_logger(__name__)

# Keep references so running tasks are not garbage-collected.
_RUNNING_TASKS: set[asyncio.Task[None]] = set()


def _schedule(coro: Coroutine[Any, Any, None], book_id: UUID) -> None:
    async def run() -> None:
        try:
            await coro
        except Exception as exc:
            log.exception("passages_background_unhandled", book_id=str(book_id))
            await service._set_state(book_id, status="failed", error=str(exc))

    task = asyncio.create_task(run())
    _RUNNING_TASKS.add(task)
    task.add_done_callback(_RUNNING_TASKS.discard)


def _require_key(settings: Settings) -> None:
    openai = is_openai_model(settings.PASSAGES_MODEL)
    if openai and not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured (needed for the passages model).",
        )
    if not openai and not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )


async def _view(session: AsyncSession, book_id: UUID) -> PassagesViewResponse:
    try:
        view = await service.build_view(session, book_id=book_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PassagesViewResponse.model_validate(view)


async def _claim(session: AsyncSession, book_id: UUID, state: str) -> None:
    try:
        await service.claim(session, book_id=book_id, status=state)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PassageConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


async def _passage(session: AsyncSession, book_id: UUID, passage_id: UUID) -> SpecialPassage:
    passage = await session.get(SpecialPassage, passage_id)
    if passage is None or passage.book_id != book_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passage not found")
    return passage


@router.get(
    "/{book_id}/passages",
    response_model=PassagesViewResponse,
    summary="Special passages with their text, checks and flags",
)
async def get_passages(
    book_id: UUID, session: AsyncSession = Depends(get_session)
) -> PassagesViewResponse:
    return await _view(session, book_id)


@router.post(
    "/{book_id}/passages/scan",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PassagesViewResponse,
    summary="Find special passages in the manuscript (background)",
)
async def scan_passages(
    book_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PassagesViewResponse:
    _require_key(settings)
    await _claim(session, book_id, "scanning")
    _schedule(service.scan_book(book_id=book_id, settings=settings), book_id)
    return await _view(session, book_id)


@router.post(
    "/{book_id}/passages/check",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PassagesViewResponse,
    summary="Check translated passages and correct the ones that break their rule (background)",
)
async def check_passages(
    book_id: UUID,
    passage_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PassagesViewResponse:
    _require_key(settings)
    if passage_id is not None:
        await _passage(session, book_id, passage_id)
    await _claim(session, book_id, "checking")
    _schedule(
        service.check_book(book_id=book_id, settings=settings, passage_id=passage_id), book_id
    )
    return await _view(session, book_id)


@router.post(
    "/{book_id}/passages",
    status_code=status.HTTP_201_CREATED,
    response_model=PassagesViewResponse,
    summary="Mark a run of paragraphs as a special passage",
)
async def create_passage(
    book_id: UUID, body: CreatePassageIn, session: AsyncSession = Depends(get_session)
) -> PassagesViewResponse:
    try:
        await service.create_passage(
            session,
            book_id=book_id,
            first_paragraph_id=body.first_paragraph_id,
            last_paragraph_id=body.last_paragraph_id,
            kind=body.kind,
            rule=body.rule,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PassageConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _view(session, book_id)


@router.patch(
    "/{book_id}/passages/{passage_id}",
    response_model=PassagesViewResponse,
    summary="Change a passage's rule or target message",
)
async def update_passage(
    book_id: UUID,
    passage_id: UUID,
    body: UpdatePassageIn,
    session: AsyncSession = Depends(get_session),
) -> PassagesViewResponse:
    await _passage(session, book_id, passage_id)
    await service.update_rule(
        session, passage_id=passage_id, rule=body.rule, target_message=body.target_message
    )
    return await _view(session, book_id)


@router.post(
    "/{book_id}/passages/{passage_id}/resolve",
    response_model=PassagesViewResponse,
    summary="Answer a passage's flag: accept, restore, use another version, edit or dismiss",
)
async def resolve_passage(
    book_id: UUID,
    passage_id: UUID,
    body: ResolvePassageIn,
    session: AsyncSession = Depends(get_session),
) -> PassagesViewResponse:
    await _passage(session, book_id, passage_id)
    try:
        await service.resolve_passage(
            session,
            passage_id=passage_id,
            action=body.action,
            candidate=body.candidate,
            paragraphs=[p.model_dump() for p in body.paragraphs],
        )
    except PassageConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _view(session, book_id)
