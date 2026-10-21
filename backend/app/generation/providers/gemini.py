"""Gemini provider.

Sole place that knows about the Google GenAI SDK shape: client
construction, retry/backoff, and response object handling. Chains call
``generate`` and stay oblivious to vendor specifics — if we ever swap to
a different provider, this is the only file that changes (alongside a new
sibling module under ``providers/``).
"""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError
from opentelemetry import trace as otel_trace_api

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

try:
    from langfuse import get_client as _langfuse_get_client

    _langfuse_get_client()
    log.info("langfuse_enabled_for_gemini")
except Exception:
    _langfuse_get_client = None  # type: ignore[assignment]
    log.exception("langfuse_unavailable_for_gemini")


def _langfuse_update_current_generation(
    *,
    model: str,
    response: types.GenerateContentResponse,
) -> None:
    """Attach model id and token usage to the active Langfuse generation span, if any."""
    if _langfuse_get_client is None:
        return
    span = otel_trace_api.get_current_span()
    if span is otel_trace_api.INVALID_SPAN or not span.is_recording():
        return

    usage_details: dict[str, int] = {}
    um = getattr(response, "usage_metadata", None)
    if um is not None:
        prompt_tokens = getattr(um, "prompt_token_count", None)
        candidates_tokens = getattr(um, "candidates_token_count", None)
        thoughts_tokens = getattr(um, "thoughts_token_count", None)
        cached_tokens = getattr(um, "cached_content_token_count", None)
        total_tokens = getattr(um, "total_token_count", None)

        if prompt_tokens is not None:
            usage_details["input"] = int(prompt_tokens)
        if candidates_tokens is not None or thoughts_tokens is not None:
            usage_details["output"] = int(candidates_tokens or 0) + int(thoughts_tokens or 0)
        if cached_tokens:
            usage_details["cache_read_input_tokens"] = int(cached_tokens)
        if not usage_details and total_tokens is not None:
            usage_details["total"] = int(total_tokens)

    client = _langfuse_get_client()
    client.update_current_generation(
        model=model,
        usage_details=usage_details or None,
    )


class GenerationDisabledError(RuntimeError):
    """Raised when an LLM call is requested but no provider key is configured.

    Callers can catch this to skip a step gracefully (e.g. proceed without
    metadata enrichment when the key is absent in dev environments).
    """


@lru_cache(maxsize=4)
def _get_client(api_key: str, timeout_ms: int) -> genai.Client:
    """Cached Gemini client.

    Keyed by ``(api_key, timeout_ms)`` so callers requesting different
    timeouts get distinct cached clients rather than fighting over a
    shared one.
    """
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )


