import { z } from "zod";

const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// ─── Schemas ────────────────────────────────────────────
// Mirror Pydantic on the backend. If the backend shape changes,
// these schemas catch the drift at runtime instead of letting
// a stale type slip through.

export const MetadataStatusSchema = z.enum(["pending", "ready", "failed"]);
export type MetadataStatus = z.infer<typeof MetadataStatusSchema>;

/** How to start or continue a run. */
export type RunOptions = {
  /** The model picked for the run; nothing means the configured default. */
  model?: string;
  /** False continues a run paused for cost without checking cost again. */
  costLimit?: boolean;
};

function runQuery(opts?: RunOptions): string {
  const params = new URLSearchParams();
  if (opts?.model) params.set("model", opts.model);
  if (opts?.costLimit === false) params.set("cost_limit", "false");
  return params.size ? `?${params.toString()}` : "";
}

/** One step's real cost against its estimate (see backend cost_guard). */
export const CostGuardStateSchema = z.object({
  estimate_usd: z.number(),
  spent_usd: z.number(),
  units_done: z.number().int(),
  units_total: z.number().int(),
  limit: z.boolean(),
  paused_reason: z.string().nullable(),
});
export type CostGuardState = z.infer<typeof CostGuardStateSchema>;

export const GlossaryExtractionStatusSchema = z.enum([
  "idle",
  "running",
  "completed",
  "failed",
  "cancelled",
]);
export type GlossaryExtractionStatus = z.infer<typeof GlossaryExtractionStatusSchema>;

export const VoiceExtractionStatusSchema = GlossaryExtractionStatusSchema;
export type VoiceExtractionStatus = z.infer<typeof VoiceExtractionStatusSchema>;

export const SpeakersExtractionStatusSchema = GlossaryExtractionStatusSchema;
export type SpeakersExtractionStatus = z.infer<typeof SpeakersExtractionStatusSchema>;

export const ParagraphSchema = z.object({
  id: z.string().uuid(),
  position: z.number().int(),
  text: z.string(),
  style: z.string().nullable(),
});
export type Paragraph = z.infer<typeof ParagraphSchema>;

export const ChapterDetailSchema = z.object({
  id: z.string().uuid(),
  position: z.number().int(),
  title: z.string().nullable(),
  paragraphs: z.array(ParagraphSchema),
});
export type ChapterDetail = z.infer<typeof ChapterDetailSchema>;

export const BookSummarySchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  author: z.string().nullable(),
  source_language: z.string(),
  target_language: z.string(),
  manuscript_language: z.string().nullable(),
  language_style_note: z.string().nullable(),
  metadata_model: z.string().nullable(),
  metadata_status: MetadataStatusSchema,
  glossary_extraction_status: GlossaryExtractionStatusSchema,
  glossary_extraction_windows_total: z.number().int().nullable().optional(),
  glossary_extraction_windows_completed: z.number().int().nullable().optional(),
  voice_extraction_status: VoiceExtractionStatusSchema,
  voice_extraction_windows_total: z.number().int().nullable().optional(),
  voice_extraction_windows_completed: z.number().int().nullable().optional(),
  voice_extraction_last_error: z.string().nullable().optional(),
  speakers_extraction_status: SpeakersExtractionStatusSchema,
  speakers_extraction_windows_total: z.number().int().nullable().optional(),
  speakers_extraction_windows_completed: z.number().int().nullable().optional(),
  speakers_extraction_last_error: z.string().nullable().optional(),
  /** Stages the author marked as finished by hand. */
  stages_marked_finished: z.array(z.enum(["glossary", "voices"])),
  /** Real cost against the estimate, per step ("glossary", "speakers", "voices", "translation"). */
  cost_guard: z.record(z.string(), CostGuardStateSchema),
  original_filename: z.string(),
  word_count: z.number().int(),
  created_at: z.string(),
});
export type BookSummary = z.infer<typeof BookSummarySchema>;

export const BookDetailSchema = BookSummarySchema.extend({
  chapters: z.array(ChapterDetailSchema),
});
export type BookDetail = z.infer<typeof BookDetailSchema>;

/** Stages the author can mark as finished by hand. */
export type MarkableStage = "glossary" | "voices";

export const UploadBookResponseSchema = z.object({
  book: BookSummarySchema,
  chapter_count: z.number().int(),
  paragraph_count: z.number().int(),
});
export type UploadBookResponse = z.infer<typeof UploadBookResponseSchema>;

