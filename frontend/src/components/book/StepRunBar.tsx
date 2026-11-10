import { AlertCircle, CheckCircle2, ChevronDown, Circle, Loader2, PauseCircle } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import type { CostGuardState } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { costSummary } from "./cost";

export type RunStatus = "idle" | "running" | "completed" | "failed" | "cancelled";

/**
 * The run of a step, in one line, at the top of the step page.
 *
 * A step has two jobs: the model's run and your review of what it made.
 * The review is where the time goes, so the run takes one line: where it
 * stands, what it cost, and the one action that fits (start, stop or
 * continue). Models, estimates and the rarer actions sit under Settings.
 *
 * `notice` is for something that needs you now, such as a run paused for
 * going over its estimate. It shows under the line, never folded away.
 */
export function StepRunBar({
  status,
  summary,
  meta,
  cost,
  action,
  notice,
  settings,
  settingsOpenByDefault = false,
  label,
}: {
  status: RunStatus;
  /** One sentence on where the run stands. */
  summary: ReactNode;
  /** Small print after the summary: model, date. */
  meta?: ReactNode;
  cost?: CostGuardState;
  /** The one action that fits the state. */
  action?: ReactNode;
  notice?: ReactNode;
  settings?: ReactNode;
  settingsOpenByDefault?: boolean;
  /** Accessible name of the section, e.g. "Glossary run". */
  label: string;
}) {
  const [open, setOpen] = useState(settingsOpenByDefault);
  const spent = costSummary(cost);

  return (
    <section className="rounded-lg border border-ink-800 bg-ink-800" aria-label={label}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
        <StatusIcon status={status} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] leading-snug text-ink-100">{summary}</p>
          {(meta || spent) && (
            <p className="mt-0.5 font-mono text-[10.5px] tabular-nums text-ink-500">
              {meta}
              {meta && spent && <span className="text-ink-600"> · </span>}
              {spent}
            </p>
          )}
        </div>
        {action}
        {settings && (
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="text-ink-300"
          >
            Settings
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 transition-transform duration-200 ease-out",
                open && "rotate-180",
              )}
              aria-hidden
            />
          </Button>
        )}
      </div>
      {notice && <div className="border-t border-ink-700 px-4 py-2.5">{notice}</div>}
      {settings && open && <div className="border-t border-ink-700 px-4 py-4">{settings}</div>}
    </section>
  );
}

function StatusIcon({ status }: { status: RunStatus }) {
  const cls = "h-4 w-4 shrink-0";
  switch (status) {
    case "running":
      return <Loader2 className={cn(cls, "animate-spin text-accent")} aria-label="running" />;
    case "completed":
      return <CheckCircle2 className={cn(cls, "text-success")} aria-label="finished" />;
    case "failed":
      return <AlertCircle className={cn(cls, "text-danger")} aria-label="failed" />;
    case "cancelled":
      return <PauseCircle className={cn(cls, "text-warning")} aria-label="stopped" />;
    default:
      return <Circle className={cn(cls, "text-ink-500")} aria-label="not started" />;
  }
}
