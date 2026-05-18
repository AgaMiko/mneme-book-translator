import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  VOICE_EXTRACTION_OVERLAP_WORDS,
  VOICE_EXTRACTION_WINDOW_WORDS,
} from "@/constants/voiceExtraction";
import type {
  BookDetail,
  VoiceProfilePatchBody,
  VoiceSelectedPassage,
  VoiceWorkingProfile,
  WorkingSpeakersResponse,
} from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import {
  bookKeys,
  useContinueSpeakersExtraction,
  useContinueVoiceExtraction,
  usePatchVoiceWorkingProfile,
  useRegenerateFlaggedVoices,
  useResetSpeakersExtraction,
  useResetVoiceExtraction,
  useStartSpeakersExtraction,
  useStartVoiceExtraction,
  useStopSpeakersExtraction,
  useStopVoiceExtraction,
  useVoiceExtractionEstimate,
  useWorkingSpeakers,
  useWorkingVoices,
} from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

interface Props {
  book: BookDetail;
}

function formatUsd(n: number): string {
  if (n > 0 && n < 0.01) return "under $0.01";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: n < 1 ? 3 : 2,
  }).format(n);
}

function formatWindowList(windows: number[], maxVisible = 28): string {
  if (windows.length === 0) return "—";
  if (windows.length <= maxVisible) return windows.join(", ");
  return `${windows.slice(0, maxVisible).join(", ")} … +${windows.length - maxVisible}`;
}

function isAwaitingVoiceReview(v: VoiceWorkingProfile): boolean {
  return v.status === "proposed" || v.status === "adjusted";
}

function ReviewProgressLine({
  awaiting,
  accepted,
  rejected,
}: {
  awaiting: number;
  accepted: number;
  rejected: number;
}) {
  if (awaiting + accepted + rejected === 0) return null;
  return (
    <div className="mt-2.5 flex flex-wrap gap-2">
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-mono text-[11px] tabular-nums",
          awaiting > 0
            ? "border-accent/35 bg-accent-soft/50 text-accent"
            : "border-ink-700/80 bg-ink-900/50 text-ink-500",
        )}
      >
        {awaiting} pending
      </span>
      <span className="inline-flex items-center gap-1 rounded-full border border-ink-700/80 bg-ink-900/40 px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-ink-300">
        {accepted} accepted
      </span>
      {rejected > 0 ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-ink-700/80 bg-ink-950/60 px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-ink-500">
          {rejected} rejected
        </span>
      ) : null}
    </div>
  );
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

