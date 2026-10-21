"""OpenAI provider (models named ``gpt-…``), used by fragment translation.

Like ``providers/gemini.py``, this is the only place that knows the vendor
SDK. It returns a ``ModelResult`` with the parsed schema object and usage in
the same keys the Gemini path stores (``prompt_token_count``,
``cached_content_token_count``, ``candidates_token_count``,
``thoughts_token_count``), so renditions, costs and comparisons treat both
providers the same way.

Caching: OpenAI caches a repeated prompt prefix by itself (cached input is
about 10% of the price) and keeps nothing we would have to delete. The
fragment prompts already start with the part that is the same for the whole
book, and ``prompt_cache_key`` groups a run's calls so they hit the same cache.

Thinking: the translation thinking level ("minimal" … "high") is passed as
the reasoning effort. Reasoning models reject ``temperature``, so it is not
sent when an effort is set.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")


def is_openai_model(model: str) -> bool:
    return model.strip().lower().startswith(OPENAI_MODEL_PREFIXES)


class OpenAIDisabledError(RuntimeError):
    """Raised when an OpenAI model is selected but OPENAI_API_KEY is not set."""


@dataclass(slots=True)
class ModelResult:
    parsed: Any | None
    text: str | None
    usage: dict[str, Any] | None


@lru_cache(maxsize=4)
def _get_client(api_key: str, timeout_s: float) -> AsyncOpenAI:
    # Our own loop below retries; the SDK's retries stay at its default.
    return AsyncOpenAI(api_key=api_key, timeout=timeout_s)


def _usage(response: Any) -> dict[str, Any] | None:
    u = getattr(response, "usage", None)
    if u is None:
        return None
    reasoning = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None) or 0
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", None) or 0
    return {
        "prompt_token_count": u.input_tokens,
        "cached_content_token_count": cached,
        "candidates_token_count": max(0, (u.output_tokens or 0) - reasoning),
        "thoughts_token_count": reasoning,
        "total_token_count": u.total_tokens,
    }


async def generate(
    *,
    prompt: str,
    schema: Any,
    settings: Settings,
    model: str,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
    prompt_cache_key: str | None = None,
    timeout_s: int = 420,
    max_retries: int = 4,
    initial_backoff_s: float = 1.0,
) -> ModelResult:
    """Call an OpenAI model with a JSON-schema-constrained response."""
    if not settings.OPENAI_API_KEY:
        raise OpenAIDisabledError("OPENAI_API_KEY is not configured.")
    client = _get_client(settings.OPENAI_API_KEY, float(timeout_s))

    kwargs: dict[str, Any] = {"model": model, "input": prompt, "text_format": schema}
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    elif temperature is not None:
        kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    if prompt_cache_key:
        kwargs["prompt_cache_key"] = prompt_cache_key

    for attempt in range(max_retries):
        try:
            response = await client.responses.parse(**kwargs)
        except (RateLimitError, InternalServerError, APIConnectionError, APITimeoutError) as exc:
            if attempt == max_retries - 1:
                log.warning("openai_error", model=model, attempt=attempt, error=str(exc))
                raise
            await asyncio.sleep(initial_backoff_s * (2**attempt))
            continue
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None)
            raise RuntimeError(f"OpenAI response incomplete: {reason}")
        return ModelResult(
            parsed=response.output_parsed,
            text=getattr(response, "output_text", None),
            usage=_usage(response),
        )
    raise RuntimeError("OpenAI call failed unexpectedly")
