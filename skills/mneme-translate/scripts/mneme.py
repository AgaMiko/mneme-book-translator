# /// script
# requires-python = ">=3.10"
# dependencies = ["python-docx>=1.1"]
# ///
"""Helper for the mneme-translate skill.

Claude does the reading and translating. This script does the parts that
need exact counting: splitting the manuscript, cutting fragments, merging
translated paragraphs into chapter files, checks, and export. It keeps all
state in plain files inside the book folder, so a run can stop and continue.

Run it with uv (installs python-docx for .docx input on the fly):

    uv run scripts/mneme.py <command> [args]

or with plain Python 3.10+ (python-docx is needed only to read .docx).

Commands (run in the book folder, or pass --dir):

    prepare <manuscript> --source-language pl [--title T] [--target-title T]
            [--target-language English] [--force]
        Split a .docx, .md or .txt manuscript into source/chapter-NN.md
        and plan fragments of about 1,200 words. Writes mneme.json. Text
        before the first chapter heading goes to source/front-matter.md.
    status                      Steps, fragments done, next fragment.
    mark <step> <state>         Record a step state, e.g. "mark glossary reviewed".
    dialogue [chapters] [--skeleton | --group]
                                Paragraphs that look like dialogue, with ids.
                                --skeleton writes work/lines-draft.md to fill in;
                                --group turns it into work/lines.md per speaker.
    terms <chapter>             Glossary terms found in a chapter (source side).
    fragment <id>               One fragment with its neighbours, the glossary
                                terms and voice files that apply to it.
    save <id> <file>            Check a translated fragment (same ids, same
                                order) and merge it into translation/chapter-NN.md.
    letters <chapter> <first> <last> [--translation] [--from WORDS] [--to WORDS]
                                First letters of sentences, lines, paragraphs
                                and words of a passage, for hidden messages.
    check [chapters]            Write check-report.md: missing paragraphs,
                                leftover source letters, dialogue dashes,
                                placeholders, glossary use, style metrics.
                                Merges notes/chapter-NN.md into notes.md.
    export [--draft] [--chapters 1-2] [--title T]
                                Write export/<title>.md (and .docx / .epub
                                when pandoc is installed).

Chapters are given as 3, 1-4 or 1,3,5-6.

The rules and numbers mirror the Mneme app (backend/app/services/fragmenter.py,
translation_qa.py, constants/languages.py, manuscript_parser.py).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

# ─── Numbers and language facts copied from the app ─────────────────────

TARGET_WORDS = 1200  # fragmenter.TARGET_WORDS
MIN_WORDS_BEFORE_SCENE_CUT = 600
MIN_TAIL_WORDS = 400  # the app uses 250; 400 avoids tiny last fragments
NEIGHBOUR_PARAGRAPHS = 2  # paragraphs of context on each side of a fragment

SOURCE_LETTERS = {  # constants/languages.py
    "pl": ("Polish", "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"),
    "de": ("German", "äöüßÄÖÜ"),
    "kn": ("Kannada", "\u0c80-\u0cff"),
}

_NUMBER = r"\s+[\divxlcdm]+"
CHAPTER_MARKERS = {  # manuscript_parser._CHAPTER_MARKERS_BY_LANGUAGE
    "pl": [r"rozdzia[łl]" + _NUMBER, r"prolog(?:\s+.*)?$", r"epilog(?:\s+.*)?$"],
    "de": [r"kapitel" + _NUMBER, r"prolog(?:\s+.*)?$", r"epilog(?:\s+.*)?$"],
}
EN_CHAPTER_MARKERS = [r"chapter" + _NUMBER, r"prologue(?:\s+.*)?$", r"epilogue(?:\s+.*)?$"]

# translation_qa.py targets
SHE_HE_MAX_PCT = 15.0
ELLIPSES_MAX_PER_1K = 3.0
DASHES_MAX_PER_1K = 6.0
STOCK_PHRASES = (
    r"the weight of", r"\ba beat\b", r"ghost of a smile", r"a flicker of",
    r"couldn't help but", r"something shifted", r"didn't know (?:she|he) was holding",
    r"let out a breath (?:she|he)", r"a wave of(?! (?:her |his |their |the |a )?hand)", r"for a heartbeat", r"(?:^|(?<=\n)|(?<=[.!?…\"”] ))[*_]?suddenly\b",
)
STOCK_LABEL = {STOCK_PHRASES[-1]: "Suddenly (opening a sentence)"}
PLACEHOLDER = re.compile(r"x{4,}|\[x+\]")

SCENE_BREAK = re.compile(r"^\*\*\*(?: |$)")
STAR_SPLIT = re.compile(r"(?:^|\s+)(?<!\*)\*{3}(?!\*)(?:\s+|$)")  # "***" standing alone in a paragraph
MD_ESCAPE = re.compile(r"\\([!.\-()\[\]#+>~'\"`=|{}])")  # \! \. and the like; \* and \_ are kept
ID_LINE = re.compile(r"^\[([A-Za-z0-9_-]+)\]\s*$")
DIALOGUE_START = re.compile(r"^\s*[–—-]\s")
# A sentence ends at . ! ? or …, maybe followed by closing quotes or italic marks.
SENTENCE_END = re.compile(r"(?<=[.!?\u2026])[*_\"\u201d\u2019\u00bb)]*\s+")
QUOTES = re.compile(r"[„”\"“«»]")

STATE_FILE = "mneme.json"


# ─── Paragraph files: "[id]" on its own line, then the text ─────────────


def read_paragraphs(path: Path) -> list[tuple[str, str]]:
    """Read a file of "[id]\\ntext" blocks. Text may span lines."""
    if not path.exists():
        return []
    out: list[tuple[str, str]] = []
    pid: str | None = None
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ID_LINE.match(line)
        if m:
            if pid is not None:
                out.append((pid, "\n".join(buf).strip()))
            pid, buf = m.group(1), []
        elif pid is not None:
            buf.append(line)
    if pid is not None:
        out.append((pid, "\n".join(buf).strip()))
    return out


def write_paragraphs(path: Path, header: str, paras: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(f"[{pid}]\n{text}" for pid, text in paras)
    path.write_text(f"{header}\n\n{body}\n", encoding="utf-8")


def render(paras: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[{pid}]\n{text}" for pid, text in paras)


# ─── State ──────────────────────────────────────────────────────────────


def load_state(root: Path) -> dict:
    path = root / STATE_FILE
    if not path.exists():
        sys.exit(f"No {STATE_FILE} in {root}. Run 'prepare' first.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(root: Path, state: dict) -> None:
    (root / STATE_FILE).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def chapter_file(root: Path, n: int, kind: str = "source") -> Path:
    return root / kind / f"chapter-{n:02d}.md"


def find_fragment(state: dict, fid: str) -> dict:
    for f in state["fragments"]:
        if f["id"] == fid:
            return f
    sys.exit(f"No fragment {fid}. Run 'status' to see the ids.")


def translated_ids(root: Path, n: int) -> set[str]:
    return {pid for pid, text in read_paragraphs(chapter_file(root, n, "translation")) if text}


# ─── prepare ────────────────────────────────────────────────────────────


def chapter_pattern(lang: str) -> re.Pattern[str]:
    keys = CHAPTER_MARKERS.get(lang.lower(), []) + EN_CHAPTER_MARKERS
    return re.compile(rf"^\s*({'|'.join(keys)})", re.IGNORECASE)


def docx_blocks(path: Path) -> tuple[str | None, list[tuple[str, str | None]]]:
    """(title, [(text, style)]). Italic and bold runs become *…* and **…**."""
    try:
        from docx import Document
    except ImportError:
        sys.exit("Reading .docx needs python-docx: run with 'uv run' or 'pip install python-docx'.")
    doc = Document(str(path))
    blocks: list[tuple[str, str | None]] = []
    for para in doc.paragraphs:
        parts = []
        for run in para.runs:
            t = run.text
            if not t.strip():
                parts.append(t)
                continue
            lead, core, trail = re.match(r"^(\s*)(.*?)(\s*)$", t, re.S).groups()
            if run.bold:
                core = f"**{core}**"
            elif run.italic:
                core = f"*{core}*"
            parts.append(lead + core + trail)
        # Adjacent runs with the same formatting leave "**" or "* *" seams; join them.
        text = re.sub(r"\*\*\*\*|(?<=\w)\*\*(?=\w)", "", "".join(parts)).strip()
        blocks.append((text, para.style.name if para.style else None))
    return (doc.core_properties.title or None), blocks


def text_blocks(path: Path) -> list[tuple[str, str | None]]:
    """Paragraphs of .md/.txt: blank-line separated, or one per line if no blank lines."""
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    chunks = [c for c in re.split(r"\n\s*\n", raw) if c.strip()]
    if len(chunks) <= 2 and raw.count("\n") > 10:
        chunks = [line for line in raw.split("\n") if line.strip()]
    out: list[tuple[str, str | None]] = []
    for c in chunks:
        c = c.strip()
        if re.fullmatch(r"#+", c):
            continue  # an empty heading line
        m = re.match(r"^(#{1,2})\s+(.*)$", c)
        if m and "\n" not in c:
            out.append((m.group(2).strip(), "Title" if m.group(1) == "#" and not out else "Heading 1"))
        else:
            out.append((c, None))
    return out


def plain(text: str) -> str:
    """Text without markdown marks: heading signs, escapes, * and _."""
    return re.sub(r"\s+", " ", re.sub(r"[*_\\]", "", re.sub(r"^\s*#+\s*", "", text))).strip()


def has_chapter_word(text: str, pattern: re.Pattern[str], heading: bool) -> bool:
    """A heading counts as a chapter heading when a chapter word appears anywhere in it
    ("*Mira* **Rozdział 1** …"); a plain paragraph only when it starts with one."""
    p = plain(text)
    if heading:
        return any(pattern.match(p[m.start():]) for m in re.finditer(r"(?<!\w)\w", p))
    return bool(pattern.match(p))


def scene_break(text: str) -> str | None:
    """'***' or '*** Name' when the block is a scene break, else None. Accepts the
    escaped forms of Word-to-Markdown exports: '### **\\*\\*\\***', '### **\\*\\*\\* Kerry**'."""
    t = text.strip()
    escaped = t.startswith("#") or "\\*" in t
    if not escaped:
        m = re.fullmatch(r"\*\s*\*\s*\*(?:\s+(\S.*))?", t)
        name = m.group(1) if m else None
        if not m or (name and (name.startswith("*") or len(name.split()) > 3 or re.search(r"[.!?…]", name))):
            return None
    else:
        t = re.sub(r"^#+\s*", "", t).replace("\\", "")
        m = re.fullmatch(r"\*{3,}\s*(.*?)\s*", t)
        if not m:
            return None
        name = m.group(1).strip("* ").strip()
        if name and (len(name.split()) > 3 or re.search(r"[.!?…]", name)):
            return None
    return f"*** {name}" if name else "***"


def split_heading(text: str) -> str:
    """Put each part of a chapter heading on its own line: the POV name, the chapter
    line, each epigraph line and the attribution. Parts are separated by two spaces or
    sit in separate italic/bold runs ('*line one.* *line two.*')."""
    parts = [p.strip() for p in re.split(r"\s{2,}", text.strip()) if p.strip()]
    lines: list[str] = []
    for part in parts:
        lines += [s for s in re.split(r"(?<=[^\s*]\*)\s+(?=\*[^\s*])", part) if s.strip()]
    return "\n".join(lines)


def short_label(title: str) -> str:
    """'chapter 2 (Einard)'-style label: the first line of the heading, without marks."""
    first = plain(split_heading(title).split("\n")[0]) if title else ""
    return first[:40]


def cmd_prepare(root: Path, a: argparse.Namespace) -> None:
    src = Path(a.manuscript).expanduser()
    if not src.exists():
        sys.exit(f"Manuscript not found: {src}")
    if (root / STATE_FILE).exists():
        if not a.force:
            sys.exit(f"{STATE_FILE} already exists. Use --force to split the manuscript again.")
        if any((root / "translation").glob("chapter-*.md")):
            sys.exit("translation/ already has chapter files, and a new split may change paragraph ids. "
                     "Move translation/ aside first if you really want to split again.")
        written = [d for d in ("work", "voices") if any((root / d).glob("*.md"))] \
            + (["notes.md"] if (root / "notes.md").exists() else [])
        if written:
            print(f"Warning: {', '.join(written)} already exist. Paragraph ids may change with the new "
                  "split, so line ids in work/lines.md, voice evidence and notes may point at the "
                  "wrong paragraphs. Compare source/ before and after.")
        for old in (root / "source").glob("chapter-*.md"):
            old.unlink()
    lang = a.source_language.lower()
    title = a.title
    if src.suffix.lower() == ".docx":
        doc_title, blocks = docx_blocks(src)
        title = title or doc_title
    else:
        blocks = text_blocks(src)
    pattern = chapter_pattern(lang)
    blocks = [(t, s) for t, s in blocks if t]

    def is_heading(style: str | None) -> bool:
        s = (style or "").lower()
        return s == "title" or s.startswith("heading 1")

    # Text before the first chapter heading (title page, author, dedication) is front matter.
    first_chapter = next((i for i, (t, s) in enumerate(blocks)
                          if has_chapter_word(t, pattern, is_heading(s))), None)
    front: list[str] = []
    if first_chapter:
        front = [t for t, _ in blocks[:first_chapter]]
        if blocks[0][1] == "Title":
            title = title or blocks[0][0]
        blocks = blocks[first_chapter:]

    chapters: list[dict] = []
    current: dict = {"title": None, "paras": []}
    for text, style in blocks:
        s = (style or "").lower()
        chapter_word = has_chapter_word(text, pattern, is_heading(style))
        if s == "title" and not chapter_word and not chapters and not current["paras"] and current["title"] is None:
            title = title or text
            continue
        if s.startswith("heading 1") or chapter_word:
            if current["paras"] or current["title"] is not None:
                chapters.append(current)
            current = {"title": split_heading(text), "paras": []}
            continue
        if brk := scene_break(text):
            current["paras"].append(brk)
            continue
        text = MD_ESCAPE.sub(r"\1", text)
        parts = STAR_SPLIT.split(text)
        for i, part in enumerate(parts):
            if part.strip():
                current["paras"].append(part.strip())
            if i < len(parts) - 1:
                current["paras"].append("***")
    if current["paras"] or current["title"] is not None:
        chapters.append(current)
    if not chapters:
        sys.exit("No text found in the manuscript.")

    (root / "source").mkdir(parents=True, exist_ok=True)
    if front:
        (root / "source" / "front-matter.md").write_text("\n\n".join(front) + "\n", encoding="utf-8")
    state_chapters, fragments = [], []
    for n, ch in enumerate(chapters, 1):
        paras: list[tuple[str, str]] = []
        if ch["title"]:
            paras.append(("title", ch["title"]))
        paras += [(f"p{i:03d}", t) for i, t in enumerate(ch["paras"], 1)]
        write_paragraphs(chapter_file(root, n), f"<!-- Chapter {n} source. One [id] per paragraph. -->", paras)
        words = sum(len(t.split()) for _, t in paras)
        state_chapters.append({"n": n, "title": ch["title"] or f"Chapter {n}",
                               "label": short_label(ch["title"] or ""), "words": words})
        fragments += plan_fragments(n, paras)

    state = {
        "title": title or src.stem,
        "target_title": a.target_title,
        "manuscript": str(src),
        "source_language": SOURCE_LETTERS.get(lang, (a.source_language,))[0],
        "source_language_code": lang,
        "source_letters": a.letters if a.letters is not None else SOURCE_LETTERS.get(lang, ("", ""))[1],
        "target_language": a.target_language,
        "steps": {"split": "done", "glossary": "todo", "voices": "todo",
                  "passages": "todo", "translation": "todo", "check": "todo", "export": "todo"},
        "chapters": state_chapters,
        "fragments": fragments,
    }
    save_state(root, state)
    for d in ("translation", "voices", "work", "notes"):
        (root / d).mkdir(exist_ok=True)
    total = sum(c["words"] for c in state_chapters)
    print(f"Split '{state['title']}': {len(state_chapters)} chapters, {total} words, "
          f"{len(fragments)} fragments. State in {root / STATE_FILE}.")
    if front:
        print(f"Front matter before chapter 1 ({sum(len(t.split()) for t in front)} words) "
              "is in source/front-matter.md and is not translated.")
    untitled = [c["n"] for c in state_chapters if not chapters[c["n"] - 1]["title"]]
    if untitled:
        print(f"Chapters without a heading: {untitled}. Check that the split is right.")
    if not state["source_letters"]:
        print(f"Note: no letter list for '{lang}'. Pass --letters to enable the leftover-letters check.")


def plan_fragments(n: int, paras: list[tuple[str, str]]) -> list[dict]:
    """Same rules as the app's fragmenter: ~1,200 words, cut early at a scene
    break after 600; a tail under MIN_TAIL_WORDS joins the previous fragment."""
    frags: list[dict] = []
    cur: dict | None = None
    for pid, text in paras:
        words = len(text.split())
        if cur and cur["ids"]:
            if cur["words"] >= TARGET_WORDS or (SCENE_BREAK.match(text) and cur["words"] >= MIN_WORDS_BEFORE_SCENE_CUT):
                frags.append(cur)
                cur = None
        if cur is None:
            cur = {"ids": [], "words": 0}
        cur["ids"].append(pid)
        cur["words"] += words
    if cur and cur["ids"]:
        if frags and cur["words"] < MIN_TAIL_WORDS:
            frags[-1]["ids"] += cur["ids"]
            frags[-1]["words"] += cur["words"]
        else:
            frags.append(cur)
    return [{"id": f"{n:02d}-{i}", "chapter": n, "ids": f["ids"], "words": f["words"]}
            for i, f in enumerate(frags, 1)]


# ─── status / mark ──────────────────────────────────────────────────────


def fragment_done(root: Path, f: dict, cache: dict[int, set[str]]) -> bool:
    if f["chapter"] not in cache:
        cache[f["chapter"]] = translated_ids(root, f["chapter"])
    return set(f["ids"]) <= cache[f["chapter"]]


def cmd_status(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    cache: dict[int, set[str]] = {}
    done = [f for f in st["fragments"] if fragment_done(root, f, cache)]
    words_done = sum(f["words"] for f in done)
    words_all = sum(f["words"] for f in st["fragments"])
    print(f"{st['title']} ({st['source_language']} → {st['target_language']})")
    print("Steps: " + ", ".join(f"{k} {v}" for k, v in st["steps"].items()))
    print(f"Fragments: {len(done)}/{len(st['fragments'])} translated, "
          f"{words_done}/{words_all} words ({100 * words_done // max(words_all, 1)}%)")
    for ch in st["chapters"]:
        frs = [f for f in st["fragments"] if f["chapter"] == ch["n"]]
        k = sum(fragment_done(root, f, cache) for f in frs)
        mark = "✓" if k == len(frs) else f"{k}/{len(frs)}"
        print(f"  {ch['n']:>3}  {mark:>5}  {ch['words']:>6} words  {ch.get('label') or plain(ch['title'])[:60]}")
    nxt = next((f for f in st["fragments"] if not fragment_done(root, f, cache)), None)
    print(f"Next fragment: {nxt['id']}" if nxt else "All fragments translated.")
    if lc := st.get("last_check"):
        print(f"Last check: chapters {', '.join(map(str, lc['chapters']))} on {lc['date']}.")


def cmd_mark(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    st["steps"][a.step] = a.state
    save_state(root, st)
    print(f"{a.step}: {a.state}")


# ─── Glossary ───────────────────────────────────────────────────────────


def load_glossary(root: Path) -> list[dict]:
    """Rows of the glossary.md table, without rejected ones."""
    path = root / "glossary.md"
    if not path.exists():
        return []
    rows, header = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            header = None if not line.strip() else header
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(header, cells))
        if row.get("status", "").lower().startswith(("rejected", "removed")):
            continue
        if row.get("source"):
            rows.append(row)
    return rows


def term_forms(row: dict) -> list[str]:
    forms = [row["source"]] + [f.strip() for f in row.get("forms seen", "").split(",")]
    return [f for f in dict.fromkeys(forms) if f and f not in ("—", "-")]


LETTER = r"[^\W_]"  # a letter or digit in any script


def word_pattern(word: str, inflect: bool) -> str:
    """A word of 5+ letters may change its last letter and take up to 4 more
    (Polish 'chorobę' for 'choroba'); a word of 4 letters may take up to 3 more."""
    if not inflect or not word[-1:].isalpha() or len(word) < 4:
        return re.escape(word)
    if len(word) >= 5:
        return re.escape(word[:-1]) + f"{LETTER}{{0,4}}"
    return re.escape(word) + f"{LETTER}{{0,3}}"


def term_regex(row: dict) -> re.Pattern[str]:
    """Match any listed form, each word with case endings (see word_pattern).
    The optional Match column of the glossary turns this off: 'case' matches
    with the case as written, 'exact' matches the forms without endings.
    The app does this more carefully in term_matching.py."""
    mode = row.get("match", "").lower()
    inflect = "exact" not in mode
    alts = []
    for f in sorted(term_forms(row), key=len, reverse=True):
        alts.append(r"\s+".join(word_pattern(w, inflect) for w in f.split()))
    flags = 0 if "case" in mode else re.IGNORECASE
    return re.compile(rf"(?<!{LETTER})(?:{'|'.join(alts)})(?!{LETTER})", flags)


SENTENCE_START = re.compile(r"(?:^|[.!?…:]\s+|[–—-]\s+)[*_(]*$")


def row_matches(row: dict, text: str) -> bool:
    """Whether a glossary row's term is in the text. A row with Match 'case' skips
    a capitalised form that opens a sentence or a line ("Dłonie miała zimne"), since
    the capital there says nothing about the term."""
    rx = term_regex(row)
    if "case" not in row.get("match", "").lower():
        return bool(rx.search(text))
    for m in rx.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if not SENTENCE_START.search(text[line_start:m.start()]):
            return True
    return False


def terms_in(text: str, glossary: list[dict]) -> list[dict]:
    return [r for r in glossary if row_matches(r, text)]


def target_of(row: dict) -> str:
    return row.get("english") or row.get("target") or ""


def english_forms(row: dict) -> list[str]:
    """The English column may list several forms: 'weave/wove/woven'. The first is the main one."""
    return [f.strip() for f in target_of(row).split("/") if f.strip()]


def english_regex(row: dict) -> re.Pattern[str]:
    """What counts as the agreed English being used: the English form without a
    leading 'the', each word with English endings (Plainband/Plainbands,
    weave/weaving), or a listed form that is itself written in the translation
    (a short form the rules keep, such as 'Jen' for Jenna)."""
    case = "case" in row.get("match", "").lower()
    alts = []
    for form in english_forms(row):
        # With Match 'case', keep 'the' and its capital out of the comparison but the
        # term's own capitals in it ('the Hands' must not be 'hands').
        target = re.sub(r"^the\s+", "", form, flags=re.IGNORECASE)
        words = []
        for w in target.split():
            stem = re.sub(r"(?:ers|er|es|s|ing|ed|e|y)$", "", w, flags=re.IGNORECASE) if len(w) > 4 else w
            words.append(re.escape(stem) + r"[\w'’]{0,5}")
        alts.append(r"\s+".join(words))
    # A short form the rules keep as it is ('Jen' for Jenna): a listed form that the
    # English form starts with.
    main = re.sub(r"^the\s+", "", (english_forms(row) or [""])[0], flags=re.IGNORECASE)
    alts += [re.escape(f) for f in term_forms(row)
             if f[:1].isupper() and main.lower().startswith(f.lower()) and f.lower() != main.lower()]
    if not alts:
        return re.compile(r"(?!)")
    return re.compile(rf"(?<!{LETTER})(?:{'|'.join(alts)})", 0 if case else re.IGNORECASE)


def cmd_terms(root: Path, a: argparse.Namespace) -> None:
    glossary = load_glossary(root)
    text = "\n".join(t for _, t in read_paragraphs(chapter_file(root, a.chapter)))
    for r in terms_in(text, glossary):
        print(f"{r['source']} → {target_of(r)}  ({r.get('type', '')})")


# ─── dialogue ───────────────────────────────────────────────────────────


LINE_ENTRY = re.compile(r"^- \[(\d+):(\w+)\]\s*(.*?)\s*(?:→\s*(.*?))?\s*\|")


QUOTED = re.compile(r"[„“\"«»]([^„“”\"«»\n]+)[”\"“»«]")


def looks_like_dialogue(text: str) -> bool:
    """A paragraph that opens with a dialogue dash, or quotes more than three words
    (a quoted single word or title, such as „klasyk", is not speech)."""
    return bool(DIALOGUE_START.match(text)) or any(len(q.split()) > 3 for q in QUOTED.findall(text))


def cmd_dialogue(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    if a.group:
        return group_lines(root)
    chapters = parse_chapters(a.chapters, st)
    out = []
    for n in chapters:
        lines = [(pid, t) for pid, t in read_paragraphs(chapter_file(root, n))
                 if pid != "title" and looks_like_dialogue(t)]
        if not lines:
            continue
        out.append(f"## Chapter {n}\n")
        for pid, t in lines:
            if a.skeleton:
                out.append(f"- [{n:02d}:{pid}] ? → ? | {plain(t)[:90]}")
            else:
                out.append(f"[{n:02d}:{pid}] {t}\n")
        if a.skeleton:
            out.append("")
    if not a.skeleton:
        print("\n".join(out))
        return
    path = root / "work" / "lines-draft.md"
    if path.exists():
        sys.exit(f"{path.relative_to(root)} already exists; delete it first to start again.")
    head = ["# Dialogue lines (draft)", "",
            "<!-- Replace '? → ?' with 'Speaker → Listener' (glossary English names), 'thought',",
            "     or 'not dialogue'. An unnamed speaker gets a short role ('Inn man 1', 'Older guard');",
            "     'Unknown' only when even the role is unclear. Then run 'dialogue --group'. -->", ""]
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(head + out), encoding="utf-8")
    print(f"Wrote {path.relative_to(root)} ({sum(1 for x in out if x.startswith('- ['))} candidate lines).")


def group_lines(root: Path) -> None:
    """work/lines-draft.md (chapter order) → work/lines.md (one section per speaker)."""
    draft = root / "work" / "lines-draft.md"
    if not draft.exists():
        sys.exit("No work/lines-draft.md. Run 'dialogue <chapters> --skeleton' first.")
    by: dict[str, list[str]] = {}
    open_lines = 0
    sources: dict[int, dict[str, str]] = {}
    for line in draft.read_text(encoding="utf-8").splitlines():
        m = LINE_ENTRY.match(line)
        if not m:
            continue
        ch, pid, who, to = m.groups()
        who = who.strip()
        if who in ("?", "") :
            open_lines += 1
            continue
        if who.lower() in ("not dialogue", "-", "—"):
            continue
        n = int(ch)
        if n not in sources:
            sources[n] = dict(read_paragraphs(chapter_file(root, n)))
        said = plain(sources[n].get(pid, ""))
        said = said if len(said) <= 200 else said[:200].rsplit(" ", 1)[0] + " …"
        entry = f"[{ch}:{pid}]" + (f" to {to}" if to and to != "?" else "") + (f": {said}" if said else "")
        by.setdefault(who, []).append(entry)
    order = sorted(by, key=lambda k: (k in ("Unknown", "thought"), -len(by[k])))
    parts = ["# Attributed lines", "", "<!-- Built by 'dialogue --group' from work/lines-draft.md. -->", ""]
    for who in order:
        parts += [f"## {who} ({len(by[who])})", "", *by[who], ""]
    (root / "work" / "lines.md").write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote work/lines.md: {len(by)} speakers." + (f" {open_lines} lines still '?'." if open_lines else ""))


# ─── fragment / save ────────────────────────────────────────────────────


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def cmd_fragment(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    f = find_fragment(st, a.id)
    n = f["chapter"]
    src = read_paragraphs(chapter_file(root, n))
    tgt = dict(read_paragraphs(chapter_file(root, n, "translation")))
    idx = {pid: i for i, (pid, _) in enumerate(src)}
    first, last = idx[f["ids"][0]], idx[f["ids"][-1]]
    body = src[first:last + 1]
    before = src[max(0, first - NEIGHBOUR_PARAGRAPHS):first]
    after = src[last + 1:last + 1 + NEIGHBOUR_PARAGRAPHS]
    chapter = next(c for c in st["chapters"] if c["n"] == n)

    glossary = load_glossary(root)
    text = "\n".join(t for _, t in body)
    found = terms_in(text, glossary)
    earlier = "\n".join(t for _, t in src[:first])  # this chapter before the fragment
    seen_before = {id(r) for r in terms_in(earlier, glossary)} if earlier else set()
    voices: list[Path] = []
    for r in found:
        if "character" in r.get("type", "").lower():
            path = root / "voices" / f"{slug(target_of(r))}.md"
            if path.exists():
                voices.append(path)
    # Briefs for minor speakers: a line "Matches: word, word" lists source words that call them up.
    for path in sorted((root / "voices").glob("*.md")):
        if path.name.startswith("_") or path in voices:
            continue
        m = re.search(r"^Matches:\s*(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
        if m and any(w.strip() and w.strip().lower() in text.lower() for w in m.group(1).split(",")):
            voices.append(path)
    cast = root / "voices" / "_cast.md"
    if cast.exists():
        voices.append(cast)

    label = chapter.get("label") or short_label(chapter["title"])
    out = [f"# Fragment {f['id']} ({f['words']} words), chapter {n}" + (f" ({label})" if label else ""), ""]
    out.append("## Glossary terms in this fragment\n")
    out.append("(Notes are shown where a term first appears in the chapter; see glossary.md for the rest.)\n")
    for r in found:
        note = r.get("notes") if id(r) not in seen_before and r.get("notes") not in (None, "", "—") else None
        out.append(f"- {r['source']} → {target_of(r)}" + (f" — {note}" if note else ""))
    if not found:
        out.append("(none found by the script; check the full glossary for names it missed)")
    out.append("\n## Voice briefs to read\n")
    out += [f"- {p.relative_to(root)}" for p in voices] or ["(none matched; check who speaks in the fragment)"]
    if before:
        out.append("\n## End of the previous text (source; context only, do not translate)\n")
        out.append(render(before))
        prev_t = [(pid, tgt[pid]) for pid, _ in before if tgt.get(pid)]
        if prev_t:
            out.append("\n## End of the previous text (current translation; match its terms and tone)\n")
            out.append(render(prev_t))
    if after:
        out.append("\n## Start of the next text (source; context only, do not translate)\n")
        out.append(render(after))
    out.append("\n## Source paragraphs to translate\n")
    out.append(render(body))
    out.append(f"\n<!-- Write the translation as the same [id] blocks to work/{f['id']}.md, "
               f"then run: save {f['id']} work/{f['id']}.md. Notes go under '## {f['id']}' "
               f"in notes/chapter-{n:02d}.md. -->")
    print("\n".join(out))


def cmd_save(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    f = find_fragment(st, a.id)
    new = read_paragraphs(Path(a.file) if Path(a.file).is_absolute() else root / a.file)
    got = [pid for pid, _ in new]
    if got != f["ids"]:
        missing = [p for p in f["ids"] if p not in got]
        extra = [p for p in got if p not in f["ids"]]
        sys.exit(f"Not saved: the ids must match the fragment, in order.\n"
                 f"  missing: {missing or '—'}\n  extra: {extra or '—'}\n"
                 f"  expected order: {' '.join(f['ids'])}")
    empty = [pid for pid, t in new if not t]
    if empty:
        sys.exit(f"Not saved: empty paragraphs {empty}.")
    n = f["chapter"]
    order = [pid for pid, _ in read_paragraphs(chapter_file(root, n))]
    merged = dict(read_paragraphs(chapter_file(root, n, "translation")))
    merged.update(dict(new))
    paras = [(pid, merged[pid]) for pid in order if pid in merged]
    write_paragraphs(chapter_file(root, n, "translation"),
                     f"<!-- Chapter {n} translation. Same [id]s as source/chapter-{n:02d}.md. -->", paras)
    problems = hard_checks(st, new, read_paragraphs(chapter_file(root, n)))
    print(f"Saved {f['id']} ({len(new)} paragraphs) to translation/chapter-{n:02d}.md.")
    for p in problems:
        print(f"  check: {p}")
    m = style_metrics("\n".join(t for _, t in new))
    print(f"  style: She/He openers {m['she_he_pct']}% (target ≤ {SHE_HE_MAX_PCT}%); ellipses per 1k in "
          f"narration {m['ellipses_narration_per_1k']} (target ≤ {ELLIPSES_MAX_PER_1K}), in dialogue "
          f"{m['ellipses_dialogue_per_1k']}; em dashes per 1k {m['dashes_per_1k']} (target ≤ {DASHES_MAX_PER_1K})"
          + (f"; check these phrases: {', '.join(m['stock'])}" if m["stock"] else ""))


# ─── checks ─────────────────────────────────────────────────────────────


def hard_checks(st: dict, tgt: list[tuple[str, str]], src: list[tuple[str, str]]) -> list[str]:
    src_map = dict(src)
    letters = st.get("source_letters") or ""
    leftover = re.compile(f"[{letters}]") if letters else None
    problems = []
    for pid, text in tgt:
        if leftover and (m := leftover.findall(text)):
            problems.append(f"[{pid}] source-language letters left: {''.join(sorted(set(m)))}")
        if DIALOGUE_START.match(text):
            problems.append(f"[{pid}] starts with a dialogue dash; use quotes")
        if re.search(r"\\[!.\-*_]", text):
            problems.append(f"[{pid}] markdown escape backslash")
        if re.search(r"(?<!\.)\.\.\.(?!\.)", text):
            problems.append(f"[{pid}] three full stops; write the ellipsis as …")
        s_ph = PLACEHOLDER.findall(src_map.get(pid, ""))
        if len(PLACEHOLDER.findall(text)) < len(s_ph):
            problems.append(f"[{pid}] author placeholder missing ({', '.join(s_ph)})")
    return problems


def glossary_drift(glossary: list[dict], src: dict[str, str], tgt: list[tuple[str, str]]) -> dict[str, list[str]]:
    """{term line: [paragraph ids]} for source terms whose agreed English is missing."""
    out: dict[str, list[str]] = {}
    for pid, text in tgt:
        for r in terms_in(src.get(pid, ""), glossary):
            if target_of(r) and not english_regex(r).search(text):
                out.setdefault(f"'{r['source']}' → '{target_of(r)}'", []).append(pid)
    return out


SHE_HE = re.compile(r"^[*_\s]*(She|He)\b")


def she_he_runs(tgt: list[tuple[str, str]], top: int = 5) -> list[str]:
    """Paragraphs with the most She/He sentence openers (two or more), for revision."""
    counts = []
    for pid, text in tgt:
        narration = DIALOGUE_SPANS.sub(" ", text)
        k = sum(bool(SHE_HE.match(s)) for s in SENTENCE_END.split(narration) if s.strip())
        if k >= 2:
            counts.append((k, pid))
    return [f"{pid} ({k})" for k, pid in sorted(counts, key=lambda x: (-x[0], x[1]))[:top]]


DIALOGUE_SPANS = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d')


def ellipses(text: str) -> int:
    return text.count("…") + len(re.findall(r"(?<!\.)\.\.\.(?!\.)", text))


def style_metrics(text: str) -> dict:
    narration = DIALOGUE_SPANS.sub(" ", text)
    dialogue = " ".join(DIALOGUE_SPANS.findall(text))
    sentences = [s for s in SENTENCE_END.split(narration) if s.strip()]
    she_he = sum(bool(SHE_HE.match(s)) for s in sentences)
    words = max(len(text.split()), 1)
    stock = {p: len(re.findall(p, text, re.IGNORECASE)) for p in STOCK_PHRASES}
    per_1k = lambda k: round(1000 * k / words, 1)  # noqa: E731
    return {
        "words": words,
        "she_he_pct": round(100 * she_he / max(len(sentences), 1), 1),
        "ellipses_per_1k": per_1k(ellipses(text)),
        "ellipses_narration_per_1k": per_1k(ellipses(narration)),
        "ellipses_dialogue_per_1k": per_1k(ellipses(dialogue)),
        "dashes_per_1k": per_1k(text.count("—")),
        "stock": {STOCK_LABEL.get(k, re.sub(r"\\b|\(\?!.*\)", "", k)): v for k, v in stock.items() if v},
    }


def parse_chapters(spec: str | None, st: dict) -> list[int]:
    """'3', '1-4' or '1,3,5-6' → chapter numbers; None → every chapter."""
    every = [c["n"] for c in st["chapters"]]
    if not spec:
        return every
    out: list[int] = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", part)
        if not m:
            sys.exit(f"Chapters must look like 3, 1-4 or 1,3,5-6 (got '{spec}').")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        out += [n for n in every if lo <= n <= hi and n not in out]
    if not out:
        sys.exit(f"No chapters match '{spec}'.")
    return out


def merge_notes(root: Path, st: dict) -> int:
    """Join notes/chapter-NN.md into notes.md, in chapter order. Returns the count of notes."""
    files = sorted((root / "notes").glob("chapter-*.md"))
    if not files:
        return 0
    old = root / "notes.md"
    if old.exists() and "Built by 'check'" not in old.read_text(encoding="utf-8"):
        print("notes.md was written by hand, so it was not replaced. Move its notes into "
              "notes/chapter-NN.md, then delete it, and run check again.")
        return 0
    parts = [f"# Translator notes: {st['title']}",
             "", "<!-- Built by 'check' from notes/chapter-NN.md. Edit those files, not this one. -->", ""]
    count = 0
    for f in files:
        text = f.read_text(encoding="utf-8").strip()
        if text:
            parts += [f"# Chapter {int(f.stem.split('-')[1])}", "", text, ""]
            count += sum(1 for ln in text.splitlines() if ln.startswith("- ["))
    (root / "notes.md").write_text("\n".join(parts), encoding="utf-8")
    return count


def cmd_check(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    glossary = load_glossary(root)
    chapters = parse_chapters(a.chapter, st)
    lines = [f"# Check report: {st['title']}", ""]
    total, untranslated = 0, []
    flag = lambda v, mx, unit="": f"{v}{unit} (target ≤ {mx}{unit}){' ⚠' if v > mx else ''}"  # noqa: E731
    for n in chapters:
        src = read_paragraphs(chapter_file(root, n))
        tgt = read_paragraphs(chapter_file(root, n, "translation"))
        if not tgt:
            untranslated.append(n)
            continue
        have = {pid for pid, _ in tgt}
        missing = [pid for pid, _ in src if pid not in have]
        problems = hard_checks(st, tgt, src)
        drift = glossary_drift(glossary, dict(src), tgt)
        m = style_metrics("\n".join(t for _, t in tgt))
        src_text = "\n".join(t for _, t in src)
        src_ell = round(1000 * ellipses(src_text) / max(len(src_text.split()), 1), 1)
        total += len(problems) + len(drift)
        runs = she_he_runs(tgt)
        lines.append(f"## Chapter {n}\n")
        if missing:
            lines.append(f"Untranslated paragraphs: {' '.join(missing)}\n")
        lines.append("Problems:\n" + ("\n".join(f"- {p}" for p in problems) or "- none") + "\n")
        lines.append("Glossary (agreed English not found; check each, a pronoun or short form may be fine):\n"
                     + ("\n".join(f"- {term} in {len(ids)} paragraph{'s' if len(ids) > 1 else ''}: {' '.join(ids)}"
                                  for term, ids in sorted(drift.items(), key=lambda kv: -len(kv[1])))
                        or "- none") + "\n")
        lines.append(
            f"Style: {m['words']} words; She/He openers {flag(m['she_he_pct'], SHE_HE_MAX_PCT, '%')}; "
            f"ellipses per 1k in narration {flag(m['ellipses_narration_per_1k'], ELLIPSES_MAX_PER_1K)}, "
            f"in dialogue {m['ellipses_dialogue_per_1k']} (whole source {src_ell}); "
            f"em dashes per 1k {flag(m['dashes_per_1k'], DASHES_MAX_PER_1K)}"
            + (f"; check these phrases: {', '.join(f'{k} ×{v}' for k, v in m['stock'].items())}" if m["stock"] else "")
            + "\n")
        if runs and m["she_he_pct"] > SHE_HE_MAX_PCT - 3:
            lines.append(f"Most She/He openers: {', '.join(runs)}\n")
    if untranslated:
        lines.append(f"Not translated yet: {len(untranslated)} chapter{'s' if len(untranslated) > 1 else ''} "
                     f"({', '.join(map(str, untranslated))}).\n")
    (root / "check-report.md").write_text("\n".join(lines), encoding="utf-8")
    checked = [n for n in chapters if n not in untranslated]
    if checked:
        st["last_check"] = {"chapters": checked, "date": date.today().isoformat()}
        save_state(root, st)
    notes = merge_notes(root, st)
    print(f"Wrote check-report.md ({total} problems and glossary terms to look at)."
          + (f" Merged {notes} notes into notes.md." if notes else ""))


# ─── letters (hidden messages) ──────────────────────────────────────────


def cmd_letters(root: Path, a: argparse.Namespace) -> None:
    kind = "translation" if a.translation else "source"
    paras = read_paragraphs(chapter_file(root, a.chapter, kind))
    ids = [pid for pid, _ in paras]
    if a.first not in ids or a.last not in ids:
        sys.exit("First or last id not found in that chapter.")
    block = paras[ids.index(a.first):ids.index(a.last) + 1]
    if a.start_at:
        pid, t = block[0]
        k = t.find(a.start_at)
        if k < 0:
            sys.exit(f"'{a.start_at}' not found in [{pid}].")
        block[0] = (pid, t[k:])
    if a.end_at:
        pid, t = block[-1]
        k = t.find(a.end_at)
        if k < 0:
            sys.exit(f"'{a.end_at}' not found in [{pid}].")
        block[-1] = (pid, t[:k + len(a.end_at)])
    text = "\n".join(t for _, t in block)
    first = lambda items: "".join(w[0] for w in items if w)  # noqa: E731
    letter = lambda s: next((c for c in s if c.isalpha()), "")  # noqa: E731
    sentences = [s for s in SENTENCE_END.split(text) if s.strip()]
    lines_ = [ln for ln in text.splitlines() if ln.strip()]
    words = re.findall(r"[^\W\d_]+", text)
    marked = re.findall(r"\*\*?([^*]+)\*\*?", text)
    print(f"sentences:  {''.join(letter(s) for s in sentences)}")
    print(f"lines:      {''.join(letter(s) for s in lines_)}")
    print(f"paragraphs: {''.join(letter(t) for _, t in block)}")
    print(f"words:      {first(words)}")
    if marked:
        print(f"marked:     {''.join(letter(s) for s in marked)}")


# ─── export ─────────────────────────────────────────────────────────────


def to_md(text: str) -> str:
    lines = text.strip().split("\n")
    if lines[0].strip() == "***":  # a scene break, maybe with a POV name under it
        rest = "  \n".join(lines[1:]).strip()
        return "* * *" + (f"\n\n{rest}" if rest else "")
    return "  \n".join(lines)


def chapter_heading(title: str, n: int) -> tuple[str, list[str]]:
    """('Chapter 3', [lines under it]) from a translated [title] paragraph: the
    'Chapter N' line becomes the heading and the POV name and epigraph go under it."""
    lines = [ln for ln in title.strip().split("\n") if ln.strip()]
    en = re.compile(rf"^\s*({'|'.join(EN_CHAPTER_MARKERS)})", re.IGNORECASE)
    for i, ln in enumerate(lines):
        if en.match(plain(ln)):
            return plain(ln).rstrip("."), lines[:i] + lines[i + 1:]
    return (plain(lines[0]) if lines else f"Chapter {n}"), lines[1:]


def cmd_export(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    if a.title:
        st["target_title"] = a.title
        save_state(root, st)
    book_title = st.get("target_title") or st["title"]
    chapters = parse_chapters(a.chapters, st)
    out = [f"% {book_title}", ""]
    gaps = 0
    for ch in [c for c in st["chapters"] if c["n"] in chapters]:
        n = ch["n"]
        src = read_paragraphs(chapter_file(root, n))
        tgt = dict(read_paragraphs(chapter_file(root, n, "translation")))
        has_title = any(p == "title" for p, _ in src)
        if tgt.get("title"):
            heading, under = chapter_heading(tgt["title"], n)
        elif has_title:
            gaps += 1
            heading, under = f"Chapter {n}", [f"**[Untranslated: chapter {n}, heading]**"]
        else:
            heading, under = f"Chapter {n}", []
        out.append(f"# {heading}\n")
        if under:
            out.append(to_md("\n".join(under)) + "\n")
        for f in [f for f in st["fragments"] if f["chapter"] == n]:
            for pid in f["ids"]:
                if pid == "title":
                    continue
                if tgt.get(pid):
                    out.append(to_md(tgt[pid]) + "\n")
                else:
                    gaps += 1
                    out.append(f"**[Untranslated: chapter {n}, paragraph {pid}]**\n")
    if gaps and not a.draft:
        sys.exit(f"{gaps} paragraphs are not translated. Use --draft to export with gaps marked.")
    exp = root / "export"
    exp.mkdir(exist_ok=True)
    name = slug(book_title) or "book"
    if a.chapters:
        name += "_ch" + re.sub(r"[^0-9,-]", "", a.chapters).replace(",", "+")
    if a.draft:
        name += "_DRAFT"
    md = exp / f"{name}.md"
    md.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {md.relative_to(root)}")
    if shutil.which("pandoc"):
        for ext in ("docx", "epub"):
            target = exp / f"{name}.{ext}"
            subprocess.run(["pandoc", str(md), "-o", str(target)], check=True)
            print(f"Wrote {target.relative_to(root)}")
    else:
        print("pandoc not found: only Markdown was written. Install pandoc for .docx and .epub.")


# ─── CLI ────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default=".", help="book folder (default: current folder)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("manuscript")
    s.add_argument("--source-language", required=True, help="code (pl, de, kn) or English name")
    s.add_argument("--target-language", default="English")
    s.add_argument("--title")
    s.add_argument("--target-title", help="title of the translation, used by export")
    s.add_argument("--letters", help="source letters that must not stay in the translation")
    s.add_argument("--force", action="store_true")
    sub.add_parser("status")
    s = sub.add_parser("mark"); s.add_argument("step"); s.add_argument("state")
    s = sub.add_parser("dialogue"); s.add_argument("chapters", nargs="?", help="3, 1-4 or 1,3,5-6")
    s.add_argument("--skeleton", action="store_true", help="write work/lines-draft.md to fill in")
    s.add_argument("--group", action="store_true", help="turn work/lines-draft.md into work/lines.md")
    s = sub.add_parser("terms"); s.add_argument("chapter", type=int)
    s = sub.add_parser("fragment"); s.add_argument("id")
    s = sub.add_parser("save"); s.add_argument("id"); s.add_argument("file")
    s = sub.add_parser("letters"); s.add_argument("chapter", type=int); s.add_argument("first")
    s.add_argument("last"); s.add_argument("--translation", action="store_true")
    s.add_argument("--from", dest="start_at", help="start inside the first paragraph at these words")
    s.add_argument("--to", dest="end_at", help="end inside the last paragraph after these words")
    s = sub.add_parser("check"); s.add_argument("chapter", nargs="?", help="3, 1-4 or 1,3,5-6")
    s = sub.add_parser("export"); s.add_argument("--draft", action="store_true")
    s.add_argument("--chapters", help="export only these chapters: 3, 1-4 or 1,3,5-6")
    s.add_argument("--title", help="title of the translation (saved for later exports)")
    a = p.parse_args()
    root = Path(a.dir).expanduser().resolve()
    {
        "prepare": cmd_prepare, "status": cmd_status, "mark": cmd_mark, "dialogue": cmd_dialogue,
        "terms": cmd_terms, "fragment": cmd_fragment, "save": cmd_save, "letters": cmd_letters,
        "check": cmd_check, "export": cmd_export,
    }[a.cmd](root, a)


if __name__ == "__main__":
    main()