def _log_gemini_api_error(
    exc: APIError,
    *,
    model: str,
    attempt: int,
) -> None:
    """Log everything Google returns; the generic exception string often omits nested detail."""
    payload: dict[str, Any] = {
        "model": model,
        "attempt": attempt,
        "code": exc.code,
        "status": exc.status,
        "message": exc.message,
        "details": exc.details,
    }
    resp = exc.response
    if resp is not None:
        payload["http_status"] = getattr(resp, "status_code", None)
        if hasattr(resp, "text"):
            try:
                text = resp.text
                if len(text) > 64_000:
                    text = f"{text[:64_000]}...<truncated>"
                payload["http_response_text"] = text
            except Exception:
                payload["http_response_text"] = "<unavailable>"
    try:
        payload["details_json"] = json.dumps(exc.details, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        payload["details_json"] = None
    log.error("gemini_api_error", **payload)


async def generate(
    *,
    prompt: str,
    schema: Any,
    settings: Settings,
    model: str,
    temperature: float = 0.1,
    timeout_s: int = 240,
    max_retries: int = 4,
    initial_backoff_s: float = 1.0,
    max_output_tokens: int | None = 8192,
    thinking_level: str | None = None,
    cached_content: str | None = None,
) -> types.GenerateContentResponse:
    """Call Gemini with a JSON-schema-constrained response.

    Retries on 5xx, 429 and dropped connections with exponential backoff. Other errors propagate
    immediately. Returns the raw SDK response — chain code is responsible
    for ``.parsed`` vs ``.text`` handling, since the right fallback depends
    on what each step considers an acceptable degradation.

    ``max_output_tokens`` defaults to 8192 so structured JSON responses are
    less likely to hit model output ceilings mid-object; pass ``None`` to
    omit the knob and use the API default.
    """
    if not settings.GEMINI_API_KEY:
        raise GenerationDisabledError("GEMINI_API_KEY is not configured.")

    client = _get_client(settings.GEMINI_API_KEY, timeout_s * 1000)

    config_kwargs: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_schema": schema,
        "temperature": temperature,
    }
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    if thinking_level:
        # "minimal" | "low" | "medium" | "high"; None keeps the model's default.
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel(thinking_level.upper())
        )
    if cached_content:
        # Name of an explicit cache (see ``create_cache``); its contents are
        # sent before ``prompt`` and billed at the cached-input rate.
        config_kwargs["cached_content"] = cached_content
    config = types.GenerateContentConfig(**config_kwargs)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            result = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            _langfuse_update_current_generation(model=model, response=result)
            return result
        except (ServerError, ClientError) as exc:
            last_exc = exc
            retryable = isinstance(exc, ServerError) or (
                isinstance(exc, ClientError) and exc.code == 429
            )
            if (not retryable) or attempt == max_retries - 1:
                _log_gemini_api_error(exc, model=model, attempt=attempt)
                raise
            await asyncio.sleep(initial_backoff_s * (2**attempt))
        except httpx.TransportError as exc:
            # Dropped or reset connections ("Server disconnected without sending
            # a response") happen on long runs; they are safe to retry.
            last_exc = exc
            if attempt == max_retries - 1:
                log.warning("gemini_transport_error", model=model, attempt=attempt, error=str(exc))
                raise
            await asyncio.sleep(initial_backoff_s * (2**attempt))

    raise RuntimeError("Gemini call failed unexpectedly") from last_exc


# ─── Explicit context caches ────────────────────────────
#
# A cache holds a prompt prefix that many calls share (for translation: the
# rules, style sheet and glossary). Cached tokens are billed at about 10% of
# the input price, plus storage per hour, so a cache must not outlive its
# run: callers delete it when done, every cache has an expiry time as a
# safety net, and ``delete_caches_with_prefix`` clears leftovers on startup.

_CACHE_TIMEOUT_MS = 120_000


async def create_cache(
    *,
    settings: Settings,
    model: str,
    text: str,
    display_name: str,
    ttl_s: int,
) -> str:
    """Create a cache holding ``text`` for ``model``; return its name."""
    if not settings.GEMINI_API_KEY:
        raise GenerationDisabledError("GEMINI_API_KEY is not configured.")
    client = _get_client(settings.GEMINI_API_KEY, _CACHE_TIMEOUT_MS)
    cache = await client.aio.caches.create(
        model=model,
        config=types.CreateCachedContentConfig(
            contents=[types.Content(role="user", parts=[types.Part(text=text)])],
            display_name=display_name,
            ttl=f"{ttl_s}s",
        ),
    )
    if not cache.name:
        raise RuntimeError("Gemini returned a cache without a name.")
    return cache.name


async def refresh_cache(*, settings: Settings, name: str, ttl_s: int) -> None:
    """Push a cache's expiry ``ttl_s`` seconds into the future."""
    if not settings.GEMINI_API_KEY:
        return
    client = _get_client(settings.GEMINI_API_KEY, _CACHE_TIMEOUT_MS)
    await client.aio.caches.update(
        name=name, config=types.UpdateCachedContentConfig(ttl=f"{ttl_s}s")
    )


async def delete_cache(*, settings: Settings, name: str) -> None:
    if not settings.GEMINI_API_KEY:
        return
    client = _get_client(settings.GEMINI_API_KEY, _CACHE_TIMEOUT_MS)
    await client.aio.caches.delete(name=name)


async def delete_caches_with_prefix(*, settings: Settings, prefix: str) -> int:
    """Delete every cache whose display name starts with ``prefix``."""
    if not settings.GEMINI_API_KEY:
        return 0
    client = _get_client(settings.GEMINI_API_KEY, _CACHE_TIMEOUT_MS)
    deleted = 0
    pager = await client.aio.caches.list()
    async for cache in pager:
        if cache.name and (cache.display_name or "").startswith(prefix):
            await client.aio.caches.delete(name=cache.name)
            deleted += 1
    return deleted
