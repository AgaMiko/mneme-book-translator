"""Predict token usage and USD cost for the voice pipeline (Pass 1 + Pass 2).

Windowing matches ``app.constants.voice_extraction``. Token counts use a
chars ÷ 4 heuristic plus fixed per-call output budgets derived from the
three-chain workflow (extraction windows, then per-character selection and
per-passage translation). Pass 1 runs on ``SPEAKERS_MODEL`` and Pass 2 on
``VOICES_MODEL``; output budgets are visible tokens, and thinking at
``STEP_THINKING`` is added on top. These budgets have not been checked
against a real run yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.services.gemini_model_pricing import model_usd_per_million_tokens
from app.services.glossary_extraction_estimate import (
    _chars_to_tokens_heuristic,
    glossary_window_count,
)
from app.services.translation_estimate import thinking_ratio

if TYPE_CHECKING:
    from app.core.config import Settings

# Rough output token budgets per LLM call type.
_PASS1_OUTPUT_TOKENS_PER_WINDOW = 900
_PASS2_EXTRACTION_OUTPUT_TOKENS_PER_WINDOW = 2400
_PASS2_SELECTION_OUTPUT_TOKENS_PER_CHARACTER = 750
_PASS2_TRANSLATION_OUTPUT_TOKENS_PER_PASSAGE = 550
_AVG_PASSAGES_PER_CHARACTER = 2.5

# Input prompt size heuristics (chars) — smaller than glossary windows.
_PASS1_PROMPT_CHARS_PER_WINDOW = 14_000
_PASS2_EXTRACTION_PROMPT_CHARS_PER_WINDOW = 18_000
_PASS2_SELECTION_PROMPT_CHARS = 6_500
_PASS2_TRANSLATION_PROMPT_CHARS = 5_200


@dataclass(frozen=True)
class VoicePassEstimate:
    model: str
    window_count: int
    character_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float
    pricing_input_usd_per_mtok: float
    pricing_output_usd_per_mtok: float


@dataclass(frozen=True)
class VoiceExtractionEstimateResult:
    model: str
    window_words: int
    overlap_words: int
    character_count: int
    pass1: VoicePassEstimate
    pass2: VoicePassEstimate
    estimated_total_tokens: int
    estimated_cost_usd: float
    pricing_input_usd_per_mtok: float
    pricing_output_usd_per_mtok: float


def _window_count(word_count: int) -> int:
    return glossary_window_count(
        word_count,
        window_words=VOICE_EXTRACTION_WINDOW_WORDS,
        overlap_words=VOICE_EXTRACTION_OVERLAP_WORDS,
    )


def _pass(
    *, model: str, settings: Settings, windows: int, chars: int, input_tokens: int, visible_out: int
) -> VoicePassEstimate:
    pin, pout = model_usd_per_million_tokens(model, settings.OPENAI_BACKGROUND_SERVICE_TIER)
    if settings.GEMINI_INPUT_PRICE_USD_PER_MTOK is not None:
        pin = settings.GEMINI_INPUT_PRICE_USD_PER_MTOK
    if settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK is not None:
        pout = settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK
    out = math.ceil(visible_out * (1 + thinking_ratio(model, settings.STEP_THINKING, "line_edit")))
    return VoicePassEstimate(
        model=model,
        window_count=windows,
        character_count=chars,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=out,
        estimated_total_tokens=input_tokens + out,
        estimated_cost_usd=round((input_tokens * pin + out * pout) / 1_000_000.0, 4),
        pricing_input_usd_per_mtok=pin,
        pricing_output_usd_per_mtok=pout,
    )


def estimate_voice_extraction(
    *,
    word_count: int,
    character_count: int,
    settings: Settings,
    speakers_model: str | None = None,
    voices_model: str | None = None,
) -> VoiceExtractionEstimateResult:
    """Aggregate token and cost prediction for Pass 1 and Pass 2."""
    model1 = speakers_model or settings.SPEAKERS_MODEL
    model2 = voices_model or settings.VOICES_MODEL
    windows = _window_count(word_count)
    chars = max(0, character_count) if windows else 0

    pass1_in = windows * _chars_to_tokens_heuristic(_PASS1_PROMPT_CHARS_PER_WINDOW)
    pass1_out = windows * _PASS1_OUTPUT_TOKENS_PER_WINDOW

    translation_calls = max(0, math.ceil(chars * _AVG_PASSAGES_PER_CHARACTER))
    pass2_in = (
        windows * _chars_to_tokens_heuristic(_PASS2_EXTRACTION_PROMPT_CHARS_PER_WINDOW)
        + chars * _chars_to_tokens_heuristic(_PASS2_SELECTION_PROMPT_CHARS)
        + translation_calls * _chars_to_tokens_heuristic(_PASS2_TRANSLATION_PROMPT_CHARS)
    )
    pass2_out = (
        windows * _PASS2_EXTRACTION_OUTPUT_TOKENS_PER_WINDOW
        + chars * _PASS2_SELECTION_OUTPUT_TOKENS_PER_CHARACTER
        + translation_calls * _PASS2_TRANSLATION_OUTPUT_TOKENS_PER_PASSAGE
    )
    pass1 = _pass(
        model=model1,
        settings=settings,
        windows=windows,
        chars=chars,
        input_tokens=pass1_in,
        visible_out=pass1_out,
    )
    pass2 = _pass(
        model=model2,
        settings=settings,
        windows=windows,
        chars=chars,
        input_tokens=pass2_in,
        visible_out=pass2_out,
    )
    return VoiceExtractionEstimateResult(
        model=model2,
        window_words=VOICE_EXTRACTION_WINDOW_WORDS,
        overlap_words=VOICE_EXTRACTION_OVERLAP_WORDS,
        character_count=chars,
        pass1=pass1,
        pass2=pass2,
        estimated_total_tokens=pass1.estimated_total_tokens + pass2.estimated_total_tokens,
        estimated_cost_usd=round(pass1.estimated_cost_usd + pass2.estimated_cost_usd, 4),
        pricing_input_usd_per_mtok=pass2.pricing_input_usd_per_mtok,
        pricing_output_usd_per_mtok=pass2.pricing_output_usd_per_mtok,
    )
