# Export for Notion

`logbook export notion FOLDER [--since YYYY-MM-DD] [--include-unsigned] [--force] [--dry-run]` writes the
record's facts about your people, your ideas and the companies you deal with into one folder, for the
program that keeps your Notion workspace. It is a crossing like `export crossing` for Hermes
([the crossing](crossing.md), [ADR 0016](adr/0016-tier-crossing-policy.md)): the record writes a folder
and stops, and something else carries it.

```bash
logbook export notion ~/Handover/notion --dry-run      # count, write nothing
logbook export notion ~/Handover/notion                # the whole record, signed days only
logbook export notion ~/Handover/notion --since 2026-09-01
```

## Who carries it

Nobody, as far as this command is concerned. It asks Notion nothing, finds nothing on the Notion side and
creates nothing there: no page, no database, no property. It needs no Notion token and opens no
connection. Another program (the Purser) picks the folder up later and pushes it over its own signed
route to the program that writes the Notion pages; the machine that holds the record listens to nobody
and calls nobody. What is matched to what happens there, by the keys the folder gives:

| Section | Matched on |
|---|---|
| a person | their emails, phones and handles, as the record's resolution lines hold them |
| an idea | its Notion page id, `notion:<id>`, from the idea's `page` ref ([entities](entities.md)) |
| an org | its domain, from the org's `domain` ref |

Anything without such a key is left out of the folder and counted: a person known only by a provider
id, an idea with no Notion page, an org with no domain.

## The policy entry

Nothing leaves without the `notion` entry in `policy/crossing.json`:

```json
{"notion": {"max_tier": 2}}
```

A record whose file has no such entry is refused in one sentence that says what to add. The entry works
as every entry does: `max_tier` is the highest tier that may leave (tier 3 never leaves for Notion,
whatever it says), and an `until` date ends it: from the day after, nothing leaves until you write a new
date. The entry has no `write`: left out, it is the empty list, and it stays empty, since this
destination writes nothing back.

Only the lines of days you have signed (`logbook day sign`, [the signed day](signed-day.md)) inform a fact,
as in every crossing. To let the facts of unsigned days leave too, the entry must allow it and you must
ask for it, both:

```json
{"notion": {"max_tier": 2, "include_unsigned": true}}
```

```bash
logbook export notion ~/Handover/notion --include-unsigned
```

`--include-unsigned` without `"include_unsigned": true` in the entry is refused.

## The window

Every event rests on lines written in the window, from the start of `--since` (default: the record's
first day) to the moment the record is read, that pass the gate: a contact, a promise, an idea's status
entry, a touch. A calendar entry later today is no contact yet. An idea's current status is a state, not
an event: it is read from every status line the gate lets through, whatever its day, so a narrow window
never blanks it. A person's days together are a total in the same way: counted over their whole history
in the record, from its first day to the moment it is read, through the same gate, so a run over the last
week still says how many days you have spent together and since when. The lines that
bind a name to an address or a page, `resolution/v1` and `entity/v1`, come from any day and are held to
the ceiling and not to the signature, as a crossing package ships its resolution lines: Ola's email is
his whenever the record learned it. A line the record holds at tier 3 binds nothing here, and an earlier
line it replaced at a lower tier stands again for this export.

## What leaves

```
FOLDER/
  manifest.json   the envelope: what this run is, and the list of the other files with their digests
  persons.json    one object per person, emitted whole
  ideas.json      one object per idea with a Notion page
  orgs.json       one object per domain
```

**The envelope**, `manifest.json`: `export_id` (new each run), `as_of` (when the record was read),
`read_head` (the record's head when it was read), `policy` (the entry's name, `notion`, and its version:
the SHA-256 of its `max_tier`, `until` and `model`, as a dream draft records it), `signed_only` (true
unless `--include-unsigned`), the window of local days, the tiers, the counts per section, what was left
out and held back, and `files`: every other file with its SHA-256 and length.

**Persons.** Everyone the record names who had any contact with you in the window — a message, a call, a
mail, a calendar entry, a recording, a tagged photo or a day together ([people](people.md)) — never you.
Each: `id` (the record's person id), `identities` (`{kind, value}`, emails, phones and handles exactly as
the resolution lines hold them) and `facts`:

- `last_contact`: its `date` and `kind` (`together`, `call`, `message`, `transcript`, `event`, `mail` or
  `photo`; a day together names the day when it falls on the last one);
- `days_together`: the days you spent together over the whole record, not only the window, with
  `first_together` and `last_together`, the first and the last of them (`YYYY-MM-DD`); 0 and null when
  there are none;