export const GlossaryExtractionEstimateSchema = z.object({
  model: z.string(),
  window_count: z.number().int(),
  window_words: z.number().int(),
  overlap_words: z.number().int(),
  estimated_input_tokens: z.number().int(),
  estimated_output_tokens: z.number().int(),
  estimated_total_tokens: z.number().int(),
  estimated_cost_usd: z.number(),
  pricing_input_usd_per_mtok: z.number(),
  pricing_output_usd_per_mtok: z.number(),
});
export type GlossaryExtractionEstimate = z.infer<typeof GlossaryExtractionEstimateSchema>;

export const GlossaryExtractionStartResponseSchema = z.object({
  status: z.literal("accepted"),
  book_id: z.string().uuid(),
});
export type GlossaryExtractionStartResponse = z.infer<typeof GlossaryExtractionStartResponseSchema>;

export const GlossaryImportSourceSchema = z.object({
  book_id: z.string().uuid(),
  title: z.string().nullable(),
  original_filename: z.string().nullable(),
  created_at: z.string(),
  accepted: z.number().int(),
  removed: z.number().int(),
});
export type GlossaryImportSource = z.infer<typeof GlossaryImportSourceSchema>;

export const GlossaryImportSourcesSchema = z.object({
  sources: z.array(GlossaryImportSourceSchema),
});

export const GlossaryImportResultSchema = z.object({
  added: z.number().int(),
  updated: z.number().int(),
  kept: z.number().int(),
});
export type GlossaryImportResult = z.infer<typeof GlossaryImportResultSchema>;

export const GlossaryExtractionStopResponseSchema = z.object({
  status: z.literal("accepted"),
  book_id: z.string().uuid(),
});
export type GlossaryExtractionStopResponse = z.infer<typeof GlossaryExtractionStopResponseSchema>;

export const GlossaryWorkingEntrySchema = z.object({
  id: z.string().uuid(),
  canonical_form: z.string(),
  term_type: z.string(),
  meaning: z.string(),
  translation_recommendation: z.record(z.string(), z.unknown()),
  variants: z.array(z.string()),
  status: z.string(),
  first_seen_window: z.number().int(),
  occurrence_count: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
  /** Set while the status is an automatic decision you have not confirmed or undone. */
  auto_review: z
    .object({
      action: z.enum(["merge", "accept", "reject"]),
      reason: z.string(),
      source_canonical_form: z.string().optional(),
      /** Set when the LLM review decided it; form matches carry none. */
      confidence: z.enum(["high", "low"]).optional(),
      better_target: z.string().optional(),
      removed_variants: z.array(z.string()).optional(),
    })
    .passthrough()
    .nullable()
    .optional(),
  /** For `status === "merged"`: the term this one was merged into. */
  merged_into_id: z.string().uuid().nullable().optional(),
});
export type GlossaryWorkingEntry = z.infer<typeof GlossaryWorkingEntrySchema>;

export const GlossaryRunMetaSchema = z.object({
  id: z.string().uuid(),
  status: z.string(),
  started_at: z.string(),
  completed_at: z.string().nullable(),
  model: z.string().nullable(),
  entry_count: z.number().int(),
});
export type GlossaryRunMeta = z.infer<typeof GlossaryRunMetaSchema>;

export const GlossarySelectOptionSchema = z.object({
  id: z.string(),
  label: z.string(),
});
export type GlossarySelectOption = z.infer<typeof GlossarySelectOptionSchema>;

export const WorkingGlossaryResponseSchema = z.object({
  run: GlossaryRunMetaSchema.nullable(),
  entries: z.array(GlossaryWorkingEntrySchema),
  term_type_options: z.array(GlossarySelectOptionSchema),
  translation_suggestion_options: z.array(GlossarySelectOptionSchema),
});
export type WorkingGlossaryResponse = z.infer<typeof WorkingGlossaryResponseSchema>;

export const VoiceSelectedPassageSchema = z.object({
  id: z.string().uuid(),
  selection_rank: z.number().int(),
  source_text: z.string(),
  why_selected: z.string(),
  translation_proposed: z.string().nullable(),
  translation_authoritative: z.string().nullable(),
  status: z.string(),
  /** Cast pass: why the proposed English loses the voice, and a revision. */
  translation_review: z.string().nullable(),
  translation_revised: z.string().nullable(),
});
export type VoiceSelectedPassage = z.infer<typeof VoiceSelectedPassageSchema>;

export const VoiceEvidenceLineSchema = z.object({
  paragraph_id: z.string().uuid(),
  chapter_number: z.number().int(),
  text: z.string(),
});
export type VoiceEvidenceLine = z.infer<typeof VoiceEvidenceLineSchema>;

export const VoiceFeatureSchema = z.object({
  feature: z.string(),
  lines: z.array(VoiceEvidenceLineSchema),
});
export type VoiceFeature = z.infer<typeof VoiceFeatureSchema>;

