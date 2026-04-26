"""Glossary enum labels and legacy ``term_type`` normalization for API + persistence.

Canonical literals live in ``extract_glossary_model``; labels and select-option
payloads are derived here so the working-glossary endpoint stays the single
source of truth for the review UI.
"""

from __future__ import annotations

from typing import get_args

from app.generation.prompt_manager.models.extract_glossary_model import (
    TermType,
    TranslationSuggestion,
)

_CANONICAL_TERM_TYPES = frozenset(get_args(TermType))

TERM_TYPE_LABELS: dict[str, str] = {
    "character_name": "Character",
    "place_name": "Place",
    "organization": "Organization",
    "lore_term": "Lore",
    "cultural_term": "Cultural",
    "specialized_usage": "Specialized",
    "other": "Other",
}

TRANSLATION_SUGGESTION_LABELS: dict[str, str] = {
    "keep_original": "Keep original",
    "translate": "Translate",
}

if set(TERM_TYPE_LABELS) != _CANONICAL_TERM_TYPES:
    raise RuntimeError("TERM_TYPE_LABELS keys must match TermType Literal")
if set(TRANSLATION_SUGGESTION_LABELS) != frozenset(get_args(TranslationSuggestion)):
    raise RuntimeError(
        "TRANSLATION_SUGGESTION_LABELS keys must match TranslationSuggestion Literal",
    )


def normalize_stored_term_type(raw: str) -> str:
    """Map DB / legacy extraction values onto the current ``TermType`` set."""
    if raw == "magic_term":
        return "lore_term"
    if raw in _CANONICAL_TERM_TYPES:
        return raw
    return "other"


def term_type_select_options() -> list[dict[str, str]]:
    return [{"id": t, "label": TERM_TYPE_LABELS[t]} for t in get_args(TermType)]


def translation_suggestion_select_options() -> list[dict[str, str]]:
    return [
        {"id": t, "label": TRANSLATION_SUGGESTION_LABELS[t]}
        for t in get_args(TranslationSuggestion)
    ]
