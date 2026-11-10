"""API contracts for special passages and their flags (Step 6)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID  # noqa: TC003 - pydantic needs it at runtime

from pydantic import BaseModel, Field

PassageKind = Literal["verse", "hidden_message", "wordplay"]
PassageStatus = Literal["unchecked", "passed", "corrected", "failed", "author", "dismissed"]


class PassagesStateOut(BaseModel):
    status: Literal["idle", "scanning", "checking", "completed", "failed"]
    done: int
    total: int
    error: str | None
    # A scan has finished at least once.
    scanned: bool


class PassageParagraphOut(BaseModel):
    paragraph_id: str
    source: str
    # Current English; None while the paragraph is not translated.
    text: str | None
    # English before the first correction; None when nothing was changed.
    first_text: str | None


class ParagraphTextIn(BaseModel):
    paragraph_id: str
    text: str


class PassageCandidateOut(BaseModel):
    paragraphs: list[ParagraphTextIn]
    target_message: str | None = None
    notes: str = ""
    # Why this version failed the check; empty when it passed.
    problems: list[str] = Field(default_factory=list)


class PassageFlagOut(BaseModel):
    id: str
    severity: Literal["blocking", "review", "fyi"]
    status: Literal["open", "accepted", "changed", "dismissed"]
    question: str


class PassageOut(BaseModel):
    id: str
    chapter_id: str
    chapter_label: str
    kind: PassageKind
    rule: str
    unit: str | None
    source_message: str | None
    target_message: str | None
    evidence: str
    origin: Literal["detected", "author"]
    status: PassageStatus
    problems: list[str]
    translated: bool
    # The English changed since the last check (for example a re-translation).
    stale: bool
    paragraphs: list[PassageParagraphOut]
    dependent_paragraphs: list[PassageParagraphOut]
    candidates: list[PassageCandidateOut]
    flag: PassageFlagOut | None


class PassagesViewResponse(BaseModel):
    state: PassagesStateOut
    passages: list[PassageOut]
    open_flags: int
    blocking_flags: int


class CreatePassageIn(BaseModel):
    first_paragraph_id: UUID
    last_paragraph_id: UUID
    kind: PassageKind
    # Optional: what the translation must keep. Worked out at the first check when empty.
    rule: str = ""


class UpdatePassageIn(BaseModel):
    rule: str | None = None
    target_message: str | None = None


class ResolvePassageIn(BaseModel):
    action: Literal["accept", "restore", "use_candidate", "edit", "dismiss"]
    # use_candidate: index into the passage's candidates.
    candidate: int | None = None
    # edit: the new English of the paragraphs that change.
    paragraphs: list[ParagraphTextIn] = Field(default_factory=list)
