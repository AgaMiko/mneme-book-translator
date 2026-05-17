import { BookOpen, Trash2 } from "lucide-react";

import { useBooks, useDeleteBook } from "@/lib/api/hooks";
import { cn, formatNumber, formatRelativeDate } from "@/lib/utils";
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
          <li key={i} className="h-16 animate-pulse rounded-md bg-ink-800" aria-hidden />
        ))}
      </ul>
    );
  }

  if (isError) {
    return <p className="text-xs text-danger">Couldn't load library — is the API running?</p>;
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-ink-700 px-4 py-6 text-center">
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
                "group relative flex items-start gap-2 rounded-md px-3 py-2",
                "transition-colors duration-150",
                isSelected ? "bg-ink-700" : "hover:bg-ink-800",
              )}
            >
              <button
                type="button"
                onClick={() => onSelect(book.id)}
                className={cn(
                  "min-w-0 flex-1 rounded text-left",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                )}
                aria-current={isSelected ? "true" : undefined}
              >
                <div className="truncate text-sm font-medium text-ink-50">{book.title}</div>
                {book.author && (
                  <div className="truncate text-xs italic text-ink-300">{book.author}</div>
                )}
                <div className="mt-0.5 truncate text-xs text-ink-400">
                  {formatNumber(book.word_count)} words · {formatRelativeDate(book.created_at)}
                </div>
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
