"""LLM-backed generation layer for the translation pipeline.

Conventions:
- **providers/**: vendor-specific I/O (Gemini, etc.)
- **models/**: Pydantic schemas (structured outputs)
- **prompts/**: prompt templates
- **chains/**: orchestration that wires provider + prompt + schema + model
"""
from app.generation.chains.extract_metadata_chain import extract_manuscript_metadata
from app.generation.client import GenerationDisabledError
from app.generation.prompt_manager.models.extract_metadata_model import ManuscriptMetadata
from app.generation.chains.extract_glossary_chain import extract_glossary_window
from app.generation.prompt_manager.models.extract_glossary_model import (
    GlossaryEntryCompact,
    GlossaryUpdate,
    NewTerm,
    ExtendOperation,
    MergeOperation,
    RefineOperation,
    TranslationRecommendation,
)

from app.generation.chains.extract_voices_chain import extract_voices_window
from app.generation.prompt_manager.models.extract_voices_model import (
    CharacterVoiceCompact,
    ExtendVoiceProfile,
    GlossaryCharacterRef,
    NewVoiceProfile,
    ReplaceReferencePassage,
    VoiceNote,
    VoiceNoteCategory,
    VoiceUpdate,
)

__all__ = [
    "GenerationDisabledError",
    "ManuscriptMetadata",
    "extract_manuscript_metadata",
    "ExtendOperation",
    "GlossaryEntryCompact",
    "GlossaryUpdate",
    "MergeOperation",
    "NewTerm",
    "RefineOperation",
    "TranslationRecommendation",
    "extract_glossary_window",
    "CharacterVoiceCompact",
    "ExtendVoiceProfile",
    "GlossaryCharacterRef",
    "NewVoiceProfile",
    "ReplaceReferencePassage",
    "VoiceNote",
    "VoiceNoteCategory",
    "VoiceUpdate",
    "extract_voices_window",
]
