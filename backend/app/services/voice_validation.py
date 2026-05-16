"""Cross-check helper: drop voice operations whose declared canonical_name
doesn't match the entry their ID resolves to.

Background
----------
Every operation in a ``VoiceUpdate`` carries TWO references to its
target character: a UUID-style ``glossary_entry_id`` (or ``profile_id``)
and a human-readable ``canonical_name``. The model has to copy both
from the prompt. If it pastes the wrong ID — picking up a neighbor's
UUID while still writing the intended canonical_name — the two will
disagree.

These helpers are pure functions over already-loaded glossary
characters and existing voice profiles. They return only the
operations that pass the cross-check; mismatched ones are filtered out
and logged. Drop them into ``apply_delta`` before the persistence step.

Why filter, not raise
---------------------
A single bad operation in a window of 5-10 should not crash the entire
window's persistence. Filter the bad ones, persist the good ones,
log the rejections so they're visible in operations dashboards. The
model gets another chance on a later window.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.generation.prompt_manager.models.extract_voices_model import (
        AddCandidate,
        ExtendVoiceProfile,
        NewVoiceProfile,
        ReplaceCandidate,
    )

logger = logging.getLogger(__name__)


def filter_new_profiles(
    ops: list[NewVoiceProfile],
    *,
    glossary_name_by_id: dict[str, str],
) -> list[NewVoiceProfile]:
    """Keep only NewVoiceProfile ops where canonical_name matches the
    name on the glossary entry the ID points to.

    ``glossary_name_by_id`` is built once per call to apply_delta from
    the loaded glossary character list:
        {str(c.glossary_entry_id): c.canonical_name for c in characters}
    """
    kept: list[NewVoiceProfile] = []
    for op in ops:
        expected = glossary_name_by_id.get(op.glossary_entry_id)
        if expected is None:
            logger.warning(
                "Voice op references unknown glossary_entry_id %s "
                "(claimed name=%r); dropping operation.",
                op.glossary_entry_id,
                op.canonical_name,
            )
            continue
        if op.canonical_name.strip() != expected.strip():
            logger.warning(
                "Voice op name/ID mismatch: glossary_entry_id=%s resolves to %r "
                "but model wrote canonical_name=%r; dropping operation.",
                op.glossary_entry_id,
                expected,
                op.canonical_name,
            )
            continue
        kept.append(op)
    return kept


def filter_extend_ops(
    ops: list[ExtendVoiceProfile],
    *,
    profile_name_by_id: dict[str, str],
) -> list[ExtendVoiceProfile]:
    """Keep only ExtendVoiceProfile ops whose canonical_name matches
    the name on the existing profile their profile_id points to."""
    kept: list[ExtendVoiceProfile] = []
    for op in ops:
        expected = profile_name_by_id.get(op.profile_id)
        if expected is None:
            logger.warning(
                "Voice extend op references unknown profile_id %s "
                "(claimed name=%r); dropping operation.",
                op.profile_id,
                op.canonical_name,
            )
            continue
        if op.canonical_name.strip() != expected.strip():
            logger.warning(
                "Voice extend op name/ID mismatch: profile_id=%s resolves to %r "
                "but model wrote canonical_name=%r; dropping operation.",
                op.profile_id,
                expected,
                op.canonical_name,
            )
            continue
        kept.append(op)
    return kept


def filter_candidate_replacements(
    ops: list[ReplaceCandidate],
    *,
    profile_name_by_id: dict[str, str],
) -> list[ReplaceCandidate]:
    """Keep only ReplaceCandidate ops whose canonical_name matches
    the existing profile their profile_id points to."""
    kept: list[ReplaceCandidate] = []
    for op in ops:
        expected = profile_name_by_id.get(op.profile_id)
        if expected is None:
            logger.warning(
                "Voice candidate-replace op references unknown profile_id %s "
                "(claimed name=%r); dropping operation.",
                op.profile_id,
                op.canonical_name,
            )
            continue
        if op.canonical_name.strip() != expected.strip():
            logger.warning(
                "Voice candidate-replace op name/ID mismatch: profile_id=%s "
                "resolves to %r but model wrote canonical_name=%r; "
                "dropping operation.",
                op.profile_id,
                expected,
                op.canonical_name,
            )
            continue
        kept.append(op)
    return kept


def filter_add_candidate_ops(
    ops: list[AddCandidate],
    *,
    profile_name_by_id: dict[str, str],
) -> list[AddCandidate]:
    """Keep only AddCandidate ops whose canonical_name matches
    the existing profile their profile_id points to."""
    kept: list[AddCandidate] = []
    for op in ops:
        expected = profile_name_by_id.get(op.profile_id)
        if expected is None:
            logger.warning(
                "Voice add-candidate op references unknown profile_id %s "
                "(claimed name=%r); dropping operation.",
                op.profile_id,
                op.canonical_name,
            )
            continue
        if op.canonical_name.strip() != expected.strip():
            logger.warning(
                "Voice add-candidate op name/ID mismatch: profile_id=%s "
                "resolves to %r but model wrote canonical_name=%r; "
                "dropping operation.",
                op.profile_id,
                expected,
                op.canonical_name,
            )
            continue
        kept.append(op)
    return kept


# ─── Integration sketch ────────────────────────────────────────────
#
# Inside apply_delta(), after loading current glossary characters and
# current voice profiles, build the lookup dicts once and run the
# filters before persistence:
#
#     glossary_name_by_id = {
#         str(c.glossary_entry_id): c.canonical_name
#         for c in await load_glossary_characters(session, book_id=book_id)
#     }
#     profile_name_by_id = {
#         str(p.id): p.canonical_name
#         for p in await load_compact_voice_profiles(session, book_id=book_id)
#     }
#
#     new_profiles = filter_new_profiles(
#         delta.new_profiles,
#         glossary_name_by_id=glossary_name_by_id,
#     )
#     extensions = filter_extend_ops(
#         delta.extensions,
#         profile_name_by_id=profile_name_by_id,
#     )
#     candidate_replacements = filter_candidate_replacements(
#         delta.candidate_replacements,
#         profile_name_by_id=profile_name_by_id,
#     )
#
#     # ... continue with the existing apply_delta order, using
#     # the filtered lists rather than delta.new_profiles directly.
