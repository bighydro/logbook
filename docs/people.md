# People

`logbook people [--year YYYY] [--json]` is everyone the record knows and what it knows of each;
`logbook person <name-or-ref> [--year YYYY] [--json]` is one of them on one page, with the timeline
of the days you spent together. Both are readers (ADR 0013): derived from the record at its head,
every time, and never written. The owner is never listed: the record is yours, and you are not
your own company. `people merge` finds the same person named twice, `people review` finds the people
the sources saw that the record has not placed, and `people --priority` ranks everyone by a plain
score; each writes only when you say so, and only through the record's own lines.

```bash
logbook people                          # everyone with evidence in the record, most days together first
logbook people --year 2026              # one year
logbook people --json                   # the report as one JSON object
logbook person "Ola Nordmann"           # a label; a unique first or last name does too: `person Ola`
logbook person ola@example.org          # an address the resolution lines know
logbook person +447700900001            # a phone number
logbook person provider_id:immich:f_01  # any ref as kind:value; the entity id works too
logbook people --priority               # everyone heard in the last year, ranked, with the score
logbook people review                   # who the sources saw that the record has not placed
```

## Who is a person

A person is an entity the record's resolution lines mint (RFC 0006, `entity.type` `person`): a
contacts import, a `logbook add` of a name for an address, an alias that reaches one. The label of
the first standing line is the name; every ref that resolves to the entity is one of theirs. Nobody
the record has not named appears here: an attendee with a display name and no resolution line is
in `rollup people` under `unresolved`, not in `people`. A person with no evidence in the window is
not listed by `people`; `person` still prints their page and says there is no contact.

The owner is `owner_id` and `owner_emails` in `logbook.json`, every resolution that names those,
and the names, addresses and numbers of `policy/owner.json`, as the with module reads them
(`present.owner_of`). A ref of the owner's counts for nobody.

## What is known

```
11 people · 2026-06-01 – 2026-06-21 · tier 2
  Ola Nordmann  messages 5 · calendar 1 · transcripts 1 · 3 days · 2 nights · last real contact 2026-06-16 (meeting) · birthday 1985-03-12 · Office, aboard solvind, 47.3769,8.5417 (Zürich)
  Liv Berg      calendar 1 · 1 day · last real contact 2026-06-09 (meeting) · Office
  Eva Nordmann  calls 1 · last real contact 2026-06-17 (call)
  Jonas Weber   calendar 1
```

One row per person, most days together first, then the latest contact, then the name. The head
names the window and the **tier** of the report: the highest tier of any evidence it rests on
(SPEC §4). A person's own tier is the highest tier of the lines that put them there, the resolution
lines that name them included, so it is 2 in practice and 3 when a transcript was written at 3.

- **Channels**, each with how many lines, the first and last local day, the highest tier among
  them and, under `--json`, the id of the last line:
    - `messages`: a `message/v1` (RFC 0008) they sent, by `sender`; and one you sent in a
      **direct** chat with them. Your line in a direct chat goes to the one person who wrote in
      that chat; in a chat only you wrote in, to the person the chat's id names (a WhatsApp JID
      `447700900001@s.whatsapp.net` is the phone number; iMessage names a direct chat by the
      address). Your lines in a group name nobody.
    - `calls`: a `call/v1` (RFC 0012) whose `counterparty` they are, answered or not.
    - `mail`: a `mail/v1` (RFC 0015) from them, or to them (`to`, `cc`, `bcc`), by address.
    - `calendar`: an `event/v1` (RFC 0009) they attend and did not decline, timed or all-day,
      wherever it was held.
    - `transcripts`: a `transcript/v1` (RFC 0004) they are a participant of, by email, phone or
      provider id, else by the spoken name when the record labels exactly one person by it.
    - `faces`: a `photo/v1` (RFC 0002) with their face tagged, through the library's person id
      (`provider_id`, `<library>:<id>`).
- **First and last contact**: the earliest and latest day over every channel and every day
  together.
