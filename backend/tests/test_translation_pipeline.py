"""Tests for the pure parts of fragment translation."""

from uuid import uuid4

from app.core.config import Settings
from app.generation.chains.translate_fragment_chain import _alignment_problem, stage_model
from app.generation.prompt_manager.models.translate_fragment_model import ParagraphOut
from app.models.book import Book
from app.services.fragmenter import ChapterInput, ParagraphInput, plan_fragments
from app.services.translation_estimate import estimate_translation
from app.services.translation_qa import hard_checks, style_metrics
from app.services.translation_service import missing_prerequisites, speakers_for_range


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
    s = Settings(
        GEMINI_MODEL="base",
        TRANSLATION_MODEL=None,
        TRANSLATION_FAITHFUL_MODEL=None,
        TRANSLATION_POLISH_MODEL="pro",
    )
    assert stage_model(s, "faithful") == "base"
    assert stage_model(s, "polish") == "pro"
    s2 = Settings(GEMINI_MODEL="base", TRANSLATION_MODEL="mid", TRANSLATION_FAITHFUL_MODEL=None)
    assert stage_model(s2, "line_edit") == "mid"


def test_estimate_scales_with_words() -> None:
    s = Settings(
        GEMINI_MODEL="gemini-3.1-flash-lite-preview",
        TRANSLATION_MODEL=None,
        TRANSLATION_FAITHFUL_MODEL=None,
        TRANSLATION_STAGE_COUNT=3,
    )
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
    gemini_only = {"TRANSLATION_MODEL": None, "TRANSLATION_FAITHFUL_MODEL": None}
    lite = Settings(GEMINI_MODEL="gemini-3.1-flash-lite-preview", **gemini_only)
    flash = Settings(
        GEMINI_MODEL="gemini-3.8-flash",
        **gemini_only,
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
    high = Settings(GEMINI_MODEL="gemini-3.8-flash", **gemini_only)  # high thinking everywhere
    c = estimate_translation(
        word_count=10_000, fragment_count=None, glossary_terms=50, settings=high
    )
    assert c.cost_usd > b.cost_usd
    no_cache = Settings(GEMINI_MODEL="gemini-3.8-flash", **gemini_only, TRANSLATION_CACHE=False)
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

    async def fake_prewarm(*, settings, model, prefix):  # type: ignore[no-untyped-def]
        raise AssertionError("no OpenAI model in this test")

    monkeypatch.setattr(translation_cache, "create_cache", fake_create)
    monkeypatch.setattr(translation_cache, "delete_cache", fake_delete)
    monkeypatch.setattr(translation_cache, "prewarm_cache", fake_prewarm)
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


def test_openai_models_are_recognised() -> None:
    from app.generation.providers.openai import is_openai_model

    assert is_openai_model("gpt-6-luna")
    assert is_openai_model("GPT-6.1-sol")
    assert not is_openai_model("gemini-3.8-flash")


async def test_gpt_models_go_to_openai_with_reasoning_effort(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.generation.chains import translate_fragment_chain as chain
    from app.generation.prompt_manager.models.translate_fragment_model import (
        FaithfulFragment,
        ParagraphOut,
    )
    from app.generation.providers.openai import ModelResult

    calls: list[dict] = []  # type: ignore[type-arg]

    async def fake_openai(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        out = FaithfulFragment(paragraphs=[ParagraphOut(paragraph_id="p1", text="Yes.")])
        return ModelResult(parsed=out, text=None, usage={"prompt_token_count": 10})

    async def fail_gemini(**kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Gemini must not be called for a gpt model")

    monkeypatch.setattr(chain, "openai_generate", fake_openai)
    monkeypatch.setattr(chain, "gemini_generate", fail_gemini)
    s = Settings(GEMINI_MODEL="gemini-3.8-flash", TRANSLATION_MODEL="gpt-6-luna")
    result = await chain.translate_fragment_faithful(
        fixed_context="RULES",
        cached_content=None,
        context="ctx",
        source=[("p1", "Tak.")],
        target_language="English",
        settings=s,
    )
    assert result.model == "gpt-6-luna"
    assert result.output.paragraphs[0].text == "Yes."
    assert calls[0]["reasoning_effort"] == "high"
    assert calls[0]["prefix"] == "RULES"  # sent as its own cacheable block
    assert "RULES" not in calls[0]["prompt"]
    assert calls[0]["prompt_cache_key"].startswith("mneme-")
    assert calls[0]["service_tier"] == "flex"


def test_openai_usage_maps_to_gemini_keys() -> None:
    from types import SimpleNamespace

    from app.generation.providers.openai import _usage

    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1000,
            input_tokens_details=SimpleNamespace(cached_tokens=600),
            output_tokens=900,
            output_tokens_details=SimpleNamespace(reasoning_tokens=700),
            total_tokens=1900,
        )
    )
    assert _usage(response) == {
        "prompt_token_count": 1000,
        "cached_content_token_count": 600,
        "candidates_token_count": 200,
        "thoughts_token_count": 700,
        "total_token_count": 1900,
    }


def test_only_case_forms_count_as_glossary_variants() -> None:
    from app.services.translation_service import is_form_of

    for canonical, variant in [
        ("Mira", "Miro"),
        ("Einard", "Einardzie"),
        ("Stein", "Steina"),
        ("Hania", "Hanna"),
        ("Dar Widzenia Pyłu", "Dar Widzenia Pyłem"),
    ]:
        assert is_form_of(canonical, variant), (canonical, variant)
    for canonical, variant in [
        ("Naelori", "Vynmor"),  # a different place named next to it
        ("Elantria", "adeptka"),  # a description, not her name
        ("Klejnot Myśli", "Krwawy Szeptacz"),  # a different artefact
        ("Alithor", "medalion Alithora"),  # a phrase containing the name
        ("Kerry", "Selen"),  # an alias: translated on its own
        ("Mira", "Mira"),  # the canonical form itself
    ]:
        assert not is_form_of(canonical, variant), (canonical, variant)


async def test_openai_models_are_prewarmed_not_given_gemini_caches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.services import translation_cache

    prewarmed: list[str] = []

    async def fake_prewarm(*, settings, model, prefix):  # type: ignore[no-untyped-def]
        prewarmed.append(model)

    async def fail_create(**kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("OpenAI models must not get a Gemini cache")

    monkeypatch.setattr(translation_cache, "prewarm_cache", fake_prewarm)
    monkeypatch.setattr(translation_cache, "create_cache", fail_create)
    caches = await translation_cache.RunCaches.open(
        settings=Settings(GEMINI_MODEL="m", OPENAI_API_KEY="k"),
        run_id=uuid4(),
        fixed_context="rules",
        models={"gpt-6-luna", "gpt-6.1-sol"},
    )
    assert sorted(prewarmed) == ["gpt-6-luna", "gpt-6.1-sol"]
    assert caches.name_for("gpt-6-luna") is None
    await caches.close()


def test_openai_input_marks_the_prefix_as_a_cache_breakpoint() -> None:
    from app.generation.providers.openai import _input

    content = _input("RULES", "rest")[0]["content"]
    assert content[0] == {
        "type": "input_text",
        "text": "RULES",
        "prompt_cache_breakpoint": {"mode": "explicit"},
    }
    assert content[1] == {"type": "input_text", "text": "rest"}


def test_two_step_mode() -> None:
    from app.generation.chains.translate_fragment_chain import calls_per_fragment
    from app.generation.prompt_manager.prompts.translate_fragment_prompt import (
        build_revision_prompt,
    )
    from app.services.translation_service import _run_models

    three = Settings(GEMINI_MODEL="m", TRANSLATION_MODEL="gpt-6.1-sol", TRANSLATION_STAGE_COUNT=3)
    two = Settings(
        GEMINI_MODEL="m",
        TRANSLATION_MODEL="gpt-6.1-sol",
        TRANSLATION_FAITHFUL_MODEL="gpt-6-luna",
        TRANSLATION_STAGE_COUNT=2,
    )
    assert calls_per_fragment(three) == ("faithful", "line_edit", "polish")
    assert calls_per_fragment(two) == ("faithful", "line_edit")
    assert _run_models(two) == {"faithful": "gpt-6-luna", "polish": "gpt-6.1-sol"}

    a = estimate_translation(
        word_count=10_000, fragment_count=None, glossary_terms=50, settings=three
    )
    b = estimate_translation(
        word_count=10_000, fragment_count=None, glossary_terms=50, settings=two
    )
    assert [s.stage for s in b.stages] == ["faithful", "line_edit"]
    assert b.cost_usd < a.cost_usd

    prompt = build_revision_prompt(
        context="ctx",
        target_language="English",
        source=[("p1", "Tak.")],
        faithful=[("p1", "Yes.")],
        checks=[],
        rhythm=[],
        metrics_block="She/He 30%",
    )
    assert "revision (stage 2 of 2)" in prompt
    assert "She/He 30%" in prompt  # the style targets are part of the revision
    assert "Return the text unchanged" not in prompt


def test_default_pipeline_is_one_sol_step_on_flex() -> None:
    from app.generation.chains.translate_fragment_chain import calls_per_fragment, stage_thinking

    s = Settings(GEMINI_MODEL="gemini-3.1-flash-lite-preview")
    assert calls_per_fragment(s) == ("line_edit",)
    assert stage_model(s, "line_edit") == "gpt-6.1-sol"
    assert stage_thinking(s, "line_edit") == "high"
    assert s.TRANSLATION_OPENAI_SERVICE_TIER == "flex"
    # Measured on chapters 3 and 5 (5,491 words): $0.70 on Flex.
    est = estimate_translation(word_count=5491, fragment_count=6, glossary_terms=178, settings=s)
    assert 0.5 < est.cost_usd < 0.95


def test_two_step_estimate_matches_measured_cost() -> None:
    s = Settings(GEMINI_MODEL="gemini-3.1-flash-lite-preview", TRANSLATION_STAGE_COUNT=2)
    # Measured on chapters 3 and 5 (5,491 words): $0.67 on Flex.
    est = estimate_translation(word_count=5491, fragment_count=6, glossary_terms=178, settings=s)
    assert 0.45 < est.cost_usd < 0.95


def test_current_renditions_use_one_run_per_fragment() -> None:
    from types import SimpleNamespace

    from app.services.translation_service import current_renditions

    frag, old_run, new_run, running = uuid4(), uuid4(), uuid4(), uuid4()

    def r(run, stage):  # type: ignore[no-untyped-def]
        return SimpleNamespace(fragment_id=frag, run_id=run, stage=stage)

    rows = [
        r(old_run, "faithful"),
        r(old_run, "line_edit"),
        r(old_run, "polish"),
        r(new_run, "faithful"),  # two-step run: no line edit
        r(new_run, "polish"),
        r(running, "faithful"),  # a re-run still in progress
    ]
    current = current_renditions(rows)  # type: ignore[arg-type]
    assert {k[1] for k in current} == {"faithful", "polish"}
    assert all(v.run_id == new_run for v in current.values())


def test_one_step_mode() -> None:
    from app.generation.chains.translate_fragment_chain import calls_per_fragment
    from app.generation.prompt_manager.prompts.translate_fragment_prompt import (
        build_one_step_prompt,
    )
    from app.services.translation_service import _run_models

    one = Settings(GEMINI_MODEL="m")  # one step is the default
    assert calls_per_fragment(one) == ("line_edit",)
    assert _run_models(one) == {"polish": "gpt-6.1-sol"}
    est = estimate_translation(word_count=5491, fragment_count=6, glossary_terms=178, settings=one)
    assert [s.stage for s in est.stages] == ["line_edit"]

    prompt = build_one_step_prompt(
        context="ctx", target_language="English", source=[("p1", "Tak.")]
    )
    assert "translation (one pass)" in prompt
    assert "Meaning wins over variety" in prompt
    assert "She/He openers" in prompt
    assert "{" not in prompt  # every placeholder filled


def test_find_terms_matches_case_forms_and_respects_capitals() -> None:
    from app.services.term_matching import TermIndex, find_terms

    index = TermIndex.build(
        [
            ("mira", "Mira", ["Miro"]),
            ("einard", "Einard", []),
            ("splot", "splot", []),
            ("rada", "Rada", []),
            ("dar", "Dar Widzenia", []),
            ("hania", "Hania", ["Hanna"]),
            ("naelori", "Naelori", ["Vynmor"]),  # a wrong variant is ignored
            ("zapasc", "Zapaść", []),
        ]
    )
    text = (
        "Miro, Einardzie! Splocie i splątany. Radość, a potem Rada. "
        "Dar Widzenia, Hanna, katedra Vynmor. Zapadła cisza."
    )
    hits = [(t, text[a:b]) for t, a, b in find_terms(text, index)]
    assert ("mira", "Miro") in hits
    assert ("einard", "Einardzie") in hits
    assert ("splot", "Splocie") in hits
    assert ("rada", "Rada") in hits
    assert ("dar", "Dar Widzenia") in hits
    assert ("hania", "Hanna") in hits
    assert all(word not in {w for _, w in hits} for word in ("splątany", "Radość", "Vynmor", "Zapadła"))


def test_translation_needs_glossary_and_voices() -> None:
    book = Book(
        title="Book",
        original_filename="book.docx",
        storage_path="book.docx",
        glossary_extraction_status="idle",
        voice_extraction_status="idle",
    )
    assert missing_prerequisites(book) == ["glossary", "voices"]
    book.glossary_extraction_status = "completed"
    assert missing_prerequisites(book) == ["voices"]
    book.voice_extraction_status = "running"
    assert missing_prerequisites(book) == ["voices"]
    book.voice_extraction_status = "completed"
    assert missing_prerequisites(book) == []
