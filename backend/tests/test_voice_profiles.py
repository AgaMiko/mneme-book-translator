# ruff: noqa: RUF001 - typographic dashes are the point of these tests
"""Unit tests for building voice profiles from lines: units, sampling, prompt text, validation."""

from uuid import UUID, uuid4

from app.generation.prompt_manager.models.build_voice_profile_model import (
    CharacterProfileDraft,
)
from app.services.voice_profiles import (
    CharacterLines,
    SpokenLine,
    cut_passage,
    plan_units,
    render_unit,
    sample_lines,
    validate_profiles,
)

_CH1, _CH2 = uuid4(), uuid4()


def _line(i: int, *, chapter: int = 1, kind: str = "speech", **kw: object) -> SpokenLine:
    base: dict[str, object] = {
        "paragraph_id": uuid4(),
        "line_index": i,
        "chapter_id": _CH1 if chapter == 1 else _CH2,
        "chapter_number": chapter,
        "kind": kind,
        "text": f"– Linia {i}.",
    }
    base.update(kw)
    return SpokenLine(**base)  # type: ignore[arg-type]


def _char(name: str, n: int, *, passages: int = 1, thoughts: int = 0) -> CharacterLines:
    return CharacterLines(
        glossary_entry_id=uuid4(),
        name=name,
        speech=[_line(i) for i in range(n)],
        thoughts=[_line(100 + i, kind="thought") for i in range(thoughts)],
        passage_count=passages,
    )


# ─── Units ──────────────────────────────────────────────


def test_big_characters_alone_small_ones_grouped() -> None:
    chars = [_char("Mira", 40), _char("Stein", 12), _char("A", 2), _char("B", 1), _char("C", 0)]
    units = plan_units(chars, min_lines=3, group_size=8)
    assert [[c.name for c in u] for u in units] == [["Mira"], ["Stein"], ["A", "B"]]


def test_small_groups_split_at_group_size() -> None:
    chars = [_char(f"P{i}", 1) for i in range(5)]
    assert [len(u) for u in plan_units(chars, group_size=2)] == [2, 2, 1]


# ─── Sampling ───────────────────────────────────────────


def test_no_sampling_within_budget() -> None:
    lines = [_line(i) for i in range(5)]
    kept, sampled = sample_lines(lines, budget_tokens=10_000)
    assert kept == lines
    assert not sampled


def test_sampling_keeps_every_chapter_and_addressee() -> None:
    lines = [_line(i, chapter=1, addressee="Stein") for i in range(40)]
    lines += [_line(40 + i, chapter=2, addressee="Aurel") for i in range(40)]
    lines.append(_line(80, chapter=2, addressee="Jenna"))
    kept, sampled = sample_lines(lines, budget_tokens=60)
    assert sampled
    assert len(kept) < len(lines)
    assert {ln.chapter_number for ln in kept} == {1, 2}
    assert {ln.addressee for ln in kept} == {"Stein", "Aurel", "Jenna"}
    assert [ln.line_index for ln in kept] == sorted(ln.line_index for ln in kept)


def test_sampling_prefers_named_speaker_lines() -> None:
    lines = [_line(i, inferred=i % 2 == 0) for i in range(40)]
    kept, _ = sample_lines(lines, budget_tokens=60)
    assert kept
    assert all(not ln.inferred for ln in kept)


# ─── Prompt text ────────────────────────────────────────


def test_render_numbers_lines_across_characters() -> None:
    a, b = _char("Mira", 2, passages=2, thoughts=1), _char("Stein", 1)
    r = render_unit([a, b])
    assert r.who == "these characters: Mira, Stein"
    assert r.has_thoughts
    assert "### C1 · Mira — 2 spoken lines; pick 2 passages" in r.text
    assert "### C2 · Stein — 1 spoken line; pick 1 passage" in r.text
    assert [r.numbers[n][0].name for n in sorted(r.numbers)] == ["Mira", "Mira", "Mira", "Stein"]
    assert r.numbers[3][1].kind == "thought"
    assert "L4 [ch. 1] – Linia 0." in r.text


# ─── Validation ─────────────────────────────────────────


def _draft(code: str, name: str, **kw: object) -> CharacterProfileDraft:
    base: dict[str, object] = {
        "character_code": code,
        "character_name": name,
        "source_voice_observation": "obs",
        "target_voice_strategy": "strat",
    }
    base.update(kw)
    return CharacterProfileDraft.model_validate(base)


def test_validate_keeps_only_own_speech_lines() -> None:
    mira = _char("Mira", 2, thoughts=1)
    stein = _char("Stein", 1)
    r = render_unit([mira, stein])  # L1 L2 Mira speech, L3 Mira thought, L4 Stein
    (p,) = validate_profiles(
        [
            _draft(
                "C1",
                "mira",
                features=[
                    {"feature": "tic", "lines": [1, 3, 4, 99]},
                    {"feature": "only foreign", "lines": [4]},
                ],
                register_shifts=[{"situation": "to Stein", "change": "softer", "lines": [2]}],
            )
        ],
        r,
    )
    assert p.character is mira
    assert p.features == [("tic", [mira.speech[0].paragraph_id])]
    assert p.shifts == [("to Stein", "softer", [mira.speech[1].paragraph_id])]


def test_validate_drops_mismatched_code_and_name() -> None:
    r = render_unit([_char("Mira", 1), _char("Stein", 1)])
    assert validate_profiles([_draft("C1", "Stein")], r) == []


def test_validate_passages_order_chapter_and_cap() -> None:
    mira = CharacterLines(
        glossary_entry_id=uuid4(),
        name="Mira",
        speech=[_line(0), _line(1), _line(2, chapter=2)],
        passage_count=2,
    )
    r = render_unit([mira])
    (p,) = validate_profiles(
        [
            _draft(
                "C1",
                "Mira",
                reference_passages=[
                    {"first_line": 2, "last_line": 1, "why": "reversed"},
                    {"first_line": 1, "last_line": 2, "why": "duplicate range"},
                    {"first_line": 2, "last_line": 3, "why": "crosses chapters"},
                    {"first_line": 3, "last_line": 3, "why": "over the cap"},
                ],
            )
        ],
        r,
    )
    assert [(a.line_index, b.line_index, why) for a, b, why in p.passages] == [
        (0, 1, "reversed"),
        (1, 1, "crosses chapters"),
    ]


# ─── Passages ───────────────────────────────────────────


def test_cut_passage_includes_paragraphs_between() -> None:
    first = _line(0)
    last = _line(1)
    other: UUID = uuid4()
    paras = [(first.paragraph_id, "– A?"), (other, "– B."), (last.paragraph_id, "– C!")]
    text, fp, lp = cut_passage(first, last, paras)
    assert text == "– A?\n\n– B.\n\n– C!"
    assert (fp, lp) == (first.paragraph_id, last.paragraph_id)


def test_cut_passage_too_long_falls_back_to_first_line() -> None:
    first, last = _line(0), _line(1)
    paras = [(first.paragraph_id, "x"), *[(uuid4(), "y") for _ in range(20)]]
    paras.append((last.paragraph_id, "z"))
    text, fp, lp = cut_passage(first, last, paras, max_paragraphs=5)
    assert text == first.text
    assert fp == lp == first.paragraph_id
