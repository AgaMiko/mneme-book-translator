"""Special passages (Step 6): scan, check, correction and author actions.

Flow
----
1. ``scan_book`` reads every chapter once (before or during translation).
   One call per chapter lists candidate passages; one call per candidate,
   given the passage's first-letter strings, states the rule or says there
   is none. Passages with a rule are stored as ``SpecialPassage`` rows.
2. ``check_book`` runs after translation. For each passage whose
   paragraphs are translated it checks the English against the rule: with
   code where the rule is about letters or line counts
   (``passage_rules``), with a model otherwise. When the rule is broken
   the passage is translated again, up to ``PASSAGES_REWRITE_ATTEMPTS``
   times, and each attempt is checked the same way. The first attempt
   that passes replaces the text in the fragment's final rendition.
3. Every checked passage gets one ``TranslationFlag``: ``fyi`` when the
   rule was kept, ``review`` when the text was corrected, ``blocking``
   when no attempt passed. ``resolve_passage`` applies the author's
   answer (accept, restore the first translation, use another attempt,
   edit, dismiss).

A passage is checked again when its English changed since the last check,
for example after the fragment was re-translated.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from langfuse import propagate_attributes
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.generation.chains.special_passages_chain import (
    check_passage,
    describe_rule,
    rewrite_passage,
    scan_chapter,
)
from app.models.book import Book, Chapter
from app.models.passages import PASSAGE_KINDS, SpecialPassage, TranslationFlag
from app.models.translation import FragmentRendition, TranslationRun
from app.services.passage_rules import (
    UNITS,
    Unit,
    hidden_message_problems,
    line_count_problems,
    message_slack,
    render_letter_strings,
    spelled_message,
    stated_messages,
)
from app.services.translation_service import (
    load_book_with_text,
    load_current_renditions,
    title_paragraph_id,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings
    from app.generation.prompt_manager.models.special_passages_model import (
        PassageCandidate,
        PassageRewrite,
        PassageRule,
    )

log = get_logger(__name__)

_SCAN_CONCURRENCY = 4
# A longer run of paragraphs is a scene, not a passage.
_MAX_PASSAGE_PARAGRAPHS = 60
_BUSY = ("scanning", "checking")
_STALE_ERROR = "The server restarted while this was running. Start it again."
_AUTHOR_RULE = (
    "Marked by the author. Keep the form of the source: its lines and rhyme, "
    "and any message its letters spell."
)

Action = Literal["accept", "restore", "use_candidate", "edit", "dismiss"]


class PassageConflictError(RuntimeError):
    """The request does not fit the current state (a run is active, ids overlap…)."""


# ─── Chapter text ────────────────────────────────────────


@dataclass(slots=True)
class ChapterText:
    """One chapter's heading and paragraphs under short prompt ids."""

    chapter_id: UUID
    position: int
    # (real id, short id, text): the heading is ``t``, paragraphs ``p1``, ``p2``…
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def by_short(self) -> dict[str, int]:
        return {short: i for i, (_, short, _) in enumerate(self.rows)}

    def render(self, rows: list[tuple[str, str, str]] | None = None) -> str:
        return "\n\n".join(f"[{short}] {text}" for _, short, text in (rows or self.rows))


def chapter_text(chapter: Chapter) -> ChapterText:
    out = ChapterText(chapter_id=chapter.id, position=chapter.position)
    title = (chapter.title or "").strip()
    # A one-line heading has no epigraph, so there is nothing to scan in it.
    if "\n" in title:
        out.rows.append((title_paragraph_id(chapter.id), "t", title))
    n = 0
    for p in chapter.paragraphs:
        text = (p.text or "").strip()
        if text:
            n += 1
            out.rows.append((str(p.id), f"p{n}", text))
    return out


def _short_id(raw: str) -> str:
    """``p12`` from ``[p12]``, ``P12`` or ``p 12``."""
    return "".join(ch for ch in raw.lower() if ch.isalnum())


def candidate_range(candidate: PassageCandidate, chapter: ChapterText) -> tuple[int, int] | None:
    """Row indexes of a candidate, or ``None`` when its ids are not usable."""
    index = chapter.by_short
    first = index.get(_short_id(candidate.first_paragraph))
    last = index.get(_short_id(candidate.last_paragraph))
    if first is None or last is None or last < first:
        return None
    if last - first + 1 > _MAX_PASSAGE_PARAGRAPHS:
        return None
    return first, last