export const VoiceRegisterShiftSchema = z.object({
  situation: z.string(),
  change: z.string(),
  lines: z.array(VoiceEvidenceLineSchema),
});
export type VoiceRegisterShift = z.infer<typeof VoiceRegisterShiftSchema>;

export const VoiceWorkingProfileSchema = z.object({
  id: z.string().uuid(),
  glossary_entry_id: z.string().uuid(),
  canonical_name: z.string(),
  source_voice_observation: z.string(),
  target_voice_strategy: z.string(),
  /** Short rules from the cast pass; what translation sends when set. */
  translation_brief: z.string().nullable(),
  /** Primary passage (rank 0); use `selected_passages` for the full v3 set. */
  reference_passage_source: z.string(),
  reference_passage_translation_proposed: z.string(),
  reference_passage_translation_authoritative: z.string().nullable(),
  /** Always present on the API (v3); may be `[]` before selection runs. */
  selected_passages: z.array(VoiceSelectedPassageSchema),
  status: z.string(),
  needs_regeneration: z.boolean(),
  dialogue_volume_observed: z.number().int(),
  first_seen_window: z.number().int(),
  last_observed_window: z.number().int(),
  /** Profiles built from all of a character's lines; 0 / [] for older profiles. */
  line_count: z.number().int(),
  low_evidence: z.boolean(),
  lines_sampled: z.boolean(),
  features: z.array(VoiceFeatureSchema),
  register_shifts: z.array(VoiceRegisterShiftSchema),
  created_at: z.string(),
  updated_at: z.string(),
});
export type VoiceWorkingProfile = z.infer<typeof VoiceWorkingProfileSchema>;

export const WorkingVoicesResponseSchema = z.object({
  entries: z.array(VoiceWorkingProfileSchema),
});
export type WorkingVoicesResponse = z.infer<typeof WorkingVoicesResponseSchema>;

export const AddresseeCountSchema = z.object({
  glossary_entry_id: z.string().uuid(),
  canonical_name: z.string(),
  line_count: z.number().int(),
});
export type AddresseeCount = z.infer<typeof AddresseeCountSchema>;

export const CharacterSpeakerMapSchema = z.object({
  glossary_entry_id: z.string().uuid(),
  canonical_name: z.string(),
  line_count: z.number().int(),
  thought_count: z.number().int(),
  speech_words: z.number().int(),
  chapters: z.array(z.number().int()),
  windows: z.array(z.number().int()),
  addressees: z.array(AddresseeCountSchema),
});
export type CharacterSpeakerMap = z.infer<typeof CharacterSpeakerMapSchema>;

export const WorkingSpeakersResponseSchema = z.object({
  entries: z.array(CharacterSpeakerMapSchema),
  lines_total: z.number().int(),
  lines_attributed: z.number().int(),
  lines_unknown: z.number().int(),
  lines_not_dialogue: z.number().int(),
});
export type WorkingSpeakersResponse = z.infer<typeof WorkingSpeakersResponseSchema>;

export const DialogueLineSchema = z.object({
  paragraph_id: z.string().uuid(),
  line_index: z.number().int(),
  chapter_number: z.number().int(),
  chapter_title: z.string().nullable(),
  text: z.string(),
  kind: z.string(),
  speaker_name: z.string().nullable(),
  addressee_name: z.string().nullable(),
  confidence: z.string().nullable(),
});
export type DialogueLine = z.infer<typeof DialogueLineSchema>;

export const DialogueLinesResponseSchema = z.object({
  lines: z.array(DialogueLineSchema),
  truncated: z.boolean(),
});
export type DialogueLinesResponse = z.infer<typeof DialogueLinesResponseSchema>;

export const ManuscriptSpeakerLineSchema = z.object({
  paragraph_id: z.string().uuid(),
  kind: z.string(),
  speaker_id: z.string().uuid().nullable(),
  speaker_name: z.string().nullable(),
  addressee_name: z.string().nullable(),
  confidence: z.string().nullable(),
  mixed: z.boolean(),
});
export type ManuscriptSpeakerLine = z.infer<typeof ManuscriptSpeakerLineSchema>;

export const ManuscriptSpeakersResponseSchema = z.object({
  lines: z.array(ManuscriptSpeakerLineSchema),
});
export type ManuscriptSpeakersResponse = z.infer<typeof ManuscriptSpeakersResponseSchema>;

export const NarrationSceneSchema = z.object({
  chapter_id: z.string().uuid(),
  pov_name: z.string().nullable(),
  pov_id: z.string().uuid().nullable(),
  source: z.enum(["heading", "scene_break", "assumed", "unknown"]),
  paragraph_ids: z.array(z.string().uuid()),
});
export type NarrationScene = z.infer<typeof NarrationSceneSchema>;

