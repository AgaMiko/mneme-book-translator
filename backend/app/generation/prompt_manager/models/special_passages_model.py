"""Schemas for special passages (Step 6).

Paired with ``../prompts/special_passages_prompt.py``. Four calls:

- ``ChapterScan`` — one per chapter, before translation: runs of
  paragraphs that might follow a rule (verse, a document that could hide
  a message, wordplay the plot depends on).
- ``PassageRule`` — one per candidate, with the passage's first-letter
  strings computed by code: is there a rule, what is it, and which other
  paragraphs of the chapter quote or decode the passage.
- ``PassageVerdict`` — one per passage, after translation: does the
  English keep the rule.
- ``PassageRewrite`` — only when it does not: the passage translated
  again so that it keeps the rule, with patches for the paragraphs that
  quote or decode it.

Paragraph ids are the short ids of the prompt (``p1``, ``p2``…, ``t`` for
the chapter heading); the service maps them back.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CandidateKind = Literal["verse", "document", "wordplay"]
RuleKind = Literal["verse", "hidden_message", "wordplay", "none"]
RuleUnit = Literal["sentence", "line", "paragraph", "word", "marked_word", "other", "none"]


class PassageCandidate(BaseModel):
    first_paragraph: str = Field(description="Id of the passage's first paragraph (p12).")
    last_paragraph: str = Field(
        description="Id of its last paragraph. The same id for a one-paragraph passage."
    )
    kind: CandidateKind = Field(
        description=(
            "verse: a poem, song, rhyme, chant, prayer or spell in lines. "
            "document: a letter, note, inscription or other quoted text that could "
            "hide a message, or that the story treats as coded or strange. "
            "wordplay: a pun, anagram or play on a name that the plot or a later "
            "line depends on."
        )
    )
    evidence: str = Field(description="One sentence: what in the text makes this a candidate.")


class ChapterScan(BaseModel):
    candidates: list[PassageCandidate] = Field(
        default_factory=list, description="Empty when the chapter has none."
    )


class PassageRule(BaseModel):
    kind: RuleKind = Field(
        description=(
            "verse: lines with rhyme, metre or a fixed line count. "
            "hidden_message: letters or words of the passage spell something. "
            "wordplay: the passage only works through a double meaning, an anagram "
            "or the sound of a word. "
            "none: an ordinary text with no rule a translation could break."
        )
    )
    rule: str = Field(
        description=(
            "The rule in one or two plain sentences, written for the translator: "
            "what the translation must keep. Empty when kind is none."
        )
    )
    unit: RuleUnit = Field(
        description=(
            "Hidden messages only: which units carry the letters. sentence, line, "
            "paragraph, word or marked_word (italic or bold words) when the message "
            "is made of their first letters; other for any other rule; none for "
            "the other kinds."
        )
    )
    source_message: str = Field(
        description="Hidden messages only: what the source spells. Otherwise empty."
    )
    target_message: str = Field(
        description=(
            "Hidden messages only: the same message in the target language, as the "
            "translated passage should spell it. Otherwise empty."
        )
    )
    dependent_paragraphs: list[str] = Field(
        default_factory=list,
        description=(
            "Ids of paragraphs outside the passage that quote its words, explain "
            "its rule or state what it hides. Empty when there are none."
        ),
    )


class PassageVerdict(BaseModel):
    problems: list[str] = Field(
        default_factory=list,
        description=(
            "Each way the translation breaks the rule, one plain sentence each. "
            "Empty when it keeps the rule."
        ),
    )
    kept: bool = Field(description="True when the translation keeps the rule.")


class ParagraphText(BaseModel):
    paragraph_id: str = Field(description="The paragraph id from the input. Copy it exactly.")
    text: str = Field(description="The paragraph in the target language.")


class PassageRewrite(BaseModel):
    plan: str = Field(
        description=(
            "Write this first. For a hidden message: the target message letter by "
            "letter, and the unit that will start with each letter. For verse: the "
            "rhyme scheme and line count you will keep."
        )
    )
    paragraphs: list[ParagraphText] = Field(
        description="Every paragraph of the passage, same ids, same order."
    )
    dependent_paragraphs: list[ParagraphText] = Field(
        default_factory=list,
        description=(
            "Only the dependent paragraphs that must change to match the new "
            "passage, each in full. Empty when none must change."
        ),
    )
    target_message: str = Field(
        description="Hidden messages only: what the new passage spells. Otherwise empty."
    )
    notes: str = Field(
        description=(
            "One or two plain sentences for the author: what was changed to keep "
            "the rule (sentences merged or reordered, an image replaced)."
        )
    )
