"""LLM chain: extract manuscript metadata from the opening sample.

Single-step chain. Given the first ~1000 characters of a manuscript,
infer language, author, title, and a translator-facing style note.

Layering
--------
- Schema   ``prompt_manager/models/extract_metadata_model.py`` — the contract
- Prompt   ``prompt_manager/prompts/extract_metadata_prompt.py`` — task framing
- Provider ``providers/gemini.py`` — vendor SDK + retry/backoff

This module wires the three together. It contains no vendor-specific code
and no business logic beyond response shape disambiguation.

Observability
-------------
Wrapped with ``@observe`` so each invocation appears as a generation in
Langfuse. When ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` are unset
the decorator is a no-op — no errors, no traces sent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langfuse import observe

from app.generation.prompt_manager.models.extract_metadata_model import ManuscriptMetadata
from app.generation.prompt_manager.prompts.extract_metadata_prompt import PROMPT
from app.generation.providers.gemini import generate as gemini_generate

if TYPE_CHECKING:
    from app.core.config import Settings


@observe(name="extract_manuscript_metadata", as_type="generation")
async def extract_manuscript_metadata(
    *,
    sample: str,
    settings: Settings,
) -> ManuscriptMetadata:
    """Call Gemini and return validated manuscript metadata.

    The provider returns the raw SDK response; this function picks the
    parsed object when the SDK already deserialized into the schema, and
    falls back to ``model_validate_json`` on the raw text otherwise.
    Empty responses raise — this step has no graceful degradation, since
    metadata downstream affects how chapters are stored.
    """
    response = await gemini_generate(
        prompt=PROMPT.format(sample=sample),
        schema=ManuscriptMetadata,
        model=settings.GEMINI_MODEL,
        settings=settings,
        temperature=0.9,
    )

    if isinstance(response.parsed, ManuscriptMetadata):
        return response.parsed
    if response.text:
        return ManuscriptMetadata.model_validate_json(response.text)
    raise RuntimeError("Gemini returned an empty metadata response.")
