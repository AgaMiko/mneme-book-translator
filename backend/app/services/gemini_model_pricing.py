"""Default USD pricing (paid tier) for Gemini models used in estimates.

Rates are per **million** input / output tokens. When Google changes prices,
update this table or set ``GEMINI_INPUT_PRICE_USD_PER_MTOK`` /
``GEMINI_OUTPUT_PRICE_USD_PER_MTOK`` in the environment to override.

Unknown models fall back to ``gemini-2.5-flash-lite`` pricing as a conservative
middle tier for Flash-class work.
"""

from __future__ import annotations

# (input USD / 1M tokens, output USD / 1M tokens)
_DEFAULT_FLASH_LITE = (0.10, 0.40)

# Longest keys first so ``gemini-3.1-flash-lite-preview`` matches before ``gemini-3``.
_MODEL_USD_PER_MTOK: list[tuple[str, tuple[float, float]]] = [
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


def resolve_gemini_usd_per_million_tokens(model: str) -> tuple[float, float]:
    """Return (input_per_mtok, output_per_mtok) for ``model`` id."""
    key = model.strip().lower()
    for prefix, prices in _MODEL_USD_PER_MTOK:
        if prefix in key:
            return prices
    return _DEFAULT_FLASH_LITE
