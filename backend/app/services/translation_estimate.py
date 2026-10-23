"""Rough token and USD estimate for fragment translation.

Same approach as ``glossary_extraction_estimate``: characters ÷ 4 for
tokens. Per fragment there are three calls (faithful, line edit, polish).
Each call sends the shared context (rules, style sheet, glossary, voices,
neighbouring text) plus the source; the line edit and polish also send the
previous stage's English. The fixed part (rules, style sheet, glossary) is
priced as cached input when the run cache is on. Output is the English text
plus notes, plus thinking tokens, which depend on the model and the thinking
level of each stage (measured on chapter 5 of Zaplataczka).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.generation.chains.translate_fragment_chain import (
    calls_per_fragment,
    stage_model,
    stage_thinking,
)
from app.generation.prompt_manager.prompts.translate_fragment_prompt import (
    FAITHFUL_TASK,
    LINE_EDIT_TASK,
    ONE_STEP_TASK,
    POLISH_TASK,
    RULES_CORE,
    STYLE_SHEET,
)
from app.generation.providers.openai import is_openai_model
from app.services.fragmenter import TARGET_WORDS
from app.services.gemini_model_pricing import (
    resolve_flex_usd_per_million_tokens,
    resolve_gemini_usd_per_million_tokens,
)

if TYPE_CHECKING:
    from app.core.config import Settings

_SOURCE_CHARS_PER_WORD = 6.5  # Polish prose incl. spaces and punctuation
_TARGET_CHARS_PER_WORD = 6.0
_TARGET_WORDS_PER_SOURCE_WORD = 1.25
_GLOSSARY_ROW_CHARS = 220
_VOICE_PROFILE_CHARS = 1_200
_VOICES_PER_FRAGMENT = 3
_NEIGHBOUR_WORDS = 400
_NOTES_OUTPUT_CHARS = 1_200
# Thinking tokens as a share of visible output, measured on chapter 5 of
# Zaplataczka with Gemini 3.8 Flash (2026-10-21).
# At "high", the final edit thinks the most (it checks every target).
_THINKING_RATIO_BY_LEVEL: dict[str, dict[str, float]] = {
    "minimal": {"faithful": 0.0, "line_edit": 0.0, "polish": 0.0},
    "low": {"faithful": 0.0, "line_edit": 0.0, "polish": 0.0},
    "medium": {"faithful": 4.0, "line_edit": 4.0, "polish": 4.0},
    "high": {"faithful": 7.5, "line_edit": 7.5, "polish": 12.5},
}
_THINKING_RATIO_MODEL_DEFAULT = 3.2
# Flash-Lite thinks only when a level is asked for. "medium": 2.0, measured on
# a glossary window with Gemini 3.1 Flash-Lite (2026-10-23); "low" and "high"
# are guesses either side of it.
_LITE_THINKING_RATIO: dict[str, float] = {"minimal": 0.0, "low": 1.0, "medium": 2.0, "high": 3.0}
# OpenAI reasoning tokens as a share of visible output, measured the same way
# (Luna and Sol on chapters 3 and 5). Sol's single revision in two-step mode
# reasons like a line edit.
_OPENAI_THINKING_RATIO: dict[str, dict[str, dict[str, float]]] = {
    "gpt-6-luna": {
        "high": {"faithful": 2.1, "line_edit": 2.1, "polish": 2.1},
        "medium": {"faithful": 0.6, "line_edit": 0.6, "polish": 0.6},
    },
    "gpt-6.1-sol": {
        "high": {"faithful": 1.8, "line_edit": 3.1, "polish": 2.7, "one_step": 3.6},
        "medium": {"faithful": 0.4, "line_edit": 0.4, "polish": 0.3},
    },
}
_CACHED_INPUT_SHARE_OF_PRICE = 0.1


def thinking_ratio(model: str, level: str | None, stage: str) -> float:
    """``stage`` may be "one_step"; where that was not measured, the line edit's
    ratio is used (the one-step call uses the line-edit settings)."""
    if "lite" in model.lower():
        return _LITE_THINKING_RATIO.get(level or "minimal", 0.0)
    for prefix, by_level in _OPENAI_THINKING_RATIO.items():
        if model.lower().startswith(prefix) and level in by_level:
            ratios = by_level[level]
            return ratios.get(stage, ratios["line_edit"])
    if level is None:
        return _THINKING_RATIO_MODEL_DEFAULT
    ratios = _THINKING_RATIO_BY_LEVEL.get(level, {})
    return ratios.get(stage, ratios.get("line_edit", _THINKING_RATIO_MODEL_DEFAULT))


def _tokens(chars: float) -> int:
    return max(0, math.ceil(chars / 4))


@dataclass(slots=True)
class StageEstimate:
    stage: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(slots=True)
class TranslationEstimate:
    word_count: int
    fragment_count: int
    glossary_terms: int
    stages: list[StageEstimate]

    @property
    def total_tokens(self) -> int:
        return sum(s.input_tokens + s.output_tokens for s in self.stages)

    @property
    def cost_usd(self) -> float:
        return round(sum(s.cost_usd for s in self.stages), 2)


def estimate_translation(
    *, word_count: int, fragment_count: int | None, glossary_terms: int, settings: Settings
) -> TranslationEstimate:
    fragments = fragment_count or (math.ceil(word_count / TARGET_WORDS) if word_count else 0)
    target_words = word_count * _TARGET_WORDS_PER_SOURCE_WORD
    # The fixed part (rules, style sheet, glossary) is cached per run.
    fixed_chars_per_call = len(RULES_CORE) + len(STYLE_SHEET) + glossary_terms * _GLOSSARY_ROW_CHARS
    context_chars_per_call = (
        _VOICES_PER_FRAGMENT * _VOICE_PROFILE_CHARS + _NEIGHBOUR_WORDS * _SOURCE_CHARS_PER_WORD
    )
    source_chars = word_count * _SOURCE_CHARS_PER_WORD
    target_chars = target_words * _TARGET_CHARS_PER_WORD
    tasks = {"faithful": FAITHFUL_TASK, "line_edit": LINE_EDIT_TASK, "polish": POLISH_TASK}

    stages: list[StageEstimate] = []
    calls = calls_per_fragment(settings)
    for i, stage in enumerate(calls):
        one_step = len(calls) == 1
        task = ONE_STEP_TASK if one_step else tasks[stage]
        input_chars = fragments * (context_chars_per_call + len(task)) + source_chars
        if i > 0:  # every call after the first also reads the previous English
            input_chars += target_chars
        visible_out = target_chars + fragments * _NOTES_OUTPUT_CHARS
        model = stage_model(settings, stage)
        fixed_tokens = _tokens(fragments * fixed_chars_per_call)
        input_tokens = _tokens(input_chars) + fixed_tokens
        ratio = thinking_ratio(
            model, stage_thinking(settings, stage), "one_step" if one_step else stage
        )
        output_tokens = _tokens(visible_out * (1 + ratio))
        in_price, out_price = resolve_gemini_usd_per_million_tokens(model)
        if is_openai_model(model) and settings.TRANSLATION_OPENAI_SERVICE_TIER == "flex":
            in_price, out_price = resolve_flex_usd_per_million_tokens(model) or (
                in_price,
                out_price,
            )
        if settings.GEMINI_INPUT_PRICE_USD_PER_MTOK is not None:
            in_price = settings.GEMINI_INPUT_PRICE_USD_PER_MTOK
        if settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK is not None:
            out_price = settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK
        fixed_price = in_price * (_CACHED_INPUT_SHARE_OF_PRICE if settings.TRANSLATION_CACHE else 1)
        cost = (
            (input_tokens - fixed_tokens) * in_price
            + fixed_tokens * fixed_price
            + output_tokens * out_price
        ) / 1_000_000
        stages.append(
            StageEstimate(
                stage=stage,
                model=model,
                calls=fragments,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 4),
            )
        )
    return TranslationEstimate(
        word_count=word_count,
        fragment_count=fragments,
        glossary_terms=glossary_terms,
        stages=stages,
    )
