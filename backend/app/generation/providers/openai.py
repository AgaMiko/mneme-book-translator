"""OpenAI provider (models named ``gpt-…``), used by fragment translation.

Like ``providers/gemini.py``, this is the only place that knows the vendor
SDK. It returns a ``ModelResult`` with the parsed schema object and usage in
the same keys the Gemini path stores (``prompt_token_count``,
``cached_content_token_count``, ``candidates_token_count``,
``thoughts_token_count``), so renditions, costs and comparisons treat both
providers the same way.

Caching: the part of the prompt that is the same for every call of a run
(rules, style sheet, glossary) is sent as its own input block that ends in an
explicit cache breakpoint, and ``prewarm_cache`` writes that cache once
before a run starts. Without the prewarm, all fragments start together, none
finds a cache, and nothing is ever read from it (0 cached tokens in the first
runs). OpenAI caches expire on their own (30 minutes); there is nothing to
delete.

Service tier: ``flex`` costs half of the standard price and answers more
slowly; at busy times it can refuse a request with 429, which is retried
with a longer wait.

Thinking: the translation thinking level ("minimal" … "high") is passed as
the reasoning effort. Reasoning models reject ``temperature``, so it is not
sent when an effort is set.
"""

from __future__ import annotations

import asyncio
import hashlib
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

# Flex requests can queue for a long time; OpenAI suggests timeouts of minutes.
_FLEX_TIMEOUT_S = 900
_FLEX_BACKOFF_S = 15.0


def is_openai_model(model: str) -> bool:
    return model.strip().lower().startswith(OPENAI_MODEL_PREFIXES)


def cache_key_for(prefix: str) -> str:
    """Stable ``prompt_cache_key``: the same fixed prefix gives the same key."""
    return "mneme-" + hashlib.sha256(prefix.encode()).hexdigest()[:24]


class OpenAIDisabledError(RuntimeError):
    """Raised when an OpenAI model is selected but OPENAI_API_KEY is not set."""


@dataclass(slots=True)
class ModelResult:
    parsed: Any | None
    text: str | None
    usage: dict[str, Any] | None


@lru_cache(maxsize=4)
def _get_client(api_key: str, timeout_s: float) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, timeout=timeout_s)


def _input(prefix: str | None, prompt: str) -> list[dict[str, Any]]:
    """User message: the cacheable prefix (ending in a breakpoint), then the rest."""
    content: list[dict[str, Any]] = []
    if prefix:
        content.append(
            {
                "type": "input_text",
                "text": prefix,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        )
    content.append({"type": "input_text", "text": prompt})
    return [{"role": "user", "content": content}]


def _usage(response: Any) -> dict[str, Any] | None:
    u = getattr(response, "usage", None)
    if u is None:
        return None
    reasoning = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None) or 0
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", None) or 0
    out = {
        "prompt_token_count": u.input_tokens,
        "cached_content_token_count": cached,
        "candidates_token_count": max(0, (u.output_tokens or 0) - reasoning),
        "thoughts_token_count": reasoning,
        "total_token_count": u.total_tokens,
    }
    tier = getattr(response, "service_tier", None)
    if tier:
        out["service_tier"] = tier
    return out


async def generate(
    *,
    prompt: str,
    schema: Any,
    settings: Settings,
    model: str,
    prefix: str | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
    prompt_cache_key: str | None = None,
    service_tier: str | None = None,
    timeout_s: int = 420,
    max_retries: int = 5,
    initial_backoff_s: float = 1.0,
) -> ModelResult:
    """Call an OpenAI model with a JSON-schema-constrained response.

    ``prefix`` is the part shared by every call of a run; it is sent first and
    marked as a cache breakpoint.
    """
    if not settings.OPENAI_API_KEY:
        raise OpenAIDisabledError("OPENAI_API_KEY is not configured.")
    flex = service_tier == "flex"
    client = _get_client(settings.OPENAI_API_KEY, float(_FLEX_TIMEOUT_S if flex else timeout_s))

    kwargs: dict[str, Any] = {
        "model": model,
        "input": _input(prefix, prompt),
        "text_format": schema,
    }
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    elif temperature is not None:
        kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    if prompt_cache_key:
        kwargs["prompt_cache_key"] = prompt_cache_key
    if service_tier:
        kwargs["service_tier"] = service_tier

    backoff = _FLEX_BACKOFF_S if flex else initial_backoff_s
    for attempt in range(max_retries):
        try:
            response = await client.responses.parse(**kwargs)
        except (RateLimitError, InternalServerError, APIConnectionError, APITimeoutError) as exc:
            if attempt == max_retries - 1:
                log.warning("openai_error", model=model, attempt=attempt, error=str(exc))
                raise
            await asyncio.sleep(backoff * (2**attempt))
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


async def prewarm_cache(*, settings: Settings, model: str, prefix: str) -> None:
    """Write the cache for ``prefix`` without generating output.

    Called once per run and model before the fragments start, so the first
    wave of parallel calls already reads the fixed part from the cache.
    """
    if not settings.OPENAI_API_KEY:
        raise OpenAIDisabledError("OPENAI_API_KEY is not configured.")
    client = _get_client(settings.OPENAI_API_KEY, 120.0)
    await client.responses.create(
        model=model,
        input=_input(prefix, "(cache prewarm)"),  # type: ignore[arg-type]
        prompt_cache_key=cache_key_for(prefix),
        prompt_cache_options={"prewarm": True},
    )
