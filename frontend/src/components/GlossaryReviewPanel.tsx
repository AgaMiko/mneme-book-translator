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
  PenLine,
  Search,
  Shapes,
  Sparkles,
  UserRound,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/Button";
import { OverflowMenu } from "@/components/ui/OverflowMenu";
import type {
  GlossaryEntryPatchBody,
  GlossaryRunMeta,
  GlossarySelectOption,
  GlossaryWorkingEntry,
} from "@/lib/api/client";
import { usePatchGlossaryWorkingEntry, useWorkingGlossary } from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

/**
 * Term-type presentation. Color is intentionally NOT part of the
 * categorical mapping — every chip and badge uses the same neutral
 * surface so the brand palette stays coherent. Distinction across types
 * is carried by the icon, not by a per-type color.
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
  const suggestion = typeof rec.suggestion === "string" ? rec.suggestion : "translate";
  const proposed_target =
    typeof rec.proposed_target === "string" || rec.proposed_target === null
      ? (rec.proposed_target as string | null)
      : null;
  const rationale = typeof rec.rationale === "string" ? rec.rationale : "";
  const rawAlts = rec.alternative_targets;
  const fromApi: string[] = Array.isArray(rawAlts)
    ? rawAlts
        .filter((x): x is string => typeof x === "string" && x.trim() !== "")
        .map((x) => x.trim())
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

/**
 * Which slice of the run you are looking at. This is one control rather
 * than a toggle plus an implicit "everything" state: a term is pending,
 * accepted, or removed, and you review one of those piles at a time.
 */
type StatusFilter = "pending" | "accepted" | "removed";

const STATUS_FILTERS: readonly { id: StatusFilter; label: string }[] = [
  { id: "pending", label: "Pending" },
  { id: "accepted", label: "Accepted" },
  { id: "removed", label: "Removed" },
];

function matchesStatus(entry: GlossaryWorkingEntry, filter: StatusFilter): boolean {
  if (filter === "pending") return isAwaitingAcceptance(entry);
  if (filter === "accepted") return entry.status === "accepted";
  return entry.status === "rejected";
}

