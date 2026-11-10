import { useState } from "react";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import { CostGuardNotice } from "@/components/book/CostGuardNotice";
import { ModelPicker } from "@/components/book/ModelPicker";
import { StepRunBar } from "@/components/book/StepRunBar";
import { Button } from "@/components/ui/Button";
import type { StepModel } from "@/hooks/useStepModel";
import { useGlossaryImportSources, useImportGlossary } from "@/lib/api/hooks";
import type {
  BookDetail,
  GlossaryExtractionEstimate,
  GlossaryRunMeta,
  RunOptions,
} from "@/lib/api/client";
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

type StartMut = UseMutationResult<
  { status: "accepted"; book_id: string },
  Error,
  RunOptions | void
>;
type StopMut = UseMutationResult<{ status: "accepted"; book_id: string }, Error, void>;

interface Props {
  book: BookDetail;
  estimate: UseQueryResult<GlossaryExtractionEstimate, Error>;
  startGlossary: StartMut;
  continueGlossary: StartMut;
  stopGlossary: StopMut;
  expandGlossary: StartMut;
  /** The model the next run (start, continue or expand) uses; the estimate follows it. */
  model: StepModel;
  /** Metadata for the latest run, when one exists. */
  run: GlossaryRunMeta | null;
}

/**
 * The glossary run, as the step's run bar: one line on where the run
 * stands with the action that fits (build, stop or continue). The model,
 * the estimate, the rarer actions (new run, expand) and the import from
 * another book are under Settings, so the terms below start near the top.
 */
