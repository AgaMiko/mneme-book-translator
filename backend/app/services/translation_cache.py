"""Explicit Gemini caches for one translation run.

Every translation call starts with the same fixed context (rules, style
sheet, glossary; about 8,000 tokens for *Zaplataczka*). A run uploads it
once per model as an explicit cache, and each call points at the cache
instead of sending the text again. Cached tokens cost about 10% of normal
input; storage costs about $1 per million tokens per hour, which is cents
for one run.

Clean-up, so a cache never keeps costing money after its run:

1. ``RunCaches.close`` deletes the caches when the run ends: finished,
   failed or stopped (``run_translation`` calls it in ``finally``).
2. Each cache expires on its own after ``CACHE_TTL_S`` unless refreshed;
   a background task refreshes it every ``REFRESH_EVERY_S`` while the run
   is alive. If the server dies, the cache is gone within the hour.
3. On server start, ``delete_leftover_caches`` removes every cache whose
   name starts with ``CACHE_NAME_PREFIX`` (no run survives a restart).

If a cache cannot be created (model without caching, prefix too short,
quota), the run continues without it; the prompt order still lets Gemini's
automatic prefix caching apply.

OpenAI models get no explicit cache to manage: ``open`` only prewarms
OpenAI's own prefix cache (see ``providers/openai.py``), which expires by
itself after 30 minutes.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.generation.providers.gemini import (
    create_cache,
    delete_cache,
    delete_caches_with_prefix,
    refresh_cache,
)
from app.generation.providers.openai import is_openai_model, prewarm_cache

if TYPE_CHECKING:
    from uuid import UUID

    from app.core.config import Settings

log = get_logger(__name__)

CACHE_NAME_PREFIX = "mneme-translation-"
CACHE_TTL_S = 3600
REFRESH_EVERY_S = 900


class RunCaches:
    """The caches of one run, one per model, with refresh and clean-up."""

    def __init__(self, settings: Settings, names: dict[str, str]) -> None:
        self._settings = settings
        self._names = names  # model -> cache name
        self._refresher: asyncio.Task[None] | None = None
        if names:
            self._refresher = asyncio.create_task(self._refresh_loop())

    @classmethod
    async def open(
        cls, *, settings: Settings, run_id: UUID, fixed_context: str, models: set[str]
    ) -> RunCaches:
        names: dict[str, str] = {}
        if settings.TRANSLATION_CACHE:
            # OpenAI: write the prefix cache once so the first parallel calls
            # already read from it. It expires on its own; nothing to delete.
            for model in sorted(m for m in models if is_openai_model(m)):
                try:
                    await prewarm_cache(settings=settings, model=model, prefix=fixed_context)
                    log.info("translation_cache_prewarmed", run_id=str(run_id), model=model)
                except Exception as exc:
                    log.warning(
                        "translation_cache_prewarm_failed",
                        run_id=str(run_id),
                        model=model,
                        error=f"{type(exc).__name__}: {exc}"[:500],
                    )
            # Gemini: an explicit cache per model, deleted when the run ends.
            for model in sorted(m for m in models if not is_openai_model(m)):
                try:
                    names[model] = await create_cache(
                        settings=settings,
                        model=model,
                        text=fixed_context,
                        display_name=f"{CACHE_NAME_PREFIX}{run_id}",
                        ttl_s=CACHE_TTL_S,
                    )
                    log.info("translation_cache_created", run_id=str(run_id), model=model)
                except Exception as exc:
                    log.warning(
                        "translation_cache_unavailable",
                        run_id=str(run_id),
                        model=model,
                        error=f"{type(exc).__name__}: {exc}"[:500],
                    )
        return cls(settings, names)

    def name_for(self, model: str) -> str | None:
        return self._names.get(model)

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(REFRESH_EVERY_S)
            for name in self._names.values():
                try:
                    await refresh_cache(settings=self._settings, name=name, ttl_s=CACHE_TTL_S)
                except Exception as exc:
                    log.warning("translation_cache_refresh_failed", name=name, error=str(exc))

    async def close(self) -> None:
        if self._refresher is not None:
            self._refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresher
        for model, name in self._names.items():
            try:
                await delete_cache(settings=self._settings, name=name)
                log.info("translation_cache_deleted", model=model)
            except Exception as exc:
                # It still expires on its own within CACHE_TTL_S.
                log.warning("translation_cache_delete_failed", name=name, error=str(exc))
        self._names = {}


async def delete_leftover_caches(settings: Settings) -> None:
    """Startup clean-up: remove caches of runs a dead process left behind."""
    try:
        n = await delete_caches_with_prefix(settings=settings, prefix=CACHE_NAME_PREFIX)
    except Exception as exc:
        log.warning("translation_cache_cleanup_failed", error=str(exc))
        return
    if n:
        log.info("translation_caches_cleaned_up", count=n)
