"""Unit tests for the cast pass: prompt text, validation, and briefs in translation prompts."""

from uuid import uuid4

from app.generation.prompt_manager.models.cast_voices_model import CastBriefs, PassageCheck
from app.generation.prompt_manager.prompts.translate_fragment_prompt import (
    VoiceRow,
    render_voices,
)
from app.generation.prompt_manager.prompts.translate_passage_prompt import render_voice_block
from app.services.voice_cast import (
    CastPassage,
    CastProfile,
    render_cast,
    validate_briefs,
    validate_flags,
)


def _profile(name: str, *, accepted: bool = False, passages: int = 1) -> CastProfile:
    return CastProfile(
        voice_id=uuid4(),
        name=name,
        accepted=accepted,
        line_count=10,
        features=[f"{name} feature"],
        shifts=["to Stein: softer"],
        strategy=f"{name} strategy",
        passages=[
            CastPassage(id=uuid4(), source=f"źródło {i}", english=f"english {i}", accepted=False)
            for i in range(passages)
        ],
    )


def test_render_for_briefs_shows_profiles_and_sources_only() -> None:
    mira, stein = _profile("Mira", passages=2), _profile("Stein", accepted=True)
    r = render_cast([mira, stein])
    assert r.codes == {"C1": mira, "C2": stein}
    assert list(r.passages) == ["P1", "P2", "P3"]
    assert "### C2 · Stein — 10 spoken lines · accepted by the author" in r.text
    assert "Current strategy:\nMira strategy" in r.text
    assert "źródło 0" in r.text
    assert "english 0" not in r.text


def test_render_for_check_shows_briefs_and_translations() -> None:
    mira = _profile("Mira", passages=1)
    r = render_cast([mira], briefs={mira.voice_id: "Voice: plain healer."})
    assert "Brief:\nVoice: plain healer." in r.text
    assert "Proposed translation:\nenglish 0" in r.text
    assert "Current strategy" not in r.text


def test_validate_briefs_matches_code_and_name() -> None:
    mira, stein = _profile("Mira"), _profile("Stein")
    r = render_cast([mira, stein])
    result = CastBriefs.model_validate(
        {
            "cast_notes": "Mira and Stein both spar.",
            "briefs": [
                {"character_code": "C1", "character_name": "mira", "brief": "Voice: plain."},
                {"character_code": "C2", "character_name": "Mira", "brief": "wrong name"},
            ],
        }
    )
    assert validate_briefs(result, r) == {mira.voice_id: "Voice: plain."}


def test_validate_flags_keeps_open_passages_with_a_revision() -> None:
    mira, stein = _profile("Mira"), _profile("Stein")
    stein.passages.append(CastPassage(id=uuid4(), source="s", english="e", accepted=True))
    r = render_cast([mira, stein], briefs={})  # P1 Mira, P2 Stein, P3 Stein accepted
    result = PassageCheck.model_validate(
        {
            "passage_flags": [
                {
                    "passage": "p 1",
                    "problem": "flattened",
                    "reason": "Echo question expanded.",
                    "revised_translation": "Exploded?",
                },
                {
                    "passage": "P3",
                    "problem": "off_brief",
                    "reason": "x",
                    "revised_translation": "x",
                },
                {
                    "passage": "P9",
                    "problem": "off_brief",
                    "reason": "x",
                    "revised_translation": "x",
                },
                {
                    "passage": "P2",
                    "problem": "sounds_like_other",
                    "reason": "no text",
                    "revised_translation": " ",
                },
            ]
        }
    )
    assert validate_flags(result, r) == {
        mira.passages[0].id: ("Flattened: Echo question expanded.", "Exploded?")
    }


def test_passage_translation_uses_brief_when_set() -> None:
    assert render_voice_block(observation="o", strategy="s", brief="Voice: plain.") == (
        "### Voice brief\n\nVoice: plain."
    )
    assert "### Target voice strategy\n\ns" in render_voice_block(
        observation="o", strategy="s", brief=None
    )


def test_translation_prompt_sends_brief_instead_of_full_profile() -> None:
    text = render_voices(
        [
            VoiceRow(name="Mira", observation="long obs", strategy="long strat", brief="1. Short."),
            VoiceRow(name="Stein", observation="obs", strategy="strat"),
        ]
    )
    assert "### Mira\n\nVoice brief (how they come across):\n1. Short." in text
    assert "long obs" not in text
    assert "long strat" not in text
    assert "Target voice strategy (how to render it):\nstrat" in text


def test_pick_sample_spreads_and_prefers_named_longer_lines() -> None:
    from app.services.voice_cast import pick_sample
    from app.services.voice_profiles import SpokenLine

    def line(i: int, words: int, *, inferred: bool = False) -> SpokenLine:
        return SpokenLine(
            paragraph_id=uuid4(),
            line_index=i,
            chapter_id=uuid4(),
            chapter_number=i // 10 + 1,
            kind="speech",
            text=" ".join(["słowo"] * words),
            inferred=inferred,
        )

    lines = [line(i, 2) for i in range(10)] + [line(10 + i, 8) for i in range(30)]
    lines += [line(40 + i, 8, inferred=True) for i in range(10)]
    picked = pick_sample(lines, 6)
    assert len(picked) == 6
    assert all(p.count("słowo") == 8 for p in picked)
    assert picked[0].startswith("[ch. 2]")
    assert pick_sample(lines[:3], 6) == [f"[ch. 1] {ln.text}" for ln in lines[:3]]
