/**
 * Inline Markdown in translated text: `*italic*` and `**bold**`.
 *
 * Translations keep italics for thoughts, letters and titles the Markdown
 * way (the export renders them too). The reader shows them as italics
 * instead of raw asterisks. Offsets point into the raw text, so glossary
 * term spans (also raw offsets) can be laid over the result.
 *
 * Left as they are: scene breaks (a line of `***`) and asterisks without a
 * closing pair.
 */

export interface InlineRun {
  /** Raw-text offsets of the visible characters (markers excluded). */
  start: number;
  end: number;
  italic: boolean;
  bold: boolean;
}

const SCENE_BREAK = /^\s*(?:#{1,3}\s*)?\*\s*\*\s*\*\s*$/;
// Markers must hug the text (`*word*`, not `* word *`), as in Markdown.
const EMPHASIS = /\*\*(?=\S)(.+?)(?<=\S)\*\*|\*(?=\S)([^*\n]+?)(?<=\S)\*/g;

export function parseInline(text: string): InlineRun[] {
  const runs: InlineRun[] = [];
  const plain = (start: number, end: number) => {
    if (end > start) runs.push({ start, end, italic: false, bold: false });
  };
  let lineStart = 0;
  for (const line of text.split("\n")) {
    const lineEnd = lineStart + line.length;
    if (SCENE_BREAK.test(line)) {
      plain(lineStart, lineEnd);
    } else {
      let pos = 0;
      for (const m of line.matchAll(EMPHASIS)) {
        const at = m.index ?? 0;
        plain(lineStart + pos, lineStart + at);
        const bold = m[1] !== undefined;
        const marker = bold ? 2 : 1;
        const inner = bold ? m[1] : m[2];
        runs.push({
          start: lineStart + at + marker,
          end: lineStart + at + marker + inner.length,
          italic: !bold,
          bold,
        });
        pos = at + m[0].length;
      }
      plain(lineStart + pos, lineEnd);
    }
    plain(lineEnd, Math.min(lineEnd + 1, text.length)); // the newline itself
    lineStart = lineEnd + 1;
  }
  return runs;
}
