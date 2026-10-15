# RFC 0037 — Entities: orgs, ideas, places and assets reviewed like people

Status: draft · 2026-10-13 · comment period closed 2026-10-14: the owner decided its twelve questions, and each decision is in the body (§16, [Decided](#16-decided)) · amended 2026-10-14: an org's status reason stays on its tier-3 line, never a `note/v1` (§8, §10.2, §10.5) · amends RFC 0035 (its amendment 1) and ADR 0018 rule 4

The record knows five kinds of thing that recur across its lines and that the owner wants a page for: a **person**, an **org** (a company invested in or passed on, a club, a brand), a **place**, an **asset** (a boat, an aircraft, a car) and an **idea** (a thread that starts as a repository README, continues in Notion, is spoken of in transcripts, and is built or killed). People review (RFC 0035, `docs/people.md#review`) settled the mechanism for one of them: observed references resolve to a canonical entity under the owner's control; an unresolved proposal is not an identity; nothing is promoted on its own. This RFC generalises that mechanism to the other four, so that one review sitting (`review KIND`) and one page pattern serve all five, and adds the one thing the other four need that a person does not: a **status**, as lines, proposed by the dream and disposed by the owner. A person has no status. A goal is not an entity and has its own verdict, RFC 0036's `review/v1`; a promise has RFC 0034's dispositions (§12).

Three payload profiles are proposed, `entity/v1`, `entity-review/v1` and `status/v1`, all new and none of them one of the RFC 0031 freezes: their schemas may change while this RFC is a draft, and they become frozen only by RFC 0031's process. The envelope does not change: no spec version bump, no new conformance fixture, no new ADR. There is **one road per kind**: a person binds through `resolution/v1` (RFC 0006, frozen), and nothing about the canonical person of RFC 0006 and RFC 0035 changes; an org, an idea, a place and an asset bind through `entity/v1` only (§3.3). The owner's no, for every kind, is one profile, `entity-review/v1` (§6). This RFC amends two documents in place, each with a dated section and no rewrite: RFC 0035, whose no is written as `entity-review/v1` from now on ([its amendment 1](https://github.com/bighydro/logbook/blob/main/rfcs/0035-people-review-v1.md#amendment-1--the-no-is-entity-reviewv1)), and ADR 0018 rule 4, whose registry entries are never deleted and are closed by a status line ([the amendment](https://github.com/bighydro/logbook/blob/main/docs/adr/0018-assets-are-subjects.md)).

RFC 0036 (goals, reviews, drafts and chapters) merged while this RFC was in comment, and this RFC was written before it. It is cited by number wherever this RFC speaks of a draft, a review or a writer: what the dream writes is a `draft/v1` line (RFC 0036), and a draft is a proposal, never a fact; a goal's verdict is a `review/v1` line (RFC 0036), which `status/v1` is not; and the writers of §5 and §10 hold the writer lock as `day sign` does (RFC 0034 amendment 3), as RFC 0036 amendment 1 (open at this writing, #269) has its goal, review and chapter writers do.

## 1. Words

- An **entity** is a canonical thing of one **kind**, `person`, `org`, `place`, `asset` or `idea`, identified in this record by `{ type, id, registry }` as RFC 0006 mints them. It exists because a line names it: a `resolution/v1` line for a person, an `entity/v1` line for the other four (or, for an org, a `company` resolution line of RFC 0006 written before this RFC, §3.3).
- An **observed** entity is what one source saw, keyed by its **strongest identifier** for its kind (§4), and nobody chose it. It is a row of a derived table in the index, never a line.
- A **ref** is a source-native identifier, `{ kind, value }`, as RFC 0006 defines it. A ref **resolves** to an entity or to nothing.
- A **touch** is any standing line that resolves, through one of its refs, to the entity: a mail from its domain, a meeting with its people, a Notion page under its root, a stay in its circle, a position report of its hull.
- A **status** is the owner's disposition of an org, an idea, a place or an asset at a point in time, one `status/v1` line; the current status is the last standing one. A person has none; a goal's verdict is RFC 0036's `review/v1`.
- The **dream** is `logbook dream` (`docs/dream.md`): each morning a model reads yesterday and writes one `draft/v1` line about it (RFC 0036), and nothing else. With this RFC the dream's run also evaluates the status rules of §10.4 against the head, and the review shows what they propose; a proposal is never a line, and the owner's answer is (RFC 0034: agents draft, the owner signs; RFC 0036: a draft is a proposal until the owner confirms it through an act of their own).

## 2. Why one mechanism

People review taught the rule that keeps a queue alive: derive an observed identity from the strongest identifier the observation carries, never from the id a source gives one observation, or one person explodes into a row per observation. The same rule applies to a company seen through four roads (its mail domain, its people's calendar invitations, the WhatsApp group with its name, the ledger line that paid it) and to an idea seen through four others (the README of a repository, the Notion page it grew into, the transcript where it was talked through, the task that said "write up the fjord kiosk"). Without a canonical entity, the Manifest shelf is a list of domains and the Ideas shelf a list of page titles. With one, each company and each idea is one thread, with every touch on it, the people in it, the documents that carry it, and what the owner decided about it, and why.

Places (`docs/places.md#review`) and assets (ADR 0018) already have registries, `places.json` and `assets.json`, and places already have a review. They join here so that the sitting is one sitting, the no is one line and the page is one page; their registries stay (§3.3), and a place given up or a boat sold is a status, never a deleted entry (§10.3).

## 3. `entity/v1`: the canonical thing

### 3.1 Line

`kind` MUST be `entity`. `source` MUST be `manual`: an entity exists because the owner said so, through `review KIND --accept` or `--name`, `setup places review`, `setup assets add`, or `logbook add`. `tier` is the highest tier of the evidence it cites (SPEC §4), and is never 3: an `entity/v1` line MUST NOT cite a tier-3 line (§8). `at` is when the owner said so; `end` is null.

### 3.2 Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"entity/v1"` | MUST | |
| `entity` | object | MUST | `{ type, id, registry }`. `type` is one of `org`, `place`, `asset`, `idea`, never `person` (§3.3); `registry` MUST be `logbook`; `id` MUST be a UUIDv7 minted in this record (§3.4 rule 4), or the id the registry file already holds for a place or an asset (§3.3). A private or interpreter namespace MUST NOT appear as a registry (ADR 0013.2) |
| `label` | string | MUST | the name, as the owner gave it or accepted it: `Nordmann Verft AS`, `the fjord kiosk` |
| `refs` | array of object | SHOULD | the identifiers this line binds to the entity, each `{ kind, value }`, of the kinds the entity's type takes (below). A later line for the same entity adds refs; it never removes one (retract the line that bound it) |
| `aliases` | array of string | MAY | other spellings of the label, for the page's head and for matching: `Nordmann Verft`, `NV` |
| `keys` | object | MAY | the dedupe key of §9 as the writer computed it, for a reader without the table |
| `method` | string | MAY | `owner` |
| `evidence` | array of string | MAY | ids of the lines the entity was seen on when it was accepted; never a tier-3 line |
| `supersedes` | string | MAY | the id of an earlier `entity/v1` line for the same entity this replaces (a relabel) |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |
| `extra` | object | MAY | what the kind needs and nothing else: an org's country or register number as the owner typed it; an idea's one-line pitch; nothing a line of the record already holds |

The ref kinds each type takes. `domain` is RFC 0006's; the others are this RFC's, each lower-cased and folded as given:

| `entity.type` | `refs[].kind` |
|---|---|
| `org` | `domain` (the registered domain, §4.2), `repo` (a code host and an organisation, `github.com/nordmann-verft`), `group` (a chat's display name, folded), `merchant` (a ledger merchant string, folded) |
| `idea` | `page` (`notion:<page id>`), `repo` (a host, an owner and a name, `github.com/nordmann-verft/kiosk`), `title` (a title's words, folded and sorted, as RFC 0035's `name`) |
| `place` | `place` (the name as `places.json` spells it) |
| `asset` | `mmsi`, `icao24`, `registration` |

An address is never an org's ref: an `email` ref is a person's, through `resolution/v1`, and an address's org is found by its registered domain. A ref of a kind its type does not take makes the line invalid.

### 3.3 One road per kind

Each kind binds its refs through exactly one profile, and a reader looks a ref up through that profile alone:

| Kind | Binds through | Notes |
|---|---|---|
| person | `resolution/v1` (RFC 0006, frozen) | the alias walk of RFC 0006 rule 6, at most four hops; unchanged |
| org | `entity/v1` | and, read and never written, the `company` resolution lines of RFC 0006 (below) |
| idea | `entity/v1` | |
| place | `entity/v1` | beside `places.json`, the setting |
| asset | `entity/v1` | beside `assets.json`, the setting |

There is no `resolution/v2`, and no profile takes a second road. An `entity/v1` line never names a person, and no writer of this RFC writes a `resolution/v1` line for anything but a person.

**The person.** Nothing in RFC 0006 or in how `docs/people.md` resolves a person changes, and no line is rewritten; the one change is the profile of the owner's no (RFC 0035 amendment 1):

| General form | The person today |
|---|---|
| an entity exists because a line names it | a person exists because a `resolution/v1` line names `{ type: "person", id, registry: "logbook" }` (RFC 0006, Minting) |
| its label is the `label` of the first standing line that names it | the same (`docs/people.md#who-is-a-person`) |
| its refs are every ref whose lookup ends at it | every ref whose alias walk (RFC 0006 rule 6) ends at a line naming it |
| `review person` | `people review`, which it aliases (§5); only the line its `--reject` writes changes |
| the owner's no | `entity-review/v1`, `type` `person` (§6), which `people review` writes from now on; the `people-review/v1` lines already written are read forever (RFC 0035 amendment 1) |
| its page | `logbook people NAME`, which gains the common sections of §7 without losing a row |
| its status | none: a person is not disposed of |

A person minted by a resolution is complete. Its other spellings are the labels of its resolution lines, as `docs/people.md` reads them; there is no `entity/v1` line for a person to carry them.

**Orgs and `company`.** RFC 0006 allows `entity.type` `company` in a resolution line, and the profile is frozen, so the value stays where it was written. A standing `resolution/v1` line whose `entity.type` is `company` is read as an org: its `entity.id` is the org's id, its `label` a label of the org, and the ref it binds resolves to the org as if an `entity/v1` line of the same `at` bound it. No such line is rewritten (SPEC §3), and no writer writes a new one: an org's domains, repositories, groups and merchants are bound by its `entity/v1` line's `refs`. A record whose only line for an org is a `company` resolution has an org with no `entity/v1` line, and it is complete; the first `review org --accept` that matches it writes an `entity/v1` line with the same id (§3.4 rule 4). `company` is a legacy value, read as `org` and never written, and `org` is the kind's one word (§16, question 12).

**Places.** A place keeps its registry: `places.json` is the setting, read by every reader each run, and renaming a place changes no line (`docs/places.md`). Its entity id is the place's name, as the file spells it, under `registry` `logbook`; a place gets no UUID because a `places.json` entry has none to carry. An `entity/v1` line for a place is written when `setup places review --accept` (or `review place --accept`) runs after this RFC is adopted, beside the `note/v1` naming line it writes today, and carries `{ kind: "place", value: "<name>" }` and the stay lines as `evidence`; a place named before has no line and is complete. RFC 0006's place resolution, a stay to a `wikidata` or `osm` id, is unchanged and is a different statement: that the named place is a known public place. It binds no canonical place.

**Assets.** An asset keeps its registry: `assets.json`, `{ id, kind, name, mmsi?, icao24?, registration? }` (ADR 0018). Its entity id is the registry's `id`. An `entity/v1` line for an asset binds the identifiers the registry already names as `refs` (`mmsi`, `icao24`, `registration`), so that a line naming the hull without the registry resolves to it; `setup assets add` writes one. A `location/v1` line's `subject` is the asset's id and needs no resolution.

A registry entry, of either file, is never deleted: a place given up or an asset sold or let go is closed by a `status/v1` line with `until` (§10.3; ADR 0018 rule 4, as amended).

### 3.4 Rules

1. An `entity/v1` line never modifies a line it cites. Readers join by ref.
2. **One road.** A ref resolves to at most one person, through `resolution/v1`, and to at most one entity of each other kind, through the last standing `entity/v1` line of that kind that binds it (and, for an org, the `company` resolution lines read as §3.3 says; a ref bound by both resolves by the later line). A writer refuses to bind a ref that already resolves to another entity of the same kind, and says which.
3. Retraction (RFC 0003) applies: a retracted `entity/v1` line binds nothing, and the refs it bound fall back to whatever other line binds them, or to nothing. Retracting the minting line of an entity with standing `status/v1` lines leaves them standing, and the reader shows them under the id with the label the status line carries (§10.2).
4. **Minting.** The first `entity/v1` line for a new org or idea mints a UUIDv7 as `entity.id`. A `review KIND --accept` MUST look the dedupe key (§9) up before minting, in the `entity/v1` lines and, for an org, in the `company` resolution lines, and MUST reuse the id when the key already resolves; the log is the registry, and there is no registry file for orgs or ideas.
5. Nothing requires the profile. A record with no `entity/v1` line is complete; its people are complete as RFC 0006 leaves them, its orgs as their `company` resolutions leave them, and its places and assets as their files leave them.

## 4. Observed → canonical, per kind

The observed entities are one derived table in the index, `observed_entities` in `index.sqlite`, with a `kind` column (`person`, `org`, `idea`, `place`, `asset`) and one row per `(kind, strongest identifier)`: the display names seen, the identifiers as the lines wrote them, counts per source and per line kind, the days seen, first and last seen, the tier of the evidence, a few line ids, for an org the `hint` (§4.2), and the canonical entity the row resolves to when one of its identifiers has a line standing *as written* (RFC 0035's rule: the readers look a ref up as the line carries it). It is built from the standing lines through the index, the owner's own identities left out, stamped with the head and with the digests of `places.json`, `assets.json`, `policy/stays.json` and `policy/entities.json` (§4.6), served while they stand, rebuilt when the record grows. Its shape is checked with `PRAGMA table_info`; a table of another shape is built again, never read. Nothing is written to the record.

`observed_people` and `observed_places`, the tables of today, become **views** over `observed_entities` (`kind = 'person'`, `kind = 'place'`) with the columns they have now, for one release, so a reader or a test of today reads them unchanged; the release after drops them, and its changelog says so. A view's shape is checked as a table's is.

The strongest-identifier rule holds for every kind: an observed entity's identity is derived from the strongest identifier the observation carries, in the order its kind gives, and never from the id a source gives one observation.

### 4.1 person

As RFC 0035 and `docs/people.md#review`: email, else phone in E.164, else the name's words folded and sorted. Evidence: `mail/v1`, `message/v1`, `transcript/v1`, `event/v1`. Unchanged.

### 4.2 org

Strongest identifier, in this order:

1. the **registered domain** (the public suffix plus one label: `nordmann-verft.example` from `post.nordmann-verft.example`), from a `mail/v1` `from`, `to`, `cc` or `bcc` address, or an `event/v1` attendee's email ref, lower-cased. A domain in the **public mail providers** list (§4.6) names nobody's org and is skipped: `example.org` is a family's provider in the synthetic record and tells nothing;
2. else the **GitHub org**: the first path segment of a `browse/v1` url on `github.com`, or of a link under a `task/v1`'s `extra.links`, lower-cased (`github.com/nordmann-verft`); whether it is an organisation or a user's own account the reader cannot always tell, and the hint says what it guesses;
3. else the **group name**: a `message/v1` whose `chat.type` is `group`, by `chat.name` folded (`nordmann verft board`); the group is the observation, the people in it are persons and are reviewed as such;
4. else the **merchant**: a `transaction/v1` `merchant` string, folded, when the same string recurs on three or more lines (a merchant seen once is noise; the threshold is a hypothesis).

**The hint.** The kind on every line is `org`, and only `org`: a company, a club, a brand and a family's own domain are all orgs if the owner accepts them. What the queue guesses about an observed org is a column of its row, `hint`, one of `company`, `brand`, `community` or `personal`, and nothing else:

| `hint` | When |
|---|---|
| `personal` | a domain whose every address seen resolves to a canonical person, three of them at most (`personal_max_people`, §4.6): a family's own domain; or a GitHub path whose segment is a `handle` ref of a canonical person: their own account |
| `community` | the strongest identifier is a group name |
| `brand` | the strongest identifier is a merchant string |
| `company` | anything else: a domain or a GitHub organisation |

The hint ranks the queue and does nothing else: proposals are ranked by score, then by hint in the order `company`, `community`, `brand`, `personal`, and the row shows it (`[personal]`). It is never written to a line, never part of a key, and never read by a page or a shelf; the owner's accept writes an `org`, whatever the hint said.

The proposal: an observed org not yet placed against each canonical org, scored by what speaks for the pair, a plain sum as `people review`'s:

| Evidence | Points | What it means |
|---|---|---|
| same domain | 60 | a `domain` ref of the canonical org (or of a `company` resolution line read as it) spells the registered domain |
| same GitHub org | 50 | a `repo` ref of the canonical org has the same first segment |
| same name | 20, +5 per further source up to +10 | the display name (a mail's `from.name`, a group's name, a merchant string, a repo's org) and the label or an alias are one name: the same words in any order, case, punctuation and the forms `AS`, `ASA`, `Ltd`, `Inc`, `GmbH`, `AB` aside; two words at least, or one word of six letters or more |
| the org's people | 10 per canonical person, up to 30 | a canonical person whose address is at one of this org's domains was seen on the observed lines (an attendee, a sender, a group member) |
| together on the same days | 2 per day, up to 20 | both were seen on the day; days alone never propose |

A domain alone, matching no canonical org, proposes a **new** org with the domain as its name and the names the sources gave it (the display name of a `from` is read; a signature in a body is not, because the body is never read), as `places review` proposes a blank with the names its sources gave.

### 4.3 idea

Strongest identifier, in this order:

1. the **Notion root page**: the `sync notion` `event/v1` line's page id, or the topmost of "the titles above it" when the integration can see that page, as `page` (`notion:<id>`). A page under a root is the root's idea unless the owner says otherwise; the lineage is the evidence and the sub-pages are the documents (§7);
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

As today (`docs/places.md#review`): the observed place is a cluster of stays within 75 m, ranked by nights then hours, named by what the sources already said (Timeline visits, calendar locations held during the stay, photo libraries, Dawarich). Nothing is looked up and no coordinate leaves the machine. The strongest identifier is the cluster's centre, rounded to six decimals, written as a `point` ref (`55.600000,4.436000`) where a line carries it (§6). `review place` is `setup places review` with this RFC's queue shape; the accept and name semantics are the page's, and the reject writes a line (§5, §6).

### 4.5 asset

An observed asset is one of:

1. a **subject** on a `location/v1` line (`subject` set) that `assets.json` does not name: lines from another machine's registry, or a hull reported under an id the registry never held;
2. an **aircraft registration** on a `flight/v1` line (`aircraft.registration`) seen on three or more flights, or on a `keeper/v1` boarding pass that names a tail; the owner's own aircraft flies its owner more than once, an airline's does not;
3. an **MMSI** or **callsign** named in the `extra` of an AIS report of a vessel that the registry does not know, when it recurs across days near the owner's own hull (a raft-up neighbour, a club boat).

Strongest identifier: `mmsi`, else `icao24`, else `registration`, else the `subject` id. The proposal matches on the same identifier (60), the same registration spelled two ways (`ZZ-ABC` and `ZZABC`, 50), or the same name on the report and in the registry (20). Accepting writes the asset into `assets.json` as `setup assets add` does, and an `entity/v1` line binding the identifiers. Nothing is synced for a new asset until the owner asks (ADR 0018: the record records what was asked for). An entry closed by a status line (§10.3) is still in the registry and still names its subject: its lines are never proposed as a new asset.

### 4.6 `policy/entities.json`

One setting, read each run, never a line:

```json
{"public_mail_providers": ["gmail.com", "outlook.com", "hotmail.com", "icloud.com", "me.com", "proton.me", "yahoo.com", "example.org"],
 "merchant_min_lines": 3, "title_min_lines": 2, "personal_max_people": 3,
 "code_hosts": ["github.com", "gitlab.com", "codeberg.org"],
 "mute_days": 365, "stale_after_days": {"hold": 1095, "exploring": 730}}
```

The provider list ships with a default a reader carries in code and the file extends; a domain of the owner's own (`owner_emails` in `logbook.json`, `policy/owner.json`) is never an org. `mute_days` is §10.5's and `stale_after_days` §10.6's; the status rules' thresholds of §10.4 live here too, under their own names, with the defaults the table gives. Every number is a hypothesis, as `policy/stays.json`'s constants are.

## 5. `review KIND`

One command, one shape, five kinds:

```bash
logbook review org                       # the queue: observed orgs not yet placed, ranked
logbook review idea --json               # the queue, the unplaced and the placed count
logbook review org --accept 1,3 --reject 11
logbook review idea --name 2 "the fjord kiosk"     # accept with the owner's own name
logbook review org --all-above 50
logbook review org --status 8 hold --reason "…"    # answer a status proposal (§10.4)
logbook review place                     # = setup places review (kept, with one line saying so)
logbook review person                    # = people review (kept)
logbook review asset
logbook review                           # every kind with a queue, one block each, nothing written
```

```
7 proposals · 9 observed orgs not yet placed, 4 placed · tier 2
   1  [80]  nordmann-verft.example (Nordmann Verft, Nordmann Verft AS; mail 12, calendar 3) → Nordmann Verft AS: same domain · same name Nordmann Verft AS · Ola Nordmann on both
   2  [25]  group "nordmann verft board" (message 41) [community] → Nordmann Verft AS: same name · Ola Nordmann on both
   5  [new] fjordkiosk.example (Fjordkiosk; mail 2) → ____
   7  [new] nordmann.example (mail 30) [personal] → ____
nothing written: `review org --accept N[,N]`, `--name N "…"`, `--reject N[,N]`, or `--all-above SCORE`
```

The numbers are the queue's at this head and change when the record does; `--json` carries a stable `id` per pair, a digest of the two keys, and the row's `hint`. Every number is checked before the first line is written; a number the queue does not have, a number both accepted and rejected, or a score that is not a whole number exits 2 and writes nothing. On a terminal the command asks `y`, `n`, a name, Enter to skip or `q` for each proposal shown, as `places review` does, and writes each answer at once.

What each answer writes:

| Kind | `--accept` / `--name` | `--reject` |
|---|---|---|
| person | the `resolution/v1` alias lines `people review` writes today (RFC 0006) | one `entity-review/v1` line, `type` `person` (§6; RFC 0035 amendment 1) |
| org | one `entity/v1` line (minting when the key is new, §3.4 rule 4), binding the `domain`, `repo`, `group` and `merchant` refs | one `entity-review/v1` line, `type` `org`; it MAY cite the `transaction/v1` lines a merchant proposal rested on, and is then tier 3 (§8) |
| idea | one `entity/v1` line binding the `page`, `repo` and `title` refs | one `entity-review/v1` line, `type` `idea` |
| place | the `places.json` entry, the fitted radius and the `note/v1` naming line as today, and one `entity/v1` line (§3.3) | one `entity-review/v1` line, `type` `place`, with the spot as a `point` ref and the name proposed, or none for a blank (§6); never again an entry in `state/places-review.json` alone (§6.4) |
| asset | the `assets.json` entry as `setup assets add` writes it, and one `entity/v1` line | one `entity-review/v1` line, `type` `asset` |

A rejected pair is never proposed again; retract the line and it returns. A `--name` on a proposal that matched a canonical entity is a relabel of nothing: it accepts the match and leaves the label; to rename an entity, `logbook add` an `entity/v1` line that `supersedes` the standing one. `serve`'s Places page answers through the same accept and reject (`docs/serve.md`), so its "Not a place" writes the same line.

**The writers.** Every write goes through `Logbook.append`, `source` `manual`, and nothing else writes these lines: no adapter, no import, no model, and no tool through the door (ADR 0022). Each command holds the record's writer lock from its first read of the record to its last append, as `day sign` does (RFC 0034 amendment 3) and as RFC 0036 amendment 1 has its writers do: it reads the head again before it appends and, when another writer moved it, is refused with `HeadMoved`, one sentence, exit 2, nothing written. The review reader opens no connection: no register of companies, no code host, no Notion is asked. The tests hold it to that with the network guard on.

## 6. `entity-review/v1`: the owner's no

One profile carries every no the sitting writes, for every kind: the owner's statement that an observed thing is **not** the canonical entity a review proposed, or is not a new one. It is RFC 0035's `people-review/v1` with the kind on the line, and it replaces it as the line `people review --reject` writes (RFC 0035 amendment 1); the `people-review/v1` lines already in a record are read as `entity-review/v1` lines of `type` `person`, forever.

### 6.1 Line

`kind` MUST be `entity-review`. `source` MUST be `manual`: the owner said so. `tier` MUST be the highest tier of the evidence it refers to (SPEC §4): 2 in practice, 1 for a place's no, which rests on stays, and 3 when it cites a tier-3 line, as an org's no on a merchant match may cite the transactions the match rested on (§8). `at` is when the owner said it (for a no migrated from `state/places-review.json`, the entry's `rejected_at`, §6.4; `recorded_at` says when it became a line); `end` is null.

### 6.2 Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"entity-review/v1"` | MUST | |
| `type` | string | MUST | the kind: `person`, `org`, `idea`, `place` or `asset` |
| `verdict` | string | MUST | `different`: the observed thing is not the entity, or, when there is no `entity`, not a new entity of its kind (under `name`, for a place). No other verdict is defined; a *same* is the accept's line, never this |
| `ref` | object | MUST | the observed thing's strongest identifier, `{ kind, value }`, of its kind's order (§4): a person's `email`, `phone` or `name`; an org's `domain`, `repo`, `group` or `merchant`; an idea's `page`, `repo` or `title`; a place's `point` (`<lat>,<lon>`, six decimals); an asset's `mmsi`, `icao24`, `registration` or `subject` |
| `refs` | array of object | SHOULD | the observed thing's identifiers as the lines wrote them. A reader matches a later observation against `ref` and every entry here |
| `observed` | array of string | MAY | the display names it was seen under |
| `entity` | object | MUST when the proposal named a canonical entity, absent when it proposed a new one | `{ type, id, registry }`, `type` equal to the line's `type` |
| `name` | string | MAY | for a place, the name the proposal offered for the spot; absent for a blank. No other kind carries it |
| `label` | string | SHOULD | the canonical entity's label at the time, for reading the log without any table |
| `method` | string | MAY | `owner` |
| `evidence` | array of string | MAY | ids of the lines the observed thing was seen on |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |
| `extra` | object | MAY | `migrated_from`: `state/places-review.json` on a no `--migrate-rejects` wrote |

### 6.3 Rules

1. An `entity-review` line binds no ref and changes no resolution: the observed identifiers resolve as before, and every reader but the review reads as before.
2. **Against an entity.** A review reader MUST NOT propose an observed thing against an entity when a standing `entity-review` line with that `entity` names the observed thing's strongest identifier, or any identifier it was seen as, in `ref` or `refs` (RFC 0035 rule 2, for every kind).
3. **As new.** A standing line with no `entity` keeps the observed thing out of the queue's new proposals: for an org, an idea or an asset, every new proposal for that ref; for a place, the new proposal under its `name`, or the blank when it has none, so a spot whose blank was rejected returns when a source names it, as `state/places-review.json` behaved. A ref so held may still be proposed against a canonical entity.
4. **A spot is a circle.** A place's `point` matches an observed place whose centre lies within the cluster distance of it (75 m, `--radius`), as the state file's rejections matched.
5. Retraction (RFC 0003) applies: a retracted line counts for nothing, and the proposal returns.
6. **The old no.** A standing `people-review/v1` line (RFC 0035) is read exactly as an `entity-review/v1` line with `type` `person` and the same fields. No writer writes one after RFC 0035 amendment 1; none is rewritten.
7. Nothing requires the line. A record with none is complete, and a queue is as long as its evidence.

### 6.4 A place's no, and the state file

`setup places review --reject` has kept a place's no in `state/places-review.json`, which a backup leaves out; from this RFC it writes an `entity-review/v1` line, `type` `place`, as every other kind's no is written. The nos already in the file become lines once:

```bash
logbook setup places review --migrate-rejects     # also: logbook review place --migrate-rejects
```

writes one line per entry of the file that no standing line already holds: `ref` `{ kind: "point", value: "<lat>,<lon>" }` from the entry's `lat` and `lon`, `name` the entry's name (absent for a blank), `at` its `rejected_at` (now when it has none), `extra.migrated_from` the file's path, tier 1 (a place's no rests on stays), every write through `Logbook.append` under one hold of the writer lock. It is run once: a second run finds every entry held and writes nothing, and says so.

The file then becomes a **cache**. `--migrate-rejects` rewrites it from the standing lines, with the head it was built at, and from then on the review rebuilds it from the lines whenever the head moved or the file is missing, and reads it only to avoid reading the lines again. Deleting it brings nothing back; retracting a line does. A file without the head, the file of today, is not yet a cache: until `--migrate-rejects` runs, every entry in it that no line holds is still read as a no, so nothing returns before the owner migrates, it is never rewritten except by that command, and each review says how many entries are not lines yet and the command to run.

## 7. The entity page

`logbook org NAME`, `logbook idea NAME`, `logbook people NAME` (today's person page), `logbook place NAME`, `logbook asset NAME`, each `[--year YYYY] [--json]`, and `logbook entity KIND NAME` for all of them. `NAME` is tried as a ref first (`kind:value`, a domain, a `+` number, a `notion:` id, an `owner/name` repo), then as an entity id, then as a label or alias (case aside), then as a word of a label (`kiosk` finds the fjord kiosk when no other idea is a kiosk); several or none is refused with exit 2 and the reason on stderr, as `people NAME` does.

The page has the same sections for every kind, in this order, then the kind's own:

1. **Head**: the label, the refs in parentheses, the kind, the tier of the page (the highest tier of any line it rests on, SPEC §4; what the page shows past the crossing ceiling is governed by ADR 0016 as every reader is).
2. **Status line**: the current status, since when (for a place or an asset, `until` when), who proposed it and the reason, from the last standing `status/v1` line, and `stale` when §10.6 says so. A person has no status and the row is left out; an entity with no status line says `—`.
3. **Timeline of every touch**: every standing line that resolves to the entity, most recent first, one row per local day (by `day_start`, RFC 0036) with the source, the line kind and what it was (`mail from ola.nordmann@nordmann-verft.example "Q3 numbers"`, `edited notion "Kiosk / Pricing" +340 words`, `stay 6 h`, `position 59.90,10.75 (aisstream)`); under `--json` each row carries the line ids. The subject of a mail and the title of a page are what the line already holds; a body is never shown because it is never stored.
4. **People involved**: the canonical people on the entity's lines, most days first: attendees of its meetings, senders in its group, actors on its pages, splitters on its ledger lines, speakers of its transcripts; each with how many touches and the last one. An observed person not yet placed is counted (`and 3 not yet placed`), never named in a row.
5. **Documents as references**: the Notion pages (title, id, url), Drive files (name, id, link), repositories and mails (subject, date, the ids of the lines) that touch the entity, newest first, as references and never as copies: the record holds the title, the hash and the word count of a page, not the page.
6. **Status lines**: every `status/v1` line for the entity, oldest first, with its date, status, who proposed it, its reason (the note written with it, §10.5) and whether it stands; a retracted one is shown struck and said.

Then the kind's own: an **org** adds its domains and the ledger's net in and out by year, derived at read time from the lines its `merchant` refs match, within the ceiling (tier-3 lines are shown only where the page itself may show tier 3; no line of the org cites them, §8); an **idea** adds its title thread (the titles of its pages, tasks and transcripts, as the lines hold them, newest first), the words written by month (the sum of `sync notion`'s word deltas), the repositories and the days since its spark; a **place** adds its visits, nights and hours as `places review` counts them and the days together there; an **asset** adds its last known position and the days aboard, as `asset_status` and the with module derive them; a **person** keeps every row of `docs/people.md#the-person-page` and adds sections 3 and 5 (a person's documents are the pages and files they acted on). A person's page shows no status, and a person draft (RFC 0036 amendment 1, open at this writing) is RFC 0036's to place on the page, not this RFC's.

## 8. Tiers

SPEC §4: derived data inherits the highest tier of its evidence, and a profile names the tier its producers write by default. One rule runs through the table: **an `entity/v1` line never cites a tier-3 line**, so no name of the Manifest or the Ideas shelf is lifted to 3 and sealed with age (RFC 0029) for a transaction it was matched by; the money is derived by the page at read time, within the ceiling.

| Line | Tier | Reasoning |
|---|---|---|
| `entity/v1`, kind `org` | 2 | its evidence is mail (2), calendar (1) and group names (2). It MUST NOT cite a `transaction/v1` line: a merchant match is written as a `merchant` ref, a folded string the ledger shows anyway, and the shelf derives the ledger's involvement at read time |
| `entity/v1`, kind `idea` | 2 | its label is the owner's own words, as `task/v1` and `note/v1` keep them at 2; its evidence is Notion events (1), tasks (2) and transcripts (2). A transcript written at 3 is matched by its `title` ref and never cited, so the line stays at 2 |
| `entity/v1`, kind `place` | 1, 2 when it cites a note or a calendar entry with attendees | the stays are derived from `location/v1` (1); the `note/v1` naming line beside it is 2 by RFC 0010 and is a separate line. The name of a home is not more identifying than the home's coordinates in every tier-1 stay |
| `entity/v1`, kind `asset` | 1 | its evidence is position reports (1) and flights (1) |
| `entity-review/v1` | the highest tier of its evidence: 2 in practice, 1 for a place's (stays), 3 when it cites a tier-3 line | the owner's no MAY cite the transactions a merchant proposal rested on, so the record keeps why it was asked; a no is read by the review alone, so its tier hides nothing a shelf needs |
| `status/v1`, kind `org` | 3, MUST | `hold`, `add`, `sell` and `exited` describe a position in money; `passed` and `let-go` are decisions (2). The envelope's `tier` is plain (SPEC §4), so a line at 2 among lines at 3 would say, without a key, which companies the owner passed on and which they hold. One tier for all six statuses gives that away to nobody; the cost is that the anti-portfolio seals with age like the portfolio, which is right |
| `status/v1`, kind `idea` | 2, MUST | a decision about one's own work; the reason is the owner's words |
| `status/v1`, kind `place` or `asset` | 2, MUST | a decision about one's own place or one's own boat. **No money on the line**: no price, no amount, and no `transaction/v1` line cited; a sale's payment, when the record has one, is a tier-3 line of its own that the page may show beside the status within the ceiling |
| `note/v1`, label `status` | 2, MUST (RFC 0010) | the owner's words on why, written with an idea's, a place's or an asset's status line that has a reason (§10.5), and never with an org's. SPEC §4 lets a producer write a higher tier only where the profile's default is a SHOULD, so the note cannot follow an org's line to 3, and at 2 it would carry an org's reason, which can name money, wherever tier 2 crosses: an org's reason stays in the `reason` of its tier-3 status line and nowhere else. No `note/v1` line is written above 2. The note carries the words and the entity, never the disposition; the words are readable at 2, as every note is |

The page's tier is the highest of its lines; an org page that shows ledger lines is 3 and crosses nothing (RFC 0005, ADR 0016). The Manifest shelf groups the orgs by their status lines, which are 3, so it is 3 with or without `--money`; a reader under a ceiling of 2 lists every org under **no status** and says how many status lines it may not show. The Ideas shelf rests on lines at 2 or below and is 2.

## 9. Dedupe keys

A key is what a writer looks up before minting or writing, so a second review sitting, a second machine or a re-run never writes the same thing twice (ADR 0017's rule, applied to the owner's own writes). One key per kind, folded (NFKC, lower-cased, whitespace collapsed), computed by the writer and carried under `keys` for readers without the table:

| Kind | Key, looked up through | Example |
|---|---|---|
| person | `email:<address>`, else `phone:<E.164>`, else `name:<words sorted>` (RFC 0035's order); through `resolution/v1` only | `email:ola.nordmann@example.org` |
| org | `domain:<registered domain>`, else `repo-org:<host>/<org>`, else `group:<folded name>`, else `merchant:<folded string>`; through `entity/v1` and the `company` resolution lines. The hint is never part of it | `domain:nordmann-verft.example` |
| idea | `page:notion:<root page id>`, else `repo:<host>/<owner>/<name>`, else `title:<words sorted, articles out>`; through `entity/v1` | `repo:github.com/nordmann-verft/kiosk` |
| place | `place:<name as places.json spells it, folded>`; and a centre inside a named place's radius is that place already (`docs/places.md#the-fitted-radius`); through `entity/v1` and `places.json` | `place:hytta på banken` |
| asset | `mmsi:<n>`, else `icao24:<hex, lower>`, else `registration:<folded, hyphens out>`, else `subject:<id>`; through `entity/v1` and `assets.json` | `mmsi:970123456` |

A `review KIND --accept` whose key resolves already reuses that id and binds the new refs to it; `--name` on a new key mints.

The owner's other lines:

| Line | Key | Example |
|---|---|---|
| `entity-review/v1` | `(type, ref, entity id)` against an entity; `(type, ref)` as new, and for a place `(place, point, name)`, the blank's name absent. A place's `point` is one key with every point within the cluster distance of it (§6.3 rule 4). A writer that finds the key held writes nothing and says so; `--migrate-rejects` uses the same key, so its second run writes nothing | `(place, point:55.600000,4.436000, —)` |
| `status/v1` | `(entity, status, local day)`: the writer refuses a second status equal to the standing one on the same day; a status equal to the standing one on a later day with a new `reason` is written (the owner reaffirmed, and said why, which is how a `hold` mutes a proposal, §10.5) | `(org 019cadd3…0201, hold, 2026-10-12)` |
| `note/v1`, label `status` | none of its own: one per idea's, place's or asset's status line that has a reason (an org's writes none, §10.5), written with it under the same hold of the lock and named by its `note` field | |

The `--json` of every reader carries the key beside the id.

## 10. `status/v1`: what the owner decided

### 10.1 Line

`kind` MUST be `status`. `source` MUST be `manual`: a status is the owner's disposition, never the dream's. `tier` as §8, MUST: 3 for an org, 2 for an idea, a place or an asset. `at` is when the owner disposed; `end` is null.

### 10.2 Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"status/v1"` | MUST | |
| `entity` | object | MUST | `{ type, id, registry }`, `type` `org`, `idea`, `place` or `asset`. Never `person`: a person has no status. Never a goal: a goal's verdict is RFC 0036's `review/v1` (§12) |
| `label` | string | SHOULD | the entity's label at the time, for reading the log without any table |
| `status` | string | MUST | one of the kind's dispositions (§10.3); any other value makes the line invalid for its kind |
| `reason` | string | SHOULD; MUST for `passed`, `let-go` and `killed` | the owner's words on why. The anti-portfolio is this field: a passed company keeps its thread and its reason |
| `note` | string | MUST when `reason` is given, except for an org | the id of the `note/v1` line written with this one, carrying the same words (§10.5). An org's line has none: its reason stays on its tier-3 line, because the note's tier is fixed at 2 by RFC 0010 |
| `proposed_by` | string | MUST | `dream` when the owner disposed of a proposal the review showed, `owner` when they set it unprompted |
| `proposal` | object | MAY | what the dream proposed, when `proposed_by` is `dream`: `{ status, score, because: [string] }`, so the record keeps the proposal even when the owner chose another status |
| `since` | date | MAY | for an org or an idea, the local day the status took effect when it is not the line's own day (an exit in June entered in October) |
| `until` | date | MUST for a place or an asset; MUST NOT otherwise | the last local day the registry entry holds: the berth given up, the boat handed over (§10.3) |
| `evidence` | array of string | MAY | ids of the lines the proposal rested on; for a place or an asset, never a tier-3 line |
| `supersedes` | string | MAY | the id of the standing status line this replaces |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |

No field carries an amount, a price or a currency, for any kind.

### 10.3 Dispositions

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

For a **place**, one:

| Status | Meaning |
|---|---|
| `let-go` | the owner gave it up: a berth, a flat, an office, a cabin sold or no longer rented. `reason` MUST say; `until` is the last day it was the owner's |

For an **asset**, two:

| Status | Meaning |
|---|---|
| `sold` | the owner sold it; `until` is the last day it was theirs. The price is not on the line |
| `let-go` | it stopped being the owner's without a sale: scrapped, lost, given away, a lease ended. `reason` MUST say |

**A registry entry is closed, never deleted.** A place or an asset with a standing `let-go` or `sold` line stays in `places.json` or `assets.json`, and is **closed** from the day after `until`. A closed place still names the stays inside its radius, before and after `until`: a place given up is still where it is, and the visit to an old flat is a visit to it. A closed asset still names the lines whose `subject` is its id; `sync ais` and `sync adsb` ask for no position of it after `until` (ADR 0018: the record records what was asked for), and a position line after it that reaches the record anyway (an import, another machine's sync) is valid and shown, as ADR 0018 rule 4 has it. Retracting the status line (RFC 0003) reopens the entry. This RFC defines no disposition that reopens a closed entry otherwise; a boat bought back is for a later amendment.

There is no state machine: for an org or an idea any status may follow any, because a record keeps what the owner decided and not what a diagram allows (`passed` then `hold` is a company the owner came back to, and the two lines say so). The current status is the last standing line's; a retracted status line counts for nothing and the one before it stands; an entity with no status line has none and its shelf row says `—`.

### 10.4 Proposed by the dream, disposed by the owner

The pattern is the signed day's (RFC 0034) and the goal review's (RFC 0036): the engine proposes, the owner's answer is the line, and nothing is a line until the owner answers. The dream proposes a status when the record's own facts move, by these rules, evaluated against the head on the dream's normal cadence (each morning, with `logbook dream`'s run, `docs/dream.md`) and by `review` whenever it runs, so the two always agree. A proposal is not a line and not a draft segment: no `draft/v1` line carries it, and RFC 0036's rule that no reader derives a fact from a draft holds unchanged.

| Kind | The dream proposes | Because |
|---|---|---|
| org | `exited` | a `transaction/v1` inflow from the org's merchant or a mail from its domain with no touch after it for 90 days, after a standing `hold`, `add` or `sell` |
| org | `let-go` | no touch for 365 days under a standing `hold`, `add` or `sell` |
| org | `passed` | a new org with meetings and mail in a window of 60 days, then no touch for 180, and no status line |
| idea | `exploring` | a `spark` whose page or repo is touched in three or more weeks |
| idea | `build` | an `exploring` idea whose repo is touched on ten or more days in a month |
| idea | `killed` | an `exploring` or `build` idea with no touch for 180 days |
| idea | `built` | never: only the owner knows what done is |
| place, asset | nothing | only the owner knows a berth is given up or a boat sold; the owner writes it (`logbook status`, below) |

The proposals appear in `review org` and `review idea` under their own heading after the identity proposals, numbered on, with the because-list; `--status N hold --reason "…"` (or the terminal's prompt) writes the line with `proposed_by` `dream` and the proposal kept; `logbook status org "Nordmann Verft AS" passed --reason "…"` writes one unprompted with `proposed_by` `owner`, and so do `logbook status place "Hytta på banken" let-go --until 2026-09-30 --reason "…"` and `logbook status asset Nordlys sold --until 2026-08-31`. `--reject N` on a status proposal writes nothing and mutes nothing: the proposal returns when the facts change. The thresholds are hypotheses in `policy/entities.json` (§4.6).

### 10.5 The reason, as a note

When a status is given a reason, by `--reason` or the terminal's prompt, the reason is the `status/v1` line's `reason`, in the owner's words, for every kind. For an idea, a place or an asset the writer appends two lines under one hold of the writer lock: first one `note/v1` line (RFC 0010: `source` `manual`, tier 2, `text` the reason as given, `labels` `["status"]`, `extra.entity` the entity's `{ type, id, registry }`), then the `status/v1` line, whose `reason` is the same words and whose `note` names the note. The note carries the entity and never the disposition.

**An org's reason stays on its tier-3 line, with no note.** RFC 0010 makes a `note/v1` line tier 2 as a MUST, and SPEC §4 allows a higher tier only where the profile's default is a SHOULD, so a note cannot be written at the org line's 3; left at 2, it would carry an org's reason, which can name money, everywhere tier 2 crosses. For an org the writer appends the `status/v1` line alone, its `reason` the words and no `note` field. No status writes a `note/v1` above tier 2, and a status without a reason writes no note. Every reader that shows a reason (`status list`, the review's and the status command's output, the pages) reads it from the status line when there is no note, so an org's reason shows to the owner wherever its tier-3 line may be read, and never at 2.

The note is the owner's words in the place every reader already looks for them: the Day lists it on its day, `search` finds it, and the Ideas shelf reads an idea's **title thread** (§7) and its **reasons** (the status notes, oldest first) and nothing more. Notion bodies stay out of scope: `sync notion` keeps a page's title, hash and word count and never its text, and this RFC reads no body, Notion's or a mail's.

**A hold with a reason is the standing no.** No line says "never propose this". A standing `status/v1` line with status `hold` and a `reason`, written in answer to a proposal (`proposed_by` `dream`) whose `proposal.status` was another disposition, **mutes** proposals of that disposition for that entity for 365 days from the line's local day (`mute_days`, §4.6): the owner was asked, kept the position, and said why. It is a reader's rule, documented here and settable, and no line records the mute. A `hold` without a reason mutes nothing; nor does one set unprompted, which answers no proposal. For an idea, which has no `hold`, the same rule reads a line that keeps the idea's standing status, with a reason, in answer to a proposal (an `exploring` kept against a proposed `killed`). A muted proposal returns when the days have passed and its rule still holds.

### 10.6 Dispositions as they age

A disposition the owner set long ago, on an entity the record has not touched since, is **stale**, by a reader's rule and never by a line: the standing status is a key of `stale_after_days` (§4.6), and neither a touch nor a status line for the entity falls within that many days of today. By default a `hold` is stale after three years (1095 days) and an `exploring` after two (730); the owner sets other statuses or other numbers in the file, and a status the setting does not name is never stale. The shelf and the page mark a stale row (`stale: no touch since 2023-06-01`), and `--json` carries `stale` and `stale_since`.

Staleness proposes nothing and does not make the dream propose more often: the rules of §10.4 run on their normal cadence. A stale entity becomes **one question in the weekly dream**, the dream's draft of a week (RFC 0036 `draft/v1`, unit `week`): asked once, about its standing status and its last touch ("Havn Data AS: still hold? Nothing since June 2023."), never a proposal and never a line of its own. The owner's answer is a `status/v1` line, which restarts the clock, or nothing, and the shelf keeps the mark. The week's draft has no writer yet; until it has one, the stale entities are listed in `review org` and `review idea` under their own heading, and nothing asks. How the week's draft cites a status line older than the week is for its writer to settle under RFC 0036 (`draft/v1` rule 6 holds a segment's evidence to the lines the unit read).

## 11. The two shelves

Both are readers (ADR 0013), derived at the head every run, never written, in the terminal and as pages of the Library (`logbook serve`, `docs/serve.md`).

**The Manifest shelf**, `logbook manifest [--year YYYY] [--money] [--json]`, is every canonical org, grouped by its current status, under four headings in this order: **holding** (`hold`, `add`, `sell`, with the status in the row), **exited**, **passed** (the anti-portfolio) and **let go**, then **no status**. "The Manifest" is the shelf's name in the Library and nothing more: it is not a kind, and no line carries the word. Each row: the label, the status and since when, the last touch (what and when), how many people involved and the first two by days, how many documents, the reason on a `passed` or `let-go` row, in full, and `stale` when §10.6 says so. With `--money`, and only on a terminal that may show tier 3, the ledger's net in and out for the year on each row, derived at read time from the lines the org's `merchant` refs match. Within a heading, most recent touch first. Nothing is ranked by amount: the shelf is a list of decisions, and the passed companies are on it as fully as the held ones.

```
manifest · 6 orgs · to 2026-10-12 · tier 3
holding
  Nordmann Verft AS   hold since 2024-03-02 (owner) · last touch 2026-10-09 mail · 1 person (Ola Nordmann) · 11 documents
  Havn Data AS        hold since 2023-05-10 (owner) · stale: no touch since 2023-06-01 · 1 document
passed
  Fjordkiosk AS       passed 2026-06-14 (dream proposed passed) · last touch 2026-05-02 meeting · 2 people · 1 document
                      reason: good team, but a kiosk is a place and I do not want to own places
```

**The Ideas shelf**, `logbook ideas [--year YYYY] [--json]`, is every canonical idea, grouped by status in the order `build`, `exploring`, `spark`, `built`, `killed`, then **no status**. Each row: the label, the status and since when, the last touch, the words written this year (the Notion deltas), the repositories, the people involved, the days since its spark, the title thread's latest titles, and its reasons (the status notes, §10.5), the latest in the row and every one under `--json`. Within a heading, most recent touch first; a `killed` idea that sparked again is under its new status with its old reason one line below.

```
ideas · 4 · to 2026-10-12 · tier 2
exploring
  the fjord kiosk     exploring since 2026-09-20 (dream proposed) · last touch 2026-10-11 notion "Kiosk / Pricing" · +2,140 words this year · github.com/nordmann-verft/kiosk · 1 person (Ola Nordmann) · 54 days since spark
                      reason: pricing page written; talk to the ferry company first
killed
  the tide clock      killed 2026-04-02 (owner) · reason: every chartplotter already shows it
```

Under `serve`, the shelves are `/manifest` and `/ideas`, and an entity's page is `/org/<id>`, `/idea/<id>`, with the same sections as §7; the pages are rendered within the ceiling as every `serve` page is.

## 12. Relation to RFC 0036 and RFC 0034

Three things in the record look alike, an owner's word on something at a date, proposed by an engine or not and written only by the owner, and they are three, each with its own line and its own words:

| | Status (this RFC) | Review (RFC 0036) | Disposition (RFC 0034) |
|---|---|---|---|
| of what | an entity: an org, an idea, a place, an asset | a goal (`goal/v1`) | a commitment: a line confirmed on a signed day's page |
| the line | `status/v1` | `review/v1` | `dispositions` on `signed-day/v1` (amendment 1), not a line of its own |
| the words | the kind's own (§10.3) | `advancing`, `stalled`, `done`, `let go`, `superseded` | `kept`, `missed`, `dropped`, `carried` |
| its date | `at` when the owner disposed, `since` when it took effect, `until` the last day of a place or an asset | `at` the date the verdict is about, `recorded_at` when it was written | the signature's |
| tier | 3 for an org, 2 otherwise | 2 | the signature's (1) |
| its writer | `review KIND --status`, `logbook status` (§10.4) | `goal review` (RFC 0036 amendment 1, open at this writing) | `day sign` (RFC 0034) |
| what the readers do with it | the shelves, the entity page | the Day, the open goals | `promises` closes a promise |

- **`status/v1` takes no goal.** A goal is the owner's intention, not a thing in the world the record touches; its verdict is RFC 0036's `review/v1`, whose five words fit a goal and would not fit a company. RFC 0036 is the RFC that specifies the goal review.
- **A person has no status.** A person is not held, passed or let go; what the record says about a person over time (`people drift`, the person page) is derived by readers, and a model's words about one are a draft, a proposal (RFC 0036 `draft/v1`; its amendment 1, open at this writing, adds a `person` unit).
- **A promise is not an entity.** What became of a commitment is the signature's disposition (RFC 0034 amendment 1), on the day the owner signed, and `promises` reads it there.
- **One pattern.** All three are one loop: a proposal, the owner's answer as a line, and the next proposal only when the record moves. `review KIND` is that loop for entities, and `day sign` for a day's commitments. If `review goal` joins the sitting, as RFC 0036 amendment 1 (#269) proposes, it lists goals and answers through the writer `goal review` uses, writing `review/v1` and never `status/v1`.

## 13. What this RFC amends

- **RFC 0035**, by its amendment 1 ([rfcs/0035-people-review-v1.md](https://github.com/bighydro/logbook/blob/main/rfcs/0035-people-review-v1.md#amendment-1--the-no-is-entity-reviewv1)): `people review --reject` writes `entity-review/v1`, `type` `person`, from now on; readers accept `people-review/v1` forever; no line is rewritten.
- **ADR 0018 rule 4**, by an amendment paragraph in [docs/adr/0018-assets-are-subjects.md](https://github.com/bighydro/logbook/blob/main/docs/adr/0018-assets-are-subjects.md): registry entries are never deleted, and a `status/v1` line closes them with `until`.
- **`docs/places.md`** changes when the reject is implemented, not in this RFC: `--reject` writes a line, `--migrate-rejects` exists, and `state/places-review.json` is a cache.

## 14. Examples (synthetic)

An org, minted at review; its domain is bound here, by the entity line's `refs`, and by no resolution line:

```json
{"at":"2026-10-12T20:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity","tier":2,
 "payload":{"schema":"entity/v1","entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000201","registry":"logbook"},
 "label":"Nordmann Verft AS","aliases":["Nordmann Verft"],
 "refs":[{"kind":"domain","value":"nordmann-verft.example"},{"kind":"group","value":"nordmann verft board"},{"kind":"repo","value":"github.com/nordmann-verft"}],
 "keys":{"org":"domain:nordmann-verft.example"},"method":"owner",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000001a1","019cadd3-6bc0-7dcd-9133-0000000001a2"],"logbook_head":"8f1c…"}}
```

A `company` resolution line an earlier writer left, as RFC 0006 allowed it. It is **read, never written**: a reader reads it as binding the domain to the org `019cadd3…0203`, and no writer of this RFC writes one like it or rewrites it:

```json
{"at":"2023-05-02T18:00:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"domain","value":"havn.example"},
 "entity":{"type":"company","id":"019cadd3-6bc0-7dcd-9133-000000000203","registry":"logbook"},"label":"Havn Data AS","method":"owner"}}
```

An idea:

```json
{"at":"2026-09-20T21:02:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity","tier":2,
 "payload":{"schema":"entity/v1","entity":{"type":"idea","id":"019cadd3-6bc0-7dcd-9133-000000000301","registry":"logbook"},
 "label":"the fjord kiosk",
 "refs":[{"kind":"repo","value":"github.com/nordmann-verft/kiosk"},{"kind":"page","value":"notion:1f2e3d4c-0000-0000-0000-000000000031"},{"kind":"title","value":"fjord kiosk"}],
 "keys":{"idea":"repo:github.com/nordmann-verft/kiosk"},"method":"owner","extra":{"pitch":"a kiosk on the ferry quay that sells what the ferry forgot"}}}
```

The owner's no on a merchant match, citing the two transactions it rested on, so it is tier 3; the org's own line, above, stays at 2:

```json
{"at":"2026-10-12T20:16:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity-review","tier":3,
 "payload":{"schema":"entity-review/v1","type":"org","verdict":"different",
 "ref":{"kind":"merchant","value":"nordmann kiosk"},"refs":[{"kind":"merchant","value":"nordmann kiosk"}],
 "observed":["NORDMANN KIOSK"],"entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000201","registry":"logbook"},
 "label":"Nordmann Verft AS","method":"owner",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000001c1","019cadd3-6bc0-7dcd-9133-0000000001c2"],"logbook_head":"8f1c…"}}
```

A place's no, carried over from `state/places-review.json` by `--migrate-rejects`: a blank rejected in February, a line since October (`recorded_at`, in the envelope, is `2026-10-14T09:00:00Z`):

```json
{"at":"2026-02-16T19:20:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity-review","tier":1,
 "payload":{"schema":"entity-review/v1","type":"place","verdict":"different",
 "ref":{"kind":"point","value":"55.600000,4.436000"},"method":"owner",
 "extra":{"migrated_from":"state/places-review.json"}}}
```

A passed company: one line, tier 3, the reason on it and no note (§10.5), the dream's proposal kept beside the owner's word:

```json
{"at":"2026-06-14T19:40:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":3,
 "payload":{"schema":"status/v1","entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000202","registry":"logbook"},
 "label":"Fjordkiosk AS","status":"passed","reason":"good team, but a kiosk is a place and I do not want to own places",
 "proposed_by":"dream","proposal":{"status":"passed","score":40,"because":["3 meetings and 9 mails 2026-03-30 – 2026-05-02","no touch for 180 days","no status line"]},
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000001b1"],"logbook_head":"8f1c…"}}
```

A hold with a reason, in answer to a proposed `let-go`: proposals of `let-go` for this org are muted until 2027-10-12 (§10.5). Its reason is on the line and nowhere else:

```json
{"at":"2026-10-12T20:20:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":3,
 "payload":{"schema":"status/v1","entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000204","registry":"logbook"},
 "label":"Nordmann Seil AS","status":"hold","reason":"quiet on purpose; the board meets once a year",
 "proposed_by":"dream","proposal":{"status":"let-go","score":30,"because":["no touch for 365 days under hold"]},
 "supersedes":"019cadd3-6bc0-7dcd-9133-0000000001b2"}}
```

An idea the owner moved on without being asked (its note `…01d3`, labelled `status`, holds the reason):

```json
{"at":"2026-10-11T22:05:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":2,
 "payload":{"schema":"status/v1","entity":{"type":"idea","id":"019cadd3-6bc0-7dcd-9133-000000000301","registry":"logbook"},
 "label":"the fjord kiosk","status":"exploring","proposed_by":"owner","reason":"pricing page written; talk to the ferry company first",
 "note":"019cadd3-6bc0-7dcd-9133-0000000001d3"}}
```

A boat sold: tier 2, no price, the entry in `assets.json` kept and closed after 31 August; the sale's payment, if the ledger has it, is a tier-3 line of its own that this one does not cite:

```json
{"at":"2026-09-03T17:30:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":2,
 "payload":{"schema":"status/v1","entity":{"type":"asset","id":"nordlys","registry":"logbook"},
 "label":"Nordlys","status":"sold","until":"2026-08-31","proposed_by":"owner"}}
```

A place let go (its note `…01d4` holds the reason):

```json
{"at":"2026-10-02T19:00:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":2,
 "payload":{"schema":"status/v1","entity":{"type":"place","id":"Verkstedet","registry":"logbook"},
 "label":"Verkstedet","status":"let-go","until":"2026-09-30","reason":"the lease ended; the tools are at Hytta på banken now",
 "note":"019cadd3-6bc0-7dcd-9133-0000000001d4","proposed_by":"owner"}}
```

## 15. What this RFC changes, and what it does not

It changes three writers, when it is implemented: `people review --reject` writes `entity-review/v1` (RFC 0035 amendment 1); `setup places review --reject` writes `entity-review/v1` and no longer keeps the no in `state/places-review.json` alone, which becomes a cache (§6.4); and closing a place or an asset is a status line, never an edit that removes the entry (ADR 0018 rule 4, as amended). It adds `observed_entities` and turns `observed_people` and `observed_places` into views for one release (§4).

It does not change:

- The meaning of any line already in a record. `resolution/v1` is read as before, a `company` line read as an org; `people-review/v1` is read forever; `people`, `people NAME`, `people review`, `people merge` and `setup places review` keep their names and their output, each gaining an alias and, for the pages, sections.
- The road of a person: `resolution/v1` only, frozen, and no `entity/v1` line names one.
- What an adapter writes. No adapter writes an `entity/v1`, `entity-review/v1`, `status/v1` or status `note/v1` line; all are `source` `manual`.
- The network. The review reads the record and the settings files; the pages read the record. Nothing asks a company register, a code host or Notion, and no body is read.
- The envelope (SPEC §2–3), the canonical JSON, the hashing and the conformance samples.

## 16. Decided

The comment period on the twelve questions closed on 2026-10-14; the owner decided each, and the body above says so where it applies. Question → decision → reason:

1. **Two roads for a ref?** → One road per kind: a person binds through `resolution/v1` (frozen), an org, an idea, an asset and a place through `entity/v1` only; `company` resolution lines are read as orgs and never rewritten; no `resolution/v2` (§3.3, §3.4) → one lookup per kind, nothing frozen reopened, and no line rewritten.
2. **One no, or one per kind?** → One profile for every no, `entity-review/v1`; RFC 0035 is amended (an amendment section, not a rewrite) so `people review` writes `entity-review/v1` `type` `person` from now on, and readers accept `people-review/v1` forever (§6) → the sitting is one sitting, and the old lines keep their meaning.
3. **A place's no: line or state file?** → A line, `entity-review/v1` `type` `place`; `--migrate-rejects` writes the state file's nos as lines once, and the file becomes a cache (§6.4) → a decision of the owner's belongs in the chain, which a backup keeps.
4. **Who is an org?** → `org` is the only kind on a line; the observed row carries a `hint` (`company`, `brand`, `community`, `personal`) used for ranking only, never written to a line (§4.2) → the guess helps the queue without becoming a fact.
5. **Ideas and the body?** → `status --reason` writes one `note/v1` (tier 2, label `status`) beside the status line when a reason is given (for an idea, a place or an asset; an org's reason stays on its tier-3 line, with no note: amended 2026-10-14, §10.5); the Ideas shelf reads the title thread and the reasons; Notion bodies stay out of scope (§10.5, §11) → the owner's own words, kept where notes are, and nothing read that the record does not store.
6. **A standing no on a status?** → No "never" line; a `hold` with a reason mutes proposals of the rejected disposition for that entity for 365 days, a documented reader rule, settable (§10.5) → the owner's answer is already the line, and a mute that ends cannot outlive the facts.
7. **One table or three?** → One table, `observed_entities`, with a `kind` column; `observed_people` and `observed_places` become views for one release (§4) → one build and one shape check, without breaking today's readers at once.
8. **Ledger evidence?** → The entity line never cites a tier-3 line and stays at 2; the owner's `entity-review/v1` line may cite the transaction and is then tier 3; the shelf derives money at read time (§8) → the names stay unsealed by money, and the evidence of a no is kept where it costs nothing.
9. **Dispositions as they age?** → Staleness is a reader's rule (`hold` over three years, `exploring` over two, in the settings); the dream proposes on its normal cadence; a stale entity becomes one question in the weekly dream (§10.6) → a flag is cheaper than proposals, and a question asks without nagging.
10. **Status for places and assets?** → `status/v1` takes a place (`let-go`) and an asset (`sold`, `let-go`) at tier 2 with no money on the line; registry entries are never deleted, a status line closes them with `until`; ADR 0018 rule 4 is amended to say so (§10.3, §13) → the record keeps the decision and the date, and the old track keeps its name.
11. **The goal review?** → Goals are reviewed by RFC 0036's `review/v1`; `status/v1` takes no goal, and a person has no status; §12 separates status (entities), review (goals) and dispositions (promises) → three things with three sets of words, each specified once.
12. **The word?** → `org` is the kind; `company` is a frozen legacy value, read as `org`; "the Manifest" is the Library shelf's name, not a kind (§3.3, §11) → one word for the kind, and the shelf's name stays the shelf's.
