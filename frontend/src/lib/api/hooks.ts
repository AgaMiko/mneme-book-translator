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
  type GlossaryEntryPatchBody,
  type GlossaryExtractionEstimate,
  type GlossaryExtractionStartResponse,
  type GlossaryExtractionStopResponse,
  type GlossaryWorkingEntry,
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
  workingVoices: (id: string) => [...bookKeys.all, "working-voices", id] as const,
  workingSpeakers: (id: string) => [...bookKeys.all, "working-speakers", id] as const,
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
): UseQueryResult<GlossaryExtractionEstimate, Error> {
  return useQuery({
    queryKey: id ? bookKeys.glossaryEstimate(id) : ["books", "glossary-estimate", "none"],
    queryFn: () => api.getGlossaryExtractionEstimate(id!),
    enabled: id !== null && enabled,
  });
}

export function useVoiceExtractionEstimate(
  id: string | null,
  enabled: boolean,
): UseQueryResult<VoiceExtractionEstimate, Error> {
  return useQuery({
    queryKey: id ? bookKeys.voiceEstimate(id) : ["books", "voice-estimate", "none"],
    queryFn: () => api.getVoiceExtractionEstimate(id!),
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
    },
  });
}

export function useUploadBook(): UseMutationResult<
  UploadBookResponse,
  Error,
  { file: File; sourceLanguage?: string }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, sourceLanguage }) => api.uploadBook(file, sourceLanguage),
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
): UseMutationResult<GlossaryExtractionStartResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.startGlossaryExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
    },
  });
}

export function useContinueGlossaryExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.continueGlossaryExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingGlossary(bookId) });
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
): UseMutationResult<GlossaryExtractionStartResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.startVoiceExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useContinueVoiceExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.continueVoiceExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
    },
  });
}

export function useRegenerateFlaggedVoices(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.regenerateFlaggedVoices(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingVoices(bookId) });
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
): UseMutationResult<GlossaryExtractionStartResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.startSpeakersExtraction(bookId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: bookKeys.detail(bookId) });
      void qc.invalidateQueries({ queryKey: bookKeys.lists() });
      void qc.invalidateQueries({ queryKey: bookKeys.workingSpeakers(bookId) });
    },
  });
}

export function useContinueSpeakersExtraction(
  bookId: string,
): UseMutationResult<GlossaryExtractionStartResponse, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.continueSpeakersExtraction(bookId),
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
