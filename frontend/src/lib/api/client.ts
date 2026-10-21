import { z } from "zod";

const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// ─── Schemas ────────────────────────────────────────────
// Mirror Pydantic on the backend. If the backend shape changes,
// these schemas catch the drift at runtime instead of letting
// a stale type slip through.

export const MetadataStatusSchema = z.enum(["pending", "ready", "failed"]);
export type MetadataStatus = z.infer<typeof MetadataStatusSchema>;

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
  original_filename: z.string(),
  word_count: z.number().int(),
  created_at: z.string(),
});
export type BookSummary = z.infer<typeof BookSummarySchema>;

export const BookDetailSchema = BookSummarySchema.extend({
  chapters: z.array(ChapterDetailSchema),
});
export type BookDetail = z.infer<typeof BookDetailSchema>;

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
});
export type VoiceSelectedPassage = z.infer<typeof VoiceSelectedPassageSchema>;

export const VoiceWorkingProfileSchema = z.object({
  id: z.string().uuid(),
  glossary_entry_id: z.string().uuid(),
  canonical_name: z.string(),
  source_voice_observation: z.string(),
  target_voice_strategy: z.string(),
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
  created_at: z.string(),
  updated_at: z.string(),
});
export type VoiceWorkingProfile = z.infer<typeof VoiceWorkingProfileSchema>;

export const WorkingVoicesResponseSchema = z.object({
  entries: z.array(VoiceWorkingProfileSchema),
});
export type WorkingVoicesResponse = z.infer<typeof WorkingVoicesResponseSchema>;

export const SpeakerWindowSchema = z.object({
  window_number: z.number().int(),
  quoted_evidence: z.string(),
});
export type SpeakerWindow = z.infer<typeof SpeakerWindowSchema>;

export const CharacterSpeakerMapSchema = z.object({
  glossary_entry_id: z.string().uuid(),
  canonical_name: z.string(),
  windows: z.array(z.number().int()),
  appearances: z.array(SpeakerWindowSchema),
});
export type CharacterSpeakerMap = z.infer<typeof CharacterSpeakerMapSchema>;

export const WorkingSpeakersResponseSchema = z.object({
  entries: z.array(CharacterSpeakerMapSchema),
  windows_mapped: z.number().int(),
  edges_total: z.number().int(),
});
export type WorkingSpeakersResponse = z.infer<typeof WorkingSpeakersResponseSchema>;

export const VoicePassEstimateSchema = z.object({
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
  reference_passage_translation?: string;
  selected_passage_id?: string;
  selected_passage_translation?: string;
  needs_regeneration?: boolean;
};

export type GlossaryEntryPatchBody = {
  proposed_target?: string;
  suggestion?: "keep_original" | "translate";
  accept?: boolean;
  reject?: boolean;
  merge_into_entry_id?: string;
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
  word_count: z.number().int(),
  fragment_count: z.number().int(),
  glossary_terms: z.number().int(),
  total_tokens: z.number().int(),
  cost_usd: z.number(),
  stages: z.array(
    z.object({
      stage: TranslationStageSchema,
      model: z.string(),
      calls: z.number().int(),
      input_tokens: z.number().int(),
      output_tokens: z.number().int(),
      cost_usd: z.number(),
    }),
  ),
});
export type TranslationEstimate = z.infer<typeof TranslationEstimateSchema>;

export type StartTranslationBody = {
  chapter_ids?: string[] | null;
  retranslate?: boolean;
};

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

  getGlossaryExtractionEstimate: async (id: string): Promise<GlossaryExtractionEstimate> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction-estimate`),
      GlossaryExtractionEstimateSchema,
    ),

  getVoiceExtractionEstimate: async (id: string): Promise<VoiceExtractionEstimate> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction-estimate`),
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

  startVoiceExtraction: async (id: string): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/run`, { method: "POST" }),
      GlossaryExtractionStartResponseSchema,
    ),

  continueVoiceExtraction: async (id: string): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/continue`, { method: "POST" }),
      GlossaryExtractionStartResponseSchema,
    ),

  regenerateFlaggedVoices: async (id: string): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/voice-extraction/regenerate`, { method: "POST" }),
      GlossaryExtractionStartResponseSchema,
    ),

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

  startSpeakersExtraction: async (id: string): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/speaker-extraction/run`, { method: "POST" }),
      GlossaryExtractionStartResponseSchema,
    ),

  continueSpeakersExtraction: async (id: string): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/speaker-extraction/continue`, { method: "POST" }),
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

  startGlossaryExtraction: async (id: string): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction/run`, { method: "POST" }),
      GlossaryExtractionStartResponseSchema,
    ),

  continueGlossaryExtraction: async (id: string): Promise<GlossaryExtractionStartResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction/continue`, { method: "POST" }),
      GlossaryExtractionStartResponseSchema,
    ),

  stopGlossaryExtraction: async (id: string): Promise<GlossaryExtractionStopResponse> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/glossary-extraction/stop`, { method: "POST" }),
      GlossaryExtractionStopResponseSchema,
    ),

  getTranslation: async (id: string): Promise<TranslationView> =>
    handleResponse(await fetch(`${API_URL}/books/${id}/translation`), TranslationViewSchema),

  getTranslationEstimate: async (
    id: string,
    chapterIds: string[] | null,
  ): Promise<TranslationEstimate> => {
    const qs = chapterIds?.length
      ? "?" + chapterIds.map((c) => `chapter_id=${encodeURIComponent(c)}`).join("&")
      : "";
    return handleResponse(
      await fetch(`${API_URL}/books/${id}/translation/estimate${qs}`),
      TranslationEstimateSchema,
    );
  },

  startTranslation: async (id: string, body: StartTranslationBody): Promise<TranslationRun> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/translation/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      TranslationRunSchema,
    ),

  continueTranslation: async (id: string): Promise<TranslationRun> =>
    handleResponse(
      await fetch(`${API_URL}/books/${id}/translation/continue`, { method: "POST" }),
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
