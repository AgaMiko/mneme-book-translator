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

    prepare <manuscript> --source-language pl [--title T] [--target-language English]
        Split a .docx, .md or .txt manuscript into source/chapter-NN.md
        and plan fragments of about 1,200 words. Writes mneme.json.
    status                      Steps, fragments done, next fragment.
    mark <step> <state>         Record a step state, e.g. "mark glossary reviewed".
    dialogue [chapter]          Paragraphs that look like dialogue, with ids.
    terms <chapter>             Glossary terms found in a chapter (source side).
    fragment <id>               One fragment with its neighbours, the glossary
                                terms and voice files that apply to it.
    save <id> <file>            Check a translated fragment (same ids, same
                                order) and merge it into translation/chapter-NN.md.
    letters <chapter> <first> <last> [--translation]
                                First letters of sentences, lines, paragraphs
                                and words of a passage, for hidden messages.
    check [chapter]             Write check-report.md: missing paragraphs,
                                leftover source letters, dialogue dashes,
                                placeholders, glossary use, style metrics.
    export [--draft]            Write export/<title>.md (and .docx / .epub
                                when pandoc is installed).

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
from pathlib import Path

# ─── Numbers and language facts copied from the app ─────────────────────

TARGET_WORDS = 1200  # fragmenter.TARGET_WORDS
MIN_WORDS_BEFORE_SCENE_CUT = 600
MIN_TAIL_WORDS = 250
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
    r"let out a breath (?:she|he)", r"a wave of", r"for a heartbeat", r"\bsuddenly\b",
)
PLACEHOLDER = re.compile(r"x{4,}|\[x+\]")

SCENE_BREAK = re.compile(r"^\s*(?:#{1,3}\s*)?\*\s*\*\s*\*\s*")
STAR_SPLIT = re.compile(r"\s*(?<!\*)\*{3}(?!\*)\s*")
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
        m = re.match(r"^(#{1,2})\s+(.*)$", c)
        if m and "\n" not in c:
            out.append((m.group(2).strip(), "Title" if m.group(1) == "#" and not out else "Heading 1"))
        else:
            out.append((c, None))
    return out


