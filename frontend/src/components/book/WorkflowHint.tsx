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
 * on the Glossary tab during extraction). Silence is a feature.
 */
export function WorkflowHint({ book, activeTab, onSelectTab }: Props) {
  const message = computeHint(book, activeTab);
  if (!message) return null;

  const { text, action } = message;

  return (
    <div className="border-b border-ink-800 bg-ink-900">
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
              "hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
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
      if (book.speakers_extraction_status === "running") {
        return {
          text: "Speaker identification is running — mapping who speaks in each window.",
          action: { label: "Watch progress", tab: "voices" },
        };
      }
      if (book.speakers_extraction_status !== "completed") {
        return {
          text: "Glossary is ready — identify speakers per window first, then run voice extraction.",
          action: { label: "Open voices", tab: "voices" },
        };
      }
      if (book.voice_extraction_status === "running") {
        return {
          text: "Voice extraction is running in the background.",
          action: { label: "Watch progress", tab: "voices" },
        };
      }
      if (book.voice_extraction_status !== "completed") {
        return {
          text: "Speakers are mapped — run character voice extraction next.",
          action: { label: "Open voices", tab: "voices" },
        };
      }
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

  if (activeTab === "voices") {
    if (book.glossary_extraction_status !== "completed") {
      return {
        text: "Finish the glossary first — voices attach only to character entries there.",
        action: { label: "Open glossary", tab: "glossary" },
      };
    }
    if (book.speakers_extraction_status === "idle") {
      return {
        text: "Pass 1: identify which glossary characters speak in each window (quoted lines only).",
      };
    }
    if (book.speakers_extraction_status === "running") {
      return {
        text: "Pass 1 in flight — one window at a time, with verbatim evidence per speaker.",
      };
    }
    if (book.speakers_extraction_status !== "completed") {
      return {
        text: "Finish or reset speaker identification before voice extraction for best grounding.",
      };
    }
    if (book.voice_extraction_status === "idle") {
      return {
        text: "Pass 2: extract voice observations and strategies for characters that speak.",
      };
    }
    if (book.voice_extraction_status === "running") {
      return {
        text: "Profiles update as each window finishes.",
      };
    }
    if (book.voice_extraction_status === "completed") {
      return {
        text: "Accept or reject each profile; rejected voices stay out of the next extraction pass.",
      };
    }
  }

  return null;
}
