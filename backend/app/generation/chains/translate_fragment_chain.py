"""LLM chains: translate one fragment in three stages.

1. ``translate_fragment_faithful`` — complete, accurate translation.
2. ``line_edit_fragment`` — natural published-novel prose, checked against
   the source.
3. ``polish_fragment`` — final polish against measured style targets.

Each call returns a paragraph-aligned result: one paragraph per input id, in
order. If the model returns other ids, the call is repeated once with the
problem stated; a second failure raises ``FragmentAlignmentError``.

Models come from settings: ``TRANSLATION_<STAGE>_MODEL``, then
``TRANSLATION_MODEL``, then ``GEMINI_MODEL``. Models named ``gpt-…`` go to
OpenAI (``providers/openai.py``), everything else to Gemini.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langfuse import observe
from pydantic import BaseModel

from app.generation.prompt_manager.models.translate_fragment_model import (
    FaithfulFragment,
    LineEditedFragment,
    ParagraphOut,
    PolishedFragment,
)
from app.generation.prompt_manager.prompts.translate_fragment_prompt import (
    build_faithful_prompt,
    build_line_edit_prompt,
    build_one_step_prompt,
    build_polish_prompt,
    build_revision_prompt,
)
from app.generation.providers.gemini import generate as gemini_generate
from app.generation.providers.openai import ModelResult, cache_key_for, is_openai_model
from app.generation.providers.openai import generate as openai_generate

if TYPE_CHECKING:
    from app.core.config import Settings

# A 1,500-word fragment is about 3k output tokens, but the limit also counts
# thinking tokens: at "high" thinking a final edit used up 32k and the JSON
# was cut off. 65,536 is the Gemini 3.x Flash maximum.
_MAX_OUTPUT_TOKENS = 65_536
_TIMEOUT_S = 420


class FragmentAlignmentError(RuntimeError):
    """The model did not return exactly the input paragraph ids."""


@dataclass(slots=True)
class StageResult[T]:
    output: T
    model: str
    usage: dict[str, Any] | None


def stage_thinking(settings: Settings, stage: str) -> str | None:
    level = {
        "faithful": settings.TRANSLATION_THINKING_FAITHFUL,
        "line_edit": settings.TRANSLATION_THINKING_LINE_EDIT,
        "polish": settings.TRANSLATION_THINKING_POLISH,
    }.get(stage)
    return level.strip().lower() if level and level.strip() else None


def calls_per_fragment(settings: Settings) -> tuple[str, ...]:
    """The model calls each fragment gets, named by the settings they use.

    In two-step mode the second call (``line_edit`` settings) is the
    revision, and its output is stored as the final (``polish``) stage. In
    one-step mode the only call uses the ``line_edit`` settings too.
    """
    if settings.TRANSLATION_STAGE_COUNT == 1:
        return ("line_edit",)
    if settings.TRANSLATION_STAGE_COUNT == 2:
        return ("faithful", "line_edit")
    return ("faithful", "line_edit", "polish")


def stage_model(settings: Settings, stage: str) -> str:
    specific = {
        "faithful": settings.TRANSLATION_FAITHFUL_MODEL,
        "line_edit": settings.TRANSLATION_LINE_EDIT_MODEL,
        "polish": settings.TRANSLATION_POLISH_MODEL,
    }.get(stage)
    return specific or settings.TRANSLATION_MODEL or settings.GEMINI_MODEL


def _usage(response: Any) -> dict[str, Any] | None:
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return None
    keys = (
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "cached_content_token_count",
        "total_token_count",
    )
    return {k: getattr(um, k, None) for k in keys}


def _alignment_problem(paragraphs: list[ParagraphOut], expected_ids: list[str]) -> str | None:
    got = [p.paragraph_id.strip() for p in paragraphs]
    if got == expected_ids:
        return None
    missing = [i for i in expected_ids if i not in got]
    extra = [i for i in got if i not in expected_ids]
    parts = [f"expected {len(expected_ids)} paragraphs, got {len(got)}"]
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if extra:
        parts.append("unexpected: " + ", ".join(extra))
    if not missing and not extra:
        parts.append("wrong order")
    return "; ".join(parts)


async def _call_model(
    *,
    fixed_context: str,
    prompt: str,
    schema: type[BaseModel],
    model: str,
    stage: str,
    temperature: float,
    cached_content: str | None,
    settings: Settings,
) -> ModelResult:
    """Send one call to the provider that serves ``model``.

    ``prompt`` is everything after the fixed context. OpenAI gets the fixed
    context as a separate, cacheable block; Gemini gets it in front of the
    prompt, or not at all when an explicit cache (``cached_content``) holds it.
    """
    thinking = stage_thinking(settings, stage)
    if is_openai_model(model):
        return await openai_generate(
            prefix=fixed_context,
            prompt=prompt,
            schema=schema,
            model=model,
            settings=settings,
            temperature=temperature,
            reasoning_effort=thinking,
            prompt_cache_key=cache_key_for(fixed_context),
            service_tier=settings.TRANSLATION_OPENAI_SERVICE_TIER or None,
            timeout_s=_TIMEOUT_S,
        )
    response = await gemini_generate(
        prompt=prompt if cached_content else f"{fixed_context}\n\n{prompt}",
        schema=schema,
        model=model,
        settings=settings,
        temperature=temperature,
        timeout_s=_TIMEOUT_S,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        thinking_level=thinking,
        cached_content=cached_content,
    )
    return ModelResult(parsed=response.parsed, text=response.text, usage=_usage(response))


async def _generate_aligned[T: BaseModel](
    *,
    fixed_context: str,
    cached_content: str | None,
    prompt: str,
    schema: type[T],
    expected_ids: list[str],
    stage: str,
    temperature: float,
    settings: Settings,
) -> StageResult[T]:
    """Call the model; ``prompt`` is everything after the fixed context."""
    model = stage_model(settings, stage)
    problem: str | None = None
    for attempt in range(2):
        full_prompt = prompt
        if problem:
            full_prompt += (
                "\n\n## Correction\n\nYour previous answer had the wrong paragraphs "
                f"({problem}). Return exactly these ids, in this order: " + ", ".join(expected_ids)
            )
        result = await _call_model(
            fixed_context=fixed_context,
            prompt=full_prompt,
            schema=schema,
            model=model,
            stage=stage,
            temperature=temperature,
            cached_content=cached_content,
            settings=settings,
        )
        if isinstance(result.parsed, schema):
            parsed = result.parsed
        elif result.text:
            parsed = schema.model_validate_json(result.text)
        else:
            raise RuntimeError("Translation returned an empty response.")
        for p in parsed.paragraphs:  # type: ignore[attr-defined]
            p.paragraph_id = p.paragraph_id.strip()
        problem = _alignment_problem(parsed.paragraphs, expected_ids)  # type: ignore[attr-defined]
        if problem is None:
            return StageResult(output=parsed, model=model, usage=result.usage)
        if attempt == 1:
            break
    raise FragmentAlignmentError(problem or "paragraph mismatch")


@observe(name="translate_fragment_faithful", as_type="generation")
async def translate_fragment_faithful(
    *,
    fixed_context: str,
    cached_content: str | None,
    context: str,
    source: list[tuple[str, str]],
    target_language: str,
    settings: Settings,
) -> StageResult[FaithfulFragment]:
    """Stage 1. ``source`` is ``[(short_id, text)]``."""
    prompt = build_faithful_prompt(context=context, target_language=target_language, source=source)
    return await _generate_aligned(
        fixed_context=fixed_context,
        cached_content=cached_content,
        prompt=prompt,
        schema=FaithfulFragment,
        expected_ids=[pid for pid, _ in source],
        stage="faithful",
        temperature=0.3,
        settings=settings,
    )


@observe(name="line_edit_fragment", as_type="generation")
async def line_edit_fragment(
    *,
    fixed_context: str,
    cached_content: str | None,
    context: str,
    source: list[tuple[str, str]],
    faithful: list[tuple[str, str]],
    checks: list[str],
    rhythm: list[str],
    target_language: str,
    settings: Settings,
) -> StageResult[LineEditedFragment]:
    """Stage 2. ``checks`` are QA problems and ``rhythm`` the repeated words and
    even-length sentence runs found in the faithful text."""
    prompt = build_line_edit_prompt(
        context=context,
        target_language=target_language,
        source=source,
        faithful=faithful,
        checks=checks,
        rhythm=rhythm,
    )
    return await _generate_aligned(
        fixed_context=fixed_context,
        cached_content=cached_content,
        prompt=prompt,
        schema=LineEditedFragment,
        expected_ids=[pid for pid, _ in source],
        stage="line_edit",
        temperature=0.5,
        settings=settings,
    )


@observe(name="polish_fragment", as_type="generation")
async def polish_fragment(
    *,
    fixed_context: str,
    cached_content: str | None,
    context: str,
    source: list[tuple[str, str]],
    line_edited: list[tuple[str, str]],
    metrics_block: str,
    target_language: str,
    settings: Settings,
) -> StageResult[PolishedFragment]:
    """Stage 3."""
    prompt = build_polish_prompt(
        context=context,
        target_language=target_language,
        source=source,
        line_edited=line_edited,
        metrics_block=metrics_block,
    )
    return await _generate_aligned(
        fixed_context=fixed_context,
        cached_content=cached_content,
        prompt=prompt,
        schema=PolishedFragment,
        expected_ids=[pid for pid, _ in source],
        stage="polish",
        temperature=0.4,
        settings=settings,
    )


@observe(name="revise_fragment", as_type="generation")
async def revise_fragment(
    *,
    fixed_context: str,
    cached_content: str | None,
    context: str,
    source: list[tuple[str, str]],
    faithful: list[tuple[str, str]],
    checks: list[str],
    rhythm: list[str],
    metrics_block: str,
    target_language: str,
    settings: Settings,
) -> StageResult[LineEditedFragment]:
    """Two-step mode, stage 2: line edit and final edit in one pass.

    Uses the line-edit model and thinking level; the caller stores the
    result as the final stage.
    """
    prompt = build_revision_prompt(
        context=context,
        target_language=target_language,
        source=source,
        faithful=faithful,
        checks=checks,
        rhythm=rhythm,
        metrics_block=metrics_block,
    )
    return await _generate_aligned(
        fixed_context=fixed_context,
        cached_content=cached_content,
        prompt=prompt,
        schema=LineEditedFragment,
        expected_ids=[pid for pid, _ in source],
        stage="line_edit",
        temperature=0.5,
        settings=settings,
    )


@observe(name="translate_fragment_one_step", as_type="generation")
async def translate_fragment_one_step(
    *,
    fixed_context: str,
    cached_content: str | None,
    context: str,
    source: list[tuple[str, str]],
    target_language: str,
    settings: Settings,
) -> StageResult[LineEditedFragment]:
    """One-step mode: straight from the source to the final text.

    Uses the line-edit model and thinking level; the caller stores the
    result as the final stage.
    """
    prompt = build_one_step_prompt(context=context, target_language=target_language, source=source)
    return await _generate_aligned(
        fixed_context=fixed_context,
        cached_content=cached_content,
        prompt=prompt,
        schema=LineEditedFragment,
        expected_ids=[pid for pid, _ in source],
        stage="line_edit",
        temperature=0.5,
        settings=settings,
    )
