"""Prompt for the first-pass manuscript metadata extraction step."""

PROMPT = """\
Extract metadata from this manuscript opening. Use only evidence visible in the sample — leave fields absent rather than guess.

For the style note, be concrete: name the register, the voice, and any texture a translator should keep in mind. Avoid empty labels like "literary fiction".

Opening sample:
{sample}
"""

