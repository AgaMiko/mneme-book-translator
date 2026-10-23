"""Models the author can pick for each pipeline step, and the recommended one.

Only text models that return structured JSON are offered: from Google's list,
the Flash, Flash-Lite and Pro models (not Live, TTS, image, transcription or
Omni, which have no price here); from OpenAI, the three gpt-6 models.

Recommendations (2026-10-23): gpt-6.1-sol everywhere. For translation it won
the blind tests on Zaplataczka chapters 3 and 5. For the other steps it is
the author's best guess and has not been compared with other models yet;
the notes say so in the app.

The frontend reads all of this from ``GET /models``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class ModelOption:
    id: str
    label: str
    provider: Literal["openai", "gemini"]


MODEL_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption("gpt-6.1-sol", "GPT-6.1 Sol", "openai"),
    ModelOption("gpt-6-astra", "GPT-6 Astra", "openai"),
    ModelOption("gpt-6-luna", "GPT-6 Luna", "openai"),
    ModelOption("gemini-3.1-pro-preview", "Gemini 3.1 Pro", "gemini"),
    ModelOption("gemini-3.8-flash", "Gemini 3.8 Flash", "gemini"),
    ModelOption("gemini-3.6-flash", "Gemini 3.6 Flash", "gemini"),
    ModelOption("gemini-3-flash-preview", "Gemini 3 Flash", "gemini"),
    ModelOption("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "gemini"),
    ModelOption("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "gemini"),
)
MODEL_IDS = frozenset(m.id for m in MODEL_OPTIONS)

Step = Literal["glossary", "glossary_review", "speakers", "voices", "translation"]
STEPS: tuple[Step, ...] = get_args(Step)

# The settings field that holds each step's model.
STEP_SETTING: dict[Step, str] = {
    "glossary": "GLOSSARY_MODEL",
    "glossary_review": "GLOSSARY_REVIEW_MODEL",
    "speakers": "SPEAKERS_MODEL",
    "voices": "VOICES_MODEL",
    "translation": "TRANSLATION_MODEL",
}

_GUESS = "Best guess: Sol won the translation tests. Not yet compared on this step."
RECOMMENDED: dict[Step, tuple[str, str]] = {
    "glossary": ("gpt-6.1-sol", _GUESS),
    "glossary_review": (
        "gpt-6.1-sol",
        _GUESS + " Gemini 3.1 Flash-Lite agreed with your past decisions 87-88% of the time.",
    ),
    "speakers": ("gpt-6.1-sol", _GUESS),
    "voices": ("gpt-6.1-sol", _GUESS),
    "translation": ("gpt-6.1-sol", "Won the blind tests on Zaplataczka chapters 3 and 5."),
}


class UnknownModelError(ValueError):
    """The requested model is not one of ``MODEL_OPTIONS``."""


def default_model(settings: Settings, step: Step) -> str:
    return str(getattr(settings, STEP_SETTING[step]) or RECOMMENDED[step][0])


def settings_for_step(settings: Settings, step: Step, model: str | None) -> Settings:
    """``settings`` with ``model`` as the step's model, for one run or estimate.

    No model keeps the configured one. For translation the choice replaces
    every stage's model, since the app offers one model for the whole run.
    """
    if not model:
        return settings
    if model not in MODEL_IDS:
        raise UnknownModelError(f"Unknown model {model!r}.")
    update = {STEP_SETTING[step]: model}
    if step == "translation":
        update |= {
            "TRANSLATION_FAITHFUL_MODEL": model,
            "TRANSLATION_LINE_EDIT_MODEL": model,
            "TRANSLATION_POLISH_MODEL": model,
        }
    return settings.model_copy(update=update)
