"""Glossary extraction manuscript windowing — single source of truth.

Used by ``make_windows``, window-count helpers, and cost estimates so the
API, background job, and tests stay aligned.

Frontend mirror (keep values identical):
``frontend/src/constants/glossaryExtraction.ts``.
"""

GLOSSARY_EXTRACTION_WINDOW_WORDS = 1000
GLOSSARY_EXTRACTION_OVERLAP_WORDS = 200

# Glossary statuses the later steps (speakers, voices, translation) accept.
# A stopped or failed run keeps the terms it found, so the author can move on
# with them; only a glossary never started, or still running, blocks.
# Frontend mirror: ``glossaryUsable`` in ``frontend/src/components/book/tabs.ts``.
GLOSSARY_USABLE_STATUSES = ("completed", "cancelled", "failed")