/** Which section of the expanded editor the row was opened for. */
type RowIntent = "edit" | "merge";

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

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [termType, setTermType] = useState<string>("");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [openIntent, setOpenIntent] = useState<RowIntent>("edit");

  useEffect(() => {
    if (openId !== null && data?.entries && !data.entries.some((e) => e.id === openId)) {
      setOpenId(null);
    }
  }, [data?.entries, openId]);

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

  const statusCounts: Record<StatusFilter, number> = {
    pending: reviewStats.awaiting,
    accepted: reviewStats.accepted,
    removed: reviewStats.removed,
  };

  /** Entries in the selected pile — the denominator for the type select. */
  const entriesInScope = useMemo(
    () => (data?.entries ?? []).filter((e) => matchesStatus(e, statusFilter)),
    [data?.entries, statusFilter],
  );

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return entriesInScope.filter((e) => {
      if (termType !== "") {
        if (canonicalTermTypeId(e.term_type, termTypeOptionIds) !== termType) return false;
      }
      if (needle && !e.canonical_form.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [entriesInScope, termType, termTypeOptionIds, search]);

  /** Per-type counts within the selected pile, for the select labels. */
  const termTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of entriesInScope) {
      const id = canonicalTermTypeId(e.term_type, termTypeOptionIds);
      counts[id] = (counts[id] ?? 0) + 1;
    }
    return counts;
  }, [entriesInScope, termTypeOptionIds]);

  const openRow = (id: string, intent: RowIntent) => {
    setOpenId((prev) => (prev === id && openIntent === intent ? null : id));
    setOpenIntent(intent);
  };

  return (
    <section id="glossary-review" aria-labelledby="glossary-review-heading" className="scroll-mt-6">
      <div className="mb-4">
        <h2
          id="glossary-review-heading"
          className="font-serif text-2xl font-semibold tracking-tight text-ink-50"
        >
          Working glossary
        </h2>
        <RunSubtitle run={data?.run ?? null} isLoading={isLoading} />
      </div>

      {!isLoading && !isError && data && data.entries.length > 0 && (
        <div className="mb-5 flex flex-wrap items-center gap-3">
          {/* Segmented status control — subsumes the old pending-only switch. */}
          <div
            role="group"
            aria-label="Filter by review status"
            className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5"
          >
            {STATUS_FILTERS.map((f) => {
              const active = statusFilter === f.id;
              return (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setStatusFilter(f.id)}
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px]",
                    "transition-colors duration-150",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    active ? "bg-ink-800 text-ink-50" : "text-ink-400 hover:text-ink-100",
                  )}
                >
                  {f.label}
                  <span className="font-mono text-[10px] tabular-nums opacity-70">
                    {statusCounts[f.id]}
                  </span>
                </button>
              );
            })}
          </div>

          <label className="inline-flex items-center gap-2">
            <span className="sr-only">Filter by term type</span>
            <select
              value={termType}
              onChange={(e) => setTermType(e.target.value)}
              className={cn(
                "h-8 rounded-lg border border-ink-700 bg-ink-900 px-2 text-[12.5px] text-ink-100",
                "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent",
              )}
            >
              <option value="">All term types</option>
              {(data.term_type_options ?? []).map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label} ({termTypeCounts[opt.id] ?? 0})
                </option>
              ))}
            </select>
          </label>

          <label className="relative inline-flex min-w-0 flex-1 items-center sm:max-w-[16rem]">
            <span className="sr-only">Search terms</span>
            <Search
              className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-ink-500"
              aria-hidden
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search terms…"
              className={cn(
                "h-8 w-full rounded-lg border border-ink-700 bg-ink-900 pl-8 pr-2.5",
                "text-[12.5px] text-ink-100 placeholder:text-ink-600",
                "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent",
              )}
            />
          </label>
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
          No extraction run exists for this book yet. When you start a run, terms will appear here
          as each pass finishes.
        </p>
      )}

      {!isLoading && !isError && data?.run && data.entries.length === 0 && (
        <p className="max-w-prose text-sm leading-relaxed text-ink-400">
          This run has no stored terms yet. If extraction is still running, check back in a moment.
        </p>
      )}

      {!isLoading && !isError && data && filtered.length > 0 && (
        <>
          <p className="mb-3 font-mono text-xs text-ink-500">
            <span className="tabular-nums text-ink-200">{formatNumber(filtered.length)}</span>
            {filtered.length !== entriesInScope.length && (
              <>
                {" of "}
                <span className="tabular-nums">{formatNumber(entriesInScope.length)}</span>
              </>
            )}{" "}
            {statusFilter} term{filtered.length === 1 ? "" : "s"}
          </p>
          <div className="overflow-hidden rounded-lg border border-ink-800 bg-ink-900 shadow-sm ring-1 ring-black/5">
            <ul className="divide-y divide-ink-800">
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
                  intent={openId === entry.id ? openIntent : "edit"}
                  onOpen={(intent) => openRow(entry.id, intent)}
                />
              ))}
            </ul>
          </div>
        </>
      )}

      {!isLoading && !isError && data && data.entries.length > 0 && filtered.length === 0 && (
        <p className="text-sm text-ink-400">
          {entriesInScope.length === 0
            ? statusFilter === "pending"
              ? "Nothing left to accept — every active term is already reviewed."
              : `No ${statusFilter} terms in this run.`
            : "No terms match the current filters."}
        </p>
      )}
    </section>
  );
}

function RunSubtitle({ run, isLoading }: { run: GlossaryRunMeta | null; isLoading: boolean }) {
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
        "inline-flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900",
        "px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-300",
      )}
    >
      <Icon className="h-3 w-3 shrink-0 text-accent" aria-hidden />
      <span>{label}</span>
      {id !== termType && <span className="sr-only"> ({termType})</span>}
    </span>
  );
}

