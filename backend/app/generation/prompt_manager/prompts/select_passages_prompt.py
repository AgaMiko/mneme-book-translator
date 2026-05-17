"""Prompt template for per-character passage selection.

Paired with ``../models/select_passages_model.py``.

One call per character. The chain sees: source voice observation, target
voice strategy, the character's candidate pool, and the requested
passage_count (computed code-side from glossary mention percentile).
"""

from typing import Any

PROMPT = """\
You are picking the final reference passages for a character whose \
voice has been extracted from a {source_language} fiction manuscript. \
The selected passages will become the canonical calibration samples \
for translation into {target_language}.

You see the character's voice observation, target rendering strategy, \
and a pool of candidate passages collected during extraction. You pick \
{passage_count} passages from \
the pool — the ones that, taken together, best represent how this \
character sounds.

You do not translate. You do not edit the source text. Your only \
output is the selection, with brief reasoning per choice.

## Two non-negotiables

The system checks both. Operations that violate them are dropped.

**(1) Each ``candidate_source_text`` you return must be VERBATIM from \
the candidate pool below.** The system looks up the candidate by this \
text. Do not paraphrase, do not edit, do not combine candidates.

**(2) The ``profile_id`` and ``canonical_name`` you return must match \
the input.** Cross-checked.

## Selection criteria

You're picking for *coverage*, not just quality. The selected passages \
should collectively show different facets of the character's voice — \
different relationship dynamics, different emotional pitches, different \
displays of register. Two passages showing the same voice display are \
worse than one passage of a different display.

For each selection, the ``why_this_one`` reasoning should reference \
what voice display this passage shows that the other selections don't.

How to think about it:

1. **Read the observation and strategy.** What modes does this character \
have? What target-language register is the author aiming for, and what \
source markers support it? What range does the translator need to see?
2. **Skim the candidate pool's ``why_representative`` reasons.** Where \
do they cluster? Which candidates capture distinct displays?
3. **Pick a "core" first.** The candidate that most fully embodies the \
character's baseline mode — usually the most-cited reason in the pool.
4. **Pick subsequent passages for what the core misses.** A second \
dynamic, a register shift, a moment of departure.
5. **Stop when you've picked the requested count.** Don't pad.

If the candidate pool has fewer entries than the requested \
``passage_count``, return all candidates — better to have fewer good \
passages than to invent or pad.

Order matters: most representative first. The first selected passage \
will be the one translation downstream weights most heavily as a \
calibration sample.

## What NOT to do

- Don't return a candidate not in the pool. Selection lookup will fail.
- Don't return the same candidate twice.
- Don't pick based on length. The richest 3-sentence passage beats a \
mediocre 5-sentence one.
- Don't pick based on plot interest. Voice work is about how the \
character sounds, not what they reveal narratively.
- Don't try to translate. Translation is a separate later step.

---

## Character

profile_id: {profile_id}
canonical_name: {canonical_name}

### Source voice observation

{source_voice_observation}

### Target voice strategy

{target_voice_strategy}

### Candidate pool ({n_candidates} candidates)

You are picking {passage_count} of them.

{candidate_pool_block}
"""


def render_candidate_pool(candidates: list[Any]) -> str:
    """Render the candidate pool for the prompt.

    Each candidate gets a multi-line block with the full source text,
    why_representative reason, and first_seen_window. The model needs
    to read the full text to reason about voice display, so we don't
    truncate.
    """
    if not candidates:
        return "(empty — no candidates; selection cannot proceed)"

    blocks: list[str] = []
    for i, c in enumerate(candidates, start=1):
        blocks.append(
            f"--- Candidate {i} (first seen in window {c.first_seen_window}) ---\n"
            f"why_representative: {c.why_representative}\n"
            f"source_text:\n{c.source_text}"
        )
    return "\n\n".join(blocks)
