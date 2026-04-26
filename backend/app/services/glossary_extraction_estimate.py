"""Predict token usage and USD cost for iterative glossary extraction.

Windowing defaults match ``app.constants.glossary_extraction`` and
``glossary_service.make_windows``. Token counts use a **chars ÷ 4**
heuristic (Gemini-style rough tokenization) plus a small buffer for the
growing glossary table on later passes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.constants.glossary_extraction import (
    GLOSSARY_EXTRACTION_OVERLAP_WORDS,
    GLOSSARY_EXTRACTION_WINDOW_WORDS,
)
from app.generation.prompt_manager.prompts.extract_glossary_prompt import (
    FIRST_PASS_NOTE,
    PROMPT,
    render_glossary_table,
    render_notepad,
)
from app.services.gemini_model_pricing import resolve_gemini_usd_per_million_tokens

if TYPE_CHECKING:
    from app.core.config import Settings


def glossary_window_count(
    total_words: int,
    *,
    window_words: int = GLOSSARY_EXTRACTION_WINDOW_WORDS,
    overlap_words: int = GLOSSARY_EXTRACTION_OVERLAP_WORDS,
) -> int:
    """How many LLM calls the extraction loop will make for ``total_words``."""
    if total_words <= 0:
        return 0
    if total_words <= window_words:
        return 1
    stride = window_words - overlap_words
    return 1 + math.ceil((total_words - window_words) / stride)


def _chars_to_tokens_heuristic(char_count: int) -> int:
    return max(0, (char_count + 3) // 4)


def _placeholder_window_text(*, window_words: int, chars_per_word: float) -> str:
    nchars = max(1, int(window_words * chars_per_word))
    # Deterministic filler — length matters for the estimate, not linguistics.
    unit = "abcde "
    reps = (nchars + len(unit) - 1) // len(unit)
    return (unit * reps)[:nchars]


def _rendered_prompt_chars(
    *,
    window_words: int,
    chars_per_word: float,
    window_number: int,
    total_windows: int,
    include_first_pass_note: bool,
) -> int:
    tw = max(1, total_windows)
    wn = max(1, min(window_number, tw))
    body = PROMPT.format(
        first_pass_note=FIRST_PASS_NOTE if include_first_pass_note else "",
        window_number=wn,
        total_windows=tw,
        n_entries=0,
        glossary_table=render_glossary_table([]),
        notepad=render_notepad([]),
        window_text=_placeholder_window_text(
            window_words=window_words, chars_per_word=chars_per_word
        ),
        source_language="Polish",
        target_language="English",
    )
    return len(body)


@dataclass(frozen=True)
class GlossaryExtractionEstimateResult:
    model: str
    window_count: int
    window_words: int
    overlap_words: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float
    pricing_input_usd_per_mtok: float
    pricing_output_usd_per_mtok: float


def estimate_glossary_extraction(
    *,
    word_count: int,
    settings: Settings,
    window_words: int = GLOSSARY_EXTRACTION_WINDOW_WORDS,
    overlap_words: int = GLOSSARY_EXTRACTION_OVERLAP_WORDS,
    chars_per_word: float = 5.8,
    glossary_growth_buffer_ratio: float = 1.12,
    estimated_output_tokens_per_window: int = 2200,
) -> GlossaryExtractionEstimateResult:
    """Aggregate token and cost prediction for one book."""
    n = glossary_window_count(
        word_count, window_words=window_words, overlap_words=overlap_words
    )
    model = settings.GEMINI_MODEL

    if settings.GEMINI_INPUT_PRICE_USD_PER_MTOK is not None:
        pin = settings.GEMINI_INPUT_PRICE_USD_PER_MTOK
    else:
        pin, _ = resolve_gemini_usd_per_million_tokens(model)
    if settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK is not None:
        pout = settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK
    else:
        _, pout = resolve_gemini_usd_per_million_tokens(model)

    if n == 0:
        return GlossaryExtractionEstimateResult(
            model=model,
            window_count=0,
            window_words=window_words,
            overlap_words=overlap_words,
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            estimated_total_tokens=0,
            estimated_cost_usd=0.0,
            pricing_input_usd_per_mtok=pin,
            pricing_output_usd_per_mtok=pout,
        )

    tw = n
    first_chars = _rendered_prompt_chars(
        window_words=window_words,
        chars_per_word=chars_per_word,
        window_number=1,
        total_windows=tw,
        include_first_pass_note=True,
    )
    later_chars = _rendered_prompt_chars(
        window_words=window_words,
        chars_per_word=chars_per_word,
        window_number=2,
        total_windows=tw,
        include_first_pass_note=False,
    )

    raw_input = _chars_to_tokens_heuristic(first_chars) + _chars_to_tokens_heuristic(
        later_chars
    ) * (n - 1)
    est_in = math.ceil(raw_input * glossary_growth_buffer_ratio)
    est_out = n * estimated_output_tokens_per_window
    total = est_in + est_out
    cost = (est_in / 1_000_000.0) * pin + (est_out / 1_000_000.0) * pout

    return GlossaryExtractionEstimateResult(
        model=model,
        window_count=n,
        window_words=window_words,
        overlap_words=overlap_words,
        estimated_input_tokens=est_in,
        estimated_output_tokens=est_out,
        estimated_total_tokens=total,
        estimated_cost_usd=round(cost, 4),
        pricing_input_usd_per_mtok=pin,
        pricing_output_usd_per_mtok=pout,
    )
