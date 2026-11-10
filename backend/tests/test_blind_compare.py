"""Blind comparison file: A/B order is hidden, identical paragraphs are left out."""

from __future__ import annotations

from app.tools.blind_compare import ComparedParagraph, build_blind


def test_blind_file_hides_the_order_and_the_key_reveals_it() -> None:
    paragraphs = [
        ComparedParagraph("chapter 1", f"src {i}", f"old {i}", f"new {i}") for i in range(20)
    ] + [ComparedParagraph("chapter 2", "same", "Same text.", "Same text.")]
    doc, key, identical = build_blind(paragraphs, seed=1)

    assert identical == 1
    assert "20 paragraphs differ; 1 identical" in doc
    assert "Same text." not in doc
    # Both orders occur, and the key matches what the document shows.
    lines = key.splitlines()[2:]
    assert any("A = old" in line for line in lines)
    assert any("A = new" in line for line in lines)
    for n, line in enumerate(lines, start=1):
        section = doc.split(f"## ¶{n} ")[1].split("## ¶")[0]
        a_text = section.split("**A:** ")[1].split("\n")[0]
        assert a_text.startswith("old" if "A = old" in line else "new")


def test_same_seed_same_order() -> None:
    paragraphs = [ComparedParagraph("c", "s", f"o{i}", f"n{i}") for i in range(5)]
    assert build_blind(paragraphs, seed=3) == build_blind(paragraphs, seed=3)
