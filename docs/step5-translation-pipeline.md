# Step 5 & Step 6 — fragment translation and author flag review

Status: design written 2026-10-20. Built 2026-10-21: fragments, the translate chain (one-, two- and three-step modes), style metrics, rhythm and repetition checks, translator notes, polish declared edits, a cost estimate, the Translation tab, and PDF/EPUB/DOCX export (sections 2, 3, 4, 11 and part of 8). Not built yet: style sheet entity, glossary propagation and placeholder tokens, epithet claims, the flags table and Step 6 review actions, special passages.

**Change to section 3 after testing:** the default is now one step: Sol translates straight into the final text. See "Model and pipeline tests" at the end.

This doc turns the manual translation of *Zaplataczka* (→ *The Weaveress*, ~102k Polish words, 2026-10-19) into an app pipeline. The manual run used parallel agents with a shared glossary and brief, then a line-edit pass and a polish pass. Its working files are in `translations/zaplataczka/` (untracked, in the main checkout): `BRIEF.md`, `POLISH_BRIEF.md`, `glossary.md`, `terms/batch_*.md`, `AUTHOR_QUERIES.md`, `style_metrics.py`, `build_pdf.py`, plus `pass1/`, `v2_lineedit/`, `en/` and `out/`. Every design choice below points back either to code that exists today or to something that went wrong, or worked, in that run.

Contents

1. What exists today, and what Step 5 needs from it
2. Fragments and runs
3. The three-stage translate chain (faithful → line-edit → polish)
4. Changes to the shared translation rules (`translate_passage_prompt.py`)
5. Book style sheet
6. Glossary change propagation and placeholder tokens
7. Nicknames and epithets discovered during translation (claims)
8. Deterministic QA checks
9. Author flags (Step 6)
10. Special passages: acrostics, ciphers, puns, verse
11. Export (PDF / EPUB)
12. Schema summary and migrations
13. Build order
14. Open questions

---

## 1. What exists today, and what Step 5 needs from it

| Piece | Today | Step 5 needs |
|---|---|---|
| `Book → Chapter → Paragraph` (`models/book.py`) | Paragraphs hold source text and docx `style`; scene breaks are split into their own paragraphs by `manuscript_parser._split_scene_break_paragraphs`. | A **fragment** layer over paragraphs. Paragraph ids become the alignment key for every translated rendition. |
| Glossary (`models/glossary.py`) | Working `GlossaryEntry` per extraction run (`proposed/accepted/adjusted/rejected`); immutable `FinalGlossary` + `FinalGlossaryEntry`; `Book.active_final_glossary_id`. | **`publish_final_glossary` is still `NotImplementedError`** (`services/glossary_service.py:1048`). It has to be built first. Final glossaries also need versioning and a diff (§6), and entries need a few new columns (§6, §7). |
| Translation strategy | The extraction model stores `translation.suggestion ∈ {keep_original, translate}`. `translate_passage_model.TranslationStrategy` expects the 4-way `keep_original / translate_literally / adapt / transliterate` that the manual glossary used. | Store a 4-way `strategy` on `FinalGlossaryEntry` (set at publish time, author-editable). Fragment prompts read that, not `suggestion`. |
| Voices (`models/voice.py`) | `CharacterVoice.source_voice_observation` / `target_voice_strategy`, accepted per profile. | Used as is. The fragment prompt includes only the profiles of characters who speak in the fragment's windows (from `WindowSpeaker`), not all of them. |
| Speaker windows (`models/speakers.py`) | `WindowSpeaker(window_number, glossary_entry_id, quoted_evidence)` over 1,000-word windows with 200-word overlap (`constants/glossary_extraction.py`). | Map each fragment to the windows it overlaps (by word offset) to pick voice profiles. |
| `translate_passage_chain` | Translates one *calibration* passage of one character's dialogue, with the full accepted glossary. | Stays for calibration. Its rule text moves into a shared module that the new fragment prompts reuse (§4), so the two stay identical. |
| Provider | `providers/gemini.generate(prompt, schema, model, temperature, max_output_tokens)` with retry/backoff and Langfuse spans. `TRANSLATION_MODEL` is read via `getattr` with fallback to `GEMINI_MODEL`. | Three model settings, one per stage (§3). Langfuse `session_id=book_id`, as now. |
| Long jobs | Glossary, speakers and voice jobs each keep `*_status`, `*_cancel_requested`, `*_windows_total/completed` on `Book` and poll from the reader. | Translation keeps the same polling contract, but on a `translation_runs` row rather than more `Book` columns (`Book` already has 15 status columns). |

## 2. Fragments and runs

### Fragments

A **fragment** is the unit of LLM work: a contiguous run of paragraphs within one chapter.

- Target size 900–1,500 source words. Never cross a chapter boundary. Prefer to cut at a scene break (`### ***` paragraphs), then at a paragraph that ends a dialogue exchange. Never cut inside a special passage (§10).
- The manual run worked in chapter batches (3–5 chapters per agent, roughly 10k words each). It suited the agents' context window and was not chosen for quality. Smaller fragments isolate failures, give tighter QA, and make patching cheap. The polish metrics, which are noisy over 1,000 words, are aggregated per chapter (§8).
- Fragments are computed once per book (deterministically, from paragraph word counts) and are stable across runs. If the source is edited (e.g. the author fixes a typo raised in Step 6), only the affected fragment is invalidated.

### Paragraph alignment is the invariant

Every stage returns `paragraphs: [{paragraph_id, text}]` with exactly the input ids, in order. The service rejects any other output and retries once. This rule makes the following possible:

- side-by-side review in Step 6, with flags anchored to a paragraph;
- term sweeps scoped to "paragraphs whose *source* contains the term". This is what avoids the "Red tape" / "Red uniforms" false positives that a book-wide grep for the old *Ruda → Red* variant produced (§8);
- targeted propagation patches (§6) that touch three paragraphs instead of re-running a chapter;
- dropped-content detection by length ratio.

Merging two source paragraphs into one English paragraph is allowed only by leaving the second `text` empty and setting `merged_into_previous: true`. Splitting is done with `\n\n` inside one `text`. Both stay aligned.

### Runs

A **translation run** pins its inputs: `final_glossary_id`, `style_sheet_version`, and the voice profile set. Stage outputs are stored as **renditions** (one row per fragment per stage, with a parent link), so the faithful pass, the line-edit and the polish are all kept, just like the `pass1/`, `v2_lineedit/` and `en/` folders. The manual run needed those to check whether a polish edit changed meaning (e.g. Ch 30 "The wave was rising" became "The anger was rising").

## 3. The three-stage translate chain

