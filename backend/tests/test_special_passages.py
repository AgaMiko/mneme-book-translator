"""Unit tests for special passages: letter checks, scan results, rewrites, text patches."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.generation.prompt_manager.models.special_passages_model import (
    ParagraphText,
    PassageCandidate,
    PassageRewrite,
    PassageRule,
)
from app.models.passages import SpecialPassage
from app.services import special_passages_service as service
from app.services.passage_rules import (
    extract_message,
    hidden_message_problems,
    letter_strings,
    line_count_problems,
    message_slack,
    normalise_message,
    spelled_message,
    split_sentences,
    stated_messages,
)
from app.services.special_passages_service import (
    ChapterText,
    apply_texts,
    candidate_range,
    code_decides,
    code_problems,
    english_of,
    found_from_rule,
    needs_check,
    rewrite_texts,
)

LETTER = [
    "Ice came early this year. All the roads are closed.",
    "My brother sends his love! “Why do you not write?” he asks. Answer soon…",
    "Tell nobody. Come home. Honour your word. Ever yours. Daniel",
]


def test_sentence_initials_spell_the_message() -> None:
    assert extract_message(LETTER, "sentence") == "IAMWATCHED"
    assert hidden_message_problems(LETTER, "sentence", "I am watched") == []


def test_sentences_split_after_closing_quotes_and_ellipsis() -> None:
    assert split_sentences(LETTER[1]) == [
        "My brother sends his love!",
        "“Why do you not write?” he asks.",
        "Answer soon…",
    ]


def test_wrong_letters_are_reported_with_both_strings() -> None:
    problems = hidden_message_problems(LETTER[:2], "sentence", "I AM WATCHED")
    assert len(problems) == 1
    assert "IAMWA" in problems[0] and "IAMWATCHED" in problems[0]


def test_rules_code_cannot_read_give_no_problems() -> None:
    assert hidden_message_problems(LETTER, "other", "I AM WATCHED") == []
    assert hidden_message_problems(LETTER, "sentence", "") == []


def test_lines_words_and_marked_words() -> None:
    verse = ["Roses fade\nUnder snow", "Night is long"]
    assert extract_message(verse, "line") == "RUN"
    assert extract_message(verse, "paragraph") == "RN"
    assert (
        extract_message(["Take *heed*, read **every** line _everywhere_."], "marked_word") == "HEE"
    )
    assert extract_message(["źle Żyć, łatwo"], "word") == "ŹŻŁ"
    assert normalise_message("I am - watched!") == "IAMWATCHED"


def test_letter_strings_leave_out_duplicates_and_long_word_strings() -> None:
    strings = letter_strings(["One two\nThree four", "Five six\nSeven eight"])
    assert strings["line"] == "OTFS"
    assert "paragraph" not in strings  # two letters only
    assert "word" in strings
    assert "word" not in letter_strings(["word " * 200])


def test_line_count() -> None:
    assert line_count_problems(["a\nb", "c"], ["x", "y", "z"]) == []
    assert line_count_problems(["a\nb", "c"], ["x y", "z"]) == [
        "The source has 3 lines and the translation has 2."
    ]


def test_code_decides_only_first_letter_messages() -> None:
    assert code_decides(kind="hidden_message", unit="sentence", target_message="RUN")
    assert not code_decides(kind="hidden_message", unit=None, target_message="RUN")
    assert not code_decides(kind="hidden_message", unit="sentence", target_message=None)
    assert not code_decides(kind="verse", unit=None, target_message=None)
    assert code_problems(
        kind="verse", unit=None, target_message=None, source_texts=["a\nb"], target_texts=["a b"]
    )
    assert not code_problems(
        kind="wordplay", unit=None, target_message=None, source_texts=["a"], target_texts=["b"]
    )


def _chapter() -> ChapterText:
    ch = ChapterText(chapter_id=uuid4(), position=2)
    ch.rows = [("title:x", "t", "Chapter 3\nA rhyme")] + [
        (f"id{i}", f"p{i}", f"text {i}") for i in range(1, 6)
    ]
    return ch


def _rule(**kw: object) -> PassageRule:
    base = {
        "kind": "hidden_message",
        "rule": "Sentence initials spell a message.",
        "unit": "sentence",
        "source_message": "JESTEM",
        "target_message": "I AM",
        "dependent_paragraphs": ["p5", "[P2]", "p9"],
    }
    return PassageRule(**{**base, **kw})  # type: ignore[arg-type]


def test_candidate_range_accepts_loose_ids_and_rejects_bad_ones() -> None:
    ch = _chapter()
    cand = PassageCandidate(
        first_paragraph="[P2]", last_paragraph="p 3", kind="document", evidence="a letter"
    )
    assert candidate_range(cand, ch) == (2, 3)
    cand.last_paragraph = "p1"
    assert candidate_range(cand, ch) is None
    cand.last_paragraph = "p99"
    assert candidate_range(cand, ch) is None


def test_found_passage_keeps_real_ids_and_outside_dependents() -> None:
    ch = _chapter()
    found = found_from_rule(_rule(), ch, 2, 3, "a letter")
    assert found is not None
    assert found.paragraph_ids == ["id2", "id3"]
    # p2 is inside the passage and p9 does not exist.
    assert found.dependent_paragraph_ids == ["id5"]
    assert (found.unit, found.source_message, found.target_message) == (
        "sentence",
        "JESTEM",
        "I AM",
    )
    assert found.position == 200_002


def test_no_rule_means_no_passage_and_verse_has_no_message() -> None:
    ch = _chapter()
    assert found_from_rule(_rule(kind="none"), ch, 2, 3, "") is None
    verse = found_from_rule(_rule(kind="verse", unit="other"), ch, 0, 0, "")
    assert verse is not None
    assert verse.paragraph_ids == ["title:x"]
    assert (verse.unit, verse.source_message, verse.target_message) == (None, None, None)


def _rewrite(
    paragraphs: list[tuple[str, str]], dependents: list[tuple[str, str]]
) -> PassageRewrite:
    return PassageRewrite(
        plan="",
        paragraphs=[ParagraphText(paragraph_id=i, text=t) for i, t in paragraphs],
        dependent_paragraphs=[ParagraphText(paragraph_id=i, text=t) for i, t in dependents],
        target_message="",
        notes="",
    )


def test_rewrite_must_return_the_passage_paragraphs_in_order() -> None:
    short = {"id2": "p2", "id3": "p3", "id5": "p5", "id4": "p4"}
    ok = _rewrite([("p2", "A"), ("[p3]", "B")], [("p5", "C"), ("p4", "not a dependent")])
    assert rewrite_texts(ok, ids=["id2", "id3"], dependent_ids=["id5"], short=short) == {
        "id2": "A",
        "id3": "B",
        "id5": "C",
    }
    swapped = _rewrite([("p3", "B"), ("p2", "A")], [])
    assert rewrite_texts(swapped, ids=["id2", "id3"], dependent_ids=[], short=short) is None
    empty = _rewrite([("p2", "A"), ("p3", " ")], [])
    assert rewrite_texts(empty, ids=["id2", "id3"], dependent_ids=[], short=short) is None


def test_apply_texts_patches_only_the_renditions_that_hold_the_paragraphs() -> None:
    r1 = SimpleNamespace(
        paragraphs=[{"paragraph_id": "a", "text": "A"}, {"paragraph_id": "b", "text": "B"}]
    )
    r2 = SimpleNamespace(paragraphs=[{"paragraph_id": "c", "text": "C"}])
    before = r2.paragraphs
    apply_texts([r1, r2], {"b": "B2"})  # type: ignore[list-item]
    assert english_of([r1, r2]) == {"a": "A", "b": "B2", "c": "C"}  # type: ignore[list-item]
    assert r2.paragraphs is before


def _passage(**kw: object) -> SpecialPassage:
    base: dict[str, object] = {
        "book_id": uuid4(),
        "chapter_id": uuid4(),
        "position": 1,
        "kind": "verse",
        "paragraph_ids": ["a", "b"],
        "dependent_paragraph_ids": ["c"],
    }
    return SpecialPassage(**{**base, **kw})  # type: ignore[arg-type]


def test_needs_check() -> None:
    english = {"a": "A", "b": "B", "c": "C"}
    snapshot = [{"paragraph_id": i, "text": t} for i, t in english.items()]
    assert needs_check(_passage(status="unchecked"), english)
    # Not translated yet.
    assert not needs_check(_passage(status="unchecked"), {"a": "A"})
    assert not needs_check(_passage(status="dismissed"), english)
    assert not needs_check(_passage(status="corrected", checked_translation=snapshot), english)
    # Re-translated since the check.
    assert needs_check(
        _passage(status="corrected", checked_translation=snapshot), {**english, "b": "B again"}
    )


# ─── The check and correction loop, with the model calls faked ───────────


def _job(english: dict[str, str]) -> service._Job:
    ch = ChapterText(chapter_id=uuid4(), position=0)
    ch.rows = [("a", "p1", "Idę. Jestem. Mam."), ("b", "p2", "Odczytał wiadomość.")]
    return service._Job(
        passage_id=uuid4(),
        kind="hidden_message",
        rule="Sentence initials spell a message.",
        unit="sentence",
        source_message="IJM",
        target_message="RUN",
        ids=["a"],
        dependent_ids=["b"],
        source={"a": "Idę. Jestem. Mam.", "b": "Odczytał wiadomość."},
        english=english,
        chapter=ch,
        source_language="pl",
        target_language="en",
    )


def _fake_rewrites(monkeypatch: pytest.MonkeyPatch, answers: list[PassageRewrite]) -> list[dict]:
    calls: list[dict] = []

    async def fake(**kwargs: object) -> PassageRewrite:
        calls.append(kwargs)
        return answers[len(calls) - 1]

    async def no_model_check(**kwargs: object) -> None:
        raise AssertionError("a first-letter message is checked by code only")

    monkeypatch.setattr(service, "rewrite_passage", fake)
    monkeypatch.setattr(service, "check_passage", no_model_check)
    return calls


SETTINGS = SimpleNamespace(PASSAGES_REWRITE_ATTEMPTS=3)


async def test_translation_that_keeps_the_rule_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_rewrites(monkeypatch, [])
    job = _job({"a": "Run. Under. Now.", "b": "He read the message."})
    outcome = await service._check_one(job, SETTINGS)  # type: ignore[arg-type]
    assert (outcome.status, outcome.texts, calls) == ("passed", {}, [])


async def test_broken_rule_is_rewritten_until_the_letters_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_rewrites(
        monkeypatch,
        [
            _rewrite([("p1", "Rest. Up. Go.")], []),
            _rewrite([("p1", "Rest. Up. Now.")], [("p2", "He read it: run.")]),
        ],
    )
    job = _job({"a": "I go. I am. I have.", "b": "He read the message."})
    outcome = await service._check_one(job, SETTINGS)  # type: ignore[arg-type]
    assert outcome.status == "corrected"
    assert outcome.texts == {"a": "Rest. Up. Now.", "b": "He read it: run."}
    assert "III" in outcome.problems[0]
    assert [bool(c["problems"]) for c in outcome.candidates] == [True, False]
    # The second attempt starts from the first one and is told what was wrong with it.
    assert "Rest. Up. Go." in calls[1]["target_text"]
    assert "RUG" in calls[1]["problems"][0]


async def test_no_passing_attempt_leaves_the_text_and_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = _rewrite([("p1", "Still. Not. It.")], [])
    calls = _fake_rewrites(monkeypatch, [bad, bad, bad])
    job = _job({"a": "I go. I am. I have.", "b": "He read the message."})
    outcome = await service._check_one(job, SETTINGS)  # type: ignore[arg-type]
    assert (outcome.status, outcome.texts, len(calls)) == ("failed", {}, 3)
    assert len(outcome.candidates) == 3


def test_salutation_and_sign_off_do_not_break_the_message() -> None:
    letter = ["Dear Tom,", "Run now. Under cover. Now.", "Yours,\nEin"]
    assert extract_message(letter, "sentence") == "DRUNYE"
    assert hidden_message_problems(letter, "sentence", "RUN") == []
    # Letters in between still break it.
    assert hidden_message_problems(["Run. Away. Under. Now."], "sentence", "RUN")


def test_the_message_the_decoding_scene_states_is_accepted() -> None:
    scene = ["Read in order, the letters spelt out: “THEY'RE WATCHING”. He said “Run”."]
    assert stated_messages(scene) == ["THEY'RE WATCHING"]
    letter = [
        "Dear Tom,",
        "Today. Here. Every. Year. Rain. Ends. Wind. Ash. Time. Cold. Hail. In. Night. Gone.",
        "Yours, Ein",
    ]
    assert spelled_message(letter, "sentence", ["I AM WATCHED", *stated_messages(scene)]) == (
        "THEY'RE WATCHING"
    )


async def test_check_keeps_a_translation_that_spells_the_stated_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_rewrites(monkeypatch, [])
    job = _job(
        {"a": "Dear Tom. Gone. Over. On. Far. Fast. Yours.", "b": "It spelt “GO OFF” in the end."}
    )
    outcome = await service._check_one(job, SETTINGS)  # type: ignore[arg-type]
    assert (outcome.status, calls) == ("passed", [])
    assert job.target_message == "GO OFF"


def test_short_message_in_the_middle_of_a_long_letter_does_not_pass() -> None:
    body = ["Alas. Bread. Cold. Rain. Under. Now. Damp. Eggs. Fog. Grey."]
    assert spelled_message(body, "sentence", ["RUN"]) is None
    assert hidden_message_problems(body, "sentence", "RUN")
    # The source decides how much may surround the message.
    source = ["Drogi Tomie,", "Rób. Uciekaj. Natychmiast.", "Twój,\nEin"]
    assert message_slack(source, "sentence", "RUN") == (2, 3)
    assert message_slack(source, "sentence", None) == (2, 2)


def test_a_change_to_a_shared_dependent_does_not_make_the_passage_stale() -> None:
    checked = [{"paragraph_id": "a", "text": "A"}, {"paragraph_id": "c", "text": "C"}]
    passage = _passage(status="corrected", checked_translation=checked, paragraph_ids=["a"])
    assert not needs_check(passage, {"a": "A", "c": "C patched by another passage"})
    assert needs_check(passage, {"a": "A re-translated", "c": "C"})
