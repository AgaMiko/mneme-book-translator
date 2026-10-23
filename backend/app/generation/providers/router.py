"""Send a structured-output call to the provider that serves the model.

Models named ``gpt-…`` go to OpenAI, everything else to Gemini. Every step
except fragment translation (which manages its own caching) calls models
through here, so any step can run on any supported model. Each call's real
cost goes to Langfuse and to the counting run (``app.generation.usage``).

``thinking`` is the Gemini thinking level or the OpenAI reasoning effort
("minimal" | "low" | "medium" | "high"); None keeps the model's default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.generation.client import GenerationDisabledError
from app.generation.providers.gemini import generate as gemini_generate
from app.generation.providers.openai import (
    ModelResult,
    OpenAIDisabledError,
    is_openai_model,
)
from app.generation.providers.openai import generate as openai_generate
from app.generation.usage import gemini_usage, record_call

if TYPE_CHECKING:
    from app.core.config import Settings


async def generate_structured(
    *,
    prompt: str,
    schema: Any,
    model: str,
    settings: Settings,
    temperature: float = 0.1,
    thinking: str | None = None,
    max_output_tokens: int | None = 8192,
    service_tier: str | None = None,
) -> ModelResult:
    if is_openai_model(model):
        try:
            result = await openai_generate(
                prompt=prompt,
                schema=schema,
                model=model,
                settings=settings,
                temperature=temperature,
                reasoning_effort=thinking,
                service_tier=service_tier,
            )
        except OpenAIDisabledError as exc:
            # Background jobs already handle this one: the run fails with the reason.
            raise GenerationDisabledError(str(exc)) from exc
        record_call(model, result.usage, result.service_tier)
        return result
    response = await gemini_generate(
        prompt=prompt,
        schema=schema,
        model=model,
        settings=settings,
        temperature=temperature,
        thinking_level=thinking,
        max_output_tokens=max_output_tokens,
    )
    usage = gemini_usage(response)
    record_call(model, usage, None)
    return ModelResult(parsed=response.parsed, text=response.text, usage=usage)


def parse_result[T](result: ModelResult, schema: type[T], what: str) -> T:
    """The parsed object, or the JSON text validated against ``schema``."""
    if isinstance(result.parsed, schema):
        return result.parsed
    if result.text:
        return schema.model_validate_json(result.text)  # type: ignore[attr-defined]
    raise RuntimeError(f"The model returned an empty response for {what}.")
