"""Tests for voice pipeline cost estimation."""

from app.core.config import Settings
from app.services.voice_extraction_estimate import estimate_voice_extraction


def test_estimate_zero_words_no_cost() -> None:
    settings = Settings(
        GEMINI_MODEL="gemini-2.5-flash-lite",
        GEMINI_API_KEY=None,
    )
    r = estimate_voice_extraction(word_count=0, character_count=5, settings=settings)
    assert r.pass1.window_count == 0
    assert r.estimated_total_tokens == 0
    assert r.estimated_cost_usd == 0.0


def test_estimate_increases_with_word_count() -> None:
    settings = Settings(
        GEMINI_MODEL="gemini-2.5-flash-lite",
        GEMINI_API_KEY=None,
    )
    small = estimate_voice_extraction(word_count=5000, character_count=3, settings=settings)
    large = estimate_voice_extraction(word_count=50_000, character_count=12, settings=settings)
    assert large.pass1.window_count > small.pass1.window_count
    assert large.estimated_total_tokens > small.estimated_total_tokens
    assert large.estimated_cost_usd >= small.estimated_cost_usd
    assert large.pass2.estimated_cost_usd > small.pass2.estimated_cost_usd
