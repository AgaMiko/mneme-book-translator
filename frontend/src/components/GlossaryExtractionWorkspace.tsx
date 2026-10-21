import { useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, Circle, Loader2, PauseCircle } from "lucide-react";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import { Button } from "@/components/ui/Button";
import { useGlossaryImportSources, useImportGlossary } from "@/lib/api/hooks";
import type { BookDetail, GlossaryExtractionEstimate, GlossaryRunMeta } from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import {
  GLOSSARY_EXTRACTION_OVERLAP_WORDS,
  GLOSSARY_EXTRACTION_WINDOW_WORDS,
} from "@/constants/glossaryExtraction";
import { cn, formatNumber } from "@/lib/utils";

function formatUsd(n: number): string {
  if (n > 0 && n < 0.01) return "under $0.01";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: n < 1 ? 3 : 2,
  }).format(n);
}

type StartMut = UseMutationResult<{ status: "accepted"; book_id: string }, Error, void>;
type StopMut = UseMutationResult<{ status: "accepted"; book_id: string }, Error, void>;

interface Props {
  book: BookDetail;
  estimate: UseQueryResult<GlossaryExtractionEstimate, Error>;
  startGlossary: StartMut;
  continueGlossary: StartMut;
  stopGlossary: StopMut;
  expandGlossary: StartMut;
  /** Metadata for the latest run, when one exists. */
  run: GlossaryRunMeta | null;
}

/**
 * One card, at the top of the glossary scroll area, holding everything
 * about the *run* — so everything below it can be about the *terms*.
 *
 * The default state is a single line: what the last run did. The
 * estimate, the pricing note, and the four run controls live behind one
 * disclosure, because on any given visit you are far more likely to be
 * reviewing terms than starting a pass. This replaces both the old
 * sticky bottom action bar and the always-visible estimate panel.
 */
