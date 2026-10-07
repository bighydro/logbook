# The signed day

Agents draft. The owner signs. Only signed days cross.

A record fills itself: the tracker writes the points, the mail import writes the threads, a
calendar sync writes the entries, and an agent with MCP may run the adapters and draft. None of
that is you reading the day. The signed day is: you open the page, you read it, and you say *these
are the day's facts*. That sentence is one line in the chain, and it is the gate on what leaves the
record.

```bash
logbook show 2026-06-09                 # read the page; the header says `unsigned`
logbook day 2026-06-09                  # the Day, with the same header
logbook day sign 2026-06-09             # sign it: every line on the page is confirmed
logbook day sign 2026-06-09 --note "Quiet day. The call with Kari was the thing."
logbook day sign 2026-06-09 --confirm 4181,4183   # only these lines, by seq or id as `show` lists them
logbook show 2026-06-09                 # the header now says `signed 2026-06-10 08:15`
```

## What signing writes

One line, `signed-day/v1` (RFC 0034, `docs/rfcs/0034-the-signed-day.md`), tier 1, source
`manual`, appended through the same `append` every other line goes through. It carries:

- the day signed, and you as its subject (the record's `owner_id`);
- the ids of the lines you confirmed, in the page's order: every line on the page unless
  `--confirm` names some;
- the digest of the page as shown: the SHA-256 over the hashes of the lines the page listed, in
  order. Not over the text: the words are a reader's own, the lines are the record's. Anyone with
  the record recomputes it, and a day that grew after you signed is seen to have;
- an optional one-line note, in your words, tier 1 because it crosses with the day;
- when the day was signed before, the id of the signature this one supersedes.

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