@dataclass(slots=True)
class FoundPassage:
    chapter_id: UUID
    position: int
    kind: str
    paragraph_ids: list[str]
    dependent_paragraph_ids: list[str]
    rule: str
    unit: str | None
    source_message: str | None
    target_message: str | None
    evidence: str


def found_from_rule(
    rule: PassageRule, chapter: ChapterText, first: int, last: int, evidence: str
) -> FoundPassage | None:
    """A passage to store, or ``None`` when the rule call found no rule."""
    if rule.kind == "none" or not rule.rule.strip():
        return None
    ids = [real for real, _, _ in chapter.rows[first : last + 1]]
    index = chapter.by_short
    dependents: list[str] = []
    for raw in rule.dependent_paragraphs:
        i = index.get(_short_id(raw))
        if i is not None and not first <= i <= last and chapter.rows[i][0] not in dependents:
            dependents.append(chapter.rows[i][0])
    hidden = rule.kind == "hidden_message"
    return FoundPassage(
        chapter_id=chapter.chapter_id,
        position=chapter.position * 100_000 + first,
        kind=rule.kind,
        paragraph_ids=ids,
        dependent_paragraph_ids=dependents,
        rule=rule.rule.strip(),
        unit=rule.unit if hidden and rule.unit in UNITS else None,
        source_message=(rule.source_message.strip() or None) if hidden else None,
        target_message=(rule.target_message.strip() or None) if hidden else None,
        evidence=evidence.strip(),
    )


# ─── State on the book ───────────────────────────────────


async def _set_state(book_id: UUID, **values: Any) -> None:
    async with get_sessionmaker()() as session:
        book = await session.get(Book, book_id)
        if book is None:
            return
        # A new dict, so SQLAlchemy sees the change to the JSONB column.
        book.passages_state = {**(book.passages_state or {}), **values}
        await session.commit()


def _status(book: Book) -> str:
    return str((book.passages_state or {}).get("status") or "idle")


async def claim(session: AsyncSession, *, book_id: UUID, status: str) -> None:
    """Mark the book as scanning or checking; refuse when it already is."""
    book = await session.get(Book, book_id)
    if book is None:
        raise LookupError("Book not found")
    if _status(book) in _BUSY:
        raise PassageConflictError("A scan or check is already running for this book.")
    if status == "checking" and await _translation_running(session, book_id):
        raise PassageConflictError("Wait for the running translation to finish or stop it first.")
    book.passages_state = {
        "status": status,
        "done": 0,
        "total": 0,
        "error": None,
        "scanned": bool((book.passages_state or {}).get("scanned")),
    }
    await session.commit()


async def _translation_running(session: AsyncSession, book_id: UUID) -> bool:
    return (
        await session.execute(
            select(TranslationRun.id)
            .where(TranslationRun.book_id == book_id, TranslationRun.status == "running")
            .limit(1)
        )
    ).first() is not None


async def reconcile_stale_passage_runs_on_startup() -> None:
    async with get_sessionmaker()() as session:
        books = (await session.execute(select(Book))).scalars().all()
        for book in books:
            if _status(book) in _BUSY:
                book.passages_state = {
                    **book.passages_state,
                    "status": "failed",
                    "error": _STALE_ERROR,
                }
        await session.commit()


# ─── Scan ────────────────────────────────────────────────


async def _find_in_chapter(
    chapter: ChapterText, *, source_language: str, target_language: str, settings: Settings
) -> list[FoundPassage]:
    rendered = chapter.render()
    scan = await scan_chapter(
        chapter_text=rendered,
        source_language=source_language,
        target_language=target_language,
        settings=settings,
    )
    found: list[FoundPassage] = []
    taken: set[str] = set()
    for candidate in scan.candidates:
        span = candidate_range(candidate, chapter)
        if span is None:
            continue
        first, last = span
        rows = chapter.rows[first : last + 1]
        if taken & {real for real, _, _ in rows}:
            continue
        rule = await describe_rule(
            passage_text=chapter.render(rows),
            first_id=rows[0][1],
            last_id=rows[-1][1],
            candidate_kind=candidate.kind,
            letter_strings=render_letter_strings([text for _, _, text in rows]),
            chapter_text=rendered,
            source_language=source_language,
            target_language=target_language,
            settings=settings,
        )
        passage = found_from_rule(rule, chapter, first, last, candidate.evidence)
        if passage is not None:
            found.append(passage)
            taken.update(passage.paragraph_ids)
    return found


