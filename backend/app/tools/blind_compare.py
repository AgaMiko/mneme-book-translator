"""Blind comparison of two translation runs, paragraph by paragraph.

Writes a Markdown file where each paragraph shows the source and the two
translations under the letters A and B, in random order, and a separate key
file that says which letter is which run. Read and judge the first file
before opening the key.

Used to compare prompt versions: translate the same chapters once with each
version, then::

    docker compose exec api python -m app.tools.blind_compare \\
        --old <run id> --new <run id> --out /app/compare.md

Only final texts are compared (the ``polish`` stage, which every mode
stores its last pass as): a fragment that stopped at an earlier stage in
either run is left out and counted, so a draft is never judged against a
final text. Paragraphs where the two texts are identical are counted and
left out too.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models.book import Chapter, Paragraph
from app.models.translation import FragmentRendition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Every mode (one, two or three steps) stores its last pass under this stage.
_FINAL_STAGE = "polish"


@dataclass(frozen=True, slots=True)
class ComparedParagraph:
    chapter: str
    source: str
    old: str
    new: str


def build_blind(paragraphs: list[ComparedParagraph], *, seed: int) -> tuple[str, str, int]:
    """``(document, key, identical_count)`` for paragraphs in book order."""
    rng = random.Random(seed)
    doc: list[str] = []
    key: list[str] = []
    identical = 0
    number = 0
    for p in paragraphs:
        if p.old.strip() == p.new.strip():
            identical += 1
            continue
        number += 1
        old_first = rng.random() < 0.5
        a, b = (p.old, p.new) if old_first else (p.new, p.old)
        doc.append(
            f"## ¶{number} ({p.chapter})\n\n**Source:** {p.source}\n\n**A:** {a}\n\n**B:** {b}\n"
        )
        key.append(
            f"- ¶{number}: A = {'old' if old_first else 'new'}, B = {'new' if old_first else 'old'}"
        )
    header = (
        f"# Blind comparison\n\n{number} paragraphs differ; {identical} identical ones "
        "are left out. For each paragraph, pick the better version against the source "
        "(and note any errors) before opening the key.\n"
    )
    return header + "\n" + "\n".join(doc), "# Key\n\n" + "\n".join(key) + "\n", identical


async def _final_texts(session: AsyncSession, run_id: UUID) -> tuple[dict[str, str], int]:
    """``({paragraph_id: final text}, fragments without a final text)`` for one run."""
    rows = (
        await session.execute(select(FragmentRendition).where(FragmentRendition.run_id == run_id))
    ).scalars()
    final: dict[UUID, FragmentRendition] = {}
    seen: set[UUID] = set()
    for r in rows:
        seen.add(r.fragment_id)
        if r.stage == _FINAL_STAGE:
            final[r.fragment_id] = r
    out: dict[str, str] = {}
    for r in final.values():
        for p in r.paragraphs:
            out[str(p["paragraph_id"])] = p.get("text", "")
    return out, len(seen - set(final))


async def _load(old_run: UUID, new_run: UUID) -> list[ComparedParagraph]:
    async with get_sessionmaker()() as session:
        old, old_unfinished = await _final_texts(session, old_run)
        new, new_unfinished = await _final_texts(session, new_run)
        if old_unfinished or new_unfinished:
            print(
                f"Left out fragments without a final text: {old_unfinished} in the old run, "
                f"{new_unfinished} in the new run."
            )
        shared = set(old) & set(new)
        if not shared:
            return []
        rows = await session.execute(
            select(Paragraph, Chapter)
            .join(Chapter, Paragraph.chapter_id == Chapter.id)
            .where(Paragraph.id.in_([UUID(pid) for pid in shared]))
            .order_by(Chapter.position, Paragraph.position)
        )
        return [
            ComparedParagraph(
                chapter=chapter.title or f"chapter {chapter.position + 1}",
                source=para.text,
                old=old[str(para.id)],
                new=new[str(para.id)],
            )
            for para, chapter in rows.all()
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--old", required=True, type=UUID, help="run id of the old version")
    parser.add_argument("--new", required=True, type=UUID, help="run id of the new version")
    parser.add_argument("--out", required=True, type=Path, help="Markdown file to write")
    parser.add_argument("--seed", type=int, default=0, help="seed for the A/B order")
    args = parser.parse_args()

    paragraphs = asyncio.run(_load(args.old, args.new))
    if not paragraphs:
        raise SystemExit("The two runs have no translated paragraphs in common.")
    doc, key, _ = build_blind(paragraphs, seed=args.seed)
    args.out.write_text(doc, encoding="utf-8")
    key_path = args.out.with_suffix(".key.md")
    key_path.write_text(key, encoding="utf-8")
    print(f"Wrote {args.out} and {key_path}")


if __name__ == "__main__":
    main()
