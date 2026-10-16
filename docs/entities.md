# Entities: the three profiles

RFC 0037 gives the record five kinds of thing that recur across its lines: a **person**, an **org**, an
**idea**, an **asset** and a **place**. Each is a canonical entity the owner confirmed, reviewed in
one sitting ([`logbook review KIND`](review.md)) and disposed of with one command (`logbook status`).
Three payload profiles carry what the owner said. All three are `source` `manual`: the owner said it,
through a review or a command; no adapter writes one.

| Profile | Says | Written by | Tier |
|---|---|---|---|
| `entity/v1` | this is an org, an idea, an asset or a place, and these refs are it | `review KIND --accept` / `--name` | 2 |
| `entity-review/v1` | this observed thing is not that entity (the owner's no) | `review KIND --reject`, `people review --reject`, `places review --reject` | the highest of its evidence, at least 2 |
| `status/v1` | what the owner decided about an org, an idea, a place or an asset | `logbook status KIND ENTITY DISPOSITION` | 2 |

The profiles are new and in draft with RFC 0037; they become frozen only by RFC 0031's process. The
envelope does not change. The code is `logbook/contrib/entities.py`: one validator per profile, the
dedupe keys, the tier rules and the readers.

## How a ref binds

- A **person** binds through `resolution/v1` (RFC 0006, frozen), and only there. An `entity/v1` line
  for a person may give aliases; its `refs` must be empty.
- An **org**, an **idea**, an **asset** and a **place** bind through `entity/v1` only: its `refs`.
- A `resolution/v1` line of type `company`, the frozen word, is read as an **org** entity, and never
  rewritten. `org` is the kind; `company` is a legacy value; the Manifest is the shelf's name.
- A ref resolves to the entity named by the last standing line that binds it, whichever profile.

## `entity/v1`

`kind` `entity`, `source` `manual`, tier **2** for every kind. An `entity/v1` line never cites a
tier-3 line: a merchant match is bound as a `merchant` ref, a folded string, and the ledger is read
at the page within its ceiling. `at` is when the owner said so; `end` is null.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"entity/v1"` | MUST | |
| `entity` | object | MUST | `{ type, id, registry }`. `type` one of `person`, `org`, `idea`, `asset`, `place`; `registry` `logbook`. `id`: a UUIDv7 minted in this record for an org or an idea; the UUID its resolution minted for a person; the name `places.json` spells for a place; the id `assets.json` holds for an asset |
| `label` | string | MUST | the name the owner gave or accepted |
| `refs` | array of `{ kind, value }` | SHOULD | what the line binds: RFC 0006's kinds (`email`, `phone`, `handle`, `provider_id`, `device_id`, `domain`, `line`) or `repo`, `page`, `title`, `group`, `merchant`, `mmsi`, `icao24`, `registration`, `place`. Empty for a person. A later line adds refs, never removes one |
| `aliases` | array of string | MAY | other spellings of the label |
| `keys` | object | MAY | the dedupe key the writer computed, under the kind (below) |
| `method` | string | MAY | `owner` |
| `evidence` | array of string | MAY | ids of the lines it was seen on; never a tier-3 line |
| `supersedes` | string | MAY | the `entity/v1` line this replaces (a relabel) |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |
| `extra` | object | MAY | what the kind needs and no line already holds (an idea's pitch) |

An org, minted at review, its domain bound on the same line:

```json
{"at":"2026-10-12T20:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity","tier":2,
 "payload":{"schema":"entity/v1","entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000201","registry":"logbook"},
 "label":"Nordmann Verft AS","aliases":["Nordmann Verft"],
 "refs":[{"kind":"domain","value":"nordmann-verft.example"},{"kind":"group","value":"nordmann verft board"},{"kind":"repo","value":"github.com/nordmann-verft"}],
 "keys":{"org":"domain:nordmann-verft.example"},"method":"owner",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000001a1","019cadd3-6bc0-7dcd-9133-0000000001a2"],
 "logbook_head":"8f1c000000000000000000000000000000000000000000000000000000000000"}}
```

An idea:

```json
{"at":"2026-09-20T21:02:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity","tier":2,
 "payload":{"schema":"entity/v1","entity":{"type":"idea","id":"019cadd3-6bc0-7dcd-9133-000000000301","registry":"logbook"},
 "label":"the fjord kiosk",
 "refs":[{"kind":"repo","value":"github.com/nordmann-verft/kiosk"},{"kind":"page","value":"notion:1f2e3d4c-0000-0000-0000-000000000031"},{"kind":"title","value":"fjord kiosk"}],
 "keys":{"idea":"repo:github.com/nordmann-verft/kiosk"},"method":"owner","extra":{"pitch":"a kiosk on the ferry quay that sells what the ferry forgot"}}}
