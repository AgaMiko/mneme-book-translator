import { BookOpen, Trash2 } from "lucide-react";

import type { BookSummary } from "@/lib/api/client";
import { useBooks, useDeleteBook } from "@/lib/api/hooks";
import { cn, formatRelativeDate } from "@/lib/utils";
import { Button } from "@/components/ui/Button";

/** `107 643` → `107k`. The row wants the magnitude, not the figure. */
function compactWords(n: number): string {
  if (n < 1000) return `${n}`;
  return `${Math.round(n / 1000)}k`;
}

interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDeleted: (id: string) => void;
}

export function BookList({ selectedId, onSelect, onDeleted }: Props) {
  const { data, isLoading, isError } = useBooks();
  const del = useDeleteBook();

  if (isLoading) {
    return (
      <ul className="space-y-2" aria-busy="true">
        {Array.from({ length: 3 }).map((_, i) => (
          <li key={i} className="h-[68px] animate-pulse rounded-lg bg-ink-800" aria-hidden />
        ))}
      </ul>
    );
  }

  if (isError) {
    return <p className="text-xs text-danger">Couldn't load library — is the API running?</p>;
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-ink-700 px-4 py-8 text-center">
        <BookOpen className="mx-auto h-5 w-5 text-ink-400" aria-hidden />
        <p className="mt-2 text-xs text-ink-300">No manuscripts yet. Upload one above.</p>
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-0.5">
      {data.map((book) => {
        const isSelected = book.id === selectedId;
        return (
          <li key={book.id}>
            <div
              className={cn(
                "group relative flex items-start gap-2.5 rounded-lg px-3 py-2.5",
                "transition-colors duration-150",
                isSelected
                  ? "bg-ink-800 shadow-[inset_2px_0_0_var(--color-accent)]"
                  : "hover:bg-ink-800",
              )}
            >
              <button
                type="button"
                onClick={() => onSelect(book.id)}
                className={cn(
                  "min-w-0 flex-1 rounded-lg text-left",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                )}
                aria-current={isSelected ? "true" : undefined}
              >
                <div
                  className={cn(
                    "truncate font-serif text-[15px] font-semibold",
                    isSelected ? "text-ink-50" : "text-ink-200",
                  )}
                >
                  {book.title}
                </div>
                {book.author && (
                  <div className="mt-[3px] truncate text-xs text-ink-400">{book.author}</div>
                )}
                <PipelineStatusLine book={book} />
              </button>
              <Button
                variant="danger"
                size="sm"
                aria-label={`Delete ${book.title}`}
                disabled={del.isPending}
                onClick={() => {
                  if (confirm(`Delete "${book.title}"? This cannot be undone.`)) {
                    del.mutate(book.id, {
                      onSuccess: () => onDeleted(book.id),
                    });
                  }
                }}
                className="px-2 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

type Tone = "idle" | "running" | "done" | "warning" | "danger";

const DOT_TONE: Record<Tone, string> = {
  idle: "bg-ink-700",
  running: "animate-pulse bg-accent",
  done: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
};

const TEXT_TONE: Record<Tone, string> = {
  idle: "text-ink-500",
  running: "text-accent",
  done: "text-ink-400",
  warning: "text-warning",
  danger: "text-danger",
};

/**
 * How far along the pipeline this book is. The status leads — on a
 * library row it is what tells you what to do next — with size and date
 * trailing behind it as the identifying detail.
 */
function PipelineStatusLine({ book }: { book: BookSummary }) {
  const { tone, label } = pipelineStatus(book);
  return (
    <div className="mt-[7px] flex items-center gap-[7px]">
      <span
        className={cn("inline-flex items-center gap-[5px] font-mono text-[10px]", TEXT_TONE[tone])}
      >
        <span className={cn("h-[5px] w-[5px] shrink-0 rounded-full", DOT_TONE[tone])} aria-hidden />
        <span className="truncate">{label}</span>
      </span>
      <span className="shrink-0 font-mono text-[10px] text-ink-600">
        {compactWords(book.word_count)} · {formatRelativeDate(book.created_at)}
      </span>
    </div>
  );
}

/** `Glossary 42/118` while a pass is in flight, else just the step name. */
function withProgress(
  name: string,
  completed: number | null | undefined,
  total: number | null | undefined,
): string {
  if (total == null || total <= 0) return `${name}…`;
  return `${name} ${completed ?? 0}/${total}`;
}

function pipelineStatus(book: BookSummary): { tone: Tone; label: string } {
  const statuses = [
    book.glossary_extraction_status,
    book.speakers_extraction_status,
    book.voice_extraction_status,
  ];

  if (statuses.includes("failed")) return { tone: "danger", label: "Run failed" };

  if (book.glossary_extraction_status === "running") {
    return {
      tone: "running",
      label: withProgress(
        "Glossary",
        book.glossary_extraction_windows_completed,
        book.glossary_extraction_windows_total,
      ),
    };
  }
  if (book.speakers_extraction_status === "running") {
    return {
      tone: "running",
      label: withProgress(
        "Speakers",
        book.speakers_extraction_windows_completed,
        book.speakers_extraction_windows_total,
      ),
    };
  }
  if (book.voice_extraction_status === "running") {
    return {
      tone: "running",
      label: withProgress(
        "Voices",
        book.voice_extraction_windows_completed,
        book.voice_extraction_windows_total,
      ),
    };
  }

  if (statuses.includes("cancelled")) return { tone: "warning", label: "Stopped" };

  if (book.voice_extraction_status === "completed") return { tone: "done", label: "Voices ready" };
  if (book.speakers_extraction_status === "completed") {
    return { tone: "done", label: "Speakers mapped" };
  }
  if (book.glossary_extraction_status === "completed") {
    return { tone: "done", label: "Glossary ready" };
  }
  if (book.metadata_status === "pending") return { tone: "running", label: "Reading metadata…" };
  if (book.metadata_status === "failed") return { tone: "danger", label: "Metadata failed" };

  return { tone: "idle", label: "Not started" };
}
