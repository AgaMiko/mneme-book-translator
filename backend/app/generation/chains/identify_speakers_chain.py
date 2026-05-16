"""LLM chain: identify which glossary characters speak in one window.

Pass 1 of the voice pipeline. One call per window; iterative across
the manuscript with a one-note notepad threading state forward.

Layering (mirrors extract_voices_chain)
---------------------------------------
- Schema   ``prompt_manager/models/identify_speakers_model.py`` — contract
- Prompt   ``prompt_manager/prompts/identify_speakers_prompt.py`` — task framing
- Provider ``providers/gemini.py`` — vendor SDK + retry/backoff

Precondition
------------
Pass 1 requires a completed glossary with at least one character
entry. Service code enforces this; the chain trusts that
``glossary_characters`` is populated correctly.

Why not folded into voice extraction
------------------------------------
Splitting "who spoke here" from "what's their voice" gives the model
one cognitive job per call, with grounded output (every claimed
speaker carries a verbatim quote). Pass 2 then receives a
known-narrow candidate pool, which tightens its grounding too.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langfuse import observe

from app.core.logging import get_logger
from app.generation.prompt_manager.models.identify_speakers_model import (
    GlossaryCharacterRef,
    SpeakerNote,
    SpeakersInWindow,
)
from app.generation.prompt_manager.prompts.identify_speakers_prompt import (
    PROMPT,
    render_glossary_characters_table,
    render_notepad,
)
from app.generation.providers.gemini import generate as gemini_generate
from app.generation.structured_output import EmptyGeminiResponseError, parse_gemini_model

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

_IDENTIFY_SPEAKERS_MAX_OUTPUT_TOKENS = 8_192
_PARSE_ATTEMPTS = 3


def _empty_window_fallback(
    *,
    window_number: int,
    previous_notepad: list[SpeakerNote],
    detail: str,
) -> SpeakersInWindow:
    """Continue the run without speakers for this window."""
    log.warning(
        "speakers_window_empty_fallback",
        window_number=window_number,
        detail=detail,
    )
    return SpeakersInWindow(
        window_summary=f"(no model output for window {window_number})",
        speakers=[],
        notepad=previous_notepad[:1],
    )


@observe(name="identify_speakers_window", as_type="generation")
async def identify_speakers_window(
    *,
    window_text: str,
    glossary_characters: list[GlossaryCharacterRef],
    previous_notepad: list[SpeakerNote],
    window_number: int,
    total_windows: int,
    source_language: str,
    settings: Settings,
) -> SpeakersInWindow:
    """Run one speaker-identification pass over a window of text.

    Returns the window's speakers and an optional one-note notepad.
    The chain is stateless — all iteration state lives in
    ``previous_notepad``, which the caller threads forward from the
    previous call (or an empty list for window 1).

    If Gemini returns no parseable JSON after several attempts, returns
    an empty speaker list for this window so a single bad window does
    not abort a 200+ window run. The notepad is carried forward unchanged.
    """
    if len(window_text) > 80_000:
        log.warning(
            "speakers_window_text_large",
            window_number=window_number,
            chars=len(window_text),
        )

    rendered = PROMPT.format(
        window_number=window_number,
        total_windows=total_windows,
        n_characters=len(glossary_characters),
        glossary_characters_table=render_glossary_characters_table(glossary_characters),
        notepad=render_notepad(previous_notepad),
        window_text=window_text,
        source_language=source_language,
    )

    last_detail = ""
    for attempt in range(_PARSE_ATTEMPTS):
        response = await gemini_generate(
            prompt=rendered,
            schema=SpeakersInWindow,
            model=settings.GEMINI_MODEL,
            settings=settings,
            temperature=0.1,
            max_output_tokens=_IDENTIFY_SPEAKERS_MAX_OUTPUT_TOKENS,
        )
        try:
            return parse_gemini_model(response, SpeakersInWindow)
        except EmptyGeminiResponseError as exc:
            last_detail = exc.detail
            log.warning(
                "speakers_parse_attempt_failed",
                window_number=window_number,
                attempt=attempt + 1,
                detail=last_detail,
            )
            if attempt + 1 < _PARSE_ATTEMPTS:
                await asyncio.sleep(1.5 * (attempt + 1))

    return _empty_window_fallback(
        window_number=window_number,
        previous_notepad=previous_notepad,
        detail=last_detail,
    )
