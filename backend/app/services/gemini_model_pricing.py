"""Default USD pricing (paid tier) for Gemini models used in estimates.

Rates are per **million** input / output tokens. When Google changes prices,
update this table or set ``GEMINI_INPUT_PRICE_USD_PER_MTOK`` /
``GEMINI_OUTPUT_PRICE_USD_PER_MTOK`` in the environment to override.

Unknown models fall back to ``gemini-2.5-flash-lite`` pricing as a conservative
middle tier for Flash-class work.

Rates are paid-tier prices for prompts up to 200K tokens, from the Gemini
Developer API and Vertex AI pricing pages (checked 2026-10-21). Where a model
has a lower price until a cut-off date (3.6 to 3.8 Flash until 2026-12-31,
4 Argon until 2026-11-30), the table uses the later, higher price, so
estimates don't go up when the lower price ends.
"""

from __future__ import annotations

# (input USD / 1M tokens, output USD / 1M tokens)
_DEFAULT_FLASH_LITE = (0.10, 0.40)

# Longest keys first so ``gemini-3.1-flash-lite-preview`` matches before ``gemini-3``.
_MODEL_USD_PER_MTOK: list[tuple[str, tuple[float, float]]] = [
    # OpenAI models used for translation (standard tier, checked 2026-10-21).
    ("gpt-6-astra", (20.00, 75.00)),
    ("gpt-6.1-sol", (4.00, 15.00)),
    ("gpt-6-luna", (0.20, 0.75)),
    ("gemini-4-argon", (4.00, 20.00)),
    ("gemini-3.8-flash-cyber", (1.50, 7.50)),
    ("gemini-3.8-flash", (1.50, 7.50)),
    ("gemini-3.7-flash", (1.50, 7.50)),
    ("gemini-3.6-flash", (1.50, 7.50)),
    ("gemini-3.5-flash-lite", (0.30, 2.50)),
    ("gemini-3.5-flash", (1.50, 9.00)),
    ("gemini-3.1-flash-lite-preview", (0.25, 1.50)),
    ("gemini-3.1-flash-lite", (0.25, 1.50)),
    ("gemini-3-flash", (0.50, 3.00)),
    ("gemini-3.1-pro", (2.00, 12.00)),
    ("gemini-3-pro", (2.00, 12.00)),
    ("gemini-2.5-flash-lite", (0.10, 0.40)),
    ("gemini-2.5-flash", (0.30, 2.50)),
    ("gemini-2.0-flash-lite", (0.075, 0.30)),
    ("gemini-2.0-flash", (0.10, 0.40)),
    ("gemini-2.5-pro", (1.25, 10.00)),
    ("gemini-1.5-flash", (0.075, 0.30)),
    ("gemini-1.5-pro", (1.25, 5.00)),
]


# OpenAI Flex tier (half the standard price for Sol and Astra), 2026-10-21.
_OPENAI_FLEX_USD_PER_MTOK: list[tuple[str, tuple[float, float]]] = [
    ("gpt-6-astra", (10.00, 50.00)),
    ("gpt-6.1-sol", (2.00, 10.00)),
    ("gpt-6-luna", (0.10, 0.50)),
]


def resolve_flex_usd_per_million_tokens(model: str) -> tuple[float, float] | None:
    """Flex prices for an OpenAI model, or None when there is no Flex price."""
    key = model.strip().lower()
    for prefix, prices in _OPENAI_FLEX_USD_PER_MTOK:
        if prefix in key:
            return prices
    return None


def resolve_gemini_usd_per_million_tokens(model: str) -> tuple[float, float]:
    """Return (input_per_mtok, output_per_mtok) for ``model`` id."""
    key = model.strip().lower()
    for prefix, prices in _MODEL_USD_PER_MTOK:
        if prefix in key:
            return prices
    return _DEFAULT_FLASH_LITE