function EntryStatusChip({ status }: { status: string }) {
  if (status === "proposed") return null;
  const tone =
    status === "accepted"
      ? "border-success-border bg-success-surface text-success"
      : status === "adjusted"
        ? "border-accent bg-accent-soft text-accent"
        : status === "rejected"
          ? "border-ink-700 bg-ink-950 text-ink-500"
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
          "inline-flex min-w-0 max-w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg border border-ink-700",
          "bg-ink-950 px-2.5 py-1.5 shadow-sm",
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
            <span className="min-w-0 truncate font-sans text-sm font-semibold tracking-tight text-accent">
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

/** Secondary term actions: everything real but rare. */
function RowOverflowMenu({
  disabled,
  onEditDetails,
  onMerge,
  onReject,
}: {
  disabled: boolean;
  onEditDetails: () => void;
  onMerge: () => void;
  onReject: () => void;
}) {
  return (
    <OverflowMenu
      disabled={disabled}
      label="More term actions"
      items={[
        { label: "Edit & review", icon: PenLine, onClick: onEditDetails },
        { label: "Merge into another term…", icon: GitMerge, onClick: onMerge },
        { label: "Reject term", icon: XCircle, onClick: onReject, danger: true },
      ]}
    />
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
  intent,
  onOpen,
}: {
  entry: GlossaryWorkingEntry;
  allEntries: readonly GlossaryWorkingEntry[];
  patchGlossaryEntry: ReturnType<typeof usePatchGlossaryWorkingEntry>;
  termTypeOptions: GlossarySelectOption[];
  translationSuggestionOptions: GlossarySelectOption[];
  termTypeOptionIds: readonly string[];
  expanded: boolean;
  intent: RowIntent;
  onOpen: (intent: RowIntent) => void;
}) {
  const tr = readTranslation(entry.translation_recommendation);
  const dimmed = entry.status === "rejected";

  const mergeTargets = useMemo(
    () => allEntries.filter((e) => e.id !== entry.id && e.status !== "rejected"),
    [allEntries, entry.id],
  );

  const [draftTarget, setDraftTarget] = useState(() => tr.proposed_target ?? "");
  const [draftSuggestion, setDraftSuggestion] = useState<"keep_original" | "translate">(() =>
    tr.suggestion === "keep_original" || tr.suggestion === "translate"
      ? tr.suggestion
      : "translate",
  );
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<null | "save" | "accept" | "remove" | "merge">(null);
  const mergeSelectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    setDraftTarget(tr.proposed_target ?? "");
    setDraftSuggestion(
      tr.suggestion === "keep_original" || tr.suggestion === "translate"
        ? (tr.suggestion as "keep_original" | "translate")
        : "translate",
    );
    setMergeTargetId("");
    setReviewError(null);
  }, [entry.id, entry.updated_at, tr.proposed_target, tr.suggestion]);

  /** Opened via "Merge into another term…" — put the cursor where it belongs. */
  useEffect(() => {
    if (!expanded || intent !== "merge") return;
    mergeSelectRef.current?.focus();
    mergeSelectRef.current?.scrollIntoView({ block: "nearest" });
  }, [expanded, intent]);

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

  const requestReject = () => {
    if (
      !window.confirm("Reject this term? It will be marked removed and ignored during extraction.")
    ) {
      return;
    }
    void runPatch("remove", { reject: true });
  };

  return (
    <li>
      <div
        className={cn(
          "transition-colors duration-200 ease-out",
          dimmed ? "opacity-50" : "",
          expanded ? "bg-ink-800" : "hover:bg-ink-800",
        )}
      >
        <div className="flex items-stretch">
          <button
            type="button"
            onClick={() => onOpen("edit")}
            aria-expanded={expanded}
            className={cn(
              "group flex min-w-0 flex-1 items-start gap-2.5 px-3 py-2.5 text-left sm:gap-3 sm:px-4 sm:py-3",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-500 transition-colors",
                "group-hover:bg-ink-800 group-hover:text-ink-200",
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
                "flex shrink-0 items-start gap-1 border-l border-ink-800 bg-ink-950",
                "px-1.5 py-2",
              )}
            >
              {isAwaitingAcceptance(entry) ? (
                <Button
                  variant="accent"
                  size="sm"
                  disabled={rowBusy !== null}
                  title="Accept using the current translation (no need to expand)"
                  aria-label={`Accept ${entry.canonical_form}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    void runPatch("accept", { accept: true });
                  }}
                >
                  {rowBusy === "accept" ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                  ) : (
                    <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  )}
                  <span className="hidden min-[380px]:inline">Accept</span>
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                disabled={rowBusy !== null}
                title="Edit the translation for this term"
                aria-label={`Edit ${entry.canonical_form}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onOpen("edit");
                }}
                className="w-8 px-0"
              >
                <PenLine className="h-3.5 w-3.5 shrink-0" aria-hidden />
              </Button>
              <RowOverflowMenu
                disabled={rowBusy !== null}
                onEditDetails={() => onOpen("edit")}
                onMerge={() => onOpen("merge")}
                onReject={requestReject}
              />
            </div>
          ) : null}
        </div>
        {reviewError && !expanded ? (
          <p
            className="border-t border-ink-800 px-4 py-2 pl-11 pr-4 text-xs text-danger"
            role="alert"
          >
            {reviewError}
          </p>
        ) : null}
        {expanded && (
          <div className="border-t border-ink-800 px-4 pb-4 pl-11 pr-4 pt-1">
            <div className="space-y-3 text-sm leading-relaxed text-ink-200">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">Gloss</p>
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
                <p className="rounded-lg border border-ink-800 bg-ink-900 px-3 py-2 text-xs leading-relaxed text-ink-400">
                  This term is rejected and is skipped during glossary extraction and when building
                  a final glossary snapshot.
                </p>
              ) : null}
              {!dimmed ? (
                <>
                  <div className="rounded-lg border border-ink-800 bg-ink-900 p-3">
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
                            "w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100",
                            "placeholder:text-ink-600",
                            "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent",
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
                            "w-full rounded-lg border border-ink-700 bg-ink-950 px-2 py-2 font-sans text-sm text-ink-100",
                            "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent",
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
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={rowBusy !== null}
                        className="border border-ink-700"
                        onClick={() =>
                          void runPatch("save", {
                            proposed_target: draftTarget,
                            suggestion: draftSuggestion,
                          })
                        }
                      >
                        {rowBusy === "save" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        ) : null}
                        Save translation
                      </Button>
                      <Button
                        variant="accent"
                        size="sm"
                        disabled={rowBusy !== null}
                        onClick={() =>
                          void runPatch("accept", {
                            proposed_target: draftTarget,
                            suggestion: draftSuggestion,
                            accept: true,
                          })
                        }
                      >
                        {rowBusy === "accept" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        ) : (
                          <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
                        )}
                        Accept
                      </Button>
                      {isAwaitingAcceptance(entry) ? (
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={rowBusy !== null}
                          onClick={requestReject}
                        >
                          {rowBusy === "remove" ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                          ) : (
                            <XCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                          )}
                          Reject
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  <div className="rounded-lg border border-ink-800 bg-ink-950 p-3">
                    <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                      Merge
                    </p>
                    <p className="mt-1 max-w-prose text-xs leading-relaxed text-ink-500">
                      Folds this heading into another row. Merging deletes this row and moves its
                      surface form and variants onto the term you keep.
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
                          ref={mergeSelectRef}
                          value={mergeTargetId}
                          onChange={(e) => setMergeTargetId(e.target.value)}
                          disabled={rowBusy !== null || mergeTargets.length === 0}
                          className={cn(
                            "w-full max-w-md rounded-lg border border-ink-700 bg-ink-950 px-2 py-2 font-sans text-sm text-ink-100",
                            "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent",
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
                      <Button
                        variant="ghost"
                        size="sm"
                        className="border border-ink-700"
                        disabled={
                          rowBusy !== null || mergeTargetId === "" || mergeTargets.length === 0
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
                      >
                        {rowBusy === "merge" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        ) : (
                          <GitMerge className="h-3.5 w-3.5 shrink-0 text-ink-300" aria-hidden />
                        )}
                        Merge into selected
                      </Button>
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
                        className="rounded-lg border border-ink-700 bg-ink-900 px-2 py-1 font-mono text-xs text-ink-200"
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