export const NarrationPovResponseSchema = z.object({
  scenes: z.array(NarrationSceneSchema),
});
export type NarrationPovResponse = z.infer<typeof NarrationPovResponseSchema>;

export const VoicePassEstimateSchema = z.object({
  model: z.string(),
  window_count: z.number().int(),
  character_count: z.number().int(),
  estimated_input_tokens: z.number().int(),
  estimated_output_tokens: z.number().int(),
  estimated_total_tokens: z.number().int(),
  estimated_cost_usd: z.number(),
});
export type VoicePassEstimate = z.infer<typeof VoicePassEstimateSchema>;

export const VoiceExtractionEstimateSchema = z.object({
  model: z.string(),
  window_words: z.number().int(),
  overlap_words: z.number().int(),
  character_count: z.number().int(),
  pass1: VoicePassEstimateSchema,
  pass2: VoicePassEstimateSchema,
  estimated_total_tokens: z.number().int(),
  estimated_cost_usd: z.number(),
  pricing_input_usd_per_mtok: z.number(),
  pricing_output_usd_per_mtok: z.number(),
});
export type VoiceExtractionEstimate = z.infer<typeof VoiceExtractionEstimateSchema>;

export type VoiceProfilePatchBody = {
  accept?: boolean;
  reject?: boolean;
  source_voice_observation?: string;
  target_voice_strategy?: string;
  translation_brief?: string;
  reference_passage_translation?: string;
  selected_passage_id?: string;
  selected_passage_translation?: string;
  needs_regeneration?: boolean;
};

export const GlossaryReviewResultSchema = z.object({
  by_form: z.number().int(),
  accepted: z.number().int(),
  rejected: z.number().int(),
  merged: z.number().int(),
  skipped: z.number().int(),
  /** What the review's model calls cost. */
  cost_usd: z.number(),
});
export type GlossaryReviewResult = z.infer<typeof GlossaryReviewResultSchema>;

export const GlossaryReviewEstimateSchema = z.object({
  model: z.string(),
  pending: z.number().int(),
  input_tokens: z.number().int(),
  output_tokens: z.number().int(),
  cost_usd: z.number(),
});
export type GlossaryReviewEstimate = z.infer<typeof GlossaryReviewEstimateSchema>;

/** Pipeline steps that let you pick a model. */
export type ModelStep = "glossary" | "glossary_review" | "speakers" | "voices" | "translation";

export const ModelCatalogSchema = z.object({
  options: z.array(z.object({ id: z.string(), label: z.string(), provider: z.string() })),
  steps: z.record(
    z.string(),
    z.object({ default: z.string(), recommended: z.string(), note: z.string() }),
  ),
});
export type ModelCatalog = z.infer<typeof ModelCatalogSchema>;

/** `?model=…` for calls that take the model picked for a run. */
function modelQuery(model?: string): string {
  return model ? `?model=${encodeURIComponent(model)}` : "";
}

export type GlossaryEntryPatchBody = {
  proposed_target?: string;
  suggestion?: "keep_original" | "translate";
  accept?: boolean;
  reject?: boolean;
  merge_into_entry_id?: string;
  confirm_auto?: boolean;
  undo_auto?: boolean;
};

// ─── Translation (Step 5) ───────────────────────────────

export const TranslationStageSchema = z.enum(["faithful", "line_edit", "polish"]);
export type TranslationStage = z.infer<typeof TranslationStageSchema>;

export const TranslationRunSchema = z.object({
  id: z.string(),
  status: z.enum(["running", "completed", "failed", "cancelled"]),
  cancel_requested: z.boolean(),
  chapter_ids: z.array(z.string()).nullable(),
  fragments_total: z.number().int(),
  fragments_completed: z.number().int(),
  fragments_failed: z.number().int(),
  models: z.record(z.string()),
  error_message: z.string().nullable(),
  started_at: z.string(),
  completed_at: z.string().nullable(),
});
export type TranslationRun = z.infer<typeof TranslationRunSchema>;

export const TranslatorNoteSchema = z.object({
  paragraph_id: z.string().nullable(),
  kind: z.string(),
  note: z.string(),
});
export type TranslatorNote = z.infer<typeof TranslatorNoteSchema>;

export const DeclaredEditSchema = z.object({
  paragraph_id: z.string().nullable(),
  kind: z.string(),
  before: z.string(),
  after: z.string(),
  why: z.string(),
});
export type DeclaredEdit = z.infer<typeof DeclaredEditSchema>;

export const QaIssueSchema = z.object({
  check: z.string(),
  paragraph_id: z.string(),
  detail: z.string(),
});
export type QaIssue = z.infer<typeof QaIssueSchema>;