async def scan_book(*, book_id: UUID, settings: Settings) -> None:
    """Find special passages in every chapter. The caller has claimed ``scanning``."""
    async with get_sessionmaker()() as session:
        book = await load_book_with_text(session, book_id)
        if book is None:
            return
        chapters = [chapter_text(c) for c in sorted(book.chapters, key=lambda c: c.position)]
        chapters = [c for c in chapters if c.rows]
        source_language, target_language = book.resolved_source_language, book.target_language
    await _set_state(book_id, total=len(chapters))

    semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)
    done = 0
    errors: list[str] = []

    async def worker(chapter: ChapterText) -> None:
        nonlocal done
        async with semaphore:
            try:
                found = await _find_in_chapter(
                    chapter,
                    source_language=source_language,
                    target_language=target_language,
                    settings=settings,
                )
                await _store_found(book_id, found)
            except Exception as exc:
                log.exception("passages_scan_chapter_failed", chapter_id=str(chapter.chapter_id))
                errors.append(str(exc))
        done += 1
        await _set_state(book_id, done=done)

    with propagate_attributes(session_id=str(book_id)):
        await asyncio.gather(*(worker(c) for c in chapters))

    if errors and len(errors) == len(chapters):
        await _set_state(book_id, status="failed", error=errors[0])
    else:
        note = f"{len(errors)} chapters could not be scanned." if errors else None
        await _set_state(book_id, status="completed", error=note, scanned=True)


async def _store_found(book_id: UUID, found: list[FoundPassage]) -> None:
    """Store new passages, leaving out any that overlap one the book already has."""
    if not found:
        return
    async with get_sessionmaker()() as session:
        existing = (
            (
                await session.execute(
                    select(SpecialPassage.paragraph_ids).where(SpecialPassage.book_id == book_id)
                )
            )
            .scalars()
            .all()
        )
        taken = {pid for ids in existing for pid in ids}
        for f in found:
            if taken & set(f.paragraph_ids):
                continue
            session.add(
                SpecialPassage(
                    book_id=book_id,
                    chapter_id=f.chapter_id,
                    position=f.position,
                    kind=f.kind,
                    paragraph_ids=f.paragraph_ids,
                    dependent_paragraph_ids=f.dependent_paragraph_ids,
                    rule=f.rule,
                    unit=f.unit,
                    source_message=f.source_message,
                    target_message=f.target_message,
                    evidence=f.evidence,
                )
            )
        await session.commit()


# ─── English text of the book ────────────────────────────


async def _final_renditions(
    session: AsyncSession, book_id: UUID, chapter_ids: list[UUID] | None = None
) -> list[FragmentRendition]:
    """The final-stage rendition of each fragment's current run."""
    latest = await load_current_renditions(session, book_id=book_id, chapter_ids=chapter_ids)
    return [r for (_, stage), r in latest.items() if stage == "polish"]


def english_of(renditions: list[FragmentRendition]) -> dict[str, str]:
    return {
        str(p.get("paragraph_id")): str(p.get("text", "")) for r in renditions for p in r.paragraphs
    }


def apply_texts(renditions: list[FragmentRendition], texts: dict[str, str]) -> None:
    """Write ``paragraph id → text`` into the renditions that hold those paragraphs."""
    for r in renditions:
        if not any(str(p.get("paragraph_id")) in texts for p in r.paragraphs):
            continue
        # A new list, so SQLAlchemy sees the change to the JSONB column.
        r.paragraphs = [
            {**p, "text": texts.get(str(p.get("paragraph_id")), p.get("text", ""))}
            for p in r.paragraphs
        ]


def _snapshot(ids: list[str], english: dict[str, str]) -> list[dict[str, str]]:
    return [{"paragraph_id": i, "text": english[i]} for i in ids if i in english]


def _all_ids(passage: SpecialPassage) -> list[str]:
    return [*passage.paragraph_ids, *passage.dependent_paragraph_ids]


def own_text_changed(passage: SpecialPassage, english: dict[str, str]) -> bool:
    """The passage's own paragraphs differ from the last check.

    Dependent paragraphs are left out: two passages can share them (a scene
    that decodes both), and a correction of one must not make the other
    look changed.
    """
    own = set(passage.paragraph_ids)
    checked = [r for r in passage.checked_translation or [] if r["paragraph_id"] in own]
    return _snapshot(passage.paragraph_ids, english) != checked


def needs_check(passage: SpecialPassage, english: dict[str, str]) -> bool:
    """Translated, and never checked or changed since the last check."""
    if passage.status == "dismissed":
        return False
    if any(i not in english for i in passage.paragraph_ids):
        return False
    if passage.status == "unchecked":
        return True
    return own_text_changed(passage, english)


