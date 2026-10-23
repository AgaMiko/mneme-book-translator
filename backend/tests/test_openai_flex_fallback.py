"""When OpenAI's Flex tier is unavailable, the call runs on the standard tier."""

from types import SimpleNamespace
from typing import Any

import httpx
from openai import RateLimitError

from app.core.config import Settings
from app.generation.providers import openai as provider


def _refusal(code: str) -> RateLimitError:
    body = {"message": "Flex processing is temporarily unavailable.", "code": code}
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return RateLimitError(
        "Error code: 429",
        response=httpx.Response(429, request=request, json={"error": body}),
        body=body,
    )


class _Responses:
    def __init__(self) -> None:
        self.tiers: list[str | None] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.tiers.append(kwargs.get("service_tier"))
        if kwargs.get("service_tier") == "flex":
            raise _refusal("flex_unavailable")
        return SimpleNamespace(
            status="completed", output_parsed={"ok": True}, output_text=None, usage=None
        )


async def test_flex_unavailable_falls_back_to_standard(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = _Responses()
    monkeypatch.setattr(provider, "_get_client", lambda *_a: SimpleNamespace(responses=responses))
    result = await provider.generate(
        prompt="p",
        schema=dict,
        settings=Settings(OPENAI_API_KEY="test"),
        model="gpt-6.1-sol",
        service_tier="flex",
    )
    assert responses.tiers == ["flex", None]
    assert result.parsed == {"ok": True}
    assert result.service_tier is None  # so the call is priced at the standard rate
