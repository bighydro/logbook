# People

`logbook people [--year YYYY] [--json]` is everyone the record knows and what it knows of each;
`logbook person <name-or-ref> [--year YYYY] [--json]` is one of them on one page, with the timeline
of the days you spent together. Both are readers (ADR 0013): derived from the record at its head,
every time, and never written. The owner is never listed: the record is yours, and you are not
your own company.

```bash
logbook people                          # everyone with evidence in the record, most days together first
logbook people --year 2026              # one year
logbook people --json                   # the report as one JSON object
logbook person "Ola Nordmann"           # a label; a unique first or last name does too: `person Ola`
logbook person ola@example.org          # an address the resolution lines know
logbook person +447700900001            # a phone number
logbook person provider_id:immich:f_01  # any ref as kind:value; the entity id works too
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