# ─── Check and correction ────────────────────────────────


def code_problems(
    *,
    kind: str,
    unit: str | None,
    target_message: str | None,
    source_texts: list[str],
    target_texts: list[str],
    source_message: str | None = None,
    also: list[str] | None = None,
) -> list[str]:
    """What code can see is wrong; empty when it sees nothing."""
    if kind == "verse":
        return line_count_problems(source_texts, target_texts)
    if kind == "hidden_message" and unit in UNITS:
        slack = message_slack(source_texts, cast("Unit", unit), source_message)
        return hidden_message_problems(target_texts, unit or "", target_message or "", also, slack)
    return []


def code_decides(*, kind: str, unit: str | None, target_message: str | None) -> bool:
    """Whether the code check alone settles the rule (first-letter messages)."""
    return kind == "hidden_message" and unit in UNITS and bool((target_message or "").strip())


@dataclass(slots=True)
class _Job:
    passage_id: UUID
    kind: str
    rule: str
    unit: str | None
    source_message: str | None
    target_message: str | None
    ids: list[str]
    dependent_ids: list[str]
    source: dict[str, str]
    english: dict[str, str]
    chapter: ChapterText
    source_language: str
    target_language: str


@dataclass(slots=True)
class _Outcome:
    status: str
    problems: list[str]
    candidates: list[dict[str, Any]]
    # Text to write into the renditions (empty unless corrected).
    texts: dict[str, str]
    job: _Job


def _block(ids: list[str], texts: dict[str, str]) -> str:
    return "\n\n".join(f"[{i}] {texts.get(i, '')}" for i in ids)


def _dependent_block(job: _Job, english: dict[str, str], short: dict[str, str]) -> str:
    parts = []
    for i in job.dependent_ids:
        if i in english:
            parts.append(f"[{short[i]}] {job.source.get(i, '')}\n[{short[i]}] {english[i]}")
    return "\n\n".join(parts)


async def _problems(job: _Job, english: dict[str, str], settings: Settings) -> list[str]:
    """Why ``english`` breaks the passage's rule; empty when it keeps it."""
    source_texts = [job.source.get(i, "") for i in job.ids]
    target_texts = [english.get(i, "") for i in job.ids]
    if code_decides(kind=job.kind, unit=job.unit, target_message=job.target_message):
        # The translation may spell its own wording of the message (the first
        # translation chose it, or the author did). That is fine when the
        # decoding scene states the same words.
        stated = stated_messages([english[i] for i in job.dependent_ids if i in english])
        unit = cast("Unit", job.unit)
        spelled = spelled_message(
            target_texts,
            unit,
            [job.target_message or "", *stated],
            message_slack(source_texts, unit, job.source_message),
        )
        if spelled is not None:
            job.target_message = spelled
            return []
    found = code_problems(
        kind=job.kind,
        unit=job.unit,
        target_message=job.target_message,
        source_texts=source_texts,
        target_texts=target_texts,
        source_message=job.source_message,
    )
    if found or code_decides(kind=job.kind, unit=job.unit, target_message=job.target_message):
        return found
    short = {real: s for real, s, _ in job.chapter.rows}
    verdict = await check_passage(
        kind=job.kind,
        rule=job.rule,
        source_message=job.source_message,
        target_message=job.target_message,
        source_text=_block([short[i] for i in job.ids], {short[i]: job.source[i] for i in job.ids}),
        target_text=_block([short[i] for i in job.ids], {short[i]: english[i] for i in job.ids}),
        letter_strings=render_letter_strings(target_texts),
        dependent_text=_dependent_block(job, english, short),
        source_language=job.source_language,
        target_language=job.target_language,
        settings=settings,
    )
    if verdict.kept and not verdict.problems:
        return []
    return [p.strip() for p in verdict.problems if p.strip()] or ["The rule is not kept."]


def rewrite_texts(
    rewrite: PassageRewrite, *, ids: list[str], dependent_ids: list[str], short: dict[str, str]
) -> dict[str, str] | None:
    """``real id → text`` from a rewrite, or ``None`` when its paragraphs do not match."""
    real = {s: r for r, s in short.items()}
    got = [real.get(_short_id(p.paragraph_id)) for p in rewrite.paragraphs]
    if got != ids or any(not p.text.strip() for p in rewrite.paragraphs):
        return None
    out = {i: p.text.strip() for i, p in zip(ids, rewrite.paragraphs, strict=True)}
    for p in rewrite.dependent_paragraphs:
        i = real.get(_short_id(p.paragraph_id))
        if i in dependent_ids and p.text.strip():
            out[i] = p.text.strip()
    return out


