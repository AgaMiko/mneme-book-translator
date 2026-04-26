import { ChevronDown } from "lucide-react";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import type { BookDetail, GlossaryExtractionEstimate } from "@/lib/api/client";
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
  onOpenTerms: () => void;
}

export function GlossaryExtractionWorkspace({
  book,
  estimate,
  startGlossary,
  continueGlossary,
  stopGlossary,
  onOpenTerms,
}: Props) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-serif text-xl font-medium text-ink-50">Run extraction</h2>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-ink-500">
            One model pass per overlapping text window (~{formatNumber(GLOSSARY_EXTRACTION_WINDOW_WORDS)}{" "}
            words, ~{formatNumber(GLOSSARY_EXTRACTION_OVERLAP_WORDS)} overlap). Extracted terms appear
            below as the run progresses.
          </p>
        </div>
        <button
          type="button"
          onClick={onOpenTerms}
          className={cn(
            "shrink-0 rounded-md border border-ink-700 px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink-200",
            "hover:border-ink-600 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          )}
        >
          Jump to terms ↓
        </button>
      </div>

      {estimate.isLoading && (
        <p className="text-sm text-ink-400" aria-busy="true">
          Calculating estimate…
        </p>
      )}
      {estimate.isError && (
        <p className="text-sm text-danger">Could not load the estimate. Check the API and try again.</p>
      )}
      {estimate.data && estimate.data.window_count === 0 && (
        <p className="text-sm text-ink-300">
          This manuscript has no counted words, so glossary extraction would not run.
        </p>
      )}

      {estimate.data && estimate.data.window_count > 0 && (
        <>
          <details
            className={cn(
              "overflow-hidden rounded-lg border border-ink-800 bg-ink-800",
              "[&[open]_summary_.glossary-chevron]:rotate-180",
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
                {book.glossary_extraction_status === "running" &&
                book.glossary_extraction_windows_total != null &&
                book.glossary_extraction_windows_total > 0 ? (
                  <>
                    Pass{" "}
                    <span className="tabular-nums text-ink-50">
                      {book.glossary_extraction_windows_completed ?? 0}
                    </span>
                    <span className="text-ink-600"> / </span>
                    <span className="tabular-nums text-ink-50">
                      {book.glossary_extraction_windows_total}
                    </span>
                    <span className="mx-2 text-ink-600">·</span>
                  </>
                ) : null}
                <span className="text-ink-400">Estimate</span>
                <span className="mx-2 text-ink-600">·</span>
                <span className="tabular-nums text-ink-100">
                  {formatNumber(estimate.data.estimated_total_tokens)} tok
                </span>
                <span className="mx-2 text-ink-600">·</span>
                <span className="text-accent">{formatUsd(estimate.data.estimated_cost_usd)}</span>
                <span className="mx-2 text-ink-600">·</span>
                <span className="tabular-nums text-ink-400">
                  {formatNumber(estimate.data.window_count)} pass
                  {estimate.data.window_count === 1 ? "" : "es"}
                </span>
              </span>
              <ChevronDown
                className="glossary-chevron h-4 w-4 shrink-0 rotate-0 text-ink-500 transition-transform duration-200 ease-out"
                aria-hidden
              />
            </summary>
            <div className="space-y-3 border-t border-ink-700 px-4 py-4 text-sm leading-relaxed text-ink-300">
              <p>
                <span className="text-ink-100">Glossary extraction</span> will run{" "}
                <span className="font-mono text-ink-100">
                  {formatNumber(estimate.data.window_count)}
                </span>{" "}
                time
                {estimate.data.window_count === 1 ? "" : "s"} (windows of ~
                {formatNumber(GLOSSARY_EXTRACTION_WINDOW_WORDS)} words, ~
                {formatNumber(GLOSSARY_EXTRACTION_OVERLAP_WORDS)} words overlap).
              </p>
              <p>
                We predict roughly{" "}
                <span className="font-mono text-ink-100">
                  {formatNumber(estimate.data.estimated_total_tokens)}
                </span>{" "}
                tokens (~
                <span className="font-mono text-ink-100">
                  {formatNumber(estimate.data.estimated_input_tokens)}
                </span>{" "}
                in, ~
                <span className="font-mono text-ink-100">
                  {formatNumber(estimate.data.estimated_output_tokens)}
                </span>{" "}
                out), model{" "}
                <span className="font-mono text-xs text-ink-100">{estimate.data.model}</span>. At
                the configured rates (
                <span className="font-mono text-ink-100">
                  ${estimate.data.pricing_input_usd_per_mtok.toFixed(3)}
                </span>{" "}
                /{" "}
                <span className="font-mono text-ink-100">
                  ${estimate.data.pricing_output_usd_per_mtok.toFixed(3)}
                </span>{" "}
                per M in/out), about{" "}
                <span className="font-mono text-accent">{formatUsd(estimate.data.estimated_cost_usd)}</span>
                .
              </p>
              <p className="text-xs text-ink-500">
                Estimates follow prompt size and word count; real usage varies. See{" "}
                <a
                  href="https://ai.google.dev/gemini-api/docs/pricing"
                  className="text-ink-400 underline decoration-ink-600 underline-offset-2 hover:text-accent"
                  target="_blank"
                  rel="noreferrer"
                >
                  Google pricing
                </a>
                . Override with{" "}
                <span className="font-mono">GEMINI_INPUT_PRICE_USD_PER_MTOK</span> /{" "}
                <span className="font-mono">GEMINI_OUTPUT_PRICE_USD_PER_MTOK</span>.
              </p>
            </div>
          </details>

          <div className="space-y-3 text-sm">
            {book.glossary_extraction_status === "completed" && (
              <div className="rounded-md border border-success-border bg-success-surface px-3 py-2 text-success">
                <p>Last run finished. Review the terms below.</p>
                <button
                  type="button"
                  onClick={onOpenTerms}
                  className="mt-2 font-mono text-xs uppercase tracking-wider underline underline-offset-2 hover:opacity-80"
                >
                  Jump to terms ↓
                </button>
              </div>
            )}
            {book.glossary_extraction_status === "failed" && (
              <p className="text-danger">
                Extraction failed. Fix the issue (API key, quota), then Continue to resume or
                start a new run.
              </p>
            )}
            {book.glossary_extraction_status === "cancelled" && (
              <p className="text-warning">
                Stopped mid-run. Partial results are kept. Continue to resume or start fresh.
              </p>
            )}
          </div>

          {startGlossary.isError && (
            <p className="text-sm text-danger">
              {startGlossary.error instanceof ApiError
                ? startGlossary.error.detail
                : "Could not start extraction."}
            </p>
          )}
          {continueGlossary.isError && (
            <p className="text-sm text-danger">
              {continueGlossary.error instanceof ApiError
                ? continueGlossary.error.detail
                : "Could not continue extraction."}
            </p>
          )}
          {stopGlossary.isError && (
            <p className="text-sm text-danger">
              {stopGlossary.error instanceof ApiError
                ? stopGlossary.error.detail
                : "Could not request stop."}
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** Slim sticky bar: primary actions only (sits below the scroll area). */
export function GlossaryExtractionActionBar({
  book,
  startGlossary,
  continueGlossary,
  stopGlossary,
  enabled,
}: Pick<Props, "book" | "startGlossary" | "continueGlossary" | "stopGlossary"> & {
  enabled: boolean;
}) {
  if (!enabled) return null;
  return (
    <div
      className={cn(
        "sticky bottom-0 z-10 flex flex-wrap items-center justify-end gap-2",
        "border-t border-ink-800 bg-ink-900/95 px-4 py-2.5 backdrop-blur-sm",
      )}
    >
      {book.glossary_extraction_status === "running" && (
        <button
          type="button"
          disabled={stopGlossary.isPending}
          onClick={() => stopGlossary.mutate()}
          className={cn(
            "inline-flex items-center gap-2 rounded-md border border-ink-600 px-3 py-1.5",
            "font-mono text-xs uppercase tracking-wider text-ink-200",
            "hover:border-danger-border hover:bg-danger-surface hover:text-danger",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger",
            "disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {stopGlossary.isPending ? "Stopping…" : "Stop"}
        </button>
      )}
      {(book.glossary_extraction_status === "failed" ||
        book.glossary_extraction_status === "cancelled") && (
        <button
          type="button"
          disabled={continueGlossary.isPending}
          onClick={() => continueGlossary.mutate()}
          className={cn(
            "inline-flex items-center gap-2 rounded-md border border-success-border px-3 py-1.5",
            "font-mono text-xs uppercase tracking-wider text-success",
            "hover:bg-success-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success",
            "disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {continueGlossary.isPending ? "Continuing…" : "Continue"}
        </button>
      )}
      <button
        type="button"
        disabled={book.glossary_extraction_status === "running" || startGlossary.isPending}
        onClick={() => startGlossary.mutate()}
        className={cn(
          "inline-flex items-center gap-2 rounded-md border border-accent px-3 py-1.5",
          "font-mono text-xs uppercase tracking-wider text-accent",
          "bg-accent-soft hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          "disabled:cursor-not-allowed disabled:opacity-40",
        )}
      >
        {book.glossary_extraction_status === "running"
          ? "Running…"
          : startGlossary.isPending
            ? "Starting…"
            : "Start new run"}
      </button>
    </div>
  );
}