```

## `entity-review/v1`

One profile for every no (RFC 0035's shape, every kind). `kind` `entity-review`, `source` `manual`.
Its tier is the highest tier of the evidence it cites and never under 2, a decision (SPEC §4); it
may cite a `transaction/v1` line, and is then tier 3. People review writes it for a person from now
on; a `people-review/v1` line is read as an `entity-review/v1` of type person, forever. A place's no
is a line too: `places review --reject` writes one, and `state/places-review.json` is a cache rebuilt
from the lines; `--migrate-rejects` writes the pairs the file held from before 0.7 as lines, once.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"entity-review/v1"` | MUST | |
| `verdict` | string | MUST | `different`: the observed thing is not the entity. A same is a binding line, never this |
| `ref` | `{ kind, value }` | MUST | the observed thing's strongest identifier: a person's `email`, `phone` or folded `name`; an org's `domain`, `repo`, `group` or `merchant`; an idea's `page`, `repo` or `title`; an asset's `mmsi`, `icao24`, `registration` or `subject`; a place's `centre` (`lat,lon` to six decimals) |
| `refs` | array of `{ kind, value }` | SHOULD | its identifiers as the lines wrote them; a later observation matches `ref` or any of these |
| `observed` | array of string | MAY | the names it was seen under |
| `entity` | object | MUST | the canonical entity proposed, `{ type, id, registry }`; for a proposal of a **new** entity (an org, an idea or an asset not yet minted, a place name) `{ type }` alone, the name in `label`, and for a rejected blank no `label` either. A person's is always whole |
| `label` | string | SHOULD | the entity's label at the time, or the name the proposal gave |
| `method` | string | MAY | `owner` |
| `evidence` | array of string | MAY | ids of the lines the observed thing was seen on |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |
| `raw_id`, `extra` | | MAY | the writer's: the proposal's id, its score and what matched |

A review reader never proposes the observed thing against the entity again while the line stands;
retract it and the proposal returns. An org seen as a sailing club's chat group, not the yard:

```json
{"at":"2026-10-12T20:16:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity-review","tier":2,
 "payload":{"schema":"entity-review/v1","verdict":"different","ref":{"kind":"group","value":"nordmann verft sailing"},
 "refs":[{"kind":"group","value":"nordmann verft sailing"}],"observed":["Nordmann Verft sailing"],
 "entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000201","registry":"logbook"},
 "label":"Nordmann Verft AS","method":"owner","evidence":["019cadd3-6bc0-7dcd-9133-0000000001c1"],
 "logbook_head":"8f1c000000000000000000000000000000000000000000000000000000000000"}}
```

A place's no: that spot is not "Boathouse":

```json
{"at":"2026-10-12T20:18:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity-review","tier":2,
 "payload":{"schema":"entity-review/v1","verdict":"different","ref":{"kind":"centre","value":"59.902100,10.741200"},
 "entity":{"type":"place"},"label":"Boathouse","method":"owner",
 "logbook_head":"8f1c000000000000000000000000000000000000000000000000000000000000"}}
```

## `status/v1`

What the owner decided, at a point in time. `kind` `status`, `source` `manual`, and no money on the
line: the ledger holds it. Its tier is the kind's (RFC 0037 §8): **3** for an org, whose dispositions
describe a position in money (a `passed` at 2 among `hold`s at 3 would say which is which), so the
line may cite tier-3 evidence; **2** for an idea, a place or an asset, a decision about your own work,
place or craft, which never cites a tier-3 line. A person has no status; a goal is reviewed by
RFC 0036's `review/v1`. `at` is when the owner disposed; `end` is null.

