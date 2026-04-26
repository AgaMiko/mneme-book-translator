"""Shared LLM provider plumbing.

A single Gemini client is reused across calls. We treat "no API key" as
a soft state: callers can decide whether to skip a step gracefully or
surface the error.
"""

from __future__ import annotations

from functools import lru_cache

from google import genai


class GenerationDisabledError(RuntimeError):
    """Raised when an LLM call is requested but no provider is configured."""


@lru_cache(maxsize=1)
def _build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def get_client(api_key: str | None) -> genai.Client:
    """Return a cached Gemini client, or raise when no key is configured."""
    if not api_key:
        raise GenerationDisabledError("GEMINI_API_KEY is not configured.")
    return _build_client(api_key)
