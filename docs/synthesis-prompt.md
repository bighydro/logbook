# The synthesis prompt

`logbook transcript synthesize` sends a model two messages: the prompt, which is the file
[`logbook/contrib/synthesis-prompt.md`](https://github.com/bighydro/logbook/blob/main/logbook/contrib/synthesis-prompt.md)
in the package with the call and the language filled in, and the call as JSON. This page explains the
prompt; `transcript synthesize ID --show-prompt` prints both as they go. The prompt's name,
`transcript-synthesis/1`, is kept in every synthesis's `extra.prompt`, so a draft says which wording
wrote it, and a call synthesized under an older prompt is synthesized again; a change to the prompt that
changes what a synthesis holds bumps the number.

## What it asks for

One JSON object with five keys, each a list, in this order, which is the order the record keeps and
the Day prints whatever order the model answers in:

| Key | What | Each item |
|---|---|---|
| `actions` | what someone is to do after the call, one item per action | `text`, `assignee` (as the transcript names them, `me` for the owner, or null), `due` (the call's own words for when, or null), `evidence` |
| `topics` | the themes of the call, each once, however often it came back | `topic` (two to five words), `text` (one or two sentences), `evidence` |
| `decisions` | what the call agreed and closed | `text`, `evidence` |
| `open_threads` | what it left unanswered or said to come back to | `text`, `evidence` |
| `personal` | anything personal that came up: at most three short neutral sentences | `text`, `evidence` |

`evidence` is a list of the material's references: `U12` for an utterance, `T` for what the header alone
says. An item that rests on no utterance carries `"unsupported": true` in its place.

## The rules it gives the model

1. **Evidence.** Every item names the utterances it rests on, or says `unsupported`. Never an invented
   reference, never one the material did not give, never an utterance cited for an item it does not
   support. The record checks every reference afterwards ([the synthesis](transcript-synthesis.md#evidence-the-transcript-line-and-the-utterances-beside-it)),
   so the rule is enforced, not only asked.
2. **Work only.** The actions, topics, decisions and open threads are the work the call was about.
   Whatever is personal (health, family, feelings, a private plan, anyone's life outside work) goes to
   `personal`, as a pointer and never its details ("A family matter of Ola's came up."), or nowhere.
   This is the synthesis's only filter, and it is the model's to apply: the code sends the whole call
   and decides nothing about what is personal, because a word list would both miss and over-reach.
3. **Actions on top**, one item per action, with the assignee and the due hint the call gave. An action
   nobody took on is still an action.
4. **Topics are consolidated across the whole call.** A theme that comes up at minute 2, again at
   minute 20 and at minute 45 is one topic citing all three places, never three topics, and never one
   topic per stretch of the call. The utterances carry their time into the call when the recording
   gives it, so the model can see the theme return. The record holds the model to it as far as names
   go: two topics with the same name, case and spacing aside, are merged into one.
5. **Decisions are settled, not discussed.** A proposal nobody agreed to, or a question talked over and
   left, is an open thread.
6. **Open threads** are what was left unanswered or said to come back to.
7. **Only what the transcript says**, names as it gives them, plain and brief; no greeting, no
   headings, no bullet marks.

The prompt names the call (title, weekday, day, zone, how many utterances) and the language to write in:
the language most of the call is in, decided as the dream decides it, by counting each language's
commonest words over the title and the utterances.

## What the model is not given

Addresses, phone numbers or provider ids of the participants (names only); any other line of the
record; the provider's own summary; the draft of the day. Its answer becomes a `draft/v1` line whose
segments carry the transcript line's id and whose `extra.segments` carry the utterance numbers; nothing
of the prompt or of the call's words is kept.
