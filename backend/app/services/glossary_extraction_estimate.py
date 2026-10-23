"""Predict token usage and USD cost for iterative glossary extraction.

Windowing defaults match ``app.constants.glossary_extraction`` and
``glossary_service.make_windows``. Token counts use a **chars ÷ 4**
heuristic (Gemini-style rough tokenization).

Every window's prompt carries the whole glossary found so far, which grows
to ~1.5 terms per 1,000 words by the end of a run. Most names turn up
early, so on average a window carries ~68% of the final table. On
Zaplataczka (107k words, 135 windows) that table was ~70% of all input; an
earlier version of this estimate left it out and came in 3.6 times low on
input and 4 times high on output. Measured (2026-10-23) on three single
runs over Zaplataczka: 1.3 to 1.5 terms per 1,000 words, ~236 characters
per glossary row, 6.6 characters per word, 410 to 540 visible output
tokens per window.
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
from app.services.gemini_model_pricing import model_usd_per_million_tokens
from app.services.translation_estimate import thinking_ratio

if TYPE_CHECKING:
    from collections.abc import Callable

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
    model: str | None = None,
    window_words: int = GLOSSARY_EXTRACTION_WINDOW_WORDS,
    overlap_words: int = GLOSSARY_EXTRACTION_OVERLAP_WORDS,
    chars_per_word: float = 6.6,
    terms_per_1000_words: float = 1.5,
    average_table_share: float = 0.68,
    glossary_row_chars: int = 236,
    visible_output_tokens_per_window: int = 550,
) -> GlossaryExtractionEstimateResult:
    """Aggregate token and cost prediction for one book with ``model``
    (``GLOSSARY_MODEL`` by default). Output includes thinking tokens at
    ``STEP_THINKING``; OpenAI models are priced on the background tier."""
    n = glossary_window_count(word_count, window_words=window_words, overlap_words=overlap_words)
    model = model or settings.GLOSSARY_MODEL

    pin, pout = model_usd_per_million_tokens(model, settings.OPENAI_BACKGROUND_SERVICE_TIER)
    if settings.GEMINI_INPUT_PRICE_USD_PER_MTOK is not None:
        pin = settings.GEMINI_INPUT_PRICE_USD_PER_MTOK
    if settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK is not None:
        pout = settings.GEMINI_OUTPUT_PRICE_USD_PER_MTOK

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

    final_terms = word_count / 1000 * terms_per_1000_words
    table_chars_per_window = final_terms * average_table_share * glossary_row_chars
    est_in = _chars_to_tokens_heuristic(first_chars) + (n - 1) * _chars_to_tokens_heuristic(
        later_chars + int(table_chars_per_window)
    )
    visible_out = n * visible_output_tokens_per_window
    est_out = math.ceil(
        visible_out * (1 + thinking_ratio(model, settings.STEP_THINKING, "line_edit"))
    )
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


def glossary_expected_cost(
    *, word_count: int, settings: Settings, model: str | None = None
) -> Callable[[int], float]:
    """Estimated cost of windows 1..k, for comparing a running extraction with its estimate.

    Windows get dearer as the glossary table in each prompt grows: the table
    at window i is about ``(i / n) ** p`` of its final size, with ``p`` set so
    that the average share is 0.68 as measured. The rest of each window
    (instructions, text, output) costs the same throughout.
    """
    full = estimate_glossary_extraction(word_count=word_count, settings=settings, model=model)
    n = full.window_count
    if n == 0:
        return lambda _k: 0.0
    no_table = estimate_glossary_extraction(
        word_count=word_count, settings=settings, model=model, terms_per_1000_words=0
    )
    fixed = no_table.estimated_cost_usd
    table = full.estimated_cost_usd - fixed
    exponent = 1 / 0.68  # p + 1, with 1 / (p + 1) = 0.68

    def expected(k: int) -> float:
        share = min(max(k, 0), n) / n
        return fixed * share + table * share**exponent

    return expected
