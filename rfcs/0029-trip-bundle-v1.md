# RFC 0029 — bundle profile `trip-bundle/v1`, page `trip-share/v1`, line `received/v1`

Status: draft · 2026-10-03 · comment period: two weeks

The shared trip: how one member of the circle (ADR 0009) hands another their record of a trip they took together, and how the recipient's record keeps it without ever mistaking it for its own. Three things are defined here, and they are all this version builds of the circle's shared page (ARCHITECTURE): a **bundle profile** on top of the crossing package (RFC 0005), the **page** of derived rows it carries, and the **received line** the recipient's `import` writes. `logbook export trip-bundle <trip> --to <member>` produces the first two; `logbook import trip-bundle <folder>` produces the third; `logbook trip <id>` reads the pages back beside the recipient's own trip.

## Why a profile, not a new package

A crossing package already says everything a bundle between two records has to say: verbatim lines, the referenced files, an optional resolution overlay, a manifest with the policy that was applied, a `crossing/v1` line in the sender's chain so that the crossing is never invisible (ADR 0016). A trip is a *selection* of such a package — one trip's days, a few kinds of line — plus one thing a plain crossing has no place for: the rows the sender's readers derive from the trip. ADR 0019 declines a line for a derived trip and says that a circle page shares derived rows. So the trip bundle is a crossing package whose manifest carries `profile: "trip-bundle/v1"` and one more file, `trip.json`, with those rows. A consumer of plain crossing packages ignores the fields it does not know (RFC 0005) and reads the lines as before.

## The bundle

```
<bundle>/
  manifest.json          # crossing-package/v1, with the fields below
  entries.jsonl          # the trip's photo/v1 and flight/v1 lines, verbatim
  trip.json              # trip-share/v1: the derived rows
  resolution.jsonl       # OPTIONAL: the resolution/v1 lines that name the people (tier 2)
  attachments/<sha256>   # OPTIONAL: the photos' files, only with --attachments
```

The manifest is RFC 0005's, as `export crossing` writes it, plus:

| Field | Type | Req | Meaning |
|---|---|---|---|
| `profile` | `"trip-bundle/v1"` | MUST | what this crossing package is cut to |
| `trip` | object | MUST | `{ id, start, end, until }`: the derived trip id (`trip:<first day>:<last day>`, ADR 0019) and its days, the return day as `until` |
| `trip_file` | string | MUST | `trip.json` |
| `trip_sha256` | hex sha256 | MUST | the digest of that file's bytes, as `entries_sha256` names the entries |
| `sender` | object | MUST | `{ id, name, refs }`: the owner id, the first name of the sender's `policy/owner.json` (else the id), and — only when tier 2 crosses — the sender's own addresses and numbers as `{ kind, value }` refs, so the recipient can match the sender to one of its own people by a ref rather than by a spelling |
| `timezone` | IANA name | SHOULD | the sender's record zone, so the recipient can place the page on the sender's local days |
| `attachments_included` | boolean | MUST | whether the photos' files were asked for; without them a photo line crosses with its hashes and nothing else |
| `covers` | object | MUST (RFC 0005) | `{ from, to }`: from the first day's local midnight to the end of the return day, in UTC |

## Rules of the export

1. **Only the trip's days, and only what a reader of a trip needs.** `entries.jsonl` carries the standing `photo/v1` lines whose `at` is inside `covers` and the standing `flight/v1` lines the trip lists (SPEC §3.2.6), in chain order, verbatim. Nothing else of those days crosses: not the location points (the stays stand for them), not the calendar entries, notes, transcripts, messages or mail the company was derived from, not the health or money lines. A reader that wants more asks for a plain crossing.
2. **Derived rows cross as rows.** `trip.json` is the trip as the sender's readers derive it at `logbook_head`, never a line (ADR 0019). The home stays either side of the trip are left out: nothing of home crosses.
3. **The tiers are the request's and the ceiling is the destination's** (ADR 0016): `--tier` defaults to 1, the destination's `max_tier` in `policy/crossing.json` bounds it, and a destination the file does not name receives nothing. The people rows, the sender's refs and the resolution overlay are tier 2 — a name is a resolution's work (RFC 0006, *Privacy*) — so with `--tier 1` the page carries the places, the moves, the flights and the photos, and `held_back.people` says how many names stayed home. A photo line's own tier is what it is; a tier-3 line crosses only under `--tier 1,2,3`, with the warning `export crossing` prints.
4. **Pixels only when asked.** A photo line crosses with the digests it carries; the files cross only with `--attachments`, copied and hashed on the way as RFC 0005 says, and the manifest says which it was.
5. **A crossing is never invisible.** A real export appends one `crossing/v1` line (RFC 0011) with `extra.trip` the trip id and `extra.profile` this profile. A dry run appends nothing. The watermark of `export crossing` does not move: a trip is not a delta window.

