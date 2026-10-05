# RFC 0028 — payload profile `story/v1`

Status: frozen for v1.0 as to the fields the Day reads · 2026-10-05 (RFC 0031 question 5; fixture `conformance/profiles/story/`) · **draft, unfinished** · 2026-10-03 · comment period: two weeks once the author has closed the open questions at the end

A *told* story, as distinct from an observed event. "In 1961 we moved to the house by the lake" is not something the record saw happen; it is something one person said to another, on a day the record did see, about a time it did not. Every other profile so far records an observation — a fix, a photo, a calendar entry, a transcript of a meeting — made at the instant the line's `at` names. This profile records testimony: the thing told, the time it is about at the precision the teller gave it, who told it, who heard it, how sure the teller said they were, where it came from, and the transcript it was lifted from when there is one.

The one instant anyone observed is the telling. The story's `at` is `told_at`, and the story is on the day it was told. What it is *about* is a claim, kept as a claim: `refers_to`.

## Line

`kind` MUST be `story`. `tier` SHOULD be 2 and MUST NOT be 1: a story carries someone else's words, the class of content SPEC §4 puts under tier 2 (notes, messages, confirmations), and a producer MAY write 3 for a reason it states (`logbook add story --tier 3`). `at` is `told_at`, when the story was recorded; `end` is `null`. `source` is the producer: `manual` when the owner wrote it down or added a file at the command line; an adapter's name when a tool lifted it out of something it imported.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"story/v1"` | MUST | |
| `raw_id` | string | MUST | the dedupe key; the reference writes `story:<sha256 of the file's bytes>`, so a file added twice is one line |
| `text` | string | MUST | the thing told, plain text, verbatim: the teller's words as recorded, or the listener's write-down of them |
| `title` | string | MAY | a name for the story, when the file or the transcript gave one |
| `told_at` | RFC3339 UTC | MUST | when the story was recorded; equal to the line's `at` |
| `refers_to` | object | SHOULD | the time the story is about, as told and as a span: `{ text, from, to, precision }` (below). Absent when the story names no time at all |
| `teller` | object | MUST | who told it: `{ ref: { kind, value }, name? }`, an RFC 0006 ref as the raw lines carry it (`email`, `phone`, `handle`, `provider_id`, …) and the label known when the line was written, so the line reads without any registry |
| `listener` | object | MUST | who it was told to, the same shape; the owner, in most records, by one of their own refs |
| `confidence` | string | SHOULD | how sure the teller said they were: `sure`, `fuzzy` or `disputed`. Absent means the teller did not say. This is the **teller's** statement, never a reader's estimate (see Notes) |
| `source` | string | SHOULD | where the words came from: `conversation`, `voice-memo`, `interview`, `letter`, `written`, or another word; an open vocabulary. Distinct from the envelope's `source`, which names the producer |
| `transcript` | object | MAY | the transcript the story was lifted from, as a SPEC §1.1 attachment reference `{ sha256, path, bytes, media_type }` |
| `transcript_line` | string | MAY | the `id` of the `transcript/v1` line (RFC 0004) in this record the story came from, when it is there |
| `supersedes` | string | MAY | the `id` of an earlier story line this one replaces: the same story told again, a year put right |

Anything else the producer knows MAY go under `extra`.

### `refers_to`

```json
{"text": "1961", "from": "1961-01-01", "to": "1961-12-31", "precision": "year"}
```

`text` is the time as told, verbatim. `from` and `to` are the first and last local day the story is about, inclusive, as `YYYY-MM-DD`, or both `null`. `precision` says how the span was read: `day`, `month`, `year`, `decade`, or `phrase`. The reference reads four shapes into a span — `1961` (a year), `1961-05` (a month), `1961-05-04` (a day), `1950s` (a decade) — and keeps any other words as a `phrase` with no span: "before the war", "the summer I turned ten", "when grandmother was a girl". A phrase is on no day; it is still the story's time, and a reader prints it as told. Words that begin with a digit and are none of the four shapes (`1961-5`, `196`) are a mistake, not a phrase, and the producer refuses them.

A later revision MAY add a span written out (`1961..1963`, `1961-05/1961-08`) and a precision for it; a reader that meets a `precision` it does not know treats the span as `from`–`to` when both are there, else as a phrase.

## Rules