async def _fill_rule(job: _Job, settings: Settings) -> None:
    """Work out the rule of a passage the author marked without one."""
    rows = [r for r in job.chapter.rows if r[0] in job.ids]
    rule = await describe_rule(
        passage_text=job.chapter.render(rows),
        first_id=rows[0][1],
        last_id=rows[-1][1],
        candidate_kind=job.kind,
        letter_strings=render_letter_strings([t for _, _, t in rows]),
        chapter_text=job.chapter.render(),
        source_language=job.source_language,
        target_language=job.target_language,
        settings=settings,
    )
    index = job.chapter.by_short
    found = found_from_rule(rule, job.chapter, index[rows[0][1]], index[rows[-1][1]], "")
    if found is None:
        job.rule = _AUTHOR_RULE
        return
    job.kind, job.rule, job.unit = found.kind, found.rule, found.unit
    job.source_message, job.target_message = found.source_message, found.target_message
    job.dependent_ids = found.dependent_paragraph_ids


async def _check_one(job: _Job, settings: Settings) -> _Outcome:
    if not job.rule.strip():
        await _fill_rule(job, settings)
    problems = await _problems(job, job.english, settings)
    if not problems:
        return _Outcome("passed", [], [], {}, job)

    short = {real: s for real, s, _ in job.chapter.rows}
    short_ids = [short[i] for i in job.ids]
    source_text = _block(short_ids, {short[i]: job.source[i] for i in job.ids})
    candidates: list[dict[str, Any]] = []
    current, feedback = dict(job.english), problems
    for _ in range(max(1, settings.PASSAGES_REWRITE_ATTEMPTS)):
        rewrite = await rewrite_passage(
            kind=job.kind,
            rule=job.rule,
            source_message=job.source_message,
            target_message=job.target_message,
            problems=feedback,
            source_text=source_text,
            target_text=_block(short_ids, {short[i]: current[i] for i in job.ids}),
            dependent_text=_dependent_block(job, current, short),
            source_language=job.source_language,
            target_language=job.target_language,
            settings=settings,
        )
        texts = rewrite_texts(rewrite, ids=job.ids, dependent_ids=job.dependent_ids, short=short)
        if texts is None:
            feedback = [*problems, "Your last answer did not return the passage's paragraphs."]
            continue
        attempt = {**job.english, **texts}
        found = await _problems(job, attempt, settings)
        candidates.append(
            {
                "paragraphs": [{"paragraph_id": i, "text": t} for i, t in texts.items()],
                "target_message": rewrite.target_message.strip() or None,
                "notes": rewrite.notes.strip(),
                "problems": found,
            }
        )
        if not found:
            return _Outcome("corrected", problems, candidates, texts, job)
        # Work on from this attempt: it is usually closer than the first translation.
        current, feedback = attempt, found
    return _Outcome("failed", problems, candidates, {}, job)


_QUESTIONS = {
    "passed": "The translation keeps the rule. Nothing was changed.",
    "corrected": (
        "The first translation broke the rule, so the passage was translated again "
        "and the new text passed the check. Compare the two versions."
    ),
    "failed": (
        "The translation breaks the rule and no new version passed the check. "
        "Choose a version or write the text."
    ),
}
_SEVERITY = {"passed": "fyi", "corrected": "review", "failed": "blocking"}


async def _flag_for(session: AsyncSession, passage: SpecialPassage) -> TranslationFlag:
    flag = (
        await session.execute(
            select(TranslationFlag).where(TranslationFlag.special_passage_id == passage.id)
        )
    ).scalar_one_or_none()
    if flag is None:
        flag = TranslationFlag(
            book_id=passage.book_id,
            special_passage_id=passage.id,
            paragraph_id=passage.paragraph_ids[0],
        )
        session.add(flag)
    return flag


