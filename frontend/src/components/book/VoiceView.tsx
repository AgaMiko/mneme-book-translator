import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, type ReactNode } from "react";

import {
  VOICE_EXTRACTION_OVERLAP_WORDS,
  VOICE_EXTRACTION_WINDOW_WORDS,
} from "@/constants/voiceExtraction";
import type { BookDetail, VoiceWorkingProfile, WorkingSpeakersResponse } from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import {
  bookKeys,
  useContinueSpeakersExtraction,
  useContinueVoiceExtraction,
  usePatchVoiceWorkingProfile,
  useResetSpeakersExtraction,
  useResetVoiceExtraction,
  useStartSpeakersExtraction,
  useStartVoiceExtraction,
  useStopSpeakersExtraction,
  useStopVoiceExtraction,
  useWorkingSpeakers,
  useWorkingVoices,
} from "@/lib/api/hooks";
import { cn, formatNumber, formatRelativeDate } from "@/lib/utils";

interface Props {
  book: BookDetail;
}

function formatWindowList(windows: number[], maxVisible = 28): string {
  if (windows.length === 0) return "—";
  if (windows.length <= maxVisible) return windows.join(", ");
  return `${windows.slice(0, maxVisible).join(", ")} … +${windows.length - maxVisible}`;
}

function SpeakerMapPanel({
  book,
  speakers,
}: {
  book: BookDetail;
  speakers: UseQueryResult<WorkingSpeakersResponse, Error>;
}) {
  const done = book.speakers_extraction_windows_completed;
  const total = book.speakers_extraction_windows_total;
  const progress =
    book.speakers_extraction_status === "running" && total != null && total > 0
      ? ` · scanning window ${done ?? 0}/${total}`
      : "";

  if (speakers.isLoading && !speakers.data) {
    return (
      <p className="mt-4 text-sm text-ink-400" aria-busy="true">
        Loading speaker map…
      </p>
    );
  }
  if (speakers.isError) {
    return <p className="mt-4 text-sm text-danger">Could not load speaker map.</p>;
  }
  if (!speakers.data || speakers.data.entries.length === 0) {
    return (
      <p className="mt-4 text-sm text-ink-500">
        {book.speakers_extraction_status === "running"
          ? `Waiting for first window…${progress}`
          : "No speakers mapped yet."}
      </p>
    );
  }

  const { entries, windows_mapped, edges_total } = speakers.data;

  return (
    <div className="mt-4">
      <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
        {entries.length} character{entries.length === 1 ? "" : "s"} · {windows_mapped} window
        {windows_mapped === 1 ? "" : "s"} · {edges_total} appearance
        {edges_total === 1 ? "" : "s"}
        {progress}
      </p>
      <ul
        className="mt-3 max-h-72 space-y-2 overflow-y-auto rounded-md border border-ink-800/80 bg-ink-900/40 p-2"
        aria-live="polite"
        aria-label="Characters and window numbers where they speak"
      >
        {entries.map((entry) => (
          <li
            key={entry.glossary_entry_id}
            className="grid gap-1 rounded px-2 py-1.5 text-sm sm:grid-cols-[minmax(8rem,11rem)_1fr]"
          >
            <span className="font-medium text-ink-100">{entry.canonical_name}</span>
            <span className="font-mono text-xs leading-relaxed text-ink-400">
              {formatWindowList(entry.windows)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
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
  speakerWindows,
  onAccept,
  onReject,
}: {
  v: VoiceWorkingProfile;
  book: BookDetail;
  patchPending: boolean;
  speakerWindows?: number[];
  onAccept: () => void;
  onReject: () => void;
}) {
  const selected = v.selected_passages ?? [];
  const hasMulti = selected.length > 0;
  const showLegacyOnly = !hasMulti && v.reference_passage_source.trim().length > 0;
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
            {v.status} · voice windows {v.first_seen_window}→{v.last_observed_window}
            {hasMulti
              ? ` · ${selected.length} reference passage${selected.length === 1 ? "" : "es"}`
              : ` · dialogue scans ${formatNumber(v.dialogue_volume_observed)}`}
          </p>
          {speakerWindows && speakerWindows.length > 0 ? (
            <p className="mt-1 font-mono text-[10px] leading-relaxed text-accent/90">
              speaks in windows {formatWindowList(speakerWindows)}
            </p>
          ) : null}
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

      <ProfileBlock label="Source voice observation">{v.source_voice_observation}</ProfileBlock>
      <ProfileBlock label="Target voice strategy">{v.target_voice_strategy}</ProfileBlock>

      {hasMulti ? (
        <div className="mt-4 space-y-6">
          {selected
            .slice()
            .sort((a, b) => a.selection_rank - b.selection_rank)
            .map((p, i) => {
              const pos = i + 1;
              const prop = p.translation_proposed?.trim() ?? "";
              const auth = p.translation_authoritative;
              const same = auth != null && auth.trim() === prop;
              return (
                <div key={p.id} className="rounded-md border border-ink-800/80 bg-ink-900/25 p-3">
                  <p className="font-mono text-[10px] uppercase tracking-wider text-accent">
                    Reference passage {pos} of {selected.length}
                    {p.selection_rank > 0 ? ` · rank ${p.selection_rank}` : ""} · {p.status}
                  </p>
                  <p className="mt-1 text-[10px] leading-relaxed text-ink-500">{p.why_selected}</p>
                  <ProfileBlock label={`Source (${book.source_language})`} className="!mt-2">
                    <p className="whitespace-pre-wrap border-l-2 border-ink-600 pl-3 text-ink-200">
                      {p.source_text}
                    </p>
                  </ProfileBlock>
                  <ProfileBlock
                    label={`Model translation (${book.target_language})`}
                    className="!mt-2"
                  >
                    <p className="whitespace-pre-wrap leading-relaxed text-ink-200">
                      {p.translation_proposed ?? "—"}
                    </p>
                  </ProfileBlock>
                  {auth != null && auth !== "" ? (
                    <ProfileBlock label="Final translation (for downstream use)" className="!mt-2">
                      <p className="whitespace-pre-wrap leading-relaxed text-ink-100">{auth}</p>
                      {same && prop ? (
                        <p className="mt-2 text-[10px] font-mono text-ink-500">
                          Same as model draft.
                        </p>
                      ) : null}
                    </ProfileBlock>
                  ) : (
                    <p className="mt-2 text-[10px] text-ink-500">
                      No final translation for this passage yet (accept the profile to lock the
                      model draft on all passages, or reject).
                    </p>
                  )}
                </div>
              );
            })}
        </div>
      ) : showLegacyOnly ? (
        <>
          <ProfileBlock label={`Reference passage — source (${book.source_language})`}>
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
              No authoritative translation yet — accept the profile to lock in the model draft, or
              reject to dismiss the profile.
            </p>
          )}
        </>
      ) : (
        <p className="mt-3 rounded border border-ink-800/80 bg-ink-900/30 px-3 py-2 text-xs text-ink-500">
          No selected reference passages yet. They appear after the selection and translation steps
          of the voice pipeline finish (1–4 per character from the candidate pool).
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
  const glossaryReady = book.glossary_extraction_status === "completed";
  const speakersPoll =
    book.speakers_extraction_status === "running" || book.voice_extraction_status === "running";
  const speakers = useWorkingSpeakers(book.id, {
    enabled:
      glossaryReady &&
      (book.speakers_extraction_status !== "idle" ||
        (book.speakers_extraction_windows_completed ?? 0) > 0),
    refetchIntervalMs: speakersPoll ? 1500 : false,
  });
  const voices = useWorkingVoices(book.id, {
    enabled: glossaryReady,
    refetchIntervalMs: book.voice_extraction_status === "running" ? 1500 : false,
  });
  const speakerWindowsByGlossaryId = useMemo(() => {
    const map = new Map<string, number[]>();
    for (const e of speakers.data?.entries ?? []) {
      map.set(e.glossary_entry_id, e.windows);
    }
    return map;
  }, [speakers.data?.entries]);
  const startSpeakers = useStartSpeakersExtraction(book.id);
  const continueSpeakers = useContinueSpeakersExtraction(book.id);
  const stopSpeakers = useStopSpeakersExtraction(book.id);
  const resetSpeakers = useResetSpeakersExtraction(book.id);
  const startVoice = useStartVoiceExtraction(book.id);
  const continueVoice = useContinueVoiceExtraction(book.id);
  const stopVoice = useStopVoiceExtraction(book.id);
  const resetVoice = useResetVoiceExtraction(book.id);
  const patchVoice = usePatchVoiceWorkingProfile(book.id);

  const prevVoice = useRef<string | null>(null);
  const prevSpeakers = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevVoice.current;
    prevVoice.current = book.voice_extraction_status;
    if (prev === "running" && book.voice_extraction_status !== "running") {
      void queryClient.invalidateQueries({ queryKey: bookKeys.workingVoices(book.id) });
    }
  }, [book.voice_extraction_status, book.id, queryClient]);
  useEffect(() => {
    const prev = prevSpeakers.current;
    prevSpeakers.current = book.speakers_extraction_status;
    if (prev === "running" && book.speakers_extraction_status !== "running") {
      void queryClient.invalidateQueries({ queryKey: bookKeys.workingSpeakers(book.id) });
    }
  }, [book.speakers_extraction_status, book.id, queryClient]);

  const actionEnabled = book.word_count > 0 && book.glossary_extraction_status === "completed";
  const speakersIncomplete = book.speakers_extraction_status !== "completed";
  const nothingToResetSpeakers =
    book.speakers_extraction_status === "idle" && !book.speakers_extraction_last_error;
  const nothingToResetVoice =
    book.voice_extraction_status === "idle" &&
    !book.voice_extraction_last_error &&
    voices.isSuccess &&
    voices.data.entries.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="reader-surface flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-6 py-10">
          <div className="space-y-5">
            <div>
              <h2 className="font-serif text-xl font-medium text-ink-50">Character voices</h2>
              <p className="mt-1 max-w-xl text-sm leading-relaxed text-ink-500">
                Two passes over the same windows (~{formatNumber(VOICE_EXTRACTION_WINDOW_WORDS)}{" "}
                words, ~{formatNumber(VOICE_EXTRACTION_OVERLAP_WORDS)} overlap).{" "}
                <strong className="text-ink-400">Pass 1</strong> maps which glossary characters have
                quoted speech in each window. <strong className="text-ink-400">Pass 2</strong>{" "}
                builds voice profiles, then <strong className="text-ink-400">selects</strong> and{" "}
                <strong className="text-ink-400">translates</strong> reference passages. Review
                profiles below.
              </p>
            </div>

            <div className="rounded-lg border border-ink-800 bg-ink-850/30 p-4">
              <h3 className="font-mono text-[10px] uppercase tracking-wider text-ink-400">
                Pass 1 · Speaker identification
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-500">
                For each window, list glossary characters with at least one quoted speaking line and
                a verbatim phrase as evidence. POV narration counts when the narrative voice is
                clearly theirs. This map scopes Pass 2 and later translation prompts.
              </p>

              {book.speakers_extraction_last_error &&
                book.speakers_extraction_status !== "running" && (
                  <p className="mt-3 rounded-md border border-danger-border bg-danger-surface px-3 py-2 text-sm text-danger">
                    {book.speakers_extraction_last_error}
                  </p>
                )}

              {book.speakers_extraction_status === "completed" && (
                <p className="mt-3 rounded-md border border-success-border bg-success-surface px-3 py-2 text-sm text-success">
                  Speaker map complete. You can run Pass 2 below.
                </p>
              )}

              {startSpeakers.isError && (
                <p className="mt-3 text-sm text-danger">
                  {startSpeakers.error instanceof ApiError
                    ? startSpeakers.error.detail
                    : "Could not start speaker identification."}
                </p>
              )}
              {continueSpeakers.isError && (
                <p className="mt-3 text-sm text-danger">
                  {continueSpeakers.error instanceof ApiError
                    ? continueSpeakers.error.detail
                    : "Could not continue speaker identification."}
                </p>
              )}
              {stopSpeakers.isError && (
                <p className="mt-3 text-sm text-danger">
                  {stopSpeakers.error instanceof ApiError
                    ? stopSpeakers.error.detail
                    : "Could not request stop."}
                </p>
              )}
              {resetSpeakers.isError && (
                <p className="mt-3 text-sm text-danger">
                  {resetSpeakers.error instanceof ApiError
                    ? resetSpeakers.error.detail
                    : "Could not reset speaker data."}
                </p>
              )}

              <SpeakerMapPanel book={book} speakers={speakers} />
            </div>

            {book.glossary_extraction_status !== "completed" && (
              <p className="text-sm text-warning">
                Finish glossary extraction first; voices need at least one character entry.
              </p>
            )}

            {book.voice_extraction_last_error && book.voice_extraction_status !== "running" && (
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
            {resetVoice.isError && (
              <p className="text-sm text-danger">
                {resetVoice.error instanceof ApiError
                  ? resetVoice.error.detail
                  : "Could not reset voice data."}
              </p>
            )}

            <button
              type="button"
              onClick={() =>
                listRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
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
                speakerWindows={speakerWindowsByGlossaryId.get(v.glossary_entry_id)}
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
            "sticky bottom-0 z-10 w-full min-w-0 border-t border-ink-800 bg-ink-900/95 px-4 py-3 backdrop-blur-sm",
          )}
        >
          <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-2 border-b border-ink-800/80 pb-2.5">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Pass 1 · Speakers
            </p>
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
              {book.speakers_extraction_status !== "running" && (
                <button
                  type="button"
                  disabled={nothingToResetSpeakers || resetSpeakers.isPending}
                  title={nothingToResetSpeakers ? "No speaker data to clear." : undefined}
                  onClick={() => {
                    if (
                      !window.confirm(
                        "This will delete the per-window speaker map and Pass 1 notepad for this book. You can run identification again afterward. Continue?",
                      )
                    ) {
                      return;
                    }
                    resetSpeakers.mutate();
                  }}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-md border border-danger-border px-3 py-1.5",
                    "font-mono text-xs uppercase tracking-wider text-danger",
                    "hover:bg-danger-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger",
                    "disabled:cursor-not-allowed disabled:opacity-40",
                  )}
                >
                  {resetSpeakers.isPending ? "Resetting…" : "Reset"}
                </button>
              )}
              {book.speakers_extraction_status === "running" && (
                <button
                  type="button"
                  disabled={stopSpeakers.isPending}
                  onClick={() => stopSpeakers.mutate()}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-md border border-ink-600 px-3 py-1.5",
                    "font-mono text-xs uppercase tracking-wider text-ink-200",
                    "hover:border-danger-border hover:bg-danger-surface hover:text-danger",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger",
                    "disabled:cursor-not-allowed disabled:opacity-40",
                  )}
                >
                  {stopSpeakers.isPending ? "Stopping…" : "Stop"}
                </button>
              )}
              {(book.speakers_extraction_status === "failed" ||
                book.speakers_extraction_status === "cancelled") && (
                <button
                  type="button"
                  disabled={continueSpeakers.isPending}
                  onClick={() => continueSpeakers.mutate()}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-md border border-success-border px-3 py-1.5",
                    "font-mono text-xs uppercase tracking-wider text-success",
                    "hover:bg-success-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success",
                    "disabled:cursor-not-allowed disabled:opacity-40",
                  )}
                >
                  {continueSpeakers.isPending ? "Continuing…" : "Continue"}
                </button>
              )}
              <button
                type="button"
                disabled={book.speakers_extraction_status === "running" || startSpeakers.isPending}
                onClick={() => startSpeakers.mutate()}
                className={cn(
                  "inline-flex items-center gap-2 rounded-md border border-accent px-3 py-1.5",
                  "font-mono text-xs uppercase tracking-wider text-accent",
                  "bg-accent-soft hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  "disabled:cursor-not-allowed disabled:opacity-40",
                )}
              >
                {book.speakers_extraction_status === "running"
                  ? "Running…"
                  : startSpeakers.isPending
                    ? "Starting…"
                    : book.speakers_extraction_status === "completed"
                      ? "Re-run Pass 1"
                      : "Start Pass 1"}
              </button>
            </div>
          </div>

          <div className="mt-2.5 flex w-full min-w-0 flex-col gap-2">
            {speakersIncomplete && book.voice_extraction_status !== "running" && (
              <p className="text-center text-xs text-warning sm:text-left">
                Speaker identification is not complete — Pass 2 will use the full glossary character
                list per window until you finish Pass 1.
              </p>
            )}
            <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-2">
              <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                Pass 2 · Voices
              </p>
              <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                {book.voice_extraction_status !== "running" && (
                  <button
                    type="button"
                    disabled={nothingToResetVoice || resetVoice.isPending}
                    title={nothingToResetVoice ? "No voice data to clear." : undefined}
                    onClick={() => {
                      if (
                        !window.confirm(
                          "This will permanently delete all character voice profiles, the extraction notepad, and your review progress (accept/reject) for this book. You can run extraction again afterward. This cannot be undone. Continue?",
                        )
                      ) {
                        return;
                      }
                      resetVoice.mutate();
                    }}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-md border border-danger-border px-3 py-1.5",
                      "font-mono text-xs uppercase tracking-wider text-danger",
                      "hover:bg-danger-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger",
                      "disabled:cursor-not-allowed disabled:opacity-40",
                    )}
                  >
                    {resetVoice.isPending ? "Resetting…" : "Reset"}
                  </button>
                )}
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
                      : "Start Pass 2"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
