import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  api,
  type BookDetail,
  type BookSummary,
  type DialogueLinesResponse,
  type GlossaryEntryPatchBody,
  type GlossaryExtractionEstimate,
  type GlossaryExtractionStartResponse,
  type GlossaryExtractionStopResponse,
  type GlossaryImportResult,
  type GlossaryImportSource,
  type GlossaryReviewEstimate,
  type GlossaryReviewResult,
  type GlossaryWorkingEntry,
  type ManuscriptSpeakersResponse,
  type MarkableStage,
  type NarrationPovResponse,
  type ModelCatalog,
  type RunOptions,
  type StartTranslationBody,
  type TranslationEstimate,
  type TranslationRun,
  type TranslationTerms,
  type TranslationView,
  type UploadBookResponse,
  type VoiceExtractionEstimate,
  type VoiceProfilePatchBody,
  type VoiceWorkingProfile,
  type WorkingGlossaryResponse,
  type WorkingSpeakersResponse,
  type WorkingVoicesResponse,
} from "./client";

// Query key factory — all cache invalidation flows through here.
export const bookKeys = {
  all: ["books"] as const,
  lists: () => [...bookKeys.all, "list"] as const,
  detail: (id: string) => [...bookKeys.all, "detail", id] as const,
  glossaryEstimate: (id: string) => [...bookKeys.all, "glossary-estimate", id] as const,
  voiceEstimate: (id: string) => [...bookKeys.all, "voice-estimate", id] as const,
  workingGlossary: (id: string) => [...bookKeys.all, "working-glossary", id] as const,
  glossaryImportSources: (id: string) => [...bookKeys.all, "glossary-import-sources", id] as const,
  workingVoices: (id: string) => [...bookKeys.all, "working-voices", id] as const,
  workingSpeakers: (id: string) => [...bookKeys.all, "working-speakers", id] as const,
  dialogueLines: (id: string, speakerId: string | null) =>
    [...bookKeys.all, "dialogue-lines", id, speakerId ?? "none"] as const,
  translation: (id: string) => [...bookKeys.all, "translation", id] as const,
  translationTerms: (id: string) => [...bookKeys.all, "translation-terms", id] as const,
  // Under `translationTerms` so glossary edits that refresh one refresh both.
  manuscriptTerms: (id: string) => [...bookKeys.translationTerms(id), "with-pending"] as const,
  manuscriptSpeakers: (id: string) => [...bookKeys.all, "manuscript-speakers", id] as const,
  // Under `workingGlossary`: POV names are matched to glossary characters.
  manuscriptNarration: (id: string) => [...bookKeys.workingGlossary(id), "narration"] as const,
  translationEstimate: (id: string, chapterIds: readonly string[] | null) =>
    [...bookKeys.all, "translation-estimate", id, chapterIds ?? "all"] as const,
};

// How often to re-fetch a book while it's still being enriched. Short
// enough that the metadata appears responsive, long enough that we don't
// hammer the API for nothing. Stops automatically once status flips.
const METADATA_POLL_INTERVAL_MS = 1500;

export function useBooks(): UseQueryResult<BookSummary[], Error> {
  return useQuery({
    queryKey: bookKeys.lists(),
    queryFn: api.listBooks,
    refetchInterval: (query) => {
      // Keep the sidebar in sync while *any* book is still pending.
      const data = query.state.data;
      if (!data) return false;
      const anyPending = data.some((b) => b.metadata_status === "pending");
      const anyGlossary = data.some((b) => b.glossary_extraction_status === "running");
      const anySpeakers = data.some((b) => b.speakers_extraction_status === "running");
      const anyVoice = data.some((b) => b.voice_extraction_status === "running");
      return anyPending || anyGlossary || anySpeakers || anyVoice
        ? METADATA_POLL_INTERVAL_MS
        : false;
    },
  });
}

