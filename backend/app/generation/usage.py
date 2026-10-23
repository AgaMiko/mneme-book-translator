"""Real token usage and cost of each model call.

Every call through ``providers/router.py`` (and fragment translation's own
calls) ends in ``record_call``, which:

- prices the call with the same table the estimates use (OpenAI Flex at
  half price, cached input at a tenth),
- attaches model, tokens and cost to the active Langfuse generation, since
  Langfuse does not know these models' prices,
- adds the cost to the run's ``Spend`` when a run is counting (see
  ``counting``), so the run can compare real cost with its estimate.

Usage dicts use the Gemini key names, which the OpenAI provider also fills:
``prompt_token_count``, ``cached_content_token_count``,
``candidates_token_count``, ``thoughts_token_count``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.services.gemini_model_pricing import model_usd_per_million_tokens

if TYPE_CHECKING:
    from collections.abc import Iterator

log = get_logger(__name__)

# Cached input costs a tenth of fresh input (Gemini and OpenAI alike).
CACHED_INPUT_SHARE_OF_PRICE = 0.1


@dataclass(slots=True)
class Spend:
    """What the calls of one run (or one part of it) actually cost."""

    usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, cost: float, usage: dict[str, Any] | None) -> None:
        self.usd += cost
        self.calls += 1
        if usage:
            self.input_tokens += int(usage.get("prompt_token_count") or 0)
            self.output_tokens += int(usage.get("candidates_token_count") or 0) + int(
                usage.get("thoughts_token_count") or 0
            )


_spend: ContextVar[Spend | None] = ContextVar("spend", default=None)


@contextmanager
def counting(spend: Spend) -> Iterator[Spend]:
    """Add the cost of every call made inside the block (and its tasks) to ``spend``."""
    token = _spend.set(spend)
    try:
        yield spend
    finally:
        _spend.reset(token)


def gemini_usage(response: Any) -> dict[str, Any] | None:
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


def call_cost(model: str, usage: dict[str, Any] | None, service_tier: str | None) -> float:
    if not usage:
        return 0.0
    pin, pout = model_usd_per_million_tokens(model, service_tier)
    prompt = int(usage.get("prompt_token_count") or 0)
    cached = min(prompt, int(usage.get("cached_content_token_count") or 0))
    output = int(usage.get("candidates_token_count") or 0) + int(
        usage.get("thoughts_token_count") or 0
    )
    return (
        (prompt - cached) * pin + cached * pin * CACHED_INPUT_SHARE_OF_PRICE + output * pout
    ) / 1_000_000


def record_call(model: str, usage: dict[str, Any] | None, service_tier: str | None) -> float:
    """Price one finished call, report it to Langfuse and the counting run. Returns USD."""
    cost = call_cost(model, usage, service_tier)
    spend = _spend.get()
    if spend is not None:
        spend.add(cost, usage)
    _report_to_langfuse(model, usage, cost)
    return cost


def _report_to_langfuse(model: str, usage: dict[str, Any] | None, cost: float) -> None:
    try:
        from langfuse import get_client
    except ImportError:
        return
    details: dict[str, int] = {}
    if usage:
        prompt = int(usage.get("prompt_token_count") or 0)
        cached = int(usage.get("cached_content_token_count") or 0)
        details["input"] = prompt - min(prompt, cached)
        if cached:
            details["cache_read_input_tokens"] = cached
        details["output"] = int(usage.get("candidates_token_count") or 0) + int(
            usage.get("thoughts_token_count") or 0
        )
    try:
        get_client().update_current_generation(
            model=model,
            usage_details=details or None,
            cost_details={"total": cost} if usage else None,
        )
    except Exception:  # tracing must never break a run
        log.debug("langfuse_update_failed", model=model)