1. **A story is on the day it was told, never on the day it is about.** `at` is `told_at`. A reader that lists a day's lines (`show`, SPEC §3.2.1) lists a story on its told day with its mark. No reader places a story's line on a day inside `refers_to` as if it had been observed there (see *Why a story is never placed on the day it refers to*).
2. **`refers_to` is a claim at the teller's precision.** A producer MUST NOT sharpen it: a year stays a year, a decade a decade, a phrase a phrase. A listener who knows better writes a second story, or a note, and never edits the first.
3. **`confidence` is the teller's.** It records what the teller said about their own memory. A reader that forms its own view of a story's reliability keeps that view outside the line.
4. **People are refs.** `teller` and `listener` carry refs and the label known at the time; a reader names them through the record's resolution lines (RFC 0006, the alias walk), falling back to the written `name`, then to the ref's value. Nothing is resolved into the line.
5. **The words are the story's; the transcript is pointed at.** When a story is lifted from a transcript, `text` carries the words and `transcript` references the attachment the transcript adapter stores (SPEC §1.1), so the two lines share one file and nothing is copied. A story read from a text file carries its text inline, as a note does (RFC 0010); the file itself is not stored.
6. **Standing.** A story is standing when it is not retracted (RFC 0003) and no later story line names it in `supersedes`. Readers of what a day is about take the standing stories.
7. **About a day.** A standing story is *about* a local day when `refers_to.from ≤ day ≤ refers_to.to`. A story with no span is about no day. A decade is about every day in it: `day 1955-03-02` lists a story that refers to the 1950s, because that is what the teller said.

## Why a story is never placed on the day it refers to

The envelope's `at` is *when the thing happened* (SPEC §2), and everything downstream trusts it: the month file a line is written to, the day `show` lists it on, the lines a Day attaches to a stay, the evidence that promotes a cluster of fixes into a stay (§3.2.3 rule 5), the `sources` row that says which trackers spoke that day, the window a rollup counts. Every one of those readings assumes that a line dated 4 May 1961 is something that was observed on 4 May 1961.

A story is not. Its `refers_to` is a claim: made decades later, by one person, at whatever precision their memory gave ("1961", "the fifties", "before the war"), and sometimes disputed by the next person asked. If the line were dated by that claim:

- The record would say a day in 1961 had an observation, from source `manual`, when nothing was observed; `sources` would count a tracker that did not exist.
- A year or a decade has no instant to date a line by; the line would carry a made-up midnight on a made-up first of January, and the precision the teller gave would be lost in the envelope even if kept in the payload.
- Two stories about the same year by two tellers who disagree would sit on the same invented day as two facts, where they are two testimonies.
- The telling itself — a real event on a real day, often the only time two people sat down and talked about it — would be lost as an event of that day.

So the line is dated by what was observed, the telling, and what it refers to is in the payload, as a claim with its precision. The Day of 4 May 1961 then lists the story under its own heading, *Stories about this day*, apart from the timeline: a reader sees at once that the timeline holds what was observed and the stories hold what was told. The told day lists the story as a line of its own, as `show` lists a note: the telling is what happened that day.

## Readers

**`show <told day>`** prints a story as `📖 refers to <when> — told by <name> to <name>`: `when` is `refers_to.text` as told (`an unsaid time` when there is none), the names through the resolution lines. `--raw` prints the refs' values as given, never a name.

**`day <date>`** lists, after the unplaced lines and before the health line, the standing stories whose `refers_to` covers the date under the heading *Stories about this day*: each as `show` prints it, with the teller's `confidence` and the day it was told, and its first line under it. The Day's JSON carries them under `stories` (`line`, `told_at`, `title`, `text`, `refers_to`, `teller`, `listener`, `confidence`, `source`); SPEC §3.2.7 gains that field when this RFC is accepted. The stories are never in `timeline`, `unplaced` or `sources`, and the told day does not list the story as unplaced: a story is not a placeable observation.

**`show person <name>`** (not implemented in this draft) MAY list, apart from the shared days, *Stories told by* and *Stories told to* this person, each with its `refers_to` as told, most recently told first; and the stories *about* a span the person page covers, when the page has one. They are testimony about the person, or by them, and belong beside the shared days, never counted among them: a story is not a day together.

**`year <YYYY>`** and a future **`year --print`** MAY end with a section *Stories about this year*: the standing stories whose span overlaps the year, each as told, with teller, listener and confidence, so a printed year of 1961 — a year the record never observed — can carry what the family said about it, and a printed year the record did observe can carry what was later said about it. They are listed after the observed sections and are not counted in the year's numbers.

**`promises`** and the with module never read a story. A sentence in a story is not a commitment of anyone's, and a name in a story is not company at a stay.

## Example (synthetic)

Ola Nordmann telling Kari Nordmann, one evening in June 2026, about a move in 1961. Neither exists.

