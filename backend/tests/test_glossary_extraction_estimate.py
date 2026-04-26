"""Tests for glossary extraction window counting and cost estimation."""

from app.constants.glossary_extraction import (
    GLOSSARY_EXTRACTION_OVERLAP_WORDS,
    GLOSSARY_EXTRACTION_WINDOW_WORDS,
)
from app.core.config import Settings
from app.services.glossary_extraction_estimate import (
    estimate_glossary_extraction,
    glossary_window_count,
)
from app.services.glossary_service import make_windows


def test_make_windows_overlap_stride() -> None:
    words = ["w"] * 2500
    text = " ".join(words)
    wins = make_windows(
        text,
        window_words=GLOSSARY_EXTRACTION_WINDOW_WORDS,
        overlap_words=GLOSSARY_EXTRACTION_OVERLAP_WORDS,
    )
    assert len(wins) == glossary_window_count(
        2500,
        window_words=GLOSSARY_EXTRACTION_WINDOW_WORDS,
        overlap_words=GLOSSARY_EXTRACTION_OVERLAP_WORDS,
    )
    assert all(len(w.split()) <= GLOSSARY_EXTRACTION_WINDOW_WORDS for w in wins)


def test_glossary_window_count_empty() -> None:
    assert glossary_window_count(0) == 0


def test_glossary_window_count_single_window() -> None:
    assert glossary_window_count(1) == 1
    assert glossary_window_count(GLOSSARY_EXTRACTION_WINDOW_WORDS) == 1


def test_glossary_window_count_stride() -> None:
    stride = GLOSSARY_EXTRACTION_WINDOW_WORDS - GLOSSARY_EXTRACTION_OVERLAP_WORDS
    assert glossary_window_count(GLOSSARY_EXTRACTION_WINDOW_WORDS + 1) == 2
    assert glossary_window_count(GLOSSARY_EXTRACTION_WINDOW_WORDS + stride) == 2
    words = ["w"] * 2000
    assert len(
        make_windows(
            " ".join(words),
            window_words=GLOSSARY_EXTRACTION_WINDOW_WORDS,
            overlap_words=GLOSSARY_EXTRACTION_OVERLAP_WORDS,
        ),
    ) == glossary_window_count(2000)


def test_estimate_zero_words_no_cost() -> None:
    settings = Settings(
        GEMINI_MODEL="gemini-2.5-flash-lite",
        GEMINI_API_KEY=None,
    )
    r = estimate_glossary_extraction(word_count=0, settings=settings)
    assert r.window_count == 0
    assert r.estimated_total_tokens == 0
    assert r.estimated_cost_usd == 0.0


def test_estimate_increases_with_word_count() -> None:
    settings = Settings(
        GEMINI_MODEL="gemini-2.5-flash-lite",
        GEMINI_API_KEY=None,
    )
    small = estimate_glossary_extraction(word_count=5000, settings=settings)
    large = estimate_glossary_extraction(word_count=50_000, settings=settings)
    assert large.window_count > small.window_count
    assert large.estimated_total_tokens > small.estimated_total_tokens
    assert large.estimated_cost_usd >= small.estimated_cost_usd


def test_price_env_override() -> None:
    settings = Settings(
        GEMINI_MODEL="gemini-2.5-flash-lite",
        GEMINI_API_KEY=None,
        GEMINI_INPUT_PRICE_USD_PER_MTOK=1.0,
        GEMINI_OUTPUT_PRICE_USD_PER_MTOK=2.0,
    )
    r = estimate_glossary_extraction(word_count=10_000, settings=settings)
    assert r.pricing_input_usd_per_mtok == 1.0
    assert r.pricing_output_usd_per_mtok == 2.0
