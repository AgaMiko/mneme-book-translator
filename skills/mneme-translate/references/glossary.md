# Glossary

The glossary gives every name, place and invented word one agreed English form, so the translation uses it the same way every time. These rules come from the app's glossary prompts (`extract_glossary_prompt.py` and `review_glossary_prompt.py`).

## File format

`glossary.md` in the book folder holds one Markdown table. Keep the header exactly as below, because `mneme.py` reads the table by these column names. Do not put a `|` inside a cell.

```markdown
# Glossary

| Source | Forms seen | Type | English | Alternatives | Notes | Status | Match |
|---|---|---|---|---|---|---|---|
| Hania | Hani, Hanię, Hanka | character_name | Hania | Hanna | Kerry's sister; Hanka is a fond short form. | proposed | |
| Szklane Wzgórze | Szklanym Wzgórzu | place_name | Glass Hill | Glasshill | Descriptive name: translate the image. | proposed | |
| Dłonie | Dłoni, Dłońmi | lore_term | the Hands | | Imperial name for Weavers. The ordinary word dłoń (a hand) is NOT this term. | proposed | case |
```

- **Source**: the canonical form, the one the book settles on.
- **Forms seen**: other spellings, inflected forms, epithets and nicknames of the same thing, comma separated. Only names and forms of the term itself: not common nouns that refer to the character ("wuj", uncle, is not a form of Tyrel), because the check then expects the name wherever the word appears. The script matches each word of a form with case endings (a word of five letters or more may change its last letter and add up to four), so list irregular forms that change more than that (Polish "Pies" → "Psa").
- **Type**: `character_name`, `place_name`, `organization`, `lore_term` (invented magic, technology, artefacts, named creatures and events, in-world religion), `cultural_term` (real-world customs, food or dress a reader may not know), `specialized_usage` (an ordinary word with a special in-world sense), `other`.
- **English**: the one form the translation uses.
- **Alternatives**: other good options, so the reviewer can choose.
- **Notes**: what it is, in one sentence, and why this English form. Say when an ordinary word is NOT the glossary term (a literal object that shares a name with a lore term).
- **Status**: `proposed`, then `accepted` or `rejected` after review. Rejected rows are ignored by the script.
- **Match** (optional last column; leave it empty in most rows): `case` matches the forms only with the capitals as written, `exact` matches them without case endings, `case exact` does both. Use it for a term that is also an everyday word ("Dłonie", the Hands, a name for Weavers, against "dłoni", a hand), so the script does not list the term in every fragment and the check does not flag every hand.

## Starting from an existing glossary

If the user has a reviewed glossary from another book (the next book in a series, or an earlier version of this manuscript), copy it to `glossary.md` in the book folder before this step, in the format above. Then build as below, with one difference: rows already marked `accepted` or `rejected` are the author's decisions. Never rename, rewrite or merge them away. Only add missing terms as `proposed`, and add new forms seen to existing rows.

## Building it

Read the manuscript chapter by chapter (`source/chapter-NN.md`). After each chapter, update `glossary.md` with what that chapter adds: new terms, new forms of existing terms, merges, and corrections. Keep a short private notepad in `work/glossary-notes.md` for things to watch (a spelling to confirm, a name whose role is not clear yet). For a long book, read several chapters in parallel with subagents and merge their rows; check the merged table for duplicates.

What to find: every surface form an English-only reader needs a stable decision on. Proper names, invented or world-specific vocabulary, culturally loaded labels, and ordinary words used in a special in-world sense. Skip generic description and words used in their everyday meaning.

- **Canonical form.** Prefer the form the manuscript settles on as the usual reference, even when the first occurrence was longer (a titled introduction, then the short name used afterwards).
- **Deduping.** If a spelling, epithet or nickname clearly belongs to a term already in the table, add it to Forms seen instead of opening a new row. When two rows are the same entity, merge them and keep the steadier heading.
- **Substantive updates only.** Change a row only when a later chapter changes its meaning or the translation strategy.
- **English for readers who do not know the source language.** Descriptive place names and faction labels usually carry meaning first: give their image or role in English rather than keeping opaque source-language strings, except where the story clearly needs the exact source form on the English page.
- English running text should normally avoid source-language letters; keep diacritics and exact spellings in the Source and Forms seen columns.
- When the source register is archaic, folkloric or slangy, let a matching texture show in English where it fits the narrative voice.
- Titles of songs, chapters and in-world works should read like credible English titles with the same emotional cue.
- When related word families appear (shared roots across roles or processes), line up the English so the kinship stays visible, and fix earlier rows if a later chapter shows a link you missed.
- When several English options are all defensible, pick one default, put the others in Alternatives, and say briefly in Notes how they differ.

## Reviewing it (before showing it to the user)

Go through the proposed rows once more and decide each the way the author would. A term belongs in the glossary when the translation needs one fixed decision for it.

**Keep:** names of people, places, organisations, factions and creatures; invented words and coinages; titles of in-world books, songs and works, and quoted sayings, prayers or mottos, even when they appear only once; words used in a special in-world sense, and named concepts where several English renderings are possible and consistency matters.

**Remove:** everyday words whose English is simply the dictionary word (a sword, darkness); descriptive phrases and sensory descriptions that are not names; ordinary objects, foods and actions; generic ranks and roles used as common nouns (a general).

**Merge** only when two rows refer to the same person, place or thing: another name, an epithet, a short form, or the same term in another grammatical form. Similar meaning is not enough.

Also remove forms that do not belong to the term (another character's nickname), and fix an English target that is clearly wrong.

Also decide the English title of the book with the user if it is not set; it goes to `export --title`.

Then show the user a short summary: how many terms by type, the rows you are least sure about (titles of in-world works, named abilities that read like descriptions, everyday words that might carry a special sense, merges of a name with an epithet), and the choices with strong alternatives. The user edits `glossary.md` directly or tells you what to change. When the user is happy, set the kept rows to `accepted` and run `mark glossary reviewed`.

## Changing a term later

If the user changes an English form after fragments are translated, search `translation/` for the old form and replace it, then run `check` again.