export const StyleMetricsSchema = z.object({
  words: z.number(),
  narration_sentences: z.number(),
  she_he_openers: z.number(),
  ellipses: z.number(),
  em_dashes: z.number(),
  stock: z.record(z.number()),
  she_he_pct: z.number(),
  ellipses_per_1k: z.number(),
  dashes_per_1k: z.number(),
  stock_total: z.number(),
  repetitions: z.number().optional(),
  repetitions_per_1k: z.number().optional(),
  even_runs: z.number().optional(),
});
export type StyleMetrics = z.infer<typeof StyleMetricsSchema>;

export const StageOutputSchema = z.object({
  paragraphs: z.array(z.object({ paragraph_id: z.string(), text: z.string() })),
  notes: z.array(TranslatorNoteSchema),
  declared_edits: z.array(DeclaredEditSchema),
  qa: z.array(QaIssueSchema),
  metrics: StyleMetricsSchema.partial(),
  model: z.string().nullable(),
  created_at: z.string(),
});
export type StageOutput = z.infer<typeof StageOutputSchema>;

export const TranslationFragmentSchema = z.object({
  fragment_id: z.string(),
  position: z.number().int(),
  paragraph_ids: z.array(z.string()),
  word_count: z.number().int(),
  run_status: z
    .object({
      status: z.enum(["pending", "running", "completed", "failed"]),
      last_stage: TranslationStageSchema.nullable(),
      error_message: z.string().nullable(),
    })
    .nullable(),
  stages: z.object({
    faithful: StageOutputSchema.optional(),
    line_edit: StageOutputSchema.optional(),
    polish: StageOutputSchema.optional(),
  }),
});
export type TranslationFragment = z.infer<typeof TranslationFragmentSchema>;

export const ChapterTranslationSchema = z.object({
  chapter_id: z.string(),
  fragments: z.array(TranslationFragmentSchema),
  metrics: z.object({
    faithful: StyleMetricsSchema.optional(),
    line_edit: StyleMetricsSchema.optional(),
    polish: StyleMetricsSchema.optional(),
  }),
});
export type ChapterTranslation = z.infer<typeof ChapterTranslationSchema>;

export const TranslationViewSchema = z.object({
  run: TranslationRunSchema.nullable(),
  fragment_count: z.number().int(),
  chapters: z.array(ChapterTranslationSchema),
});
export type TranslationView = z.infer<typeof TranslationViewSchema>;

export const TranslationEstimateSchema = z.object({
  service_tier: z.string().nullable().optional(),
  word_count: z.number().int(),
  fragment_count: z.number().int(),
  glossary_terms: z.number().int(),
  total_tokens: z.number().int(),
  cost_usd: z.number(),
  stages: z.array(
    z.object({
      stage: TranslationStageSchema,
      model: z.string(),
      thinking: z.string().nullable().optional(),
      stored_as: TranslationStageSchema,
      calls: z.number().int(),
      input_tokens: z.number().int(),
      output_tokens: z.number().int(),
      cost_usd: z.number(),
    }),
  ),
});
export type TranslationEstimate = z.infer<typeof TranslationEstimateSchema>;

export const GlossaryTermSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  term_type: z.string(),
  note: z.string().nullable(),
  status: z.string(),
});
export type GlossaryTerm = z.infer<typeof GlossaryTermSchema>;

export const TermSpanSchema = z.object({
  term_id: z.string(),
  start: z.number().int(),
  end: z.number().int(),
});
export type TermSpan = z.infer<typeof TermSpanSchema>;

export const TranslationTermsSchema = z.object({
  terms: z.array(GlossaryTermSchema),
  paragraphs: z.record(z.array(TermSpanSchema)),
});
export type TranslationTerms = z.infer<typeof TranslationTermsSchema>;

export type StartTranslationBody = {
  chapter_ids?: string[] | null;
  retranslate?: boolean;
  /** Model for every stage of the run; omit for the configured one. */
  model?: string;
};

export type ExportFormat = "pdf" | "epub" | "docx";

/**
 * Download URL for the translated book (a plain link; the API sends a file).
 * `draft` exports even when special passages still need a decision.
 */
export function translationExportUrl(
  bookId: string,
  format: ExportFormat,
  stage: TranslationStage,
  draft = false,
): string {
  const url = `${API_URL}/books/${bookId}/translation/export?format=${format}&stage=${stage}`;
  return draft ? `${url}&draft=true` : url;
}

// ─── Special passages (Step 6) ──────────────────────────

export const PassageKindSchema = z.enum(["verse", "hidden_message", "wordplay"]);
export type PassageKind = z.infer<typeof PassageKindSchema>;

