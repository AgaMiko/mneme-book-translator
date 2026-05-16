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

from typing import TYPE_CHECKING

from langfuse import observe

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

if TYPE_CHECKING:
    from app.core.config import Settings


# Pass 1 outputs are short — a list of speakers with one quote each
# plus an optional one-line notepad. 8k tokens is comfortable
# headroom; we still pay only for what's generated.
_IDENTIFY_SPEAKERS_MAX_OUTPUT_TOKENS = 8_192


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
    """
    rendered = PROMPT.format(
        window_number=window_number,
        total_windows=total_windows,
        n_characters=len(glossary_characters),
        glossary_characters_table=render_glossary_characters_table(glossary_characters),
        notepad=render_notepad(previous_notepad),
        window_text=window_text,
        source_language=source_language,
    )

    # Temperature 0.1 — Pass 1 is a near-deterministic attribution
    # task. Slight room for the model to break attribution ties when
    # context is genuinely ambiguous, but lower than voice extraction
    # (0.3) which benefits from expressive room in the voice fields.
    response = await gemini_generate(
        prompt=rendered,
        schema=SpeakersInWindow,
        model=settings.GEMINI_MODEL,
        settings=settings,
        temperature=0.1,
        max_output_tokens=_IDENTIFY_SPEAKERS_MAX_OUTPUT_TOKENS,
    )

    if isinstance(response.parsed, SpeakersInWindow):
        return response.parsed
    if response.text:
        return SpeakersInWindow.model_validate_json(response.text)
    raise RuntimeError(
        f"Gemini returned an empty speakers response for window {window_number}."
    )
