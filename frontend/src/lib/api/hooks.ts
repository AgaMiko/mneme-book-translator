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
  type GlossaryExtractionEstimate,
  type GlossaryExtractionStartResponse,
  type GlossaryExtractionStopResponse,
  type UploadBookResponse,
  type WorkingGlossaryResponse,
} from "./client";

// Query key factory — all cache invalidation flows through here.
export const bookKeys = {
  all: ["books"] as const,
  lists: () => [...bookKeys.all, "list"] as const,
  detail: (id: string) => [...bookKeys.all, "detail", id] as const,
  glossaryEstimate: (id: string) => [...bookKeys.all, "glossary-estimate", id] as const,
  workingGlossary: (id: string) => [...bookKeys.all, "working-glossary", id] as const,
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
      return anyPending || anyGlossary ? METADATA_POLL_INTERVAL_MS : false;
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

export function useWorkingGlossary(
  bookId: string,
  opts: { enabled: boolean; refetchIntervalMs: number | false },
): UseQueryResult<WorkingGlossaryResponse, Error> {
  return useQuery({
    queryKey: bookKeys.workingGlossary(bookId),
    queryFn: () => api.getWorkingGlossary(bookId),
    enabled: opts.enabled,
    refetchInterval:
      opts.refetchIntervalMs === false ? false : opts.refetchIntervalMs,
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
