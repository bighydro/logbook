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
logbook day reflect 2026-06-09 --audio evening.m4a --sign      # or close it by voice (below)
logbook serve                           # or on the Day page: Reflect, tick, Sign (below)
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

Only you sign: here, on the Day page of `logbook serve`, or through the door when you allow it
(below).

## Signing on the Day page

`logbook serve` is the Library, and its Day page is your own Sign path. At its foot, *Reflect and
sign* takes your reflection (typed, the day's Wispr Flow draft offered prefilled, or a recording
where this machine can hear one), shows the proposals the rules read in it as boxes, none ticked,
and Sign signs the day through the code `day reflect --sign` runs: the ticked delegations written as
notes, then `signing.sign` with every line on the page confirmed, your reflection among them, and
the ticked dispositions in the signature. The line is byte for byte what `logbook day reflect DAY
--sign --accept N,N` writes for the same reflection and ticks. A day you signed before is signed
again, the new line superseding the standing one and keeping what it said, and the page then shows
the signature with its page digest. It answers this machine only, and nothing is written until you
click ([serve](serve.md#reflect-and-sign)).

It needs no policy. The page is not the door: it never reads `policy/crossing.json`, and the `write`
list there may stay empty. The Purser, the orchestrator that builds your Day page elsewhere, remains
an alternative front door, through `sign_day` below, and only when you name the tool in that list.

## Signing through the door

An orchestrator that builds your Day page somewhere else, on a phone or a VPS, used to print a `day sign`
command for you to run by hand. When you name it in `policy/crossing.json`, `{"mcp": {"max_tier": 1,
"write": ["sign_day", "note_day"]}}`, it carries your verdict back itself through the MCP tool `sign_day`
(ADR 0022, RFC 0034 amendment 3): the same arguments as the flags, `confirm`, `kept`, `missed`, `dropped`,
`carried`, `note` and `at`, the same checks, the same supersession, through the same code, and the same line
`day sign` would have written, byte for byte. It never waits for another writer and never signs a day more
than 60 days back (`write_window_days`); without the entry it is refused in one sentence. Its companion
`note_day` keeps the proposals and your notes on the day as `note/v1` lines, so the page can be rebuilt from
the record alone ([the MCP server](mcp.md#write-tools)).

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

**When the day begins at `day_start`.** The day starts where the record says it does
([settings](settings.md#where-your-day-begins-day_start)), and `--at` is checked by the same rule
the index puts every line on its day by, so the moment you sign and the page you sign agree. With
`"day_start": "06:00"`, 01:30 on the 10th is still the 9th: `day sign 2026-06-09 --at
2026-06-10T01:30:00+02:00` signs the 9th, whose page is its lines up to 06:00 on the 10th, the
lines `day 2026-06-09` shows, and the same moment for the 10th is refused, since the 10th has not
begun (`--at … is before 2026-06-10 starts at 06:00 in Europe/Oslo`). The check is made when a
signature is written and never again: a signature already in the record stands as it was written,
even one whose moment would be too early under a boundary set later. No signature records the
boundary it was signed under; one written before `day_start` was set was signed under midnight.
Its page is read under the boundary the record has now, so a page the move changed reads `the
page has changed since` until you sign it again (RFC 0036).

## Closing the day by voice

At the end of the day you say a few sentences about it: what went out, what did not, what you will do
tomorrow, what Ola should do. `logbook day reflect` makes that the close of the day. The words become
part of the record, and what you said about your commitments, and about what others should do, is
proposed to you, so that the day can be signed with it in one go.

```bash
logbook day reflect 2026-06-09 --audio evening.m4a        # a recording, heard on this machine
logbook day reflect 2026-06-09 --text "The photos went out. Ola should book the ferry."
logbook day reflect 2026-06-09 --mic 60                   # on macOS: sixty seconds from the microphone
logbook day reflect 2026-06-09                            # the Wispr Flow dictation that begins with "reflect"
logbook day reflect 2026-06-09 --from-wispr               # take that dictation as it is
logbook day reflect 2026-06-09 --dry-run                  # what it would write, and nothing written
logbook day reflect 2026-06-09 --sign --accept 3,6        # sign the day with the proposals you accept
```

**The reflection** is one `note/v1` line on the day (RFC 0010: tier 2, as every note is, whoever writes
it), source `reflect`, with `reflection` in its `labels`, the same convention `note_day` uses through the
door, and written through the same code. `--text` is typed; `--audio FILE` is heard by the local whisper
engine of the `openlogbook[transcribe]` extra, exactly as `derive transcripts` hears a voice memo: nothing
leaves the machine, the hub is offline while it listens, and a model that is not on the machine stops the
command until you run it once with `--fetch-model`. Without the extra, `--audio` says which extra to
install; `--text` always works. `--mic SECONDS` records from the default microphone on macOS with ffmpeg,
then hears it the same way, and keeps no recording; elsewhere, without ffmpeg, or with no microphone, it
says so in a sentence. The reflection is printed back a sentence a line, numbered. Without `--sign`,
nothing else is written. The same words already on the day are not written twice: run the command again
and it reads the reflection that is there.

**The Wispr Flow convention.** If you dictate with Wispr Flow all day, there is no new habit: a dictation
that begins with the word *reflect* is the reflection. The first word counts, in any case, after any
spaces and punctuation: "Reflect: a long day on the water...", "reflect, the photos went out...". The
word must be *reflect* itself; "reflection" or "reflecting" does not count, and neither does the word
later in a dictation. `logbook day reflect DAY` with no input offers the latest such dictation of the day
as the draft, without that word: on a terminal you answer y to take it, e to type it again as it should
read, or n to leave it; elsewhere it prints the draft and writes nothing until you say `--from-wispr`.
`--from-wispr SEQ` takes the dictation with that seq instead. The note keeps the dictation's id under
`extra.dictation` and the moment you spoke as its `at`, and a dictation taken up is not offered again.
The dictation itself stays what Wispr Flow made it, tier 3; the reflection is a note and tier 2, because
you confirmed it as one.

**The proposals** are read out of the reflection by rules, no model, with the cue tables `promises` uses,
and printed numbered, each with its evidence; every one is a guess until you accept it:

- **commitment** — a sentence that reads as your promise: "I'll fix the bilge pump on Saturday", "ich
  werde die Rechnung morgen bezahlen", with the day its date phrase names. The reflection is a note in
  your words, so `promises` lists it from the reflection itself; accepting it writes nothing more.
- **delegation** — what someone else should do: "ask Ola to ...", "tell Ines to ...", "Ola should ...",
  "Ola must ...", "Ola soll ...", "frag Ines, ob ...", "Ola, can you ...", with the name as you said it.
  A name is a capitalised word or two that is not a pronoun or a day and does not follow an article ("Die
  Fähre soll ..." asks no one). Accepted, it is one more `note/v1` line on the day, label `delegation`,
  `extra.to` the name and `extra.reflection` the reflection's id: no profile `promises` reads requests
  from fits a request you make of someone else, so it is a note, in your words.
- **kept, missed, dropped, carried** — a sentence that says what became of a commitment already on the
  day's page: "went out", "done", "sent" for kept; "didn't", "not yet" for missed; "drop", "forget it"
  for dropped; "tomorrow", "next week" for carried; and their German ("erledigt", "noch nicht", "vergiss
  es", "morgen"). The first such word in a sentence decides. The sentence must also be about the
  commitment: its words and the commitment's (casefolded, three letters or more, a plural *s* dropped,
  function words, days and the disposition's own words left out) overlap by a Dice coefficient of 0.5 or
  more, `reflect.MATCH`; the best match wins. "The mooring photos went out to the harbour office" matches
  "I'll send the mooring photos to the harbour office by Friday" at 0.89; "The harbour office sent a
  letter about the berth fee" shares two of its five words with it, 0.4, and is no reference. Accepted, the
  disposition goes into the signature.

**`--sign`** signs the day after the proposals are printed, in one go, through the same `signing.sign`
`day sign` calls. You say which proposals you accept with `--accept N,N` (or `--accept none`); on a
terminal it asks y or n for each delegation and disposition, and q stops with nothing written. Without a
terminal and without `--accept`, it prints the proposals and refuses, writing nothing. Then, under one
hold of the writer lock: the reflection is written (unless it is on the day already), each accepted
delegation is written, and the day is signed: the reflection and the delegations among the lines
confirmed, the accepted dispositions in the signature, and `--at` (the moment you spoke, with an offset or
`Z`, on the day) as both the reflection's moment and the signature's. The signature is byte for byte the
one `day sign DAY --kept ... --at ...` writes over the same page. A day you signed before is signed again,
superseding the standing signature as RFC 0034 allows, and keeping what it said: the lines it confirmed
that are still on the page, its dispositions (an accepted one wins on a line they share) and its note,
with the reflection added. Two accepted proposals that give one line two dispositions, a number no
proposal has and a moment off the day are each refused before anything is written. Another writer
holding the record (with `--no-wait`) and a head that moved while the page was read are the store's own
errors, said in one sentence; nothing is retried. `--note`, `--confirm` and the four disposition flags
stay with `day sign`.

**Where it shows.** `logbook day` prints the reflection in a section of its own, labelled `reflection`
with the time you spoke: your words in your voice, below the header and above the record, the timeline
and everything after it. The Day page of `logbook serve` shows it the same way, under *Reflection*, and
at its foot lets you write it and sign the day with it ([above](#signing-on-the-day-page)).
`day --json` carries it under `reflection` (`line`, `seq`, `at`, `at_local`, `source`, `text`), a key
that is there only on a day that has one, so every other Day's object, the conformance sample's among
them, is unchanged. The latest reflection standing is the one shown; retract it and the one before it
stands. The reflection is still a note of the day like any other: `show` lists it, and the MCP tool
`day_lines` returns it as it returns every note, under the ceiling.

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

A destination that should see only what you have looked at lately gets `signed_within_days` on its
entry in `policy/crossing.json` (RFC 0036, draft): `{"cloud-model": {"max_tier": 2, "until":
"2026-12-31", "signed_within_days": 14}}` crosses, through that entry, only the lines of days whose
standing signature you wrote in the last fourteen days, today included; a day unsigned or signed
earlier crosses nothing but its header, the day and its signed state. Signing a day again
refreshes it. Absent, there is no restriction, which is the behaviour above. The key is the
entry's, not the command's, so it holds for every crossing that reads the entry, the shared page,
the bundle, the vault, the site and the MCP read tools included, and `--unsigned` does not lift it;
the tier ceiling and `until` apply on top, as always.

## In the conformance sample

`conformance/sample-logbook` signs its first day on its last evening, so a verifier meets the
profile and `show 2026-03-01` prints `signed` in its header.