| Kind | Dispositions |
|---|---|
| org | `hold`, `add`, `sell`, `let-go`, `exited`, `passed` |
| idea | `spark`, `exploring`, `build`, `built`, `killed` |
| place | `let-go` |
| asset | `sold`, `let-go` |

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"status/v1"` | MUST | |
| `entity` | object | MUST | `{ type, id, registry }`, `type` `org`, `idea`, `place` or `asset` |
| `label` | string | SHOULD | the entity's label at the time |
| `status` | string | MUST | one of the kind's dispositions; any other makes the line invalid |
| `reason` | string | SHOULD; MUST for `passed`, `let-go`, `killed` | the owner's words on why; for an org, the only place they are written |
| `note` | string | MUST when `reason` is given, except for an org | the id of the `note/v1` line written just before this one with the same words; an org's line has none |
| `proposed_by` | string | MUST | `dream` when the owner disposed of a proposal, `owner` when unprompted |
| `proposal` | object | MAY | what the dream proposed, `{ status, score, because }` |
| `since` | date | MAY | the local day it took effect when not the line's own day |
| `evidence` | array of string | MAY | ids of the lines the proposal rested on |
| `supersedes` | string | MAY | the standing status line this replaces |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |

**Rules.** The current status is the last standing line's; any status may follow any. A status
equal to the standing one on the same local day is refused; on a later day it is written only with a
new reason (the owner reaffirmed, and said why). `status --reason "…"` puts the owner's words in
the line's `reason`. For an idea, a place or an asset it first writes one `note/v1` line, tier 2,
label `status`, the words as its text and the entity under `extra.entity` (never the disposition),
then the status line, whose `note` names it, both under one hold of the writer lock (RFC 0037
§10.5), so the owner's words are on the day and in `search`. A pair written before the writer kept
this order, the status line first and the note naming it under `extra.status`, is read the same. An
org's reason stays on its tier-3 status line and is never a note: RFC 0010 fixes a note at tier 2
(MUST), and a reason about a company can name money, so a note would carry it wherever tier 2
crosses. No status writes a note above tier 2. `status list` and the status command's output read
the reason from the status line, and `status list --json` names its note (`note`, null for an org).
A place let go and an asset sold or let go close their registry
entry with `until`, the line's local day: the entry in `places.json` or `assets.json` is never
deleted (ADR 0018, rule 4).

**Readers' rules**, never lines (`policy/entities.json`):

- **Mute.** A status line with a reason that answers a proposal of another disposition (the dream
  proposed `let-go`, the owner held, and said why) mutes proposals of that disposition for that
  entity for `mute_days`, **365** by default, while it is the current status. There is no "never"
  line.
- **Stale.** A `hold` older than three years and an `exploring` older than two are stale
  (`stale_days`, `{"hold": 1095, "exploring": 730}`); `status list` says so.

A passed company, the dream's proposal kept beside the owner's word:

```json
{"at":"2026-06-14T19:40:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":3,
 "payload":{"schema":"status/v1","entity":{"type":"org","id":"019cadd3-6bc0-7dcd-9133-000000000202","registry":"logbook"},
 "label":"Fjordkiosk AS","status":"passed","reason":"good team, but a kiosk is a place and I do not want to own places",
 "proposed_by":"dream","proposal":{"status":"passed","score":40,"because":["3 meetings and 9 mails 2026-03-30 – 2026-05-02","no touch for 180 days","no status line"]},
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000001b1"],
 "logbook_head":"8f1c000000000000000000000000000000000000000000000000000000000000"}}
```

An idea the owner moved on without being asked (its note `…01d3`, labelled `status` and written
just before it, holds the reason):

```json
{"at":"2026-10-11T22:05:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"status","tier":2,
 "payload":{"schema":"status/v1","entity":{"type":"idea","id":"019cadd3-6bc0-7dcd-9133-000000000301","registry":"logbook"},
 "label":"the fjord kiosk","status":"exploring","proposed_by":"owner","reason":"pricing page written; talk to the ferry company first",
 "note":"019cadd3-6bc0-7dcd-9133-0000000001d3"}}
```

## The orgs read back

`logbook show orgs` is every org you named (RFC 0037 §11), under its current status: **holding**
(`hold`, `add`, `sell`), **exited**, **passed** (the anti-portfolio, each with its reason in full),
**let go**, then **no status**; within a heading the most recent touch first. A **touch** is a line
that resolves to the org through one of its refs: a mail or a meeting with an address at its
domain, a transcript one of its people spoke in, a page or an act on its code-host org, its group
chat, its merchant. A row says the status and since when, the last touch and what it was, the people
on its lines (the first two by days), how many documents (mails and repositories, as references) and
`stale` when the status is one `stale_days` names and neither it nor a touch falls within that many
days of today. Then the people who appear with more than one org: the co-investor graph.

```
$ logbook show orgs
orgs · 4 · 2026-10-12 · tier 3 · money not shown
holding
  Nordmann Verft AS     hold since 2026-04-02 (owner) · last touch 2026-10-09 group "Nordmann Verft": message from Ola · 3 people (Ola Nordmann, Per Hansen) · 3 documents
  Nordmann Tidevann AS  add since 2026-10-02 (owner) · last touch 2026-10-01 mail from Liv Berg "Follow-on round" · 3 people (Liv Berg, Per Hansen) · 4 documents
  Nordmann Havbris AS   hold since 2023-06-15 (owner) · stale: nothing since 2023-07-01 · last touch 2023-07-01 the ledger · 1 person (Anders Vik) · 2 documents
