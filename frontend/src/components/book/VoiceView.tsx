import { useQueryClient, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Circle,
  Flag,
  Loader2,
  PauseCircle,
  RotateCcw,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { OverflowMenu } from "@/components/ui/OverflowMenu";
import {
  VOICE_EXTRACTION_OVERLAP_WORDS,
  VOICE_EXTRACTION_WINDOW_WORDS,
} from "@/constants/voiceExtraction";
import type {
  BookDetail,
  GlossaryExtractionStatus,
  VoiceExtractionEstimate,
  VoicePassEstimate,
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

type VoidMutation = UseMutationResult<unknown, Error, void>;

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

function errorDetail(mutation: { isError: boolean; error: Error | null }, fallback: string) {
  if (!mutation.isError) return null;
  return mutation.error instanceof ApiError ? mutation.error.detail : fallback;
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
            ? "border-accent bg-accent-soft text-accent"
            : "border-ink-700 bg-ink-900 text-ink-500",
        )}
      >
        {awaiting} pending
      </span>
      <span className="inline-flex items-center gap-1 rounded-full border border-ink-700 bg-ink-900 px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-ink-300">
        {accepted} accepted
      </span>
      {rejected > 0 ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-ink-700 bg-ink-950 px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-ink-500">
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
      <p className="text-sm text-ink-400" aria-busy="true">
        Loading speaker map…
      </p>
    );
  }
  if (speakers.isError) {
    return <p className="text-sm text-danger">Could not load speaker map.</p>;
  }
  if (!speakers.data || speakers.data.entries.length === 0) {
    return (
      <p className="text-sm text-ink-500">
        {book.speakers_extraction_status === "running"
          ? `Waiting for first window…${progress}`
          : "No speakers mapped yet."}
      </p>
    );
  }

  const { entries, windows_mapped, edges_total } = speakers.data;

  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
        {entries.length} character{entries.length === 1 ? "" : "s"} · {windows_mapped} window
        {windows_mapped === 1 ? "" : "s"} · {edges_total} appearance
        {edges_total === 1 ? "" : "s"}
        {progress}
      </p>
      <ul
        className="mt-2 max-h-64 space-y-1.5 overflow-y-auto rounded-lg border border-ink-800 bg-ink-900 p-2"
        aria-live="polite"
        aria-label="Characters and window numbers where they speak"
      >
        {entries.map((entry) => (
          <li
            key={entry.glossary_entry_id}
            className="grid gap-1 rounded px-2 py-1 text-sm sm:grid-cols-[minmax(8rem,11rem)_1fr]"
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

function PassStatusIcon({ status }: { status: GlossaryExtractionStatus }) {
  const cls = "h-4 w-4 shrink-0";
  if (status === "running") {
    return <Loader2 className={cn(cls, "animate-spin text-accent")} aria-hidden />;
  }
  if (status === "completed")
    return <CheckCircle2 className={cn(cls, "text-success")} aria-hidden />;
  if (status === "failed") return <AlertCircle className={cn(cls, "text-danger")} aria-hidden />;
  if (status === "cancelled")
    return <PauseCircle className={cn(cls, "text-warning")} aria-hidden />;
  return <Circle className={cn(cls, "text-ink-500")} aria-hidden />;
}

function passStatusLine(
  status: GlossaryExtractionStatus,
  completed: number | null | undefined,
  total: number | null | undefined,
): string {
  const progress = total != null && total > 0 ? `${completed ?? 0}/${total}` : null;
  switch (status) {
    case "running":
      return progress ? `Running — window ${progress}.` : "Running.";
    case "completed":
      return progress ? `Complete — ${progress} windows.` : "Complete.";
    case "cancelled":
      return progress ? `Stopped after ${progress}. Partial results kept.` : "Stopped mid-run.";
    case "failed":
      return "Last run failed.";
    default:
      return "Not started.";
  }
}

/**
 * One pass, one card: what it is, where it stands, what it costs, and —
 * behind a disclosure — everything needed to drive it. Two of these side
 * by side replace the sticky bottom bar that used to stack four button
 * rows under the profiles you were trying to read.
 */
function PassCard({
  eyebrow,
  description,
  status,
  windowsCompleted,
  windowsTotal,
  lastError,
  pass,
  characterCount,
  model,
  startLabel,
  start,
  continueMut,
  stop,
  reset,
  resetConfirm,
  nothingToReset,
  disabled,
  estimateLoading,
  children,
}: {
  eyebrow: string;
  description: string;
  status: GlossaryExtractionStatus;
  windowsCompleted: number | null | undefined;
  windowsTotal: number | null | undefined;
  lastError: string | null | undefined;
  pass: VoicePassEstimate | null;
  characterCount: number | null;
  model: string | null;
  startLabel: string;
  start: VoidMutation;
  continueMut: VoidMutation;
  stop: VoidMutation;
  reset: VoidMutation;
  resetConfirm: string;
  nothingToReset: boolean;
  disabled: boolean;
  estimateLoading: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const running = status === "running";
  const resumable = status === "failed" || status === "cancelled";

  const mutationError =
    errorDetail(start, "Could not start this pass.") ??
    errorDetail(continueMut, "Could not continue this pass.") ??
    errorDetail(stop, "Could not request stop.") ??
    errorDetail(reset, "Could not reset this pass.");

  return (
    <section
      className="flex flex-col rounded-lg border border-ink-800 bg-ink-800"
      aria-label={eyebrow}
    >
      <div className="flex flex-1 flex-col px-4 py-3">
        <div className="flex items-start gap-2.5">
          <PassStatusIcon status={status} />
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-400">{eyebrow}</p>
            <p className="mt-1 text-[13px] leading-snug text-ink-100">
              {passStatusLine(status, windowsCompleted, windowsTotal)}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink-500">{description}</p>
            <p className="mt-2 font-mono text-[11px] tabular-nums text-ink-400">
              {estimateLoading ? (
                "estimating…"
              ) : pass ? (
                <>
                  {formatNumber(pass.window_count)} windows
                  <span className="text-ink-600"> · </span>
                  {formatNumber(pass.estimated_total_tokens)} tok
                  <span className="text-ink-600"> · </span>
                  <span className="text-accent">{formatUsd(pass.estimated_cost_usd)}</span>
                </>
              ) : (
                "no estimate available"
              )}
            </p>
          </div>
        </div>

        {lastError && !running && (
          <p className="mt-3 rounded-lg border border-danger-border bg-danger-surface px-3 py-2 text-xs text-danger">
            {lastError}
          </p>
        )}

        <div className="mt-3">
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={open}
            className="-ml-2"
            onClick={() => setOpen((o) => !o)}
          >
            Controls
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 transition-transform duration-200 ease-out",
                open && "rotate-180",
              )}
              aria-hidden
            />
          </Button>
        </div>
      </div>

      {open && (
        <div className="space-y-4 border-t border-ink-700 px-4 py-4">
          {pass && (
            <dl className="grid grid-cols-2 gap-2.5">
              <EstimateCell label="Windows" value={formatNumber(pass.window_count)} />
              <EstimateCell
                label="Tokens"
                value={formatNumber(pass.estimated_total_tokens)}
                detail={`${formatNumber(pass.estimated_input_tokens)} in · ${formatNumber(pass.estimated_output_tokens)} out`}
              />
              <EstimateCell label="Cost" value={formatUsd(pass.estimated_cost_usd)} accent />
              <EstimateCell
                label={characterCount != null ? "Characters" : "Model"}
                value={characterCount != null ? formatNumber(characterCount) : (model ?? "—")}
              />
            </dl>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="accent"
              size="sm"
              disabled={disabled || running || start.isPending}
              onClick={() => start.mutate()}
            >
              {running ? "Running…" : start.isPending ? "Starting…" : startLabel}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled || !resumable || continueMut.isPending}
              title={
                resumable
                  ? "Resume from the last completed window"
                  : "Only available after a stopped or failed run"
              }
              onClick={() => continueMut.mutate()}
            >
              {continueMut.isPending ? "Continuing…" : "Continue"}
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={disabled || !running || stop.isPending}
              title={running ? "Stop after the current window" : "Only available while running"}
              onClick={() => stop.mutate()}
            >
              {stop.isPending ? "Stopping…" : "Stop"}
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={disabled || running || nothingToReset || reset.isPending}
              title={
                running
                  ? "Stop the run before resetting"
                  : nothingToReset
                    ? "Nothing to clear."
                    : undefined
              }
              onClick={() => {
                if (!window.confirm(resetConfirm)) return;
                reset.mutate();
              }}
            >
              {reset.isPending ? "Resetting…" : "Reset…"}
            </Button>
          </div>

          {mutationError && (
            <p className="text-sm text-danger" role="alert">
              {mutationError}
            </p>
          )}

          {children}
        </div>
      )}
    </section>
  );
}

function EstimateCell({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: string;
  detail?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2">
      <dt className="font-mono text-[10px] uppercase tracking-wider text-ink-500">{label}</dt>
      <dd
        className={cn(
          "mt-1 truncate font-mono text-[13px] tabular-nums",
          accent ? "text-accent" : "text-ink-100",
        )}
        title={value}
      >
        {value}
      </dd>
      {detail && <p className="mt-0.5 font-mono text-[10px] text-ink-500">{detail}</p>}
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
    <div className={className}>
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

  return (
    <div className="rounded-lg border border-ink-800 bg-ink-900 p-3">
      <p className="font-mono text-[10px] uppercase tracking-wider text-accent">
        Reference passage {pos} of {total}
        {passage.selection_rank > 0 ? ` · rank ${passage.selection_rank}` : ""} · {passage.status}
      </p>
      <p className="mt-1 text-[10px] leading-relaxed text-ink-500">{passage.why_selected}</p>
      <ProfileBlock label={`Source (${book.source_language})`} className="mt-2">
        <p className="whitespace-pre-wrap border-l-2 border-ink-600 pl-3 text-ink-200">
          {passage.source_text}
        </p>
      </ProfileBlock>
      <ProfileBlock label={`Model translation (${book.target_language})`} className="mt-2">
        <p className="whitespace-pre-wrap leading-relaxed text-ink-200">{prop || "—"}</p>
      </ProfileBlock>
      <ProfileBlock label={`Your translation (${book.target_language})`} className="mt-2">
        <textarea
          value={draftTranslation}
          onChange={(e) => setDraftTranslation(e.target.value)}
          disabled={patchPending}
          rows={4}
          className={cn(
            "w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100",
            "placeholder:text-ink-600 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent",
            "disabled:opacity-60",
          )}
          aria-label={`Translation for reference passage ${pos}`}
        />
      </ProfileBlock>
      {auth != null && auth !== "" && same && prop ? (
        <p className="mt-2 font-mono text-[10px] text-ink-500">
          Saved translation matches model draft.
        </p>
      ) : null}
      <div className="mt-3">
        <Button
          variant="ghost"
          size="sm"
          className="border border-ink-700"
          disabled={patchPending}
          onClick={() =>
            onPatch({
              selected_passage_id: passage.id,
              selected_passage_translation: draftTranslation,
            })
          }
        >
          Save translation
        </Button>
      </div>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  // "proposed"/"adjusted" are storage words; what the reviewer needs to
  // know is that a decision is outstanding.
  const label = status === "proposed" || status === "adjusted" ? "needs review" : status;
  const tone =
    status === "accepted"
      ? "border-success-border bg-success-surface text-success"
      : status === "rejected"
        ? "border-ink-700 bg-ink-950 text-ink-500"
        : status === "adjusted"
          ? "border-accent bg-accent-soft text-accent"
          : "border-ink-700 bg-ink-900 text-ink-400";
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 font-mono text-[9px] font-medium uppercase tracking-wider",
        tone,
      )}
    >
      {label}
    </span>
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
  const [showWindows, setShowWindows] = useState(false);
  /**
   * An accepted profile is a decision already made — it collapses to its
   * summary until you explicitly reopen it. Local state, because
   * "reopened" is a way of looking at the row, not a stored status.
   */
  const [reopened, setReopened] = useState(false);
  const collapsed = v.status === "accepted" && !reopened;

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

  useEffect(() => {
    if (v.status !== "accepted") setReopened(false);
  }, [v.status]);

  const sameTranslation =
    v.reference_passage_translation_authoritative != null &&
    v.reference_passage_translation_authoritative.trim() ===
      v.reference_passage_translation_proposed.trim();

  const metadataLine = [
    `voice windows ${v.first_seen_window}→${v.last_observed_window}`,
    ...(speakerWindows && speakerWindows.length > 0
      ? [`speaks in ${speakerWindows.length} windows`]
      : []),
    hasMulti
      ? `${selected.length} reference passage${selected.length === 1 ? "" : "es"}`
      : `dialogue scans ${formatNumber(v.dialogue_volume_observed)}`,
  ].join(" · ");

  return (
    <article
      className={cn(
        "rounded-lg border bg-ink-800 p-4 text-sm text-ink-200",
        v.needs_regeneration ? "border-warning-border" : "border-ink-800",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-serif text-base font-medium text-ink-50">{v.canonical_name}</p>
            <StatusChip status={v.status} />
            {v.needs_regeneration && (
              <span className="rounded-full border border-warning-border bg-warning-surface px-2 py-0.5 font-mono text-[9px] font-medium uppercase tracking-wider text-warning">
                flagged
              </span>
            )}
          </div>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink-500">
            {metadataLine}
          </p>
          {showWindows && speakerWindows && speakerWindows.length > 0 ? (
            <p className="mt-1.5 font-mono text-[10px] leading-relaxed text-accent">
              speaks in windows {formatWindowList(speakerWindows)}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {collapsed ? (
            <Button variant="ghost" size="sm" onClick={() => setReopened(true)}>
              Reopen
            </Button>
          ) : (
            <>
              <Button
                variant="accent"
                size="sm"
                disabled={patchPending || v.status === "accepted"}
                onClick={() => onPatch({ accept: true })}
              >
                Accept
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={patchPending || v.status === "rejected"}
                onClick={() => onPatch({ reject: true })}
              >
                Reject
              </Button>
            </>
          )}
          <OverflowMenu
            disabled={patchPending}
            label={`More actions for ${v.canonical_name}`}
            items={[
              {
                label: v.needs_regeneration ? "Clear regeneration flag" : "Flag for regeneration",
                icon: Flag,
                onClick: () => onPatch({ needs_regeneration: !v.needs_regeneration }),
              },
              {
                label: showWindows ? "Hide speaker windows" : "View speaker windows",
                icon: Users,
                onClick: () => setShowWindows((s) => !s),
                disabled: !speakerWindows || speakerWindows.length === 0,
              },
              ...(v.status === "accepted"
                ? [
                    {
                      label: "Reopen for review",
                      icon: RotateCcw,
                      onClick: () => setReopened(true),
                    },
                  ]
                : []),
            ]}
          />
        </div>
      </div>

      {!collapsed && (
        <>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <ProfileBlock label="Source voice observation">
              {v.source_voice_observation}
            </ProfileBlock>
            <ProfileBlock label="Target voice strategy">{v.target_voice_strategy}</ProfileBlock>
          </div>

          {hasMulti ? (
            <div className="mt-4 space-y-4">
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
            <div className="mt-4 space-y-3">
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
                    "w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100",
                    "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60",
                  )}
                />
                <div className="mt-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="border border-ink-700"
                    disabled={patchPending}
                    onClick={() => onPatch({ reference_passage_translation: legacyDraft })}
                  >
                    Save translation
                  </Button>
                </div>
              </ProfileBlock>
              {v.reference_passage_translation_authoritative != null && sameTranslation ? (
                <p className="font-mono text-[10px] text-ink-500">Same as model draft.</p>
              ) : null}
            </div>
          ) : (
            <p className="mt-3 rounded-lg border border-ink-800 bg-ink-900 px-3 py-2 text-xs text-ink-500">
              No selected reference passages yet.
            </p>
          )}
        </>
      )}
    </article>
  );
}

/**
 * Voice extraction and review: same overlapping windows as the glossary
 * pass, but profiles attach only to glossary characters.
 */
export function VoiceView({ book }: Props) {
  const queryClient = useQueryClient();
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

  const actionsDisabled = !(book.word_count > 0 && glossaryReady);
  const speakersIncomplete = book.speakers_extraction_status !== "completed";
  const nothingToResetSpeakers =
    book.speakers_extraction_status === "idle" && !book.speakers_extraction_last_error;
  const nothingToResetVoice =
    book.voice_extraction_status === "idle" &&
    !book.voice_extraction_last_error &&
    voices.isSuccess &&
    voices.data.entries.length === 0;

  const est: VoiceExtractionEstimate | undefined = estimate.data;

  return (
    <div className="reader-surface h-full min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div>
          <h2 className="font-serif text-xl font-medium text-ink-50">Character voices</h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-500">
            Two passes over the same windows (~{formatNumber(VOICE_EXTRACTION_WINDOW_WORDS)} words,
            ~{formatNumber(VOICE_EXTRACTION_OVERLAP_WORDS)} overlap). Pass 1 maps speakers per
            window; Pass 2 builds voice profiles and reference passages.
            {est ? ` Model ${est.model}.` : ""}
          </p>
        </div>

        {!glossaryReady && (
          <p className="mt-4 rounded-lg border border-warning-border bg-warning-surface px-3 py-2 text-sm text-warning">
            Finish glossary extraction first; voices need at least one character entry.
          </p>
        )}

        <div className="mt-6 grid gap-3 lg:grid-cols-2">
          <PassCard
            eyebrow="Pass 1 · Speaker identification"
            description="For each window, list glossary characters with quoted speech. This map scopes Pass 2."
            status={book.speakers_extraction_status}
            windowsCompleted={book.speakers_extraction_windows_completed}
            windowsTotal={book.speakers_extraction_windows_total}
            lastError={book.speakers_extraction_last_error}
            pass={est?.pass1 ?? null}
            characterCount={null}
            model={est?.model ?? null}
            startLabel={
              book.speakers_extraction_status === "completed" ? "Re-run Pass 1" : "Start Pass 1"
            }
            start={startSpeakers}
            continueMut={continueSpeakers}
            stop={stopSpeakers}
            reset={resetSpeakers}
            resetConfirm="This will delete the per-window speaker map and Pass 1 notepad for this book. Continue?"
            nothingToReset={nothingToResetSpeakers}
            disabled={actionsDisabled}
            estimateLoading={estimate.isLoading}
          >
            {/* The speaker map lives here now — never hidden, just
                collapsed with the controls that produce it. */}
            <div className="border-t border-ink-800 pt-3">
              <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink-500">
                Speaker map
              </p>
              <SpeakerMapPanel book={book} speakers={speakers} />
            </div>
          </PassCard>

          <PassCard
            eyebrow="Pass 2 · Voices + passages"
            description={
              speakersIncomplete
                ? "Builds profiles and reference passages. Without a complete Pass 1 it falls back to the full glossary character list per window."
                : "Builds voice profiles and selects reference passages for the characters that speak."
            }
            status={book.voice_extraction_status}
            windowsCompleted={book.voice_extraction_windows_completed}
            windowsTotal={book.voice_extraction_windows_total}
            lastError={book.voice_extraction_last_error}
            pass={est?.pass2 ?? null}
            characterCount={est?.character_count ?? null}
            model={est?.model ?? null}
            startLabel={
              book.voice_extraction_status === "completed" ? "Re-run Pass 2" : "Start Pass 2"
            }
            start={startVoice}
            continueMut={continueVoice}
            stop={stopVoice}
            reset={resetVoice}
            resetConfirm="This will permanently delete all character voice profiles and review progress. Continue?"
            nothingToReset={nothingToResetVoice}
            disabled={actionsDisabled}
            estimateLoading={estimate.isLoading}
          />
        </div>

        <div className="mt-10 space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
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
                role="group"
                aria-label="Filter profiles"
                className="inline-flex shrink-0 rounded-lg border border-ink-700 bg-ink-900 p-0.5"
              >
                {[
                  { id: true, label: "Pending" },
                  { id: false, label: "All" },
                ].map((opt) => (
                  <button
                    key={opt.label}
                    type="button"
                    aria-pressed={pendingOnly === opt.id}
                    onClick={() => setPendingOnly(opt.id)}
                    className={cn(
                      "inline-flex h-7 items-center rounded-md px-2.5 text-[12.5px] transition-colors duration-150",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                      pendingOnly === opt.id
                        ? "bg-ink-800 text-ink-50"
                        : "text-ink-400 hover:text-ink-100",
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          {flaggedProfileCount > 0 ? (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warning-border bg-warning-surface px-4 py-3">
              <p className="text-sm text-ink-300">
                <span className="font-medium tabular-nums text-warning">{flaggedProfileCount}</span>{" "}
                profile{flaggedProfileCount === 1 ? "" : "s"} flagged for regeneration.
              </p>
              <Button
                variant="ghost"
                size="sm"
                className="border border-warning-border text-warning hover:bg-warning-surface"
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
              >
                {regenerateFlagged.isPending || book.voice_extraction_status === "running"
                  ? "Regenerating…"
                  : "Run regeneration"}
              </Button>
            </div>
          ) : null}

          {voices.isLoading && (
            <p className="text-sm text-ink-400" aria-busy="true">
              Loading…
            </p>
          )}
          {voices.isError && <p className="text-sm text-danger">Could not load voice profiles.</p>}
          {voices.data && voices.data.entries.length === 0 && (
            <p className="text-sm text-ink-400">
              No profiles yet. Run extraction after glossary completes.
            </p>
          )}
          {voices.data && voices.data.entries.length > 0 && profilesInScope.length === 0 && (
            <p className="text-sm text-ink-400">
              No pending profiles — switch to “All” to see accepted entries.
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
  );
}