async def _save_outcome(outcome: _Outcome) -> None:
    job = outcome.job
    async with get_sessionmaker()() as session:
        passage = await session.get(SpecialPassage, job.passage_id)
        if passage is None or passage.status == "dismissed":
            return
        renditions = await _final_renditions(session, passage.book_id)
        passage.kind, passage.rule, passage.unit = job.kind, job.rule, job.unit
        passage.source_message, passage.target_message = job.source_message, job.target_message
        passage.dependent_paragraph_ids = job.dependent_ids
        ids = _all_ids(passage)
        english = english_of(renditions)
        # Text that changed since the last check is a fresh translation, so it
        # is the new "first"; a second check of the same text keeps the old one.
        fresh = passage.first_translation is None or own_text_changed(passage, english)
        if fresh:
            passage.first_translation = _snapshot(ids, english)
        elif outcome.status == "passed" and passage.status in ("corrected", "author"):
            # A second check of text this step or the author wrote: it still
            # keeps the rule. Keep the status, problems, versions and flag.
            passage.checked_translation = _snapshot(ids, english)
            await session.commit()
            return
        if outcome.texts:
            apply_texts(renditions, outcome.texts)
        passage.checked_translation = _snapshot(ids, english_of(renditions))
        passage.status = outcome.status
        passage.problems = outcome.problems
        passage.candidates = outcome.candidates
        flag = await _flag_for(session, passage)
        flag.severity = _SEVERITY[outcome.status]
        flag.question = _QUESTIONS[outcome.status]
        flag.status, flag.resolved_at, flag.author_response = "open", None, None
        await session.commit()


async def check_book(*, book_id: UUID, settings: Settings, passage_id: UUID | None = None) -> None:
    """Check translated passages and correct the ones that break their rule.

    With ``passage_id``, that passage is checked again whatever its state.
    The caller has claimed ``checking``.
    """
    async with get_sessionmaker()() as session:
        book = await load_book_with_text(session, book_id)
        if book is None:
            return
        chapters = {c.id: chapter_text(c) for c in book.chapters}
        passages = (
            (
                await session.execute(
                    select(SpecialPassage)
                    .where(SpecialPassage.book_id == book_id)
                    .order_by(SpecialPassage.position)
                )
            )
            .scalars()
            .all()
        )
        english = english_of(await _final_renditions(session, book_id))
        jobs: list[_Job] = []
        for p in passages:
            forced = (
                p.id == passage_id
                and p.status != "dismissed"
                and all(i in english for i in p.paragraph_ids)
            )
            chapter = chapters.get(p.chapter_id)
            if chapter is None or not (forced or needs_check(p, english)):
                continue
            source = {real: text for real, _, text in chapter.rows}
            if any(i not in source for i in p.paragraph_ids):
                continue
            jobs.append(
                _Job(
                    passage_id=p.id,
                    kind=p.kind,
                    rule=p.rule,
                    unit=p.unit,
                    source_message=p.source_message,
                    target_message=p.target_message,
                    ids=list(p.paragraph_ids),
                    dependent_ids=[i for i in p.dependent_paragraph_ids if i in source],
                    source=source,
                    english=english,
                    chapter=chapter,
                    source_language=book.resolved_source_language,
                    target_language=book.target_language,
                )
            )
    await _set_state(book_id, total=len(jobs))

    # One passage at a time, each read from the current English: passages in
    # the same fragment, or sharing a decoding scene, would otherwise
    # overwrite each other's corrections.
    errors: list[str] = []
    with propagate_attributes(session_id=str(book_id)):
        for done, job in enumerate(jobs, start=1):
            try:
                async with get_sessionmaker()() as session:
                    job.english = english_of(await _final_renditions(session, book_id))
                await _save_outcome(await _check_one(job, settings))
            except Exception as exc:
                log.exception("passages_check_failed", passage_id=str(job.passage_id))
                errors.append(str(exc))
            await _set_state(book_id, done=done)

    if errors and len(errors) == len(jobs):
        await _set_state(book_id, status="failed", error=errors[0])
    else:
        note = f"{len(errors)} passages could not be checked." if errors else None
        await _set_state(book_id, status="completed", error=note)


async def run_around_translation(*, book_id: UUID, settings: Settings, translate: Any) -> None:
    """Scan (first time only) while ``translate`` runs, then check the passages.

    ``translate`` is the translation run's coroutine. A failure here never
    fails the translation.
    """

    async def scan_once() -> None:
        try:
            async with get_sessionmaker()() as session:
                book = await session.get(Book, book_id)
                if book is None or (book.passages_state or {}).get("scanned"):
                    return
                await claim(session, book_id=book_id, status="scanning")
            await scan_book(book_id=book_id, settings=settings)
        except PassageConflictError:
            return
        except Exception as exc:
            log.exception("passages_scan_failed", book_id=str(book_id))
            await _set_state(book_id, status="failed", error=str(exc))

    scan = asyncio.create_task(scan_once())
    try:
        await translate
    finally:
        await scan
    try:
        async with get_sessionmaker()() as session:
            await claim(session, book_id=book_id, status="checking")
        await check_book(book_id=book_id, settings=settings)
    except (PassageConflictError, LookupError):
        return
    except Exception as exc:
        log.exception("passages_check_failed", book_id=str(book_id))
        await _set_state(book_id, status="failed", error=str(exc))


