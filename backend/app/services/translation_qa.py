"""Deterministic checks on translated text.

Two kinds:

- **Style metrics** (port of ``translations/zaplataczka/style_metrics.py``):
  share of narration sentences starting with She/He, ellipses and em dashes
  per 1,000 words, stock-phrase hits. Targets come from the polish brief.
  These are measured, not enforced: the polish prompt receives them, and the
  UI shows them per chapter.
- **Rhythm checks**: content words repeated within a few lines, and runs
  of sentences of about the same length. Direct translation tends to
  produce both (Polish varies words by inflection, and sentence-for-sentence
  translation evens out length). These are hints for the line edit and
  polish, listed with the exact spots; deliberate repetition in the source
  is allowed.
- **Hard checks** that point at a translation error: leftover source-language
  letters, Polish dialogue dashes at the start of a paragraph, markdown escape
  backslashes, author placeholders that went missing.

Pure functions; no database access.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.constants.languages import source_letters

# Polish-brief targets.
SHE_HE_MAX_PCT = 15.0
ELLIPSES_MAX_PER_1K = 3.0
DASHES_MAX_PER_1K = 6.0

STOCK_PHRASES: tuple[str, ...] = (
    r"the weight of",
    r"\ba beat\b",
    r"ghost of a smile",
    r"a flicker of",
    r"couldn't help but",
    r"something shifted",
    r"didn't know (?:she|he) was holding",
    r"let out a breath (?:she|he)",
    r"a wave of",
    r"for a heartbeat",
    r"\bsuddenly\b",
)

PLACEHOLDER_PATTERNS: tuple[str, ...] = (r"x{4,}", r"\[x+\]")

_QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d')
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\u2026])\s+")
_SHE_HE_OPENER = re.compile(r"^[*_\s]*(She|He)\b")

# Rhythm checks.
REPEAT_WINDOW_CONTENT_WORDS = 20  # about 40-60 running words
EVEN_RUN_MIN_SENTENCES = 4
EVEN_RUN_TOLERANCE = 0.25
EVEN_RUN_MIN_WORDS = 6

_STOPWORDS = frozenset(
    """a about above after again against all almost also although always am an and another any
    anyone anything are around as at away back be because been before behind being below beside
    between both but by can could did didn't do does doesn't doing don't done down during each
    either enough even ever every few for from further get got had hadn't has have haven't
    having he he'd he's her here hers herself him himself his how i i'd i'm if in into is isn't
    it it's its itself just know last least less like little made make many may me might more
    most much must my myself never no nor not nothing now of off often on once one only onto or
    other others our ours ourselves out over own perhaps quite rather said same say says see
    seemed she she'd she's should since so some something still such than that that's the their
    theirs them themselves then there there's these they they'd they're this those though
    through thus to too toward towards under until up upon us very was wasn't way we we'd we're
    were weren't what when where whether which while who whom whose why will with within
    without would wouldn't yet you you'd you're your yours yourself""".split()  # noqa: SIM905 - easier to read and edit as text
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019]*")
_ANY_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\u2026])[\"\u201d\u2019]?\s+")


@dataclass(slots=True)
class StyleMetrics:
    words: int = 0
    narration_sentences: int = 0
    she_he_openers: int = 0
    ellipses: int = 0
    em_dashes: int = 0
    stock: dict[str, int] = field(default_factory=dict)
    repetitions: int = 0
    even_runs: int = 0

    @property
    def repetitions_per_1k(self) -> float:
        return round(1000 * self.repetitions / max(1, self.words), 1)

    @property
    def she_he_pct(self) -> float:
        return round(100 * self.she_he_openers / max(1, self.narration_sentences), 1)

    @property
    def ellipses_per_1k(self) -> float:
        return round(1000 * self.ellipses / max(1, self.words), 1)

    @property
    def dashes_per_1k(self) -> float:
        return round(1000 * self.em_dashes / max(1, self.words), 1)

    @property
    def stock_total(self) -> int:
        return sum(self.stock.values())

    def merge(self, other: StyleMetrics) -> StyleMetrics:
        stock = dict(self.stock)
        for k, v in other.stock.items():
            stock[k] = stock.get(k, 0) + v
        return StyleMetrics(
            words=self.words + other.words,
            narration_sentences=self.narration_sentences + other.narration_sentences,
            she_he_openers=self.she_he_openers + other.she_he_openers,
            ellipses=self.ellipses + other.ellipses,
            em_dashes=self.em_dashes + other.em_dashes,
            stock=stock,
            repetitions=self.repetitions + other.repetitions,
            even_runs=self.even_runs + other.even_runs,
        )

    def over_target(self) -> list[str]:
        """Human-readable list of metrics that miss the polish targets."""
        out: list[str] = []
        if self.she_he_pct > SHE_HE_MAX_PCT:
            out.append(
                f"narration sentences starting with She/He: {self.she_he_pct}% "
                f"(target ≤ {SHE_HE_MAX_PCT:g}%)"
            )
        if self.ellipses_per_1k > ELLIPSES_MAX_PER_1K:
            out.append(
                f"ellipses: {self.ellipses_per_1k} per 1,000 words "
                f"(target ≤ {ELLIPSES_MAX_PER_1K:g})"
            )
        if self.dashes_per_1k > DASHES_MAX_PER_1K:
            out.append(
                f"em dashes: {self.dashes_per_1k} per 1,000 words (target ≤ {DASHES_MAX_PER_1K:g})"
            )
        for phrase, n in self.stock.items():
            out.append(f"stock phrase /{phrase}/ appears {n} times (target 0)")
        return out

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(
            she_he_pct=self.she_he_pct,
            ellipses_per_1k=self.ellipses_per_1k,
            dashes_per_1k=self.dashes_per_1k,
            stock_total=self.stock_total,
            repetitions_per_1k=self.repetitions_per_1k,
        )
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> StyleMetrics:
        return cls(
            words=int(d.get("words", 0)),
            narration_sentences=int(d.get("narration_sentences", 0)),
            she_he_openers=int(d.get("she_he_openers", 0)),
            ellipses=int(d.get("ellipses", 0)),
            em_dashes=int(d.get("em_dashes", 0)),
            stock=dict(d.get("stock") or {}),
            repetitions=int(d.get("repetitions", 0)),
            even_runs=int(d.get("even_runs", 0)),
        )


