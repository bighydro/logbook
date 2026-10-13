# RFC 0037 — Entities: orgs, ideas, places and assets reviewed like people

Status: draft · 2026-10-13 · comment period: two weeks

The record knows five kinds of thing that recur across its lines and that the owner wants a page for: a **person**, an **org** (a company invested in or passed on), a **place**, an **asset** (a boat, an aircraft, a car) and an **idea** (a thread that starts as a repository README, continues in Notion, is spoken of in transcripts, and is built or killed). People review (RFC 0035, `docs/people.md#review`) settled the mechanism for one of them: observed references resolve to a canonical entity under the owner's control; an unresolved proposal is not an identity; nothing is promoted on its own. This RFC generalises that mechanism to the other four, so that one review sitting (`review KIND`) and one page pattern serve all five, and adds the one thing the other kinds need that a person does not: a **status**, as lines, proposed by the dream and disposed by the owner.

Two payload profiles are proposed, `entity/v1` and `status/v1`, both new and neither one of the RFC 0031 freezes: their schemas may change while this RFC is a draft, and they become frozen only by RFC 0031's process. The envelope does not change: no spec version bump, no new conformance fixture, no ADR. The canonical person of RFC 0006 and RFC 0035 is not changed by a single line (§3).

## 1. Words

- An **entity** is a canonical thing of one **kind**, `person`, `org`, `place`, `asset` or `idea`, identified in this record by `{ type, id, registry }` as RFC 0006 mints them. It exists because a line names it.
- An **observed** entity is what one source saw, keyed by its **strongest identifier** for its kind (§4), and nobody chose it. It is a row of a derived table in the index, never a line.
- A **ref** is a source-native identifier, `{ kind, value }`, as RFC 0006 defines it. A ref **resolves** to an entity or to nothing.
- A **touch** is any standing line that resolves, through one of its refs, to the entity: a mail from its domain, a meeting with its people, a Notion page under its root, a stay in its circle, a position report of its hull.
- A **status** is the owner's disposition of an org or an idea at a point in time, one `status/v1` line; the current status is the last standing one.
- The **dream** is the nightly engine that drafts the Day, the digest's question and, with this RFC, status proposals. It writes no line of its own (RFC 0034: agents draft, the owner signs).

## 2. Why one mechanism

People review taught the rule that keeps a queue alive: derive an observed identity from the strongest identifier the observation carries, never from the id a source gives one observation, or one person explodes into a row per observation. The same rule applies to a company seen through four roads (its mail domain, its people's calendar invitations, the WhatsApp group with its name, the ledger line that paid it) and to an idea seen through four others (the README of a repository, the Notion page it grew into, the transcript where it was talked through, the task that said "write up the fjord kiosk"). Without a canonical entity, the Manifest shelf is a list of domains and the Ideas shelf a list of page titles. With one, each company and each idea is one thread, with every touch on it, the people in it, the documents that carry it, and what the owner decided about it, and why.

Places (`docs/places.md#review`) and assets (ADR 0018) already have registries, `places.json` and `assets.json`, and places already have a review. They join here so that the sitting is one sitting and the page is one page; their registries stay (§3.3, §3.4).

## 3. `entity/v1`: the canonical thing

### 3.1 Line

`kind` MUST be `entity`. `source` MUST be `manual`: an entity exists because the owner said so, through `review KIND --accept`, `--name`, or `logbook add`. `tier` MUST be the highest tier of the evidence it cites (SPEC §4), with the reasoning of §7. `at` is when the owner said so; `end` is null.

### 3.2 Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"entity/v1"` | MUST | |
| `entity` | object | MUST | `{ type, id, registry }`. `type` is one of `person`, `org`, `place`, `asset`, `idea`; `registry` MUST be `logbook`; `id` MUST be a UUIDv7 minted in this record, or the id the registry file already holds for a place or an asset (§3.3, §3.4). A private or interpreter namespace MUST NOT appear as a registry (ADR 0013.2) |
| `label` | string | MUST | the name, as the owner gave it or accepted it: `Nordmann Verft AS`, `the fjord kiosk` |
| `refs` | array of object | SHOULD | the identifiers this line binds to the entity, each `{ kind, value }` with `kind` one of RFC 0006's kinds (`email`, `phone`, `handle`, `provider_id`, `device_id`, `domain`, `line`) or one of the kinds this RFC adds: `repo` (`github.com/nordmann-verft/kiosk`, host and path, lower-cased), `page` (`notion:<page id>`), `title` (a title's words, folded and sorted, as RFC 0035's `name`), `group` (a chat's display name, folded), `merchant` (a ledger merchant string, folded), `mmsi`, `icao24`, `registration`, `place` (a name in `places.json`). A later line for the same entity adds refs; it never removes one (retract the line that bound it) |
| `aliases` | array of string | MAY | other spellings of the label, for the page's head and for matching: `Nordmann Verft`, `NV` |
| `keys` | object | MAY | the dedupe key of §8 as the writer computed it, for a reader without the table |
| `method` | string | MAY | `owner` |
| `evidence` | array of string | MAY | ids of the lines the entity was seen on when it was accepted |
| `supersedes` | string | MAY | the id of an earlier `entity/v1` line for the same entity this replaces (a relabel) |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |
| `extra` | object | MAY | what the kind needs and nothing else: an org's country or register number as the owner typed it; an idea's one-line pitch; nothing a line of the record already holds |

