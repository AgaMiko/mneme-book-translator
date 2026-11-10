import type { BookDetail } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { LABEL } from "@/components/ui/typography";

interface Props {
  book: BookDetail;
  /** DOM id of the chapter currently in view (`chapter-<uuid>`). */
  activeChapterId: string | null;
  onSelect: (chapterDomId: string) => void;
}

/**
 * Chapter navigation, persistent across every tab.
 *
 * It used to live inside `ManuscriptView`, which meant the book's shape
 * vanished the moment you opened the glossary. Now it stays: the rail is
 * the book, the panel to its right is what you're doing to it. Selecting
 * a chapter from a working tab returns you to the manuscript at that
 * point — which is why these are buttons, not anchors.
 */
export function ChapterRail({ book, activeChapterId, onSelect }: Props) {
  return (
    <nav
      className="hidden w-[288px] shrink-0 overflow-y-auto border-r border-ink-800 bg-ink-900 px-3 py-6 lg:block"
      aria-label="Chapters"
    >
      <div className="mb-2.5 flex items-center justify-between px-2.5">
        <p className={LABEL}>Chapters</p>
        <span className="font-mono text-label tabular-nums text-ink-400">
          {book.chapters.length}
        </span>
      </div>
      <ol className="space-y-0.5">
        {book.chapters.map((c, idx) => {
          const id = `chapter-${c.id}`;
          const label = c.title ?? `Chapter ${idx + 1}`;
          const active = activeChapterId === id;
          return (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onSelect(id)}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "flex w-full items-baseline gap-2 rounded-lg px-2.5 py-2 text-left text-small",
                  "transition-colors duration-150",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  active
                    ? "bg-ink-800 text-ink-50 shadow-[inset_2px_0_0_var(--color-accent)]"
                    : "text-ink-400 hover:bg-ink-800 hover:text-ink-100",
                )}
              >
                <span
                  className={cn(
                    "shrink-0 font-mono text-label tabular-nums",
                    active ? "text-accent" : "text-ink-500",
                  )}
                >
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0 truncate">{label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