def sentences_to_fix(
    paragraphs: list[tuple[str, str]], metrics: StyleMetrics, *, limit: int = 30
) -> list[str]:
    """Concrete sentences behind each missed target, as ``[id] sentence``.

    Giving the polish model the exact sentences works better than giving it
    only the numbers: a small model otherwise returns the text unchanged.
    """
    want_she_he = metrics.she_he_pct > SHE_HE_MAX_PCT
    want_ellipses = metrics.ellipses_per_1k > ELLIPSES_MAX_PER_1K
    want_dashes = metrics.dashes_per_1k > DASHES_MAX_PER_1K
    out: list[str] = []
    for pid, text in paragraphs:
        narration = _QUOTED.sub(" ", text)
        for sentence in _SENTENCE_SPLIT.split(narration):
            s = " ".join(sentence.split())
            if len(s.split()) <= 2:
                continue
            reasons = []
            if want_she_he and _SHE_HE_OPENER.match(s):
                reasons.append("She/He opener")
            if want_ellipses and ("\u2026" in s or "..." in s):
                reasons.append("ellipsis in narration")
            if want_dashes and "\u2014" in s:
                reasons.append("em dash")
            if any(re.search(p, s, re.IGNORECASE) for p in STOCK_PHRASES):
                reasons.append("stock phrase")
            if reasons:
                out.append(f"[{pid}] ({', '.join(reasons)}) {s}")
            if len(out) >= limit:
                return out
    return out


