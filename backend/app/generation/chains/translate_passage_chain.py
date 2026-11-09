"""LLM chain: translate one selected passage with full glossary context.

One call per selected passage. Runs after passage selection completes.

This is the THIRD of three chains in the voice pipeline:

1. **extract_voices_chain** — produces voice metadata + candidate pool.
2. **select_passages_chain** — picks N passages per character.
3. **translate_passage_chain** (this) — translates each selected passage.

Model choice
------------
Translation is the chain that benefits most from a more capable model.
It runs on the voices step's model (``VOICES_MODEL``, chosen per run in
the app), like the rest of Pass 2: ~50-80 calls per book, each producing
a few hundred tokens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langfuse import observe

from app.constants.languages import language_name
from app.generation.prompt_manager.models.translate_passage_model import (
    GlossaryTermRef,
    PassageTranslation,
)
from app.generation.prompt_manager.prompts.translate_passage_prompt import (
    PROMPT,
    VOICE_GUIDE_BRIEF,
    VOICE_GUIDE_PROFILE,
    render_glossary_block,
    render_voice_block,
)
from app.generation.providers.router import generate_structured, parse_result

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
    voice_brief: str | None = None,
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
    guide = (VOICE_GUIDE_BRIEF if voice_brief else VOICE_GUIDE_PROFILE).format(
        source_language=language_name(source_language), target_language=target_language
    )
    rendered = PROMPT.format(
        source_language=language_name(source_language),
        target_language=target_language,
        profile_id=profile_id,
        canonical_name=canonical_name,
        voice_guide=guide,
        voice_block=render_voice_block(
            observation=source_voice_observation,
            strategy=target_voice_strategy,
            brief=voice_brief,
        ),
        n_terms=len(glossary_terms),
        glossary_block=render_glossary_block(glossary_terms),
        selected_passage_id=selected_passage_id,
        passage_source_text=passage_source_text,
    )

    # Part of the voices step, so it runs on the voices model. (It used to
    # send TRANSLATION_MODEL to Gemini, which fails for gpt-… models.)
    result = await generate_structured(
        prompt=rendered,
        schema=PassageTranslation,
        model=settings.VOICES_MODEL,
        settings=settings,
        # Translation wants faithfulness and consistency. 0.3 is the
        # same value used elsewhere in the pipeline; kept here for
        # reliability over creative variation. If you switch to a
        # better model and want slightly more literary flexibility,
        # 0.4-0.5 is reasonable — but not higher.
        temperature=0.3,
        thinking=settings.STEP_THINKING,
        max_output_tokens=_TRANSLATE_MAX_OUTPUT_TOKENS,
        service_tier=settings.OPENAI_BACKGROUND_SERVICE_TIER,
    )
    return parse_result(result, PassageTranslation, f"passage translation {selected_passage_id}")