# ─── Author actions ──────────────────────────────────────


async def create_passage(
    session: AsyncSession,
    *,
    book_id: UUID,
    first_paragraph_id: UUID,
    last_paragraph_id: UUID,
    kind: str,
    rule: str,
) -> SpecialPassage:
    """A passage the author marked: a run of paragraphs in one chapter."""
    if kind not in PASSAGE_KINDS:
        raise ValueError(f"Unknown kind: {kind}")
    book = await load_book_with_text(session, book_id)
    if book is None:
        raise LookupError("Book not found")
    for chapter in book.chapters:
        ids = [p.id for p in chapter.paragraphs if (p.text or "").strip()]
        if first_paragraph_id in ids and last_paragraph_id in ids:
            first, last = ids.index(first_paragraph_id), ids.index(last_paragraph_id)
            break
    else:
        raise PassageConflictError("Both paragraphs must be in the same chapter.")
    if last < first:
        first, last = last, first
    chosen = [str(i) for i in ids[first : last + 1]]
    existing = (
        (
            await session.execute(
                select(SpecialPassage.paragraph_ids).where(SpecialPassage.book_id == book_id)
            )
        )
        .scalars()
        .all()
    )
    if {pid for row in existing for pid in row} & set(chosen):
        raise PassageConflictError("These paragraphs are already part of a special passage.")
    passage = SpecialPassage(
        book_id=book_id,
        chapter_id=chapter.id,
        position=chapter.position * 100_000 + first + 1,
        kind=kind,
        paragraph_ids=chosen,
        rule=rule.strip(),
        origin="author",
    )
    session.add(passage)
    await session.commit()
    return passage


async def update_rule(
    session: AsyncSession,
    *,
    passage_id: UUID,
    rule: str | None,
    target_message: str | None,
) -> SpecialPassage:
    """The author rewrites the rule or the target message; the passage is checked again."""
    passage = await session.get(SpecialPassage, passage_id)
    if passage is None:
        raise LookupError("Passage not found")
    if rule is not None and rule.strip():
        passage.rule = rule.strip()
    if target_message is not None:
        passage.target_message = target_message.strip() or None
    if passage.status != "dismissed":
        passage.status = "unchecked"
    await session.commit()
    return passage


async def resolve_passage(
    session: AsyncSession,
    *,
    passage_id: UUID,
    action: Action,
    candidate: int | None = None,
    paragraphs: list[dict[str, str]] | None = None,
) -> SpecialPassage:
    """Apply the author's answer to a passage's flag."""
    passage = await session.get(SpecialPassage, passage_id)
    if passage is None:
        raise LookupError("Passage not found")
    if await _translation_running(session, passage.book_id):
        raise PassageConflictError("Wait for the running translation to finish or stop it first.")
    renditions = await _final_renditions(session, passage.book_id)
    ids = _all_ids(passage)

    texts: dict[str, str] = {}
    flag_status = "accepted"
    if action == "restore" or (action == "dismiss" and passage.status in ("corrected", "author")):
        texts = {p["paragraph_id"]: p["text"] for p in passage.first_translation or []}
        if action == "restore" and not texts:
            raise PassageConflictError("There is no earlier translation to restore.")
    elif action == "use_candidate":
        if candidate is None or not 0 <= candidate < len(passage.candidates):
            raise PassageConflictError("That version does not exist.")
        texts = {p["paragraph_id"]: p["text"] for p in passage.candidates[candidate]["paragraphs"]}
        # Dependent paragraphs this version did not touch go back to the first translation.
        first = {p["paragraph_id"]: p["text"] for p in passage.first_translation or []}
        texts = {**{i: first[i] for i in passage.dependent_paragraph_ids if i in first}, **texts}
    elif action == "edit":
        texts = {
            p["paragraph_id"]: p["text"].strip()
            for p in paragraphs or []
            if p.get("paragraph_id") in ids and p.get("text", "").strip()
        }
        if not texts:
            raise PassageConflictError("No text to save.")

    if texts:
        if passage.first_translation is None:
            passage.first_translation = _snapshot(ids, english_of(renditions))
        apply_texts(renditions, texts)
    if action == "dismiss":
        passage.status, flag_status = "dismissed", "dismissed"
    elif action != "accept":
        passage.status, flag_status = "author", "changed"
    passage.checked_translation = _snapshot(ids, english_of(renditions))

    flag = await _flag_for(session, passage)
    if not flag.question:
        flag.question = "Marked as a special passage."
    flag.status, flag.resolved_at = flag_status, datetime.now(UTC)
    await session.commit()
    return passage


