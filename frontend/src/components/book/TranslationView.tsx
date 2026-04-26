/**
 * Placeholder for the translation surface (step 4).
 *
 * Normally unreachable through the UI (the tab is disabled). Renders
 * "coming next" if a user lands here via a stale `?tab=translation` URL.
 */
export function TranslationView() {
  return (
    <div className="reader-surface flex h-full items-center justify-center">
      <div className="max-w-md px-6 text-center">
        <p className="font-mono text-[11px] uppercase tracking-wider text-ink-500">
          coming next
        </p>
        <h2 className="mt-3 font-serif text-2xl text-ink-100">
          Translation begins after glossary review
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-400">
          Once you've accepted a glossary, Mneme will translate fragment by
          fragment with the surrounding context, your accepted terms, and
          remembered character voices. Every decision stays yours to override.
        </p>
      </div>
    </div>
  );
}
