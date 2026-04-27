"""Unit tests for voice dialogue counting heuristics."""

from app.services.voice_service import (
    count_dialogue_turns,
    first_dialogue_snippet_near_character,
)


def test_count_dialogue_turns_finds_name_near_quote() -> None:
    text = 'Aurel said "I will not go" and left.'
    assert count_dialogue_turns(text, canonical_name="Aurel", variants=[]) >= 1


def test_count_dialogue_turns_polish_lower_quote() -> None:
    text = "Aurel rzekł: „Nie pojadę”."
    assert count_dialogue_turns(text, canonical_name="Aurel", variants=[]) >= 1


def test_count_dialogue_turns_no_false_positive_without_name() -> None:
    text = '"Hello," she said to no one in particular.'
    assert count_dialogue_turns(text, canonical_name="Aurel", variants=[]) == 0


def test_first_snippet_matches_quote_near_name() -> None:
    text = 'Aurel said "I will not go" and left.'
    s = first_dialogue_snippet_near_character(
        text, canonical_name="Aurel", variants=[], max_chars=500
    )
    assert s is not None
    assert "will not go" in s


def test_first_snippet_none_without_name() -> None:
    text = '"Hello," she said to no one in particular.'
    assert (
        first_dialogue_snippet_near_character(
            text, canonical_name="Aurel", variants=[]
        )
        is None
    )