def cmd_prepare(root: Path, a: argparse.Namespace) -> None:
    src = Path(a.manuscript).expanduser()
    if not src.exists():
        sys.exit(f"Manuscript not found: {src}")
    if (root / STATE_FILE).exists() and not a.force:
        sys.exit(f"{STATE_FILE} already exists. Use --force to split the manuscript again "
                 "(translation files are kept, but paragraph ids may change).")
    lang = a.source_language.lower()
    title = a.title
    if src.suffix.lower() == ".docx":
        doc_title, blocks = docx_blocks(src)
        title = title or doc_title
    else:
        blocks = text_blocks(src)
    pattern = chapter_pattern(lang)

    chapters: list[dict] = []
    current: dict = {"title": None, "paras": []}
    for text, style in blocks:
        if not text:
            continue
        s = (style or "").lower()
        if s == "title" and not chapters and not current["paras"] and current["title"] is None:
            title = title or text
            continue
        if s.startswith("heading 1") or pattern.match(text):
            if current["paras"] or current["title"] is not None:
                chapters.append(current)
            current = {"title": text, "paras": []}
            continue
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

    state_chapters, fragments = [], []
    for n, ch in enumerate(chapters, 1):
        paras: list[tuple[str, str]] = []
        if ch["title"]:
            paras.append(("title", ch["title"]))
        paras += [(f"p{i:03d}", t) for i, t in enumerate(ch["paras"], 1)]
        write_paragraphs(chapter_file(root, n), f"<!-- Chapter {n} source. One [id] per paragraph. -->", paras)
        words = sum(len(t.split()) for _, t in paras)
        state_chapters.append({"n": n, "title": ch["title"] or f"Chapter {n}", "words": words})
        fragments += plan_fragments(n, paras)

    state = {
        "title": title or src.stem,
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
    for d in ("translation", "voices", "work"):
        (root / d).mkdir(exist_ok=True)
    total = sum(c["words"] for c in state_chapters)
    print(f"Split '{state['title']}': {len(state_chapters)} chapters, {total} words, "
          f"{len(fragments)} fragments. State in {root / STATE_FILE}.")
    if not state["source_letters"]:
        print(f"Note: no letter list for '{lang}'. Pass --letters to enable the leftover-letters check.")


def plan_fragments(n: int, paras: list[tuple[str, str]]) -> list[dict]:
    """Same rules as the app's fragmenter: ~1,200 words, cut early at a scene
    break after 600, a tail under 250 words joins the previous fragment."""
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
        print(f"  {ch['n']:>3}  {mark:>5}  {ch['words']:>6} words  {ch['title'][:60]}")
    nxt = next((f for f in st["fragments"] if not fragment_done(root, f, cache)), None)
    print(f"Next fragment: {nxt['id']}" if nxt else "All fragments translated.")


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


def term_regex(row: dict) -> re.Pattern[str]:
    """Match any listed form; forms of 4+ letters may take up to 3 more letters
    (case endings). The app does this more carefully in term_matching.py."""
    alts = []
    for f in sorted(term_forms(row), key=len, reverse=True):
        tail = f"{LETTER}{{0,3}}" if len(f) >= 4 and f[-1].isalpha() else ""
        alts.append(re.escape(f) + tail)
    return re.compile(rf"(?<!{LETTER})(?:{'|'.join(alts)})(?!{LETTER})", re.IGNORECASE)


def terms_in(text: str, glossary: list[dict]) -> list[dict]:
    return [r for r in glossary if term_regex(r).search(text)]


def target_of(row: dict) -> str:
    return row.get("english") or row.get("target") or ""


def cmd_terms(root: Path, a: argparse.Namespace) -> None:
    glossary = load_glossary(root)
    text = "\n".join(t for _, t in read_paragraphs(chapter_file(root, a.chapter)))
    for r in terms_in(text, glossary):
        print(f"{r['source']} → {target_of(r)}  ({r.get('type', '')})")


# ─── dialogue ───────────────────────────────────────────────────────────


def cmd_dialogue(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    chapters = [a.chapter] if a.chapter else [c["n"] for c in st["chapters"]]
    for n in chapters:
        lines = [(pid, t) for pid, t in read_paragraphs(chapter_file(root, n))
                 if DIALOGUE_START.match(t) or QUOTES.search(t)]
        if lines:
            print(f"## Chapter {n}\n")
            for pid, t in lines:
                print(f"[{n:02d}:{pid}] {t}\n")


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
    voices = []
    for r in found:
        if "character" in r.get("type", "").lower():
            path = root / "voices" / f"{slug(target_of(r))}.md"
            if path.exists():
                voices.append(path)

    out = [f"# Fragment {f['id']} ({f['words']} words), chapter {n}: {chapter['title']}", ""]
    out.append("## Glossary terms in this fragment\n")
    out += [f"- {r['source']} → {target_of(r)}" + (f" — {r['notes']}" if r.get("notes") not in (None, "", "—") else "")
            for r in found] or ["(none found by the script; check the full glossary for names it missed)"]
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
               f"then run: save {f['id']} work/{f['id']}.md -->")
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
        s_ph = PLACEHOLDER.findall(src_map.get(pid, ""))
        if len(PLACEHOLDER.findall(text)) < len(s_ph):
            problems.append(f"[{pid}] author placeholder missing ({', '.join(s_ph)})")
    return problems


def glossary_drift(glossary: list[dict], src: dict[str, str], tgt: list[tuple[str, str]]) -> list[str]:
    out = []
    for pid, text in tgt:
        for r in terms_in(src.get(pid, ""), glossary):
            target = target_of(r)
            if target and target.lower() not in text.lower():
                out.append(f"[{pid}] '{r['source']}' in the source, but '{target}' not in the translation")
    return out


def style_metrics(text: str) -> dict:
    narration = re.sub(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d', " ", text)
    sentences = [s for s in SENTENCE_END.split(narration) if s.strip()]
    she_he = sum(bool(re.match(r"^[*_\s]*(She|He)\b", s)) for s in sentences)
    words = max(len(text.split()), 1)
    stock = {p: len(re.findall(p, text, re.IGNORECASE)) for p in STOCK_PHRASES}
    return {
        "words": words,
        "she_he_pct": round(100 * she_he / max(len(sentences), 1), 1),
        "ellipses_per_1k": round(1000 * (text.count("…") + text.count("...")) / words, 1),
        "dashes_per_1k": round(1000 * text.count("—") / words, 1),
        "stock": {k.replace("\\b", ""): v for k, v in stock.items() if v},
    }


def cmd_check(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    glossary = load_glossary(root)
    chapters = [a.chapter] if a.chapter else [c["n"] for c in st["chapters"]]
    lines = [f"# Check report: {st['title']}", ""]
    total = 0
    for n in chapters:
        src = read_paragraphs(chapter_file(root, n))
        tgt = read_paragraphs(chapter_file(root, n, "translation"))
        if not tgt:
            lines.append(f"## Chapter {n}\n\nNot translated yet.\n")
            continue
        have = {pid for pid, _ in tgt}
        missing = [pid for pid, _ in src if pid not in have]
        problems = hard_checks(st, tgt, src)
        drift = glossary_drift(glossary, dict(src), tgt)
        m = style_metrics("\n".join(t for _, t in tgt))
        total += len(problems) + len(drift)
        lines.append(f"## Chapter {n}\n")
        if missing:
            lines.append(f"Untranslated paragraphs: {' '.join(missing)}\n")
        lines.append("Problems:\n" + ("\n".join(f"- {p}" for p in problems) or "- none") + "\n")
        lines.append("Glossary (agreed English not found; check each, a pronoun or short form may be fine):\n"
                     + ("\n".join(f"- {d}" for d in drift) or "- none") + "\n")
        flag = lambda v, mx: f"{v} (target ≤ {mx}){' ⚠' if v > mx else ''}"  # noqa: E731
        lines.append(
            f"Style: {m['words']} words; She/He openers {flag(m['she_he_pct'], SHE_HE_MAX_PCT)}%; "
            f"ellipses per 1k {flag(m['ellipses_per_1k'], ELLIPSES_MAX_PER_1K)}; "
            f"em dashes per 1k {flag(m['dashes_per_1k'], DASHES_MAX_PER_1K)}"
            + (f"; stock phrases: {', '.join(f'{k} ×{v}' for k, v in m['stock'].items())}" if m["stock"] else "")
            + "\n")
    (root / "check-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote check-report.md ({total} problems and glossary warnings).")


# ─── letters (hidden messages) ──────────────────────────────────────────


def cmd_letters(root: Path, a: argparse.Namespace) -> None:
    kind = "translation" if a.translation else "source"
    paras = read_paragraphs(chapter_file(root, a.chapter, kind))
    ids = [pid for pid, _ in paras]
    if a.first not in ids or a.last not in ids:
        sys.exit("First or last id not found in that chapter.")
    block = paras[ids.index(a.first):ids.index(a.last) + 1]
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
    if text.strip() == "***":
        return "\\* \\* \\*"
    return text.replace("\n", "  \n")


def cmd_export(root: Path, a: argparse.Namespace) -> None:
    st = load_state(root)
    out = [f"% {st['title']}", ""]
    gaps = 0
    for ch in st["chapters"]:
        n = ch["n"]
        src = read_paragraphs(chapter_file(root, n))
        tgt = dict(read_paragraphs(chapter_file(root, n, "translation")))
        title = tgt.get("title") or ("Chapter " + str(n) if not any(p == "title" for p, _ in src) else None)
        heading = (title or ch["title"]).split("\n")
        out.append(f"# {heading[0]}\n")
        if len(heading) > 1:
            out.append(to_md("\n".join(heading[1:])) + "\n")
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
    name = slug(st["title"]) or "book"
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
    s.add_argument("--letters", help="source letters that must not stay in the translation")
    s.add_argument("--force", action="store_true")
    sub.add_parser("status")
    s = sub.add_parser("mark"); s.add_argument("step"); s.add_argument("state")
    s = sub.add_parser("dialogue"); s.add_argument("chapter", nargs="?", type=int)
    s = sub.add_parser("terms"); s.add_argument("chapter", type=int)
    s = sub.add_parser("fragment"); s.add_argument("id")
    s = sub.add_parser("save"); s.add_argument("id"); s.add_argument("file")
    s = sub.add_parser("letters"); s.add_argument("chapter", type=int); s.add_argument("first")
    s.add_argument("last"); s.add_argument("--translation", action="store_true")
    s = sub.add_parser("check"); s.add_argument("chapter", nargs="?", type=int)
    s = sub.add_parser("export"); s.add_argument("--draft", action="store_true")
    a = p.parse_args()
    root = Path(a.dir).expanduser().resolve()
    {
        "prepare": cmd_prepare, "status": cmd_status, "mark": cmd_mark, "dialogue": cmd_dialogue,
        "terms": cmd_terms, "fragment": cmd_fragment, "save": cmd_save, "letters": cmd_letters,
        "check": cmd_check, "export": cmd_export,
    }[a.cmd](root, a)


if __name__ == "__main__":
    main()