function PassageBlock({
  passage,
  pos,
  total,
  book,
  patchPending,
  onPatch,
}: {
  passage: VoiceSelectedPassage;
  pos: number;
  total: number;
  book: BookDetail;
  patchPending: boolean;
  onPatch: (body: VoiceProfilePatchBody) => void;
}) {
  const initialTranslation =
    passage.translation_authoritative?.trim() || passage.translation_proposed?.trim() || "";
  const [draftTranslation, setDraftTranslation] = useState(initialTranslation);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraftTranslation(initialTranslation);
  }, [
    passage.id,
    passage.translation_authoritative,
    passage.translation_proposed,
    initialTranslation,
  ]);

  const prop = passage.translation_proposed?.trim() ?? "";
  const auth = passage.translation_authoritative;
  const same = auth != null && auth.trim() === prop;

  const saveTranslation = async () => {
    setSaving(true);
    try {
      onPatch({
        selected_passage_id: passage.id,
        selected_passage_translation: draftTranslation,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-md border border-ink-800/80 bg-ink-900/25 p-3">
      <p className="font-mono text-[10px] uppercase tracking-wider text-accent">
        Reference passage {pos} of {total}
        {passage.selection_rank > 0 ? ` · rank ${passage.selection_rank}` : ""} · {passage.status}
      </p>
      <p className="mt-1 text-[10px] leading-relaxed text-ink-500">{passage.why_selected}</p>
      <ProfileBlock label={`Source (${book.source_language})`} className="!mt-2">
        <p className="whitespace-pre-wrap border-l-2 border-ink-600 pl-3 text-ink-200">
          {passage.source_text}
        </p>
      </ProfileBlock>
      <ProfileBlock label={`Model translation (${book.target_language})`} className="!mt-2">
        <p className="whitespace-pre-wrap leading-relaxed text-ink-200">{prop || "—"}</p>
      </ProfileBlock>
      <ProfileBlock label={`Your translation (${book.target_language})`} className="!mt-2">
        <textarea
          value={draftTranslation}
          onChange={(e) => setDraftTranslation(e.target.value)}
          disabled={patchPending || saving}
          rows={4}
          className={cn(
            "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100",
            "placeholder:text-ink-600 focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/25",
            "disabled:opacity-60",
          )}
          aria-label={`Translation for reference passage ${pos}`}
        />
      </ProfileBlock>
      {auth != null && auth !== "" && same && prop ? (
        <p className="mt-2 text-[10px] font-mono text-ink-500">
          Saved translation matches model draft.
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={patchPending || saving}
          onClick={() => void saveTranslation()}
          className={cn(
            "rounded border border-ink-600 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-ink-200",
            "hover:bg-ink-800 disabled:opacity-40",
          )}
        >
          {saving ? "Saving…" : "Save translation"}
        </button>
      </div>
    </div>
  );
}

function VoiceProfileCard({
  v,
  book,
  patchPending,
  speakerWindows,
  onPatch,
}: {
  v: VoiceWorkingProfile;
  book: BookDetail;
  patchPending: boolean;
  speakerWindows?: number[];
  onPatch: (body: VoiceProfilePatchBody) => void;
}) {
  const selected = v.selected_passages ?? [];
  const hasMulti = selected.length > 0;
  const showLegacyOnly = !hasMulti && v.reference_passage_source.trim().length > 0;
  const [legacyDraft, setLegacyDraft] = useState(
    v.reference_passage_translation_authoritative?.trim() ||
      v.reference_passage_translation_proposed.trim() ||
      "",
  );

  useEffect(() => {
    setLegacyDraft(
      v.reference_passage_translation_authoritative?.trim() ||
        v.reference_passage_translation_proposed.trim() ||
        "",
    );
  }, [
    v.id,
    v.updated_at,
    v.reference_passage_translation_authoritative,
    v.reference_passage_translation_proposed,
  ]);

  const sameTranslation =
    v.reference_passage_translation_authoritative != null &&
    v.reference_passage_translation_authoritative.trim() ===
      v.reference_passage_translation_proposed.trim();

  return (
    <article
      className={cn(
        "rounded-lg border bg-ink-850/40 p-4 text-sm text-ink-200",
        v.needs_regeneration ? "border-warning/50" : "border-ink-800",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-serif text-base font-medium text-ink-50">{v.canonical_name}</p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink-500">
            {v.status} · voice windows {v.first_seen_window}→{v.last_observed_window}
            {v.needs_regeneration ? (
              <span className="ml-2 text-warning">· flagged for regeneration</span>
            ) : null}
            {hasMulti
              ? ` · ${selected.length} reference passage${selected.length === 1 ? "" : "es"}`
              : ` · dialogue scans ${formatNumber(v.dialogue_volume_observed)}`}
          </p>
          {speakerWindows && speakerWindows.length > 0 ? (
            <p className="mt-1 font-mono text-[10px] leading-relaxed text-accent/90">
              speaks in windows {formatWindowList(speakerWindows)}
            </p>
          ) : null}
        </div>
        <div className="flex flex-shrink-0 flex-col items-end gap-2">
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-ink-400">
            <input
              type="checkbox"
              checked={v.needs_regeneration}
              disabled={patchPending}
              onChange={(e) => onPatch({ needs_regeneration: e.target.checked })}
              className="rounded border-ink-600 bg-ink-950 text-accent focus:ring-accent/40"
            />
            Flag profile for regeneration
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={patchPending || v.status === "accepted"}
              onClick={() => onPatch({ accept: true })}
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
              onClick={() => onPatch({ reject: true })}
              className={cn(
                "rounded border border-danger-border px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-danger",
                "hover:bg-danger-surface disabled:opacity-40",
              )}
            >
              Reject
            </button>
          </div>
        </div>
      </div>

      <ProfileBlock label="Source voice observation">{v.source_voice_observation}</ProfileBlock>
      <ProfileBlock label="Target voice strategy">{v.target_voice_strategy}</ProfileBlock>

      {hasMulti ? (
        <div className="mt-4 space-y-6">
          {selected
            .slice()
            .sort((a, b) => a.selection_rank - b.selection_rank)
            .map((p, i) => (
              <PassageBlock
                key={p.id}
                passage={p}
                pos={i + 1}
                total={selected.length}
                book={book}
                patchPending={patchPending}
                onPatch={onPatch}
              />
            ))}
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
          <ProfileBlock label={`Your translation (${book.target_language})`}>
            <textarea
              value={legacyDraft}
              onChange={(e) => setLegacyDraft(e.target.value)}
              disabled={patchPending}
              rows={4}
              className={cn(
                "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100",
                "focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/25 disabled:opacity-60",
              )}
            />
            <button
              type="button"
              disabled={patchPending}
              onClick={() => onPatch({ reference_passage_translation: legacyDraft })}
              className={cn(
                "mt-2 rounded border border-ink-600 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-ink-200",
                "hover:bg-ink-800 disabled:opacity-40",
              )}
            >
              Save translation
            </button>
          </ProfileBlock>
          {v.reference_passage_translation_authoritative != null && sameTranslation ? (
            <p className="mt-2 text-[10px] font-mono text-ink-500">Same as model draft.</p>
          ) : null}
        </>
      ) : (
        <p className="mt-3 rounded border border-ink-800/80 bg-ink-900/30 px-3 py-2 text-xs text-ink-500">
          No selected reference passages yet.
        </p>
      )}
    </article>
  );
}

function VoiceCostEstimate({
  book,
  estimate,
}: {
  book: BookDetail;
  estimate: ReturnType<typeof useVoiceExtractionEstimate>;
}) {
  if (estimate.isLoading) {
    return (
      <p className="text-sm text-ink-400" aria-busy="true">
        Calculating cost estimate…
      </p>
    );
  }
  if (estimate.isError || !estimate.data) return null;
  if (estimate.data.pass1.window_count === 0) return null;

  const { data } = estimate;
  const pass1Running =
    book.speakers_extraction_status === "running" && book.speakers_extraction_windows_total;
  const pass2Running =
    book.voice_extraction_status === "running" && book.voice_extraction_windows_total;

  return (
    <details
      className={cn(
        "overflow-hidden rounded-lg border border-ink-800 bg-ink-800",
        "[&[open]_summary_.voice-chevron]:rotate-180",
      )}
    >
      <summary
        className={cn(
          "flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3",
          "font-mono text-xs uppercase tracking-wider text-ink-300",
          "hover:bg-ink-700 [&::-webkit-details-marker]:hidden",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent",
        )}
      >
        <span className="min-w-0 flex-1 text-left leading-snug text-ink-200">
          <span className="text-ink-400">Cost estimate</span>
          <span className="mx-2 text-ink-600">·</span>
          <span className="tabular-nums text-ink-100">
            {formatNumber(data.estimated_total_tokens)} tok
          </span>
          <span className="mx-2 text-ink-600">·</span>
          <span className="text-accent">{formatUsd(data.estimated_cost_usd)}</span>
          <span className="mx-2 text-ink-600">·</span>
          <span className="tabular-nums text-ink-400">
            {formatNumber(data.character_count)} character
            {data.character_count === 1 ? "" : "s"}
          </span>
        </span>
        <ChevronDown
          className="voice-chevron h-4 w-4 shrink-0 rotate-0 text-ink-500 transition-transform duration-200 ease-out"
          aria-hidden
        />
      </summary>
      <div className="space-y-4 border-t border-ink-700 px-4 py-4 text-sm leading-relaxed text-ink-300">
        <p className="text-xs text-ink-500">
          Windows ~{formatNumber(data.window_words)} words, ~{formatNumber(data.overlap_words)}{" "}
          overlap · model {data.model}
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border border-ink-700/80 bg-ink-900/50 p-3">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-400">
              Pass 1 · Speaker identification
              {pass1Running ? (
                <span className="ml-2 text-accent">
                  {book.speakers_extraction_windows_completed ?? 0}/
                  {book.speakers_extraction_windows_total}
                </span>
              ) : null}
            </p>
            <p className="mt-2 tabular-nums text-ink-100">
              {formatNumber(data.pass1.window_count)} windows ·{" "}
              {formatNumber(data.pass1.estimated_total_tokens)} tok ·{" "}
              <span className="text-accent">{formatUsd(data.pass1.estimated_cost_usd)}</span>
            </p>
          </div>
          <div className="rounded-md border border-ink-700/80 bg-ink-900/50 p-3">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-400">
              Pass 2 · Voices + passages
              {pass2Running ? (
                <span className="ml-2 text-accent">
                  {book.voice_extraction_windows_completed ?? 0}/
                  {book.voice_extraction_windows_total}
                </span>
              ) : null}
            </p>
            <p className="mt-2 tabular-nums text-ink-100">
              {formatNumber(data.pass2.window_count)} extraction windows + selection/translation for{" "}
              {formatNumber(data.character_count)} characters ·{" "}
              {formatNumber(data.pass2.estimated_total_tokens)} tok ·{" "}
              <span className="text-accent">{formatUsd(data.pass2.estimated_cost_usd)}</span>
            </p>
          </div>
        </div>
        <p className="text-xs text-ink-500">
          Pricing: ${data.pricing_input_usd_per_mtok}/M input · ${data.pricing_output_usd_per_mtok}
          /M output. Heuristic only — actual usage varies.
        </p>
      </div>
    </details>
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
  const estimate = useVoiceExtractionEstimate(book.id, glossaryReady);
  const [pendingOnly, setPendingOnly] = useState(false);

  const speakerWindowsByGlossaryId = useMemo(() => {
    const map = new Map<string, number[]>();
    for (const e of speakers.data?.entries ?? []) {
      map.set(e.glossary_entry_id, e.windows);
    }
    return map;
  }, [speakers.data?.entries]);

  const pass2Started =
    book.voice_extraction_status !== "idle" || (voices.data?.entries.length ?? 0) > 0;

  const reviewStats = useMemo(() => {
    const all = voices.data?.entries ?? [];
    let awaiting = 0;
    let accepted = 0;
    let rejected = 0;
    for (const v of all) {
      if (isAwaitingVoiceReview(v)) awaiting += 1;
      else if (v.status === "accepted") accepted += 1;
      else if (v.status === "rejected") rejected += 1;
    }
    return { awaiting, accepted, rejected };
  }, [voices.data?.entries]);

  const flaggedProfileCount = useMemo(
    () => (voices.data?.entries ?? []).filter((v) => v.needs_regeneration).length,
    [voices.data?.entries],
  );

  const profilesInScope = useMemo(() => {
    const all = voices.data?.entries ?? [];
    if (!pendingOnly) return all;
    return all.filter(isAwaitingVoiceReview);
  }, [voices.data?.entries, pendingOnly]);

  const startSpeakers = useStartSpeakersExtraction(book.id);
  const continueSpeakers = useContinueSpeakersExtraction(book.id);
  const stopSpeakers = useStopSpeakersExtraction(book.id);
  const resetSpeakers = useResetSpeakersExtraction(book.id);
  const startVoice = useStartVoiceExtraction(book.id);
  const continueVoice = useContinueVoiceExtraction(book.id);
  const stopVoice = useStopVoiceExtraction(book.id);
  const resetVoice = useResetVoiceExtraction(book.id);
  const regenerateFlagged = useRegenerateFlaggedVoices(book.id);
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
                <strong className="text-ink-400">Pass 1</strong> maps speakers per window.{" "}
                <strong className="text-ink-400">Pass 2</strong> builds voice profiles and reference
                passages. Review profiles below.
              </p>
            </div>

            {glossaryReady ? <VoiceCostEstimate book={book} estimate={estimate} /> : null}

            {!pass2Started ? (
              <div className="rounded-lg border border-ink-800 bg-ink-850/30 p-4">
                <h3 className="font-mono text-[10px] uppercase tracking-wider text-ink-400">
                  Pass 1 · Speaker identification
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-500">
                  For each window, list glossary characters with quoted speech. This map scopes Pass
                  2.
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

                <SpeakerMapPanel book={book} speakers={speakers} />
              </div>
            ) : (
              <p className="rounded-md border border-ink-800/80 bg-ink-900/30 px-3 py-2 text-xs text-ink-500">
                Pass 1 speaker map is hidden while Pass 2 results are in focus. Re-run Pass 1 from
                the controls below if you need to refresh the map.
              </p>
            )}

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
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h3 className="font-serif text-lg text-ink-100">Profiles</h3>
                {!voices.isLoading && voices.data && voices.data.entries.length > 0 ? (
                  <ReviewProgressLine
                    awaiting={reviewStats.awaiting}
                    accepted={reviewStats.accepted}
                    rejected={reviewStats.rejected}
                  />
                ) : null}
              </div>
              {voices.data && voices.data.entries.length > 0 ? (
                <div
                  className={cn("shrink-0 rounded-xl border border-ink-800/80 bg-ink-900/35 p-3")}
                >
                  <div className="flex items-center gap-2.5">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={pendingOnly}
                      aria-label={
                        pendingOnly ? "Showing pending profiles only" : "Showing all profiles"
                      }
                      onClick={() => setPendingOnly((v) => !v)}
                      className={cn(
                        "relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                        pendingOnly
                          ? "border-accent/50 bg-accent-soft"
                          : "border-ink-700 bg-ink-950/80",
                      )}
                    >
                      <span
                        className={cn(
                          "pointer-events-none absolute left-0.5 top-0.5 h-6 w-6 rounded-full bg-ink-100 shadow transition-transform duration-200 ease-out",
                          pendingOnly ? "translate-x-[1.375rem] bg-accent" : "translate-x-0",
                        )}
                        aria-hidden
                      />
                    </button>
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                        Pending only
                      </p>
                      <p className="text-[11px] text-ink-500">Hide accepted profiles</p>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            {flaggedProfileCount > 0 ? (
              <div className="flex flex-wrap items-center gap-3 rounded-md border border-warning/40 bg-warning/5 px-4 py-3">
                <p className="text-sm text-ink-300">
                  <span className="tabular-nums font-medium text-warning">
                    {flaggedProfileCount}
                  </span>{" "}
                  profile{flaggedProfileCount === 1 ? "" : "s"} flagged for regeneration.
                </p>
                <button
                  type="button"
                  disabled={
                    book.voice_extraction_status === "running" ||
                    book.speakers_extraction_status !== "completed" ||
                    regenerateFlagged.isPending
                  }
                  title={
                    book.speakers_extraction_status !== "completed"
                      ? "Complete speaker identification first."
                      : "Re-run extraction only for flagged characters in their speaker windows."
                  }
                  onClick={() => regenerateFlagged.mutate()}
                  className={cn(
                    "rounded-md border border-warning/50 px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-warning",
                    "hover:bg-warning/10 disabled:cursor-not-allowed disabled:opacity-60",
                  )}
                >
                  {regenerateFlagged.isPending || book.voice_extraction_status === "running"
                    ? "Regenerating…"
                    : "Run regeneration"}
                </button>
              </div>
            ) : null}

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
            {voices.data && voices.data.entries.length > 0 && profilesInScope.length === 0 && (
              <p className="text-sm text-ink-400">
                No pending profiles — turn off “Pending only” to see accepted entries.
              </p>
            )}
            {profilesInScope.map((v) => (
              <VoiceProfileCard
                key={v.id}
                v={v}
                book={book}
                patchPending={patchVoice.isPending}
                speakerWindows={speakerWindowsByGlossaryId.get(v.glossary_entry_id)}
                onPatch={(body) => patchVoice.mutate({ voiceId: v.id, body })}
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
                        "This will delete the per-window speaker map and Pass 1 notepad for this book. Continue?",
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
                          "This will permanently delete all character voice profiles and review progress. Continue?",
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
