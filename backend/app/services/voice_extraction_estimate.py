"""Predict token usage and USD cost for the voice pipeline (Pass 1 + Pass 2).

Windowing matches ``app.constants.voice_extraction``. Token counts use a
chars ÷ 4 heuristic plus fixed per-call output budgets derived from the
three-chain workflow (extraction windows, then per-character selection and
per-passage translation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.services.gemini_model_pricing import resolve_gemini_usd_per_million_tokens
from app.services.glossary_extraction_estimate import (
    _chars_to_tokens_heuristic,
    glossary_window_count,
)

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
    window_count: int
    character_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float


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


def estimate_voice_extraction(
    *,
    word_count: int,
    character_count: int,
    settings: Settings,
) -> VoiceExtractionEstimateResult:
    """Aggregate token and cost prediction for Pass 1 and Pass 2."""
    model = settings.GEMINI_MODEL
    windows = _window_count(word_count)
    chars = max(0, character_count)

    if settings.GEMINI_INPUT_PRICE_USD_PER_MTOK is not None:
        pin = settings.GEMINI_INPUT_PRICE_USD_PER_MTOK
    else:
        pin, _ = resolve_gemini_usd_per_million_tokens(model)
    if settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK is not None:
        pout = settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK
    else:
        _, pout = resolve_gemini_usd_per_million_tokens(model)

    if windows == 0:
        empty = VoicePassEstimate(0, chars, 0, 0, 0, 0.0)
        return VoiceExtractionEstimateResult(
            model=model,
            window_words=VOICE_EXTRACTION_WINDOW_WORDS,
            overlap_words=VOICE_EXTRACTION_OVERLAP_WORDS,
            character_count=chars,
            pass1=empty,
            pass2=empty,
            estimated_total_tokens=0,
            estimated_cost_usd=0.0,
            pricing_input_usd_per_mtok=pin,
            pricing_output_usd_per_mtok=pout,
        )

    pass1_in = windows * _chars_to_tokens_heuristic(_PASS1_PROMPT_CHARS_PER_WINDOW)
    pass1_out = windows * _PASS1_OUTPUT_TOKENS_PER_WINDOW
    pass1_total = pass1_in + pass1_out
    pass1_cost = (pass1_in / 1_000_000.0) * pin + (pass1_out / 1_000_000.0) * pout

    pass2_extract_in = windows * _chars_to_tokens_heuristic(
        _PASS2_EXTRACTION_PROMPT_CHARS_PER_WINDOW
    )
    pass2_extract_out = windows * _PASS2_EXTRACTION_OUTPUT_TOKENS_PER_WINDOW
    selection_calls = chars
    translation_calls = max(0, math.ceil(chars * _AVG_PASSAGES_PER_CHARACTER))
    pass2_post_in = selection_calls * _chars_to_tokens_heuristic(_PASS2_SELECTION_PROMPT_CHARS) + (
        translation_calls * _chars_to_tokens_heuristic(_PASS2_TRANSLATION_PROMPT_CHARS)
    )
    pass2_post_out = (
        selection_calls * _PASS2_SELECTION_OUTPUT_TOKENS_PER_CHARACTER
        + translation_calls * _PASS2_TRANSLATION_OUTPUT_TOKENS_PER_PASSAGE
    )
    pass2_in = pass2_extract_in + pass2_post_in
    pass2_out = pass2_extract_out + pass2_post_out
    pass2_total = pass2_in + pass2_out
    pass2_cost = (pass2_in / 1_000_000.0) * pin + (pass2_out / 1_000_000.0) * pout

    total_tokens = pass1_total + pass2_total
    total_cost = round(pass1_cost + pass2_cost, 4)

    return VoiceExtractionEstimateResult(
        model=model,
        window_words=VOICE_EXTRACTION_WINDOW_WORDS,
        overlap_words=VOICE_EXTRACTION_OVERLAP_WORDS,
        character_count=chars,
        pass1=VoicePassEstimate(
            window_count=windows,
            character_count=chars,
            estimated_input_tokens=pass1_in,
            estimated_output_tokens=pass1_out,
            estimated_total_tokens=pass1_total,
            estimated_cost_usd=round(pass1_cost, 4),
        ),
        pass2=VoicePassEstimate(
            window_count=windows,
            character_count=chars,
            estimated_input_tokens=pass2_in,
            estimated_output_tokens=pass2_out,
            estimated_total_tokens=pass2_total,
            estimated_cost_usd=round(pass2_cost, 4),
        ),
        estimated_total_tokens=total_tokens,
        estimated_cost_usd=total_cost,
        pricing_input_usd_per_mtok=pin,
        pricing_output_usd_per_mtok=pout,
    )
