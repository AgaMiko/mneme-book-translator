"""LLM chain: extract a voice-profile delta from one window of manuscript text.

Iterative chain — one call per window. Caller is responsible for
windowing the manuscript, persisting each delta, and feeding the next
call's ``current_profiles`` and ``previous_notepad``.

Layering
--------
- Schema   ``prompt_manager/models/extract_voices_model.py`` — the contract
- Prompt   ``prompt_manager/prompts/extract_voices_prompt.py`` — task framing
- Provider ``providers/gemini.py`` — vendor SDK + retry/backoff

Precondition
------------
Voice extraction requires a completed glossary with at least one
character entry. Service code enforces this; the chain itself trusts
that ``glossary_characters`` is populated correctly.

Observability
-------------
Wrapped with ``@observe`` so each window's call appears as a generation
in Langfuse. For multi-window traces, callers should set
``session_id=str(book_id)`` so all windows of a book group together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langfuse import observe

from app.generation.prompt_manager.models.extract_voices_model import (
    CharacterVoiceCompact,
    GlossaryCharacterRef,
    VoiceNote,
    VoiceUpdate,
)
from app.generation.prompt_manager.prompts.extract_voices_prompt import (
    FIRST_PASS_NOTE,
    PROMPT,
    render_glossary_characters_table,
    render_notepad,
    render_voice_profiles_table,
)
from app.generation.providers.gemini import generate as gemini_generate

if TYPE_CHECKING:
    from app.core.config import Settings

# Gemini's default 8192 output limit truncates voice JSON when the window
# has many speakers — each new profile carries a voice_summary AND a
# translated reference passage. 32k gives comfortable headroom across
# the worst-case window without bloating typical calls (we still pay only
# for what's generated).
_VOICE_EXTRACT_MAX_OUTPUT_TOKENS = 32_768


@observe(name="extract_voices_window", as_type="generation")
async def extract_voices_window(
    *,
    window_text: str,
    glossary_characters: list[GlossaryCharacterRef],
    current_profiles: list[CharacterVoiceCompact],
    previous_notepad: list[VoiceNote],
    window_number: int,
    total_windows: int,
    source_language: str,
    target_language: str,
    settings: Settings,
) -> VoiceUpdate:
    """Run one voice-extraction pass over a window of text.

    Returns a delta — the caller applies it to the persisted profiles
    and threads the resulting state into the next call.

    The chain itself is stateless. All iteration state lives in the
    arguments: ``current_profiles`` and ``previous_notepad`` come from
    whatever the previous call returned (or empty lists for window 1).
    ``glossary_characters`` is the canonical character list; voice
    profiles can only be created for characters in this list.
    """
    is_first_pass = window_number == 1

    rendered = PROMPT.format(
        first_pass_note=FIRST_PASS_NOTE if is_first_pass else "",
        window_number=window_number,
        total_windows=total_windows,
        n_characters=len(glossary_characters),
        n_profiles=len(current_profiles),
        glossary_characters_table=render_glossary_characters_table(glossary_characters),
        voice_profiles_table=render_voice_profiles_table(current_profiles),
        notepad=render_notepad(previous_notepad),
        window_text=window_text,
        source_language=source_language,
        target_language=target_language,
    )

    # Temperature is deliberately low. The previous chain ran at 0.9,
    # which produced rambly strings, JSON syntax errors, and high
    # output variance — the voice_summary needs *some* expressive
    # room (translators benefit from "exhausted-formal court speech"
    # over "formal"), but 0.9 is creative-writing territory, not
    # structured extraction. 0.3 keeps the qualitative slots
    # expressive enough while reliably producing parseable JSON. The
    # reference passage translation likewise wants faithfulness more
    # than variation — 0.3 is right for both.
    response = await gemini_generate(
        prompt=rendered,
        schema=VoiceUpdate,
        model=settings.GEMINI_MODEL,
        settings=settings,
        temperature=0.3,
        max_output_tokens=_VOICE_EXTRACT_MAX_OUTPUT_TOKENS,
    )

    if isinstance(response.parsed, VoiceUpdate):
        return response.parsed
    if response.text:
        return VoiceUpdate.model_validate_json(response.text)
    raise RuntimeError(
        f"Gemini returned an empty voice response for window {window_number}."
    )
