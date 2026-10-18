# The relationship reader (experimental)

A question asked across time about one person, answered by a model from what passed between you and
them, and nothing else, with every claim citing the lines it rests on or listed as unsupported. The
boundaries in full are in `logbook/contrib/relationship/README.md`; this page is how to use it.

```
logbook people ingest "Ola Nordmann" --window 2026-06-01 2026-06-30
logbook people ask "Ola Nordmann" "What did we plan for the boat?"
logbook dream person "Ola Nordmann" --window 2026-06-01 2026-06-30
```

## The entry

Nothing crosses without its own entry in `policy/crossing.json`, with a last day:

```json
{"relationship": {"max_tier": 2, "until": "2026-11-15"}}
```

- `max_tier`: the highest tier of a line that may be read and sent, and of the names that say whom a
  line is with: 1 or 2. While the model is a cloud one, an entry that says 3 is refused, and nothing
  above the ceiling is read.
- `until`, required: the last day the lend holds. From the next day nothing is read or sent, and the
  command says so in one sentence; write a new date to lend it again.
- `model`, optional: the one model a person may go to. When `LOGBOOK_DREAM_MODEL` names another, the
  command refuses.
- `include_unsigned`, optional: `true` lets the lines of days you have not signed cross too. Without
  it only the lines of signed days cross (`day sign`, RFC 0034).

The `dream` entry never stands in for it: a record with a `dream` entry and no `relationship` entry
sends no person anywhere.

## The model

Until a model runs on your own hardware, the reader uses the model the dream uses, through the same
three variables (`docs/dream.md`): `LOGBOOK_DREAM_ENDPOINT`, `LOGBOOK_DREAM_MODEL` and, for a cloud
model, `LOGBOOK_DREAM_KEY`. The key goes in the request's header and nowhere else: an error from the
endpoint is said with it replaced by `<key>`.

What the model is sent is the person's name, the window, your question and their lines in it: the
messages of your direct chat (both ways), your calls, the mail between you, the events you both
attended and the calls that were recorded, each with its time, who spoke and its words, and the
promises read in those words. Each line goes as a reference (`L1`, `L2`, ...), never its id. Nothing
else of the record: no note that names them, no group chat, no photo, no stay, no draft, and none of
the days you spent together, which rest on where you were. `people ask --show-prompt` prints exactly
what is sent.

## `people ingest` and `people ask`

`people ingest NAME --window FROM TO` reads the person's lines into a store under
`state/relationship/<id>/`, beside the record and never in it. `people ask NAME QUESTION` sends the
lines the store holds that the record still allows, and prints the answer: each supported claim with
the lines it cites under it, then, under `unsupported`, every claim that cites no line of theirs, a
line outside the set, or a reference it was not given. `--json` carries the same, and the claims in
the `draft/v1` segment shape. An answer is never written.

The store serves only under the head and the entry it was read under: a new line, a retraction, a
signed day, or the entry changed, and `ask` asks you to ingest again.

## `dream person`

`dream person NAME [--window FROM TO]` (default: the 90 days that end today) reads the same lines from
the record and writes one `draft/v1` line about the person, as `dream day` writes one about a day: what
passed between you, the threads still open, the promises, two questions, every sentence citing their
lines or marked unsupported, refused when more than 30 % is unsupported. It is a proposal, never a fact.
Dreaming the same person over the same window at the same head writes nothing; another window, or a
record that moved, writes a new draft that supersedes the standing one. `--dry-run` asks and writes
nothing. No page shows a person draft yet.