passed
  Fjordkiosk AS         passed since 2026-06-14 (owner) · last touch 2026-04-20 mail from Kari Nordmann "Follow-up" · 2 people (Kari Nordmann, Per Hansen) · 2 documents
                        reason: good team, but a kiosk is a place and I do not want to own places
people with more than one org
  Per Hansen: Fjordkiosk AS, Nordmann Tidevann AS, Nordmann Verft AS
  Liv Berg: Nordmann Tidevann AS, Nordmann Verft AS
  Ola Nordmann: Nordmann Tidevann AS, Nordmann Verft AS
```

`logbook show org NAME` is one org's page (RFC 0037 §7), the org named as `status` names one (a
domain, a word of its name, its id): its refs, its status and its reason, every touch newest first,
the people, who introduced whom where a mail's subject says so (`Intro: Ines <> Liv`), the documents
and every status line, the one in force marked and a retracted one said so. An org whose naming line
was retracted stays while a status line names it, under that line's label (RFC 0037 §3.4 rule 3);
two orgs of one label are told apart by their key. Both take `--json`; nothing is written.

**Money only with `--money`.** A ledger line the org's `merchant` refs match is a touch like any
other, so the last touch, the order and the stale flag are the same with `--money` or without; without
it the shelf says only `the ledger` for it, with no merchant and no figure, and the page shows no
ledger row. With `--money` the page adds the ledger's lines and its in, out and net per year, and the
shelf each row's for `--year` (this year by default), derived at read time. No line of the org cites
them.

**Tier 3 stays tier 3.** An org's status line is tier 3 and its reason is on it; the page and the
shelf read every line through a gate (the owner's terminal and `logbook serve` read every tier; a
crossing, an exported site and the door read their policy's). Through a gate without tier 3 there
is no status and no reason: every org is under no status, and the shelf says how many status lines
it may not show; an org's page says only that it shows none, never how many it has, which would tell
which orgs carry a decision. A person who is with an org only on a tier-3 line (a split payment) is no edge of
the graph there; an edge is as high a tier as the lines it rests on.

## The dedupe keys

A key is what a writer looks up before minting, so a second sitting, a second machine or a re-run
never mints the same thing twice. Folded: NFKC, case aside, whitespace collapsed.

| Kind | Key, strongest first | Example |
|---|---|---|
| person | `email:`, else `phone:` (E.164), else `name:` (words sorted) | `email:ola.nordmann@example.org` |
| org | `domain:` (the registered domain), else `repo-org:` (host and org), else `group:`, else `merchant:` | `domain:nordmann-verft.example` |
| idea | `page:notion:` (the root page), else `repo:` (host, owner, name), else `title:` (words sorted, articles out) | `repo:github.com/nordmann-verft/kiosk` |
| place | `place:` (the name `places.json` spells) | `place:hytta på banken` |
| asset | `mmsi:`, else `icao24:`, else `registration:` (hyphens out), else `subject:` | `mmsi:970123456` |

The registered domain is the public suffix and one label, read from the suffixes the code carries
and `public_suffixes` in `policy/entities.json`; the names RFC 2606 reserves count as suffixes, so in
the synthetic record `post.verft.example.org` is the org `verft.example.org` and `example.org`, a
public mail provider, names nobody's org.

## `policy/entities.json`

One setting, read each run, never a line. Absent is the defaults.

```text
{"public_mail_providers": ["…"], "public_suffixes": ["…"], "code_hosts": ["github.com", "gitlab.com", "codeberg.org"],
 "merchant_min_lines": 3, "title_min_lines": 2, "registration_min_flights": 3,
 "mute_days": 365, "stale_days": {"hold": 1095, "exploring": 730}}
```

The provider list extends the default the code carries (RFC 0037 §4.6); the owner's own domains are
never an org. The thresholds are hypotheses, as `policy/stays.json`'s constants are.
