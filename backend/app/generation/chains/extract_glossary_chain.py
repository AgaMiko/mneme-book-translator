"""LLM chain: extract a glossary delta from one window of manuscript text.

Iterative chain — one call per window. Caller is responsible for windowing
the manuscript, persisting the delta, and feeding the next call's
``current_glossary`` and ``previous_notepad``.

Layering
--------
- Schema   ``prompt_manager/models/extract_glossary_model.py`` — the contract
- Prompt   ``prompt_manager/prompts/extract_glossary_prompt.py`` — task framing
- Provider ``providers/router.py`` — Gemini or OpenAI, by model (``GLOSSARY_MODEL``)

Observability
-------------
Wrapped with ``@observe`` so each window's call appears as a generation in
Langfuse. When ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` are unset
the decorator is a no-op.

For multi-window traces, the caller should set the Langfuse session_id to
``book_id`` so all windows of a book group together in the dashboard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langfuse import observe

from app.generation.prompt_manager.models.extract_glossary_model import (
    GlossaryEntryCompact,
    GlossaryUpdate,
)
from app.generation.prompt_manager.prompts.extract_glossary_prompt import (
    FIRST_PASS_NOTE,
    PROMPT,
    render_glossary_table,
    render_notepad,
)
from app.generation.providers.router import generate_structured, parse_result

if TYPE_CHECKING:
    from app.core.config import Settings


@observe(name="extract_glossary_window", as_type="generation")
async def extract_glossary_window(
    *,
    window_text: str,
    current_glossary: list[GlossaryEntryCompact],
    previous_notepad: list[str],
    window_number: int,
    total_windows: int,
    source_language: str,
    target_language: str,
    settings: Settings,
) -> GlossaryUpdate:
    """Run one extraction pass over a window of text.

    Returns a delta — the caller applies it to the persisted glossary
    and threads the resulting state into the next call.

    The chain itself is stateless. All iteration state lives in the
    arguments: ``current_glossary`` and ``previous_notepad`` come from
    whatever the previous call returned (or empty lists for window 1).
    """
    is_first_pass = window_number == 1

    rendered = PROMPT.format(
        first_pass_note=FIRST_PASS_NOTE if is_first_pass else "",
        window_number=window_number,
        total_windows=total_windows,
        n_entries=len(current_glossary),
        glossary_table=render_glossary_table(current_glossary),
        notepad=render_notepad(previous_notepad),
        window_text=window_text,
        source_language=source_language,
        target_language=target_language,
    )

    result = await generate_structured(
        prompt=rendered,
        schema=GlossaryUpdate,
        model=settings.GLOSSARY_MODEL,
        settings=settings,
        # Slightly higher than metadata extraction — glossary work benefits
        # from a touch of variation when reasoning about edge cases.
        # Still well below creative-writing temperatures. (Reasoning models
        # ignore temperature when a thinking level is set.)
        temperature=0.9,
        thinking=settings.STEP_THINKING,
        service_tier=settings.OPENAI_BACKGROUND_SERVICE_TIER,
    )
    return parse_result(result, GlossaryUpdate, f"glossary window {window_number}")