## `trip.json`: `trip-share/v1`

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"trip-share/v1"` | MUST | |
| `trip` | object | MUST | `{ id, start, end, until, nights, in_transit, route }` as `trips --json` gives them (SPEC §3.2.6) |
| `sender` | object | MUST | as the manifest's |
| `stays` | array | MUST | the owner's stays of the trip that are not at home, each as `derive stays --json` gives a segment (SPEC §3.2.3: `id`, `start`, `end`, the local forms, `lat`, `lon`, `place`, `attached`, `lines`), plus `label` (the route's label for it, SPEC §3.2.6 rule 4) and `nights` (how many of the trip's nights were spent at it) |
| `moves` | array | MUST | the owner's moves whose span touches the trip's, as segments (`distance_m`, `mode`, `airports`; a move carries no coordinates) |
| `flights` | array | MUST | the trip's flights as `trips --json` lists them |
| `people` | array | MUST | the people confirmed present at the stays (SPEC §3.2.5, confirmed only; never the owner), each `{ person, name, status, sources, refs, lines }`, where `refs` are the `{ kind, value }` refs that name them: the refs of their evidence and every ref the sender's record resolves to the same person. Empty when tier 2 does not cross |
| `photos` | object | MUST | `{ count, lines }`: the photo lines in `entries.jsonl` |
| `held_back` | object | MUST | `{ people, lines, resolutions }`: what the request kept home |
| `tiers` | array | MUST | the tiers asked for |
| `tier` | 1, 2 or 3 | MUST | the page's own tier: the highest of what it carries, 2 as soon as it names anyone (SPEC §4: derived data inherits the highest tier of its evidence) |

The `person` ids are the sender's (RFC 0006: one id space per record) and mean nothing to the recipient; the refs are how two records find the same person.

## The received line: `received/v1`

`import trip-bundle` reads a bundle, checks every digest the manifest names and recomputes every line's own hash (RFC 0005: a subset cannot replay the chain, so this is the whole of its provenance; a mismatch refuses the bundle), and appends what the record does not hold yet:

- **A received line** for every line of `entries.jsonl` and `resolution.jsonl`: `kind` MUST be `received`, `source` MUST be `received`, `tier` the inner line's, `at`, `end` and `tz` the inner line's, so it is on its day at its tier. The payload is `{ schema: "received/v1", raw_id, line, extra }`: `line` the sender's line **verbatim**, envelope and all, so its own hash still recomputes in the recipient's record; `raw_id` the inner payload's `raw_id`, else `received:<sender owner id>:<inner line id>`; `extra.from` the sender's owner id, `extra.sender` their name, `extra.bundle_id`, `extra.logbook_head` (the sender's head the bundle reflects), `extra.package_sha256` and `extra.received_at`.
- **The page** as one received line of schema `trip-share/v1`: the content of `trip.json` with `raw_id` `trip-share:<bundle_id>` and the same `extra`; `at` and `end` are the manifest's `covers`, `tz` its `timezone`, `tier` the page's own.

Rules:

1. **A received line is never one of the record's own.** Its kind is `received`, which no derived reader takes (SPEC §3.2.2: a derived reader reads standing lines of a kind): the sender's photos are nobody's photos here, the sender's flights are not this owner's flights, and the sender's resolutions name nobody in this record's registry (`resolve.standing` reads kind `resolution`, and these are not). `show` lists them on their day as `from <sender>: <kind> <source> · …`.
2. **Never over the record's own, never twice.** Before writing, the import asks the index which of the lines' `raw_id`s the record already holds, whatever their source. One held by a line of the record's own (the same shared photo under the same asset id, the same invite) is skipped and counted as *kept as yours*; one held by a received line is skipped and counted as *received before*. A page whose bundle id is in the record already is skipped the same way. Nothing is ever rewritten (SPEC §3).
3. **The files go in the store.** With `attachments/` in the bundle, each file that hashes to its name is put in the record's own store (SPEC §1.1, write-once); one that does not is counted and left.
4. **A bundle of the record's own is refused.** The manifest's `owner` equal to this record's `owner_id` is not a crossing; the import says so and writes nothing.
5. **A dry run writes nothing** and prints the same counts.

## The merged page

`logbook trip <id>` reads the received pages whose trip touches this one — found through the index by their `raw_id` prefix, a retracted page left out — and shows, per sender:

- **who was there according to each record**: `you` and this record's confirmed people on one side, the sender and their confirmed people on the other. A person of theirs is matched to one of yours when one of their refs is one of the owner's own identities (then they are `you`), or resolves in this record to a person confirmed here; else when the names are equal, case and spacing aside; else they are seen by one record only.
- **the places the records agree on**: each located stay of this trip's route with the sender's stays within 300 m of it (`AGREE_M`; the distance `rollup places` groups unnamed stays by), the sender's label and nights beside yours; a stay of theirs that matches none of yours is a row of its own.
- a **`seen only by`** column on both: `you`, the sender's name, or nothing when both records have it.

The page compares and confirms nobody: SPEC §3.2.5 rule 5 (the `circle` source of the with module) stays reserved, and nothing here is written back. A page that reaches the record is the fact that the sender's record said this at that head, with the package digest to show for it; it is not this record's derivation, and no reader of this record derives from it.

## Example (synthetic)

A received photo line, the sender's line verbatim inside it. The people, places and ids are invented; the cabin is not at these coordinates.

```json
{"at":"2026-06-13T09:00:00Z","end":null,"tz":"Europe/Oslo","source":"received","kind":"received","tier":1,
 "payload":{"schema":"received/v1","raw_id":"p-2026-06-13T09:00:00Z",
 "line":{"id":"01a0ffdb-2a0c-7b3e-8d41-0c7a2f9e1b05","seq":411,"at":"2026-06-13T09:00:00Z","end":null,"tz":"Europe/Oslo",
  "source":"immich","kind":"photo","tier":1,
  "payload":{"schema":"photo/v1","asset_id":"p-2026-06-13T09:00:00Z","library":"immich","file_name":"IMG_130900.HEIC",
   "media":"image","provenance":"camera","faces":1,"people":["p_17"],"lat":60.8604,"lon":8.5506,"raw_id":"p-2026-06-13T09:00:00Z"},
  "recorded_at":"2026-06-14T18:02:11Z","prev":"5c0e…","hash":"9b1f…"},
 "extra":{"from":"019cadd3-6bc0-7dcd-9133-00000000b000","sender":"Ola Nordmann","bundle_id":"01a0ffdb-7c2e-7a1d-9f00-1e2d3c4b5a69",
  "logbook_head":"53d39fda…","package_sha256":"258a4267…","received_at":"2026-06-20T08:15:00Z"}}}
