# The relationship reader — EXPERIMENTAL, slice 1

A question asked across time about one person, "what did Ola and I plan for the boat?", answered by a
model from that person's lines only, with every claim citing lines the record resolves or listed as
unsupported. Slice 0 was the acceptance test and the store; slice 1 wires a real model. Until the
owner's own hardware runs one, that is the cloud model the dream uses, through the same endpoint and
the same three variables (`LOGBOOK_DREAM_ENDPOINT`, `LOGBOOK_DREAM_MODEL`, `LOGBOOK_DREAM_KEY`;
`docs/dream.md`), under this reader's own entry and never the dream's. Nothing here depends on Honcho:
the store under `state/` is shaped as a Honcho-like store would hold it (peers, messages, the line-id
map), and a Honcho service on local hardware may later stand behind the same boundary (`ask.Model`).

```
logbook people ingest "Ola Nordmann" --window 2026-06-01 2026-06-30   # read his lines into the store
logbook people ask "Ola Nordmann" "What did we plan for the boat?"     # the model answers; writes nothing
logbook dream person "Ola Nordmann" --window 2026-06-01 2026-06-30    # one draft/v1 of him, unit person
```

## The boundaries

- **A reader, not a writer.** It never appends a line, never signs a day, never writes a note and never
  resolves an identity. The canonical record is the same before and after, head and bytes; the only
  thing it writes is its own store under `state/relationship/<person>/`, bookkeeping beside the record
  and never in it, never in a backup.
- **Its own crossing entry.** Reading a person for a model is a crossing, so it is governed by
  `policy/crossing.json`: `{"relationship": {"max_tier": 2, "until": "2026-11-15"}}`. `max_tier` is the
  ceiling the lines are read, served and sent under, 1 or 2 (while the model is a cloud one, 3 is
  refused); `until`, required, is the last day the lend holds.
  No entry, no `until`, or a day past it, and nothing is read, served or sent, and one sentence says
  so. The `dream` entry never stands in for it. `model`, optional, is the one model a person may go to
  (an environment that names another is refused); `include_unsigned`, optional, `true` lifts the
  signed-day gate.
- **The gate.** A line of evidence crosses only at or under `max_tier` and on a day the owner has
  signed (RFC 0034), unless the entry says `include_unsigned`; a resolution line, which binds a ref to a
  person and gives the label, only at or under `max_tier`, whatever its day, as `export notion` holds
  them. The people reader reads through it, so no person, label, speaker or line rests on a line above
  the ceiling: a person whose every resolution line is above it is refused, and nothing of them is read.
  The lines the gate refuses are counted (`held_back`, `unsigned`), never read.
- **What crosses to the model** is the person's label, the window, the question and the served lines,
  nothing else: each line as a reference (`L1`, `L2`, ...), never its id, with its instant, kind,
  speakers by label, the record's own words for it (never the store's, which may be edited) and the
  promises read in those words (a mail's among them: its text is its subject, and a promise sentence of
  its body crosses as the promise's quote). A promise is read from a line of the set and adds no line. The days
  together in the window go beside the lines (RFC 0036 amendment 2, the owner's decision of 18 October
  2026): each its date, the `places.json` name of the stay they shared (`a place with no name` when it
  has none, never coordinates) and the references of the lines it rests on, through the same gate, read
  again from the record and never kept in the store; the answer counts them, `days_together`.
- **The key never shows.** Every error from the endpoint is said with the key, and its last eight
  characters, replaced by `<key>`; `--show-prompt` prints the two messages, never a header.
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
- **Citations resolved, unsupported claims visible.** Every reference the model cites is turned back
  into its line id and resolved against the set: a line of it is printed with its instant, kind, source
  and speakers; any other id, a real line of the record or not, an invented reference, a claim that
  cites nothing and one the model marked unsupported are listed under `unsupported` with the reason.
  `--json` carries the answer in the `draft/v1` segment shape too (`segments`). An answer is never
  written to the record.
- **The person draft.** `dream person NAME [--window FROM TO]` (`logbook/contrib/dream_person.py`, a
  writer beside the dream's, never in this package) reads the same set from the record through the same
  gate and writes one `draft/v1` line of unit `person` as `dream day` writes a day's: `subject` the
  person's id, `window`, `policy_version` of the `relationship` entry, evidence only of the set (an id
  outside it marks the sentence unsupported), more than 30 % unsupported refused, `supersedes` the
  standing person draft whatever its window, and nothing written again at the same head over the same
  window under the same entry (RFC 0036 rule 1).
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
| `manifest.json` | the reader (`relationship/1`), the person and label, the window, `read_head`, the `policy` read under (`max_tier`, `until`, `model`, `include_unsigned`), `read_count`, `held_back` (the person's lines above the ceiling, by number), `unsigned` (on days not signed, by number) |
| `peers.json` | `[{id, label}]`: the person, the others who spoke, the owner (`owner`) |
| `messages.jsonl` | one message per line of the set: `id`, `speakers` (peer ids), `role` (counterpart, attendee, speaker), `kind`, `at`, `source`, `tier`, `unresolved`, `text` (a message's text, a mail's subject, an event's title, a transcript's title and the provider's summary, a call as what it was) |
| `lines.json` | the line-id map: message id → line id |

## Not in this slice

Mood and personality claims, Honcho itself, a door tool, and the person page showing the standing
person draft (RFC 0036 amendment 1 puts it after the numbers; nothing reads a person draft yet, and the
readers of drafts hold a person draft to the `relationship` entry it was written under,
`drafts.allowed`). The days together are sent as days, never as the stays' coordinates (above). A person's label comes from a resolution
line at or under the ceiling and counts toward a draft's tier; a person named only above it is refused.
