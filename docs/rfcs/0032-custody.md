# RFC 0032 — payload profile `custody/v1`: a record changes hands

Status: draft · 2026-10-03 · comment period: two weeks · **the consent section is to be read by a non-technical co-author before the comment period opens**; the technical sections may be commented on now.

A record is one person's. So far the person whose life it records and the person who holds the pen have been the same person, and the format has one word for both: `owner_id` in `logbook.json`. Three ordinary events pull the two apart. A parent keeps a child's record from birth until the child is old enough to take the pen. An executor receives a record after a death. One partner keeps a record on the other's behalf, through an illness or a long absence, and hands it back. In each the record stays whose it was and the hand that appends to it changes. This profile gives that change one line, says how the whole record crosses to the new hand, what the previous hand may keep, how the tiers apply to them afterwards, and how `verify` shows that the chain was not broken on the way.

Nothing here changes the envelope (SPEC §2–3) or the hash. A `custody/v1` line is a line like any other; the rules about it are a profile's rules, and the chain rules of §3 are what prove the handover.

## Words

- The **subject** is the person the record is about: `owner_id`. It never changes. A record does not change subject; a subject may have more than one record only by the mistake of starting two.
- The **keeper** is the person who holds the pen: the one who appends, sets the policies and decides what crosses. With no custody line standing, the keeper is the subject.
- **Custody** is the state of being kept by someone other than the subject. The **custody chain** is the sequence of keepers the record has had, read from its custody lines.
- A **handover** is one change of keeper. It is two lines, written by two hands: the outgoing keeper's `handover` and the incoming keeper's `accept`, adjacent in the chain.

## Three cases

**A child's record.** The parent starts the record on the day of birth with `owner_id` the child's, and the first line says the parent keeps it (`act` `declare`). For years the parent appends: photos, the pediatrician's visits, the first flight, the parent's own notes in the parent's words. One day the child takes the pen: the parent writes `handover`, hands over the folder, and the child writes `accept`. The parent's own record, the one about the parent's life, is untouched; it has its own photos of the same birthdays.

**A death.** The subject kept their own record. They may have named a successor in life (`declare` with `successor`), or left a will that does, or neither. The executor writes the `handover` line, since the keeper cannot, and cites the instrument that gives them the authority; the record cannot judge that authority, only hold it (rule 2). The executor then writes `accept` as the new keeper, or hands the record on to the heir with a second pair.

**Partners.** One partner keeps the other's record during an illness: a `handover` from the subject to the partner and the partner's `accept`; then, months later, a `handover` back and the subject's `accept`. Two handovers, four lines, and the record reads who held the pen on every day in between.

## Line

