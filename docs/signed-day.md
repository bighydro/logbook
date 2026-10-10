# The signed day

Agents draft. The owner signs. Only signed days cross.

A record fills itself: the tracker writes the points, the mail import writes the threads, a
calendar sync writes the entries, and an agent with MCP may run the adapters and draft. None of
that is you reading the day. The signed day is: you open the page, you read it, and you say *these
are the day's facts*. That sentence is one line in the chain, and it is the gate on what leaves the
record.

```bash
logbook show 2026-06-09                 # read the page; the header says `unsigned`
logbook day 2026-06-09                  # the Day: the readiness row says whether every usual source is in
logbook day sign 2026-06-09             # sign it: every line on the page is confirmed
logbook day sign 2026-06-09 --note "Quiet day. The call with Kari was the thing."
logbook day sign 2026-06-09 --confirm 4181,4183   # only these lines, by seq or id as `show` lists them
logbook day sign 2026-06-09 --kept 4181 --carried 4183   # and what became of the commitments on them
logbook day sign 2026-06-09 --confirm none               # nothing on the page is a fact of the day
logbook day sign 2026-06-09 --at 2026-06-09T19:30:00+02:00   # signed when you clicked, not when this ran
logbook show 2026-06-09                 # the header now says `signed 2026-06-10 08:15`
```

## What signing writes

One line, `signed-day/v1` (RFC 0034, `docs/rfcs/0034-the-signed-day.md`), tier 1, source
`manual`, appended through the same `append` every other line goes through. It carries:

- the day signed, and you as its subject (the record's `owner_id`);
- the ids of the lines you confirmed, in the page's order: every line on the page unless
  `--confirm` names some, or none at all with `--confirm none` (below);
- the digest of the page as shown: the SHA-256 over the hashes of the lines the page listed, in
  order. Not over the text: the words are a reader's own, the lines are the record's. Anyone with
  the record recomputes it, and a day that grew after you signed is seen to have;
- an optional one-line note, in your words, tier 1 because it crosses with the day;
- when the day was signed before, the id of the signature this one supersedes;
- optionally, what became of the commitments on the page (below): by line id, `kept`, `missed`,
  `dropped` or `carried`.

It rewrites nothing. A day that was wrong is corrected the way the record corrects anything, by
new lines, and then signed again; the later signature stands and the earlier stays in the chain.
Retracting a signature (`repair retract SEQ`) leaves the earlier one standing, or the day unsigned.

Only you sign. The MCP server has no tool for it and never will; an agent that wants a day signed
asks you.

## What the readers say

`logbook show DAY` prints the state in its header, `2026-06-09  unsigned` or `2026-06-09  signed
2026-06-10 08:15`, and lists a signature on the day it was written as any line. `logbook day DAY`
prints the same after the weekday, with `, the page has changed since` when a line was added to
the day after you signed, and carries it in `--json` under `signed`: when, which line, how many
lines were confirmed and on the page, the page digest, whether the page still matches, the note.

## Dispositions: what became of the commitments

A page has commitments on it: a note that says "I'll send the mooring photos by Friday", a
transcript in which you said you would book the crane. The evening you sign the day is when you
know what became of them, so the signature can say so (RFC 0034, amendment 1):

```bash
logbook day sign 2026-06-09 --kept 4181 --missed 4190 --dropped 4192 --carried 4183,4185
```

Each flag takes lines by seq or id as `show` lists them, and a line given one is confirmed by that,
whatever `--confirm` says. The four words:

- **kept**: it was done. `promises` closes it.
- **missed**: it was not, and you say so. `promises` closes it and says `missed on 2026-06-09`.
- **dropped**: you let it go on purpose. `promises` closes it, with nothing to flag.
- **carried**: still open, taken to a later day. `promises` keeps it open; you dispose of it when you
  sign the day it was kept or missed on.

A line that is not on the page, a retracted line, a line named twice (in one flag or two, by seq or
by id) and a flag that names no line are each refused in a sentence, and nothing is written. The
field is optional: a signature without it is what it always was.

On a signed day `logbook day` prints the symbol before each line you disposed of, on the line's
own row: ✓ kept, ✗ missed, – dropped, → carried; an unsigned day, and a line given none, print as
before. `--json` carries the map under `signed.dispositions`. `show` lists the counts on the
signature's row (`kept 2, missed 1`). `logbook promises` reads the standing signature of each
promise's day: kept and dropped are done, missed is done and flagged, carried is open, and
`--open` hides the first three. The crossing carries the field with the line.

## Confirming nothing, and the moment you signed

Two things a day signed from a phone needs (RFC 0034, amendment 2).

**`--confirm none`.** You read the page, you untick every proposed fact, and the day is still
signed: the line carries an empty `confirmed`, the page digest is still over what you were shown,
and the header says `signed` as for any signature. The day's lines cross with it, as the lines of
any signed day do: the gate is the signature, not the list. The word goes alone: `--confirm
none,4181` and `--confirm none --kept 4181` are each refused in one sentence, because a line given
a disposition is confirmed by that. `--confirm ""` is still refused as naming no line, so an empty
shell variable never signs a day by accident; you type the word.

**`--at RFC3339`.** The signature carries the moment you clicked, not the moment the command ran:
`--at 2026-06-09T19:30:00+02:00`, with an offset or `Z`, stored in UTC like every `at` in the
record and shown by `show` and `day` in the record's local time (`signed 2026-06-09 19:30`). Three
things are refused, each in a sentence with nothing written: a moment that is not RFC 3339 with an
offset or `Z` (the message shows the shape); a moment more than five minutes ahead of this
machine's clock (a phone runs a few minutes fast, never hours); and a moment before the day you
are signing starts, in the record's zone. Without `--at`, the signature is at now, as before.

## Readiness: is the day all in?

Before signing you want to know whether everything that usually arrives has arrived. The Day's
`readiness` row says, for six classes of source, whether the day has lines of it and which usual
sources have not delivered:

```
  readiness     mail none · message present · meeting none · location present, missing dawarich · photo present · calendar present
```

The classes are mail, message, meeting (a transcript), location, photo and calendar. A source is
*usual* for a class when it delivered that class on four in five of the logged days of the last
four weeks and `policy/import.json` has not disabled it. `none` means nothing is in and nothing
usually is; `missing <source>` names what has not come. It is computed from the record and the
policy alone: no connection is opened, nothing is written. It is advice, not a gate: sign a day
with the tracker missing when you know the phone was off.

## The gate on the crossing

`logbook export crossing` (RFC 0005, the package a member of your circle pulls) crosses, by
default, only the lines of days you have signed: a line's day is the local day of its `at`, and a
signature crosses with the day it signs. The console says how many lines were held back on
unsigned days, and `--unsigned` crosses them too. The tier ceiling (ADR 0016) still applies on top:
a tier-3 line on a signed day never crosses without the policy and `--tier 1,2,3`. The manifest
records which it was (`policy.signed_days`, `only` or `any`), and so does the `crossing/v1` line
the export appends (`policy.signed_only`).

The shared page (`export share day`), the trip bundle, the vault and the site keep their own
selections and are not gated by signatures.

## In the conformance sample

`conformance/sample-logbook` signs its first day on its last evening, so a verifier meets the
profile and `show 2026-03-01` prints `signed` in its header.
