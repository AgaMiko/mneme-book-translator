"""LLM chain: build voice profiles from all of a character's lines.

One call per unit: a character with enough lines, or a group of
characters with only a few each. The caller renders the lines
(``services.voice_profiles.render_unit``), validates the result and
stores it (``services.voice_build_service``).

Layering
--------
- Schema   ``prompt_manager/models/build_voice_profile_model.py`` — contract
- Prompt   ``prompt_manager/prompts/build_voice_profile_prompt.py`` — task framing
- Provider ``providers/router.py`` — vendor SDK + retry/backoff
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langfuse import observe

from app.constants.languages import language_name
from app.core.logging import get_logger
from app.generation.prompt_manager.models.build_voice_profile_model import VoiceProfiles
from app.generation.prompt_manager.prompts.build_voice_profile_prompt import (
    PROMPT,
    THOUGHTS_NOTE,
    THOUGHTS_NOTE_NONE,
)
from app.generation.providers.router import generate_structured, parse_result

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

# A profile with features, two fields and passages is a few thousand
# tokens; a group of eight small characters is the largest output.
_BUILD_VOICE_MAX_OUTPUT_TOKENS = 32_768
_PARSE_ATTEMPTS = 2


@observe(name="build_voice_profiles", as_type="generation")
async def build_voice_profiles(
    *,
    characters_section: str,
    who: str,
    has_thoughts: bool,
    source_language: str,
    target_language: str,
    settings: Settings,
) -> VoiceProfiles:
    """Profiles for the characters in ``characters_section``.

    Raises ``ValueError`` when no parseable output comes back after
    retries; the caller leaves the unit for Continue.
    """
    rendered = PROMPT.format(
        source_language=language_name(source_language),
        target_language=target_language,
        who=who,
        thoughts_note=THOUGHTS_NOTE if has_thoughts else THOUGHTS_NOTE_NONE,
        characters_section=characters_section,
    )
    last: Exception | None = None
    for attempt in range(_PARSE_ATTEMPTS):
        # Temperature 0.3: some room in the voice fields, as before.
        result = await generate_structured(
            prompt=rendered,
            schema=VoiceProfiles,
            model=settings.VOICES_MODEL,
            settings=settings,
            temperature=0.3,
            thinking=settings.STEP_THINKING,
            max_output_tokens=_BUILD_VOICE_MAX_OUTPUT_TOKENS,
            service_tier=settings.OPENAI_BACKGROUND_SERVICE_TIER,
        )
        try:
            return parse_result(result, VoiceProfiles, f"voice profiles for {who}")
        except (ValueError, RuntimeError) as exc:
            last = exc
            log.warning(
                "voice_profile_parse_attempt_failed",
                who=who,
                attempt=attempt + 1,
                detail=str(exc)[:600],
            )
            if attempt + 1 < _PARSE_ATTEMPTS:
                await asyncio.sleep(2.0)
    raise ValueError(f"No usable voice profile output for {who}: {last}")
