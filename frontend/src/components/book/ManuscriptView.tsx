import { useEffect, useRef, useState } from "react";

import type { BookDetail } from "@/lib/api/client";
import { cn } from "@/lib/utils";

interface Props {
  book: BookDetail;
}

/**
 * The reading surface. Lora prose, drop caps, sticky chapter nav.
 */
export function ManuscriptView({ book }: Props) {
  const [activeChapter, setActiveChapter] = useState<string | null>(null);
  const chapterRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) setActiveChapter(visible.target.id);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: [0.1, 0.5, 1.0] },
    );
    Object.values(chapterRefs.current).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [book]);

  return (
    <div className="flex h-full min-h-0">
      <nav
        className="hidden w-56 shrink-0 overflow-y-auto border-r border-ink-800 px-4 py-8 lg:block"
        aria-label="Chapters"
      >
        <p className="mb-3 text-xs uppercase tracking-wider text-ink-400">Chapters</p>
        <ol className="space-y-1">
          {book.chapters.map((c, idx) => {
            const id = `chapter-${c.id}`;
            const label = c.title ?? `Chapter ${idx + 1}`;
            return (
              <li key={c.id}>
                <a
                  href={`#${id}`}
                  className={cn(
                    "block rounded px-2 py-1.5 text-xs transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    activeChapter === id
                      ? "bg-ink-800 text-ink-50"
                      : "text-ink-400 hover:bg-ink-800 hover:text-ink-100",
                  )}
                >
                  <span className="mr-2 tabular-nums text-ink-500">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <span className="truncate">{label}</span>
                </a>
              </li>
            );
          })}
        </ol>
      </nav>

      <div className="reader-surface flex-1 overflow-y-auto">
        <article className="mx-auto max-w-prose px-6 py-12 lg:py-16">
          {book.language_style_note && (
            <p className="mb-12 max-w-prose border-l-2 border-ink-700 pl-4 font-serif text-sm italic leading-relaxed text-ink-300">
              {book.language_style_note}
            </p>
          )}
          {book.chapters.map((chapter, idx) => {
            const id = `chapter-${chapter.id}`;
            const label = chapter.title ?? `Chapter ${idx + 1}`;
            return (
              <section
                key={chapter.id}
                id={id}
                ref={(el) => (chapterRefs.current[id] = el)}
                className="mb-16 scroll-mt-8"
              >
                <h2 className="mb-6 font-serif text-2xl text-accent">{label}</h2>
                <div className="chapter-body space-y-5 font-serif text-lg text-ink-100">
                  {chapter.paragraphs.length === 0 ? (
                    <p className="italic text-ink-500">[empty chapter]</p>
                  ) : (
                    chapter.paragraphs.map((p) => <p key={p.id}>{p.text}</p>)
                  )}
                </div>
              </section>
            );
          })}
        </article>
      </div>
    </div>
  );
}
