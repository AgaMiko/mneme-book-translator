import { useState } from "react";

import { BookReader } from "@/components/BookReader";
import { LibraryScreen } from "@/components/LibraryScreen";

/**
 * Two screens, one piece of state. `selectedId === null` is the library;
 * anything else is that book, full-window. The sidebar is gone — a rail
 * that is always half the chrome makes every screen feel like a panel of
 * a tool rather than a manuscript you are working on.
 */
export default function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-ink-900 text-ink-50">
      {selectedId ? (
        <BookReader bookId={selectedId} onBack={() => setSelectedId(null)} />
      ) : (
        <LibraryScreen onSelect={setSelectedId} />
      )}
    </div>
  );
}