def _stem(word: str) -> str:
    w = word.lower().replace("\u2019", "'")
    for suffix in ("'s", "ingly", "edly", "ing", "ed", "ly", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


@dataclass(slots=True)
class Repetition:
    paragraph_id: str
    word: str


def find_repetitions(
    paragraphs: list[tuple[str, str]], *, ignore: set[str] | None = None
) -> list[Repetition]:
    """Content words used again within ``REPEAT_WINDOW_CONTENT_WORDS`` content words.

    Skips function words, words under four letters, names (capitalised words
    that never appear in lower case) and ``ignore`` (glossary terms, which must stay fixed).
    Reports each word once per paragraph, at its second use.
    """
    ignore_stems = {_stem(w) for w in (ignore or set())}
    # A capitalised word that never appears in lower case here is a name.
    lowercase_words = {
        m.group(0).lower()
        for _, text in paragraphs
        for m in _WORD.finditer(text)
        if m.group(0)[0].islower()
    }
    stream: list[tuple[str, str, str]] = []  # (paragraph id, stem, surface)
    for pid, text in paragraphs:
        for m in _WORD.finditer(text):
            surface = m.group(0)
            low = surface.lower().replace("\u2019", "'")
            if len(low) < 4 or low in _STOPWORDS:
                continue
            if surface[0].isupper() and surface.lower() not in lowercase_words:
                continue
            stem = _stem(surface)
            if stem in ignore_stems:
                continue
            stream.append((pid, stem, surface))
    out: list[Repetition] = []
    last_seen: dict[str, int] = {}
    reported: set[tuple[str, str]] = set()
    for pos, (pid, stem, surface) in enumerate(stream):
        prev = last_seen.get(stem)
        if (
            prev is not None
            and pos - prev <= REPEAT_WINDOW_CONTENT_WORDS
            and (pid, stem) not in reported
        ):
            reported.add((pid, stem))
            out.append(Repetition(pid, surface.lower()))
        last_seen[stem] = pos
    return out


@dataclass(slots=True)
class EvenRun:
    paragraph_id: str
    lengths: list[int]
    first_sentence: str


def find_even_runs(paragraphs: list[tuple[str, str]]) -> list[EvenRun]:
    """Runs of 4+ consecutive sentences of about the same length (±25%).

    Sentences under six words end a run: they already vary the rhythm.
    """
    out: list[EvenRun] = []
    for pid, text in paragraphs:
        sentences = [" ".join(s.split()) for s in _ANY_SENTENCE_SPLIT.split(text) if s.strip()]
        lengths = [len(s.split()) for s in sentences]
        i = 0
        while i < len(lengths):
            j = i
            while j < len(lengths) and lengths[j] >= EVEN_RUN_MIN_WORDS:
                window = lengths[i : j + 1]
                mean = sum(window) / len(window)
                if any(abs(n - mean) > EVEN_RUN_TOLERANCE * mean for n in window):
                    break
                j += 1
            if j - i >= EVEN_RUN_MIN_SENTENCES:
                out.append(EvenRun(pid, lengths[i:j], sentences[i]))
                i = j
            else:
                i += 1
    return out


def rhythm_to_fix(
    paragraphs: list[tuple[str, str]], *, ignore: set[str] | None = None, limit: int = 20
) -> list[str]:
    """Repeated words and even-length sentence runs, as ``[id] …`` lines."""
    out: list[str] = []
    for r in find_even_runs(paragraphs):
        lengths = ", ".join(str(n) for n in r.lengths)
        out.append(
            f"[{r.paragraph_id}] {len(r.lengths)} sentences in a row of similar length "
            f"({lengths} words), starting: {r.first_sentence[:80]}"
        )
    for rep_ in find_repetitions(paragraphs, ignore=ignore):
        out.append(f'[{rep_.paragraph_id}] "{rep_.word}" is used again within a few lines')
    return out[:limit]


def style_metrics(paragraphs: list[str]) -> StyleMetrics:
    m = StyleMetrics()
    pairs = [(str(i), t) for i, t in enumerate(paragraphs)]
    m.repetitions = len(find_repetitions(pairs))
    m.even_runs = len(find_even_runs(pairs))
    for text in paragraphs:
        m.words += len(text.split())
        m.ellipses += text.count("\u2026") + text.count("...")
        m.em_dashes += text.count("\u2014")
        narration = _QUOTED.sub(" ", text)
        for sentence in _SENTENCE_SPLIT.split(narration):
            if len(sentence.split()) <= 2:
                continue
            m.narration_sentences += 1
            if _SHE_HE_OPENER.match(sentence):
                m.she_he_openers += 1
        for phrase in STOCK_PHRASES:
            n = len(re.findall(phrase, text, re.IGNORECASE))
            if n:
                m.stock[phrase] = m.stock.get(phrase, 0) + n
    return m


@dataclass(slots=True)
class QaIssue:
    check: str
    paragraph_id: str
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"check": self.check, "paragraph_id": self.paragraph_id, "detail": self.detail}


def hard_checks(
    *,
    source: list[tuple[str, str]],
    target: list[tuple[str, str]],
    source_language: str,
    allowed_words: set[str] | None = None,
) -> list[QaIssue]:
    """Checks on paragraph-aligned ``(paragraph_id, text)`` pairs.

    ``allowed_words`` are words that may keep source letters (names the
    glossary keeps in the original, e.g. "Elżka").
    """
    issues: list[QaIssue] = []
    # Letters that should not appear in English output (a regex class body).
    letters = source_letters(source_language)
    letter_re = re.compile(f"[{letters}]") if letters else None
    allowed = {w.lower() for w in (allowed_words or set())}
    source_by_id = dict(source)

    for pid, text in target:
        if letter_re is not None:
            bad = sorted(
                {
                    w.strip(".,;:!?\"'()[]*\u2018\u2019\u201c\u201d\u2014\u2026")
                    for w in text.split()
                    if letter_re.search(w)
                }
            )
            bad = [w for w in bad if w and w.lower() not in allowed]
            if bad:
                issues.append(
                    QaIssue("source_letters", pid, "Source-language words left: " + ", ".join(bad))
                )
        if re.match(r"^\s*[\u2013\u2014-]\s", text):
            issues.append(
                QaIssue(
                    "dialogue_dash", pid, "Paragraph starts with a dash; dialogue should be quoted."
                )
            )
        if re.search(r"\\[!.*_#\[\]()-]", text):
            issues.append(QaIssue("escape_backslash", pid, "Markdown escape backslash left in."))
        src = source_by_id.get(pid, "")
        for pat in PLACEHOLDER_PATTERNS:
            want = len(re.findall(pat, src))
            got = len(re.findall(pat, text))
            if want != got:
                issues.append(
                    QaIssue(
                        "placeholder",
                        pid,
                        f"Author placeholder /{pat}/ appears {want} times in the source, {got} times here.",
                    )
                )
    return issues