### 3.3 How the canonical person maps onto the general form

Nothing in RFC 0006, RFC 0035 or `docs/people.md` changes, and no line is rewritten:

| General form | The person today |
|---|---|
| an entity exists because a line names it | a person exists because a `resolution/v1` line names `{ type: "person", id, registry: "logbook" }` (RFC 0006, Minting) |
| its label is the `label` of the first standing line that names it | the same (`docs/people.md#who-is-a-person`) |
| its refs are every ref whose lookup ends at it | every ref whose alias walk (RFC 0006 rule 6) ends at a line naming it |
| `review person` | `people review`, unchanged, which it aliases (§5) |
| the owner's no | `people-review/v1` (RFC 0035), unchanged |
| its page | `person`, which gains the common sections of §6 without losing a row |

An `entity/v1` line for a person is never required and `review person` never writes one; a person minted by a resolution is an entity of kind `person` with no `entity/v1` line, and is complete. An owner MAY write one (`logbook add`) to give a person `aliases` or `extra`; its `refs` MUST be empty for a person, because a person's refs bind through `resolution/v1` and a second road would split the lookup (open question 1).

**Orgs and `company`.** RFC 0006 already allows `entity.type` `company` in a resolution line, and the profile is frozen, so the word stays. An org's email and domain refs bind through `resolution/v1` with `type` `company` and the org's id; a reader reads `company` in a resolution line and `org` in an `entity/v1` or `status/v1` line as the one kind `org`. Refs RFC 0006 cannot carry (`group`, `merchant`, `repo`) bind through the `entity/v1` line's `refs`.

**Places.** A place keeps its registry: `places.json` is the setting, read by every reader each run, and renaming a place changes no line (`docs/places.md`). Its entity id is the place's name, as the file spells it, under `registry` `logbook`; a place also gets no UUID because a `places.json` entry has none to carry. An `entity/v1` line for a place is written only when `review place --accept` runs after this RFC is adopted, beside the `note/v1` naming line it writes today, and carries `{ kind: "place", value: "<name>" }` and the stay lines as `evidence`; a place named before has no line and is complete. RFC 0006's place resolution (a stay to a `wikidata` or `osm` id) is unchanged and is a different statement: that the named place is a known public place.

**Assets.** An asset keeps its registry: `assets.json`, `{ id, kind, name, mmsi?, icao24?, registration? }` (ADR 0018). Its entity id is the registry's `id`. An `entity/v1` line for an asset binds the identifiers the registry already names as `refs` (`mmsi`, `icao24`, `registration`) so that a line naming the hull without the registry resolves to it; `logbook assets add` MAY write one. A `location/v1` line's `subject` is the asset's id and needs no resolution.

### 3.4 Rules

1. An `entity/v1` line never modifies a line it cites. Readers join by ref.
2. **One lookup, two profiles.** A ref resolves to the entity named by the last standing line that binds it, whichever profile bound it: a `resolution/v1` line by RFC 0006 rule 6 (the alias walk, at most four hops), or an `entity/v1` line whose `refs` carry it. A ref bound by both resolves by the later line; a writer refuses to bind a ref that already resolves to another entity and says so.
3. Retraction (RFC 0003) applies: a retracted `entity/v1` line binds nothing, and the refs it bound fall back to whatever other line binds them, or to nothing. Retracting the minting line of an entity with standing `status/v1` lines leaves them standing and the reader shows them under the id with the label the status line carries (§9.3).
4. Minting: the first `entity/v1` line for a new org or idea mints a UUIDv7 as `entity.id`. A `review KIND --accept` MUST look the dedupe key (§8) up before minting and MUST reuse the id when the key already resolves; the log is the registry, and there is no registry file for orgs or ideas.
5. Nothing requires the profile. A record with no `entity/v1` line is complete; its people are complete as RFC 0006 leaves them, and its places and assets as their files leave them.

## 4. Observed → canonical, per kind

