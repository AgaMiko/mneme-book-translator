import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";

import {
  GLOSSARY_EXTRACTION_OVERLAP_WORDS,
  GLOSSARY_EXTRACTION_WINDOW_WORDS,
} from "@/constants/glossaryExtraction";
import type { BookDetail, VoiceWorkingProfile } from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import {
  bookKeys,
  useContinueVoiceExtraction,
  usePatchVoiceWorkingProfile,
  useStartVoiceExtraction,
  useStopVoiceExtraction,
  useWorkingVoices,
} from "@/lib/api/hooks";
import { cn, formatNumber, formatRelativeDate } from "@/lib/utils";

interface Props {
  book: BookDetail;
}

function ProfileBlock({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mt-3", className)}>
      <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">{label}</p>
      <div className="mt-1.5 leading-relaxed text-ink-300">{children}</div>
    </div>
  );
}

function VoiceProfileCard({
  v,
  book,
  patchPending,
  onAccept,
  onReject,
}: {
  v: VoiceWorkingProfile;
  book: BookDetail;
  patchPending: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  const sameTranslation =
    v.reference_passage_translation_authoritative != null &&
    v.reference_passage_translation_authoritative.trim() ===
      v.reference_passage_translation_proposed.trim();

  return (
    <article className="rounded-lg border border-ink-800 bg-ink-850/40 p-4 text-sm text-ink-200">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-serif text-base font-medium text-ink-50">{v.canonical_name}</p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink-500">
            {v.status} · windows {v.first_seen_window}→{v.last_observed_window} · dialogue scans{" "}
            {formatNumber(v.dialogue_volume_observed)}
          </p>
          <p className="mt-1.5 break-all font-mono text-[10px] leading-relaxed text-ink-600">
            glossary entry · {v.glossary_entry_id}
          </p>
          <p className="mt-1 font-mono text-[10px] text-ink-600">
            created {formatRelativeDate(v.created_at)} · updated {formatRelativeDate(v.updated_at)}
          </p>
        </div>
        <div className="flex flex-shrink-0 flex-wrap gap-2">
          <button
            type="button"
            disabled={patchPending || v.status === "accepted"}
            onClick={onAccept}
            className={cn(
              "rounded border border-success-border px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-success",
              "hover:bg-success-surface disabled:opacity-40",
            )}
          >
            Accept
          </button>
          <button
            type="button"
            disabled={patchPending || v.status === "rejected"}
            onClick={onReject}
            className={cn(
              "rounded border border-danger-border px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-danger",
              "hover:bg-danger-surface disabled:opacity-40",
            )}
          >
            Reject
          </button>
        </div>
      </div>

      <ProfileBlock label="Voice summary">{v.voice_summary}</ProfileBlock>

      <ProfileBlock
        label={`Reference passage — source (${book.source_language})`}
      >
        <p className="whitespace-pre-wrap border-l-2 border-ink-600 pl-3 text-ink-200">
          {v.reference_passage_source}
        </p>
      </ProfileBlock>

      <ProfileBlock label={`Translation — model (${book.target_language})`}>
        <p className="whitespace-pre-wrap leading-relaxed text-ink-200">
          {v.reference_passage_translation_proposed}
        </p>
      </ProfileBlock>

      {v.reference_passage_translation_authoritative != null ? (
        <ProfileBlock label="Translation — final (for downstream use)">
          <p className="whitespace-pre-wrap leading-relaxed text-ink-100">
            {v.reference_passage_translation_authoritative}
          </p>
          {sameTranslation ? (
            <p className="mt-2 text-[10px] font-mono text-ink-500">Same as model draft.</p>
          ) : (
            <p className="mt-2 text-[10px] font-mono text-ink-500">
              Differs from model draft — your edits or accept workflow set this.
            </p>
          )}
        </ProfileBlock>
      ) : (
        <p className="mt-3 rounded border border-ink-800/80 bg-ink-900/30 px-3 py-2 text-xs text-ink-500">
          No authoritative translation yet — accept the profile to lock in the model
          draft, or reject to dismiss the profile.
        </p>
      )}
    </article>
  );
}

/**
 * Voice extraction and review: same overlapping windows as the glossary pass,
 * but profiles attach only to glossary characters.
 */
export function VoiceView({ book }: Props) {
  const queryClient = useQueryClient();
  const listRef = useRef<HTMLDivElement | null>(null);
  const voices = useWorkingVoices(book.id, {
    enabled: book.glossary_extraction_status === "completed",
    refetchIntervalMs: book.voice_extraction_status === "running" ? 1500 : false,
  });
  const startVoice = useStartVoiceExtraction(book.id);
  const continueVoice = useContinueVoiceExtraction(book.id);
  const stopVoice = useStopVoiceExtraction(book.id);
  const patchVoice = usePatchVoiceWorkingProfile(book.id);

  const prevVoice = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevVoice.current;
    prevVoice.current = book.voice_extraction_status;
    if (prev === "running" && book.voice_extraction_status !== "running") {
      void queryClient.invalidateQueries({ queryKey: bookKeys.workingVoices(book.id) });
    }
  }, [book.voice_extraction_status, book.id, queryClient]);

  const actionEnabled = book.word_count > 0 && book.glossary_extraction_status === "completed";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="reader-surface flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-6 py-10">
          <div className="space-y-5">
            <div>
              <h2 className="font-serif text-xl font-medium text-ink-50">Character voices</h2>
              <p className="mt-1 max-w-xl text-sm leading-relaxed text-ink-500">
                One pass per window (~{formatNumber(GLOSSARY_EXTRACTION_WINDOW_WORDS)} words, ~
                {formatNumber(GLOSSARY_EXTRACTION_OVERLAP_WORDS)} overlap) — same geometry as glossary. Each
                character gets a short <strong className="text-ink-400">voice summary</strong> and one{" "}
                <strong className="text-ink-400">reference passage</strong> (source + model translation) for
                you to review; nothing else to curate.
              </p>
            </div>

            {book.glossary_extraction_status !== "completed" && (
              <p className="text-sm text-warning">
                Finish glossary extraction first; voices need at least one character entry.
              </p>
            )}

            {book.voice_extraction_last_error &&
              book.voice_extraction_status !== "running" && (
                <p className="rounded-md border border-danger-border bg-danger-surface px-3 py-2 text-sm text-danger">
                  {book.voice_extraction_last_error}
                </p>
              )}

            {book.voice_extraction_status === "completed" && (
              <div className="rounded-md border border-success-border bg-success-surface px-3 py-2 text-sm text-success">
                Last voice run finished. Review profiles below.
              </div>
            )}

            {startVoice.isError && (
              <p className="text-sm text-danger">
                {startVoice.error instanceof ApiError
                  ? startVoice.error.detail
                  : "Could not start voice extraction."}
              </p>
            )}
            {continueVoice.isError && (
              <p className="text-sm text-danger">
                {continueVoice.error instanceof ApiError
                  ? continueVoice.error.detail
                  : "Could not continue voice extraction."}
              </p>
            )}
            {stopVoice.isError && (
              <p className="text-sm text-danger">
                {stopVoice.error instanceof ApiError
                  ? stopVoice.error.detail
                  : "Could not request stop."}
              </p>
            )}

            <button
              type="button"
              onClick={() => listRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
              className={cn(
                "rounded-md border border-ink-700 px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink-200",
                "hover:border-ink-600 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              )}
            >
              Jump to profiles ↓
            </button>
          </div>

          <div className="my-12 border-t border-ink-800" />

          <div ref={listRef} className="scroll-mt-6 space-y-6">
            <h3 className="font-serif text-lg text-ink-100">Profiles</h3>
            {voices.isLoading && (
              <p className="text-sm text-ink-400" aria-busy="true">
                Loading…
              </p>
            )}
            {voices.isError && (
              <p className="text-sm text-danger">Could not load voice profiles.</p>
            )}
            {voices.data && voices.data.entries.length === 0 && (
              <p className="text-sm text-ink-400">
                No profiles yet. Run extraction after glossary completes.
              </p>
            )}
            {voices.data?.entries.map((v) => (
              <VoiceProfileCard
                key={v.id}
                v={v}
                book={book}
                patchPending={patchVoice.isPending}
                onAccept={() => patchVoice.mutate({ voiceId: v.id, body: { accept: true } })}
                onReject={() => patchVoice.mutate({ voiceId: v.id, body: { reject: true } })}
              />
            ))}
          </div>
        </div>
      </div>

      {actionEnabled && (
        <div
          className={cn(
            "sticky bottom-0 z-10 flex flex-wrap items-center justify-end gap-2",
            "border-t border-ink-800 bg-ink-900/95 px-4 py-2.5 backdrop-blur-sm",
          )}
        >
          {book.voice_extraction_status === "running" && (
            <button
              type="button"
              disabled={stopVoice.isPending}
              onClick={() => stopVoice.mutate()}
              className={cn(
                "inline-flex items-center gap-2 rounded-md border border-ink-600 px-3 py-1.5",
                "font-mono text-xs uppercase tracking-wider text-ink-200",
                "hover:border-danger-border hover:bg-danger-surface hover:text-danger",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger",
                "disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              {stopVoice.isPending ? "Stopping…" : "Stop"}
            </button>
          )}
          {(book.voice_extraction_status === "failed" ||
            book.voice_extraction_status === "cancelled") && (
            <button
              type="button"
              disabled={continueVoice.isPending}
              onClick={() => continueVoice.mutate()}
              className={cn(
                "inline-flex items-center gap-2 rounded-md border border-success-border px-3 py-1.5",
                "font-mono text-xs uppercase tracking-wider text-success",
                "hover:bg-success-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success",
                "disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              {continueVoice.isPending ? "Continuing…" : "Continue"}
            </button>
          )}
          <button
            type="button"
            disabled={book.voice_extraction_status === "running" || startVoice.isPending}
            onClick={() => startVoice.mutate()}
            className={cn(
              "inline-flex items-center gap-2 rounded-md border border-accent px-3 py-1.5",
              "font-mono text-xs uppercase tracking-wider text-accent",
              "bg-accent-soft hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              "disabled:cursor-not-allowed disabled:opacity-40",
            )}
          >
            {book.voice_extraction_status === "running"
              ? "Running…"
              : startVoice.isPending
                ? "Starting…"
                : "Start extraction"}
          </button>
        </div>
      )}
    </div>
  );
}
