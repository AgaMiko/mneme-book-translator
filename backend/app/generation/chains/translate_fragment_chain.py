"""LLM chains: translate one fragment in three stages.

1. ``translate_fragment_faithful`` — complete, accurate translation.
2. ``line_edit_fragment`` — natural published-novel prose, checked against
   the source.
3. ``polish_fragment`` — final polish against measured style targets.

Each call returns a paragraph-aligned result: one paragraph per input id, in
order. If the model returns other ids, the call is repeated once with the
problem stated; a second failure raises ``FragmentAlignmentError``.

Models come from settings: ``TRANSLATION_<STAGE>_MODEL``, then
``TRANSLATION_MODEL``, then ``GEMINI_MODEL``.
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
    build_polish_prompt,
)
from app.generation.providers.gemini import generate as gemini_generate

if TYPE_CHECKING:
    from app.core.config import Settings

# A 1,500-word fragment is about 3k output tokens; thinking models need room.
_MAX_OUTPUT_TOKENS = 32_768
_TIMEOUT_S = 420


class FragmentAlignmentError(RuntimeError):
    """The model did not return exactly the input paragraph ids."""


@dataclass(slots=True)
class StageResult[T]:
    output: T
    model: str
    usage: dict[str, Any] | None


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


async def _generate_aligned[T: BaseModel](
    *,
    prompt: str,
    schema: type[T],
    expected_ids: list[str],
    model: str,
    temperature: float,
    settings: Settings,
) -> StageResult[T]:
    problem: str | None = None
    for attempt in range(2):
        full_prompt = prompt
        if problem:
            full_prompt += (
                "\n\n## Correction\n\nYour previous answer had the wrong paragraphs "
                f"({problem}). Return exactly these ids, in this order: " + ", ".join(expected_ids)
            )
        response = await gemini_generate(
            prompt=full_prompt,
            schema=schema,
            model=model,
            settings=settings,
            temperature=temperature,
            timeout_s=_TIMEOUT_S,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
        )
        if isinstance(response.parsed, schema):
            parsed = response.parsed
        elif response.text:
            parsed = schema.model_validate_json(response.text)
        else:
            raise RuntimeError("Translation returned an empty response.")
        for p in parsed.paragraphs:  # type: ignore[attr-defined]
            p.paragraph_id = p.paragraph_id.strip()
        problem = _alignment_problem(parsed.paragraphs, expected_ids)  # type: ignore[attr-defined]
        if problem is None:
            return StageResult(output=parsed, model=model, usage=_usage(response))
        if attempt == 1:
            break
    raise FragmentAlignmentError(problem or "paragraph mismatch")


@observe(name="translate_fragment_faithful", as_type="generation")
async def translate_fragment_faithful(
    *,
    context: str,
    source: list[tuple[str, str]],
    target_language: str,
    settings: Settings,
) -> StageResult[FaithfulFragment]:
    """Stage 1. ``source`` is ``[(short_id, text)]``."""
    prompt = build_faithful_prompt(context=context, target_language=target_language, source=source)
    return await _generate_aligned(
        prompt=prompt,
        schema=FaithfulFragment,
        expected_ids=[pid for pid, _ in source],
        model=stage_model(settings, "faithful"),
        temperature=0.3,
        settings=settings,
    )


@observe(name="line_edit_fragment", as_type="generation")
async def line_edit_fragment(
    *,
    context: str,
    source: list[tuple[str, str]],
    faithful: list[tuple[str, str]],
    checks: list[str],
    target_language: str,
    settings: Settings,
) -> StageResult[LineEditedFragment]:
    """Stage 2. ``checks`` are QA problems found in the faithful text."""
    prompt = build_line_edit_prompt(
        context=context,
        target_language=target_language,
        source=source,
        faithful=faithful,
        checks=checks,
    )
    return await _generate_aligned(
        prompt=prompt,
        schema=LineEditedFragment,
        expected_ids=[pid for pid, _ in source],
        model=stage_model(settings, "line_edit"),
        temperature=0.5,
        settings=settings,
    )


@observe(name="polish_fragment", as_type="generation")
async def polish_fragment(
    *,
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
        prompt=prompt,
        schema=PolishedFragment,
        expected_ids=[pid for pid, _ in source],
        model=stage_model(settings, "polish"),
        temperature=0.4,
        settings=settings,
    )
