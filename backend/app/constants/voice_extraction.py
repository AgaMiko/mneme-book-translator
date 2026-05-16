"""Voice extraction manuscript windowing — single source of truth.

Used by ``voice_service.make_windows`` and the voice-extraction job.

Tighter window than glossary (500 vs 1000 words) because voice work
benefits from closer reading: less working context for the model to
lose track of which character it's writing about, less identity
leakage in the prose body. Trade is roughly 2× more LLM calls per
book than glossary — acceptable for a stage that produces per-character
authorial-craft output rather than entity coverage.

Frontend mirror (keep values identical):
``frontend/src/constants/voiceExtraction.ts``.
"""

VOICE_EXTRACTION_WINDOW_WORDS = 500
VOICE_EXTRACTION_OVERLAP_WORDS = 100