`kind` MUST be `custody`. `tier` MUST be 1, and the payload MUST carry nothing but identifiers, acts, heads, digests, tier lists and words from the closed vocabularies below: `verify` must be able to read the custody chain of a record it cannot open (SPEC §4: tiers 2–3 will be sealed), and the chain of keepers is data about the record, not about anyone's day. The reasons in a person's words, a parent's letter, the will, are a tier-2 `note/v1` or an attachment (SPEC §1.1) the line points at by digest. `at` is when the act took effect; `end` is null. `source` is `manual`: a custody line is a person's act, never an adapter's and never an agent's (ARCHITECTURE: agents never write a visibility decision).

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"custody/v1"` | MUST | |
| `act` | string | MUST | `declare`, `handover` or `accept` (rules 1, 3, 4) |
| `keeper` | object | MUST | who holds the pen after this line: `{"subject": true}` for the subject, else `{"type": "person", "id": "<uuid>", "registry": "logbook"}`, a person the record's resolution lines mint (RFC 0006) |
| `from` | object | `handover` | who held it before, in the same form |
| `reason` | string | `handover` | `age`, `death`, `incapacity`, `agreement`; nothing else, and nothing longer |
| `successor` | object | MAY, `declare` | who should keep the record if the keeper cannot, in the form of `keeper` (the case of a death) |
| `head` | hex sha256 | `handover`, `accept` | `handover`: the chain head before this line, as `crossing/v1` carries `logbook_head`. `accept`: the hash of the `handover` line it accepts |
| `handover` | string | `accept` | the `id` of the `handover` line this accepts |
| `destination` | string | `handover` | the new keeper as `policy/crossing.json` names them, so the record shows the ceiling the handover was made under (rule 3) |
| `tiers` | array of integer | `handover` | the tiers that cross with the record: always `[1, 2, 3]` (rule 3); written out so the line reads without the rule |
| `counts` | object | `handover` | `{ lines, by_tier, attachments: { included, bytes, missing } }` of the record at `head`, so the receiver can see the folder is whole |
| `retains` | object | `handover` | what the former keeper keeps: `{ tiers, crossing }` — the tiers of their retained copy and the `id` of the `crossing/v1` line that recorded it (rule 5); `{"tiers": [], "crossing": null}` when they keep nothing |
| `authority` | object | MAY | the SPEC §1.1 attachment reference of the document that gives a hand its right to write this line: a grant of probate, a power of attorney, a signed agreement. SHOULD be present when `reason` is `death` or `incapacity` |
| `key` | string | MAY | reserved: the fingerprint of the new keeper's signing key, for the record signing a later RFC defines |

Anything else MAY be kept under `extra`.

## Rules

1. **The chain is the registry.** The keeper at any point in the record is the `keeper` of the last custody line standing at or before that point; with none, the subject. A `declare` line says who keeps the record from here and names no `from`: it is the first line of a record kept on another's behalf, and it is also how a subject names a successor in life. No file outside the chain records custody; `logbook.json` is unchanged (its `owner_id` is the subject's), and a reader that does not know this profile sees a valid record with one more tier-1 line.
2. **Who writes a handover.** The `handover` line is written by the outgoing keeper's hand, and it is the last line that hand writes. When the outgoing keeper cannot write (`reason` `death` or `incapacity`), the incoming keeper writes it on their behalf and SHOULD attach the `authority`. The record holds the authority; it does not judge it. `verify` proves that the chain was not broken, not that the person who continued it had the right to (see *What `verify` proves*). A record whose `handover` after a death carries no `authority` is valid; it is also a record a court, or a child reading it later, will ask questions of.
3. **The handover is a crossing of the whole record.** It is a crossing in every sense ADR 0016 gives the word: a named destination, a ceiling in `policy/crossing.json` set by the keeper before the export, tier 3 crossing only because the keeper typed it, and a line in the chain that says it happened. It differs from an ordinary crossing in one respect: the package is the record itself, every file a backup snapshot holds (`logbook.json`, the month files, `policy/`, `places.json`, `assets.json`, `attachments/`, `notes/`), ending with the `handover` line as its last line. Nothing is held back; a chain with a line missing is not a record (SPEC §3), and the point of custody is that the new keeper holds the record, not a view of it. So `tiers` is `[1, 2, 3]`, and the `destination` MUST have `max_tier` 3 in the policy file at the time. Because the package contains the `handover` line, no `crossing/v1` line can record it (RFC 0011 rule 3: a package cannot contain the line that records it); the `handover` line carries the crossing's facts (`destination`, `tiers`, `counts`, `head`) in its place.
4. **Acceptance is the next line.** The incoming keeper's first act is an `accept` whose `handover` is the `handover` line's `id` and whose `head` is its `hash`, at `seq` one more. Between the two lines nothing is written by anyone: a record whose `handover` is followed by any other line is a record somebody appended to in transit, and rule 8 says so. Until the `accept` is written, the record has a keeper who has let go and a keeper who has not taken hold; both hands SHOULD treat it as read-only, and the reference will refuse to `add` to a record whose last line is a `handover`.
5. **What the former keeper may retain.** A copy of the record, in part or whole, exactly as a circle member may: as a `crossing-package/v1` (RFC 0005) exported *before* the `handover` line, to a `destination` that names the former keeper, under a ceiling they set for themselves in `policy/crossing.json`, with its own `crossing/v1` line in the chain. The `handover` line names that crossing line in `retains.crossing` and repeats its tiers in `retains.tiers`. A former keeper who keeps the whole folder as well, a backup snapshot, a disk, has kept something the record does not show; the profile cannot prevent it and does not pretend to. What it can do is make the honest case cheap and visible: one command, one line, and the new keeper reads in the chain what left with the old one. The defaults for `retains` per case are in *Consent*.
6. **The former keeper afterwards is a member of the circle.** After the `accept`, the former keeper has a frozen copy at most, and anything written after the `handover` reaches them only by a crossing the new keeper exports under the new keeper's ceiling for them. The new keeper's first act after accepting SHOULD be to read `policy/crossing.json` and set every destination in it as they mean it, the former keeper's among them: the policy file crosses with the record (rule 3) and still says what the former keeper decided. A retained copy's tiers (`retains.tiers`) and the ceiling in force afterwards are two different settings, and the second is the new keeper's alone.
7. **A custody line is never retracted or superseded.** A handover happened; hiding the line would hide who held the pen on which days, which is the one thing the custody chain is for. A handover made in error is undone by another: a `handover` back and an `accept`. The reference will refuse `retract` on a custody line, and a reader treats a retraction naming one as naming nothing.
8. **What `verify` checks.** Reading the custody lines in `seq` order, with the subject as the keeper before the first: every `declare` and `handover` is written while its `from`, or the keeper in force, is the keeper (a `declare` with a custody line already standing is a change of keeper without a handover, and is reported); every `handover` is followed at `seq` + 1 by an `accept` whose `handover` is its `id`, whose `head` is its `hash` and whose `keeper` is its `keeper`; every `handover`'s `head` is the `hash` of the line before it; and the last custody line of the record is not an unaccepted `handover` unless it is the record's last line (the record is in transit, and `verify` says so without failing). A record that breaks one of these is reported `custody: broken` with the `seq` of the line, and the reference's `verify` exits non-zero; whether that belongs in SPEC §3, as a validity rule with a version bump, or stays here as a profile check, is open question 1.
9. **The former keeper's own record is their own.** A parent's record holds the parent's photographs of the child, the parent's notes about the child, the child's name on a thousand calendar entries. None of that is the child's record and none of it moves. Custody is about one folder, the one whose `owner_id` is the subject's. Whether the subject may ask for lines about them in someone else's record is a question for the circle, not for this profile.
10. **Encryption at rest.** When tiers 2–3 are sealed to the keeper's key (the draft RFC on encryption at rest, on its own branch until it takes a number), a handover must also carry the right to open them: a re-keying of the sealed lines or of the record data key to the new keeper's key, in the package and recorded in the `handover` line under `key`. This profile reserves the field and defers the mechanism to that RFC; a handover of a plain record (every record today) needs none.

## What `verify` proves, and what it does not

`verify` already proves that no line was removed, inserted or changed from GENESIS to the head (SPEC §3). With rule 8 it also prints the custody chain and proves that each change of hand sits at one seam in it, with nothing written in the gap:

```
valid — 48,211 lines, head 7c1e…9b02
custody:
  kept by 019cadd3-…-0a21 (Ola Nordmann) from 2008-04-12 (declare, seq 1)
  handed to the subject at seq 41,377 (reason age) · accepted at seq 41,378 · former keeper retains tiers [1] (crossing 019c…)
  kept by the subject since 2026-04-12
