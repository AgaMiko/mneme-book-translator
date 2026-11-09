"""LLM chains for the cast pass: briefs for the whole cast, then a passage check.

Each is one call per book. The caller renders the cast
(``services.voice_cast``), validates the result and stores it
(``services.voice_build_service``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langfuse import observe
from pydantic import BaseModel

from app.constants.languages import language_name
from app.core.logging import get_logger
from app.generation.prompt_manager.models.cast_voices_model import CastBriefs, PassageCheck
from app.generation.prompt_manager.prompts.cast_voices_prompt import (
    BRIEFS_PROMPT,
    CHECK_PROMPT,
)
from app.generation.providers.router import generate_structured, parse_result

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

# 25 briefs, or a dozen revised passages.
_CAST_MAX_OUTPUT_TOKENS = 32_768
_PARSE_ATTEMPTS = 2


async def _call[T: BaseModel](prompt: str, schema: type[T], label: str, settings: Settings) -> T:
    last: Exception | None = None
    for attempt in range(_PARSE_ATTEMPTS):
        result = await generate_structured(
            prompt=prompt,
            schema=schema,
            model=settings.VOICES_MODEL,
            settings=settings,
            temperature=0.3,
            thinking=settings.STEP_THINKING,
            max_output_tokens=_CAST_MAX_OUTPUT_TOKENS,
            service_tier=settings.OPENAI_BACKGROUND_SERVICE_TIER,
        )
        try:
            return parse_result(result, schema, label)
        except (ValueError, RuntimeError) as exc:
            last = exc
            log.warning("cast_parse_attempt_failed", label=label, attempt=attempt + 1)
            if attempt + 1 < _PARSE_ATTEMPTS:
                await asyncio.sleep(2.0)
    raise ValueError(f"No usable output for the {label}: {last}")


@observe(name="cast_voice_briefs", as_type="generation")
async def write_briefs(
    *, cast_section: str, source_language: str, target_language: str, settings: Settings
) -> CastBriefs:
    """Briefs for the whole cast. Raises ``ValueError`` without usable output."""
    prompt = BRIEFS_PROMPT.format(
        source_language=language_name(source_language),
        target_language=target_language,
        cast_section=cast_section,
    )
    return await _call(prompt, CastBriefs, "cast briefs", settings)


@observe(name="cast_passage_check", as_type="generation")
async def check_passages(
    *, cast_section: str, source_language: str, target_language: str, settings: Settings
) -> PassageCheck:
    """Flags on passage translations that lose the voice. Raises ``ValueError`` without output."""
    prompt = CHECK_PROMPT.format(
        source_language=language_name(source_language),
        target_language=target_language,
        cast_section=cast_section,
    )
    return await _call(prompt, PassageCheck, "passage check", settings)