# ─── Read model ──────────────────────────────────────────


def _chapter_label(title: str | None, number: int) -> str:
    lines = [ln.strip() for ln in (title or "").splitlines() if ln.strip()]
    return " · ".join(lines[:2]) if lines else f"Chapter {number}"


async def build_view(session: AsyncSession, *, book_id: UUID) -> dict[str, Any]:
    """Passages with their text. Reads only the chapters that hold a passage."""
    book = await session.get(Book, book_id)
    if book is None:
        raise LookupError("Book not found")
    headings = (
        await session.execute(
            select(Chapter.id, Chapter.title)
            .where(Chapter.book_id == book_id)
            .order_by(Chapter.position)
        )
    ).all()
    labels = {cid: _chapter_label(title, n) for n, (cid, title) in enumerate(headings, start=1)}
    passages = (
        (
            await session.execute(
                select(SpecialPassage)
                .where(SpecialPassage.book_id == book_id)
                .order_by(SpecialPassage.position)
            )
        )
        .scalars()
        .all()
    )
    chapter_ids = list({p.chapter_id for p in passages})
    chapters = (
        (
            await session.execute(
                select(Chapter)
                .where(Chapter.id.in_(chapter_ids))
                .options(selectinload(Chapter.paragraphs))
            )
        )
        .scalars()
        .all()
        if chapter_ids
        else []
    )
    source = {real: text for c in chapters for real, _, text in chapter_text(c).rows}
    for c in chapters:
        # One-line headings are not in ``chapter_text``; a passage never uses them.
        source.setdefault(title_paragraph_id(c.id), (c.title or "").strip())
    english = (
        english_of(await _final_renditions(session, book_id, chapter_ids)) if chapter_ids else {}
    )
    flags = {
        f.special_passage_id: f
        for f in (
            await session.execute(select(TranslationFlag).where(TranslationFlag.book_id == book_id))
        )
        .scalars()
        .all()
    }

    def rows(ids: list[str], first: dict[str, str]) -> list[dict[str, Any]]:
        return [
            {
                "paragraph_id": i,
                "source": source.get(i, ""),
                "text": english.get(i),
                "first_text": first.get(i),
            }
            for i in ids
        ]

    out = []
    for p in passages:
        first = {r["paragraph_id"]: r["text"] for r in p.first_translation or []}
        flag = flags.get(p.id)
        out.append(
            {
                "id": str(p.id),
                "chapter_id": str(p.chapter_id),
                "chapter_label": labels.get(p.chapter_id, ""),
                "kind": p.kind,
                "rule": p.rule,
                "unit": p.unit,
                "source_message": p.source_message,
                "target_message": p.target_message,
                "evidence": p.evidence,
                "origin": p.origin,
                "status": p.status,
                "problems": p.problems,
                "translated": all(i in english for i in p.paragraph_ids),
                "stale": p.status != "unchecked" and needs_check(p, english),
                "paragraphs": rows(list(p.paragraph_ids), first),
                "dependent_paragraphs": rows(list(p.dependent_paragraph_ids), first),
                "candidates": p.candidates,
                "flag": None
                if flag is None
                else {
                    "id": str(flag.id),
                    "severity": flag.severity,
                    "status": flag.status,
                    "question": flag.question,
                },
            }
        )
    open_flags = [f for f in flags.values() if f.status == "open"]
    state = book.passages_state or {}
    return {
        "state": {
            "status": state.get("status") or "idle",
            "done": int(state.get("done") or 0),
            "total": int(state.get("total") or 0),
            "error": state.get("error"),
            "scanned": bool(state.get("scanned")),
        },
        "passages": out,
        "open_flags": len(open_flags),
        "blocking_flags": sum(1 for f in open_flags if f.severity == "blocking"),
    }


async def blocking_flag_count(session: AsyncSession, *, book_id: UUID) -> int:
    rows = (
        await session.execute(
            select(TranslationFlag.id).where(
                TranslationFlag.book_id == book_id,
                TranslationFlag.status == "open",
                TranslationFlag.severity == "blocking",
            )
        )
    ).all()
    return len(rows)
