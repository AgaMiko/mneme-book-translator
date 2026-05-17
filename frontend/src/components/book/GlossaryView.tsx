import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import {
  GlossaryExtractionActionBar,
  GlossaryExtractionWorkspace,
} from "@/components/GlossaryExtractionWorkspace";
import { GlossaryReviewPanel } from "@/components/GlossaryReviewPanel";
import {
  bookKeys,
  useContinueGlossaryExtraction,
  useGlossaryExtractionEstimate,
  useStartGlossaryExtraction,
  useStopGlossaryExtraction,
} from "@/lib/api/hooks";
import type { BookDetail } from "@/lib/api/client";

interface Props {
  book: BookDetail;
}

/**
 * The working surface. Composes extraction controls (top) and the live
 * glossary table (below) as scrolling sections of one page.
 */
export function GlossaryView({ book }: Props) {
  const queryClient = useQueryClient();
  const estimate = useGlossaryExtractionEstimate(book.id, true);
  const startGlossary = useStartGlossaryExtraction(book.id);
  const continueGlossary = useContinueGlossaryExtraction(book.id);
  const stopGlossary = useStopGlossaryExtraction(book.id);
  const termsRef = useRef<HTMLDivElement | null>(null);

  const prevStatus = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevStatus.current;
    prevStatus.current = book.glossary_extraction_status;
    if (prev === "running" && book.glossary_extraction_status !== "running") {
      void queryClient.invalidateQueries({
        queryKey: bookKeys.workingGlossary(book.id),
      });
    }
  }, [book.glossary_extraction_status, book.id, queryClient]);

  const actionBarEnabled = Boolean(estimate.data && estimate.data.window_count > 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="reader-surface flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-6 py-10">
          <GlossaryExtractionWorkspace
            book={book}
            estimate={estimate}
            startGlossary={startGlossary}
            continueGlossary={continueGlossary}
            stopGlossary={stopGlossary}
            onOpenTerms={() => {
              termsRef.current?.scrollIntoView({
                behavior: "smooth",
                block: "start",
              });
            }}
          />

          <div className="my-12 border-t border-ink-800" />

          <div ref={termsRef} className="scroll-mt-6">
            <GlossaryReviewPanel
              bookId={book.id}
              pollWhileRunning={book.glossary_extraction_status === "running"}
            />
          </div>
        </div>
      </div>
      <GlossaryExtractionActionBar
        book={book}
        startGlossary={startGlossary}
        continueGlossary={continueGlossary}
        stopGlossary={stopGlossary}
        enabled={actionBarEnabled}
      />
    </div>
  );
}