```json
{"at":"2026-06-10T18:30:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"story","tier":2,
 "payload":{"schema":"story/v1",
  "raw_id":"story:5a6b1f0e8c3d9a7b2e4f6c8d0a1b3c5e7f9a0b2c4d6e8f0a1b3c5d7e9f1a3b5c",
  "title":"The house by the lake",
  "text":"In 1961 we moved to the house by the lake. Father rowed the furniture across in two trips; the piano went last, on a raft he had built that morning.",
  "told_at":"2026-06-10T18:30:00Z",
  "refers_to":{"text":"1961","from":"1961-01-01","to":"1961-12-31","precision":"year"},
  "teller":{"ref":{"kind":"email","value":"ola@example.org"},"name":"Ola Nordmann"},
  "listener":{"ref":{"kind":"email","value":"kari.nordmann@example.org"},"name":"Kari Nordmann"},
  "confidence":"sure",
  "source":"conversation"}}
```

The same, lifted from a voice memo's transcript already in the record:

```json
{"at":"2026-06-13T17:30:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"story","tier":2,
 "payload":{"schema":"story/v1",
  "raw_id":"story:9c8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b",
  "title":"Kari asks about the summer of fifty-five",
  "text":"Kari Nordmann: When did the family first sail out here?\n\nOla Nordmann: The summer of fifty-five. We had a wooden boat with a brown sail; my uncle had built it the winter before.",
  "told_at":"2026-06-13T17:30:00Z",
  "refers_to":{"text":"1950s","from":"1950-01-01","to":"1959-12-31","precision":"decade"},
  "teller":{"ref":{"kind":"email","value":"ola@example.org"},"name":"Ola Nordmann"},
  "listener":{"ref":{"kind":"email","value":"kari.nordmann@example.org"},"name":"Kari Nordmann"},
  "source":"voice-memo",
  "transcript":{"sha256":"7ed527057371e8656f8754fe8e7492c4bc2355234ec458c19d22f4f6ba060354","path":"attachments/7ed527057371e8656f8754fe8e7492c4bc2355234ec458c19d22f4f6ba060354","bytes":158,"media_type":"text/markdown"},
  "transcript_line":"019cadd3-6bc0-7dcd-9133-0000000000a1"}}
```

## The reference producer

`logbook add story <file>... --teller <ref> --listener <ref> [--refers-to <when>] [--confidence sure|fuzzy|disputed] [--at <RFC3339>] [--tier 2|3]` writes one line per file:

- A **text or Markdown file**: the body is `text`; a leading `# heading` is `title` and is dropped from the text; a leading front-matter block (`---` … `---`, one `key: value` per line) MAY carry `title`, `teller`, `listener`, `refers_to`, `told_at`, `confidence` and `source`. A flag wins over the front matter. `told_at` is `--at`, else the front matter's, else now.
- A **transcript/v1 JSON** (the shape the transcript adapter reads, RFC 0004): `text` is the transcript's text when the file holds it inline, else its summary, else its title; `told_at` is the transcript's `at`; `title` its title; `source` `voice-memo`; the transcript's bytes go to the attachment store and `transcript` references them; `transcript_line` is set when the record holds the transcript/v1 line with the same `(source, raw_id)`.
- A ref is `kind:value` (an RFC 0006 kind), an address, a `+` number, or a **name** the record's resolution lines make one person, in which case one of that person's refs stands for them (an address before a number) and `name` is the record's label.
- Every file is read and every flag checked before anything is written; a mistake exits 2 with nothing appended.

## JSON Schema

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"story/v1","type":"object",
 "required":["schema","raw_id","text","told_at","teller","listener"],
 "$defs":{
  "person":{"type":"object","required":["ref"],
   "properties":{"ref":{"type":"object","required":["kind","value"],
     "properties":{"kind":{"type":"string","minLength":1},"value":{"type":"string","minLength":1}}},
    "name":{"type":"string","minLength":1}}},
  "attachment":{"type":"object","required":["sha256","path","bytes","media_type"],
   "properties":{"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"path":{"type":"string","pattern":"^attachments/[0-9a-f]{64}$"},
    "bytes":{"type":"integer","minimum":0},"media_type":{"type":"string","minLength":1}},"additionalProperties":false}},
 "properties":{
  "schema":{"const":"story/v1"},
  "raw_id":{"type":"string","minLength":1},
  "title":{"type":"string","minLength":1},
  "text":{"type":"string","minLength":1},
  "told_at":{"type":"string","format":"date-time"},
  "refers_to":{"type":"object","required":["text","from","to","precision"],
   "properties":{"text":{"type":"string","minLength":1},
    "from":{"type":["string","null"],"format":"date"},"to":{"type":["string","null"],"format":"date"},
    "precision":{"type":"string","enum":["day","month","year","decade","phrase"]}}},
  "teller":{"$ref":"#/$defs/person"},
  "listener":{"$ref":"#/$defs/person"},
  "confidence":{"type":"string","enum":["sure","fuzzy","disputed"]},
  "source":{"type":"string","minLength":1},
  "transcript":{"$ref":"#/$defs/attachment"},
  "transcript_line":{"type":"string","minLength":1},
  "supersedes":{"type":"string","minLength":1},
  "extra":{"type":"object"}},
 "additionalProperties":false}
