# ruff: noqa: RUF001 - typographic dashes are the point of these tests
"""Unit tests for Pass 1 chunking, numbered text, window mapping and validation."""

from uuid import uuid4

from app.generation.prompt_manager.models.identify_speakers_model import LineAttribution
from app.services.dialogue_lines import find_dialogue_lines
from app.services.fragmenter import ChapterInput, ParagraphInput
from app.services.glossary_service import make_windows
from app.services.speaker_chunks import plan_chunks, render_chunk, windows_for_span
from app.services.speakers_validation import resolve_attributions
from app.services.translation_service import speakers_for_range


def _chapter(*texts: str) -> ChapterInput:
    return ChapterInput(id=uuid4(), paragraphs=[ParagraphInput(id=uuid4(), text=t) for t in texts])


def _words(n: int, word: str = "słowo") -> str:
    return " ".join([word] * n)


# ─── Chunks ─────────────────────────────────────────────


def test_chunks_cut_at_paragraphs_and_never_cross_chapters() -> None:
    ch1 = _chapter(_words(300), "– Hania!", _words(300), _words(300))
    ch2 = _chapter(_words(100), "– Znam miejsce.")
    lines = find_dialogue_lines([ch1, ch2], convention="dash")
    chunks = plan_chunks([ch1, ch2], lines, chunk_words=500, min_tail_words=0)
    assert [len(c.paragraphs) for c in chunks] == [3, 1, 2]
    assert [c.number for c in chunks] == [1, 2, 3]
    assert [c.chapter_index for c in chunks] == [0, 0, 1]
    assert [len(c.lines) for c in chunks] == [1, 0, 1]


def test_short_tail_joins_previous_chunk() -> None:
    ch = _chapter(_words(600), _words(50))
    chunks = plan_chunks([ch], [], chunk_words=500, min_tail_words=100)
    assert len(chunks) == 1
    assert len(chunks[0].paragraphs) == 2


def test_context_is_previous_paragraphs_of_same_chapter_only() -> None:
    ch1 = _chapter("a", "b", "c", "d", _words(10))
    ch2 = _chapter("e")
    chunks = plan_chunks([ch1, ch2], [], chunk_words=3, min_tail_words=0, context_paragraphs=2)
    assert [p.text for p in chunks[0].context] == []
    assert [p.text for p in chunks[1].context] == ["b", "c"]
    assert chunks[-1].context == []


# ─── Numbered text ──────────────────────────────────────


def test_render_numbers_only_dialogue_lines() -> None:
    ch = _chapter("Ziewnął.", "– Hania! Gdzie jest wilczyna?", "Cisza.", "– Rozeszły się.")
    lines = find_dialogue_lines([ch], convention="dash")
    (chunk,) = plan_chunks([ch], lines)
    text, context, numbers = render_chunk(chunk)
    assert text.split("\n\n") == [
        "Ziewnął.",
        "L1: – Hania! Gdzie jest wilczyna?",
        "Cisza.",
        "L2: – Rozeszły się.",
    ]
    assert context == ""
    assert numbers[1].paragraph_id == ch.paragraphs[1].id
    assert numbers[2].paragraph_id == ch.paragraphs[3].id


def test_render_labels_context_paragraphs() -> None:
    ch = _chapter("– Idziemy?", _words(10), "– Tak.")
    lines = find_dialogue_lines([ch], convention="dash")
    chunks = plan_chunks([ch], lines, chunk_words=2, min_tail_words=0)
    _, context, _ = render_chunk(chunks[1], context_labels={ch.paragraphs[0].id: "Mira → Stein"})
    assert context == "[Mira → Stein] – Idziemy?"


# ─── Window mapping ─────────────────────────────────────


def test_windows_for_span_matches_window_geometry() -> None:
    total_words = 2000
    text = " ".join(f"w{i}" for i in range(total_words))
    windows = make_windows(text, window_words=500, overlap_words=100)
    total = len(windows)
    for start, length in [(0, 5), (398, 5), (450, 30), (500, 10), (1999, 1)]:
        expected = {
            n
            for n, w in enumerate(windows, start=1)
            if any(f"w{i}" in w.split() for i in range(start, start + length))
        }
        assert set(windows_for_span(start, length, total_windows=total)) == expected


def test_windows_for_span_agrees_with_translation_lookup() -> None:
    gid = uuid4()
    for start, length in [(0, 5), (420, 40), (1210, 3)]:
        windows = {n: {gid} for n in windows_for_span(start, length, total_windows=10)}
        assert speakers_for_range(windows, start=start, word_count=length) == {gid}


# ─── Validation ─────────────────────────────────────────


def _a(line: int, **kw: object) -> LineAttribution:
    base: dict[str, object] = {"line": line, "kind": "speech", "confidence": "clear"}
    base.update(kw)
    return LineAttribution.model_validate(base)


def test_resolve_keeps_matching_code_and_name() -> None:
    mira, stein = uuid4(), uuid4()
    chars = {"C1": (mira, "Mira"), "C2": (stein, "Stein")}
    out = resolve_attributions(
        [
            _a(
                1,
                speaker_code="C1",
                speaker_name="mira",
                addressee_code="C2",
                addressee_name="Stein",
            )
        ],
        line_count=1,
        characters=chars,
    )
    assert out[1].speaker_id == mira
    assert out[1].addressee_id == stein


def test_resolve_drops_mismatched_speaker_but_keeps_line() -> None:
    mira, stein = uuid4(), uuid4()
    chars = {"C1": (mira, "Mira"), "C2": (stein, "Stein")}
    out = resolve_attributions(
        [_a(1, speaker_code="C1", speaker_name="Stein", kind="thought")],
        line_count=1,
        characters=chars,
    )
    assert out[1].speaker_id is None
    assert out[1].kind == "thought"


def test_resolve_drops_out_of_range_and_repeated_lines() -> None:
    mira = uuid4()
    chars = {"C1": (mira, "Mira")}
    out = resolve_attributions(
        [
            _a(0, speaker_code="C1", speaker_name="Mira"),
            _a(3, speaker_code="C1", speaker_name="Mira"),
            _a(2, speaker_code="C1", speaker_name="Mira"),
            _a(2, kind="not_dialogue"),
        ],
        line_count=2,
        characters=chars,
    )
    assert set(out) == {2}
    assert out[2].kind == "speech"


def test_resolve_not_dialogue_has_no_speaker_and_self_address_is_dropped() -> None:
    mira = uuid4()
    chars = {"C1": (mira, "Mira")}
    out = resolve_attributions(
        [
            _a(1, kind="not_dialogue", speaker_code="C1", speaker_name="Mira"),
            _a(
                2,
                speaker_code="C1",
                speaker_name="Mira",
                addressee_code="C1",
                addressee_name="Mira",
            ),
        ],
        line_count=2,
        characters=chars,
    )
    assert out[1].speaker_id is None
    assert out[2].speaker_id == mira
    assert out[2].addressee_id is None