- `promises`, open both ways ([promises](promises.md)): `owed_by_owner` and `owed_to_owner`, each
  `{sentence, date, line}`: the sentence as `logbook promises` quotes it (one sentence, its case kept,
  its whitespace collapsed), the day it was said, the line it was read in. Only a promise still open,
  said in the window and in the 365 days before the moment the record is read, and only from a
  conversation the person is a direct party to: a one-to-one chat with them, a mail you are both on
  that did not come through a mailing list, a call or a meeting they spoke in. A group chat, a mailing
  list, a meeting they were only invited to and a note are not; a quoted part of a mail (the lines after
  `On … wrote:` or `Am … schrieb …:`, and those that begin with `>`) is never read at all. The newest
  come first, at most ten a side; `promises_more` counts the rest of each side. The person's speaker and
  counterpart are resolved through the same gate.

And `page`: those facts as the lines of a page, in German, whole. The program that writes Notion replaces
a person's page with it and never merges:

```
Stand: 15.10.2026, aus dem Logbuch
Letzter Kontakt: 12.10.2026 (Nachricht)
Tage zusammen: 14 (zuerst 14.06.2019, zuletzt 10.09.2026)
Offene Versprechen von mir:
– „I will call the yard tomorrow.“ (12.10.2026)
Offene Versprechen an mich:
– „I'll send you the drawings by Friday.“ (11.10.2026)
…
und 3 weitere
```

With no day together there is no "Tage zusammen" line at all; with more than ten promises a side, the
side ends in one line, `und N weitere`.

**Ideas.** Every idea whose entity has a Notion page ref: `page` (`notion:<id>`), `status` (the current
status as the gate lets it be read, whatever its day, tier 2, with the day it took effect and its line;
none when the idea has none), `reason` (the note you wrote with that status, your words as written, and
its line),
and `entries`: one per status line written in the window, an earlier one that a later status replaced
included, dated the day it took effect, in German, for the writer to append once each by its `id`:

```
20.09.2026 — Status: in Erkundung (exploring). Begründung: „pricing page written; talk to the ferry company first“
```

**Orgs.** Every org with a domain that a mail or a calendar entry in the window touched through it:
`domain` (the registered domain, as the record keys an org: `nordmann-verft.example.org` for an org bound
to `post.nordmann-verft.example.org`), the days it was `touched`, the `last_touch`, and an entry per day
(`02.09.2026 — Kontakt.`).

Every German word is a fixed template in the code; no model writes or rewrites anything. Your own words
(a status reason, a note) are quoted as the record holds them, never paraphrased.

## What never leaves

- A line above the entry's `max_tier`, and any tier-3 line, whatever the entry says. A fact that rests
  on one is not in the folder: a person known only through a tier-3 resolution line is nobody here.
- The facts of an unsigned day, unless the entry and the flag both say so.
- An org's status, its reason, a portfolio tag, and money: an org's status is tier 3 ([entities](entities.md),
  RFC 0037 §8) and is never read by this command; the ledger is never read. Companies reach the family as
  a printed export, never through Notion.
- A sentence that names money: a promise or a reason that holds a currency sign, code or word (`450
  NOK`, `2 MNOK`, `€ 12`, `kroner`, `quid`), a Norwegian price (`300,-`) or a figure with a magnitude
  (`250k`, `5 mill`) is left out and counted. A promise that talks of money without a figure is left
  out and counted the same way: one about a payment, an invoice, a transfer or a price, in German or
  English (`Zahlung`, `zahlen`, `Rechnung`, `Überweisung`, `überweisen`, `Preis`, `Geld`, `Kosten`,
  `invoice`, `payment`, `pay`, `transfer`, `wire`, `price`, `money`, `cost`, in the forms a sentence
  gives them: "Ich überweise dir das morgen", "send me the invoice"). The words are one list in the code
  (`notion_export.MONEY_WORDS`). The filter errs towards leaving a sentence out: money stays out of
  Notion.
- The text of a message, a mail or a recording, beyond the one sentence a promise quotes; a mail's
  subject; a page's title; a person's name.

## The folder

The folder is built from nothing beside FOLDER and replaces it whole, as a crossing package does
([the output directory](crossing.md#the-output-directory)): a second run leaves nothing of the first. A
FOLDER that holds anything but an earlier export of this command is refused before anything is read,
unless `--force`; the record itself, and any folder in it outside `export/`, are refused whatever the
flags.

## The line

Every real run appends one `crossing/v1` line ([RFC 0011](https://github.com/bighydro/logbook/blob/main/rfcs/0011-crossing-v1.md)),
destination `notion`: the window, the tiers, the entry in force (`max_tier`, `signed_only` and its
version), the head the facts were read at, the SHA-256 of `manifest.json`, which names every other file's,
and `counts` in the shape every crossing line has: the lines read through the gate (`logged`), those it
let through (`crossed`, by tier and kind), those it held back, and the resolution and entity lines it
bound names through (`resolutions`). The folder carries facts read off those lines, never the lines; the
sections' own counts and what was left out are under `extra.notion`. It is the only thing the command writes to the record, and the run holds the writer lock from
the read to the append, so the line follows the head the folder reflects. A dry run appends nothing.

## The dry run

`--dry-run` reads the record through the same gate and prints the counts per section, what was left out
for want of a key or for naming money, and how many lines the gate held back above the tier or on
unsigned days. It writes nothing: no folder, no line.
