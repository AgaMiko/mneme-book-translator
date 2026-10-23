"""LLM chain: attribute the numbered dialogue lines of one chunk.

Pass 1 of the voice pipeline. One call per chunk of a chapter; the
caller plans the chunks, renders the text with numbered lines, and
validates and stores the result (``services.speakers_service``).

Layering
--------
- Schema   ``prompt_manager/models/identify_speakers_model.py`` — contract
- Prompt   ``prompt_manager/prompts/identify_speakers_prompt.py`` — task framing
- Provider ``providers/router.py`` — vendor SDK + retry/backoff
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langfuse import observe

from app.core.logging import get_logger
from app.generation.prompt_manager.models.identify_speakers_model import (
    ChunkAttribution,
    GlossaryCharacterRef,
)
from app.generation.prompt_manager.prompts.identify_speakers_prompt import (
    PROMPT,
    render_characters_table,
)
from app.generation.providers.router import generate_structured, parse_result

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

# About 40 output tokens per line; a dense chunk has ~150 lines.
_IDENTIFY_SPEAKERS_MAX_OUTPUT_TOKENS = 16_384
_PARSE_ATTEMPTS = 3


@observe(name="identify_speakers_chunk", as_type="generation")
async def identify_speakers_chunk(
    *,
    chunk_text: str,
    context: str,
    chapter_label: str,
    glossary_characters: list[GlossaryCharacterRef],
    chunk_number: int,
    total_chunks: int,
    source_language: str,
    settings: Settings,
) -> ChunkAttribution:
    """Attribute the numbered lines in ``chunk_text``.

    If the model returns no parseable JSON after several attempts,
    returns no attributions, so one bad chunk does not stop the run;
    its lines are stored as ``unknown``.
    """
    rendered = PROMPT.format(
        source_language=source_language,
        n_characters=len(glossary_characters),
        characters_table=render_characters_table(glossary_characters),
        context=context or "(start of chapter)",
        chapter_label=chapter_label,
        chunk_number=chunk_number,
        total_chunks=total_chunks,
        chunk_text=chunk_text,
    )

    last_detail = ""
    for attempt in range(_PARSE_ATTEMPTS):
        result = await generate_structured(
            prompt=rendered,
            schema=ChunkAttribution,
            model=settings.SPEAKERS_MODEL,
            settings=settings,
            temperature=0.1,
            thinking=settings.STEP_THINKING,
            max_output_tokens=_IDENTIFY_SPEAKERS_MAX_OUTPUT_TOKENS,
            service_tier=settings.OPENAI_BACKGROUND_SERVICE_TIER,
        )
        try:
            return parse_result(result, ChunkAttribution, f"speakers chunk {chunk_number}")
        except (ValueError, RuntimeError) as exc:
            # Empty or invalid JSON (pydantic's ValidationError is a ValueError).
            last_detail = str(exc)[:600]
            log.warning(
                "speakers_parse_attempt_failed",
                chunk_number=chunk_number,
                attempt=attempt + 1,
                detail=last_detail,
            )
            if attempt + 1 < _PARSE_ATTEMPTS:
                await asyncio.sleep(1.5 * (attempt + 1))

    log.warning("speakers_chunk_empty_fallback", chunk_number=chunk_number, detail=last_detail)
    return ChunkAttribution(scene=f"(no model output for chunk {chunk_number})", lines=[])