```

The merged page, as `logbook trip trip:2026-06-12:2026-06-13` prints it in Ines's record after Ola's bundle came in:

```
  shared with Ola Nordmann · their trip:2026-06-12:2026-06-13 · 2 nights · received 2026-06-20 · 2 photos
    who            yours                 theirs                             seen only by
    you            owner                 confirmed (calendar)
    Ola Nordmann   confirmed (calendar)  owner
    Kari Nordmann  –                     confirmed (calendar, note, photo)  Ola Nordmann
    where            theirs                             seen only by
    Cabin, 2 nights  Hytta, 2 nights
    –                60.8700,8.5701 near Hytta, 1.5 km  Ola Nordmann
```

## Notes

- **Why wrap, and not write the sender's line as it is with a mark in `extra`.** A line of kind `photo` and source `received` would still be a photo to every reader that takes the kind: the Day would count it, the keepers would propose it, a received flight would land in the owner's rollup. Hiding a source from every reader is a rule in every reader and a change to SPEC §3.2; a kind no reader takes is already how an unknown kind behaves. The wrapper also keeps the sender's envelope, so the recipient can show that the line hashes as the sender wrote it.
- **Why the rows and not the points.** The location points would let the recipient re-derive the sender's stays with its own settings and then disagree with the sender about where the sender was. The sender's record is the authority on the sender's day; the rows are what it says, at a head.
- **What is not here.** A signature over the bundle (ARCHITECTURE: the owner's signature; the package digest and the crossing line are the provenance for now), a transport (the bundle is a folder: a private repository, an rsync target, a USB stick), and any write-back: the recipient never turns a received person into a confirmation. Those are later versions, and none of them changes this profile.
