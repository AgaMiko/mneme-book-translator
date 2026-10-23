# ruff: noqa: RUF001 - typographic dashes and quotes are the point of these tests
"""Unit tests for the dialogue line finder (voice pipeline, step 1).

Polish examples are paragraphs from Zaplataczka.
"""

from uuid import uuid4

from app.services.dialogue_lines import (
    detect_convention,
    find_dialogue_lines,
    split_dash_paragraph,
)
from app.services.fragmenter import ChapterInput, ParagraphInput


def _chapter(*texts: str) -> ChapterInput:
    return ChapterInput(id=uuid4(), paragraphs=[ParagraphInput(id=uuid4(), text=t) for t in texts])


# ─── Splitting a dash paragraph ─────────────────────────


def test_split_speech_only() -> None:
    speech, narration = split_dash_paragraph("– Hania! Gdzie jest wilczyna?")
    assert speech == ["Hania! Gdzie jest wilczyna?"]
    assert narration == []


def test_split_speech_narration_speech() -> None:
    speech, narration = split_dash_paragraph(
        "– Rozeszły się jak świeże bułeczki. – Hania wzruszyła ramionami. "
        "– Po tym, jak Generał ogłosił te „nowe procedury”, mamy związane ręce."
    )
    assert speech == [
        "Rozeszły się jak świeże bułeczki.",
        "Po tym, jak Generał ogłosił te „nowe procedury”, mamy związane ręce.",
    ]
    assert narration == ["Hania wzruszyła ramionami."]


def test_split_speech_tag_mid_sentence() -> None:
    speech, narration = split_dash_paragraph("– To przestań – rzucił i skrzyżował ramiona.")
    assert speech == ["To przestań"]
    assert narration == ["rzucił i skrzyżował ramiona."]


def test_split_keeps_stutter_and_letter_dash() -> None:
    speech, narration = split_dash_paragraph("– T–tak… – odpowiedziała.")
    assert speech == ["T–tak…"]
    assert narration == ["odpowiedziała."]
    speech, _ = split_dash_paragraph("– Następny–a… Mira, Trzeci Krąg Korpusu.")
    assert speech == ["Następny–a… Mira, Trzeci Krąg Korpusu."]


def test_split_dash_without_space_after_start() -> None:
    speech, narration = split_dash_paragraph(
        "–Na oślep nie. – Mira nabiła gotowaną marchew na widelec."
    )
    assert speech == ["Na oślep nie."]
    assert narration == ["Mira nabiła gotowaną marchew na widelec."]


def test_split_ellipsis_after_dash() -> None:
    speech, narration = split_dash_paragraph(
        "–...prrr, Zefir, prrr... – wycharczał, ściągnął ręce do siebie."
    )
    assert speech == ["...prrr, Zefir, prrr..."]
    assert narration == ["wycharczał, ściągnął ręce do siebie."]


def test_split_dash_glued_to_previous_sentence() -> None:
    speech, narration = split_dash_paragraph(
        "– Patrz na to, co nad ziemią wyrasta.– mruknął. – I nie pytaj."
    )
    assert speech == ["Patrz na to, co nad ziemią wyrasta.", "I nie pytaj."]
    assert narration == ["mruknął."]


def test_split_non_breaking_space_after_dash() -> None:
    speech, narration = split_dash_paragraph("– To przestań – rzucił.")
    assert speech == ["To przestań"]
    assert narration == ["rzucił."]


def test_split_spaced_hyphen_as_dash() -> None:
    speech, narration = split_dash_paragraph(
        "– Dobra. Wierzę ci. - Spodziewała się drwin. Nie tego. – Mówiłaś o tym Agacie?"
    )
    assert speech == ["Dobra. Wierzę ci.", "Mówiłaś o tym Agacie?"]
    assert narration == ["Spodziewała się drwin. Nie tego."]


def test_split_keeps_hyphen_inside_word() -> None:
    speech, _ = split_dash_paragraph("– Biało-czerwona flaga.")
    assert speech == ["Biało-czerwona flaga."]


# ─── Convention ─────────────────────────────────────────


def test_detect_dash_convention() -> None:
    ch = _chapter(
        "– Hania! Gdzie jest wilczyna?",
        "– Znam miejsce niedaleko stąd.",
        "Nieoczekiwana szczerość w jego tonie. Może ten „duet” ze Steinem nie jest taki zły?",
    )
    assert detect_convention([ch]) == "dash"


def test_detect_quotes_convention() -> None:
    ch = _chapter(
        '"Where is the wolfsbane?" Hania asked.',
        '"Gone," said Mira.',
        "She shrugged.",
    )
    assert detect_convention([ch]) == "quotes"


def test_detect_no_dialogue_defaults_to_quotes() -> None:
    assert detect_convention([_chapter("Ziewnął przeciągle.")]) == "quotes"


# ─── Finding lines ──────────────────────────────────────


def test_dash_book_skips_narration_and_inline_quotes() -> None:
    ch = _chapter(
        "Ziewnął przeciągle. Spojrzał na księgę „Symetria w Naturze”.",
        "– Hania! Gdzie jest wilczyna?",
        'Mira zacisnęła na niej palce i wydusiła tylko „dziękuję".',
        "– Rozeszły się. – Hania wzruszyła ramionami.",
    )
    lines = find_dialogue_lines([ch])
    assert [ln.text for ln in lines] == [
        "– Hania! Gdzie jest wilczyna?",
        "– Rozeszły się. – Hania wzruszyła ramionami.",
    ]
    assert all(ln.marker == "dash" for ln in lines)
    assert lines[1].speech_text == "Rozeszły się."


def test_dash_book_keeps_paragraph_that_starts_with_quote() -> None:
    ch = _chapter(
        "– Hania! Gdzie jest wilczyna?",
        "– Znam miejsce niedaleko stąd.",
        "„Znowu porażka. Ryciny z tuneli okazały się kolejnym ślepym tropem.”",
    )
    lines = find_dialogue_lines([ch])
    assert lines[-1].marker == "quote"
    assert lines[-1].speech_text.startswith("Znowu porażka.")


def test_quotes_book_uses_quoted_spans() -> None:
    ch = _chapter(
        '"Where is the wolfsbane?" Hania asked. "We need it now."',
        "She shrugged.",
    )
    lines = find_dialogue_lines([ch], convention="quotes")
    assert len(lines) == 1
    assert lines[0].speech_text == "Where is the wolfsbane? We need it now."


def test_word_offsets_count_every_paragraph_across_chapters() -> None:
    ch1 = _chapter("Ziewnął przeciągle.", "– Hania! Gdzie jest wilczyna?")
    ch2 = _chapter("Jedno dwa trzy.", "– Znam miejsce.")
    lines = find_dialogue_lines([ch1, ch2], convention="dash")
    assert [ln.word_offset for ln in lines] == [2, 2 + 5 + 3]
    assert lines[0].chapter_id == ch1.id
    assert lines[1].chapter_id == ch2.id
    assert lines[1].paragraph_id == ch2.paragraphs[1].id
