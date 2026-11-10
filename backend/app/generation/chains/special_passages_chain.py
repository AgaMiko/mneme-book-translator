"""LLM chains for special passages (Step 6): scan, rule, check, rewrite.

The caller (``services.special_passages_service``) renders the text
blocks, maps short paragraph ids back and checks results with code.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langfuse import observe
from pydantic import BaseModel

from app.constants.languages import language_name
from app.core.logging import get_logger
from app.generation.prompt_manager.models.special_passages_model import (
    ChapterScan,
    PassageRewrite,
    PassageRule,
    PassageVerdict,
)
from app.generation.prompt_manager.prompts.special_passages_prompt import (
    CHECK_PROMPT,
    REWRITE_PROMPT,
    RULE_PROMPT,
    SCAN_PROMPT,
)
from app.generation.providers.router import generate_structured, parse_result

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

_MAX_OUTPUT_TOKENS = 16_384
_PARSE_ATTEMPTS = 2


async def _call[T: BaseModel](
    prompt: str,
    schema: type[T],
    label: str,
    settings: Settings,
    *,
    thinking: str | None,
    temperature: float = 0.2,
) -> T:
    last: Exception | None = None
    for attempt in range(_PARSE_ATTEMPTS):
        result = await generate_structured(
            prompt=prompt,
            schema=schema,
            model=settings.PASSAGES_MODEL,
            settings=settings,
            temperature=temperature,
            thinking=thinking,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            service_tier=settings.OPENAI_BACKGROUND_SERVICE_TIER,
        )
        try:
            return parse_result(result, schema, label)
        except (ValueError, RuntimeError) as exc:
            last = exc
            log.warning("passages_parse_attempt_failed", label=label, attempt=attempt + 1)
            if attempt + 1 < _PARSE_ATTEMPTS:
                await asyncio.sleep(2.0)
    raise ValueError(f"No usable output for the {label}: {last}")


def message_block(*, source_message: str | None, target_message: str | None) -> str:
    """The hidden-message lines of a prompt; empty for the other kinds."""
    rows = []
    if source_message:
        rows.append(f"Message in the source: {source_message}")
    if target_message:
        rows.append(f"Target message (what the translation must spell): {target_message}")
    return "\n".join(rows) + ("\n" if rows else "")


@observe(name="passages_scan_chapter", as_type="generation")
async def scan_chapter(
    *, chapter_text: str, source_language: str, target_language: str, settings: Settings
) -> ChapterScan:
    prompt = SCAN_PROMPT.format(
        source_language=language_name(source_language),
        target_language=language_name(target_language),
        chapter_text=chapter_text,
    )
    return await _call(
        prompt, ChapterScan, "chapter scan", settings, thinking=settings.STEP_THINKING
    )


@observe(name="passages_describe_rule", as_type="generation")
async def describe_rule(
    *,
    passage_text: str,
    first_id: str,
    last_id: str,
    candidate_kind: str,
    letter_strings: str,
    chapter_text: str,
    source_language: str,
    target_language: str,
    settings: Settings,
) -> PassageRule:
    prompt = RULE_PROMPT.format(
        source_language=language_name(source_language),
        target_language=language_name(target_language),
        passage_text=passage_text,
        first_id=first_id,
        last_id=last_id,
        candidate_kind=candidate_kind,
        letter_strings=letter_strings,
        chapter_text=chapter_text,
    )
    return await _call(
        prompt, PassageRule, "passage rule", settings, thinking=settings.STEP_THINKING
    )


@observe(name="passages_check", as_type="generation")
async def check_passage(
    *,
    kind: str,
    rule: str,
    source_message: str | None,
    target_message: str | None,
    source_text: str,
    target_text: str,
    letter_strings: str,
    dependent_text: str,
    source_language: str,
    target_language: str,
    settings: Settings,
) -> PassageVerdict:
    prompt = CHECK_PROMPT.format(
        source_language=language_name(source_language),
        target_language=language_name(target_language),
        kind=kind,
        rule=rule,
        message_block=message_block(source_message=source_message, target_message=target_message),
        source_text=source_text,
        target_text=target_text,
        letter_strings=letter_strings,
        dependent_text=dependent_text or "(none)",
    )
    return await _call(
        prompt, PassageVerdict, "passage check", settings, thinking=settings.STEP_THINKING
    )


@observe(name="passages_rewrite", as_type="generation")
async def rewrite_passage(
    *,
    kind: str,
    rule: str,
    source_message: str | None,
    target_message: str | None,
    problems: list[str],
    source_text: str,
    target_text: str,
    dependent_text: str,
    source_language: str,
    target_language: str,
    settings: Settings,
) -> PassageRewrite:
    prompt = REWRITE_PROMPT.format(
        source_language=language_name(source_language),
        target_language=language_name(target_language),
        kind=kind,
        rule=rule,
        message_block=message_block(source_message=source_message, target_message=target_message),
        problems="\n".join(f"- {p}" for p in problems) or "- It does not follow the rule.",
        source_text=source_text,
        target_text=target_text,
        dependent_text=dependent_text or "(none)",
    )
    return await _call(
        prompt,
        PassageRewrite,
        "passage rewrite",
        settings,
        thinking=settings.PASSAGES_REWRITE_THINKING,
        temperature=0.7,
    )
