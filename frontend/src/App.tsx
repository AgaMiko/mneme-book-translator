import { useState } from "react";

import { BookList } from "@/components/BookList";
import { BookReader } from "@/components/BookReader";
import { UploadDropzone } from "@/components/UploadDropzone";

export default function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-ink-900 text-ink-50">
      {/* Sidebar */}
      <aside className="flex w-80 shrink-0 flex-col border-r border-ink-800 bg-ink-900">
        <header className="border-b border-ink-800 px-5 py-4">
          <h1 className="font-serif text-lg italic text-accent">Mneme</h1>
          <p className="mt-0.5 text-xs leading-snug text-ink-500">
            Translation that remembers.
          </p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink-500">
            pl → en
          </p>
        </header>

        <div className="border-b border-ink-800 p-4">
          <UploadDropzone onUploaded={setSelectedId} />
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          <p className="mb-2 px-2 text-xs uppercase tracking-wider text-ink-400">
            Library
          </p>
          <BookList
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDeleted={(id) => {
              if (id === selectedId) setSelectedId(null);
            }}
          />
        </div>

        <footer className="border-t border-ink-800 px-5 py-3">
          <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
            mneme · v0.1
          </p>
        </footer>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-hidden">
        {selectedId ? <BookReader bookId={selectedId} /> : <EmptyState />}
      </main>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full items-center justify-center reader-surface">
      <div className="max-w-md px-6 text-center">
        {/* Greek mu — the project's brand mark. Echoes the favicon and
            connects the empty state to the identity established in the
            sidebar header without repeating the wordmark. */}
        <div
          className="mb-6 inline-flex h-16 w-16 items-center justify-center rounded-full border border-ink-700 bg-ink-800/60"
          aria-hidden
        >
          <span className="font-serif text-3xl italic text-accent">μ</span>
        </div>
        <h2 className="font-serif text-2xl text-ink-100">
          Begin with a manuscript
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-400">
          Drop a <span className="font-mono text-xs text-ink-200">.docx</span>{" "}
          into the sidebar. Mneme will read your book end to end, build a
          glossary you can review, and remember every decision you make as
          translation proceeds.
        </p>
        <p className="mt-4 text-xs leading-relaxed text-ink-500">
          AI drafts. You decide. The book stays whole.
        </p>
      </div>
    </div>
  );
}
