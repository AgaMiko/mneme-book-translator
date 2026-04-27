import { useEffect, useMemo, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Braces,
  Building2,
  Check,
  ChevronDown,
  GitMerge,
  Library,
  Loader2,
  MapPin,
  MoreHorizontal,
  PenLine,
  Shapes,
  Sparkles,
  Trash2,
  UserRound,
  XCircle,
} from "lucide-react";

import type {
  GlossaryEntryPatchBody,
  GlossaryRunMeta,
  GlossarySelectOption,
  GlossaryWorkingEntry,
} from "@/lib/api/client";
import {
  GLOSSARY_EXTRACTION_OVERLAP_WORDS,
  GLOSSARY_EXTRACTION_WINDOW_WORDS,
} from "@/constants/glossaryExtraction";
import { usePatchGlossaryWorkingEntry, useWorkingGlossary } from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

/**
 * Term-type presentation. Color is intentionally NOT part of the
 * categorical mapping — every chip and badge uses the same neutral
 * surface so the brand palette stays coherent. Distinction across types
 * is carried by the icon, not by a per-type color. Active filter state
 * (when one type is isolated) is signalled via the clay accent border;
 * everything else dims.
 */
const TERM_TYPE_ICON: Record<string, LucideIcon> = {
  character_name: UserRound,
  place_name: MapPin,
  organization: Building2,
  lore_term: Sparkles,
  cultural_term: Library,
  specialized_usage: Braces,
};

function iconFor(id: string): LucideIcon {
  return TERM_TYPE_ICON[id] ?? Shapes;
}

function canonicalTermTypeId(raw: string, optionIds: readonly string[]): string {
  const mapped = raw === "magic_term" ? "lore_term" : raw;
  return optionIds.includes(mapped) ? mapped : "other";
}

function labelSuggestion(raw: string, options: GlossarySelectOption[]): string {
  const o = options.find((x) => x.id === raw);
  return o?.label ?? raw.replace(/_/g, " ");
}

function readTranslation(rec: Record<string, unknown>) {
  const suggestion =
    typeof rec.suggestion === "string" ? rec.suggestion : "translate";
  const proposed_target =
    typeof rec.proposed_target === "string" || rec.proposed_target === null
      ? (rec.proposed_target as string | null)
      : null;
  const rationale = typeof rec.rationale === "string" ? rec.rationale : "";
  const rawAlts = rec.alternative_targets;
  const fromApi: string[] = Array.isArray(rawAlts)
    ? rawAlts.filter((x): x is string => typeof x === "string" && x.trim() !== "").map((x) => x.trim())
    : [];
  const seen = new Set<string>();
  const ptKey = (proposed_target ?? "").trim().toLowerCase();
  if (ptKey) seen.add(ptKey);
  const alternative_targets: string[] = [];
  for (const a of fromApi) {
    const k = a.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    alternative_targets.push(a);
    if (alternative_targets.length >= 5) break;
  }
  return { suggestion, proposed_target, rationale, alternative_targets };
}

/** Not yet explicitly accepted (rejected rows are intentionally out of scope). */
function isAwaitingAcceptance(e: GlossaryWorkingEntry): boolean {
  return e.status === "proposed" || e.status === "adjusted";
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

function runStatusTone(status: string): string {
  if (status === "completed") return "text-success";
  if (status === "running") return "text-accent";
  if (status === "cancelled") return "text-warning";
  if (status === "failed") return "text-danger";
  return "text-ink-400";
}

function ReviewProgressLine({
  awaiting,
  accepted,
  removed,
}: {
  awaiting: number;
  accepted: number;
  removed: number;
}) {
  if (awaiting + accepted + removed === 0) return null;
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
      {removed > 0 ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-ink-700/80 bg-ink-950/60 px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-ink-500">
          {removed} removed
        </span>
      ) : null}
    </div>
  );
}

interface Props {
  bookId: string;
  pollWhileRunning: boolean;
}