```

## Notes

- **Why not a `note/v1` with a date in it.** A note is the owner's own words (RFC 0010 rule 4) and has no teller, no listener and no claim about another time that a reader can place. The day a story is about is the whole point of keeping it.
- **Why not a `transcript/v1`.** A transcript records that a conversation happened and what was said in it, whole. A story is one thing said in it, about another time, with the speaker and the hearer named as such and the claim about time lifted out so a Day can find it. The two point at each other and neither replaces the other.
- **Why `told_at` is in the payload when `at` carries it.** So the payload is complete on its own, as `keeper/v1` repeats the photo's `at` (RFC 0024): a story crossing into a bundle, or shown without its envelope, still says when it was told.
- **Why `confidence` is words and not a number.** A number would read as a reader's estimate, and this is the teller's statement about their own memory. Three words are what people say: I am sure; it is hazy; your aunt says otherwise.
- **Privacy.** A story is often the most personal line in a record, and it is about people who may not be the owner and may not be alive. Tier 2 is the floor, not a ceiling; a crossing policy (RFC 0005, ADR 0016) that lets tier 2 cross should be looked at again before stories are shared.

## Open questions for the author

This draft was written by a coding agent to get the shape and the reference producer in place. The questions below are the ones that need a person who has sat down with a family and listened, not a programmer. Answer them in this section or in the text above, then strike the *unfinished* from the status line and start the comment period.

1. **Who is the listener when nobody was.** A letter has a writer and a reader; a diary entry from 1961 has a writer and nobody. Is `listener` the owner by default when a story is read out of a letter or a diary, or should `listener` be optional, with `source` `letter` saying why it is absent? The reference requires it today.
2. **What `source` should mean, and its words.** The draft offers `conversation`, `voice-memo`, `interview`, `letter`, `written` and leaves the list open. Are those the right words, and should the field be called `source` at all, given the envelope has a `source` too? `medium` and `heard_in` were considered.
3. **How fuzzy a time may be, and how it is written.** The four shapes the reference reads (a year, a month, a day, a decade) cover "1961" and "the fifties". They do not cover "between the wars", "the year Kari was born", "every summer until I was ten", or a span given with two ends. Should the profile define a written span (`1961..1963`) and relative anchors (another person's birth year, a named event) in this version, or leave them as phrases for a later one? A phrase is on no Day; a family's stories are often phrases.
4. **When two people disagree.** Ola says 1961, Kari says 1962. Two stories, each with its own `confidence`? One story with `confidence` `disputed` and the other version in the text? Or a second story that `supersedes` nothing and carries `extra.disputes` pointing at the first? The draft allows all three and recommends none.
5. **Whether a story may be about a person or a place, not a time.** "Grandmother kept bees behind the schoolhouse" names no year. Should `refers_to` have siblings — `about_people`, `about_place` — so a person page or a place page can list the stories about them, or is that a resolution-style line of its own, written later, that points at the story?
6. **The told day.** Is listing a story on its told day in `show`, as a line of that day, right? Or is the telling only the record's bookkeeping, and the story should appear nowhere but under *Stories about* headings? The draft argues the telling is an event of its day and keeps it; the author may know otherwise.
7. **Whose tier.** A story told by a living person about a dead one: tier 2 as written, or 3, as with health and money, because the teller cannot be asked again and the subject cannot answer? Should `--tier 3` be the default when `confidence` is `disputed`?
8. **The listener's own words.** When the listener writes the story down from memory the same evening, `text` is the listener's paraphrase, not the teller's words. Should the profile mark that (`verbatim: false`, or `source` `written`), so a reader knows whose sentences it is reading?
9. **The name of the heading.** *Stories about this day* is the draft's wording for a Day; a decade's story then appears under "this day" for 3,652 days. Would *Stories about this time* read better, and should a Day say what precision the story was told at (`refers to 1950s` already does, in its row)?
10. **Whether `refers_to` belongs in the index.** The reference finds a day's stories by reading every story line of the record, which is fine for hundreds and slow for a million. If stories stay few, nothing changes; if a family archive is imported at scale, the index would need `refers_from` and `refers_to` columns. Is that scale real?
