"""Prompt text and validation for the cast pass (pure functions).

``voice_build_service.run_cast_pass`` loads the profiles and stores the
result. Characters are coded ``C1…Cn`` and passages ``P1…Pn`` across the
call; the code and name of a brief are cross-checked, and a flag must
name a passage that is not accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from app.generation.prompt_manager.models.cast_voices_model import (
        CastBriefs,
        PassageCheck,
    )
    from app.services.voice_profiles import SpokenLine


@dataclass(frozen=True, slots=True)
class CastPassage:
    id: UUID
    source: str
    english: str
    accepted: bool


@dataclass(slots=True)
class CastProfile:
    voice_id: UUID
    name: str
    accepted: bool
    line_count: int
    features: list[str]
    shifts: list[str]
    strategy: str
    passages: list[CastPassage] = field(default_factory=list)
    # Their own lines and lines said to them, as "[ch. 4] text", so register
    # can be judged from the text and not only from the profile.
    sample_lines: list[str] = field(default_factory=list)
    lines_to_them: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RenderedCast:
    text: str
    codes: dict[str, CastProfile]
    passages: dict[str, CastPassage]


def render_cast(
    profiles: list[CastProfile], *, briefs: dict[UUID, str] | None = None
) -> RenderedCast:
    """The cast section of a prompt, most lines first.

    Without ``briefs`` it is the input for writing briefs: profile, sample
    lines and passage sources. With ``briefs`` it is the input for the
    passage check: each brief and the passages with their translations.
    """
    if briefs is not None:
        return _render_for_check(profiles, briefs)
    out: list[str] = []
    codes: dict[str, CastProfile] = {}
    passages: dict[str, CastPassage] = {}
    for i, p in enumerate(profiles, start=1):
        code = f"C{i}"
        codes[code] = p
        status = " · accepted by the author" if p.accepted else ""
        out.append(f"### {code} · {p.name} — {p.line_count} spoken lines{status}")
        out.append("")
        if p.features:
            out.append("Features:")
            out += [f"- {f}" for f in p.features]
        if p.shifts:
            out.append("Register shifts:")
            out += [f"- {s}" for s in p.shifts]
        out.append("Current strategy:")
        out.append(p.strategy.strip() or "(none)")
        if p.sample_lines:
            out.append("Sample lines (theirs, across the book):")
            out += [f"- {ln}" for ln in p.sample_lines]
        if p.lines_to_them:
            out.append("Said to them by others:")
            out += [f"- {ln}" for ln in p.lines_to_them]
        for ps in p.passages:
            pid = f"P{len(passages) + 1}"
            passages[pid] = ps
            out.append("")
            out.append(f"#### {pid} (reference passage)")
            out.append(ps.source.strip())
        out.append("")
    return RenderedCast("\n".join(out).rstrip(), codes, passages)


def _render_for_check(profiles: list[CastProfile], briefs: dict[UUID, str]) -> RenderedCast:
    out: list[str] = []
    codes: dict[str, CastProfile] = {}
    passages: dict[str, CastPassage] = {}
    for i, p in enumerate(profiles, start=1):
        code = f"C{i}"
        codes[code] = p
        out.append(f"### {code} · {p.name}")
        out.append("")
        out.append("Brief:")
        out.append(briefs.get(p.voice_id, "").strip() or "(no brief)")
        for ps in p.passages:
            pid = f"P{len(passages) + 1}"
            passages[pid] = ps
            mark = " · accepted by the author" if ps.accepted else ""
            out.append("")
            out.append(f"#### {pid}{mark}")
            out.append("Source:")
            out.append(ps.source.strip())
            out.append("Proposed translation:")
            out.append(ps.english.strip() or "(none)")
        out.append("")
    return RenderedCast("\n".join(out).rstrip(), codes, passages)


def _passage_key(raw: str) -> str:
    """``P7`` from ``P7``, ``p7``, ``P 7`` or ``7``."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"P{digits}" if digits else raw.strip()


def validate_briefs(result: CastBriefs, rendered: RenderedCast) -> dict[UUID, str]:
    """Briefs whose code and name match a character in the call."""
    briefs: dict[UUID, str] = {}
    for b in result.briefs:
        p = rendered.codes.get(b.character_code.strip())
        if p is None or p.name.strip().casefold() != b.character_name.strip().casefold():
            continue
        if b.brief.strip() and p.voice_id not in briefs:
            briefs[p.voice_id] = b.brief.strip()
    return briefs


def validate_flags(result: PassageCheck, rendered: RenderedCast) -> dict[UUID, tuple[str, str]]:
    """``passage id → (reason, revision)`` for flags on known, not accepted passages.

    The stored reason starts with the problem kind; a flag without a
    revised translation is dropped.
    """
    labels = {
        "flattened": "Flattened",
        "sounds_like_other": "Sounds like another character",
        "off_brief": "Off brief",
    }
    flags: dict[UUID, tuple[str, str]] = {}
    for f in result.passage_flags:
        ps = rendered.passages.get(_passage_key(f.passage))
        if ps is None or ps.accepted or not f.revised_translation.strip():
            continue
        if ps.id in flags:
            continue
        reason = f"{labels.get(f.problem, f.problem)}: {f.reason.strip()}"
        flags[ps.id] = (reason, f.revised_translation.strip())
    return flags


SAMPLE_LINES = 12
LINES_TO_THEM = 5
MIN_SAMPLE_WORDS = 6


def pick_sample(lines: list[SpokenLine], k: int, *, min_words: int = MIN_SAMPLE_WORDS) -> list[str]:
    """Up to ``k`` lines spread over the book, as ``"[ch. N] text"``.

    Prefers lines with at least ``min_words`` words and a speaker the text
    names; falls back to any line when there are too few.
    """

    def evenly(items: list[SpokenLine], n: int) -> list[SpokenLine]:
        if n >= len(items):
            return list(items)
        step = len(items) / n
        return [items[int(i * step)] for i in range(n)]

    good = [ln for ln in lines if len(ln.text.split()) >= min_words and not ln.inferred]
    pool = good if len(good) >= k else [ln for ln in lines if len(ln.text.split()) >= min_words]
    if len(pool) < k:
        pool = lines
    chosen = sorted(evenly(pool, k), key=lambda ln: ln.line_index)
    return [f"[ch. {ln.chapter_number}] {ln.text}" for ln in chosen]