const PassageParagraphSchema = z.object({
  paragraph_id: z.string(),
  source: z.string(),
  /** Current English; null while the paragraph is not translated. */
  text: z.string().nullable(),
  /** English before the first correction. */
  first_text: z.string().nullable(),
});
export type PassageParagraph = z.infer<typeof PassageParagraphSchema>;

const PassageCandidateSchema = z.object({
  paragraphs: z.array(z.object({ paragraph_id: z.string(), text: z.string() })),
  target_message: z.string().nullable(),
  notes: z.string(),
  /** Why this version failed the check; empty when it passed. */
  problems: z.array(z.string()),
});
export type PassageCandidate = z.infer<typeof PassageCandidateSchema>;

export const PassageSchema = z.object({
  id: z.string(),
  chapter_id: z.string(),
  chapter_label: z.string(),
  kind: PassageKindSchema,
  rule: z.string(),
  unit: z.string().nullable(),
  source_message: z.string().nullable(),
  target_message: z.string().nullable(),
  evidence: z.string(),
  origin: z.enum(["detected", "author"]),
  status: z.enum(["unchecked", "passed", "corrected", "failed", "author", "dismissed"]),
  problems: z.array(z.string()),
  translated: z.boolean(),
  /** The English changed since the last check. */
  stale: z.boolean(),
  paragraphs: z.array(PassageParagraphSchema),
  dependent_paragraphs: z.array(PassageParagraphSchema),
  candidates: z.array(PassageCandidateSchema),
  flag: z
    .object({
      id: z.string(),
      severity: z.enum(["blocking", "review", "fyi"]),
      status: z.enum(["open", "accepted", "changed", "dismissed"]),
      question: z.string(),
    })
    .nullable(),
});
export type Passage = z.infer<typeof PassageSchema>;

export const PassagesViewSchema = z.object({
  state: z.object({
    status: z.enum(["idle", "scanning", "checking", "completed", "failed"]),
    done: z.number().int(),
    total: z.number().int(),
    error: z.string().nullable(),
    scanned: z.boolean(),
  }),
  passages: z.array(PassageSchema),
  open_flags: z.number().int(),
  blocking_flags: z.number().int(),
});
export type PassagesView = z.infer<typeof PassagesViewSchema>;

export type CreatePassageBody = {
  first_paragraph_id: string;
  last_paragraph_id: string;
  kind: PassageKind;
  rule?: string;
};

export type ResolvePassageBody =
  | { action: "accept" | "restore" | "dismiss" }
  | { action: "use_candidate"; candidate: number }
  | { action: "edit"; paragraphs: { paragraph_id: string; text: string }[] };

// ─── Errors ─────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function handleResponse<T>(res: Response, schema: z.ZodType<T>): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // leave default detail
    }
    throw new ApiError(res.status, detail);
  }
  const json = await res.json();
  return schema.parse(json);
}

// ─── Endpoints ──────────────────────────────────────────

