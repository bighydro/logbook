# The relationship reader — EXPERIMENTAL, slice 0

A question asked across time about one person, "what did Ola and I plan for the boat?", answered from
that person's lines only, with every line the answer cites resolved against the record. This slice is
the acceptance test and the smallest code that passes it. **No model is wired yet**: `ask.MODEL` is
`None`, `logbook people ask` refuses in one sentence until a later slice wires one, and the tests set a
stub. Nothing here depends on Honcho: the store under `state/` is shaped as a Honcho-like store would
hold it (peers, messages, the line-id map), and a later slice may put a real one behind the same
boundary.

```
logbook people ingest "Ola Nordmann" --window 2026-06-01 2026-06-30   # read his lines into the store
logbook people ask "Ola Nordmann" "What did we plan for the boat?"     # answer from it; writes nothing
```

## The boundaries

- **A reader, not a writer.** It never appends a line, never signs a day, never writes a note and never
  resolves an identity. The canonical record is the same before and after, head and bytes; the only
  thing it writes is its own store under `state/relationship/<person>/`, bookkeeping beside the record
  and never in it, never in a backup.
- **Its own crossing entry.** Reading a person for a model is a crossing, so it is governed by
  `policy/crossing.json`: `{"relationship": {"max_tier": 2, "until": "2026-12-31"}}`. `max_tier` is the
  ceiling the lines are read and served under; `until`, required, is the last day the lend holds. No
  entry, no `until`, or a day past it, and nothing is read or served.
- **The authorized input set** (RFC 0036 amendment 1, the person unit) of one canonical person is
  exactly the lines on which they are a counterpart (a message they sent or the owner sent in a direct
  chat with them, a call with them, a mail from or to them), an attendee (an event they did not decline)
  or a speaker (a transcript they spoke in), on a local day of the stated window, not retracted, at or
  under the ceiling. A line that merely mentions them is never in it: a note that says "with Ola", a mail
  that names them, a message someone else sent in a group, a tagged face, a draft. The person is one the
  record's resolution lines name, as `logbook people NAME` finds them, never the owner; an unresolved
  name is refused and gets no store.
- **Real speaker attribution.** Each line in the store carries the peers whose words it is: a message
  its sender's (the owner's, for one the owner sent), a mail its sender's, an answered call both ends',
  a transcript every participant the record resolves. An event is attendance, not speech. A name in a
  line's text is never a speaker.
- **One peer per canonical person.** The peers are the person, the other canonical people who spoke on
  their lines, and the owner, each once by entity id. A speaker the record does not resolve gets no
  peer; the line counts them as `unresolved`, by number only.
- **Exclusions twice.** A line above the ceiling, retracted, outside the window or merely a mention is
  left out before anything is written, and left out again when serving: `ask` reads the set again from
  the record and serves only the store's messages whose line is in it. The store is disposable and may
  be stale or edited by hand; a message whose line is not in the set is withheld and counted.
- **Citations resolved, unsupported claims visible.** Every id the model cites is resolved against the
  set: a line of it is printed with its instant, kind, source and speakers; any other id, a real line of
  the record or not, is marked unsupported with the reason, and so is a claim that cites nothing.
- **Derived access follows the policy, not only the head.** A store serves only under the head and the
  entry it was read under. A line retracted or added, the entry lowered, raised or given a new `until`,
  and `ask` refuses until the store is ingested again; an expired entry refuses outright.
- **Disposable.** Ingesting rebuilds the whole store from the record, so ingesting twice writes the same
  bytes, and wiping `state/relationship/<person>/` and ingesting again recovers the same input set and
  the same line-id map. What a model says from it need not be the same prose twice; it is never stored.

## The store

`state/relationship/<person>/`, written by `people ingest`, `manifest.json` last:

| File | Holds |
|---|---|
| `manifest.json` | the reader (`relationship/0`), the person and label, the window, `read_head`, the `policy` read under, `read_count`, `held_back` (the person's lines above the ceiling, by number) |
| `peers.json` | `[{id, label}]`: the person, the others who spoke, the owner (`owner`) |
| `messages.jsonl` | one message per line of the set: `id`, `speakers` (peer ids), `role` (counterpart, attendee, speaker), `kind`, `at`, `source`, `tier`, `unresolved`, `text` (a message's text, a mail's subject, an event's title, a transcript's title and the provider's summary, a call as what it was) |
| `lines.json` | the line-id map: message id → line id |

## Not in this slice

Mood and personality claims, a real model and its prompt, Honcho itself, a person draft written to the
record (`draft/v1` unit `person`; RFC 0036 leaves its writer open), and a door tool. The person's label
comes from a resolution line and is given to the model with the lines, as the amendment's "what the
model reads" has it; whether a ceiling below that line's tier should withhold it is open.