export function GlossaryReviewPanel({ bookId, pollWhileRunning }: Props) {
  const patchGlossaryEntry = usePatchGlossaryWorkingEntry(bookId);
  const { data, isLoading, isError, error } = useWorkingGlossary(bookId, {
    enabled: true,
    refetchIntervalMs: pollWhileRunning ? 2000 : false,
  });
  /**
   * Filter mode: single-select isolation. `null` = show all term types;
   * a string value = show only entries of that type. Click the active
   * type to clear; click another to switch. Inclusion semantics (focus
   * on one) reads more naturally than the previous exclusion set
   * (subtract noise) for a glossary the user is reviewing one bucket
   * at a time.
   */
  const [isolatedTermType, setIsolatedTermType] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [pendingOnly, setPendingOnly] = useState(false);

  useEffect(() => {
    if (
      openId !== null &&
      data?.entries &&
      !data.entries.some((e) => e.id === openId)
    ) {
      setOpenId(null);
    }
  }, [data?.entries, openId]);

  useEffect(() => {
    if (openId === null || !data?.entries) return;
    const row = data.entries.find((e) => e.id === openId);
    if (!row) return;
    if (pendingOnly && !isAwaitingAcceptance(row)) setOpenId(null);
  }, [pendingOnly, openId, data?.entries]);

  const termTypeOptionIds = useMemo(
    () => (data?.term_type_options ?? []).map((o) => o.id),
    [data?.term_type_options],
  );

  const reviewStats = useMemo(() => {
    const all = data?.entries ?? [];
    let awaiting = 0;
    let accepted = 0;
    let removed = 0;
    for (const e of all) {
      if (isAwaitingAcceptance(e)) awaiting += 1;
      else if (e.status === "accepted") accepted += 1;
      else if (e.status === "rejected") removed += 1;
    }
    return { awaiting, accepted, removed, total: all.length };
  }, [data?.entries]);

  /** Entries considered by type chips and list — full run or pending-only. */
  const entriesInScope = useMemo(() => {
    const all = data?.entries ?? [];
    if (!pendingOnly) return all;
    return all.filter(isAwaitingAcceptance);
  }, [data?.entries, pendingOnly]);

  /**
   * Per-type counts over ``entriesInScope``. Isolation is ignored so every
   * chip shows the count you would get by clicking it (within the current
   * pending / full scope).
   */
  const termTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const id of termTypeOptionIds) counts[id] = 0;
    for (const e of entriesInScope) {
      const id = canonicalTermTypeId(e.term_type, termTypeOptionIds);
      counts[id] = (counts[id] ?? 0) + 1;
    }
    return counts;
  }, [entriesInScope, termTypeOptionIds]);

  const filtered = useMemo(() => {
    if (!entriesInScope.length) return [];
    return entriesInScope.filter((e) => {
      const tid = canonicalTermTypeId(e.term_type, termTypeOptionIds);
      if (isolatedTermType !== null && tid !== isolatedTermType) return false;
      return true;
    });
  }, [entriesInScope, isolatedTermType, termTypeOptionIds]);

  /**
   * Click semantics:
   * - Click the active type → clear (return to "all types").
   * - Click any other type → switch isolation to it.
   * - No additive multi-select; that's a different mental model and
   *   would need a different UI affordance.
   */
  const selectOnlyTermType = (id: string) => {
    setIsolatedTermType((prev) => (prev === id ? null : id));
  };

  return (
    <section
      id="glossary-review"
      aria-labelledby="glossary-review-heading"
      className="mb-14 scroll-mt-6"
    >
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-8">
        <div className="min-w-0 flex-1">
          <h2
            id="glossary-review-heading"
            className="font-serif text-2xl font-semibold tracking-tight text-ink-50"
          >
            Working glossary
          </h2>
          <p className="mt-1 max-w-prose text-xs leading-relaxed text-ink-500">
            Occurrences and the first-window index are counted across the full manuscript
            (not the model), using the same ~{formatNumber(GLOSSARY_EXTRACTION_WINDOW_WORDS)}
            -word windows (~{formatNumber(GLOSSARY_EXTRACTION_OVERLAP_WORDS)} overlap) as
            extraction. Translation targets default to the source form when the model left
            them blank.
          </p>
          <RunSubtitle run={data?.run ?? null} isLoading={isLoading} />
          {!isLoading && data && data.entries.length > 0 ? (
            <ReviewProgressLine
              awaiting={reviewStats.awaiting}
              accepted={reviewStats.accepted}
              removed={reviewStats.removed}
            />
          ) : null}
        </div>
        <div
          className={cn(
            "shrink-0 rounded-xl border border-ink-800/80 bg-ink-900/35 p-3 shadow-sm ring-1 ring-black/5",
            "sm:p-3.5",
          )}
        >
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              role="switch"
              aria-checked={pendingOnly}
              aria-label={
                pendingOnly
                  ? "Showing pending terms only. Press to show the full glossary."
                  : "Showing the full glossary. Press to show only terms awaiting acceptance."
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
            <div className="min-w-0">
              <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                Pending only
              </p>
              <p className="font-sans text-[11px] leading-snug text-ink-500">
                Focus rows that still need acceptance
              </p>
            </div>
          </div>
        </div>
      </div>

      {!isLoading && !isError && data && data.entries.length > 0 && (
        <div
          className="mb-6 rounded-xl border border-ink-800/80 bg-ink-900/35 px-3 py-3 shadow-sm ring-1 ring-black/5 sm:px-4"
          role="group"
          aria-label="Filter by term type"
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Term types
              {pendingOnly ? (
                <span className="ml-1.5 font-sans normal-case text-ink-600">
                  (pending list)
                </span>
              ) : null}
            </p>
            {isolatedTermType !== null && (
              <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                Showing only{" "}
                <span className="text-accent">
                  {(data.term_type_options ?? []).find(
                    (o) => o.id === isolatedTermType,
                  )?.label ?? isolatedTermType.replace(/_/g, " ")}
                </span>
                {" · "}
                <button
                  type="button"
                  onClick={() => setIsolatedTermType(null)}
                  className={cn(
                    "underline decoration-ink-600 underline-offset-2",
                    "hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  )}
                >
                  show all
                </button>
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {(data.term_type_options ?? []).map((opt) => {
              const id = opt.id;
              const Icon = iconFor(id);
              const isActive = isolatedTermType === id;
              const isDimmed = isolatedTermType !== null && !isActive;
              const count = termTypeCounts[id] ?? 0;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={isActive}
                  title={
                    isActive
                      ? `Showing only ${opt.label} — click to clear`
                      : `Show only ${opt.label}`
                  }
                  onClick={() => selectOnlyTermType(id)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5",
                    "font-mono text-[11px] font-medium transition-all duration-150",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    isActive
                      ? "border-accent bg-accent-soft text-ink-50"
                      : "border-ink-700 bg-ink-800 text-ink-200 hover:border-ink-600 hover:text-ink-100",
                    isDimmed && "opacity-50",
                  )}
                >
                  <Icon
                    className={cn(
                      "h-3.5 w-3.5 shrink-0",
                      isActive ? "text-accent" : "text-ink-400",
                    )}
                    aria-hidden
                  />
                  <span>{opt.label}</span>
                  <span className="min-w-[1.25rem] tabular-nums opacity-70">
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {isLoading && (
        <p className="text-sm text-ink-400" aria-busy="true">
          Loading glossary…
        </p>
      )}

      {isError && (
        <p className="text-sm text-danger" role="alert">
          {error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {!isLoading && !isError && data && !data.run && (
        <p className="max-w-prose text-sm leading-relaxed text-ink-400">
          No extraction run exists for this book yet. When you start a run, terms
          will appear here as each pass finishes.
        </p>
      )}

      {!isLoading && !isError && data?.run && data.entries.length === 0 && (
        <p className="max-w-prose text-sm leading-relaxed text-ink-400">
          This run has no stored terms yet. If extraction is still running, check
          back in a moment.
        </p>
      )}

      {!isLoading && !isError && filtered.length > 0 && (
        <p className="mb-3 font-mono text-xs text-ink-500">
          {pendingOnly ? (
            <>
              <span className="tabular-nums text-ink-200">{filtered.length}</span> pending
              term{filtered.length === 1 ? "" : "s"}
              {isolatedTermType !== null && (
                <>
                  {" "}
                  (of <span className="tabular-nums">{entriesInScope.length}</span> in scope)
                </>
              )}
            </>
          ) : (
            <>
              Showing <span className="tabular-nums text-ink-200">{filtered.length}</span>
              {isolatedTermType !== null && (
                <>
                  {" "}
                  of <span className="tabular-nums">{entriesInScope.length}</span>
                </>
              )}{" "}
              term{filtered.length === 1 ? "" : "s"}
            </>
          )}
        </p>
      )}

      {!isLoading && !isError && data && filtered.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-ink-800/90 bg-ink-900/35 shadow-sm ring-1 ring-black/5">
          <ul className="divide-y divide-ink-800/70">
            {filtered.map((entry) => (
              <GlossaryEntryRow
                key={entry.id}
                entry={entry}
                allEntries={data.entries}
                patchGlossaryEntry={patchGlossaryEntry}
                termTypeOptions={data.term_type_options}
                translationSuggestionOptions={data.translation_suggestion_options}
                termTypeOptionIds={termTypeOptionIds}
                expanded={openId === entry.id}
                onToggle={() =>
                  setOpenId((prev) => (prev === entry.id ? null : entry.id))
                }
              />
            ))}
          </ul>
        </div>
      )}

      {!isLoading && !isError && data && data.entries.length > 0 && filtered.length === 0 && (
        <p className="text-sm text-ink-400">
          {pendingOnly && entriesInScope.length === 0
            ? "Nothing left to accept — every active term is already accepted."
            : isolatedTermType !== null
              ? "No terms in this category for the current view."
              : "No terms to show."}
        </p>
      )}
    </section>
  );
}

function RunSubtitle({
  run,
  isLoading,
}: {
  run: GlossaryRunMeta | null;
  isLoading: boolean;
}) {
  if (isLoading) return null;
  if (!run) return null;
  return (
    <p className="mt-1.5 font-mono text-xs text-ink-400">
      <span className={runStatusTone(run.status)}>{run.status}</span>
      <span className="text-ink-600"> · </span>
      {formatWhen(run.started_at)}
      <span className="text-ink-600"> · </span>
      {run.entry_count} term{run.entry_count === 1 ? "" : "s"}
      {run.model && (
        <>
          <span className="text-ink-600"> · </span>
          <span className="text-ink-500">{run.model}</span>
        </>
      )}
    </p>
  );
}

function TermTypeBadge({
  termType,
  termTypeOptions,
  termTypeOptionIds,
}: {
  termType: string;
  termTypeOptions: GlossarySelectOption[];
  termTypeOptionIds: readonly string[];
}) {
  const id = canonicalTermTypeId(termType, termTypeOptionIds);
  const label = termTypeOptions.find((o) => o.id === id)?.label ?? id.replace(/_/g, " ");
  const Icon = iconFor(id);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-ink-700/90 bg-ink-900/80",
        "px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-300",
      )}
    >
      <Icon className="h-3 w-3 shrink-0 text-accent" aria-hidden />
      <span>{label}</span>
      {id !== termType && (
        <span className="sr-only"> ({termType})</span>
      )}
    </span>
  );
}

function EntryStatusChip({ status }: { status: string }) {
  if (status === "proposed") return null;
  const tone =
    status === "accepted"
      ? "border-success-border bg-success-surface text-success"
      : status === "adjusted"
        ? "border-accent/30 bg-accent-soft/40 text-accent"
        : status === "rejected"
          ? "border-ink-700 bg-ink-950/80 text-ink-500"
          : "border-ink-700 bg-ink-900 text-ink-400";
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 font-mono text-[9px] font-medium uppercase tracking-wider",
        tone,
      )}
    >
      {status}
    </span>
  );
}

function CollapsedTranslationPill({
  tr,
  translationSuggestionOptions,
}: {
  tr: ReturnType<typeof readTranslation>;
  translationSuggestionOptions: GlossarySelectOption[];
}) {
  const target = (tr.proposed_target ?? "").trim();
  return (
    <div className="mt-1.5 min-w-0">
      <div
        className={cn(
          "inline-flex max-w-full min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg border border-ink-700/90",
          "bg-gradient-to-br from-ink-950/90 to-ink-900/80 px-2.5 py-1.5 shadow-sm",
        )}
      >
        <span className="shrink-0 font-mono text-[10px] uppercase tracking-wide text-ink-500">
          {labelSuggestion(tr.suggestion, translationSuggestionOptions)}
        </span>
        {target ? (
          <>
            <span className="font-sans text-ink-600" aria-hidden>
              →
            </span>
            <span className="min-w-0 truncate font-sans text-sm font-semibold tracking-tight text-accent-pink">
              {target}
            </span>
          </>
        ) : (
          <span className="font-sans text-xs text-ink-500">No target set</span>
        )}
      </div>
    </div>
  );
}

function RowOverflowMenu({
  disabled,
  onEditDetails,
  onRemoveRequest,
}: {
  disabled: boolean;
  onEditDetails: () => void;
  /** When set, shows “Remove from glossary” (e.g. already-accepted rows). */
  onRemoveRequest?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-transparent text-ink-400",
          "hover:border-ink-700 hover:bg-ink-800/80 hover:text-ink-200",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/35",
          "disabled:pointer-events-none disabled:opacity-40",
          open && "border-ink-700 bg-ink-800 text-ink-100",
        )}
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
        <span className="sr-only">More term actions</span>
      </button>
      {open ? (
        <ul
          role="menu"
          className={cn(
            "absolute right-0 top-full z-30 mt-1 min-w-[12.5rem] rounded-lg border border-ink-700/95 bg-ink-900 py-1 shadow-xl",
            "ring-1 ring-black/20",
          )}
        >
          <li role="presentation">
            <button
              type="button"
              role="menuitem"
              className={cn(
                "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-ink-100",
                "hover:bg-ink-800/90 focus-visible:bg-ink-800/90 focus-visible:outline-none",
              )}
              onClick={(e) => {
                e.stopPropagation();
                onEditDetails();
                setOpen(false);
              }}
            >
              <PenLine className="h-3.5 w-3.5 shrink-0 text-ink-500" aria-hidden />
              Edit & review
            </button>
          </li>
          {onRemoveRequest ? (
            <li role="presentation">
              <button
                type="button"
                role="menuitem"
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-danger",
                  "hover:bg-danger/10 focus-visible:bg-danger/10 focus-visible:outline-none",
                )}
                onClick={(e) => {
                  e.stopPropagation();
                  onRemoveRequest();
                  setOpen(false);
                }}
              >
                <Trash2 className="h-3.5 w-3.5 shrink-0 opacity-80" aria-hidden />
                Remove from glossary…
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

function GlossaryEntryRow({
  entry,
  allEntries,
  patchGlossaryEntry,
  termTypeOptions,
  translationSuggestionOptions,
  termTypeOptionIds,
  expanded,
  onToggle,
}: {
  entry: GlossaryWorkingEntry;
  allEntries: readonly GlossaryWorkingEntry[];
  patchGlossaryEntry: ReturnType<typeof usePatchGlossaryWorkingEntry>;
  termTypeOptions: GlossarySelectOption[];
  translationSuggestionOptions: GlossarySelectOption[];
  termTypeOptionIds: readonly string[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const tr = readTranslation(entry.translation_recommendation);
  const dimmed = entry.status === "rejected";

  const mergeTargets = useMemo(
    () => allEntries.filter((e) => e.id !== entry.id && e.status !== "rejected"),
    [allEntries, entry.id],
  );

  const [draftTarget, setDraftTarget] = useState(() => tr.proposed_target ?? "");
  const [draftSuggestion, setDraftSuggestion] = useState<
    "keep_original" | "translate"
  >(() =>
    tr.suggestion === "keep_original" || tr.suggestion === "translate"
      ? tr.suggestion
      : "translate",
  );
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<
    null | "save" | "accept" | "remove" | "merge"
  >(null);

  useEffect(() => {
    setDraftTarget(tr.proposed_target ?? "");
    setDraftSuggestion(
      tr.suggestion === "keep_original" || tr.suggestion === "translate"
        ? (tr.suggestion as "keep_original" | "translate")
        : "translate",
    );
    setMergeTargetId("");
    setReviewError(null);
  }, [
    entry.id,
    entry.updated_at,
    tr.proposed_target,
    tr.suggestion,
  ]);

  const runPatch = async (
    busyKind: "save" | "accept" | "remove" | "merge",
    body: GlossaryEntryPatchBody,
  ) => {
    setReviewError(null);
    setRowBusy(busyKind);
    try {
      await patchGlossaryEntry.mutateAsync({ entryId: entry.id, body });
      setReviewError(null);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setRowBusy(null);
    }
  };

  return (
    <li>
      <div
        className={cn(
          "transition-colors duration-200 ease-out",
          dimmed ? "opacity-50" : "",
          expanded ? "bg-ink-800/35" : "hover:bg-ink-800/25",
        )}
      >
        <div className="flex items-stretch">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className={cn(
              "group flex min-w-0 flex-1 items-start gap-2.5 px-3 py-2.5 text-left sm:gap-3 sm:px-4 sm:py-3",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/35",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-500 transition-colors",
                "group-hover:bg-ink-800/70 group-hover:text-ink-200",
              )}
            >
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform duration-200 ease-out",
                  expanded ? "rotate-180" : "rotate-0",
                )}
                aria-hidden
              />
            </span>
            <div className="min-w-0 flex-1 pb-0.5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-serif text-base font-semibold tracking-tight text-ink-50 sm:text-lg">
                  {entry.canonical_form}
                </span>
                <TermTypeBadge
                  termType={entry.term_type}
                  termTypeOptions={termTypeOptions}
                  termTypeOptionIds={termTypeOptionIds}
                />
                <EntryStatusChip status={entry.status} />
              </div>
              <CollapsedTranslationPill
                tr={tr}
                translationSuggestionOptions={translationSuggestionOptions}
              />
              <p className="mt-1.5 line-clamp-1 font-sans text-xs leading-snug text-ink-400 md:line-clamp-2">
                {entry.meaning}
              </p>
              {tr.alternative_targets.length > 0 ? (
                <p className="mt-1 line-clamp-1 font-mono text-[10px] text-ink-500">
                  <span className="text-ink-600">Also: </span>
                  {tr.alternative_targets.join(" · ")}
                </p>
              ) : null}
            </div>
          </button>
          {!dimmed ? (
            <div
              className={cn(
                "flex shrink-0 items-start gap-0.5 border-l border-ink-800/50 bg-ink-950/25",
                "px-1 py-1.5 sm:px-1.5 sm:py-2",
              )}
            >
              <RowOverflowMenu
                disabled={rowBusy !== null}
                onEditDetails={() => {
                  if (!expanded) onToggle();
                }}
                onRemoveRequest={
                  entry.status === "accepted"
                    ? () => {
                        if (
                          !window.confirm(
                            "Remove this term from the working glossary? It will be marked rejected and ignored during extraction.",
                          )
                        ) {
                          return;
                        }
                        void runPatch("remove", { reject: true });
                      }
                    : undefined
                }
              />
              {isAwaitingAcceptance(entry) ? (
                <div className="flex flex-col gap-1">
                  <button
                    type="button"
                    disabled={rowBusy !== null}
                    title="Accept using the current translation (no need to expand)"
                    aria-label={`Accept ${entry.canonical_form} without expanding`}
                    onClick={(e) => {
                      e.stopPropagation();
                      void runPatch("accept", { accept: true });
                    }}
                    className={cn(
                      "inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-accent/45",
                      "bg-accent-soft/90 px-2.5 font-mono text-[11px] font-semibold text-accent",
                      "shadow-sm hover:border-accent/70 hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                      "disabled:pointer-events-none disabled:opacity-45",
                    )}
                  >
                    {rowBusy === "accept" ? (
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" aria-hidden />
                    ) : (
                      <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    )}
                    <span className="hidden min-[380px]:inline">Accept</span>
                  </button>
                  <button
                    type="button"
                    disabled={rowBusy !== null}
                    title="Reject this term for the active glossary"
                    aria-label={`Reject ${entry.canonical_form}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (
                        !window.confirm(
                          "Reject this term? It will be marked removed and ignored during extraction.",
                        )
                      ) {
                        return;
                      }
                      void runPatch("remove", { reject: true });
                    }}
                    className={cn(
                      "inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-danger/40",
                      "bg-danger/5 px-2.5 font-mono text-[11px] font-semibold text-danger",
                      "hover:border-danger/55 hover:bg-danger/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/30",
                      "disabled:pointer-events-none disabled:opacity-45",
                    )}
                  >
                    {rowBusy === "remove" ? (
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    )}
                    <span className="hidden min-[380px]:inline">Reject</span>
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        {reviewError && !expanded ? (
          <p className="border-t border-ink-800/80 px-4 py-2 pl-11 pr-4 text-xs text-danger" role="alert">
            {reviewError}
          </p>
        ) : null}
        {expanded && (
          <div className="border-t border-ink-800/80 px-4 pb-4 pl-11 pr-4 pt-1">
            <div className="space-y-3 text-sm leading-relaxed text-ink-200">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                  Gloss
                </p>
                <p className="mt-1 font-serif text-base">{entry.meaning}</p>
              </div>
              {tr.alternative_targets.length > 0 && (
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                    Other viable renderings
                  </p>
                  <ul className="mt-2 list-inside list-disc space-y-1 font-sans text-ink-200">
                    {tr.alternative_targets.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}
              {tr.rationale ? (
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                    Translation note
                  </p>
                  <p className="mt-1 font-sans text-ink-300">{tr.rationale}</p>
                </div>
              ) : null}
              {dimmed ? (
                <p className="rounded-md border border-ink-800/60 bg-ink-900/40 px-3 py-2 text-xs leading-relaxed text-ink-400">
                  This term is rejected and is skipped during glossary extraction and
                  when building a final glossary snapshot.
                </p>
              ) : null}
              {!dimmed ? (
              <>
              <div className="rounded-md border border-ink-800 bg-ink-900/60 p-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                  Translation for review
                </p>
                <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-end">
                  <label className="block min-w-0 flex-1 font-sans text-xs text-ink-400">
                    <span className="mb-1 block text-ink-500">Target rendering</span>
                    <input
                      type="text"
                      value={draftTarget}
                      onChange={(e) => setDraftTarget(e.target.value)}
                      disabled={rowBusy !== null}
                      className={cn(
                        "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100",
                        "placeholder:text-ink-600",
                        "focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/25",
                        "disabled:opacity-60",
                      )}
                      aria-label="Translation target"
                    />
                  </label>
                  <label className="block shrink-0 font-sans text-xs text-ink-400 sm:w-44">
                    <span className="mb-1 block text-ink-500">Approach</span>
                    <select
                      value={draftSuggestion}
                      onChange={(e) =>
                        setDraftSuggestion(
                          e.target.value === "keep_original" ? "keep_original" : "translate",
                        )
                      }
                      disabled={rowBusy !== null}
                      className={cn(
                        "w-full rounded-md border border-ink-700 bg-ink-950 px-2 py-2 font-sans text-sm text-ink-100",
                        "focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/25",
                        "disabled:opacity-60",
                      )}
                      aria-label="Translation approach"
                    >
                      {translationSuggestionOptions.map((opt) => (
                        <option key={opt.id} value={opt.id}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={rowBusy !== null}
                    onClick={() =>
                      void runPatch("save", {
                        proposed_target: draftTarget,
                        suggestion: draftSuggestion,
                      })
                    }
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-3 py-1.5",
                      "font-mono text-[11px] font-medium text-ink-100",
                      "hover:border-ink-500 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                      "disabled:pointer-events-none disabled:opacity-50",
                    )}
                  >
                    {rowBusy === "save" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    ) : null}
                    Save translation
                  </button>
                  <button
                    type="button"
                    disabled={rowBusy !== null}
                    onClick={() =>
                      void runPatch("accept", {
                        proposed_target: draftTarget,
                        suggestion: draftSuggestion,
                        accept: true,
                      })
                    }
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent-soft px-3 py-1.5",
                      "font-mono text-[11px] font-medium text-accent",
                      "hover:border-accent/60 hover:bg-accent-soft/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                      "disabled:pointer-events-none disabled:opacity-50",
                    )}
                  >
                    {rowBusy === "accept" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden />
                    ) : (
                      <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    )}
                    Accept
                  </button>
                  {isAwaitingAcceptance(entry) ? (
                    <button
                      type="button"
                      disabled={rowBusy !== null}
                      onClick={() => {
                        if (
                          !window.confirm(
                            "Reject this term? It will be marked removed and ignored during extraction.",
                          )
                        ) {
                          return;
                        }
                        void runPatch("remove", { reject: true });
                      }}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-md border border-danger/40 bg-danger/5 px-3 py-1.5",
                        "font-mono text-[11px] font-medium text-danger",
                        "hover:border-danger/55 hover:bg-danger/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/30",
                        "disabled:pointer-events-none disabled:opacity-50",
                      )}
                    >
                      {rowBusy === "remove" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                      )}
                      Reject
                    </button>
                  ) : null}
                </div>
              </div>
              <div className="rounded-md border border-ink-800/90 bg-ink-950/40 p-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                  Glossary upkeep
                </p>
                <p className="mt-1 max-w-prose text-xs leading-relaxed text-ink-500">
                  Use <span className="font-medium text-ink-400">Reject</span> in translation
                  above to drop a spurious line, or fold this heading into another row. Merging
                  deletes this row and moves its surface form and variants onto the term you keep.
                </p>
                <div className="mt-3 space-y-3">
                  {mergeTargets.length === 0 ? (
                    <p className="text-xs text-ink-500">
                      No other active terms in this run to merge into.
                    </p>
                  ) : null}
                  <label className="block font-sans text-xs text-ink-400">
                    <span className="mb-1 block text-ink-500">Merge into</span>
                    <select
                      value={mergeTargetId}
                      onChange={(e) => setMergeTargetId(e.target.value)}
                      disabled={rowBusy !== null || mergeTargets.length === 0}
                      className={cn(
                        "w-full max-w-md rounded-md border border-ink-700 bg-ink-950 px-2 py-2 font-sans text-sm text-ink-100",
                        "focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/25",
                        "disabled:opacity-60",
                      )}
                      aria-label="Merge into another glossary term"
                    >
                      <option value="">Select term to keep…</option>
                      {mergeTargets.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.canonical_form}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      disabled={
                        rowBusy !== null ||
                        mergeTargetId === "" ||
                        mergeTargets.length === 0
                      }
                      onClick={() => {
                        const keep = mergeTargets.find((t) => t.id === mergeTargetId);
                        if (
                          !keep ||
                          !window.confirm(
                            `Merge “${entry.canonical_form}” into “${keep.canonical_form}”? This row will be removed.`,
                          )
                        ) {
                          return;
                        }
                        void runPatch("merge", {
                          merge_into_entry_id: mergeTargetId,
                        });
                      }}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-3 py-1.5",
                        "font-mono text-[11px] font-medium text-ink-100",
                        "hover:border-ink-500 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                        "disabled:pointer-events-none disabled:opacity-50",
                      )}
                    >
                      {rowBusy === "merge" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      ) : (
                        <GitMerge className="h-3.5 w-3.5 shrink-0 text-ink-300" aria-hidden />
                      )}
                      Merge into selected
                    </button>
                  </div>
                </div>
              </div>
              {reviewError ? (
                <p className="text-xs text-danger" role="alert">
                  {reviewError}
                </p>
              ) : null}
              </>
              ) : null}
              {entry.variants.length > 0 && (
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                    Variants in text
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {entry.variants.map((v) => (
                      <li
                        key={v}
                        className="rounded border border-ink-700 bg-ink-900 px-2 py-1 font-mono text-xs text-ink-200"
                      >
                        {v}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="font-mono text-[10px] text-ink-600">
                First seen window {entry.first_seen_window}
                <span className="text-ink-700"> · </span>
                Occurrences {entry.occurrence_count}
              </p>
            </div>
          </div>
        )}
      </div>
    </li>
  );
}
