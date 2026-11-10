import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  BookDetail,
  ManuscriptSpeakerLine,
  NarrationScene,
  TermSpan,
  TranslationView,
} from "@/lib/api/client";
import {
  useManuscriptNarration,
  useManuscriptSpeakers,
  useManuscriptTerms,
  useTranslation,
} from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";
import { HighlightedText, TermProvider } from "./TermHighlight";

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
  /** A glossary term clicked in the text: open it in the glossary. */
  onOpenTerm: (termId: string) => void;
}

/**
 * What each pipeline step has added to the text, drawn as layers you can
 * switch on and off: whose point of view each scene's narration follows,
 * who speaks each dialogue line, the glossary terms found so far (pending
 * ones too), and the translation under each paragraph. A layer is offered
 * once there is something to show.
 */
type Layer = "narration" | "speakers" | "glossary" | "translation";

const LAYER_LABELS: Record<Layer, string> = {
  narration: "Narration POV",
  speakers: "Speakers",
  glossary: "Glossary",
  translation: "Translation",
};

const LAYERS_STORAGE_KEY = "manuscript-layers";

function loadLayers(): Record<Layer, boolean> {
  const all = { narration: true, speakers: true, glossary: true, translation: false };
  try {
    const saved = JSON.parse(localStorage.getItem(LAYERS_STORAGE_KEY) ?? "null");
    return saved ? { ...all, ...saved } : all;
  } catch {
    return all;
  }
}

function saveLayers(layers: Record<Layer, boolean>) {
  try {
    localStorage.setItem(LAYERS_STORAGE_KEY, JSON.stringify(layers));
  } catch {
    // Private window or blocked storage: the choice lasts for this visit only.
  }
}

/**
 * Character colours, shared by the speaker bars and the narration band:
 * speakers in order of first line, then POV characters with no lines.
 * Mid-tone hues so the bar reads on parchment and on the dark surface.
 */
const SPEAKER_COLORS = [
  "#c2410c",
  "#0e7490",
  "#7c3aed",
  "#15803d",
  "#be185d",
  "#a16207",
  "#2563eb",
  "#65a30d",
  "#c026d3",
  "#dc2626",
];

const NO_SPANS: TermSpan[] = [];
const STAGE_ORDER = ["polish", "line_edit", "faithful"] as const;