export function GlossaryExtractionWorkspace({
  book,
  estimate,
  startGlossary,
  continueGlossary,
  stopGlossary,
  expandGlossary,
  run,
}: Props) {
  const [controlsOpen, setControlsOpen] = useState(book.glossary_extraction_status === "idle");
  const status = book.glossary_extraction_status;
  const running = status === "running";
  const runnable = Boolean(estimate.data && estimate.data.window_count > 0);

  const mutationError =
    errorDetail(startGlossary.error, "Could not start extraction.", startGlossary.isError) ??
    errorDetail(
      continueGlossary.error,
      "Could not continue extraction.",
      continueGlossary.isError,
    ) ??
    errorDetail(stopGlossary.error, "Could not request stop.", stopGlossary.isError) ??
    errorDetail(expandGlossary.error, "Could not start expanding.", expandGlossary.isError);

  return (
    <section className="rounded-lg border border-ink-800 bg-ink-800" aria-label="Extraction run">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <RunStatusIcon status={status} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] leading-snug text-ink-100">{summaryLine(book, run)}</p>
          <p className="mt-0.5 font-mono text-[10px] text-ink-500">
            {run ? (
              <>
                {run.model && (
                  <>
                    {run.model}
                    <span className="text-ink-600"> · </span>
                  </>
                )}
                {formatWhen(run.started_at)}
              </>
            ) : (
              <span className="uppercase tracking-wider">
                windows ~{formatNumber(GLOSSARY_EXTRACTION_WINDOW_WORDS)} words · ~
                {formatNumber(GLOSSARY_EXTRACTION_OVERLAP_WORDS)} overlap
              </span>
            )}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={controlsOpen}
          onClick={() => setControlsOpen((o) => !o)}
        >
          Run controls
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 transition-transform duration-200 ease-out",
              controlsOpen && "rotate-180",
            )}
            aria-hidden
          />
        </Button>
      </div>

      {controlsOpen && (
        <div className="border-t border-ink-700 px-4 py-4">
          {estimate.isLoading && (
            <p className="text-sm text-ink-400" aria-busy="true">
              Calculating estimate…
            </p>
          )}
          {estimate.isError && (
            <p className="text-sm text-danger">
              Could not load the estimate. Check the API and try again.
            </p>
          )}
          {estimate.data && estimate.data.window_count === 0 && (
            <p className="text-sm text-ink-300">
              This manuscript has no counted words, so glossary extraction would not run.
            </p>
          )}

          {estimate.data && estimate.data.window_count > 0 && (
            <>
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <EstimateCell label="Passes" value={formatNumber(estimate.data.window_count)} />
                <EstimateCell
                  label="Tokens"
                  value={`${formatNumber(estimate.data.estimated_total_tokens)}`}
                  detail={`${formatNumber(estimate.data.estimated_input_tokens)} in · ${formatNumber(estimate.data.estimated_output_tokens)} out`}
                />
                <EstimateCell
                  label="Cost"
                  value={formatUsd(estimate.data.estimated_cost_usd)}
                  accent
                />
                <EstimateCell label="Model" value={estimate.data.model} />
              </dl>

              <p className="mt-3 text-xs leading-relaxed text-ink-500">
                Estimates follow prompt size and word count; real usage varies. At the configured
                rates (${estimate.data.pricing_input_usd_per_mtok.toFixed(3)} / $
                {estimate.data.pricing_output_usd_per_mtok.toFixed(3)} per M in/out). See{" "}
                <a
                  href="https://ai.google.dev/gemini-api/docs/pricing"
                  className="text-ink-400 underline decoration-ink-600 underline-offset-2 hover:text-accent"
                  target="_blank"
                  rel="noreferrer"
                >
                  Google pricing
                </a>
                . Override with <span className="font-mono">GEMINI_INPUT_PRICE_USD_PER_MTOK</span> /{" "}
                <span className="font-mono">GEMINI_OUTPUT_PRICE_USD_PER_MTOK</span>.
              </p>
            </>
          )}

          {/* Always mounted, disabled when unavailable. A control that
              appears and disappears is harder to learn than one that
              stays put and greys out. */}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button
              variant="accent"
              size="sm"
              disabled={!runnable || running || startGlossary.isPending}
              onClick={() => startGlossary.mutate()}
            >
              {running ? "Running…" : startGlossary.isPending ? "Starting…" : "Start new run"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={
                !runnable ||
                continueGlossary.isPending ||
                !(status === "failed" || status === "cancelled")
              }
              title={
                status === "failed" || status === "cancelled"
                  ? "Resume from the last completed window"
                  : "Only available after a stopped or failed run"
              }
              onClick={() => continueGlossary.mutate()}
            >
              {continueGlossary.isPending
                ? "Continuing…"
                : (status === "failed" || status === "cancelled") &&
                    book.glossary_extraction_windows_completed
                  ? `Continue from pass ${book.glossary_extraction_windows_completed}`
                  : "Continue"}
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={!runnable || !running || stopGlossary.isPending}
              title={running ? "Stop after the current window" : "Only available while running"}
              onClick={() => stopGlossary.mutate()}
            >
              {stopGlossary.isPending ? "Stopping…" : "Stop"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={!runnable || !run || running || expandGlossary.isPending}
              title={
                run
                  ? "Read the whole manuscript again and add terms that are missing"
                  : "Run an extraction or import a glossary first"
              }
              onClick={() => expandGlossary.mutate()}
            >
              {expandGlossary.isPending ? "Starting…" : "Expand glossary"}
            </Button>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-500">
            <span className="text-ink-400">Expand glossary</span> reads the whole manuscript again
            and adds terms the glossary is missing, as proposals to review. Terms you accepted or
            removed stay as they are; it may only add spelling and case variants to them. Costs
            about the same as a new run.
          </p>

          <ImportGlossary book={book} disabled={running} />

          {mutationError && (
            <p className="mt-3 text-sm text-danger" role="alert">
              {mutationError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Copy the reviewed terms of another book's glossary into this one, for a
 * new version of the same manuscript or the next book in a series.
 */
function ImportGlossary({ book, disabled }: { book: BookDetail; disabled: boolean }) {
  const sources = useGlossaryImportSources(book.id, true);
  const importGlossary = useImportGlossary(book.id);
  const [sourceId, setSourceId] = useState("");
  const chosen = sourceId || sources.data?.[0]?.book_id || "";

  return (
    <div className="mt-5 border-t border-ink-700 pt-4">
      <h3 className="text-[13px] font-medium text-ink-100">Import from another book</h3>
      <p className="mt-1 text-xs leading-relaxed text-ink-500">
        Copies the terms you accepted or removed in another book. Unreviewed proposals are not
        copied. If a term is already accepted or removed here, this book&apos;s decision stays; if
        it is only a proposal here, the other book&apos;s decision replaces it. Then use Expand
        glossary to add the terms only this book has.
      </p>

      {sources.isLoading && <p className="mt-2 text-xs text-ink-400">Looking for books…</p>}
      {sources.data && sources.data.length === 0 && (
        <p className="mt-2 text-xs text-ink-400">No other book has reviewed glossary terms yet.</p>
      )}
      {sources.data && sources.data.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select
            value={chosen}
            onChange={(e) => {
              setSourceId(e.target.value);
              importGlossary.reset();
            }}
            className="min-w-0 max-w-full flex-1 rounded-md border border-ink-700 bg-ink-900 px-2 py-1.5 text-[13px] text-ink-100"
            aria-label="Book to import from"
          >
            {sources.data.map((s) => (
              <option key={s.book_id} value={s.book_id}>
                {s.title || s.original_filename || "Untitled"} · uploaded {formatWhen(s.created_at)}{" "}
                · {s.accepted} accepted, {s.removed} removed
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled || !chosen || importGlossary.isPending}
            onClick={() => importGlossary.mutate(chosen)}
          >
            {importGlossary.isPending ? "Importing…" : "Import"}
          </Button>
        </div>
      )}

      {importGlossary.data && (
        <p className="mt-2 text-xs text-success" role="status">
          Imported: {importGlossary.data.added} new, {importGlossary.data.updated} proposals
          replaced, {importGlossary.data.kept} already reviewed here and kept.
        </p>
      )}
      {importGlossary.isError && (
        <p className="mt-2 text-xs text-danger" role="alert">
          {errorDetail(importGlossary.error, "Could not import the glossary.", true)}
        </p>
      )}
    </div>
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

function RunStatusIcon({ status }: { status: BookDetail["glossary_extraction_status"] }) {
  const cls = "h-4 w-4 shrink-0";
  if (status === "running") {
    return <Loader2 className={cn(cls, "animate-spin text-accent")} aria-hidden />;
  }
  if (status === "completed") {
    return <CheckCircle2 className={cn(cls, "text-success")} aria-hidden />;
  }
  if (status === "failed") return <AlertCircle className={cn(cls, "text-danger")} aria-hidden />;
  if (status === "cancelled") {
    return <PauseCircle className={cn(cls, "text-warning")} aria-hidden />;
  }
  return <Circle className={cn(cls, "text-ink-500")} aria-hidden />;
}

function formatWhen(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/** One sentence describing where the last (or current) run stands. */
function summaryLine(book: BookDetail, run: GlossaryRunMeta | null): string {
  const done = book.glossary_extraction_windows_completed ?? 0;
  const total = book.glossary_extraction_windows_total ?? 0;
  const progress = total > 0 ? `${done}/${total}` : null;

  switch (book.glossary_extraction_status) {
    case "running":
      return progress ? `Extracting — pass ${progress}.` : "Extraction in flight.";
    case "completed":
      if (run) {
        const terms = `${formatNumber(run.entry_count)} term${run.entry_count === 1 ? "" : "s"}`;
        return total > 0
          ? `Extraction complete — ${terms} from ${formatNumber(total)} passes.`
          : `Extraction complete — ${terms}.`;
      }
      return "Last run finished. Terms are below, ready for review.";
    case "cancelled":
      return progress
        ? `Stopped after ${progress}. Partial results are kept — continue or start fresh.`
        : "Stopped mid-run. Partial results are kept.";
    case "failed":
      return "Last run failed. Fix the cause (API key, quota), then continue or start fresh.";
    default:
      return "No run yet. Mneme reads the full text in overlapping windows.";
  }
}

function errorDetail(error: Error | null, fallback: string, isError: boolean): string | null {
  if (!isError) return null;
  return error instanceof ApiError ? error.detail : fallback;
}
