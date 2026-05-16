"""Parse Gemini structured-output responses reliably.

The SDK sometimes leaves ``response.parsed`` and ``response.text`` empty
even when the HTTP call succeeded — blocked candidates, schema mismatch,
or text only on ``candidates[0].content.parts``. Chains should use
``parse_gemini_model`` instead of hand-rolling ``.parsed`` / ``.text``.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class EmptyGeminiResponseError(ValueError):
    """No parseable structured payload in a Gemini response."""

    def __init__(self, message: str, *, detail: str) -> None:
        super().__init__(message)
        self.detail = detail


def gemini_response_diagnostics(response: Any) -> str:
    """Human-readable snapshot for logs when parsing fails."""
    parts: list[str] = []
    candidates = getattr(response, "candidates", None) or []
    parts.append(f"candidates={len(candidates)}")
    if candidates:
        c0 = candidates[0]
        finish = getattr(c0, "finish_reason", None)
        if finish is not None:
            parts.append(f"finish_reason={finish}")
        for attr in ("safety_ratings", "citation_metadata"):
            val = getattr(c0, attr, None)
            if val:
                parts.append(f"{attr}={val!r}")
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block = getattr(prompt_feedback, "block_reason", None)
        if block:
            parts.append(f"prompt_block={block}")
    return "; ".join(parts) or "no diagnostics"


def gemini_response_text(response: Any) -> str | None:
    """Best-effort JSON text from a GenerateContentResponse."""
    text = getattr(response, "text", None)
    if text is not None:
        stripped = str(text).strip()
        if stripped:
            return stripped

    chunks: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(str(part_text))
    joined = "".join(chunks).strip()
    return joined or None


def parse_gemini_model(response: Any, schema: type[T]) -> T:
    """Return a validated model from ``response`` or raise with diagnostics."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, schema):
        return parsed

    raw = gemini_response_text(response)
    if raw:
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            detail = (
                f"{gemini_response_diagnostics(response)}; "
                f"raw_head={raw[:400]!r}; validate_err={exc}"
            )
            raise EmptyGeminiResponseError(
                f"Gemini JSON did not validate as {schema.__name__}",
                detail=detail,
            ) from exc

    detail = gemini_response_diagnostics(response)
    raise EmptyGeminiResponseError(
        f"Gemini returned no usable text for {schema.__name__}",
        detail=detail,
    )
