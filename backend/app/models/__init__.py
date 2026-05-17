"""ORM models. Importing this package registers all models on the
declarative base, which is what Alembic introspects during autogenerate.
"""

from app.models.book import Book, Chapter, Paragraph
from app.models.glossary import (
    FinalGlossary,
    FinalGlossaryEntry,
    GlossaryEntry,
    GlossaryExtractionRun,
    GlossaryNotepad,
    GlossaryWindowGeneration,
)
from app.models.speakers import SpeakerNotepad, WindowSpeaker
from app.models.voice import CharacterVoice, VoiceNotepad

__all__ = [
    "Book",
    "Chapter",
    "CharacterVoice",
    "FinalGlossary",
    "FinalGlossaryEntry",
    "GlossaryEntry",
    "GlossaryExtractionRun",
    "GlossaryNotepad",
    "GlossaryWindowGeneration",
    "Paragraph",
    "SpeakerNotepad",
    "VoiceNotepad",
    "WindowSpeaker",
]
