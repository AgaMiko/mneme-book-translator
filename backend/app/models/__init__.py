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

__all__ = [
    "Book",
    "Chapter",
    "FinalGlossary",
    "FinalGlossaryEntry",
    "GlossaryEntry",
    "GlossaryExtractionRun",
    "GlossaryNotepad",
    "GlossaryWindowGeneration",
    "Paragraph",
]
