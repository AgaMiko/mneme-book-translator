"""Source languages: prompts carry no source-language examples; checks use each language's letters."""

from __future__ import annotations

import importlib
import pkgutil
import re

import pytest

import app.generation.prompt_manager.models as models_pkg
import app.generation.prompt_manager.prompts as prompts_pkg
from app.constants.languages import (
    SUPPORTED_SOURCE_LANGUAGES,
    WORD,
    language_name,
    resolve_source_language,
    source_letters,
)
from app.generation.prompt_manager.prompts.translate_fragment_prompt import render_fixed_context
from app.services.narration_pov import CHAPTER_LINE
from app.services.term_matching import TermIndex, find_terms
from app.services.translation_qa import hard_checks


def _module_text(package: object) -> dict[str, str]:
    """Every upper-case string constant, plus pydantic field descriptions, per module."""
    out: dict[str, str] = {}
    for m in pkgutil.iter_modules(package.__path__):  # type: ignore[attr-defined]
        mod = importlib.import_module(f"{package.__name__}.{m.name}")  # type: ignore[attr-defined]
        parts = [v for k, v in vars(mod).items() if k.isupper() and isinstance(v, str)]
        for v in vars(mod).values():
            for f in getattr(v, "model_fields", {}).values():
                if f.description:
                    parts.append(f.description)
        out[m.name] = "\n".join(parts)
    return out


# Polish words and Zaplataczka names that used to sit in the prompts as examples.
_EXAMPLE_LEFTOVERS = re.compile(
    r"Polish|Rozdział|proszę|katastrofa|wymusić|kwiat|powiedział|rzucił|miecz|"
    r"-że|\bpan\b|'ino'|toż|Mirze|Miro\b|Mira\b|Stein|Einard|Aurel|Agata|Pył|weave"
)


@pytest.mark.parametrize("package", [prompts_pkg, models_pkg])
def test_prompts_carry_no_source_language_examples(package: object) -> None:
    for name, text in _module_text(package).items():
        # The metadata schema names languages as examples of its output format.
        text = text.replace("'Polish', 'English'", "")
        found = _EXAMPLE_LEFTOVERS.findall(text)
        assert not found, f"{name}: {found}"


def test_language_names() -> None:
    assert set(SUPPORTED_SOURCE_LANGUAGES) == {"pl", "de", "kn"}
    assert language_name("pl") == "Polish"
    assert language_name("Polish") == "Polish"
    assert language_name("DE") == "German"
    assert language_name("en") == "English"
    assert language_name("Finnish") == "Finnish"
    assert language_name(None) == "the source language"


def test_fixed_context_names_the_source_language() -> None:
    fixed = render_fixed_context(
        book_title="Buch", source_language="de", target_language="English", glossary=[]
    )
    assert "translating from German into English" in fixed


def test_leftover_letters_follow_the_source_language() -> None:
    assert source_letters("Finnish") == ""
    issues = hard_checks(
        source=[("a", "x")], target=[("a", "The Mädchen ran.")], source_language="de"
    )
    assert [i.check for i in issues] == ["source_letters"]
    issues = hard_checks(
        source=[("a", "x")], target=[("a", "She said ಹೇಳಿದಳು.")], source_language="kn"
    )
    assert [i.check for i in issues] == ["source_letters"]
    assert hard_checks(source=[("a", "x")], target=[("a", "Mädchen")], source_language="pl") == []


def test_kannada_words_stay_whole() -> None:
    # \w alone would split these at every vowel sign.
    assert WORD.findall("ರಾಮನಿಗೆ ಹೇಳಿದಳು.") == ["ರಾಮನಿಗೆ", "ಹೇಳಿದಳು"]
    index = TermIndex.build([("t1", "ಹೇಳಿದಳು", [])])
    text = "ಅವಳು ಹೇಳಿದಳು."
    [(term_id, start, end)] = find_terms(text, index)
    assert (term_id, text[start:end]) == ("t1", "ಹೇಳಿದಳು")


def test_detected_language_wins_over_the_upload_default() -> None:
    # Uploads default to "pl"; metadata extraction reads the real language.
    assert resolve_source_language("pl", "German") == "de"
    assert resolve_source_language("pl", "Polish") == "pl"
    assert resolve_source_language("de", None) == "de"
    assert resolve_source_language("pl", "Finnish") == "Finnish"


def test_chapter_lines_in_every_known_language() -> None:
    for line in ("Rozdział 4", "Rozdzial 12. Tytuł", "Kapitel IV", "Chapter 3"):
        assert CHAPTER_LINE.match(line), line
    for line in ("Chapter Mira", "Prolog", "Mira"):
        assert not CHAPTER_LINE.match(line), line
