import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { GlossaryExtractionWorkspace } from "@/components/GlossaryExtractionWorkspace";
import { GlossaryReviewPanel } from "@/components/GlossaryReviewPanel";
import {
  bookKeys,
  useContinueGlossaryExtraction,
  useGlossaryExtractionEstimate,
  useStartGlossaryExtraction,
  useStopGlossaryExtraction,
  useWorkingGlossary,
} from "@/lib/api/hooks";
import type { BookDetail } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";

interface Props {
  book: BookDetail;
  /** A glossary entry to open and scroll to (from the Translation tab). */
  focusEntryId?: string | null;
  onFocusHandled?: () => void;
}

/**
 * The working surface. The run card sits at the top of the scroll area
 * and the terms follow immediately below it — no sticky bar, no jump
 * links, because there is nothing between them to jump over.
 */
export function GlossaryView({ book, focusEntryId = null, onFocusHandled }: Props) {
  const queryClient = useQueryClient();
  const estimate = useGlossaryExtractionEstimate(book.id, true);
  const startGlossary = useStartGlossaryExtraction(book.id);
  const continueGlossary = useContinueGlossaryExtraction(book.id);
  const stopGlossary = useStopGlossaryExtraction(book.id);
  /**
   * Same query key the review panel below uses — react-query serves both
   * from one fetch, so the run card can name the run without a second
   * request.
   */
  const working = useWorkingGlossary(book.id, {
    enabled: true,
    refetchIntervalMs: book.glossary_extraction_status === "running" ? 2000 : false,
  });

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

  return (
    <div className={BOOK_PANEL_SURFACE}>
      <div className={cn(BOOK_PANEL_CONTAINER, "py-8")}>
        <GlossaryExtractionWorkspace
          book={book}
          estimate={estimate}
          startGlossary={startGlossary}
          continueGlossary={continueGlossary}
          stopGlossary={stopGlossary}
          run={working.data?.run ?? null}
        />

        <div className="mt-8">
          <GlossaryReviewPanel
            bookId={book.id}
            focusEntryId={focusEntryId}
            onFocusHandled={onFocusHandled}
            pollWhileRunning={book.glossary_extraction_status === "running"}
          />
        </div>
      </div>
    </div>
  );
}
