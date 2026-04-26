"""Paired schemas + prompts for LLM steps.

Import concrete modules directly, for example
``app.generation.prompt_manager.models.extract_glossary_model`` or
``app.generation.prompt_manager.prompts.extract_glossary_prompt``.

This package ``__init__`` intentionally does **not** re-export symbols or
import chains — doing so created an import cycle with
``app.generation.chains`` during submodule loads.
"""
