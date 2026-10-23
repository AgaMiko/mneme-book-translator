"""Tests for pricing real calls and pausing runs that go over their estimate."""

import asyncio

from app.core.config import Settings
from app.generation.usage import Spend, call_cost, counting, record_call
from app.models.book import Book
from app.services.cost_guard import CostGuard, linear, start_guard


def _usage(prompt: int, out: int, thoughts: int = 0, cached: int = 0) -> dict[str, int]:
    return {
        "prompt_token_count": prompt,
        "candidates_token_count": out,
        "thoughts_token_count": thoughts,
        "cached_content_token_count": cached,
    }


def _guard(**kw) -> CostGuard:  # type: ignore[no-untyped-def]
    args = {
        "step": "glossary",
        "expected": linear(10.0, 100),  # $0.10 per window
        "units_total": 100,
        "start_units": 0,
        "spent_before": 0.0,
        "limit": True,
        "threshold": 0.10,
        "min_units": 5,
    } | kw
    return CostGuard(**args)


def test_call_cost_counts_thinking_cache_and_flex() -> None:
    # Sol on Flex: $2 / $10 per million; cached input at a tenth.
    usage = _usage(prompt=1_000_000, out=100_000, thoughts=100_000, cached=500_000)
    assert (
        call_cost("gpt-6.1-sol", usage, "flex")
        == (500_000 * 2 + 500_000 * 0.2 + 200_000 * 10) / 1e6
    )
    assert call_cost("gpt-6.1-sol", None, "flex") == 0.0


def test_calls_add_to_the_counting_run_including_parallel_tasks() -> None:
    spend = Spend()

    async def one_call() -> None:
        record_call("gpt-6.1-sol", _usage(prompt=1000, out=100), None)

    async def run() -> None:
        with counting(spend):
            await asyncio.gather(one_call(), one_call())
        record_call("gpt-6.1-sol", _usage(prompt=1000, out=100), None)  # outside: not counted

    asyncio.run(run())
    assert spend.calls == 2
    assert spend.input_tokens == 2000


def test_no_pause_before_the_minimum_or_within_the_threshold() -> None:
    guard = _guard()
    guard.units_done, guard.spend.usd = 4, 5.0  # far over, but only 4 windows
    assert guard.overrun() is None
    guard.units_done, guard.spend.usd = 10, 1.09  # 9% over $1.00
    assert guard.overrun() is None


def test_pause_when_more_than_ten_percent_over() -> None:
    guard = _guard()
    guard.units_done, guard.spend.usd = 10, 1.20
    reason = guard.overrun()
    assert reason == "Paused: $1.20 spent on 10 windows, 20% over the $1.00 estimated for them."
    # It sticks, so parallel work finishing afterwards does not clear it.
    assert guard.state()["paused_reason"] == reason


def test_continue_checks_only_the_remaining_work() -> None:
    # Resumed at window 50 after spending $6.00 on the first 50 (20% over).
    guard = _guard(start_units=50, spent_before=6.0)
    guard.units_done, guard.spend.usd = 60, 1.05  # the new 10 windows: 5% over
    assert guard.overrun() is None
    assert guard.state()["spent_usd"] == 7.05


def test_without_limit_never_pauses() -> None:
    guard = _guard(limit=False)
    guard.units_done, guard.spend.usd = 50, 50.0
    assert guard.overrun() is None


def test_a_fresh_start_forgets_earlier_spend_and_continuing_keeps_it() -> None:
    book = Book(title="B", original_filename="b.docx", storage_path="b.docx")
    book.cost_guard = {"glossary": {"spent_usd": 3.0}}
    settings = Settings(GEMINI_API_KEY=None)
    fresh = start_guard(
        book,
        "glossary",
        settings=settings,
        expected=linear(10, 100),
        units_total=100,
        start_units=0,
        limit=True,
    )
    assert fresh.spent_before == 0.0
    book.cost_guard = {"glossary": {"spent_usd": 3.0}}
    resumed = start_guard(
        book,
        "glossary",
        settings=settings,
        expected=linear(10, 100),
        units_total=100,
        start_units=30,
        limit=True,
    )
    assert resumed.spent_before == 3.0
    assert book.cost_guard["glossary"]["paused_reason"] is None
