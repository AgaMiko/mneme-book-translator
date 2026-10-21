"""Tests for the pure parts of fragment translation."""

from uuid import uuid4

from app.core.config import Settings
from app.generation.chains.translate_fragment_chain import _alignment_problem, stage_model
from app.generation.prompt_manager.models.translate_fragment_model import ParagraphOut
from app.services.fragmenter import ChapterInput, ParagraphInput, plan_fragments
from app.services.translation_estimate import estimate_translation
from app.services.translation_qa import hard_checks, style_metrics
from app.services.translation_service import speakers_for_range


def _para(words: int, text: str | None = None) -> ParagraphInput:
    return ParagraphInput(
        id=uuid4(), text=text if text is not None else " ".join(["słowo"] * words)
    )


def test_fragments_never_cross_chapters() -> None:
    ch1 = ChapterInput(id=uuid4(), paragraphs=[_para(300) for _ in range(3)])
    ch2 = ChapterInput(id=uuid4(), paragraphs=[_para(300) for _ in range(3)])
    plans = plan_fragments([ch1, ch2])
    assert [p.chapter_id for p in plans] == [ch1.id, ch2.id]
    assert plans[1].start_word_offset == 900


def test_fragments_cut_at_target_and_merge_short_tail() -> None:
    ch = ChapterInput(id=uuid4(), paragraphs=[_para(400) for _ in range(7)])  # 2,800 words
    plans = plan_fragments([ch], target_words=1200, min_tail_words=500)
    assert [p.word_count for p in plans] == [1200, 1600]  # 400-word tail joins the 2nd


def test_fragments_cut_early_at_scene_break() -> None:
    paras = [_para(400), _para(400), _para(0, "***"), _para(400)]
    plans = plan_fragments([ChapterInput(id=uuid4(), paragraphs=paras)], min_tail_words=100)
    assert len(plans) == 2
    assert plans[1].paragraph_ids[0] == paras[2].id


def test_style_metrics_counts_narration_only() -> None:
    m = style_metrics(
        [
            '"She said she would come," Mira said. She walked to the door. '
            "He followed her out. The wind rose… and a wave of cold hit them."
        ]
    )
    assert m.narration_sentences == 4
    assert m.she_he_openers == 2
    assert m.ellipses == 1
    assert m.stock == {"a wave of": 1}


def test_hard_checks_find_leftover_polish_and_placeholders() -> None:
    issues = hard_checks(
        source=[("a", "Miro, chodź. xxxxxxx"), ("b", "\u2013 Tak.")],
        target=[("a", "Miro, come here. Elżka waited."), ("b", "\u2013 Yes.")],
        source_language="pl",
        allowed_words={"Elżka"},
    )
    checks = {(i.check, i.paragraph_id) for i in issues}
    assert ("placeholder", "a") in checks
    assert ("dialogue_dash", "b") in checks
    assert not any(i.check == "source_letters" for i in issues)

    issues = hard_checks(
        source=[("a", "Einardzie!")],
        target=[("a", "Einardzie!")],
        source_language="pl",
    )
    assert any(i.check == "source_letters" for i in issues) is False  # no Polish letters
    issues = hard_checks(
        source=[("a", "Łąka")], target=[("a", "The Łąka meadow")], source_language="pl"
    )
    assert [i.check for i in issues] == ["source_letters"]


def test_alignment_problem() -> None:
    ok = [ParagraphOut(paragraph_id="p1", text="a"), ParagraphOut(paragraph_id="p2", text="b")]
    assert _alignment_problem(ok, ["p1", "p2"]) is None
    assert "missing: p2" in (_alignment_problem(ok[:1], ["p1", "p2"]) or "")
    assert "wrong order" in (_alignment_problem(ok[::-1], ["p1", "p2"]) or "")


def test_speakers_for_range_uses_voice_window_geometry() -> None:
    a, b = uuid4(), uuid4()
    windows = {1: {a}, 3: {b}}  # window 1: words 0-499, window 3: 800-1299
    assert speakers_for_range(windows, start=0, word_count=100) == {a}
    assert speakers_for_range(windows, start=900, word_count=100) == {b}
    assert speakers_for_range(windows, start=450, word_count=400) == {a, b}


def test_stage_model_fallbacks() -> None:
    s = Settings(GEMINI_MODEL="base", TRANSLATION_MODEL=None, TRANSLATION_POLISH_MODEL="pro")
    assert stage_model(s, "faithful") == "base"
    assert stage_model(s, "polish") == "pro"
    s2 = Settings(GEMINI_MODEL="base", TRANSLATION_MODEL="mid")
    assert stage_model(s2, "line_edit") == "mid"


def test_estimate_scales_with_words() -> None:
    s = Settings(GEMINI_MODEL="gemini-3.1-flash-lite-preview")
    small = estimate_translation(
        word_count=1000, fragment_count=None, glossary_terms=50, settings=s
    )
    big = estimate_translation(
        word_count=100_000, fragment_count=None, glossary_terms=50, settings=s
    )
    assert small.fragment_count == 1
    assert big.fragment_count == 84
    assert big.cost_usd > small.cost_usd
    assert [st.stage for st in big.stages] == ["faithful", "line_edit", "polish"]


