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
import { type StepModel, useStepModel } from "@/hooks/useStepModel";
import { OverflowMenu } from "@/components/ui/OverflowMenu";
import {
  VOICE_EXTRACTION_OVERLAP_WORDS,
  VOICE_EXTRACTION_WINDOW_WORDS,
} from "@/constants/voiceExtraction";
import type {
  BookDetail,
  CostGuardState,
  GlossaryExtractionStatus,
  RunOptions,
  VoiceEvidenceLine,
  VoiceExtractionEstimate,
  VoiceFeature,
  VoicePassEstimate,
  VoiceProfilePatchBody,
  VoiceRegisterShift,
  VoiceSelectedPassage,
  VoiceWorkingProfile,
  WorkingSpeakersResponse,
} from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import {
  bookKeys,
  useContinueSpeakersExtraction,
  useContinueVoiceExtraction,
  useDialogueLines,
  usePatchVoiceWorkingProfile,
  useRegenerateFlaggedVoices,
  useRunVoiceCastPass,
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

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";
import { CostGuardNotice } from "./CostGuardNotice";
import { ModelPicker } from "./ModelPicker";
import { StageFinishedToggle } from "./StageFinishedToggle";
import { glossaryUsable, showStageFinishedToggle } from "./tabs";

interface Props {
  book: BookDetail;
}

type VoidMutation = UseMutationResult<unknown, Error, void>;
/** Start or continue a pass on the model picked for it. */
type RunMutation = UseMutationResult<unknown, Error, RunOptions | void>;

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

function chapterSpan(chapters: number[]): string {
  if (chapters.length === 0) return "—";
  const first = chapters[0];
  const last = chapters[chapters.length - 1];
  return first === last ? `ch. ${first}` : `ch. ${first}–${last}`;
}

/** One character's lines (or, with speakerId null, lines with no speaker). */
function SpeakerLines({ bookId, speakerId }: { bookId: string; speakerId: string | null }) {
  const lines = useDialogueLines(bookId, speakerId, true);
  if (lines.isLoading) {
    return (
      <p className="px-2 py-1 text-xs text-ink-500" aria-busy="true">
        Loading lines…
      </p>
    );
  }
  if (lines.isError || !lines.data) {
    return <p className="px-2 py-1 text-xs text-danger">Could not load lines.</p>;
  }
  return (
    <ol className="mt-1 space-y-1.5 border-l border-ink-700 pl-3">
      {lines.data.lines.map((line) => (
        <li key={line.paragraph_id} className="text-xs leading-relaxed text-ink-300">
          <span className="mr-1.5 font-mono text-[10px] text-ink-500">
            ch. {line.chapter_number}
            {line.addressee_name ? ` → ${line.addressee_name}` : ""}
            {line.kind === "thought" ? " · thought" : ""}
            {line.kind === "unknown" ? " · not attributed" : ""}
            {line.confidence === "inferred" ? " · inferred" : ""}
          </span>
          {line.text}
        </li>
      ))}
      {lines.data.truncated && (
        <li className="text-xs text-ink-500">Only the first {lines.data.lines.length} shown.</li>
      )}
    </ol>
  );
}

function SpeakerRow({
  label,
  detail,
  open,
  onToggle,
  children,
}: {
  label: string;
  detail: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <li className="rounded px-2 py-1">
      {/* Name over details: the pass card is narrow, so no side-by-side columns. */}
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-start gap-2 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-ink-100">{label}</span>
          <span className="block font-mono text-[11px] leading-relaxed text-ink-400">{detail}</span>
        </span>
        <ChevronDown
          className={cn(
            "mt-1 h-3.5 w-3.5 shrink-0 text-ink-500 transition-transform duration-200 ease-out",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      {open && children}
    </li>
  );
}

function SpeakerMapPanel({
  book,
  speakers,
}: {
  book: BookDetail;
  speakers: UseQueryResult<WorkingSpeakersResponse, Error>;
}) {
  // A glossary id, "none" for lines with no speaker, or null when all are closed.
  const [openId, setOpenId] = useState<string | null>(null);
  const done = book.speakers_extraction_windows_completed;
  const total = book.speakers_extraction_windows_total;
  const progress =
    book.speakers_extraction_status === "running" && total != null && total > 0
      ? ` · reading part ${done ?? 0}/${total}`
      : "";

  if (speakers.isLoading && !speakers.data) {
    return (
      <p className="text-sm text-ink-400" aria-busy="true">
        Loading speakers…
      </p>
    );
  }
  if (speakers.isError) {
    return <p className="text-sm text-danger">Could not load speakers.</p>;
  }
  if (!speakers.data || speakers.data.lines_total === 0) {
    return (
      <p className="text-sm text-ink-500">
        {book.speakers_extraction_status === "running"
          ? `Waiting for the first part…${progress}`
          : "No lines attributed yet."}
      </p>
    );
  }

  const { entries, lines_attributed, lines_unknown, lines_not_dialogue } = speakers.data;
  const toggle = (id: string) => setOpenId((cur) => (cur === id ? null : id));

  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
        {entries.length} character{entries.length === 1 ? "" : "s"} · {lines_attributed} line
        {lines_attributed === 1 ? "" : "s"} attributed · {lines_unknown} with no speaker ·{" "}
        {lines_not_dialogue} not dialogue
        {progress}
      </p>
      <ul
        className="mt-2 max-h-96 space-y-0.5 overflow-y-auto rounded-lg border border-ink-800 bg-ink-900 p-2"
        aria-live="polite"
        aria-label="Characters and their dialogue lines"
      >
        {entries.map((entry) => {
          const top = entry.addressees[0];
          const detail = [
            `${entry.line_count} line${entry.line_count === 1 ? "" : "s"}`,
            ...(entry.thought_count > 0 ? [`${entry.thought_count} thought`] : []),
            chapterSpan(entry.chapters),
            ...(top ? [`mostly to ${top.canonical_name}`] : []),
          ].join(" · ");
          return (
            <SpeakerRow
              key={entry.glossary_entry_id}
              label={entry.canonical_name}
              detail={detail}
              open={openId === entry.glossary_entry_id}
              onToggle={() => toggle(entry.glossary_entry_id)}
            >
              <SpeakerLines bookId={book.id} speakerId={entry.glossary_entry_id} />
            </SpeakerRow>
          );
        })}
        {lines_unknown > 0 && (
          <SpeakerRow
            label="No speaker"
            detail={`${lines_unknown} line${lines_unknown === 1 ? "" : "s"} · not in the glossary or not worked out`}
            open={openId === "none"}
            onToggle={() => toggle("none")}
          >
            <SpeakerLines bookId={book.id} speakerId={null} />
          </SpeakerRow>
        )}
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
  unit: string,
): string {
  const progress = total != null && total > 0 ? `${completed ?? 0}/${total}` : null;
  switch (status) {
    case "running":
      return progress ? `Running — ${unit} ${progress}.` : "Running.";
    case "completed":
      return progress ? `Complete — ${progress} ${unit}s.` : "Complete.";
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
  unit,
  windowsCompleted,
  windowsTotal,
  lastError,
  pass,
  characterCount,
  model,
  modelChoice,
  costState,
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
  /** What one step of the run is: "window" or "part". */
  unit: string;
  windowsCompleted: number | null | undefined;
  windowsTotal: number | null | undefined;
  lastError: string | null | undefined;
  pass: VoicePassEstimate | null;
  characterCount: number | null;
  model: string | null;
  modelChoice: StepModel;
  costState: CostGuardState | undefined;
  startLabel: string;
  start: RunMutation;
  continueMut: RunMutation;
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
              {passStatusLine(status, windowsCompleted, windowsTotal, unit)}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink-500">{description}</p>
            <p className="mt-2 font-mono text-[11px] tabular-nums text-ink-400">
              {estimateLoading ? (
                "estimating…"
              ) : pass ? (
                <>
                  {formatNumber(pass.window_count)} {unit}s<span className="text-ink-600"> · </span>
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

        <CostGuardNotice
          state={costState}
          paused={status === "cancelled"}
          busy={continueMut.isPending}
          onContinue={() => continueMut.mutate({ model: modelChoice.model })}
          onContinueWithoutLimit={() =>
            continueMut.mutate({ model: modelChoice.model, costLimit: false })
          }
          className="mt-3"
        />

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
          <ModelPicker choice={modelChoice} disabled={running} />
          {pass && (
            <dl className="grid grid-cols-2 gap-2.5">
              <EstimateCell
                label={`${unit.charAt(0).toUpperCase()}${unit.slice(1)}s`}
                value={formatNumber(pass.window_count)}
              />
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
              onClick={() => start.mutate({ model: modelChoice.model })}
            >
              {running ? "Running…" : start.isPending ? "Starting…" : startLabel}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled || !resumable || continueMut.isPending}
              title={
                resumable
                  ? `Resume from the last completed ${unit}`
                  : "Only available after a stopped or failed run"
              }
              onClick={() => continueMut.mutate({ model: modelChoice.model })}
            >
              {continueMut.isPending ? "Continuing…" : "Continue"}
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={disabled || !running || stop.isPending}
              title={running ? `Stop after the current ${unit}` : "Only available while running"}
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
      {passage.translation_review && passage.translation_revised ? (
        <div className="mt-3 rounded-lg border border-warning-border bg-warning-surface p-3">
          <p className="font-mono text-[10px] uppercase tracking-wider text-warning">Cast check</p>
          <p className="mt-1 text-xs leading-relaxed text-ink-300">{passage.translation_review}</p>
          <ProfileBlock label="Suggested revision" className="mt-2">
            <p className="whitespace-pre-wrap leading-relaxed text-ink-200">
              {passage.translation_revised}
            </p>
          </ProfileBlock>
          <Button
            variant="ghost"
            size="sm"
            className="mt-2 border border-warning-border text-warning hover:bg-warning-surface"
            disabled={patchPending}
            onClick={() =>
              onPatch({
                selected_passage_id: passage.id,
                selected_passage_translation: passage.translation_revised ?? "",
              })
            }
          >
            Use revision
          </Button>
        </div>
      ) : null}
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

/** The short rules translation reads for this character; editable. */
function BriefBlock({
  v,
  patchPending,
  onPatch,
}: {
  v: VoiceWorkingProfile;
  patchPending: boolean;
  onPatch: (body: VoiceProfilePatchBody) => void;
}) {
  const saved = v.translation_brief ?? "";
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [v.id, saved]);
  if (!saved && !draft) {
    return (
      <p className="mt-4 text-xs text-ink-500">
        No brief yet: translation uses the full strategy below until the cast pass runs.
      </p>
    );
  }
  return (
    <ProfileBlock label="Translation brief (what translation reads)" className="mt-4">
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        disabled={patchPending}
        rows={Math.min(10, Math.max(4, draft.split("\n").length + 1))}
        className={cn(
          "w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100",
          "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60",
        )}
        aria-label={`Translation brief for ${v.canonical_name}`}
      />
      {draft.trim() !== saved.trim() && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-2 border border-ink-700"
          disabled={patchPending || !draft.trim()}
          onClick={() => onPatch({ translation_brief: draft })}
        >
          Save brief
        </Button>
      )}
    </ProfileBlock>
  );
}

function EvidenceLines({ lines }: { lines: VoiceEvidenceLine[] }) {
  return (
    <ul className="mt-1 space-y-1 border-l border-ink-700 pl-3">
      {lines.map((line) => (
        <li key={line.paragraph_id} className="text-xs leading-relaxed text-ink-400">
          <span className="mr-1.5 font-mono text-[10px] text-ink-500">
            ch. {line.chapter_number}
          </span>
          {line.text}
        </li>
      ))}
    </ul>
  );
}

/** The features and register shifts behind a profile, each with its lines. */
function EvidenceBlock({
  features,
  shifts,
}: {
  features: VoiceFeature[];
  shifts: VoiceRegisterShift[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4">
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={open}
        className="-ml-2"
        onClick={() => setOpen((o) => !o)}
      >
        Evidence · {features.length} feature{features.length === 1 ? "" : "s"}
        {shifts.length > 0
          ? ` · ${shifts.length} register shift${shifts.length === 1 ? "" : "s"}`
          : ""}
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform duration-200 ease-out",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </Button>
      {open && (
        <div className="mt-2 space-y-3 rounded-lg border border-ink-800 bg-ink-900 p-3">
          {features.map((f, i) => (
            <div key={`f${i}`}>
              <p className="text-[13px] leading-snug text-ink-100">{f.feature}</p>
              <EvidenceLines lines={f.lines} />
            </div>
          ))}
          {shifts.length > 0 && (
            <p className="pt-1 font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Register shifts
            </p>
          )}
          {shifts.map((x, i) => (
            <div key={`s${i}`}>
              <p className="text-[13px] leading-snug text-ink-100">
                <span className="text-ink-400">{x.situation}:</span> {x.change}
              </p>
              <EvidenceLines lines={x.lines} />
            </div>
          ))}
        </div>
      )}
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
    ...(v.line_count > 0
      ? [
          `based on ${formatNumber(v.line_count)} line${v.line_count === 1 ? "" : "s"}` +
            (v.lines_sampled ? " (a sample was sent)" : ""),
        ]
      : [`voice windows ${v.first_seen_window}→${v.last_observed_window}`]),
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
            {v.low_evidence && (
              <span
                className="rounded-full border border-ink-700 bg-ink-900 px-2 py-0.5 font-mono text-[9px] font-medium uppercase tracking-wider text-ink-400"
                title="Fewer than three lines to build this profile from."
              >
                low evidence
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
          <BriefBlock v={v} patchPending={patchPending} onPatch={onPatch} />
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <ProfileBlock label="Source voice observation">
              {v.source_voice_observation}
            </ProfileBlock>
            <ProfileBlock label="Target voice strategy">{v.target_voice_strategy}</ProfileBlock>
          </div>

          {(v.features.length > 0 || v.register_shifts.length > 0) && (
            <EvidenceBlock features={v.features} shifts={v.register_shifts} />
          )}

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
  const glossaryReady = glossaryUsable(book);
  const voiceCompleted = book.voice_extraction_status === "completed";
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
  const speakersModel = useStepModel("speakers");
  const voicesModel = useStepModel("voices");
  const estimate = useVoiceExtractionEstimate(book.id, glossaryReady, {
    speakers: speakersModel.model,
    voices: voicesModel.model,
  });
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

  const briefCount = useMemo(
    () => (voices.data?.entries ?? []).filter((v) => v.translation_brief).length,
    [voices.data?.entries],
  );
  const flaggedPassageCount = useMemo(
    () =>
      (voices.data?.entries ?? []).reduce(
        (n, v) => n + v.selected_passages.filter((p) => p.translation_review).length,
        0,
      ),
    [voices.data?.entries],
  );

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
  const castPass = useRunVoiceCastPass(book.id);
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
    <div className={BOOK_PANEL_SURFACE}>
      <div className={cn(BOOK_PANEL_CONTAINER, "py-8")}>
        <div>
          <h2 className="font-serif text-xl font-medium text-ink-50">Character voices</h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-500">
            Pass 1 attributes every dialogue line to a character. Pass 2 builds voice profiles and
            reference passages over windows of ~{formatNumber(VOICE_EXTRACTION_WINDOW_WORDS)} words
            (~{formatNumber(VOICE_EXTRACTION_OVERLAP_WORDS)} overlap). Each pass has its own model
            under Controls.
          </p>
          {glossaryReady &&
            showStageFinishedToggle(book, "voices", speakersPoll, voiceCompleted) && (
              <div className="mt-3">
                <StageFinishedToggle
                  book={book}
                  stage="voices"
                  running={speakersPoll}
                  completed={voiceCompleted}
                />
              </div>
            )}
        </div>

        {!glossaryReady && (
          <p className="mt-4 rounded-lg border border-warning-border bg-warning-surface px-3 py-2 text-sm text-warning">
            Finish glossary extraction first; voices need at least one character entry.
          </p>
        )}

        <div className="mt-6 grid gap-3 lg:grid-cols-2">
          <PassCard
            eyebrow="Pass 1 · Speaker identification"
            description="Finds every dialogue line and asks who says it and to whom, one part of a chapter at a time. Parts with no dialogue are skipped."
            status={book.speakers_extraction_status}
            unit="part"
            windowsCompleted={book.speakers_extraction_windows_completed}
            windowsTotal={book.speakers_extraction_windows_total}
            lastError={book.speakers_extraction_last_error}
            pass={est?.pass1 ?? null}
            characterCount={null}
            model={est?.pass1.model ?? null}
            modelChoice={speakersModel}
            costState={book.cost_guard.speakers}
            startLabel={
              book.speakers_extraction_status === "completed" ? "Re-run Pass 1" : "Start Pass 1"
            }
            start={startSpeakers}
            continueMut={continueSpeakers}
            stop={stopSpeakers}
            reset={resetSpeakers}
            resetConfirm="This will delete every attributed dialogue line and the speaker map for this book. Continue?"
            nothingToReset={nothingToResetSpeakers}
            disabled={actionsDisabled}
            estimateLoading={estimate.isLoading}
          >
            {/* The speaker map lives here now — never hidden, just
                collapsed with the controls that produce it. */}
            <div className="border-t border-ink-800 pt-3">
              <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink-500">
                Speakers
              </p>
              <SpeakerMapPanel book={book} speakers={speakers} />
            </div>
          </PassCard>

          <PassCard
            eyebrow="Pass 2 · Voices + passages"
            description={
              speakersIncomplete
                ? "Needs a complete Pass 1: each profile is built from all of a character's lines."
                : "One call per character (characters with few lines share one) with all their lines; writes the profile, the evidence behind it and reference passages. Accepted and adjusted profiles are kept on a re-run."
            }
            status={book.voice_extraction_status}
            unit="call"
            windowsCompleted={book.voice_extraction_windows_completed}
            windowsTotal={book.voice_extraction_windows_total}
            lastError={book.voice_extraction_last_error}
            pass={est?.pass2 ?? null}
            characterCount={est?.character_count ?? null}
            model={est?.pass2.model ?? null}
            modelChoice={voicesModel}
            costState={book.cost_guard.voices}
            startLabel={
              book.voice_extraction_status === "completed" ? "Re-run Pass 2" : "Start Pass 2"
            }
            start={startVoice}
            continueMut={continueVoice}
            stop={stopVoice}
            reset={resetVoice}
            resetConfirm="This will permanently delete all character voice profiles and review progress. Continue?"
            nothingToReset={nothingToResetVoice}
            disabled={actionsDisabled || speakersIncomplete}
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
                    : "Rebuild flagged profiles from their stored lines."
                }
                onClick={() => regenerateFlagged.mutate({ model: voicesModel.model })}
              >
                {regenerateFlagged.isPending || book.voice_extraction_status === "running"
                  ? "Regenerating…"
                  : "Run regeneration"}
              </Button>
            </div>
          ) : null}

          {(voices.data?.entries.length ?? 0) > 0 ? (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-ink-800 bg-ink-900 px-4 py-3">
              <p className="text-sm text-ink-300">
                <span className="font-medium tabular-nums text-ink-100">{briefCount}</span> of{" "}
                {voices.data?.entries.length} profiles have a translation brief
                {flaggedPassageCount > 0 ? (
                  <>
                    {" "}
                    ·{" "}
                    <span className="font-medium tabular-nums text-warning">
                      {flaggedPassageCount}
                    </span>{" "}
                    passage{flaggedPassageCount === 1 ? "" : "s"} to check
                  </>
                ) : null}
                .
              </p>
              <Button
                variant="ghost"
                size="sm"
                className="border border-ink-700"
                disabled={book.voice_extraction_status === "running" || castPass.isPending}
                title="Rewrites every brief with the whole cast in view, retranslates the passages you haven't reviewed with the new briefs, and checks them. Briefs you edited on accepted profiles are kept."
                onClick={() => castPass.mutate({ model: voicesModel.model })}
              >
                {castPass.isPending || book.voice_extraction_status === "running"
                  ? "Running…"
                  : "Rebuild briefs"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="border border-ink-700"
                disabled={book.voice_extraction_status === "running" || castPass.isPending}
                title="Keeps the current briefs; retranslates the passages you haven't reviewed with them and checks them."
                onClick={() => castPass.mutate({ model: voicesModel.model, rebuildBriefs: false })}
              >
                Retranslate passages
              </Button>
              {castPass.isError && (
                <p className="text-xs text-danger">
                  {errorDetail(castPass, "Could not start the cast pass.")}
                </p>
              )}
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
              No profiles yet. Run Pass 1, then Pass 2, to build them.
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
