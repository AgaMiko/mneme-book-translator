"""LLM chain: decide a batch of pending glossary terms like the author would.

One call per batch of pending terms. The caller picks the terms, finds the
passages, applies the decisions and records them for the author to check.

Layering
--------
- Schema   ``prompt_manager/models/review_glossary_model.py`` — the contract
- Prompt   ``prompt_manager/prompts/review_glossary_prompt.py`` — task framing
- Provider ``providers/gemini.py`` — vendor SDK + retry/backoff
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langfuse import observe

from app.generation.prompt_manager.models.review_glossary_model import GlossaryReview
from app.generation.prompt_manager.prompts.review_glossary_prompt import (
    PROMPT,
    PromptTerm,
    render_accepted,
    render_pending,
    render_removed,
)
from app.generation.providers.gemini import generate as gemini_generate

if TYPE_CHECKING:
    from app.core.config import Settings


def review_model(settings: Settings) -> str:
    return settings.GLOSSARY_REVIEW_MODEL or settings.GEMINI_MODEL


@observe(name="review_glossary_batch", as_type="generation")
async def review_glossary_batch(
    *,
    pending: list[PromptTerm],
    accepted: list[PromptTerm],
    removed: list[PromptTerm],
    source_language: str,
    target_language: str,
    settings: Settings,
) -> GlossaryReview:
    rendered = PROMPT.format(
        source_language=source_language,
        target_language=target_language,
        n_pending=len(pending),
        pending_block=render_pending(pending),
        n_accepted=len(accepted),
        accepted_block=render_accepted(accepted),
        n_removed=len(removed),
        removed_block=render_removed(removed),
    )
    response = await gemini_generate(
        prompt=rendered,
        schema=GlossaryReview,
        model=review_model(settings),
        settings=settings,
        # A judgement task: keep it steady between runs.
        temperature=0.2,
        thinking_level=settings.GLOSSARY_REVIEW_THINKING,
        max_output_tokens=None,
    )
    if isinstance(response.parsed, GlossaryReview):
        return response.parsed
    if response.text:
        return GlossaryReview.model_validate_json(response.text)
    raise RuntimeError("Gemini returned an empty glossary review.")
