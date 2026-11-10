"""LLM chain: select N final reference passages from a character's candidate pool.

One call per character. Runs after voice extraction completes.

This is the SECOND of three chains in the voice pipeline:

1. **extract_voices_chain** — produces voice metadata + candidate pool.
2. **select_passages_chain** (this) — picks N passages per character.
3. **translate_passage_chain** — translates each selected passage.

The passage count N is determined code-side from the character's
glossary occurrence_count percentile within this book. See
``services/voice_service.py::compute_passage_counts`` for the math.
This chain just receives the count as a parameter.

Why a separate chain
--------------------
Selection is a different cognitive task than extraction. Extraction
sees one window at a time and contributes candidates; selection sees
the whole pool at once and reasons across it. The prompts are
different, the optimization targets are different.

Cheap model is fine. Selection is reasoning over already-collected
data; it doesn't need the literary attention that translation requires.
Flash Lite handles this well.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langfuse import observe

from app.constants.languages import language_name
from app.generation.prompt_manager.models.select_passages_model import (
    CandidateInPool,
    PassageSelection,
)
from app.generation.prompt_manager.prompts.select_passages_prompt import (
    PROMPT,
    render_candidate_pool,
)
from app.generation.providers.router import generate_structured, parse_result

if TYPE_CHECKING:
    from app.core.config import Settings

# Selection produces small JSON — at most 4 selected passages per call,
# each with reasoning. 8k output tokens is plenty.
_SELECT_MAX_OUTPUT_TOKENS = 8_192


@observe(name="select_passages_for_character", as_type="generation")
async def select_passages_for_character(
    *,
    profile_id: str,
    canonical_name: str,
    source_voice_observation: str,
    target_voice_strategy: str,
    candidates: list[CandidateInPool],
    passage_count: int,
    source_language: str,
    target_language: str,
    settings: Settings,
) -> PassageSelection:
    """Pick the final reference passages for one character.

    ``passage_count`` comes from the percentile-based math in the
    service layer. The chain trusts it — if the caller asks for 3,
    the chain returns 3 (or fewer, if the pool has fewer entries).

    For multi-character runs the caller should set Langfuse
    ``session_id=str(book_id)`` so all selection calls for a book
    group together with the extraction calls.
    """
    rendered = PROMPT.format(
        source_language=language_name(source_language),
        target_language=target_language,
        profile_id=profile_id,
        canonical_name=canonical_name,
        source_voice_observation=source_voice_observation,
        target_voice_strategy=target_voice_strategy,
        n_candidates=len(candidates),
        passage_count=passage_count,
        candidate_pool_block=render_candidate_pool(candidates),
    )

    result = await generate_structured(
        prompt=rendered,
        schema=PassageSelection,
        model=settings.VOICES_MODEL,
        settings=settings,
        # Selection is structured reasoning over fixed inputs. Lower
        # temperature is better — same passages should be picked
        # consistently across reruns of the same pool.
        temperature=0.2,
        thinking=settings.STEP_THINKING,
        max_output_tokens=_SELECT_MAX_OUTPUT_TOKENS,
        service_tier=settings.OPENAI_BACKGROUND_SERVICE_TIER,
    )
    return parse_result(result, PassageSelection, f"passage selection for {canonical_name!r}")