The observed entities are a derived table in the index, `observed_entities` in `index.sqlite`, one row per `(kind, strongest identifier)`: the display names seen, the identifiers as the lines wrote them, counts per source and per line kind, the days seen, first and last seen, the tier of the evidence, a few line ids, and the canonical entity the row resolves to when one of its identifiers has a line standing *as written* (RFC 0035's rule: the readers look a ref up as the line carries it). It is built from the standing lines through the index, the owner's own identities left out, stamped with the head and with the digests of `places.json`, `assets.json` and `policy/entities.json` (§4.6), served while they stand, rebuilt when the record grows. Its shape is checked with `PRAGMA table_info`; a table of another shape is built again, never read. Nothing is written to the record. The `observed_people` and `observed_places` tables of today are the `person` and `place` partitions of this one, or stay as they are (open question 7).

The strongest-identifier rule holds for every kind: an observed entity's identity is derived from the strongest identifier the observation carries, in the order its kind gives, and never from the id a source gives one observation.

### 4.1 person

As RFC 0035 and `docs/people.md#review`: email, else phone in E.164, else the name's words folded and sorted. Evidence: `mail/v1`, `message/v1`, `transcript/v1`, `event/v1`. Unchanged.

### 4.2 org

Strongest identifier, in this order:

1. the **registered domain** (the public suffix plus one label: `nordmann-verft.example` from `post.nordmann-verft.example`), from a `mail/v1` `from`, `to`, `cc` or `bcc` address, or an `event/v1` attendee's email ref, lower-cased. A domain in the **public mail providers** list (§4.6) names nobody's org and is skipped: `example.org` is a family's provider in the synthetic record and tells nothing;
2. else the **GitHub org**: the first path segment of a `browse/v1` url on `github.com`, or of a link under a `task/v1`'s `extra.links`, lower-cased (`github.com/nordmann-verft`), when it is an organisation and not a user (the reader cannot tell; the owner decides at review);
3. else the **group name**: a `message/v1` whose `chat.type` is `group`, by `chat.name` folded (`nordmann verft board`); the group is the observation, the people in it are persons and are reviewed as such;
4. else the **merchant**: a `transaction/v1` `merchant` string, folded, when the same string recurs on three or more lines (a merchant seen once is noise; the threshold is a hypothesis).

The proposal: an observed org not yet placed against each canonical org, scored by what speaks for the pair, a plain sum as `people review`'s:

| Evidence | Points | What it means |
|---|---|---|
| same domain | 60 | a domain ref of the canonical org, or an email ref of one of its resolution lines, spells the registered domain |
| same GitHub org | 50 | a `repo` ref of the canonical org has the same first segment |
| same name | 20, +5 per further source up to +10 | the display name (a mail's `from.name`, a group's name, a merchant string, a repo's org) and the label or an alias are one name: the same words in any order, case, punctuation and the forms `AS`, `ASA`, `Ltd`, `Inc`, `GmbH`, `AB` aside; two words at least, or one word of six letters or more |
| the org's people | 10 per canonical person, up to 30 | a canonical person who resolves through this org's domain was seen on the observed lines (an attendee, a sender, a group member) |
| together on the same days | 2 per day, up to 20 | both were seen on the day; days alone never propose |

A domain alone, matching no canonical org, proposes a **new** org with the domain as its name and the names the sources gave it (`Nordmann Verft AS` from a signature's display name is not read: the body is never read; a display name of a `from` is), as `places review` proposes a blank with the names its sources gave.

### 4.3 idea

Strongest identifier, in this order:

1. the **Notion root page**: the `sync notion` `event/v1` line's page id, or the topmost of "the titles above it" when the integration can see that page, as `page` (`notion:<id>`). A page under a root is the root's idea unless the owner says otherwise; the lineage is the evidence and the sub-pages are the documents (§6);
2. else the **repository**: a `browse/v1` url, a `task/v1` link or a `sync drive` file name of the form `owner/name` on a code host, as `repo` (`github.com/nordmann-verft/kiosk`, lower-cased);
3. else the **title words**: a `task/v1` `title`, a `transcript/v1` `title`, or a Notion page title, folded and sorted, as `title`, when the same folded title recurs on two or more lines of two or more sources. A title seen once in one source is noise. A transcript's `summary` is never read for a topic: it is the provider's words about the owner's, and the owner names the idea.

The proposal, scored:

| Evidence | Points | What it means |
|---|---|---|
| same page | 60 | the observed page, or one above it, is a `page` ref of the canonical idea |
| same repo | 50 | the same `repo` ref |
| same title | 20, +5 per further source up to +10 | the folded title and the label or an alias are one name: the same words in any order, the articles `the`, `a`, `an` aside; one word of six letters or more suffices (`kiosk`) |
| the idea's people | 10 per canonical person, up to 30 | a canonical person who was on the idea's lines (a Notion actor, a transcript participant, a task's assignee) was seen on the observed lines |
| the same week | 5 per week, up to 20 | the observed title was seen in a week the idea was touched |

An idea is the owner's own and the dream never mints one: an observed page, repo or title with no canonical idea proposes a **new** idea named by its title, for the owner to accept, rename or reject. A spark that was never written anywhere is not in the record and is not proposed; `logbook add` names it.

### 4.4 place

As today (`docs/places.md#review`): the observed place is a cluster of stays within 75 m, ranked by nights then hours, named by what the sources already said (Timeline visits, calendar locations held during the stay, photo libraries, Dawarich). Nothing is looked up and no coordinate leaves the machine. The strongest identifier is the cluster's centre, rounded to the grid the table uses. `review place` is `setup places review` with this RFC's queue shape; the accept, name and reject semantics are the page's.

### 4.5 asset

An observed asset is one of:

1. a **subject** on a `location/v1` line (`subject` set) that `assets.json` does not name: a hull the receiver kept reporting after the owner removed it, or lines from another machine's registry;
2. an **aircraft registration** on a `flight/v1` line (`aircraft.registration`) seen on three or more flights, or on a `keeper/v1` boarding pass that names a tail; the owner's own aircraft flies its owner more than once, an airline's does not;
3. an **MMSI** or **callsign** named in the `extra` of an AIS report of a vessel that the registry does not know, when it recurs across days near the owner's own hull (a raft-up neighbour, a club boat).

Strongest identifier: `mmsi`, else `icao24`, else `registration`, else the `subject` id. The proposal matches on the same identifier (60), the same registration spelled two ways (`ZZ-ABC` and `ZZABC`, 50), or the same name on the report and in the registry (20). Accepting writes the asset into `assets.json` as `logbook assets add` does, and an `entity/v1` line binding the identifiers. Nothing is synced for a new asset until the owner asks (ADR 0018: the record records what was asked for).

### 4.6 `policy/entities.json`

One setting, read each run, never a line:

```json
{"public_mail_providers": ["gmail.com", "outlook.com", "hotmail.com", "icloud.com", "me.com", "proton.me", "yahoo.com", "example.org"],
 "merchant_min_lines": 3, "title_min_lines": 2, "code_hosts": ["github.com", "gitlab.com", "codeberg.org"]}
```

The provider list ships with a default a reader carries in code and the file extends; a domain of the owner's own (`owner_emails` in `logbook.json`, `policy/owner.json`) is never an org. The thresholds are hypotheses, as `policy/stays.json`'s constants are.

## 5. `review KIND`

One command, one shape, five kinds:

```bash
logbook review org                       # the queue: observed orgs not yet placed, ranked
logbook review idea --json               # the queue, the unplaced and the placed count
logbook review org --accept 1,3 --reject 11
logbook review idea --name 2 "the fjord kiosk"     # accept with the owner's own name
logbook review org --all-above 50
logbook review place                     # = setup places review (kept, with one line saying so)
logbook review person                    # = people review (kept)
logbook review asset
logbook review                           # every kind with a queue, one block each, nothing written
```

```
7 proposals · 9 observed orgs not yet placed, 4 placed · tier 2
   1  [80]  nordmann-verft.example (Nordmann Verft, Nordmann Verft AS; mail 12, calendar 3) → Nordmann Verft AS: same domain · same name Nordmann Verft AS · Ola Nordmann on both
   2  [25]  group "nordmann verft board" (message 41) → Nordmann Verft AS: same name · Ola Nordmann on both
   5  [new] fjordkiosk.example (Fjordkiosk; mail 2) → ____
nothing written: `review org --accept N[,N]`, `--name N "…"`, `--reject N[,N]`, or `--all-above SCORE`
```

The numbers are the queue's at this head and change when the record does; `--json` carries a stable `id` per pair, a digest of the two keys. Every number is checked before the first line is written; a number the queue does not have, a number both accepted and rejected, or a score that is not a whole number exits 2 and writes nothing. On a terminal the command asks `y`, `n`, a name, Enter to skip or `q` for each proposal shown, as `places review` does, and writes each answer at once.

What each answer writes:

| Kind | `--accept` / `--name` | `--reject` |
|---|---|---|
| person | the `resolution/v1` alias lines `people review` writes today | one `people-review/v1` line (RFC 0035) |
| org | one `entity/v1` line (minting when the key is new, §3.4 rule 4), binding the `group`, `merchant` and `repo` refs; one `resolution/v1` line per `domain` and `email` ref, `type` `company`, as RFC 0006 allows | one `entity-review/v1` line: RFC 0035's shape with `entity.type` `org` (open question 2) |
| idea | one `entity/v1` line binding the `page`, `repo` and `title` refs | one `entity-review/v1` line, `entity.type` `idea` |
| place | the `places.json` entry, the fitted radius and the `note/v1` naming line as today, and one `entity/v1` line (§3.3) | the pair in `state/places-review.json` as today (open question 3) |
| asset | the `assets.json` entry as `assets add` writes it, and one `entity/v1` line | one `entity-review/v1` line, `entity.type` `asset` |

A rejected pair is never proposed again; retract the line, or delete the state entry, and it returns. A `--name` on a proposal that matched a canonical entity is a relabel of nothing: it accepts the match and leaves the label; to rename an entity, `logbook add` an `entity/v1` line that `supersedes` the standing one.

Every write goes through `Logbook.append`, and the review reader opens no connection: no register of companies, no code host, no Notion is asked. The tests hold it to that with the network guard on.

## 6. The entity page

`logbook org NAME`, `logbook idea NAME`, `logbook person NAME` (today's), `logbook place NAME`, `logbook asset NAME`, each `[--year YYYY] [--json]`, and `logbook entity KIND NAME` for all of them. `NAME` is tried as a ref first (`kind:value`, a domain, a `+` number, a `notion:` id, an `owner/name` repo), then as an entity id, then as a label or alias (case aside), then as a word of a label (`kiosk` finds the fjord kiosk when no other idea is a kiosk); several or none is refused with exit 2 and the reason on stderr, as `person` does.

The page has the same sections for every kind, in this order, then the kind's own:

1. **Head**: the label, the refs in parentheses, the kind, the tier of the page (the highest tier of any line it rests on, SPEC §4; what the page shows past the crossing ceiling is governed by ADR 0016 as every reader is).
2. **Status line**: the current status, since when, who proposed it and the reason, from the last standing `status/v1` line (orgs and ideas; a place or asset has none and the row is left out).
3. **Timeline of every touch**: every standing line that resolves to the entity, most recent first, one row per local day with the source, the line kind and what it was (`mail from ola.nordmann@nordmann-verft.example "Q3 numbers"`, `edited notion "Kiosk / Pricing" +340 words`, `stay 6 h`, `position 59.90,10.75 (aisstream)`); under `--json` each row carries the line ids. The subject of a mail and the title of a page are what the line already holds; a body is never shown because it is never stored.
4. **People involved**: the canonical people on the entity's lines, most days first: attendees of its meetings, senders in its group, actors on its pages, splitters on its ledger lines, speakers of its transcripts; each with how many touches and the last one. An observed person not yet placed is counted (`and 3 not yet placed`), never named in a row.
5. **Documents as references**: the Notion pages (title, id, url), Drive files (name, id, link), repositories and mails (subject, date, the ids of the lines) that touch the entity, newest first, as references and never as copies: the record holds the title, the hash and the word count of a page, not the page.
6. **Status lines**: every `status/v1` line for the entity, oldest first, with its date, status, who proposed it, its reason and whether it stands; a retracted one is shown struck and said.

Then the kind's own: an **org** adds its domains and the ledger's net in and out by year within the ceiling (tier 3 lines are shown only when the page itself may show tier 3); an **idea** adds the words written by month (the sum of `sync notion`'s word deltas), the repositories and the days since its spark; a **place** adds its visits, nights and hours as `places review` counts them and the days together there; an **asset** adds its last known position and the days aboard, as `asset_status` and the with module derive them; a **person** keeps every row of `docs/people.md#the-person-page` and adds sections 3 and 5 (a person's documents are the pages and files they acted on).

## 7. Tiers

SPEC §4: derived data inherits the highest tier of its evidence, and a profile names the tier its producers write by default.

| Profile | Default tier | Reasoning |
|---|---|---|
| `entity/v1`, kind `org` | 2 | its evidence is mail (2), calendar (1), group names (2). It MUST NOT cite a `transaction/v1` line as `evidence`: a merchant match is written as a `merchant` ref, which is a folded string the ledger shows anyway, and the ledger involvement is derived by the page at read time within the ceiling. Citing the money line would lift every org to 3 and seal the Manifest shelf's names with age (RFC 0029) |
| `entity/v1`, kind `idea` | 2 | its label is the owner's own words, as `task/v1` and `note/v1` keep them at 2; its evidence is Notion events (1), tasks (2), transcripts (2, 3 where written at 3). A line citing a tier-3 transcript is 3, and the writer says so before writing |
| `entity/v1`, kind `place` | 1, 2 when it cites a note or a calendar entry with attendees | the stays are derived from `location/v1` (1); the `note/v1` naming line beside it is 2 by RFC 0010 and is a separate line. The name of a home is not more identifying than the home's coordinates in every tier-1 stay |
| `entity/v1`, kind `asset` | 1 | its evidence is position reports (1) and flights (1) |
| `entity/v1`, kind `person` | 2 | as `resolution/v1`: the highest tier of its evidence, 2 in practice |
| `status/v1`, kind `org` | 3, MUST | `hold`, `add`, `sell` and `exited` describe a position in money; `passed` and `let-go` are decisions (2). The envelope's `tier` is plain (SPEC §4), so a line at 2 among lines at 3 would say, without a key, which companies the owner passed on and which they hold. One tier for all six statuses gives that away to nobody; the cost is that the anti-portfolio seals with age like the portfolio, which is right |
| `status/v1`, kind `idea` | 2, MUST | a decision about one's own work; the reason is the owner's words |
| `entity-review/v1` | the highest tier of its evidence, 2 in practice | as RFC 0035 |

The page's tier is the highest of its lines; an org page that shows ledger lines is 3 and crosses nothing (RFC 0005, ADR 0016); the Manifest shelf without `--money` rests on tier 2 lines and is 2.

## 8. Dedupe keys

A key is what a writer looks up before minting, so a second review sitting, a second machine or a re-run never mints the same thing twice (ADR 0017's rule, applied to the owner's own writes). One key per kind, folded (NFKC, lower-cased, whitespace collapsed), computed by the writer and carried under `keys` for readers without the table:

| Kind | Key | Example |
|---|---|---|
| person | `email:<address>`, else `phone:<E.164>`, else `name:<words sorted>` (RFC 0035's order) | `email:ola.nordmann@example.org` |
| org | `domain:<registered domain>`, else `repo-org:<host>/<org>`, else `group:<folded name>`, else `merchant:<folded string>` | `domain:nordmann-verft.example` |
| idea | `page:notion:<root page id>`, else `repo:<host>/<owner>/<name>`, else `title:<words sorted, articles out>` | `repo:github.com/nordmann-verft/kiosk` |
| place | `place:<name as places.json spells it, folded>`; and a centre inside a named place's radius is that place already (`docs/places.md#the-fitted-radius`) | `place:hytta på banken` |
| asset | `mmsi:<n>`, else `icao24:<hex, lower>`, else `registration:<folded, hyphens out>`, else `subject:<id>` | `mmsi:970123456` |

A `review KIND --accept` whose key resolves already reuses that id and binds the new refs to it; `--name` on a new key mints. A `status/v1` line is one per `(entity, status, local day)`: the writer refuses a second status equal to the standing one on the same day, and a `status` equal to the standing one on a later day with a new `reason` is written (the owner reaffirmed, and said why). The `--json` of every reader carries the key beside the id.

## 9. `status/v1`: what the owner decided

### 9.1 Line

`kind` MUST be `status`. `source` MUST be `manual`: a status is the owner's disposition, never the dream's. `tier` as §7: 3 for an org, 2 for an idea, MUST. `at` is when the owner disposed; `end` is null.

### 9.2 Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"status/v1"` | MUST | |
| `entity` | object | MUST | `{ type, id, registry }`, `type` `org` or `idea` (a later amendment MAY add a kind with its dispositions; a place and an asset have none here) |
| `label` | string | SHOULD | the entity's label at the time, for reading the log without any table |
| `status` | string | MUST | one of the kind's dispositions, below; any other value makes the line invalid for its kind |
| `reason` | string | SHOULD; MUST for `passed`, `let-go` and `killed` | the owner's words on why. The anti-portfolio is this field: a passed company keeps its thread and its reason |
| `proposed_by` | string | MUST | `dream` when the owner disposed of a proposal the review made, `owner` when they set it unprompted |
| `proposal` | object | MAY | what the dream proposed, when `proposed_by` is `dream`: `{ status, score, because: [string] }`, so the record keeps the proposal even when the owner chose another status |
| `since` | date | MAY | the local day the status took effect when it is not the line's own day (an exit in June entered in October) |
| `evidence` | array of string | MAY | ids of the lines the proposal rested on |
| `supersedes` | string | MAY | the id of the standing status line this replaces |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |

### 9.3 Dispositions

For an **org**, six, written as these strings:

| Status | Meaning |
|---|---|
| `hold` | invested, and keeping the position as it is |
| `add` | invested, and adding to it |
| `sell` | invested, and reducing or looking to sell |
| `let-go` | the owner stopped following it, without an exit: written off, or no longer theirs to decide. `reason` MUST say |
| `exited` | the position is closed by an event: acquired, listed and sold, wound up |
| `passed` | the owner looked and did not invest. The anti-portfolio: the thread, the people, the documents and the reason stay, and the Manifest shelf shows it under its own heading. `reason` MUST say |

For an **idea**, five:

| Status | Meaning |
|---|---|
| `spark` | named, nothing done |
| `exploring` | being written up, talked through, prototyped |
| `build` | being built |
| `built` | done and standing; the idea's page is now its record |
| `killed` | stopped on purpose. `reason` MUST say; a killed idea keeps its thread, and may spark again |

There is no state machine: any status may follow any, because a record keeps what the owner decided and not what a diagram allows (`passed` then `hold` is a company the owner came back to, and the two lines say so). The current status is the last standing line's; a retracted status line counts for nothing and the one before it stands; an entity with no status line has none and its shelf row says `—`.

### 9.4 Proposed by the dream, disposed by the owner

The pattern is the signed day's (RFC 0034) and the goal review's: the engine proposes in a draft, the owner's answer is the line, and nothing is a line until the owner answers. The dream proposes a status when the record's own facts move:

| Kind | The dream proposes | Because |
|---|---|---|
| org | `exited` | a `transaction/v1` inflow from the org's merchant or a mail from its domain with no touch after it for 90 days, after a standing `hold`, `add` or `sell` |
| org | `let-go` | no touch for 365 days under a standing `hold`, `add` or `sell` |
| org | `passed` | a new org with meetings and mail in a window of 60 days, then no touch for 180, and no status line |
| idea | `exploring` | a `spark` whose page or repo is touched in three or more weeks |
| idea | `build` | an `exploring` idea whose repo is touched on ten or more days in a month |
| idea | `killed` | an `exploring` or `build` idea with no touch for 180 days |
| idea | `built` | never: only the owner knows what done is |

The proposals appear in `review org` and `review idea` under their own heading after the identity proposals, numbered on, with the because-list; `--status N hold --reason "…"` (or the terminal's prompt) writes the line with `proposed_by` `dream` and the proposal kept; `logbook status org "Nordmann Verft AS" passed --reason "…"` writes one unprompted with `proposed_by` `owner`. `--reject N` on a status proposal writes nothing and the proposal returns when the facts change; a status proposal has no standing no, because the facts that made it will change (open question 6). The thresholds are hypotheses in `policy/entities.json`, as §4.6.

## 10. The two shelves

Both are readers (ADR 0013), derived at the head every run, never written, in the terminal and as pages under `serve`.

**The Manifest shelf**, `logbook manifest [--year YYYY] [--money] [--json]`, is every canonical org, grouped by its current status, under four headings in this order: **holding** (`hold`, `add`, `sell`, with the status in the row), **exited**, **passed** (the anti-portfolio) and **let go**, then **no status**. Each row: the label, the status and since when, the last touch (what and when), how many people involved and the first two by days, how many documents, and the reason on a `passed` or `let-go` row, in full. With `--money`, and only on a terminal that may show tier 3, the ledger's net in and out for the year on each row. Within a heading, most recent touch first. Nothing is ranked by amount: the shelf is a list of decisions, and the passed companies are on it as fully as the held ones.

```
manifest · 6 orgs · to 2026-10-12 · tier 2
holding
  Nordmann Verft AS   hold since 2024-03-02 (owner) · last touch 2026-10-09 mail · 4 people (Ola Nordmann, Kari Nordmann) · 11 documents
passed
  Fjordkiosk AS       passed 2026-06-14 (dream proposed passed) · last touch 2026-05-02 meeting · 2 people · 1 document
                      reason: good team, but a kiosk is a place and I do not want to own places
```

**The Ideas shelf**, `logbook ideas [--year YYYY] [--json]`, is every canonical idea, grouped by status in the order `build`, `exploring`, `spark`, `built`, `killed`, then **no status**. Each row: the label, the status and since when, the last touch, the words written this year (the Notion deltas), the repositories, the people involved, the days since its spark, and the reason on a `killed` row. Within a heading, most recent touch first; a `killed` idea that sparked again is under its new status with its old reason one line below.

```
ideas · 4 · to 2026-10-12 · tier 2
exploring
  the fjord kiosk     exploring since 2026-09-20 (dream proposed) · last touch 2026-10-11 notion · +2,140 words this year · github.com/nordmann-verft/kiosk · 2 people (Ola Nordmann) · 54 days since spark
killed
  the tide clock      killed 2026-04-02 (owner) · reason: Garmin ships it
```

Under `serve`, the shelves are `/manifest` and `/ideas`, and an entity's page is `/org/<id>`, `/idea/<id>`, with the same sections as §6; the pages are rendered within the ceiling as every `serve` page is.

## 11. Examples (synthetic)

An org, minted at review:

```json
{"at":"2026-10-12T20:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity","tier":2,
 "payload":{"schema":"entity/v1","entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000201","registry":"logbook"},
 "label":"Nordmann Verft AS","aliases":["Nordmann Verft"],
 "refs":[{"kind":"group","value":"nordmann verft board"},{"kind":"repo","value":"github.com/nordmann-verft"}],
 "keys":{"org":"domain:nordmann-verft.example"},"method":"owner",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000001a1","019cadd3-6bc0-7dcd-9133-0000000001a2"],"logbook_head":"8f1c…"}}
```

Its domain, bound through RFC 0006 as the frozen profile allows, with the same id:

```json
{"at":"2026-10-12T20:14:01Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"domain","value":"nordmann-verft.example"},
 "entity":{"type":"company","id":"019cadd3-6bc0-7dcd-9133-000000000201","registry":"logbook"},"label":"Nordmann Verft AS","method":"owner"}}
```

An idea:

```json
{"at":"2026-09-20T21:02:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity","tier":2,
 "payload":{"schema":"entity/v1","entity":{"type":"idea","id":"019cadd3-6bc0-7dcd-9133-000000000301","registry":"logbook"},
 "label":"the fjord kiosk",
 "refs":[{"kind":"repo","value":"github.com/nordmann-verft/kiosk"},{"kind":"page","value":"notion:1f2e3d4c-0000-0000-0000-000000000031"},{"kind":"title","value":"fjord kiosk"}],
 "keys":{"idea":"repo:github.com/nordmann-verft/kiosk"},"method":"owner","extra":{"pitch":"a kiosk on the ferry quay that sells what the ferry forgot"}}}
```

A passed company, the dream's proposal kept beside the owner's word:

```json
{"at":"2026-06-14T19:40:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":3,
 "payload":{"schema":"status/v1","entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000202","registry":"logbook"},
 "label":"Fjordkiosk AS","status":"passed","reason":"good team, but a kiosk is a place and I do not want to own places",
 "proposed_by":"dream","proposal":{"status":"passed","score":40,"because":["3 meetings and 9 mails 2026-03-30 – 2026-05-02","no touch for 180 days","no status line"]},
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000001b1"],"logbook_head":"8f1c…"}}
```

An idea the owner moved on without being asked:

```json
{"at":"2026-10-11T22:05:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":2,
 "payload":{"schema":"status/v1","entity":{"type":"idea","id":"019cadd3-6bc0-7dcd-9133-000000000301","registry":"logbook"},
 "label":"the fjord kiosk","status":"exploring","proposed_by":"owner","reason":"pricing page written; talk to the ferry company first"}}
```

## 12. What this RFC does not change

- No line already in a record changes meaning. `resolution/v1` and `people-review/v1` are read as before; `people`, `person`, `people review`, `people merge` and `setup places review` keep their names and their output, each gaining an alias and, for the pages, sections.
- No adapter writes an `entity/v1` or `status/v1` line. Both are `source` `manual`.
- No network. The review reads the record and the three settings files; the pages read the record. Nothing asks a company register, a code host or Notion.
- The envelope (SPEC §2–3), the canonical JSON and the hashing are untouched.

## 13. Open questions

Listed, not solved; each is for the comment period.

1. **Two roads for a ref.** A person's refs bind through `resolution/v1` only, an org's through both profiles, an idea's through `entity/v1` only. Should `entity/v1` carry every ref of every kind and `resolution/v1` be left to persons and public places, so the lookup is one profile per kind? Or should this RFC propose `resolution/v2` with the wider `entity.type` and ref kinds, and `entity/v1` carry none?
2. **The no.** `entity-review/v1` is RFC 0035's shape with a wider `entity.type`. Should RFC 0035 be amended instead, so `people-review/v1` takes any type and the kind is in the line (`kind` `people-review` on an org is wrong, `entity-review` on a person is a rename of a draft)? One profile for every no, or one per kind?
3. **A place's no.** `places review --reject` keeps the pair in `state/places-review.json`, which a backup leaves out; `people review --reject` keeps it as a line. One of the two is wrong for a sitting that serves both. Which?
4. **Who is an org.** A GitHub user's repositories look like an org's; a family's shared mail domain looks like a company's; a merchant string is a brand, not the company that owns it. The owner decides at review, but the queue's ranking rests on the guess. Is a `kind` on the observed row (`company`, `brand`, `community`) worth its code, or is `org` wide enough?
5. **Ideas and the body.** The record keeps a Notion page's title, hash and word count and never its text (`sync notion`), so an idea's thread is titles and counts. Is that enough for the Ideas shelf to be useful, or does an idea need one `note/v1` of the owner's own words per status change, and should `status --reason` write one?
6. **A standing no on a status.** A status proposal rejected returns when the facts change, because the thresholds are hypotheses. Should an owner be able to say "never propose `let-go` for this org" as a line, or is a `hold` with a reason that no?
7. **One table or three.** `observed_people` and `observed_places` exist and are tested. Fold them into `observed_entities` with a `kind` column, or leave them and add `observed_entities` for the three new kinds?
8. **Ledger evidence.** §7 forbids an org's `entity/v1` line to cite a `transaction/v1` line so the org stays tier 2, and derives the money at read time. Is the evidence trail worth more than the tier, so that the owner can see why a merchant was matched?
9. **Dispositions as they age.** `hold` for an org never touched in three years and `exploring` for an idea untouched in two are stale. Should the shelf flag staleness (a reader's rule, no line), or should the dream propose more often?
10. **Status for places and assets.** A berth given up and a boat sold are statuses too (`let-go`, `exited`). Should `status/v1` take `place` and `asset` with those two, or is removing the entry from the registry file the whole statement, as ADR 0018 rule 4 reads today?
11. **The goal review.** This RFC mirrors a goal review that is not yet written down in this repository. Which RFC or page specifies it, and does `status/v1` fit a goal with `kept`, `missed`, `dropped`, `carried` (RFC 0034's four) as a sixth kind?
12. **The word.** `org` is the kind; `company` is the frozen word in `resolution/v1`; the shelf is the Manifest. Three words for one thing is two too many; which stay?
