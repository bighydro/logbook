# Review: what the sources saw

Your sources see more than you have named. A mail domain recurs, a group chat is about a company, a
Notion page grows into a project, the receiver reports a hull the registry no longer names. `logbook
review` is one sitting for all of it (RFC 0037): for each of the five kinds of thing the record names,
what the sources observed and the record has not placed, proposed against what you named, with the
evidence, numbered. Nothing is written unless you say so, and nothing is looked up: no register of
companies, no code host, no Notion, no geocoder.

```bash
logbook review                       # every kind with its queue, one block each; nothing written
logbook review org                   # the queue of one kind: person, org, idea, asset or place
logbook review org --accept 1 --name 3 "Fjordkiosk AS" --reject 4
logbook review idea --json           # the queue, the unplaced and the placed count, as JSON
logbook review asset --all-above 50  # accept every proposal at or above the score
```

`review person` is [`people review`](people.md#review) and `review place` is
[`setup places review`](places.md#review): the same sitting, the same numbers, the same output byte
for byte, under one name.

## The five queues

An observed thing's identity is the **strongest identifier** its observation carries, never the id a
source gives one observation; keyed the other way, one company explodes into a row per mail.

| Kind | Observed by, strongest first | Proposed against |
|---|---|---|
| person | an email address, a phone number, the name's words folded ([people](people.md#review)) | the people the resolutions name |
| org | the **registered domain** of a mail or calendar address (a public mail provider and your own domains name nobody's org); a code-host org of a url or a task's link; a group chat's name; a ledger merchant seen on 3 lines or more | the orgs: `entity/v1` lines, and `resolution/v1` lines of type `company` read as orgs |
| idea | a Notion page's root (a page under it is the root's idea); a code-host repository; a task's or a transcript's title on 2 lines of 2 sources or more | the ideas the `entity/v1` lines name |
| asset | a track's subject the registry does not name (its MMSI or icao24 when the instrument said); an aircraft registration on 3 flights or more | the assets of `assets.json` |
| place | a cluster of your stays within 75 m ([places](places.md#review)) | the names the sources gave it |

The score is a plain sum of what speaks for a pair, as `people review`'s is:

| Kind | Evidence | Points |
|---|---|---|
| org | the same domain · the same code-host org · the same name (the words in any order, `AS`, `ASA`, `Ltd`, `Inc`, `GmbH`, `AB` aside; two words, or one of six letters) · the org's people on its lines · the same days | 60 · 50 · 20, +5 a further source up to +10 · 10 a person up to 30 · 2 a day up to 20 |
| idea | the same page · the same repository · the same title (the articles aside) · its people · the same weeks | 60 · 50 · 20, +5 … · 10 … · 5 a week up to 20 |
| asset | the same identifier · the same registration spelled another way (`ZZ-ABC`, `ZZABC`) · the same name | 60 · 50 · 20 |

Days, weeks and people alone never propose. A domain, a code-host org, a page, a repository or a
title that matches nothing, and an asset the registry does not know, is proposed as a **new** one,
after the matches; a group chat and a merchant are only ever proposed against an org you have. Among
equal scores an org's **hint** decides — `company` (a domain), `community` (a code-host org, a group),
`brand` (a merchant), `personal` (a family's domain: every name on it shares the surname the domain
spells) — for ranking only; the hint is never written to a line.

```
$ logbook review org
4 proposals · 5 observed orgs not yet placed, 1 placed · tier 2
  1  [34]  group "nordmann verft" (Nordmann Verft; message 3) → Nordmann Verft AS: same name Nordmann Verft ~ Nordmann Verft AS · 1 person on both · together on 2 days
  2  [25]  git.example.org/nordmann-verft (nordmann-verft; browse 1, task 1) → Nordmann Verft AS: same name nordmann-verft ~ Nordmann Verft AS across chrome, gtasks
  3  [new]  fjordkiosk.example.org (Fjordkiosk; mail 2) → ____
  4  [new]  nordmann.example.org (Kari Nordmann, Per Nordmann; mail 2) → ____
nothing written: `review org --accept N[,N]`, `--name N "…"`, `--reject N[,N]`, or `--all-above SCORE`
```

```
$ logbook review asset
2 proposals · 2 observed assets not yet placed, 0 placed · tier 2
  1  [50]  ZZ-ABC (flight 3) → Lerka: same registration ZZ-ABC ~ ZZABC
  2  [new]  970123456 (GAMLE SOLVIND; location 3) → ____
```

## Your say

| Kind | `--accept` / `--name` | `--reject` |
|---|---|---|
| person | the `resolution/v1` alias lines `people merge` writes | one `entity-review/v1` line, type person |
| org | one `entity/v1` line binding the observed identifiers (a domain, a code-host org, a group, a merchant); a new org's id a UUIDv7, minted after its dedupe key is looked up, so a key that resolves already reuses its id | one `entity-review/v1` line, type org |
| idea | one `entity/v1` line binding the page, the repository or the title | one `entity-review/v1` line, type idea |
| asset | a new one registered in `assets.json` as `setup assets add` writes it, under the id its lines carry; one `entity/v1` line binding its identifiers | one `entity-review/v1` line, type asset |
| place | the `places.json` entry with its fitted radius, and the naming as one `note/v1` line | one `entity-review/v1` line, type place, the spot's centre and the name |

`--name N "…"` accepts a new one under your own name; on a proposal that matched an entity you
have, it is refused (accept the match; a rename is an `entity/v1` line that supersedes the standing
one). A rejected pair is never proposed again; retract the line and it returns. An `entity/v1` line
is tier 2 and never cites a tier-3 line, so a merchant matched from the ledger is bound as a
`merchant` ref and the payments are not its evidence; an `entity-review/v1` line that cites them is
tier 3. The profiles are on [their own page](entities.md).

Every number is checked before the first line is written: a number the queue does not have, a
number both accepted and rejected, a score that is not a whole number, or an option of another kind
exits 2 and writes nothing. On a terminal, an org's, an idea's, an asset's and a place's queue asks
for each proposal: `y`, `n`, a name for a new one, Enter to skip, `q` to stop; each answer is written
at once.

## The table

What the sources saw is one derived table in the index, `observed_entities` in `index.sqlite`: a row
per observed person, org, idea, asset and place, keyed by the kind and its strongest identifier, with
the names seen, the identifiers as the lines wrote them, counts per source and per line kind, the days,
first and last seen, the tier of the evidence, a few line ids, the canonical people seen on its lines,
the org's hint and the canonical entity it resolves to. It is stamped per kind with the head and the
settings it was built under, served while they stand and built again when they move; its shape is
checked with `PRAGMA table_info`. `observed_people` and `observed_places`, the tables people review and
places review read until 0.7, are views over it for one release. Nothing of it is in the record.

## What happened to a place's no

Until 0.7 a place you rejected was kept in `state/places-review.json`, never as a line, and a backup
left it out. It is a line now (RFC 0037, decision 3): `setup places review --reject`, `review place
--reject` and the Places page of `logbook serve` each write one `entity-review/v1` line of type place,
and the file is a cache rebuilt from the lines, never the truth. The pairs the file held from before
still count; `setup places review --migrate-rejects` (or `review place --migrate-rejects`) writes each
once as an `entity-review/v1` line, at the moment you said it, and a second run writes nothing. Until
you run it, `review` says how many pairs are not lines yet.