export function GlossaryExtractionWorkspace({
  book,
  estimate,
  startGlossary,
  continueGlossary,
  stopGlossary,
  expandGlossary,
  model,
  run,
}: Props) {
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

  const resumable = status === "failed" || status === "cancelled";
  const doneWindows = book.glossary_extraction_windows_completed;
  const continueLabel = continueGlossary.isPending
    ? "Continuing…"
    : resumable && doneWindows
      ? `Continue from pass ${doneWindows}`
      : "Continue";

  // The one action that fits the state; the rest are under Settings.
  const action = running ? (
    <Button
      variant="danger"
      size="sm"
      disabled={stopGlossary.isPending}
      title="Stop after the current window"
      onClick={() => stopGlossary.mutate()}
    >
      {stopGlossary.isPending ? "Stopping…" : "Stop"}
    </Button>
  ) : resumable && !book.cost_guard.glossary?.paused_reason ? (
    // A run paused over its cost has its own Continue in the notice below.
    <Button
      variant="accent"
      size="sm"
      disabled={!runnable || continueGlossary.isPending}
      title="Resume from the last completed window"
      onClick={() => continueGlossary.mutate({ model: model.model })}
    >
      {continueLabel}
    </Button>
  ) : status === "idle" ? (
    <Button
      variant="accent"
      size="sm"
      disabled={!runnable || startGlossary.isPending}
      onClick={() => startGlossary.mutate({ model: model.model })}
    >
      {startGlossary.isPending
        ? "Starting…"
        : estimate.data
          ? `Build glossary · ~${formatUsd(estimate.data.estimated_cost_usd)}`
          : "Build glossary"}
    </Button>
  ) : null;

  const settings = (
    <>
      <ModelPicker choice={model} disabled={running} className="mb-4" />
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
            <EstimateCell label="Cost" value={formatUsd(estimate.data.estimated_cost_usd)} accent />
            <EstimateCell label="Model" value={estimate.data.model} />
          </dl>

          <p className="mt-3 text-xs leading-relaxed text-ink-500">
            Mneme reads the text in overlapping windows of ~
            {formatNumber(GLOSSARY_EXTRACTION_WINDOW_WORDS)} words (~
            {formatNumber(GLOSSARY_EXTRACTION_OVERLAP_WORDS)} overlap). The estimate is based on the
            manuscript&apos;s length and the size of earlier runs, including the model&apos;s
            thinking; real usage varies. Priced at $
            {estimate.data.pricing_input_usd_per_mtok.toFixed(2)} / $
            {estimate.data.pricing_output_usd_per_mtok.toFixed(2)} per million input / output tokens
            (OpenAI models on the half-price Flex tier).
          </p>
        </>
      )}

      {/* Always mounted, disabled when unavailable. A control that
          appears and disappears is harder to learn than one that
          stays put and greys out. */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          className="border border-ink-700"
          disabled={!runnable || running || startGlossary.isPending}
          onClick={() => startGlossary.mutate({ model: model.model })}
        >
          {running ? "Running…" : startGlossary.isPending ? "Starting…" : "Start new run"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={!runnable || continueGlossary.isPending || !resumable}
          title={
            resumable
              ? "Resume from the last completed window"
              : "Only available after a stopped or failed run"
          }
          onClick={() => continueGlossary.mutate({ model: model.model })}
        >
          {continueLabel}
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
          onClick={() => expandGlossary.mutate({ model: model.model })}
        >
          {expandGlossary.isPending ? "Starting…" : "Expand glossary"}
        </Button>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink-500">
        <span className="text-ink-400">Expand glossary</span> reads the whole manuscript again and
        adds terms the glossary is missing, as proposals to review. Terms you accepted or removed
        stay as they are; it may only add spelling and case variants to them. Costs about the same
        as a new run.
      </p>

      <ImportGlossary book={book} disabled={running} />
    </>
  );

  const paused =
    status === "cancelled" && book.cost_guard.glossary?.paused_reason ? (
      <CostGuardNotice
        state={book.cost_guard.glossary}
        paused
        showSpent={false}
        busy={continueGlossary.isPending}
        onContinue={() => continueGlossary.mutate({ model: model.model })}
        onContinueWithoutLimit={() =>
          continueGlossary.mutate({ model: model.model, costLimit: false })
        }
      />
    ) : null;

  const notice =
    paused || mutationError ? (
      <>
        {paused}
        {mutationError && (
          <p className={cn("text-sm text-danger", paused && "mt-2")} role="alert">
            {mutationError}
          </p>
        )}
      </>
    ) : null;

  return (
    <StepRunBar
      label="Glossary run"
      status={status}
      summary={summaryLine(book, run)}
      meta={run ? [run.model, formatWhen(run.started_at)].filter(Boolean).join(" · ") : null}
      cost={book.cost_guard.glossary}
      action={action}
      notice={notice}
      settings={settings}
      settingsOpenByDefault={status === "idle"}
    />
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

/** One short sentence on where the last (or current) run stands. */
function summaryLine(book: BookDetail, run: GlossaryRunMeta | null): string {
  const done = book.glossary_extraction_windows_completed ?? 0;
  const total = book.glossary_extraction_windows_total ?? 0;
  const progress = total > 0 ? `${done}/${total}` : null;

  switch (book.glossary_extraction_status) {
    case "running":
      return progress ? `Building the glossary · pass ${progress}` : "Building the glossary…";
    case "completed":
      if (run) {
        const terms = `${formatNumber(run.entry_count)} term${run.entry_count === 1 ? "" : "s"}`;
        return total > 0
          ? `Glossary built · ${terms} from ${formatNumber(total)} passes`
          : `Glossary built · ${terms}`;
      }
      return "Glossary built";
    case "cancelled":
      return progress
        ? `Stopped at pass ${progress} · the terms found so far are kept`
        : "Stopped · the terms found so far are kept";
    case "failed":
      return "The run failed. Check the API key or quota, then continue.";
    default:
      return "No glossary yet. Mneme reads the whole book and proposes terms for you to review.";
  }
}

function errorDetail(error: Error | null, fallback: string, isError: boolean): string | null {
  if (!isError) return null;
  return error instanceof ApiError ? error.detail : fallback;
}
