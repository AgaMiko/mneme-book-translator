"""Cross-check helpers for Pass 1 (speaker identification).

Background
----------
Each ``SpeakerInWindow`` carries TWO references to its target character
(a UUID-style ``glossary_entry_id`` and a human-readable
``canonical_name``) plus a verbatim ``quoted_evidence`` phrase. The
model has to copy the first two from the prompt's glossary list and
copy the third from the source text. Two failure modes:

1. ID and name disagree — the model pasted one character's UUID with
   another's name.
2. ``quoted_evidence`` doesn't actually appear in the window — the
   model hallucinated a phrase to satisfy the schema.

These helpers are pure functions over already-loaded glossary
characters and the window text. They return only the entries that
pass both checks; mismatches are filtered out and logged. Drop them
into ``apply_speakers_delta`` before the persistence step.

Same shape as ``voice_validation``; the duplication is on purpose
(separate stages, separate models, independent evolution).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.generation.prompt_manager.models.identify_speakers_model import (
        SpeakerInWindow,
    )

logger = logging.getLogger(__name__)


def _normalize_whitespace(s: str) -> str:
    """Collapse all whitespace runs to single spaces.

    Tolerates source text that uses non-breaking spaces, multiple
    spaces, or stray newlines around quoted dialogue. The model is
    told to copy verbatim, but small whitespace drift is common and
    not a hallucination — only meaningful textual divergence counts
    as a miss.
    """
    return " ".join(s.split())


def filter_id_mismatches(
    speakers: list[SpeakerInWindow],
    *,
    glossary_name_by_id: dict[str, str],
) -> list[SpeakerInWindow]:
    """Keep only entries where canonical_name matches the name on the
    glossary entry their ``glossary_entry_id`` resolves to.

    ``glossary_name_by_id`` is built once per ``apply_speakers_delta``
    from the loaded character list:

        {c.glossary_entry_id: c.canonical_name for c in characters}
    """
    kept: list[SpeakerInWindow] = []
    for s in speakers:
        expected = glossary_name_by_id.get(s.glossary_entry_id)
        if expected is None:
            logger.warning(
                "Speaker references unknown glossary_entry_id %s "
                "(claimed name=%r); dropping entry.",
                s.glossary_entry_id,
                s.canonical_name,
            )
            continue
        if s.canonical_name.strip() != expected.strip():
            logger.warning(
                "Speaker name/ID mismatch: glossary_entry_id=%s resolves "
                "to %r but model wrote canonical_name=%r; dropping entry.",
                s.glossary_entry_id,
                expected,
                s.canonical_name,
            )
            continue
        kept.append(s)
    return kept


def filter_evidence_mismatches(
    speakers: list[SpeakerInWindow],
    *,
    window_text: str,
) -> list[SpeakerInWindow]:
    """Keep only entries whose ``quoted_evidence`` appears in the window text.

    Whitespace is normalised on both sides before comparison so
    minor source-text formatting (non-breaking spaces, double
    spaces, line wraps) doesn't cause spurious drops.
    """
    normalized_window = _normalize_whitespace(window_text)
    kept: list[SpeakerInWindow] = []
    for s in speakers:
        evidence = s.quoted_evidence.strip()
        if not evidence:
            logger.warning(
                "Speaker has empty quoted_evidence (canonical_name=%r); dropping entry.",
                s.canonical_name,
            )
            continue
        if _normalize_whitespace(evidence) not in normalized_window:
            logger.warning(
                "Speaker quoted_evidence not found in window text "
                "(canonical_name=%r, evidence=%r); dropping entry.",
                s.canonical_name,
                evidence[:120],
            )
            continue
        kept.append(s)
    return kept


def dedupe_speakers_by_glossary_entry(
    speakers: list[SpeakerInWindow],
) -> list[SpeakerInWindow]:
    """Keep at most one entry per ``glossary_entry_id``.

    The model often cites multiple quoted lines for the same character
    in one window; the DB allows only one ``window_speakers`` row per
    (book, window, character). Keep the first validated entry (model
    order — typically the strongest attribution) and drop the rest.
    """
    seen: set[str] = set()
    kept: list[SpeakerInWindow] = []
    for s in speakers:
        gid = s.glossary_entry_id
        if gid in seen:
            logger.warning(
                "Speaker duplicate in window output (canonical_name=%r, "
                "glossary_entry_id=%s); keeping first evidence, dropping %r",
                s.canonical_name,
                gid,
                s.quoted_evidence[:120],
            )
            continue
        seen.add(gid)
        kept.append(s)
    return kept


def filter_speakers(
    speakers: list[SpeakerInWindow],
    *,
    glossary_name_by_id: dict[str, str],
    window_text: str,
) -> list[SpeakerInWindow]:
    """Apply cross-checks, then dedupe by glossary entry. Returns the kept list."""
    validated = filter_evidence_mismatches(
        filter_id_mismatches(speakers, glossary_name_by_id=glossary_name_by_id),
        window_text=window_text,
    )
    return dedupe_speakers_by_glossary_entry(validated)