/** The most finished translation of each source paragraph. */
function translatedParagraphs(view: TranslationView | undefined): Map<string, string> {
  const out = new Map<string, string>();
  for (const chapter of view?.chapters ?? []) {
    for (const fragment of chapter.fragments) {
      const stage = STAGE_ORDER.map((s) => fragment.stages[s]).find(Boolean);
      for (const p of stage?.paragraphs ?? []) out.set(p.paragraph_id, p.text);
    }
  }
  return out;
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
  onOpenTerm,
}: Props) {
  const chapterRefs = useRef<Record<string, HTMLElement | null>>({});

  const speakers = useManuscriptSpeakers(book.id, {
    enabled: book.speakers_extraction_status !== "idle",
    refetchIntervalMs: book.speakers_extraction_status === "running" ? 4000 : false,
  });
  const terms = useManuscriptTerms(book.id, {
    enabled: book.glossary_extraction_status !== "idle",
    refetchIntervalMs: book.glossary_extraction_status === "running" ? 5000 : false,
  });
  const translation = useTranslation(book.id);
  const narration = useManuscriptNarration(book.id);

  const speakerByParagraph = useMemo(
    () => new Map((speakers.data?.lines ?? []).map((l) => [l.paragraph_id, l])),
    [speakers.data],
  );
  const sceneByParagraph = useMemo(() => {
    const out = new Map<string, SceneSpot>();
    for (const scene of narration.data?.scenes ?? []) {
      const ids = scene.paragraph_ids;
      ids.forEach((id, i) => out.set(id, { scene, first: i === 0, last: i === ids.length - 1 }));
    }
    return out;
  }, [narration.data]);
  const characterColor = useMemo(() => {
    const colors = new Map<string, string>();
    const ids = [
      ...(speakers.data?.lines ?? []).map((l) => l.speaker_id),
      ...(narration.data?.scenes ?? []).map((s) => s.pov_id),
    ];
    for (const id of ids) {
      if (id && !colors.has(id)) {
        colors.set(id, SPEAKER_COLORS[colors.size % SPEAKER_COLORS.length]);
      }
    }
    return colors;
  }, [speakers.data, narration.data]);
  const translationByParagraph = useMemo(
    () => translatedParagraphs(translation.data),
    [translation.data],
  );

  const counts: Record<Layer, number> = {
    narration: narration.data?.scenes.length ?? 0,
    speakers: speakerByParagraph.size,
    glossary: terms.data?.terms.length ?? 0,
    translation: translationByParagraph.size,
  };
  const [layers, setLayers] = useState(loadLayers);
  const toggleLayer = useCallback((layer: Layer) => {
    setLayers((prev) => {
      const next = { ...prev, [layer]: !prev[layer] };
      saveLayers(next);
      return next;
    });
  }, []);
  const show = (layer: Layer) => layers[layer] && counts[layer] > 0;

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
      <LayerBar layers={layers} counts={counts} onToggle={toggleLayer} />
      <TermProvider
        terms={terms.data?.terms ?? []}
        sourceSpans={terms.data?.paragraphs ?? {}}
        onOpenTerm={onOpenTerm}
      >
        <article className={cn(BOOK_PANEL_CONTAINER, "py-12 lg:py-16")}>
          {book.language_style_note && (
            <div className="mb-12 border-l-2 border-ink-700 pl-4">
              <p className="mb-2 font-mono text-label uppercase tracking-wider text-ink-500">
                Style note
              </p>
              <p className="font-serif text-body italic text-ink-300">{book.language_style_note}</p>
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
                className="mb-16 scroll-mt-20"
              >
                <h2 className="mb-6 font-serif text-heading text-accent">{label}</h2>
                <div className="chapter-body space-y-5 font-serif text-reading text-ink-100">
                  {chapter.paragraphs.length === 0 ? (
                    <p className="italic text-ink-500">[empty chapter]</p>
                  ) : (
                    chapter.paragraphs.map((p) => {
                      const line = show("speakers") ? speakerByParagraph.get(p.id) : undefined;
                      const spot = show("narration") ? sceneByParagraph.get(p.id) : undefined;
                      return (
                        <ManuscriptParagraph
                          key={p.id}
                          text={p.text}
                          spans={
                            show("glossary") ? (terms.data?.paragraphs[p.id] ?? NO_SPANS) : NO_SPANS
                          }
                          line={line}
                          color={line?.speaker_id ? characterColor.get(line.speaker_id) : undefined}
                          spot={spot}
                          povColor={
                            spot?.scene.pov_id ? characterColor.get(spot.scene.pov_id) : undefined
                          }
                          translated={
                            show("translation") ? translationByParagraph.get(p.id) : undefined
                          }
                        />
                      );
                    })
                  )}
                </div>
              </section>
            );
          })}
        </article>
      </TermProvider>
    </div>
  );
}

