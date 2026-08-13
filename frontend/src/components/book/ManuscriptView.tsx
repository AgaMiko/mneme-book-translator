import { useEffect, useRef } from "react";

import type { BookDetail } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";

interface Props {
  book: BookDetail;
  /** Reported upward so the persistent chapter rail can follow the scroll. */
  onActiveChapterChange: (chapterDomId: string) => void;
  /**
   * A chapter picked from the rail while another tab was open. Scrolled
   * to on mount / on change, then cleared via `onScrollHandled`.
   */
  scrollTarget: string | null;
  onScrollHandled: () => void;
}

/**
 * The reading surface. Lora prose, drop caps. Chapter navigation lives
 * one level up in `ChapterRail` so it survives tab changes; this view
 * owns only the observer that tells the rail where you are.
 */
export function ManuscriptView({
  book,
  onActiveChapterChange,
  scrollTarget,
  onScrollHandled,
}: Props) {
  const chapterRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) onActiveChapterChange(visible.target.id);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: [0.1, 0.5, 1.0] },
    );
    Object.values(chapterRefs.current).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [book, onActiveChapterChange]);

  useEffect(() => {
    if (!scrollTarget) return;
    chapterRefs.current[scrollTarget]?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    onScrollHandled();
  }, [scrollTarget, onScrollHandled]);

  return (
    <div className={BOOK_PANEL_SURFACE}>
      <article className={cn(BOOK_PANEL_CONTAINER, "py-12 lg:py-16")}>
        {book.language_style_note && (
          <div className="mb-12 border-l-2 border-ink-700 pl-4">
            <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Style note
            </p>
            <p className="font-serif text-sm italic leading-relaxed text-ink-300">
              {book.language_style_note}
            </p>
          </div>
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
  );
}
