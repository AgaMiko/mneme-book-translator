"""Tests for targeted voice profile regeneration helpers."""

from app.generation.prompt_manager.models.extract_voices_model import (
    AddCandidate,
    CandidatePassage,
    ExtendVoiceProfile,
    NewVoiceProfile,
    ReplaceCandidate,
    VoiceUpdate,
)
from app.services.voice_service import filter_delta_for_profile


def test_filter_delta_for_profile_keeps_only_target_ops() -> None:
    delta = VoiceUpdate(
        window_summary="test window",
        new_profiles=[
            NewVoiceProfile(
                reasoning="a",
                glossary_entry_id="gid-a",
                canonical_name="Alice",
                source_voice_observation="obs",
                target_voice_strategy="strat",
            ),
            NewVoiceProfile(
                reasoning="b",
                glossary_entry_id="gid-b",
                canonical_name="Bob",
                source_voice_observation="obs",
                target_voice_strategy="strat",
            ),
        ],
        extensions=[
            ExtendVoiceProfile(
                profile_id="pid-a",
                canonical_name="Alice",
                new_source_voice_observation="new",
                reasoning="r",
            ),
            ExtendVoiceProfile(
                profile_id="pid-b",
                canonical_name="Bob",
                new_source_voice_observation="new",
                reasoning="r",
            ),
        ],
        candidate_additions=[
            AddCandidate(
                profile_id="pid-a",
                canonical_name="Alice",
                candidate=CandidatePassage(
                    source_text="hi",
                    why_representative="shows tone",
                ),
                reasoning="r",
            ),
        ],
        candidate_replacements=[
            ReplaceCandidate(
                profile_id="pid-b",
                canonical_name="Bob",
                remove_candidate_reason="old",
                new_candidate=CandidatePassage(
                    source_text="hey",
                    why_representative="better",
                ),
                reasoning="r",
            ),
        ],
    )

    scoped = filter_delta_for_profile(
        delta,
        profile_id="pid-a",
        glossary_entry_id="gid-a",
    )

    assert len(scoped.new_profiles) == 1
    assert scoped.new_profiles[0].canonical_name == "Alice"
    assert len(scoped.extensions) == 1
    assert scoped.extensions[0].profile_id == "pid-a"
    assert len(scoped.candidate_additions) == 1
    assert scoped.candidate_additions[0].profile_id == "pid-a"
    assert scoped.candidate_replacements == []
