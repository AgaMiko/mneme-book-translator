"""Cross-checks for Pass 1 (speaker attribution).

Each ``LineAttribution`` names its speaker and addressee twice: a short
code (``C3``) and the canonical name, both copied from the prompt's
character list. A speaker whose code and name disagree is dropped (the
line keeps its kind, with no speaker), as are line numbers outside the
chunk and repeated entries for the same line.

Pure functions over the model output and the chunk's character list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from app.generation.prompt_manager.models.identify_speakers_model import (
        LineAttribution,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedLine:
    kind: str
    speaker_id: UUID | None
    addressee_id: UUID | None
    confidence: str
    mixed: bool


def _same_name(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def resolve_character(
    code: str | None,
    name: str | None,
    *,
    characters: dict[str, tuple[UUID, str]],
) -> UUID | None:
    """The glossary id for ``code`` when ``name`` matches it, else None.

    ``characters`` maps code to ``(glossary_entry_id, canonical_name)``.
    """
    if not code:
        return None
    found = characters.get(code.strip())
    if found is None:
        logger.warning("Speaker code %r not in the character list; dropping speaker.", code)
        return None
    gid, canonical = found
    if name is None or not _same_name(name, canonical):
        logger.warning(
            "Speaker code/name mismatch: %s is %r but model wrote %r; dropping speaker.",
            code,
            canonical,
            name,
        )
        return None
    return gid


def resolve_attributions(
    attributions: list[LineAttribution],
    *,
    line_count: int,
    characters: dict[str, tuple[UUID, str]],
) -> dict[int, ResolvedLine]:
    """Validated attributions by line number (1-based).

    Lines the model left out are missing from the result; the caller
    stores them as ``unknown``.
    """
    out: dict[int, ResolvedLine] = {}
    for a in attributions:
        if not 1 <= a.line <= line_count:
            logger.warning("Attribution for L%d outside 1..%d; dropping.", a.line, line_count)
            continue
        if a.line in out:
            logger.warning("Repeated attribution for L%d; keeping the first.", a.line)
            continue
        speaker = None
        addressee = None
        if a.kind != "not_dialogue":
            speaker = resolve_character(a.speaker_code, a.speaker_name, characters=characters)
            addressee = resolve_character(a.addressee_code, a.addressee_name, characters=characters)
            if addressee is not None and addressee == speaker:
                addressee = None
        out[a.line] = ResolvedLine(
            kind=a.kind,
            speaker_id=speaker,
            addressee_id=addressee,
            confidence=a.confidence,
            mixed=a.mixed,
        )
    return out