/** Switches for the layers, pinned to the top of the reading surface. */
function LayerBar({
  layers,
  counts,
  onToggle,
}: {
  layers: Record<Layer, boolean>;
  counts: Record<Layer, number>;
  onToggle: (layer: Layer) => void;
}) {
  return (
    <div className="sticky top-0 z-30 border-b border-ink-800 bg-ink-900/90 backdrop-blur-sm">
      <div className={cn(BOOK_PANEL_CONTAINER, "flex flex-wrap items-center gap-2 py-2")}>
        <span className="mr-1 font-mono text-label uppercase tracking-wider text-ink-500">
          Show
        </span>
        {(Object.keys(LAYER_LABELS) as Layer[]).map((layer) => {
          const empty = counts[layer] === 0;
          const on = layers[layer] && !empty;
          return (
            <button
              key={layer}
              type="button"
              aria-pressed={on}
              disabled={empty}
              onClick={() => onToggle(layer)}
              title={empty ? "Nothing from this step yet" : undefined}
              className={cn(
                "rounded-full border px-2.5 py-0.5 font-sans text-small transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                on
                  ? "border-accent bg-accent-soft text-ink-50"
                  : "border-ink-700 text-ink-400 hover:text-ink-200",
                empty && "cursor-not-allowed opacity-50 hover:text-ink-400",
              )}
            >
              {LAYER_LABELS[layer]}
              <span className="ml-1.5 font-mono text-label text-ink-500">
                {empty ? "—" : formatNumber(counts[layer])}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Where a paragraph sits in its scene, for drawing the narration band. */
interface SceneSpot {
  scene: NarrationScene;
  first: boolean;
  last: boolean;
}

const KIND_LABELS: Record<string, string> = {
  speech: "says",
  thought: "thinks",
  unknown: "unclear",
};

/**
 * One source paragraph with whatever layers are on. A dialogue line gets
 * a bar in the left gutter in its speaker's colour (dashed when the
 * speaker is unknown); hovering the paragraph names the speaker. Further
 * out, a band runs down each scene in its POV character's colour, with a
 * label at the scene's start; it is dashed where the POV is not marked.
 */
function ManuscriptParagraph({
  text,
  spans,
  line,
  color,
  spot,
  povColor,
  translated,
}: {
  text: string;
  spans: TermSpan[];
  line: ManuscriptSpeakerLine | undefined;
  color: string | undefined;
  spot: SceneSpot | undefined;
  povColor: string | undefined;
  translated: string | undefined;
}) {
  const marked = spot && (spot.scene.source === "heading" || spot.scene.source === "scene_break");
  return (
    <div className="manuscript-paragraph group relative">
      {spot && (
        <>
          {/* Runs into the gap below so a scene reads as one band. */}
          <span
            aria-hidden
            className={cn(
              "absolute -left-7 top-0 w-0 border-l-2",
              spot.last ? "bottom-0" : "-bottom-5",
              marked ? "border-solid" : "border-dashed",
              !povColor && "border-ink-600",
            )}
            style={povColor ? { borderColor: povColor, opacity: marked ? 0.7 : 0.45 } : undefined}
          />
          {spot.first && <PovLabel scene={spot.scene} color={povColor} />}
        </>
      )}
      {line && (
        <>
          <span
            aria-hidden
            className={cn(
              "absolute -left-4 bottom-1 top-1 w-[3px] rounded-full",
              !color && "border-l-[3px] border-dashed border-ink-500",
            )}
            style={color ? { backgroundColor: color } : undefined}
          />
          <SpeakerCard line={line} color={color} />
        </>
      )}
      <p>
        <HighlightedText text={text} spans={spans} />
      </p>
      {translated && (
        <p className="mt-1.5 border-l border-ink-700 pl-3 font-serif text-reading text-ink-400">
          <HighlightedText text={translated} spans={NO_SPANS} />
        </p>
      )}
    </div>
  );
}

const POV_NOTES: Record<NarrationScene["source"], string> = {
  heading: "from the chapter heading",
  scene_break: "named at the scene break",
  assumed: "assumed: unnamed scene break, carried over from the chapter heading",
  unknown: "no POV marker",
};

function PovLabel({ scene, color }: { scene: NarrationScene; color: string | undefined }) {
  const flagged = scene.source === "assumed" || scene.source === "unknown";
  return (
    <div className="mb-1.5 flex items-center gap-1.5 font-sans text-label leading-none">
      <span
        aria-hidden
        className="h-2 w-2 rounded-full bg-ink-600"
        style={color ? { backgroundColor: color } : undefined}
      />
      <span className="font-mono uppercase tracking-wider text-ink-500">POV</span>
      <span className="font-medium text-ink-200">{scene.pov_name ?? "unknown"}</span>
      <span className={flagged ? "text-warning" : "text-ink-500"}>· {POV_NOTES[scene.source]}</span>
    </div>
  );
}

function SpeakerCard({ line, color }: { line: ManuscriptSpeakerLine; color: string | undefined }) {
  const kind = KIND_LABELS[line.kind] ?? line.kind;
  return (
    <span
      role="tooltip"
      className={cn(
        "pointer-events-none absolute -left-4 bottom-full z-10 mb-1 hidden items-center gap-1.5",
        "whitespace-nowrap rounded-md border border-ink-700 bg-ink-900 px-2 py-1",
        "font-sans text-small leading-none text-ink-200 shadow-md group-hover:flex",
      )}
    >
      <span
        aria-hidden
        className="h-2 w-2 rounded-full bg-ink-500"
        style={color ? { backgroundColor: color } : undefined}
      />
      <span className="font-medium text-ink-50">{line.speaker_name ?? "Unknown speaker"}</span>
      <span className="text-ink-500">{kind}</span>
      {line.addressee_name && <span className="text-ink-400">→ {line.addressee_name}</span>}
      {line.mixed && <span className="text-ink-500">· mixed</span>}
      {line.confidence === "inferred" && <span className="text-warning">· inferred</span>}
    </span>
  );
}