```
            ┌──────────── per fragment ───────────────────────────────────────┐
source  ──► │ faithful ──► QA(hard) ──► line_edit ──► QA(hard) ──► polish ──► QA(all) │ ──► rendition (current)
            └──────┬──────────────────────┬──────────────────────┬───────────┘
                   │ term proposals,      │ added_clarification  │ meaning-risk
                   │ flags                │ flags                │ edits → flags
                   ▼                      ▼                      ▼
              term claims (§7)      translation_flags (§9)
```

All three stages share one context block, built once per fragment:

- **Style sheet** block (§5).
- **Glossary** block: the pinned final glossary, plus provisional claimed terms (§7), plus placeholder-token instructions for undecided terms (§6). Each row carries `term_source | variants | term_target | strategy | sense_notes`. `sense_notes` is new and holds the disambiguation the manual run kept having to rediscover, e.g. "*zaplatać* → weave; a literal hair braid (*warkocz*) stays 'braid'".
- **Voice profiles** for the characters present in the fragment's speaker windows, as in the calibration prompt, with the scene-level voice notes the translators logged ("Batosz → broken English, do not correct", "Opus → light rural dialect, no thee/thou").
- **Continuity context**: the source of the last ~250 words of the previous fragment, plus its current English if it exists (it may not yet, because fragments run in parallel; see §7 on ordering), and the first ~150 source words of the next fragment. This is read-only context, labelled "do not translate".

### Stage 1: faithful pass

Purpose: the `pass1/` file. Every sentence is accounted for; nothing is added or dropped. All mechanical style-sheet rules are applied here (quotes, nominative names, units, mind-speech format, scene-break/POV labels), so that later stages only have to deal with prose. The manual run had to convert units in pass 1 retroactively.

```python
# prompt_manager/models/translate_fragment_model.py

class ParagraphOut(BaseModel):
    paragraph_id: str                  # copied verbatim; service checks the order and the set
    text: str                          # may contain ⟦term:…⟧ tokens (§6) and author placeholders verbatim
    merged_into_previous: bool = False

class TermProposal(BaseModel):         # §7
    source_lemma: str                  # nominative / dictionary form: "Ruda", "dzikuska"
    surface_forms: list[str]           # as seen: "Rudej", "Rudo", "dzikusko"
    target: str                        # "Ginger", "wildcat"
    term_type: TermType                # incl. new "epithet"
    referent: str | None               # canonical name of who it denotes: "Mira"
    used_by: list[str] = []            # who says it: ["Stein"]
    strategy: TranslationStrategy
    reasoning: str

class FlagProposal(BaseModel):         # §9
    paragraph_id: str
    flag_type: FlagType
    source_excerpt: str
    target_excerpt: str | None
    question: str                      # what the author must decide, in one or two sentences
    rendered_as: str | None            # what we did in the meantime
    options: list[str] = []

class FaithfulFragment(BaseModel):
    fragment_id: str
    paragraphs: list[ParagraphOut]
    scene_povs: list[ScenePov]         # {paragraph_id of the scene start, pov: canonical name | None, labelled_in_source: bool}
    term_proposals: list[TermProposal]
    flags: list[FlagProposal]
    silent_fixes: list[SilentFix]      # {paragraph_id, source_wrong: "Kkilka", read_as: "Kilka"} → flag source_typo, severity fyi
```

```python
# generation/chains/translate_fragment_chain.py

@observe(name="translate_fragment_faithful", as_type="generation")
async def translate_fragment_faithful(
    *,
    fragment_id: str,
    source_paragraphs: list[ParagraphIn],      # {paragraph_id, text, style}
    context: FragmentContext,                  # style sheet, glossary rows, voices, neighbours
    source_language: str,
    target_language: str,
    settings: Settings,
) -> FaithfulFragment: ...
```

Model `TRANSLATION_FAITHFUL_MODEL`, temperature 0.3 (as now), max output 16k tokens (a 1,500-word fragment is about 3k output tokens plus metadata).

### Stage 2: line-edit pass

Purpose: the `v2_lineedit/` file. It turns the faithful English into published-novel English (BRIEF.md "Line-edit pass"): vary sentence openings, merge or split sentences for English rhythm, cut Polish *i/więc* clause-chaining, fix stiff literal phrasing, keep ellipses only for hesitation or fear, vary dialogue tags, and make the speaker clear when two same-gender characters talk.

Input: the source paragraphs plus the faithful paragraphs. The model sees both, because an editor who reads only the English can lose what the source meant. Clarifying beats such as an added "Stein said" are allowed, **but each one must be returned as an `added_clarification` flag**. In the manual run these were mentioned only in prose notes (Ch 17 "added 'Stein' once", Ch 21 "added 'Stein said'", Ch 11 the "As if a girl were speaking through him" beat).

```python
class LineEditedFragment(BaseModel):
    fragment_id: str
    paragraphs: list[ParagraphOut]
    flags: list[FlagProposal]          # added_clarification, ambiguity (speaker attribution), …
    notes: str                         # one or two clauses, for traceability

async def line_edit_fragment(
    *, fragment_id: str, source_paragraphs: list[ParagraphIn],
    faithful: list[ParagraphOut], context: FragmentContext,
    source_language: str, target_language: str, settings: Settings,
) -> LineEditedFragment: ...
```

Model `TRANSLATION_LINE_EDIT_MODEL` (the strongest available), temperature 0.5.

### Stage 3: polish pass

Purpose: the `en/` file (POLISH_BRIEF.md). It works against **measured** targets: the deterministic metrics (§8) for the line-edited fragment *and for its whole chapter so far* are computed first and put in the prompt ("this chapter: She/He openers 23% → target ≤ 15%; ellipses 5.1/1k → ≤ 3; stock phrases: 'a wave of' ×2").

Hard "do not" list, carried over verbatim from POLISH_BRIEF: no added events, images, jokes or lines; no cuts; no glossary changes; no flattening of voices; don't touch epigraphs, quoted documents, letters, special passages (§10) or placeholders.

The polish pass in the manual run made three kinds of edit that need checks:

1. **Meaning change**: "The wave was rising" → "The anger was rising" (Ch 30).
2. **Metric rules overriding a voice device**: Lumen's signed speech "*You… me… weaving… why?*" became "*You. Me. Weaving. Why?*", and Ein's trailing "*Ein… Ein…*" lost its pause. The ellipsis budget beat a deliberate device.
3. **Continuity fixes**: "He got up" → "Rising, he turned his back on her", because he had already stood up a few lines earlier. That one was welcome, but it is an edit the author should see.

So the polish output has to declare any edit that goes beyond style:

```python
class PolishEdit(BaseModel):
    paragraph_id: str
    before: str
    after: str
    kind: Literal["meaning_risk", "voice_device", "continuity"]
    why: str

class PolishedFragment(BaseModel):
    fragment_id: str
    paragraphs: list[ParagraphOut]
    declared_edits: list[PolishEdit]   # each becomes a review-severity flag
    unsure_lines: list[FlagProposal]   # "lines you weren't sure how to fix without changing meaning"

async def polish_fragment(
    *, fragment_id: str, source_paragraphs: list[ParagraphIn],
    line_edited: list[ParagraphOut], metrics: StyleMetricsReport,
    chapter_metrics: StyleMetricsReport, context: FragmentContext, settings: Settings,
) -> PolishedFragment: ...
```

There is also a deterministic **edit-size check**: any paragraph whose normalized edit ratio between line-edit and polish is above 0.45, *and* which has no declared edit, gets an automatic `continuity`-type review flag ("large undeclared polish edit"). To protect voice devices, voice profiles and the style sheet can list **protected patterns** (e.g. Lumen's signed speech uses "…" between words) that the metric counters skip, so the metric targets don't push the model to remove them.

Model `TRANSLATION_POLISH_MODEL`, temperature 0.4.

### Retry and failure

- Schema or alignment failure: retry once with the validation error appended, then mark the fragment `failed`. Never block the run.
- Hard QA failure (§8: leftover diacritics, case endings, missing author placeholder, banned term variant): re-run *the same stage* once with the failures listed. If it still fails, accept the output and raise a `qa_check` flag.
- Soft QA miss (metrics over target): no retry. It is reported in the chapter metrics and the Step 6 dashboard.

### Cost

About 100 fragments × 3 stages ≈ 300 calls for a 100k-word book, plus about 5–10% retries and the patch calls from §6. Add `services/translation_estimate.py` on the pattern of `glossary_extraction_estimate.py` / `voice_extraction_estimate.py`, and show the estimate before the run starts.

## 4. Changes to the shared translation rules

Move the rule text out of `translate_passage_prompt.py` into `prompt_manager/prompts/_translation_rules.py` (`RULES_CORE`, `RULES_FRAGMENT`). The calibration prompt and the three fragment prompts all include `RULES_CORE`. The changes, each traced to the manual run:

1. **Make the voice exception to rule 3 (Anglo-Saxon over Latinate) explicit.** Today rule 3 is unconditional, and the strategy takes priority only through a general line ("If observation and strategy seem to conflict… follow the strategy"). BRIEF.md had to restate the exception in bold, and the Elantria profile says "MIRROR the Latinate/clinical register — a deliberate exception… don't smooth her pomposity". New text: *"Rules 1–4 govern narration and characters whose strategy does not name a register. When `target_voice_strategy` names a Latinate, clinical, elevated, archaic or broken register, that register wins over rule 3 and rule 4 for that character's lines and for free indirect thought in their POV. Example: Elantria's 'fabricates images', 'haemorrhage' stay Latinate; Batosz's non-native grammar stays broken."*
2. **Inflected names → nominative.** Polish vocative, genitive and locative forms appeared in the English ("Miro", "Einardzie", "Steina"). New rule: *"Render every name in the nominative of its glossary form. Possession uses English 's. Diminutives the glossary lists (Jen, Ein) are separate names and stay as they are. Never carry a Polish case ending into English."* The prompt also gets each character's known surface forms from `variants` ("Miro, Mirze, Mirą → Mira"), and §8 checks it.
3. **Punctuation and openers.** *"Polish dialogue dashes (– ) become English double-quoted speech. Em dashes only for interruptions and sharp asides. Ellipses: keep in dialogue where a speaker trails off or falters, and at real moments of dread; in narration, prefer a full stop, comma or restructure. Do not open consecutive narration sentences with the same pronoun ('She… She… She…')."* In the faithful pass this is guidance only. The numeric targets belong to the polish prompt.
4. **"Nothing inserted" gains one audited exception.** A minimal clarifying beat (a speaker name, or a gender cue English grammar can't carry) is allowed only in line-edit and must be returned as an `added_clarification` flag.
5. **Author placeholders and silent fixes.** *"Copy author placeholders (`xxxxxxx`, `[xxxx]`, any pattern in the style sheet) verbatim. Translate obvious source typos as intended, and list each in `silent_fixes`."* The manual run fixed about 60 typos silently and logged them by hand.
6. **Free indirect thought** stays in past tense, and only direct thought is italic (from BRIEF.md and POLISH_BRIEF.md).
7. **Glossary sense notes.** *"A term's `sense_notes` say when the everyday word is NOT the glossary term."* (Hair braid vs Dust weave; "a vessel" vs "the Vessel".)
8. The calibration prompt's opening ("a single passage of … dialogue… a calibration sample") stays in the calibration file only.

## 5. Book style sheet

In the manual run these decisions were spread across BRIEF.md "Format", glossary.md "Style decisions", the "Cross-batch decisions" table and the coordinator's messages. Some were sent to batches late (units, Drylands). They become one versioned entity per book, rendered into every prompt and read by QA and export.

```python
class StyleSheet(BaseModel):
    spelling_variant: Literal["en-GB", "en-US"]            # "en-GB"
    quote_style: Literal["double", "single"]               # "double"; smart quotes applied at export
    source_dialogue_convention: Literal["dash", "quotes", "guillemets"]  # pl: "dash"
    units_policy: UnitsPolicy
        # narration: "traditional" (paces/feet/miles/pounds) | "metric" | "as_source"
        # documents: "as_source"  (°C kept on medical charts)
        # examples: ["Cztery metry długości! → A good five paces long!"]
        # avoid_spurious_precision: true   (POLISH_BRIEF: "ninety pounds… two feet by a foot and a half" → simplify)
    mind_speech_format: str     # "POV speaker's words in double quotes; the other speaker's in italics"
    thought_format: Literal["italic_direct_only", "italic_all", "roman"]
    scene_break_marker: str     # "### ***"
    pov_label_policy: PovLabelPolicy
        # labelled break: "### *** Kerry" → "### ***" + line "*Kerry*"
        # unlabelled POV switch: "keep" | "add" | "flag"   (manual run: kept + flagged Ch14, Ch28)
    chapter_heading_template: str   # "# *{pov}*\n\n## Chapter {n}\n\n{epigraph}\n\n---"
    epigraph_format: str
    name_policy: str                # "nominative; diminutives kept; Orfeusz not Orpheus"
    anachronism_policy: str         # "no modern idiom in narration ('light years' → 'a world away')"
    placeholder_patterns: list[str] # [r"x{4,}", r"\[x+\]"]
    metric_targets: MetricTargets   # she_he_max_pct=15, ellipses_per_1k=3, dashes_per_1k=6, stock_phrases=0
    stock_phrases: list[str]        # seeded from style_metrics.STOCK
    protected_patterns: list[ProtectedPattern]  # §3: {pattern, applies_to: character|chapter, reason}
    extra_rules: str                # free text for the author
```

- Table `book_style_sheets(id, book_id, version, body JSONB, created_at, created_by)`, unique on `(book_id, version)`, plus `books.active_style_sheet_version`. Every rendition records the version it was made with, so a change can mark renditions stale (§6).
- Defaults come from the language pair (`source_language` already drives chapter-marker detection in `manuscript_parser`). PL→EN defaults are exactly the *Weaveress* choices.
- `render_style_sheet_block(sheet) -> str` sits next to `render_glossary_block`, and every stage prompt includes it.
- UI: a form under book settings, edited before the run. Changing it mid-run creates a new version and shows "N fragments made with v1".

## 6. Glossary change propagation and placeholder tokens

### What happened

- *Zaplatacz* was **Braider** when the batches started and became **Weaver** while they were running (accepted 2026-10-19). Batches that had finished were re-edited by hand. glossary.md still says "the **Braider** boy" in the *Cień* row, which was simply missed.
- *Ziemie Niczyje* was "Unclaimed Lands" in glossary.md and "the Drylands" in the coordinator's final message. Batch 4 noticed the conflict and flagged it. Batch 8 applied the Drylands.
- The weave/braid collision: Jenna "wove the flower into her braid" had to become "worked it into her fair braid" so it wouldn't read as Dust-weaving. A blind find-and-replace of `braid→weave` would have broken literal braids.

### Versioned final glossary plus a diff

- `final_glossaries` gains `version int` and `supersedes_id`. An author edit to a published term creates a **new** `FinalGlossary` (the existing snapshot stays immutable, as `models/glossary.py` intends) and moves `books.active_final_glossary_id`.
- New table `glossary_change_events(id, book_id, from_glossary_id, to_glossary_id, canonical_form, kind ∈ {changed, added, decided, removed}, old_target, new_target, old_strategy, new_strategy, propagation_status, created_at)`. One row per changed term.
- `FinalGlossaryEntry` gains `rejected_targets text[]`. Every old target goes into it automatically (Braider, Unclaimed Lands, Red), which feeds the variant sweep in §8.

### Knowing where a term is used

`fragment_term_occurrences(fragment_id, paragraph_id, canonical_form, source_hits int, target_form text, rendition_id)` is written by the deterministic matcher after each stage. It holds source hits (lemma or variants, as `_count_term_hits` does for extraction today) and the target form found in the same paragraph. A term change then becomes one query: which current renditions, and which paragraphs, use it.

### Propagating

For each change event, for each affected paragraph of each current rendition:

1. **Deterministic patch**, only when it is safe: the old target is capitalised or multi-word, appears with a word boundary, and is not a common English word. Example: `Unclaimed Lands → Drylands`, with the article handled because the entry knows its `article` ("the"). This produces a `patch` rendition directly.
2. **LLM patch** otherwise (common-word targets, inflecting verbs, gender forms: Braider/Braiders/braiding/braided → Weaver/Weavers/weaving/wove; the female form Weaveress). A small chain gets just the source paragraph, the current English paragraph, the old→new mapping and the `sense_notes`, and returns the patched paragraph:

   ```python
   async def patch_term_in_paragraph(
       *, paragraph_id: str, source_text: str, current_text: str,
       change: TermChange,            # canonical_form, old_target, new_target, sense_notes, word_family
       settings: Settings,
   ) -> PatchedParagraph: ...       # {paragraph_id, text, changed: bool, skipped_senses: list[str]}
   ```

   `skipped_senses` records "left 'braid' at …: literal hair" for the audit trail.
3. Re-run §8 QA on the patched fragment. A metric regression does not trigger a re-polish automatically. It is listed instead.
4. **Re-render** (re-run line-edit and polish for the fragment, from the faithful output with the patch applied) only when the change alters grammar around the term: number, gender, article, or a change of strategy such as keep_original → adapt. The author can also choose re-render per change.

Patches apply to every stored stage of the fragment (faithful, line-edit, polish), so that a later re-render from an earlier stage doesn't bring the old term back.

### Placeholder tokens for undecided terms

The manual run translated with guesses (*Smoliste → Pitchwood*, *Mała Ruda* kept, *Płotka → Roach*) and listed them for the author. If the author picks something else, a guessed term becomes a propagation job. Some terms are known to be undecided before the run, and the author can mark them (new column `decision_state ∈ {decided, open}` on glossary entries). For those:

- Prompts tell the model to write `⟦term:<slug>|<provisional>⟧`, e.g. `⟦term:smoliste|Pitchwood⟧`, and to build the sentence around a noun phrase whose article and number come from the entry (`article`, `grammatical_number`, both new optional columns).
- Reviewers see the provisional text, rendered as a highlighted chip in the UI.
- When the author decides, a `decided` change event resolves every token by string replacement. This is exact, because the token carries the slug, so no LLM is needed.
- Export refuses (or watermarks "DRAFT") while any token remains (§8, §11).

Tokens are for *terms* only. The author's own placeholders in the source (`xxxxxxx` epigraph, `[xxxx]`) are copied verbatim and tracked as `placeholder` flags (§9).

## 7. Nicknames and epithets discovered during translation (claims)

### What happened

Recurring nicknames and pet names weren't in the glossary, because extraction looks for world-terms. So each batch invented its own. *Ruda* became "Ginger" in some batches and "Red" in others. *dzikuska* got "wildcat", with "wild thing" and "little savage" also suggested. *kwiatuszku* became "Petal". *Hania / Hanna / Hanka* was normalised in some batches and kept as in the source in others. All of these were reconciled in a merge pass ("Cross-batch decisions") and then re-applied by hand. Batch 9 still says "Ruda → Ginger vs 'Red' in other batches: this needs a glossary decision."

### Design

1. **Catch most of them before translation.** Add `epithet` to `TermType` (extraction model, `glossary_taxonomy.TERM_TYPE_LABELS`, and a normalisation for old rows). Extend the glossary extraction prompt: *"recurring nicknames, pet names, terms of address and epithets used for a specific character, including the speaker who uses them."* New optional columns on glossary entries: `referent_entry_id` (who it denotes, e.g. Mira) and `used_by_entry_ids` (who says it, e.g. Stein). Voice profiles can then mention "Stein calls Mira 'wildcat'".
2. **Claims during translation catch the rest.** When a faithful pass returns a `TermProposal`, the service tries to **claim** it:
   - The claim key is `(book_id, casefold(source_lemma))`. Storage reuses `glossary_entries`: a new row in the book's latest extraction run with `origin='translation'`, `status='proposed'`. The existing unique constraint `uq_glossary_run_canonical (extraction_run_id, canonical_form)` acts as the lock: `INSERT … ON CONFLICT DO NOTHING RETURNING id`.
   - **Won**: the term is now provisional, and every fragment *dispatched after this point* sees it in its glossary block, marked "provisional — use exactly".
   - **Lost**, with the same target: nothing to do. The proposal's surface forms are added to `variants`.
   - **Lost**, with a different target: the worker's fragment is patched to the winner's target with `patch_term_in_paragraph` before line-edit starts. The losing target goes into the entry's `alternative_targets`, so the author still sees "Red" was considered.
   - Normalisation is difficult for Polish (*Ruda / Rudej / Rudą / Rudo*). The model gives `source_lemma` in the nominative, and the service also matches incoming `surface_forms` against the `variants` of existing claims, so "Rudo" and "Ruda" collide even when the model gives an odd lemma.
3. **Ordering to limit divergence.** Fragments are dispatched in book order with bounded concurrency (setting `TRANSLATION_CONCURRENCY`, default 6). Prompts are built at dispatch, so the earliest occurrence of a nickname usually gets claimed before later fragments start. The lock handles the remaining races. (In the manual run all 9 batches started at the same time from the same glossary, so nothing could be shared.)
4. **Name-form normalisation is decided by the author.** Hania/Hanna/Hanka is a question about the source, so the translator should not choose. When proposals for one referent come in with different surface names, the service raises a `term_choice` flag ("one character, three forms: normalise?") instead of silently normalising.
5. **Review.** Provisional terms show in the Step 6 queue (§9) as `term_choice` flags grouped by term. Accepting one publishes a new glossary version. Changing it fires §6 propagation.

## 8. Deterministic QA checks

These are pure functions in `services/translation_qa.py`. They run after every stage on the fragment, and the chapter aggregates are recomputed after polish. Results are stored per rendition in `rendition_qa_results(rendition_id, check, passed bool, severity, details JSONB)`. Hard checks trigger the one retry from §3. Soft checks feed the dashboard.

| Check | Kind | How | From the manual run |
|---|---|---|---|
| **Alignment** | hard | Same paragraph ids, in order; no empty `text` unless `merged_into_previous`. | — |
| **Length ratio** | soft | Target/source word ratio per paragraph within a band calibrated per language pair (start PL→EN at 0.9–1.8, tune on the *Weaveress* corpus). Outside the band → possible omission or insertion. | Catches dropped lines the "nothing inserted / nothing dropped" rule otherwise relies on the model for. |
| **Leftover source diacritics** | hard | `[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]` (alphabet per source language) in target text, minus an allowlist built from `keep_original` targets and the author's name (Elżka, Mała Ruda, Mikołajczyk). | Untranslated words and names with Polish letters. |
| **Case endings on names** | hard | For each `character_name` / `epithet` entry: every source `variant` that differs from the target form must not appear in the target. Plus a generic pattern `\b{name}(a|y|ie|ę|ą|o|owi|em|u)\b` for known names, with an allowlist of real names that happen to match. | "Miro", "Einardzie", "Steina" appeared in the English. BRIEF had to say it twice. |
| **Author placeholders preserved** | hard | Every match of `placeholder_patterns` in the source appears verbatim in the target, the same number of times. Each one opens a blocking `placeholder` flag. | `xxxxxxx` (Ch 30 epigraph), `[xxxx]` (Ch 17). |
| **Term tokens resolved** | export-blocking | No `⟦term:…⟧` left. | §6. |
| **Term-variant sweep** | hard | For each paragraph whose **source** hits a glossary term: the accepted target is present (case-insensitive, with word family), and no `rejected_targets` / `alternative_targets` of that term are present. Scoping to the paragraph is what keeps "Red tape" and "Red uniforms" from matching *Ruda → Red*. | Braider/Weaver, Unclaimed Lands/Drylands, Ginger/Red, Dust-sight/Dustsight. |
| **Style metrics** | soft (polish) | Port `style_metrics.py`: She/He openers % of narration sentences, ellipses/1k, em dashes/1k, stock-phrase hits. Targets come from the style sheet. Skip text matching `protected_patterns`. Report per fragment and per chapter (the targets are defined per chapter). | POLISH_BRIEF targets. |
| **Dialogue-dash leftovers** | hard | A target paragraph starting with `– ` or `— ` where the source is dialogue. | Polish dash dialogue. |
| **Spelling variant** | soft | A US↔GB word list (color/colour, gray/grey, toward/towards, pajamas/pyjamas, -ize/-ise per house choice). | British spelling throughout. |
| **Formatting** | hard | Markdown escape backslashes (`\!`, `\.`); odd number of `*` in a paragraph; scene-break marker form; chapter heading matches the template; POV label line after labelled breaks. | BRIEF "Strip markdown escape backslashes"; `build_pdf.inline` had to work around odd asterisks. |
| **Unit policy** | soft | Metric units (`\d+\s?(m|km|cm|kg|metr…)`) in narration when the policy is `traditional`; allowed inside paragraphs styled as documents/charts. | "kilka metrów → a few paces"; °C kept on charts. |
| **Large undeclared polish edit** | soft | §3 edit-size check. | "wave → anger". |
| **Special-passage constraints** | hard | §10 verifiers. | Acrostic, cipher. |

`style_metrics.py` caveats to fix in the port: narration is found by stripping `"…"`, which breaks on unbalanced quotes; and the sentence splitter counts `*She` (italic thought) as narration. Use the paragraph `style`/kind plus a proper quote tokenizer instead.

## 9. Author flags (Step 6)

`AUTHOR_QUERIES.md` was assembled by hand from nine translators' "Flags" sections. It already had three sections: **"Needs your text / approval"** (blocks a final edition), **"Decisions applied across the book"** (global term choices), and **"Questions by section"**. The flag model stores flags so the UI can show the same three sections.

### Types

| `flag_type` | Meaning | Examples from the run | Default severity |
|---|---|---|---|
| `source_typo` | The source looks wrong; we translated what was probably meant. | "Kkilka", "Eianrd", "areny stresu" (→ ośrodki?), "Ciężkie stąpnięcie" (→ westchnienie?) | `fyi` when it's an obvious letter slip (auto-resolved, listed); `review` when the reading is a guess |
| `continuity` | An inconsistency in the source, kept as written. | Cup vs mug (Ch 6), brown vs grey paper (Ch 14), Frou vs Merla Mart, Hania/Hanna, "inquisitors" vs "assassins", Morvyn's gender | `review` |
| `ambiguity` | Several readings; we chose one. Includes speaker attribution. | "Agata czysta i odważna", whose father is "responsible", who "vanished", unattributed lines in Ch 13 | `review` |
| `wordplay` | Pun, name play, anagram or structure that doesn't survive; adapted or lost. | obrzęki/obrzędy → colds/cults, *Wiara* = Faith lost, *proso/prosiątko*, Vynmor/Morvyn kept, Płotka → Roach | `review`; `blocking` when linked to a special passage (§10) |
| `placeholder` | The author's own unfinished text. | `xxxxxxx` (Ch 30 epigraph), `[xxxx]` (Ch 17) | `blocking` |
| `added_clarification` | Words we added that the source doesn't have. | "Stein said" (Ch 21), the girl's-voice beat (Ch 11), adding `*Kerry*` to an unlabelled POV break | `review` |
| `term_choice` *(added)* | A translation decision that applies book-wide; maps to a glossary entry. | Ruda → Ginger, Smoliste → Pitchwood?, Hania normalisation, "pierce" vs "break the skin" | `review`, grouped per term |
| `qa_check` *(added)* | A hard QA check that still failed after the retry, or a large undeclared polish edit. | — | `review` |

Why the two added types: `term_choice` matches the "Decisions applied across the book" table, and resolving one changes the glossary and runs propagation, which a text edit can't do. `qa_check` keeps machine findings separate from the translator's own questions.

### Table

```
translation_flags
  id, book_id, run_id, fragment_id, paragraph_id (nullable for book-wide), rendition_id
  stage            faithful | line_edit | polish | qa | propagation | special
  flag_type        (enum above)
  severity         blocking | review | fyi
  source_excerpt, target_excerpt, question, rendered_as
  options          JSONB  [{label, target_text}]      -- e.g. "Ginger" / "Red"
  glossary_entry_id (nullable)                        -- term_choice, wordplay on a name
  special_passage_id (nullable)                       -- §10
  group_key        text                               -- dedupe: "term:ruda", "name:hania", "typo"
  status           open | accepted | changed | dismissed | superseded
  author_response  text
  resolution       JSONB  {action, patch_rendition_id | glossary_change_event_id | source_paragraph_revision}
  created_at, resolved_at
```

`group_key` collapses the same question raised by several fragments. "Ruda → Ginger vs Red" was flagged by three batches, and Hania/Hanna by four. The UI shows one card listing its occurrences.

### Resolution actions

| Action | Effect |
|---|---|
| Accept | `status=accepted`. Nothing changes. |
| Edit the English | The author writes the paragraph text → `author_edit` rendition. QA re-runs. Later re-renders keep author edits unless the author confirms overwriting them. |
| Pick an option | For `term_choice` → glossary change event (§6). For other types → patch the paragraph with the option text. |
| Fix the source | The author corrects the Polish (e.g. a missing sentence: "Ręce" in Ch 11; a typo) → a new paragraph revision, the fragment is re-translated, and its other flags become `superseded` and are re-raised if still relevant. Needs `paragraph_revisions(paragraph_id, version, text)`; `paragraphs.text` stays the current one. |
| Provide text | For `placeholder` → the author writes the missing source (or the English directly) → fragment re-render. |
| Dismiss | `status=dismissed` with a reason. |

### Review UI (Step 6)

- **Blocking** first (placeholders, special-passage approvals), with a counter that gates export.
- **Book-wide decisions**: `term_choice` cards in a table, like the "Decisions applied" table, showing the chosen target and the occurrence count, with a single action to change the term and propagate it.
- **By chapter**: everything else, side by side (source paragraph | English paragraph, highlighted excerpt), filtered by type and severity. Typos are collapsed into one "N silent fixes" disclosure per chapter.
- An "export as author queries" button produces the AUTHOR_QUERIES-style Markdown/PDF for authors who prefer to answer offline.

## 10. Special passages: acrostics, ciphers, puns, verse

These passages have to satisfy a rule (letters that spell a message, a rhyme scheme), and normal prose editing would break it. In the manual run, three of the six items in "Needs your text / approval" were of this kind.

| Kind | *Weaveress* instance | Constraint |
|---|---|---|
| `acrostic` | Ch 6 letter: sentence initials spell JESTEM / OBSERWOWANY → rewritten to I AM BEING / WATCHED (15 sentences, content kept, two sentences merged). | Initials of units (sentences, lines) spell a message; the content must still be covered; narration elsewhere quotes phrases back ("the index in the family library") and states the decoded message. |
| `cipher` | Ch 6 book cipher UKRYŁEM WIADOMOŚCI / ALURGIA KŁAMIE → I HID / MESSAGES / ALURGIA / LIES, with new example words ("inherent", "harmony", "intellect"). | A letter-extraction rule over marked words; the worked examples in narration must use the same rule. |
| `verse` | Ch 3 epigraph "forbidden rhyme", re-rhymed AABB with small additions. | Rhyme scheme, line count, roughly the meter. |
| `wordplay` | obrzęki/obrzędy (colds/cults); Vynmor = Morvyn syllables swapped ("*Mor. Vyn.*"); *Wiara* = Faith; *proso/prosiątko*. | Pun meaning in both senses; anagram preserved. |
| `gendered_grammar` | Ch 11 boy in bed ten speaks with feminine verb forms ("Patrzyłam") — a plot signal English verbs can't carry. | The reader must notice; needs an added beat (→ `added_clarification`). |
| `quoted_document` | Letters, scripture ("And they cut out his tongue…"), epigraphs, diary entries. | Register lock; polish must not touch. |

### Detection

- An LLM scan during the existing glossary extraction pass, or as a cheap separate pre-pass over the same windows, returns `SpecialPassageCandidate {kind, paragraph_ids, evidence, constraint_hint}`. Acrostics are also detected deterministically: take the initials of consecutive sentences in each paragraph group and look for dictionary words of 5+ letters.
- The author can mark or unmark passages in the reader.

### Table

```
special_passages
  id, book_id, chapter_id, kind
  paragraph_ids uuid[]               -- the passage itself
  dependent_paragraph_ids uuid[]     -- narration that quotes/decodes it
  constraint JSONB                   -- e.g. {"unit":"sentence","source_message":"JESTEM OBSERWOWANY","target_message":null}
  status      detected | confirmed | candidate_ready | approved
  approved_rendition_id
```

### Handling

- The fragmenter never splits a special passage. Its paragraphs are **frozen** for line-edit and polish (they are passed as read-only context, and the service copies them through).
- A dedicated chain generates **N = 3 candidates**:

  ```python
  async def translate_special_passage(
      *, passage: SpecialPassageIn,            # kind, source paragraphs, constraint, dependent source paragraphs
      context: FragmentContext,
      target_message: str | None,              # author may fix it ("I AM BEING WATCHED") or let the model propose
      n_candidates: int,
      settings: Settings,
  ) -> SpecialPassageCandidates: ...           # each: paragraphs, dependent_paragraph_patches, target_message, notes
  ```

- **Deterministic verifiers** run on every candidate: acrostic (extract the initials per the constraint's unit and compare to `target_message`); cipher (apply the extraction rule to the marked words and compare); verse (line count, end-rhyme check via a pronouncing dictionary for English; syllable count within ±2). The decoded message must appear in the `dependent_paragraph_ids` patches. Candidates that fail are dropped, and the chain retries up to 2 times.
- Surviving candidates go to the author as one **blocking `wordplay` flag** with the candidates as `options`. Approval writes the passage paragraphs and the dependent-paragraph patches as an `author_edit` rendition.
- `wordplay` and `gendered_grammar` passages don't use the candidate loop. The normal pipeline handles them, and the faithful pass is required to raise a flag for them (the passage list is in its context).

## 11. Export (PDF / EPUB)

`build_pdf.py` worked: Markdown → HTML with book typography → headless Chrome → 5.5×8.5 in PDF. In the app:

- **Export reads from the database.** It walks chapters → current renditions → paragraphs, using the paragraph `style`/kind that `manuscript_parser` already records (heading, epigraph, scene break, body, document). `build_pdf` had to guess epigraphs with an `after_heading` heuristic and guess chapter starts from `_part2` filenames. With block kinds, neither guess is needed.
- **Intermediate format**: a small block list `[{kind: title|pov_label|chapter_heading|epigraph|scene_break|scene_pov|paragraph|document, inlines}]` with inline italics/bold already parsed. Both renderers consume it.
- **PDF**: HTML + CSS (the `build_pdf.CSS` rules: EB Garamond, justified, hyphenation, no first-line indent after headings/breaks, centred epigraph and scene breaks, page numbers from `@page @bottom-center`). Render with **WeasyPrint** inside the backend container rather than a hard-coded macOS Chrome path. It supports `@page` margin boxes, which Chrome's print path doesn't. Embed the font files instead of loading Google Fonts at render time.
- **EPUB**: `ebooklib`, one XHTML per chapter from the same blocks and the same CSS minus `@page`; nav from chapter headings; metadata from `Book` (title, author, `target_language`).
- **Typography** at export only: smart quotes (`build_pdf.smart_quotes`, including the apostrophe rule), and em/en dash normalisation. Stored renditions keep straight quotes, so QA regexes stay simple.
- **Gating**: open `blocking` flags or unresolved `⟦term:…⟧` tokens → export is refused, or produced with a "DRAFT — N open items" watermark if the author asks.
- **Variants**: export any stage (faithful / line-edit / polish), as the manual run kept `The_Weaveress_v2_lineedit.pdf` next to the final. Also exports the glossary and the author-queries report.
- Table `exports(id, book_id, run_id, format, stage, status, storage_path, open_flag_count, created_at)`. Runs as a background job with the same polling pattern.

## 12. Schema summary and migrations

Migrations continue the numbered series (latest `0013_move_regeneration_flag_to_profile.py`; `a963d457ee71_verify_clean` branches from `0011` and needs checking before adding heads).

| Migration | Tables / columns |
|---|---|
| `0014_final_glossary_versioning` | `final_glossaries.version int`, `supersedes_id`; `final_glossary_entries.strategy`, `sense_notes`, `rejected_targets text[]`, `article`, `grammatical_number`, `decision_state`, `referent_entry_id`, `used_by_entry_ids uuid[]`; `glossary_entries` gets the same, plus `origin ∈ {extraction, translation}`; `glossary_change_events`. |
| `0015_style_sheets` | `book_style_sheets`; `books.active_style_sheet_version`. |
| `0016_fragments_and_runs` | `fragments(id, book_id, chapter_id, position, paragraph_ids uuid[], word_count, start_word_offset, is_special)`; `translation_runs(id, book_id, final_glossary_id, style_sheet_version, status, cancel_requested, fragments_total, fragments_completed, models JSONB, error_message, started_at, completed_at)`; `fragment_renditions(id, fragment_id, run_id, stage ∈ {faithful, line_edit, polish, patch, author_edit, special}, parent_id, paragraphs JSONB, final_glossary_id, style_sheet_version, model, prompt_hash, raw_response JSONB, usage_metadata JSONB, is_current bool, stale_reason, created_at)` with a partial unique index on `(fragment_id, stage) WHERE is_current`. |
| `0017_qa_and_terms` | `rendition_qa_results`; `fragment_term_occurrences`. |
| `0018_translation_flags` | `translation_flags`; `paragraph_revisions`. |
| `0019_special_passages` | `special_passages`. |
| `0020_exports` | `exports`. |

New modules, following the existing layout:

- `prompt_manager/prompts/_translation_rules.py`, `translate_fragment_faithful_prompt.py`, `line_edit_fragment_prompt.py`, `polish_fragment_prompt.py`, `patch_term_prompt.py`, `special_passage_prompt.py`
- `prompt_manager/models/translate_fragment_model.py` (shared `ParagraphOut`, `TermProposal`, `FlagProposal`, stage outputs), `special_passage_model.py`
- `chains/translate_fragment_chain.py` (three stage functions), `patch_term_chain.py`, `special_passage_chain.py`
- `services/fragmenter.py`, `translation_service.py` (run orchestration, claims, retries), `translation_qa.py`, `glossary_propagation.py`, `flags_service.py`, `export_service.py`, `translation_estimate.py`
- Settings: `TRANSLATION_FAITHFUL_MODEL`, `TRANSLATION_LINE_EDIT_MODEL`, `TRANSLATION_POLISH_MODEL` (each defaulting to `TRANSLATION_MODEL`, then `GEMINI_MODEL`), `TRANSLATION_CONCURRENCY`.

## 13. Build order

Each step is shippable and testable on its own. Steps 2–4 can be checked against the manual run: `pass1/`, `v2_lineedit/` and `en/` for chapters 1–3 work as reference outputs, `AUTHOR_QUERIES.md` as a recall target for flags, and the batch term tables as a recall target for claims. These files are the author's manuscript and are not in git, so keep them as local fixtures (e.g. under `data/`, which the compose stack already mounts) unless the author agrees to commit them.

1. **Publish the final glossary.** Implement `publish_final_glossary`, add versioning, `strategy`, `sense_notes`, `rejected_targets` (migration 0014, without the claim columns). Add a "Publish" button in glossary review. *Done when:* a book has an active final glossary with a 4-way strategy per entry.
2. **Style sheet and fragmenter.** Migrations 0015–0016 (fragments only); PL→EN defaults; a settings form. *Done when:* *Zaplataczka* splits into about 90–110 fragments, none crossing a chapter boundary.
3. **Shared rules and faithful pass, end to end on one chapter.** The §4 prompt refactor (with calibration prompt tests still passing), the faithful chain, `translation_runs` + renditions, the core hard QA checks (alignment, diacritics, case endings, placeholders, term sweep, formatting), and run polling in the UI. *Done when:* Ch 1–3 translate with zero hard-QA failures after retry, and the output reads comparably to `pass1/`.
4. **Flags and a minimal Step 6.** Migration 0018; flags from faithful output, silent fixes and QA; a chapter list with accept/edit/dismiss. *Done when:* most AUTHOR_QUERIES items for Ch 1–3 appear as flags of the right type.
5. **Line-edit and polish.** Both chains, the style-metrics port with chapter aggregates and `protected_patterns`, declared polish edits, and the drift guard. *Done when:* Ch 1–3 meet the POLISH_BRIEF targets (or explain why not), and the polish raises no large undeclared edit flags.
6. **Epithets and claims.** The `epithet` term type in extraction, claim insert-on-conflict, provisional glossary rows in prompts, ordered dispatch with concurrency. *Done when:* a full-book run produces one target per nickname (Ruda, dzikuska, kwiatuszku, piegusko), and the Hania forms raise a `term_choice` flag.
7. **Propagation and placeholder tokens.** Term occurrences, change events, deterministic and LLM patches, re-render, and tokens for `decision_state=open`. *Done when:* the replay test passes: start with Braider + Unclaimed Lands, switch to Weaver + the Drylands after a third of the book, and end with zero `rejected_targets` hits and literal braids left as they were.
8. **Special passages.** Detection, freezing, the candidate chain, verifiers, approval. *Done when:* the Ch 6 acrostic and cipher come back with verified candidates and the narration's decoded message matches.
9. **Export.** Block-list intermediate, WeasyPrint PDF, ebooklib EPUB, gating, author-queries export. *Done when:* the PDF matches `out/The_Weaveress.pdf` in layout and the EPUB passes epubcheck.

Steps 6–9 depend on 1–5 but not on each other, so they can be built in parallel.

## 14. Open questions

- **Fragment size versus quality.** The manual run had the line-editor see a whole chapter. Does line-edit at 1–1.5k words lose cross-paragraph rhythm? The fallback is to run polish per chapter (about 3–4k words), which costs fewer calls but makes patches coarser.
- **Provider.** The manual run used Claude agents. The app has only a Gemini provider. Line-edit and polish quality is where the model matters most. Adding `providers/anthropic.py` next to the Gemini provider is the first thing to try; the provider module was written so this needs no chain changes.
- **Who may change the style sheet mid-run**, and whether that marks renditions stale or only flags them. The proposal here: units and quote style → patch automatically; prose-level rules → stale, re-render on request.
- **Source edits from Step 6.** Should source fixes write back to the uploaded `.docx` for the author, or only live in `paragraph_revisions`?
- **Fixed terms not in the glossary** (e.g. "pierce" vs "break the skin" for *przebić barierę*, flagged in batch 1). They are recurring phrases rather than names. Do they belong in the glossary as `specialized_usage` (yes, probably), and should the faithful pass propose them as claims too?

---

## Model and pipeline tests (2026-10-21)

All tests used *Zaplataczka*. Quality was judged blind: for each paragraph the versions were shown under shuffled letters, and the best (and sometimes worst) was picked against the Polish before the key was opened. One reader, one run per setting, so small differences are within noise. Costs are for the whole book (about 108,000 words), estimated from the tokens actually used.

| Setting (chapter 5 only) | Best / worst of 20 | Whole book |
|---|---|---|
| Gemini 3.8 Flash, high thinking, all three stages | 4 / 0 | ~$67 list (~$33 until 31 Dec) |
| gpt-6.1-sol, high, all three stages | 11 / 2 | ~$69 standard |
| gpt-6-luna, high, all three stages | 0 / 9 | ~$3 |
| Luna → Luna → Sol, medium | 0 / 3 | ~$16 |
| Luna → Sol → Luna, medium | 5 / 6 | ~$15 |

Luna's faithful drafts were fine; its errors came from the final edit, where it rewrites freely (added "with the book on her lap", dropped the third gong stroke). Sol was strongest where judgement is needed.

| Setting (chapters 3 and 5, Flex, cache) | Blind wins of 40 | Whole book |
|---|---|---|
| Sol high, all three stages | 22 | ~$37 |
| Luna draft + Sol high line edit and final | 18 | ~$26 |
| Luna draft + one Sol high revision (two steps) | 26 (vs 14 for the row above) | ~$13 |

In the three-step runs the line edit changed about 85% of paragraphs and the final edit only about 31% (95% similar), mainly lowering She/He openers and repeated words, at about 40% of the cost. One revision that gets the line-edit instructions and the style targets together did better at half the price.

| Setting (chapters 3 and 5, Flex, cache) | Blind wins of 40 | Slips | Whole book |
|---|---|---|---|
| Two steps (Luna draft + one Sol revision) | 10 | 7 | ~$13 |
| One step (Sol straight into the final text) | 30 | 3 | ~$14 |

One step won in both chapters (14 to 6 in chapter 3, 16 to 4 in chapter 5). It was the only setting that kept "the year 200 before the Rending" and the trailing ellipsis in "Today…": in two steps both errors started in Luna's draft and Sol kept them. Its measured style is weaker (She/He openers 14.8% vs 8.5%, repeated words 17.0 vs 11.2 per 1,000), because the style targets cannot be measured on a draft that does not exist; in blind reading this mattered less than fidelity and natural phrasing. One step is the default (`TRANSLATION_STAGE_COUNT=1`); the Luna draft costs only about 3% of a run, so cost did not decide it.

Other findings:

- **Thinking level:** low or medium thinking let meaning drift through (added intensity, a lost stammer). All stages default to high.
- **Caching:** prompts start with the fixed part (rules, style sheet, glossary). Gemini runs use an explicit cache per run that is deleted afterwards; OpenAI runs prewarm OpenAI's own cache before the fragments start. About half of all input is then read from the cache.
- **Glossary variants:** extraction stored aliases and other names as variants (Vynmor under Naelori). Prompts now get only real case forms; fixing extraction and review is a separate task.
- **Still open:** some glossary terms drift in every setting (adept/trainee, weave/design, "The Rending" with a capital "The"), and one step repeats words more often than the multi-step modes.
