import { ArrowRight } from "lucide-react";

import type { BookDetail } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import type { BookTab } from "./tabs";

interface Props {
  book: BookDetail;
  activeTab: BookTab;
  onSelectTab: (tab: BookTab) => void;
}

/**
 * One line. Always points at the next sensible action for the current
 * state of the book. Reads like a translator's note in a margin, not
 * a marketing nudge — italics, ink-400, no shouty styling.
 *
 * Returns `null` when the user is already where they should be (e.g.
 * on the Glossary tab during extraction). Silence is a feature; the
 * hint should not be a permanent fixture.
 */
export function WorkflowHint({ book, activeTab, onSelectTab }: Props) {
  const message = computeHint(book, activeTab);
  if (!message) return null;

  const { text, action } = message;

  return (
    <div className="border-b border-ink-800/60 bg-ink-900">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-6 py-2.5">
        <p className="font-serif text-sm italic leading-snug text-ink-400">
          {text}
        </p>
        {action && (
          <button
            type="button"
            onClick={() => onSelectTab(action.tab)}
            className={cn(
              "inline-flex items-center gap-1 rounded px-2 py-1",
              "font-mono text-[11px] uppercase tracking-wider text-accent",
              "hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
            )}
          >
            {action.label}
            <ArrowRight className="h-3 w-3" aria-hidden />
          </button>
        )}
      </div>
    </div>
  );
}

interface Hint {
  text: string;
  action?: {
    label: string;
    tab: BookTab;
  };
}

function computeHint(book: BookDetail, activeTab: BookTab): Hint | null {
  const glossaryStatus = book.glossary_extraction_status;

  // On Manuscript: nudge toward whatever the next workflow step is.
  if (activeTab === "manuscript") {
    if (glossaryStatus === "idle") {
      return {
        text: "Next: build a glossary of book-specific terms.",
        action: { label: "Open glossary", tab: "glossary" },
      };
    }
    if (glossaryStatus === "running") {
      return {
        text: "Glossary extraction is running in the background.",
        action: { label: "Watch progress", tab: "glossary" },
      };
    }
    if (glossaryStatus === "completed") {
      return {
        text: "Glossary is ready — review and accept terms before translation.",
        action: { label: "Review terms", tab: "glossary" },
      };
    }
    if (glossaryStatus === "cancelled") {
      return {
        text: "Glossary extraction was stopped — continue or restart it.",
        action: { label: "Open glossary", tab: "glossary" },
      };
    }
    if (glossaryStatus === "failed") {
      return {
        text: "Glossary extraction failed — open the workspace to retry.",
        action: { label: "Open glossary", tab: "glossary" },
      };
    }
  }

  // On Glossary: contextual instruction, no action button (user is here).
  if (activeTab === "glossary") {
    if (glossaryStatus === "idle") {
      return {
        text: "Estimate the run, then start. Mneme reads the full text in 1k-word windows.",
      };
    }
    if (glossaryStatus === "running") {
      return {
        text: "Extraction in flight — terms appear below as they're found.",
      };
    }
    if (glossaryStatus === "completed") {
      return {
        text: "Review and accept terms. Translation uses these decisions.",
      };
    }
  }

  return null;
}
