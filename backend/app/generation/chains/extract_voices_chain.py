"""LLM chain: extract a voice-profile delta from one window of manuscript text.

Iterative chain — one call per window. Caller is responsible for
windowing the manuscript, persisting each delta, and feeding the next
call's ``current_profiles`` and ``previous_notepad``.

This is the FIRST of three chains in the voice pipeline:

1. **extract_voices_chain** (this) — produces voice metadata + candidate
   passage pool. NO translation.
2. **select_passages_chain** — runs after extraction completes, picks
   1-4 final passages per character based on glossary mention percentile.
3. **translate_passage_chain** — runs per selected passage with full
   accepted glossary in context.

Layering
--------
- Schema   ``prompt_manager/models/extract_voices_model.py`` — contract
- Prompt   ``prompt_manager/prompts/extract_voices_prompt.py`` — task framing
- Provider ``providers/gemini.py`` — vendor SDK + retry/backoff

Precondition
------------
Voice extraction requires a completed glossary with at least one
character entry. Service code enforces this; the chain trusts that
``glossary_characters`` is populated correctly.
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
    REGENERATION_NOTE,
    SPEAKER_SCOPE_NOTE,
    render_glossary_characters_table,
    render_notepad,
    render_voice_profiles_table,
)
from app.generation.providers.gemini import generate as gemini_generate

if TYPE_CHECKING:
    from app.core.config import Settings

# Voice extraction with candidate pools produces somewhat larger JSON
# than the previous one-passage-per-character design — each profile can
# carry up to 8 candidate passages worth of source_text + reasoning.
# 32k output tokens gives comfortable headroom; we still pay only for
# what's generated.
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
    speakers_scoped: bool = False,
    regeneration_pass: bool = False,
) -> VoiceUpdate:
    """Run one voice-extraction pass over a window of text.

    Returns a delta — the caller applies it to persisted profiles and
    threads the resulting state into the next call.

    The chain is stateless. All iteration state lives in the arguments:
    ``current_profiles`` and ``previous_notepad`` come from whatever
    the previous call returned (or empty lists for window 1).
    """
    is_first_pass = window_number == 1 and not regeneration_pass

    rendered = PROMPT.format(
        first_pass_note=FIRST_PASS_NOTE if is_first_pass else "",
        speaker_scope_note=SPEAKER_SCOPE_NOTE if speakers_scoped else "",
        regeneration_note=REGENERATION_NOTE if regeneration_pass else "",
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

    # Temperature 0.3 — same reasoning as previous revision. Voice work
    # benefits from some expressive room in the voice fields, but not at
    # the cost of structured output reliability. The new schema
    # explicitly tells the model not to translate during this phase, so
    # the fail-into-creative-translation pressure is gone — this chain
    # is now pure structured extraction.
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
    raise RuntimeError(f"Gemini returned an empty voice response for window {window_number}.")
