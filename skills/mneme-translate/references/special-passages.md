# Special passages

A special passage is a run of paragraphs whose wording follows a rule, so a translation of the meaning alone breaks it. These rules come from the app's `special_passages_prompt.py` and `docs/step6-special-passages.md`.

| Kind | Rule the English must keep |
|---|---|
| `verse` | Poem, song, rhyme, chant, prayer, spell or riddle: number of lines, rhyme scheme, line length. |
| `hidden_message` | Letters or words spell a message (often the first letters of sentences, lines, paragraphs, words or marked words). |
| `wordplay` | A pun, anagram, riddle or play on a name that the plot, a joke or a later line depends on. Ordinary figures of speech do not count. |

## 1. Scan (before translating)

Go through the chapters and list candidates in `passages.md`:

- **verse**: set in lines, as separate paragraphs or line breaks inside one paragraph. An epigraph in the chapter heading counts.
- **document**: a letter, note, inscription or list quoted in the story that could hide a message. Signs: the story says it is coded, strange or worth reading twice; a character studies it or counts letters; its sentences are oddly regular; some words are marked. List every quoted letter or note of several sentences even without such signs: a reader looking at meaning does not notice an acrostic.
- **wordplay** as above.

Most chapters have none.

## 2. State the rule

For each candidate, run `mneme.py letters <chapter> <first-id> <last-id>`. It prints the first letters of the passage's sentences, lines, paragraphs, words and marked words. Read them as words in the source language, and read what the chapter says about the passage (a character who decodes it, a stated message). A letter string that spells nothing is the normal case: do not read a message into it. Drop candidates with no rule.

For each kept passage, write in `passages.md`:

```markdown
## 04: p031–p036 (hidden_message)

Rule: the first letters of the sentences of the letter body spell the message. The salutation and the signature stand outside it.
Source message: …
Target message: THEY'RE WATCHING ME (same meaning, as short as possible)
Dependent paragraphs: p052 (Kerry reads the letters out)
Status: todo
```

- verse: number of lines, rhyme scheme as letters (AABB), what the metre is like.
- hidden_message: the unit, the message in the source, the same message in English, and which part carries it. If the rule is not "first letters of units", describe it exactly, with the steps to read it.
- wordplay: the two meanings or forms, and what depends on them.
- **Dependent paragraphs**: paragraphs of the same chapter that quote the passage, explain its rule, give worked examples of it, or state what it hides. They must stay consistent with the translation.

## 3. Check (after the passage's fragment is translated)

Check only the rule, not style:

- verse: compare line count, rhyme scheme and metre with the source. A rhyme must be heard in English; near-rhymes count only where the source uses them. Correct prose set in lines, without the rhyme the source has, breaks the rule.
- hidden_message: run `letters … --translation` and compare with the target message. Use the script's letters; do not recount by eye. Letters before and after the message are fine when they come from a salutation or sign-off, as in the source.
- wordplay: both meanings must be readable, and what depends on them must still make sense.
- Dependent paragraphs agree with the translation: quoted words match, and a stated message is the one the passage spells.

## 4. Correct

When the rule is broken, translate the passage again:

- The rule comes first, then the meaning, then the exact wording. Keep everything the source says that the rule allows; change wording, word order and sentence breaks freely.
- Keep the voice and register: a letter still sounds like its writer, a folk song still sounds like one. Use names and terms as the current translation has them.
- **Hidden message**: plan first, one unit per letter of the target message. The part that carries the message must have exactly as many units as the message has letters, so merge or split sentences where needed. After writing, check the letters with the script and fix any mismatch. The text must still read as a natural letter, with no sign that it was built around letters.
- **Verse**: keep the number of lines and the rhyme scheme, with rhymes heard in English, and a line length close to the source.
- **Wordplay**: find an English pair that carries both meanings, or the closest play that keeps what depends on it.
- Keep the paragraph ids and count. Update the dependent paragraphs only as much as needed.

Before replacing anything, copy the current English of the passage into `passages.md` under "First translation". Save the new text with the same `save` route (write the whole fragment, or edit the paragraphs in `translation/chapter-NN.md` directly), and check again. Try up to three times; give each new attempt the problems of the last one.

Record the result in the passage's Status:

| Status | Meaning |
|---|---|
| `passed` | The normal translation keeps the rule. Nothing changed. |
| `corrected` | It broke the rule; a new translation passed and replaced it. The author should look at it. |
| `failed` | No attempt passed. The first translation stays. The author must decide before export. |

Show the user every `corrected` and `failed` passage with the source, the first translation, the new text and a note on what changed. Dependent paragraphs in other chapters are not patched: name them for the user.
