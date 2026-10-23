import { CircleDollarSign, Loader2, PauseCircle } from "lucide-react";

import { Button } from "@/components/ui/Button";
import type { CostGuardState } from "@/lib/api/client";
import { cn } from "@/lib/utils";

function usd(n: number): string {
  return n > 0 && n < 0.01 ? "under $0.01" : `$${n.toFixed(2)}`;
}

/**
 * What a step's run really cost against its estimate, and, when the run
 * paused for going over, the choice to continue.
 *
 * Continue keeps checking against the estimate for the remaining work;
 * Continue without limit finishes the run without checks.
 */
export function CostGuardNotice({
  state,
  paused,
  busy,
  onContinue,
  onContinueWithoutLimit,
  className,
}: {
  state: CostGuardState | undefined;
  /** The run is stopped; only then can a pause reason be acted on. */
  paused: boolean;
  busy: boolean;
  onContinue: () => void;
  onContinueWithoutLimit: () => void;
  className?: string;
}) {
  if (!state || (state.spent_usd === 0 && !state.paused_reason)) return null;
  const over = state.estimate_usd > 0 ? state.spent_usd / state.estimate_usd - 1 : 0;
  return (
    <div className={cn("space-y-2", className)}>
      <p className="inline-flex flex-wrap items-center gap-1.5 font-mono text-[11px] tabular-nums text-ink-400">
        <CircleDollarSign className="h-3.5 w-3.5" aria-hidden />
        Spent {usd(state.spent_usd)} of ~{usd(state.estimate_usd)} estimated
        {state.units_total > 0 && (
          <span className="text-ink-500">
            {" "}
            · {state.units_done}/{state.units_total} done
          </span>
        )}
        {over > 0.1 && <span className="text-warning"> · {Math.round(over * 100)}% over</span>}
        {!state.limit && <span className="text-ink-500"> · no cost limit</span>}
      </p>
      {paused && state.paused_reason && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning-border bg-warning-surface px-3 py-2">
          <PauseCircle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-warning">
            {state.paused_reason} Finished work is kept.
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="border border-ink-700"
            disabled={busy}
            title="Continue, and pause again if the rest also runs more than 10% over"
            onClick={onContinue}
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            Continue
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            title="Finish the run without checking the cost again"
            onClick={onContinueWithoutLimit}
          >
            Continue without limit
          </Button>
        </div>
      )}
    </div>
  );
}