- **Days together**: the confirmed set of the with module (`present`, the rules of
  `trips` and `rollup people`): an attendee of a timed calendar entry held at one of your stays, a
  speaker of a recording made inside it, a note written there that says "with <name>". The day is
  the evidence line's own. A tagged face and an all-day entry's attendee are proposals, not a day
  together.
- **Nights under one roof**: the nights whose overnight stay the person was confirmed at on that
  day — the night at anchor after the note says you grilled with them, the night of the dinner in
  the hotel.
- **Places**: where the days together were, by days there, most first: the stay's named place,
  `aboard <asset>`, or the coordinates with `near <place>, x km` or the city of the nearest large
  airport, as the rollups label an unnamed place.
- **Birthday**: when a standing resolution line of one of their refs carries one under
  `payload.extra.birthday`, as `YYYY-MM-DD` or `--MM-DD` (a year unknown), printed as stored. A
  contacts adapter that reads the card's birthday writes it there; none does yet.
- **Last real contact**: the latest of a message (either way), an answered call, or a day
  together, with how (`message`, `call`, `meeting`; on one day a meeting is named first). A mail is
  a channel and never a real contact: a newsletter is a mail too, and the record cannot tell it from
  a letter. A missed call, a tagged face and an all-day entry are not one either.

## The person page

```
Ola Nordmann  (ola@example.org, +4790000001) · tier 2
  birthday 1985-03-12
  first contact 2026-06-09 · last 2026-06-16 · last real contact 2026-06-16 (meeting)
  channels  messages 5 (2026-06-09 – 2026-06-14) · calendar 1 (2026-06-16) · transcripts 1 (2026-06-11)
  3 days together · 2 nights under one roof
  places  Office (1 day), aboard solvind (1 day), 47.3769,8.5417 (Zürich) (1 day)
  shared days
    2026-06-16  47.3769,8.5417 (Zürich) · attendee of Dinner · night
    2026-06-13  aboard solvind · note says with Ola Nordmann · night
    2026-06-11  Office · spoke in Boat plans
```

