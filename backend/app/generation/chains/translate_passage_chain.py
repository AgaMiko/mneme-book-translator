"""LLM chain: translate one selected passage with full glossary context.

One call per selected passage. Runs after passage selection completes.

This is the THIRD of three chains in the voice pipeline:

1. **extract_voices_chain** — produces voice metadata + candidate pool.
2. **select_passages_chain** — picks N passages per character.
3. **translate_passage_chain** (this) — translates each selected passage.

Model choice
------------
Translation is the chain that benefits most from a more capable model.
This chain reads the model name from settings — by default Flash Lite
to start, but bumping to Gemini Pro (or Claude, if you wire that up
later) is a one-line settings change. The cost increase is real but
bounded: ~50-80 calls per book, each producing a few hundred tokens.

The settings field is intentionally distinct from the extraction
settings.GEMINI_MODEL — extraction wants cheap and fast, translation
wants careful. Two separate model knobs let each be tuned independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langfuse import observe

from app.generation.prompt_manager.models.translate_passage_model import (
    GlossaryTermRef,
    PassageTranslation,
)
from app.generation.prompt_manager.prompts.translate_passage_prompt import (
    PROMPT,
    render_glossary_block,
)
from app.generation.providers.gemini import generate as gemini_generate

if TYPE_CHECKING:
    from app.core.config import Settings

# Translation output: one passage's worth of target-language prose plus
# brief reasoning. Comfortably fits in 4k tokens. Set to 8k for headroom.
_TRANSLATE_MAX_OUTPUT_TOKENS = 8_192


@observe(name="translate_passage", as_type="generation")
async def translate_passage(
    *,
    selected_passage_id: str,
    profile_id: str,
    canonical_name: str,
    source_voice_observation: str,
    target_voice_strategy: str,
    passage_source_text: str,
    glossary_terms: list[GlossaryTermRef],
    source_language: str,
    target_language: str,
    settings: Settings,
) -> PassageTranslation:
    """Translate one selected passage.

    Per-passage isolation: failures here affect only this passage. The
    caller (voice_service) loops over selected passages and calls this
    once each. If translation produces ~80 calls per book, distributing
    them as one-per-call rather than batched per-character keeps
    failure granularity tight.

    Set Langfuse ``session_id=str(book_id)`` so all translations for a
    book group together with their extraction and selection calls.
    """
    rendered = PROMPT.format(
        source_language=source_language,
        target_language=target_language,
        profile_id=profile_id,
        canonical_name=canonical_name,
        source_voice_observation=source_voice_observation,
        target_voice_strategy=target_voice_strategy,
        n_terms=len(glossary_terms),
        glossary_block=render_glossary_block(glossary_terms),
        selected_passage_id=selected_passage_id,
        passage_source_text=passage_source_text,
    )

    # Translation model is configured separately from extraction.
    # Default behavior: fall back to GEMINI_MODEL if no dedicated
    # translation model is set. Once you have a Pro / Claude credential
    # wired in, set settings.TRANSLATION_MODEL and this chain picks it
    # up automatically.
    model = getattr(settings, "TRANSLATION_MODEL", None) or settings.GEMINI_MODEL

    response = await gemini_generate(
        prompt=rendered,
        schema=PassageTranslation,
        model=model,
        settings=settings,
        # Translation wants faithfulness and consistency. 0.3 is the
        # same value used elsewhere in the pipeline; kept here for
        # reliability over creative variation. If you switch to a
        # better model and want slightly more literary flexibility,
        # 0.4-0.5 is reasonable — but not higher.
        temperature=0.3,
        max_output_tokens=_TRANSLATE_MAX_OUTPUT_TOKENS,
    )

    if isinstance(response.parsed, PassageTranslation):
        return response.parsed
    if response.text:
        return PassageTranslation.model_validate_json(response.text)
    raise RuntimeError(f"Translation returned empty for selected_passage_id={selected_passage_id}.")
