"""Units, sampling, prompt text and validation for building voice profiles.

Pure functions; ``voice_build_service`` loads the lines and stores the
profiles. See ``docs/voice-pipeline-redesign.md`` (step 3).

- ``plan_units`` — one call per character with ``MIN_LINES`` or more
  speech lines; characters with fewer share a call, up to ``GROUP_SIZE``.
- ``sample_lines`` — when a character's lines exceed the token budget,
  keep a sample spread over chapters that still covers every addressee
  and prefers lines whose speaker the text names.
- ``render_unit`` — the characters section of the prompt, lines numbered
  ``L1…Ln`` across the call.
- ``validate_profiles`` — keep only line numbers that are the
  character's own speech lines; drop features left without any.
- ``cut_passage`` — the passage text for a line range, from the
  paragraphs of the chapter.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from app.generation.prompt_manager.models.build_voice_profile_model import (
        CharacterProfileDraft,
    )

MIN_LINES = 3
GROUP_SIZE = 8
# Lines sent for one character; above this they are sampled.
LINE_TOKEN_BUDGET = 60_000
# Polish prose measured on Zaplataczka (see voice_extraction_estimate).
TOKENS_PER_WORD = 2.55
# A passage longer than this many paragraphs is cut to its first line.
MAX_PASSAGE_PARAGRAPHS = 10


@dataclass(frozen=True, slots=True)
class SpokenLine:
    paragraph_id: UUID
    line_index: int
    chapter_id: UUID
    chapter_number: int
    kind: str
    text: str
    addressee: str | None = None
    inferred: bool = False
    word_offset: int = 0

    @property
    def tokens(self) -> int:
        return math.ceil(len(self.text.split()) * TOKENS_PER_WORD)


@dataclass(slots=True)
class CharacterLines:
    glossary_entry_id: UUID
    name: str
    speech: list[SpokenLine] = field(default_factory=list)
    thoughts: list[SpokenLine] = field(default_factory=list)
    passage_count: int = 1


def plan_units(
    characters: list[CharacterLines],
    *,
    min_lines: int = MIN_LINES,
    group_size: int = GROUP_SIZE,
) -> list[list[CharacterLines]]:
    """Calls to make, largest characters first. Characters without speech are left out."""
    speaking = [c for c in characters if c.speech]
    big = sorted(
        (c for c in speaking if len(c.speech) >= min_lines),
        key=lambda c: (-len(c.speech), c.name.casefold()),
    )
    small = sorted(
        (c for c in speaking if len(c.speech) < min_lines),
        key=lambda c: (-len(c.speech), c.name.casefold()),
    )
    units = [[c] for c in big]
    units += [small[i : i + group_size] for i in range(0, len(small), group_size)]
    return units


def _evenly(items: list[SpokenLine], k: int) -> list[SpokenLine]:
    if k >= len(items):
        return list(items)
    if k <= 0:
        return []
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def sample_lines(
    lines: list[SpokenLine],
    *,
    budget_tokens: int = LINE_TOKEN_BUDGET,
) -> tuple[list[SpokenLine], bool]:
    """``(lines to send, sampled?)`` within ``budget_tokens``.

    Every chapter keeps at least one line, every addressee at least one,
    and lines with a named speaker go first within a chapter.
    """
    total = sum(ln.tokens for ln in lines)
    if total <= budget_tokens or not lines:
        return list(lines), False
    keep = max(1, math.floor(len(lines) * budget_tokens / total))
    by_chapter: dict[int, list[SpokenLine]] = defaultdict(list)
    for ln in lines:
        by_chapter[ln.chapter_number].append(ln)
    picked: dict[UUID, SpokenLine] = {}
    for chapter_lines in by_chapter.values():
        share = max(1, round(keep * len(chapter_lines) / len(lines)))
        clear = [ln for ln in chapter_lines if not ln.inferred]
        inferred = [ln for ln in chapter_lines if ln.inferred]
        chosen = _evenly(clear, share)
        chosen += _evenly(inferred, share - len(chosen))
        for ln in chosen:
            picked[ln.paragraph_id] = ln
    covered = {ln.addressee for ln in picked.values()}
    for ln in lines:
        if ln.addressee not in covered:
            picked[ln.paragraph_id] = ln
            covered.add(ln.addressee)
    return sorted(picked.values(), key=lambda ln: ln.line_index), True


@dataclass(slots=True)
class RenderedUnit:
    text: str
    who: str
    has_thoughts: bool
    codes: dict[str, CharacterLines]
    # Line number → (character, line)
    numbers: dict[int, tuple[CharacterLines, SpokenLine]]
    sampled: dict[UUID, int]


def _line_label(ln: SpokenLine) -> str:
    parts = [f"ch. {ln.chapter_number}"]
    if ln.addressee:
        parts.append(f"→ {ln.addressee}")
    if ln.inferred:
        parts.append("inferred")
    return " · ".join(parts)


def render_unit(
    unit: list[CharacterLines],
    *,
    budget_tokens: int = LINE_TOKEN_BUDGET,
) -> RenderedUnit:
    """The characters section of the prompt, with lines numbered across the call.

    ``sampled`` maps a character to the number of spoken lines sent, when
    their lines had to be sampled.
    """
    out: list[str] = []
    codes: dict[str, CharacterLines] = {}
    numbers: dict[int, tuple[CharacterLines, SpokenLine]] = {}
    sampled: dict[UUID, int] = {}
    has_thoughts = False
    for i, ch in enumerate(unit, start=1):
        code = f"C{i}"
        codes[code] = ch
        speech, was_sampled = sample_lines(ch.speech, budget_tokens=budget_tokens)
        if was_sampled:
            sampled[ch.glossary_entry_id] = len(speech)
        count = (
            f"a sample of {len(speech)} of {len(ch.speech)} spoken lines, spread over the book"
            if was_sampled
            else f"{len(ch.speech)} spoken line{'s' if len(ch.speech) != 1 else ''}"
        )
        passages = f"{ch.passage_count} passage{'s' if ch.passage_count != 1 else ''}"
        out.append(f"### {code} · {ch.name} — {count}; pick {passages}")
        out.append("")
        out.append("Spoken lines:")
        for ln in speech:
            n = len(numbers) + 1
            numbers[n] = (ch, ln)
            out.append(f"L{n} [{_line_label(ln)}] {ln.text}")
        if ch.thoughts:
            has_thoughts = True
            out.append("")
            out.append("Thoughts (not evidence for the spoken voice):")
            for ln in ch.thoughts:
                n = len(numbers) + 1
                numbers[n] = (ch, ln)
                out.append(f"L{n} [{_line_label(ln)}] {ln.text}")
        out.append("")
    names = [c.name for c in unit]
    who = names[0] if len(names) == 1 else "these characters: " + ", ".join(names)
    return RenderedUnit("\n".join(out).rstrip(), who, has_thoughts, codes, numbers, sampled)


@dataclass(slots=True)
class ValidatedProfile:
    character: CharacterLines
    observation: str
    strategy: str
    features: list[tuple[str, list[UUID]]]
    shifts: list[tuple[str, str, list[UUID]]]
    passages: list[tuple[SpokenLine, SpokenLine, str]]


def _own_speech(
    numbers: list[int],
    *,
    character: CharacterLines,
    rendered: RenderedUnit,
) -> list[SpokenLine]:
    out: list[SpokenLine] = []
    for n in numbers:
        found = rendered.numbers.get(n)
        if found is None:
            continue
        ch, ln = found
        if ch is character and ln.kind == "speech" and ln not in out:
            out.append(ln)
    return out


def validate_profiles(
    drafts: list[CharacterProfileDraft],
    rendered: RenderedUnit,
) -> list[ValidatedProfile]:
    """Profiles whose code and name match a character in the unit.

    Line numbers that are not the character's own speech lines are
    dropped; a feature or shift with none left is dropped. Passages must
    start and end on the character's speech lines in one chapter.
    """
    out: list[ValidatedProfile] = []
    seen: set[UUID] = set()
    for d in drafts:
        ch = rendered.codes.get(d.character_code.strip())
        if ch is None or ch.name.strip().casefold() != d.character_name.strip().casefold():
            continue
        if ch.glossary_entry_id in seen:
            continue
        seen.add(ch.glossary_entry_id)
        features = []
        for f in d.features:
            lines = _own_speech(f.lines, character=ch, rendered=rendered)
            if lines and f.feature.strip():
                features.append((f.feature.strip(), [ln.paragraph_id for ln in lines]))
        shifts = []
        for s in d.register_shifts:
            lines = _own_speech(s.lines, character=ch, rendered=rendered)
            if lines:
                shifts.append(
                    (s.situation.strip(), s.change.strip(), [ln.paragraph_id for ln in lines])
                )
        passages: list[tuple[SpokenLine, SpokenLine, str]] = []
        for p in d.reference_passages:
            ends = _own_speech([p.first_line, p.last_line], character=ch, rendered=rendered)
            if not ends:
                continue
            first, last = (
                min(ends, key=lambda ln: ln.line_index),
                max(ends, key=lambda ln: ln.line_index),
            )
            if first.chapter_id != last.chapter_id:
                last = first
            if any(q[0] == first and q[1] == last for q in passages):
                continue
            passages.append((first, last, p.why.strip()))
            if len(passages) >= ch.passage_count:
                break
        out.append(
            ValidatedProfile(
                character=ch,
                observation=d.source_voice_observation.strip(),
                strategy=d.target_voice_strategy.strip(),
                features=features,
                shifts=shifts,
                passages=passages,
            )
        )
    return out


def cut_passage(
    first: SpokenLine,
    last: SpokenLine,
    chapter_paragraphs: list[tuple[UUID, str]],
    *,
    max_paragraphs: int = MAX_PASSAGE_PARAGRAPHS,
) -> tuple[str, UUID, UUID]:
    """``(text, first_paragraph_id, last_paragraph_id)`` for a line range.

    ``chapter_paragraphs`` are the chapter's non-empty paragraphs in order.
    A range longer than ``max_paragraphs``, or one not found in the
    chapter, falls back to the first line alone.
    """
    ids = [pid for pid, _ in chapter_paragraphs]
    try:
        i = ids.index(first.paragraph_id)
        j = ids.index(last.paragraph_id)
    except ValueError:
        return first.text, first.paragraph_id, first.paragraph_id
    if j < i or j - i + 1 > max_paragraphs:
        return first.text, first.paragraph_id, first.paragraph_id
    text = "\n\n".join(t.strip() for _, t in chapter_paragraphs[i : j + 1])
    return text, ids[i], ids[j]