export function useBook(id: string | null): UseQueryResult<BookDetail, Error> {
  return useQuery({
    queryKey: id ? bookKeys.detail(id) : ["books", "detail", "none"],
    queryFn: () => api.getBook(id!),
    enabled: id !== null,
    refetchInterval: (query) => {
      // Poll the reader's open book while metadata extraction is in flight.
      // The chapters/paragraphs don't change between polls — we re-fetch
      // the whole detail because it's simple and the payload is small
      // enough that the round-trip cost beats adding a separate endpoint.
      const data = query.state.data;
      if (!data) return false;
      if (data.metadata_status === "pending") return METADATA_POLL_INTERVAL_MS;
      if (data.glossary_extraction_status === "running") return METADATA_POLL_INTERVAL_MS;
      if (data.speakers_extraction_status === "running") return METADATA_POLL_INTERVAL_MS;
      if (data.voice_extraction_status === "running") return METADATA_POLL_INTERVAL_MS;
      return false;
    },
  });
}

export function useGlossaryExtractionEstimate(
  id: string | null,
  enabled: boolean,
  model?: string,
): UseQueryResult<GlossaryExtractionEstimate, Error> {
  return useQuery({
    queryKey: id
      ? [...bookKeys.glossaryEstimate(id), model ?? null]
      : ["books", "glossary-estimate", "none"],
    queryFn: () => api.getGlossaryExtractionEstimate(id!, model),
    enabled: id !== null && enabled,
  });
}

export function useVoiceExtractionEstimate(
  id: string | null,
  enabled: boolean,
  models?: { speakers?: string; voices?: string },
): UseQueryResult<VoiceExtractionEstimate, Error> {
  return useQuery({
    queryKey: id
      ? [...bookKeys.voiceEstimate(id), models?.speakers ?? null, models?.voices ?? null]
      : ["books", "voice-estimate", "none"],
    queryFn: () => api.getVoiceExtractionEstimate(id!, models?.speakers, models?.voices),
    enabled: id !== null && enabled,
  });
}

export function useWorkingGlossary(
  bookId: string,
  opts: { enabled: boolean; refetchIntervalMs: number | false },
): UseQueryResult<WorkingGlossaryResponse, Error> {
  return useQuery({
    queryKey: bookKeys.workingGlossary(bookId),
    queryFn: () => api.getWorkingGlossary(bookId),
    enabled: opts.enabled,
    refetchInterval: opts.refetchIntervalMs === false ? false : opts.refetchIntervalMs,
  });
}

/** The model picked for one run; nothing means the configured default. */
export type ModelChoice = string | void;

/** Models per pipeline step, with the recommended one. Rarely changes. */
export function useModelCatalog(): UseQueryResult<ModelCatalog, Error> {
  return useQuery({
    queryKey: ["models"],
    queryFn: api.listModels,
    staleTime: Infinity,
  });
}

/** Tokens and cost of the LLM review of the pending glossary terms. */
export function useGlossaryReviewEstimate(
  bookId: string,
  model: string | undefined,
  enabled: boolean,
): UseQueryResult<GlossaryReviewEstimate, Error> {
  return useQuery({
    queryKey: [...bookKeys.workingGlossary(bookId), "review-estimate", model ?? null],
    queryFn: () => api.getGlossaryReviewEstimate(bookId, model),
    enabled,
  });
}

/** Mark a stage as finished by hand, or unmark it. */
export function useSetStageFinished(
  bookId: string,
): UseMutationResult<BookDetail, Error, { stage: MarkableStage; finished: boolean }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ stage, finished }) => api.setStageFinished(bookId, stage, finished),
    onSuccess: (book) => {
      qc.setQueryData(bookKeys.detail(bookId), book);
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
    },
  });
}

/** Let the LLM decide the pending glossary terms; the author checks them afterwards. */
export function useReviewPendingGlossaryTerms(
  bookId: string,
): UseMutationResult<GlossaryReviewResult, Error, ModelChoice> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (model) => api.reviewPendingGlossaryTerms(bookId, model || undefined),
    // Returned so callers' onSuccess runs once the glossary has refetched.
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) }),
        qc.invalidateQueries({ queryKey: bookKeys.translationTerms(bookId) }),
      ]),
  });
}