export const api = {
  listBooks: async (): Promise<BookSummary[]> =>
    handleResponse(await fetch(`${API_URL}/books`), z.array(BookSummarySchema)),

  getBook: async (id: string): Promise<BookDetail> =>
    handleResponse(await fetch(`${API_URL}/books/${id}`), BookDetailSchema),

  getGlossaryExtractionEstimate: async (
    id: string,
    model?: string,
  ): Promise<GlossaryExtractionEstimate> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction-estimate${modelQuery(model)}`),
      GlossaryExtractionEstimateSchema,
    ),

  getVoiceExtractionEstimate: async (
    id: string,
    speakersModel?: string,
    voicesModel?: string,
  ): Promise<VoiceExtractionEstimate> =>
    handleResponse(
      await fetch(
        `${API_URL}/books/${id}/voice-extraction-estimate?` +
          new URLSearchParams({
            ...(speakersModel ? { speakers_model: speakersModel } : {}),
            ...(voicesModel ? { voices_model: voicesModel } : {}),
          }).toString(),
      ),
      VoiceExtractionEstimateSchema,
    ),

  getWorkingGlossary: async (id: string): Promise<WorkingGlossaryResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-working`),
      WorkingGlossaryResponseSchema,
    ),

  getWorkingVoices: async (id: string): Promise<WorkingVoicesResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voices-working`),
      WorkingVoicesResponseSchema,
    ),

  getWorkingSpeakers: async (id: string): Promise<WorkingSpeakersResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/speakers-working`),
      WorkingSpeakersResponseSchema,
    ),

  /** Lines said by one character, or (speakerId null) lines with no speaker. */
  getDialogueLines: async (id: string, speakerId: string | null): Promise<DialogueLinesResponse> =>
    handleResponse(
      await fetch(
        `${API_URL}/books/${id}/dialogue-lines${speakerId ? `?speaker=${encodeURIComponent(speakerId)}` : ""}`,
      ),
      DialogueLinesResponseSchema,
    ),

  /** Speaker of every dialogue line, for the manuscript's speaker layer. */
  getManuscriptSpeakers: async (id: string): Promise<ManuscriptSpeakersResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/manuscript/speakers`),
      ManuscriptSpeakersResponseSchema,
    ),

  /** Whose POV each scene follows, read from chapter headings and scene breaks. */
  getManuscriptNarration: async (id: string): Promise<NarrationPovResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/manuscript/narration`),
      NarrationPovResponseSchema,
    ),

  patchVoiceWorkingProfile: async (
    bookId: string,
    voiceId: string,
    body: VoiceProfilePatchBody,
  ): Promise<VoiceWorkingProfile> =>
    handleResponse(
      await fetch(`${API_URL}/books/${bookId}/voices-working/profiles/${voiceId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      VoiceWorkingProfileSchema,
    ),

  startVoiceExtraction: async (
    id: string,
    opts?: RunOptions,
  ): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/run${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  continueVoiceExtraction: async (
    id: string,
    opts?: RunOptions,
  ): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/continue${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  regenerateFlaggedVoices: async (
    id: string,
    opts?: RunOptions,
  ): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/regenerate${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  /**
   * Rewrite the briefs (unless `rebuildBriefs` is false), retranslate the
   * unreviewed reference passages with them, and check the passages.
   */
  runVoiceCastPass: async (
    id: string,
    opts?: RunOptions & { rebuildBriefs?: boolean },
  ): Promise<GlossaryExtractionStartResponse> => {
    const q = runQuery(opts);
    const extra = opts?.rebuildBriefs === false ? `${q ? "&" : "?"}rebuild_briefs=false` : "";
    return handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/cast-pass${q}${extra}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    );
  },

  stopVoiceExtraction: async (id: string): Promise<GlossaryExtractionStopResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/stop`, { method: "POST" }),
      GlossaryExtractionStopResponseSchema,
    ),

  resetVoiceExtraction: async (id: string): Promise<void> => {
    const res = await fetch(`${API_URL}/books/${id}/voice-extraction/reset`, { method: "POST" });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (body?.detail != null) detail = String(body.detail);
      } catch {
        // keep default
      }
      throw new ApiError(res.status, detail);
    }
  },

  startSpeakersExtraction: async (
    id: string,
    opts?: RunOptions,
  ): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/speaker-extraction/run${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  continueSpeakersExtraction: async (
    id: string,
    opts?: RunOptions,
  ): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/speaker-extraction/continue${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  stopSpeakersExtraction: async (id: string): Promise<GlossaryExtractionStopResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/speaker-extraction/stop`, { method: "POST" }),
      GlossaryExtractionStopResponseSchema,
    ),

  resetSpeakersExtraction: async (id: string): Promise<void> => {
    const res = await fetch(`${API_URL}/books/${id}/speaker-extraction/reset`, {
      method: "POST",
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (body?.detail != null) detail = String(body.detail);
      } catch {
        // keep default
      }
      throw new ApiError(res.status, detail);
    }
  },

  patchGlossaryWorkingEntry: async (
    bookId: string,
    entryId: string,
    body: GlossaryEntryPatchBody,
  ): Promise<GlossaryWorkingEntry> =>
    handleResponse(
      await fetch(`${API_URL}/books/${bookId}/glossary-working/entries/${entryId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      GlossaryWorkingEntrySchema,
    ),

  setStageFinished: async (
    bookId: string,
    stage: MarkableStage,
    finished: boolean,
  ): Promise<BookDetail> =>
    handleResponse(
      await fetch(`${API_URL}/books/${bookId}/stages/${stage}/finished`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ finished }),
      }),
      BookDetailSchema,
    ),

  reviewPendingGlossaryTerms: async (
    bookId: string,
    model?: string,
  ): Promise<GlossaryReviewResult> =>
    handleResponse(
      await fetch(`${API_URL}/books/${bookId}/glossary-working/review${modelQuery(model)}`, {
        method: "POST",
      }),
      GlossaryReviewResultSchema,
    ),

  getGlossaryReviewEstimate: async (
    bookId: string,
    model?: string,
  ): Promise<GlossaryReviewEstimate> =>
    handleResponse(
      await fetch(
        `${API_URL}/books/${bookId}/glossary-working/review-estimate${modelQuery(model)}`,
      ),
      GlossaryReviewEstimateSchema,
    ),

  listModels: async (): Promise<ModelCatalog> =>
    handleResponse(await fetch(`${API_URL}/books/models`), ModelCatalogSchema),

  confirmAutoGlossaryReviews: async (bookId: string): Promise<{ confirmed: number }> =>
    handleResponse(
      await fetch(`${API_URL}/books/${bookId}/glossary-working/confirm-auto`, { method: "POST" }),
      z.object({ confirmed: z.number().int() }),
    ),

  startGlossaryExtraction: async (
    id: string,
    opts?: RunOptions,
  ): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction/run${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  continueGlossaryExtraction: async (
    id: string,
    opts?: RunOptions,
  ): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction/continue${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  expandGlossary: async (id: string, opts?: RunOptions): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction/expand${runQuery(opts)}`, {
        method: "POST",
      }),
      GlossaryExtractionStartResponseSchema,
    ),

  getGlossaryImportSources: async (id: string): Promise<GlossaryImportSource[]> =>
    (
      await handleResponse(
        await fetch(`${API_URL}/books/${id}/glossary-import-sources`),
        GlossaryImportSourcesSchema,
      )
    ).sources,

  importGlossary: async (id: string, sourceBookId: string): Promise<GlossaryImportResult> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_book_id: sourceBookId }),
      }),
      GlossaryImportResultSchema,
    ),

  stopGlossaryExtraction: async (id: string): Promise<GlossaryExtractionStopResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction/stop`, { method: "POST" }),
      GlossaryExtractionStopResponseSchema,
    ),

  getTranslation: async (id: string): Promise<TranslationView> =>
    handleResponse(await fetch(`${API_URL}/books/${id}/translation`), TranslationViewSchema),

  /** `includePending` also returns terms still under review (the manuscript shows them). */
  getTranslationTerms: async (id: string, includePending = false): Promise<TranslationTerms> =>
    handleResponse(
      await fetch(
        `${API_URL}/books/${id}/translation/terms${includePending ? "?include_pending=true" : ""}`,
      ),
      TranslationTermsSchema,
    ),

  getTranslationEstimate: async (
    id: string,
    chapterIds: string[] | null,
    model?: string,
  ): Promise<TranslationEstimate> => {
    const params = new URLSearchParams();
    for (const c of chapterIds ?? []) params.append("chapter_id", c);
    if (model) params.set("model", model);
    const qs = params.size ? `?${params.toString()}` : "";
    return handleResponse(
      await fetch(`${API_URL}/books/${id}/translation/estimate${qs}`),
      TranslationEstimateSchema,
    );
  },

  getPassages: async (id: string): Promise<PassagesView> =>
    handleResponse(await fetch(`${API_URL}/books/${id}/passages`), PassagesViewSchema),

  scanPassages: async (id: string): Promise<PassagesView> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/passages/scan`, { method: "POST" }),
      PassagesViewSchema,
    ),

  /** Check every translated passage, or one passage again. */
  checkPassages: async (id: string, passageId?: string): Promise<PassagesView> =>
    handleResponse(
      await fetch(
        `${API_URL}/books/${id}/passages/check${passageId ? `?passage_id=${passageId}` : ""}`,
        { method: "POST" },
      ),
      PassagesViewSchema,
    ),

  createPassage: async (id: string, body: CreatePassageBody): Promise<PassagesView> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/passages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      PassagesViewSchema,
    ),

  updatePassage: async (
    id: string,
    passageId: string,
    body: { rule?: string; target_message?: string },
  ): Promise<PassagesView> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/passages/${passageId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      PassagesViewSchema,
    ),

  resolvePassage: async (
    id: string,
    passageId: string,
    body: ResolvePassageBody,
  ): Promise<PassagesView> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/passages/${passageId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      PassagesViewSchema,
    ),

  startTranslation: async (id: string, body: StartTranslationBody): Promise<TranslationRun> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/translation/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      TranslationRunSchema,
    ),

  continueTranslation: async (id: string, opts?: RunOptions): Promise<TranslationRun> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/translation/continue${runQuery(opts)}`, {
        method: "POST",
      }),
      TranslationRunSchema,
    ),

  stopTranslation: async (id: string): Promise<void> => {
    const res = await fetch(`${API_URL}/books/${id}/translation/stop`, { method: "POST" });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (body?.detail != null) detail = String(body.detail);
      } catch {
        // keep default
      }
      throw new ApiError(res.status, detail);
    }
  },

  uploadBook: async (file: File): Promise<UploadBookResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    return handleResponse(
      await fetch(`${API_URL}/books`, { method: "POST", body: fd }),
      UploadBookResponseSchema,
    );
  },

  deleteBook: async (id: string): Promise<void> => {
    const res = await fetch(`${API_URL}/books/${id}`, { method: "DELETE" });
    if (!res.ok) {
      throw new ApiError(res.status, `${res.status} ${res.statusText}`);
    }
  },
};
