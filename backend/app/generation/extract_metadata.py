"""Compatibility shim.

The orchestration now lives in `app.generation.chains.extract_metadata_chain`.
This module keeps the original import path working.
"""

from app.generation.chains.extract_metadata_chain import extract_manuscript_metadata

__all__ = ["extract_manuscript_metadata"]