/** Confirm every automatic glossary decision that is still unconfirmed. */
export function useConfirmAutoGlossaryReviews(
  bookId: string,
): UseMutationResult<{ confirmed: number }, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.confirmAutoGlossaryReviews(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
    },
  });
}

export function usePatchGlossaryWorkingEntry(
  bookId: string,
): UseMutationResult<
  GlossaryWorkingEntry,
  Error,
  { entryId: string; body: GlossaryEntryPatchBody }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, body }) => api.patchGlossaryWorkingEntry(bookId, entryId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.translationTerms(bookId) });
    },
  });
}

export function useUploadBook(): UseMutationResult<UploadBookResponse, Error, File> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.uploadBook,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
    },
  });
}

export function useDeleteBook(): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteBook,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
    },
  });
}

export function useStartGlossaryExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.startGlossaryExtraction(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
    },
  });
}

export function useContinueGlossaryExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.continueGlossaryExtraction(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
    },
  });
}

/** Read the manuscript again and add missing terms to the current glossary. */
export function useExpandGlossary(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.expandGlossary(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
    },
  });
}

export function useGlossaryImportSources(
  bookId: string,
  enabled: boolean,
): UseQueryResult<GlossaryImportSource[], Error> {
  return useQuery({
    queryKey: bookKeys.glossaryImportSources(bookId),
    queryFn: () => api.getGlossaryImportSources(bookId),
    enabled,
  });
}

export function useImportGlossary(
  bookId: string,
): UseMutationResult<GlossaryImportResult, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceBookId: string) => api.importGlossary(bookId, sourceBookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.translationTerms(bookId) });
    },
  });
}

export function useStopGlossaryExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStopResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.stopGlossaryExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
    },
  });
}

export function useWorkingSpeakers(
  bookId: string,
  opts: { enabled: boolean; refetchIntervalMs: number | false },
): UseQueryResult<WorkingSpeakersResponse, Error> {
  return useQuery({
    queryKey: bookKeys.workingSpeakers(bookId),
    queryFn: () => api.getWorkingSpeakers(bookId),
    enabled: opts.enabled,
    refetchInterval: opts.refetchIntervalMs === false ? false : opts.refetchIntervalMs,
  });
}

export function useDialogueLines(
  bookId: string,
  speakerId: string | null,
  enabled: boolean,
): UseQueryResult<DialogueLinesResponse, Error> {
  return useQuery({
    queryKey: bookKeys.dialogueLines(bookId, speakerId),
    queryFn: () => api.getDialogueLines(bookId, speakerId),
    enabled,
  });
}

/** Speaker of every dialogue line, for marking the manuscript. */
export function useManuscriptSpeakers(
  bookId: string,
  opts: { enabled: boolean; refetchIntervalMs: number | false },
): UseQueryResult<ManuscriptSpeakersResponse, Error> {
  return useQuery({
    queryKey: bookKeys.manuscriptSpeakers(bookId),
    queryFn: () => api.getManuscriptSpeakers(bookId),
    enabled: opts.enabled,
    refetchInterval: opts.refetchIntervalMs,
  });
}

/**
 * Whose POV each scene follows. Read from the text, so it is there from
 * upload; refreshed with the glossary, whose characters the names are
 * matched to.
 */
export function useManuscriptNarration(
  bookId: string,
): UseQueryResult<NarrationPovResponse, Error> {
  return useQuery({
    queryKey: bookKeys.manuscriptNarration(bookId),
    queryFn: () => api.getManuscriptNarration(bookId),
    staleTime: 60_000,
  });
}