The same numbers, then every shared day, most recent first: where, what put them there (the with
module's reasons), and `night` when that night was spent under one roof. Under `--json` each shared
day carries the stay's id, its sources and the ids of its evidence lines.

`<name-or-ref>` is tried as a ref first — `kind:value`, an address, a `+` number — then as an
entity id, then as a label (case aside), then as a word of a label: `Ola` finds Ola Nordmann when
no one else is an Ola; `Nordmann` with three Nordmanns names several and is refused, as is a name
nobody has, and the owner's own. Exit status 2 with the reason on stderr.

## The same person twice

A record gets its people by several roads: the phone's address book mints an entity per card
(`ios-contacts`), a Takeout export mints one per card it cannot match (`google-takeout-contacts`),
and you name a calendar attendee, a mail sender or a transcript speaker by hand. The same person
can end up as two or three entities, each with its own refs, each a row of `people`.
`logbook people merge` finds them, shows why, and merges only when you say so.

```bash
logbook people merge                          # the proposals, with the evidence; nothing written
logbook people merge --json
logbook people merge --apply 5891928aa5523867 2f79068fab4863c9   # merge these, by the ids printed
logbook people merge --export-review review.csv                  # one row per secondary, to mark
logbook people merge --apply-review review.csv                   # merge the rows marked yes
```

```
4 proposals · 9 people named twice or more · tier 2
  5891928aa5523867  Kari Nordmann ← Kari
    phone +447700900101: +447700900101 (ios-contacts, seq 3) · 447700900101@s.whatsapp.net (manual, seq 6)
  2f79068fab4863c9  Per Hansen ← Per Hansen, Per Hansen
    email per.hansen@example.org: per.hansen@example.org (google-takeout-contacts, seq 7) · Per.Hansen@example.org (manual, seq 9)
    phone +447700900102: +447700900102 (google-takeout-contacts, seq 8) · 07700900102 (ios-contacts, seq 10)
  298bc7a7705e8fbc  Liv Berg ← Berg, Liv
    name Liv Berg ~ Berg, Liv · both on mail
nothing merged: `people merge --apply ID...`, or `--export-review FILE`, mark, `--apply-review`
```

Every person entity the resolution lines name, never you, is a candidate, with every ref that
resolves to it through the alias walk. Two candidates are one person when:

- **a phone meets**: a ref of each spells the same E.164 number — a `phone` ref as written, a
  number entered without a country code read with `LOGBOOK_DIAL_PREFIX` (as the adapters read
  it), or a WhatsApp JID handle (`447700900001@s.whatsapp.net`);
- **an email meets**: an `email` ref of each, or a `handle` that is an address, is the same
  address, case aside;
- **the names are one name and they share a channel**: the labels have the same words in any
  order, case, accents and punctuation aside (`Nordmann, Kari` is `Kari Nordmann`), or one spells
  a first name by its initial (`K. Nordmann`); both with two words at least — a first name alone
  names anyone — and never a word one letter off (`Anna` and `Anne` are two people); and both are
  heard on one of the channels above (both through mail, both in transcripts). A name alone is
  never enough.

A ref resolves to one entity only, so a number never meets itself: what meets is two spellings of
one identifier, which is what a second import leaves behind. Matches join (a number between A and
B and an address between B and C is one proposal of three). The **primary** is the candidate with
the most refs, then the most lines heard, then the one minted first; the others are secondary. A
proposal's id is a digest of its entity ids, the same on every run until something changes.

**Applying** writes alias lines and nothing else (RFC 0006, `alias_of`): for each ref of a
secondary whose own line names it, one `resolution/v1` line, `source` `manual`, `method` `owner`,
saying the ref is an alias of the primary's ref (a phone before an address). The ref, and every
ref already aliased to it (a WhatsApp linked-device id that `whatsapp-contacts` pointed at the
number), then resolve to the primary through the ordinary walk, which `people`, `person`, the with
module and every other reader take; a chain that would run past the walk's four hops gets a line
of its own. The line `supersedes` the line it replaces and carries both as `evidence`, the
primary's label, the head the proposal was read against (`logbook_head`), and under `extra` the
proposal id, the two entities and what matched. Nothing is retracted and no raw line is touched:
retract the alias line and the two are two again. `--apply` checks every id before writing the
first line; an id that is no proposal exits 2 and writes nothing. Under `--json`, `--apply`
prints the lines it wrote.

**Reviewing** in a spreadsheet: `--export-review FILE` writes one CSV row per (proposal,
secondary) — `proposal`, `apply`, `primary_id`, `primary`, `primary_refs`, `secondary_id`,
`secondary`, `secondary_refs`, `matched` — with `apply` empty. Write `yes` (or `y`, `x`, `true`,
`1`) in `apply` on the rows to merge and run `--apply-review FILE`: each marked row is the merge
of its secondary into its primary. A row whose secondary already resolves to its primary is said
and skipped, so the same file applies twice without harm; a row naming an entity the record does
not know, or the same entity on both sides, is refused before anything is written. A file without
the three columns is not a review file.

## Review

The record has two layers of people, and the rule between them is the one lesson an earlier system
taught the hard way.

An **observed** person is what one source saw: the address a mail came from, the number a message
came from, the attendee on a calendar entry, the name a transcript gave a speaker. Nobody chose
them; they are in the record because a line names them. A **canonical** person is one you have
confirmed: an entity the resolution lines name (RFC 0006), minted by a contacts import, a
`logbook add` of a name for an address, or a `people merge`. `people` lists the canonical people and
nobody else; the observed people are the rest, waiting. There is no third store: a confirmation is
the alias line `people merge` writes, and a rejection is one line too.

**The strongest-identifier rule.** An observed person's identity is derived from the *strongest
identifier* the observation carries, in this order and never any other way:

1. the **email** address, case aside;
2. else the **phone** number in E.164 — a `+44…` as written, a WhatsApp JID
   (`447700900101@s.whatsapp.net`) read as the number it spells, a number entered without a country
   code read with `LOGBOOK_DIAL_PREFIX` as the adapters read it;
3. else the **name** as shown, its words folded and sorted (`Berg, Liv` and `Liv Berg` are one).

Never from the id a source gives one observation — a speaker id, a chat guid, a message id, a line
id. An address seen under three display names is one observed person with three names; a number
seen as `+447700900101` in one chat and as a JID in another is one. Keyed the other way, one person
explodes into a row per observation, and no queue survives that.

**The table.** Observed people are a derived table in the index, `observed_people` in
`index.sqlite`: one row per strongest identifier with the display names and the identifiers as the
lines wrote them, counts per source and per kind, the days seen, first and last seen, the tier of
the evidence, a few line ids as evidence, and the canonical person the row resolves to when one of
its identifiers has a resolution standing *as written* — the readers look a ref up as the line
carries it, so `Per.Hansen@example.org` on a calendar entry is not placed by a line for
`per.hansen@example.org` — or, for a name alone, when the people reader would place a speaker of
that name. The table is built from the standing `mail/v1`, `message/v1`, `transcript/v1` and
`event/v1` lines through the index, your own identities left out (`owner_id`, `owner_emails`,
`policy/owner.json` and their closure), stamped with the head it was built at, served while the
head stands and rebuilt when the record grows. Its shape is checked with `PRAGMA table_info`; a
table of another shape is built again, never read. Nothing is written to the record.

**The queue.** `logbook people review` proposes each observed person not yet placed against each
canonical person, ranked by the evidence, numbered from 1, one line each:

```
15 proposals · 17 observed people not yet placed, 36 placed · tier 2
   1  [80]  eva.nordmann@example.org (Eva Nordmann; event 1) → Eva Nordmann: same email eva.nordmann@example.org · same name Eva Nordmann
   3  [22]  +447700900115 (Astrid Bakke; message 3) → Astrid Bakke: same name Astrid Bakke · together on 1 day
  11  [22]  maren.eide@example.org (Maren Eide; mail 3) → Maren Eide: same name Maren Eide · together on 1 day
  15  [20]  M. Eide (transcript 1) → Maren Eide: same name M. Eide ~ Maren Eide
nothing written: `people review --accept N[,N]`, `--reject N[,N]`, or `--all-above SCORE`
```

The score is a plain sum of what speaks for the pair:

| Evidence | Points | What it means |
|---|---|---|
| same email | 60 | an identifier of the observed person is an address a canonical ref spells, case aside |
| same phone | 50 | the same E.164 number, by the rules above |
| same name | 20, +5 per further source up to +10 | a display name and the canonical label are one name by `people merge`'s rule: the same words in any order, or an initial for a first name; two words at least, never a word one letter off |
| together on the same days | 2 per day, up to 20 | both were seen on the day; days alone never propose |

A pair you rejected is never proposed again. An observed person with no identifier a resolution
line can carry (a spoken name alone, matching nobody exactly) is listed under `observed.unplaced`
in `--json` and proposed nothing: there is nothing to write for it; name the speaker with
`logbook add` instead. The numbers are the queue's at this head and change when the record does;
`--json` carries a stable `id` per pair beside them.

**Your say.** Nothing is promoted on its own; the owner decides, and only `Logbook.append` writes.

```bash
logbook people review --accept 1,3 --reject 11   # accept these, reject that; numbers from the listing
logbook people review --all-above 50            # accept every proposal at or above 50
logbook people review --json                    # the queue, the unplaced and the placed count
```

- `--accept N[,N]` writes, per identifier of the observed person as the lines wrote it, the line
  `people merge` writes: one `resolution/v1`, `source` `manual`, `method` `owner`, `alias_of` the
  canonical person's own ref (a phone before an address), the `logbook_head` the proposal was read
  against, the target's line and the observed lines as `evidence`, and under `extra` the proposal
  id, the entity, the score and what matched. The identifier, and every reader that looks it up,
  then resolves to the canonical person through the ordinary alias walk.
- `--reject N[,N]` writes one `people-review/v1` line (RFC 0035, `kind` `people-review`) saying the
  observed person and the canonical person are not the same: the strongest identifier as `ref`,
  the identifiers as written under `refs`, the display names, the entity, the same head and
  evidence. The pair never comes back; retract the line and it does.
- `--all-above SCORE` accepts every proposal at or above the score, a whole number.

Every number is checked before the first line is written; a number the queue does not have, a
number both accepted and rejected, or a score that is not a whole number exits 2 and writes nothing.
A second `people review` after accepting is shorter by what was accepted, numbered afresh, and the
`people` rows of the people already placed do not change: a review adds refs to a person, never a
person to the list.

## Priority

`logbook people --priority [--year YYYY] [--json]` ranks the canonical people heard in the last year
of the record (the 365 days ending on its last day, clipped to it; `--year` is that year) by a
score you can argue with, printed beside each name. The score is a sum, nothing more:

1. **3 per day together** in the window (the confirmed days of the with module, as `people` counts them).
2. **1 per message exchanged**, the smaller of the two directions (their lines to you, your lines to them in a direct chat), up to 50: a conversation, not a broadcast.
3. **2 per meeting**: a timed calendar entry they attended, a transcript they spoke in.
4. **10 when the last real contact** (a message either way, an answered call, a day together) is within 30 days of the window's end, **5** within 90, else 0.
5. Nothing else: no mail (a newsletter is a mail too), no faces, no model.

```
priority · 2025-06-22 – 2026-06-21 · 11 people
  47  Ola Nordmann  3 days together · messages 2 from them, 3 from you · meetings 2 · last real contact 2026-06-16
  10  Eva Nordmann  last real contact 2026-06-17
```

Under `--json`: `window` and `people`, each `id`, `name`, `score`, `days`, `messages` (`them`, `me`),
`meetings`, `last_real_contact` and `recency`. Nothing is written.

## The window

The whole record by default: the first to the last local day with a line of any kind, so a message
written before the tracker's first point is in. `--year` is that year, clipped to the record's days;
a year with none is `no people` (and `window: null` under `--json`).

## How it reads

Everything comes through `index.sqlite` and nothing sweeps the files. The resolution and retraction
lines are read whole (`Index.resolutions`, `Index.retractions`); your stays and nights come from the
index's own columns, no line read (`reading.owner_track`, the reader `places propose` uses); and the
lines of the six kinds above stream one kind at a time over the window (`Index.of_kind` with its day
bounds), each read once and kept only when it names someone — a year of messages is counted as it
streams and never held. A retracted line, and one another line of its kind `supersedes` (a calendar
entry edited since), counts for nothing.

## JSON

```json
{"window": {"since": "2026-06-01", "until": "2026-06-21"}, "tier": 2,
 "people": [{"id": "019c…", "name": "Ola Nordmann", "refs": [{"kind": "email", "value": "ola@example.org"}],
   "tier": 2, "birthday": "1985-03-12", "first_contact": "2026-06-09", "last_contact": "2026-06-16",
   "last_real_contact": {"day": "2026-06-16", "via": "meeting", "line": "019c…"},
   "channels": {"messages": {"lines": 5, "first": "2026-06-09", "last": "2026-06-14", "tier": 2, "last_line": "019c…"}},
   "days": 3, "nights": 2, "places": [{"where": "Office", "days": 1}], "lines": ["019c…"]}]}
```

`lines` are the ids of the shared days' evidence; a channel names its last line only, since a
year of messages is thousands. The page adds `page`, `window` and `shared_days`, each with `day`,
`stay`, `where`, `night`, `sources`, `reasons` and `lines`.
