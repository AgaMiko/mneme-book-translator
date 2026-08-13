import { BookOpen, Trash2 } from "lucide-react";

import type { BookSummary } from "@/lib/api/client";
import { useBooks, useDeleteBook } from "@/lib/api/hooks";
import { cn, formatRelativeDate } from "@/lib/utils";

/** `107 643` → `107k`. The row wants the magnitude, not the figure. */
function compactWords(n: number): string {
  if (n < 1000) return `${n}`;
  return `${Math.round(n / 1000)}k`;
}
import { Button } from "@/components/ui/Button";

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
    <ul className="space-y-1">
      {data.map((book) => {
        const isSelected = book.id === selectedId;
        return (
          <li key={book.id}>
            <div
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-4 py-3",
                "transition-colors duration-150",
                isSelected ? "bg-ink-800" : "hover:bg-ink-800",
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
                <div className="truncate text-sm font-medium text-ink-50">{book.title}</div>
                {book.author && (
                  <div className="truncate text-xs italic text-ink-300">{book.author}</div>
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
  idle: "bg-ink-600",
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
    <div className="mt-1.5 flex items-center gap-2">
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_TONE[tone])} aria-hidden />
      <span
        className={cn("truncate font-mono text-[11px] uppercase tracking-wider", TEXT_TONE[tone])}
      >
        {label}
      </span>
      <span className="shrink-0 font-mono text-[11px] text-ink-500">
        <span className="text-ink-600">·</span> {compactWords(book.word_count)} ·{" "}
        {formatRelativeDate(book.created_at)}
      </span>
    </div>
  );
}

function pipelineStatus(book: BookSummary): { tone: Tone; label: string } {
  const statuses = [
    book.glossary_extraction_status,
    book.speakers_extraction_status,
    book.voice_extraction_status,
  ];

  if (statuses.includes("failed")) return { tone: "danger", label: "run failed" };

  if (book.glossary_extraction_status === "running") return { tone: "running", label: "glossary…" };
  if (book.speakers_extraction_status === "running") return { tone: "running", label: "speakers…" };
  if (book.voice_extraction_status === "running") return { tone: "running", label: "voices…" };

  if (statuses.includes("cancelled")) return { tone: "warning", label: "stopped mid-run" };

  if (book.voice_extraction_status === "completed") return { tone: "done", label: "voices ready" };
  if (book.speakers_extraction_status === "completed") {
    return { tone: "done", label: "speakers mapped" };
  }
  if (book.glossary_extraction_status === "completed") {
    return { tone: "done", label: "glossary ready" };
  }
  if (book.metadata_status === "pending") return { tone: "running", label: "reading metadata…" };
  if (book.metadata_status === "failed") return { tone: "danger", label: "metadata failed" };

  return { tone: "idle", label: "not started" };
}