```

What it cannot prove is that the hand that wrote `handover` after a death, or `accept` at any time, was the hand it names. A chain proves continuity; identity is a signature's job, and the record is not yet signed (VISION: "where it can go"). Until it is, `authority` is a document the record holds and a person reads. When a signing RFC lands, `key` on the `accept` line is where the new keeper's key is first seen, and every later line is checked against it.

## Consent

> **Review wanted from a non-technical co-author.** This section sets the defaults that decide what a parent keeps of a child's record, what an executor sees, and what a partner takes away from a handover. They are proposals written by the people who built the chain, who are not the people these cases happen to. Please read it for what feels wrong, not for what is technically open; the questions at the end collect what we already know we do not know.

The record is the subject's and the consent that matters is the subject's. Where the subject can give it, the defaults below are what applies when they say nothing; where they cannot, the defaults are deliberately the narrow reading.

**A child takes the pen (`reason` `age`).** The parent retains nothing by default: `retains` is `{"tiers": [], "crossing": null}`. The parent's own record already holds the parent's side of every day the two spent together; the child's record is the child's from here, including the lines the parent wrote in it. A parent who wants a copy asks the child, now the keeper, for a crossing, as anyone in the child's circle does. The child may retract any line in their record, the parent's notes among them; a retraction hides and never removes (RFC 0003), so the parent's words stay in the chain under a mark, and the child should be told so plainly before they take the pen. Whether the parent's notes in the child's record should have been marked as the parent's words from the start is open question 3.

**A death (`reason` `death`).** The executor receives the whole record, every tier, because a record with a line missing is not a record (rule 3) and because settling an estate needs the money and the health lines most. The executor is the keeper, not the heir: their job is to hand the record on, with a second pair of lines, or to close it. What a closed record is (a last line, a frozen folder, a deletion the subject asked for in life) is open question 2. A subject who wants their record to pass to one person and not another says so in life with a `declare` line naming a `successor`; a will that says otherwise is a matter for the law, not for `verify`. The deceased's circle, the people in `policy/crossing.json`, keep what has already crossed to them and receive nothing more unless the executor exports it.

**Partners (`reason` `incapacity`, `agreement`).** A partner keeping a record through an illness is the keeper for that time and no longer: the handover back is the expected end, and the `retains` of that second handover is what the two agree. The default is nothing. The subject, taking the pen back, reads in the chain every day the partner held it and every crossing the partner exported in that time (ADR 0016: a crossing is never invisible), which is the point: the partner's stewardship is visible to the person it was for.

**In every case** the handover is made with the subject present where the subject can be: the `accept` line of a child taking the pen is the child's own act, at their own keyboard, and the reference will not write it for them from the parent's session.

## Example (synthetic)

A record kept by a parent from birth, handed to the child at eighteen. Ola Nordmann and the child are the Oslo persona and do not exist; the ids are made up.

The first line of the record, written by the parent on the day of birth:

```json
{"at":"2008-04-12T09:30:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"custody","tier":1,
 "payload":{"schema":"custody/v1","act":"declare",
 "keeper":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-043f5aabf2a9","registry":"logbook"}}}
```

Eighteen years later. The parent first exports a tier-1 copy for themself (a `crossing/v1` line, `destination` `ola`, `tiers` `[1]`), then writes the handover, the last line of their hand:

```json
{"at":"2026-04-12T10:00:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"custody","tier":1,
 "payload":{"schema":"custody/v1","act":"handover","reason":"age",
 "from":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-043f5aabf2a9","registry":"logbook"},
 "keeper":{"subject":true},"destination":"sigrid","tiers":[1,2,3],
 "head":"53d39fda0b4d7a1e3c9f8e2d1a0b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b",
 "counts":{"lines":41376,"by_tier":{"1":39102,"2":2201,"3":73},"attachments":{"included":3120,"bytes":9823341120,"missing":2}},
 "retains":{"tiers":[1],"crossing":"019cadd3-6bc0-7dcd-9133-043f5aabf310"}}}
```

The child's first line, at their own keyboard, `seq` one more:

```json
{"at":"2026-04-12T10:04:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"custody","tier":1,
 "payload":{"schema":"custody/v1","act":"accept","keeper":{"subject":true},
 "handover":"019cadd3-6bc0-7dcd-9133-043f5aabf311",
 "head":"9afdd1bd5f7e4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a1908f7e6d5c4b3"}}
```

A succession, written by an executor for a keeper who cannot write, the grant of probate attached:

```json
{"at":"2031-02-03T12:00:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"custody","tier":1,
 "payload":{"schema":"custody/v1","act":"handover","reason":"death",
 "from":{"subject":true},
 "keeper":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-043f5aabf2c4","registry":"logbook"},
 "destination":"executor","tiers":[1,2,3],"head":"1f0a9b53d39fda0b4d7a1e3c9f8e2d1a0b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e",
 "counts":{"lines":188402,"by_tier":{"1":171000,"2":16900,"3":502},"attachments":{"included":21004,"bytes":61203398144,"missing":0}},
 "retains":{"tiers":[],"crossing":null},
 "authority":{"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","path":"attachments/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","bytes":241088,"media_type":"application/pdf"}}}
```

## Notes

- **Why a line and not a field in `logbook.json`.** The file is bookkeeping that writers rewrite on every append (SPEC §1); the chain is what nobody rewrites. Who held the pen when is exactly the kind of fact the chain exists for, and reading it needs nothing outside the record (RFC 0006 made the same choice for people: the log is the registry).
- **Why two lines and not one.** One line can say that a hand let go; it cannot say that another took hold. The seam between the two is where a record in transit could be appended to, and two adjacent lines, each written by its own hand, make that seam one `seq` wide and checkable.
- **Why the handover is not a `crossing/v1` line.** It would be, except that the package contains it. The custody line carries the same facts in the same names (`destination`, `tiers`, `counts`, `head` for `logbook_head`) so a reader that joins crossings for an audit (RFC 0011 rule 5) can join handovers with them.
- **Why `tier` 1 MUST.** A keeper who cannot open tiers 2–3 must still see who kept the record; and a chain of keepers that was itself sealed could not be checked by `verify` without a key, which would make an unopened record unverifiable in the one respect that matters most to the person who just received it.

## Open questions

1. **Validity or report.** Should a broken custody chain (rule 8) make a record *invalid* under SPEC §3, which is a spec version bump, a regenerated conformance fixture and an ADR, or stay a profile check that `verify` reports and the reference exits non-zero on? The second keeps the format small; the first means a second implementation cannot call a record valid that was appended to in transit.
2. **Closing a record.** An executor who has settled an estate holds a record nobody will append to. Is there a last line (`act` `close`), is the folder simply kept, or may the subject ask in life for deletion after death, which the format has never allowed for any line (SPEC §3: nothing is ever removed)? The format's answer today is that the folder is kept; the question is whether that is the right answer for a whole life.
3. **Whose words.** Lines a parent writes in a child's record carry `source` `manual` like the lines the child will write. Should a kept record mark the hand that wrote each line (an `extra.hand` on manual lines during custody, or the keeper read off the custody chain at the line's `seq`, which rule 1 already allows), so the child can tell their own words from their parent's without a date calculation?
4. **The subject's consent at the handover.** Rule 4 makes the `accept` the new keeper's own act. Is that enough for a child, or should the handover also require the subject's acknowledgement when the new keeper is a third person (a `handover` from a parent to a step-parent, say) — a third line, or the subject's `accept` of someone else's keeping?
5. **Age.** The profile names no age at which a child takes the pen and no test of capacity for `incapacity`. It should not; but should it name the authority that does (the law of the subject's `tz`?), or leave that to the people entirely?
6. **A record started late.** A parent who kept no record and starts one for a ten-year-old writes a `declare` as line 1 at `at` ten years after `created_at`. Nothing forbids it; should the `declare` carry the subject's birth date or anything else, or is that the `owner.json` policy's job?
7. **The retained copy's future.** The former keeper's crossing package is frozen at the handover head. May they import it into a record of their own (RFC 0033 asks the same of an asset's lines) and under what `subject`, given that `subject` today names an asset and never a person (RFC 0001 rule 1)?
8. **Re-keying.** Rule 10 defers to the encryption RFC. If that RFC chooses per-line sealing to the owner's key, a handover re-seals every tier-2–3 line, and the bench (`bench-encryption-2026-10.md`) says what that costs; if it chooses a record data key, a handover re-wraps one key. The choice there decides whether a handover of a long record is a minute or an afternoon.