def test_repetitions_skip_names_glossary_and_function_words() -> None:
    from app.services.translation_qa import find_repetitions

    paras = [
        ("p1", "The lantern swayed. Mira watched the lantern. Mira smiled at the Weaver."),
        ("p2", "The Weaver nodded, and the Weaver left."),
    ]
    words = [r.word for r in find_repetitions(paras, ignore={"Weaver"})]
    assert words == ["lantern"]


def test_even_runs_found_and_short_sentences_break_them() -> None:
    from app.services.translation_qa import find_even_runs

    even = "One two three four five six seven. " * 4
    assert len(find_even_runs([("p1", even.strip())])) == 1
    varied = (
        "One two three four five six seven. Stop. "
        "One two three four five six seven eight nine ten eleven twelve thirteen fourteen. "
        "One two three four five six seven."
    )
    assert find_even_runs([("p1", varied)]) == []


def test_estimate_counts_thinking_for_non_lite_models() -> None:
    lite = Settings(GEMINI_MODEL="gemini-3.1-flash-lite-preview")
    flash = Settings(
        GEMINI_MODEL="gemini-3.8-flash",
        TRANSLATION_THINKING_FAITHFUL="",
        TRANSLATION_THINKING_LINE_EDIT="",
        TRANSLATION_THINKING_POLISH="",
    )
    a = estimate_translation(
        word_count=10_000, fragment_count=None, glossary_terms=50, settings=lite
    )
    b = estimate_translation(
        word_count=10_000, fragment_count=None, glossary_terms=50, settings=flash
    )
    # Default thinking adds about 3.2x the visible output; Flash-Lite adds none.
    assert 4.1 < b.stages[0].output_tokens / a.stages[0].output_tokens < 4.3
    high = Settings(GEMINI_MODEL="gemini-3.8-flash")  # default: high thinking everywhere
    c = estimate_translation(
        word_count=10_000, fragment_count=None, glossary_terms=50, settings=high
    )
    assert c.cost_usd > b.cost_usd
    no_cache = Settings(GEMINI_MODEL="gemini-3.8-flash", TRANSLATION_CACHE=False)
    d = estimate_translation(
        word_count=10_000, fragment_count=None, glossary_terms=50, settings=no_cache
    )
    assert d.cost_usd > c.cost_usd


def test_fixed_context_has_nothing_fragment_specific() -> None:
    from app.generation.prompt_manager.prompts.translate_fragment_prompt import (
        GlossaryRow,
        build_faithful_prompt,
        render_fixed_context,
        render_fragment_context,
    )

    glossary = [GlossaryRow("Pył", "Dust", "translate_literally", [], None)]
    fixed = render_fixed_context(
        book_title="Zaplataczka",
        source_language="Polish",
        target_language="English",
        glossary=glossary,
    )
    assert "Dust" in fixed
    assert "Chapter 5" not in fixed
    context = render_fragment_context(
        chapter_title="Chapter 5", voices=[], previous_source="", previous_target="", next_source=""
    )
    rest = build_faithful_prompt(
        context=context, target_language="English", source=[("p1", "Tak.")]
    )
    assert "Chapter 5" in rest
    assert "Accepted glossary" not in rest  # the fixed part is sent separately or cached


def test_stage_thinking_levels() -> None:
    from app.generation.chains.translate_fragment_chain import stage_thinking

    s = Settings(GEMINI_MODEL="m")
    assert [stage_thinking(s, st) for st in ("faithful", "line_edit", "polish")] == ["high"] * 3
    assert (
        stage_thinking(Settings(GEMINI_MODEL="m", TRANSLATION_THINKING_POLISH=""), "polish") is None
    )


async def test_run_caches_are_deleted_on_close(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.services import translation_cache

    created: list[str] = []
    deleted: list[str] = []

    async def fake_create(**kwargs):  # type: ignore[no-untyped-def]
        if kwargs["model"] == "broken":
            raise RuntimeError("caching not supported")
        name = f"cachedContents/{kwargs['model']}"
        created.append(name)
        return name

    async def fake_delete(*, settings, name):  # type: ignore[no-untyped-def]
        deleted.append(name)

    monkeypatch.setattr(translation_cache, "create_cache", fake_create)
    monkeypatch.setattr(translation_cache, "delete_cache", fake_delete)
    s = Settings(GEMINI_MODEL="m", GEMINI_API_KEY="k")
    caches = await translation_cache.RunCaches.open(
        settings=s, run_id=uuid4(), fixed_context="rules", models={"flash", "broken"}
    )
    assert caches.name_for("flash") == "cachedContents/flash"
    assert caches.name_for("broken") is None  # falls back to sending the text
    await caches.close()
    assert deleted == created == ["cachedContents/flash"]

    off = await translation_cache.RunCaches.open(
        settings=Settings(GEMINI_MODEL="m", TRANSLATION_CACHE=False),
        run_id=uuid4(),
        fixed_context="rules",
        models={"flash"},
    )
    assert off.name_for("flash") is None
    await off.close()