export function useWorkingVoices(
  bookId: string,
  opts: { enabled: boolean; refetchIntervalMs: number | false },
): UseQueryResult<WorkingVoicesResponse, Error> {
  return useQuery({
    queryKey: bookKeys.workingVoices(bookId),
    queryFn: () => api.getWorkingVoices(bookId),
    enabled: opts.enabled,
    refetchInterval: opts.refetchIntervalMs === false ? false : opts.refetchIntervalMs,
  });
}

export function usePatchVoiceWorkingProfile(
  bookId: string,
): UseMutationResult<VoiceWorkingProfile, Error, { voiceId: string; body: VoiceProfilePatchBody }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ voiceId, body }) => api.patchVoiceWorkingProfile(bookId, voiceId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useStartVoiceExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.startVoiceExtraction(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useContinueVoiceExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.continueVoiceExtraction(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useRegenerateFlaggedVoices(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.regenerateFlaggedVoices(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useRunVoiceCastPass(
  bookId: string,
): UseMutationResult<
  GlossaryExtractionStartResponse,
  Error,
  (RunOptions & { rebuildBriefs?: boolean }) | void
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.runVoiceCastPass(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
    },
  });
}

export function useStopVoiceExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStopResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.stopVoiceExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useResetVoiceExtraction(bookId: string): UseMutationResult<void, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetVoiceExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useStartSpeakersExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.startSpeakersExtraction(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingSpeakers(bookId) });
    },
  });
}

export function useContinueSpeakersExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.continueSpeakersExtraction(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingSpeakers(bookId) });
    },
  });
}

export function useStopSpeakersExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStopResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.stopSpeakersExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingSpeakers(bookId) });
    },
  });
}

export function useResetSpeakersExtraction(bookId: string): UseMutationResult<void, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetSpeakersExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingSpeakers(bookId) });
    },
  });
}

// ─── Translation (Step 5) ───────────────────────────────

const TRANSLATION_POLL_INTERVAL_MS = 2000;

export function useTranslation(bookId: string): UseQueryResult<TranslationView, Error> {
  return useQuery({
    queryKey: bookKeys.translation(bookId),
    queryFn: () => api.getTranslation(bookId),
    refetchInterval: (query) =>
      query.state.data?.run?.status === "running" ? TRANSLATION_POLL_INTERVAL_MS : false,
  });
}

export function useTranslationEstimate(
  bookId: string,
  chapterIds: string[] | null,
  model?: string,
): UseQueryResult<TranslationEstimate, Error> {
  return useQuery({
    queryKey: [...bookKeys.translationEstimate(bookId, chapterIds), model ?? null],
    queryFn: () => api.getTranslationEstimate(bookId, chapterIds, model),
  });
}

export function useStartTranslation(
  bookId: string,
): UseMutationResult<TranslationRun, Error, StartTranslationBody> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.startTranslation(bookId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.translation(bookId) });
    },
  });
}

export function useContinueTranslation(
  bookId: string,
): UseMutationResult<TranslationRun, Error, RunOptions | void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts) => api.continueTranslation(bookId, opts || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.translation(bookId) });
    },
  });
}

export function useStopTranslation(bookId: string): UseMutationResult<void, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.stopTranslation(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.translation(bookId) });
    },
  });
}

/** Glossary terms found in the source paragraphs; refreshed when the glossary changes. */
export function useTranslationTerms(bookId: string): UseQueryResult<TranslationTerms, Error> {
  return useQuery({
    queryKey: bookKeys.translationTerms(bookId),
    queryFn: () => api.getTranslationTerms(bookId),
    staleTime: 60_000,
  });
}

/** Glossary terms in the source, pending ones included, for the manuscript. */
export function useManuscriptTerms(
  bookId: string,
  opts: { enabled: boolean; refetchIntervalMs: number | false },
): UseQueryResult<TranslationTerms, Error> {
  return useQuery({
    queryKey: bookKeys.manuscriptTerms(bookId),
    queryFn: () => api.getTranslationTerms(bookId, true),
    enabled: opts.enabled,
    refetchInterval: opts.refetchIntervalMs,
    staleTime: 30_000,
  });
}
