# RFC 0046 — What you heard: the words of the podcasts and videos you played (`heard/v1`)

Status: draft · 2026-10-21 · comment period: two weeks · implemented with `sync heard` and `logbook show heard` ([docs/heard.md](../docs/heard.md))

The record knows that the owner played an episode (`listen/v1`, RFC 0019) or a video (`watch/v1`, RFC 0018): the title, the show or the channel, when. It does not know what was said in it. A podcast's feed often publishes the episode's words (`<podcast:transcript>`, which the Apple Podcasts adapter already keeps as a URL and never fetches); Apple Podcasts on the Mac caches the transcripts it shows; a video has captions. This RFC adds those words to the record: one new line per episode or video whose text the record holds, the text itself in the attachment store, and the step that fetches or reads it.

`heard/v1` is a new profile, not among RFC 0031's freezes: its schema may change while this RFC is a draft. The envelope (SPEC §2–3) does not change: no spec version bump, no conformance fixture, no ADR. `listen/v1` and `watch/v1` are not amended. RFC 0044 and 0045 are being written in parallel; this is the next free number.

## 1. Words

- A **work** is one podcast episode or one video: what a `listen/v1` line with `media` `episode`, or a `watch/v1` line with `action` `watched` and a `video_id`, names.
- A **text** is the words of a work as someone published or produced them: a transcript, captions. It is someone else's words, published to anyone; it is not a conversation the owner had (that is `transcript/v1`, RFC 0004).
- A **text source** is where a text came from:
  - `feed` — the transcript the podcast's own feed publishes (`<podcast:transcript>`, podcasting 2.0), fetched once from the URL the listen line keeps under `extra.transcript_url`;
  - `apple` — the transcript Apple Podcasts on this Mac generated and cached for its own player, read where it lies;
  - `captions` — a video's published captions, as the owner supplied them (§6.3);
  - `local` — a transcription made on the home machine from audio the owner already holds. Named here so the field's values are complete; nothing writes it yet (§6.4).

## 2. The tier: 2

SPEC §4 puts what was said to the owner at tier 2 (notes, messages, personal mail) and public activity at tier 1. A podcast's or a video's words are neither: nothing in them was said *to* the owner; they were broadcast, and anyone may read them at the URL they came from. Read on its own, the text is public matter and could be tier 1.

The line is not the text on its own. Its one job is to join the text to a `listen/v1` or `watch/v1` line, and both of those are tier 2 by a MUST ("what the owner watches is as private as what they read"). A `heard/v1` line says *the owner played this, and here is what it said*: it is derived from a tier-2 line, and derived data inherits the highest tier of its evidence (SPEC §4). It also carries the work's title and show, which are the listen line's own words. A tier-1 `heard/v1` line would let a tier-1 crossing carry, line by line, the listening history the listen lines keep at 2.

So **`tier` MUST be 2**: not because the words are private, but because their presence in this record is. It is not 3: nothing here is money or health, and a text of what the owner chose to hear is no more sensitive than the listen line that already says so. Consequences, all by existing rules: in a record that seals, the line is sealed (SPEC §2) and so is its text in the store (SPEC §1.1, "a file a tier 2–3 line points at … is sealed"); `search` finds it with tiers 1 and 2, the default, in a record that does not seal (§8); a crossing at tier 1 never carries it. A crossing at tier 2 still does not carry it by default (§9).

## 3. A new profile, not an extension of `listen/v1` and `watch/v1`

Two shapes were weighed.

**Extend `listen/v1` and `watch/v1`** with a `text` attachment field. For: one line per listen, a reader of a day sees the words beside the title with no join. Against, and decisive: a line is never rewritten (SPEC §3), so the text would arrive as a *new* listen line superseding the old one, written by a different source (`heard`) at a later time: every reader of listens (`rollup listen`, the Day, the year's listening hours) would have to know that a superseding listen is not a second listen. `listen/v1` is frozen (RFC 0031): a field may be added as MAY, but a rule that changes what a listen line *is* for a reader may not. An episode played three times is three listen lines; its text would be copied three times, or carried by one of them only, and either is a rule every reader learns. And `watch/v1` would grow the same field with the same rules under a second RFC.

**A new profile, `heard/v1`**: one line per work and text source, beside the listen or watch line, naming it by id, as `star/v1` (RFC 0041) names its line and `attribution/v1` (RFC 0040) its scene. For: no reader of listens or watches changes; the text has one line whatever the number of plays; a text's own facts (where it came from, its language, its length) have fields of their own; a correction of a text is a line superseding a line of the same profile; a crossing can hold the text back by kind (§9) without touching the listening history. Against: a reader that wants the words of a listen joins by id; `logbook show heard` and `search` do it for the owner.

This RFC chooses **`heard/v1`**.

## 4. `heard/v1`: the line

`kind` MUST be `heard`. `source` is the step that wrote it: `heard` for `sync heard`. `tier` MUST be 2 (§2). `at` and `end` MUST be those of the line it names (`of`): the text is placed where the owner first heard it, so it is on that listen's or watch's day. `tz` is the record's zone. `recorded_at` says when the text arrived.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"heard/v1"` | MUST | |
| `raw_id` | string | MUST | the work and the text source, so a text is written once however often the work is played: `heard:feed:<first 16 hex of sha256(transcript URL)>`, `heard:apple:<the episode's uuid in the Podcasts store>`, `heard:captions:<video_id>`, `heard:local:<the work's key as above>` |
| `of` | string | MUST | the `id` of the listen or watch line the text belongs to: the first one the step found for the work |
| `of_kind` | string | MUST | `listen` or `watch`, so a reader can say which without opening it |
| `media` | string | MUST | `episode` or `video` |
| `title` | string | MUST | the work's title, as the line it names spells it |
| `by` | string | MAY | the show (a listen's `show`) or the channel (a watch's `channel.name`), as that line spells it |
| `text_source` | string | MUST | `feed`, `apple`, `captions` or `local` (§1) |
| `language` | string | MUST | the text's language as a BCP 47 tag, from what the text or its source says (§6), `und` when nothing says |
| `text` | object | MUST | the SPEC §1.1 reference to the text: `{sha256, path, bytes, media_type}`. The bytes are the text exactly as it was fetched or read (a feed's VTT is stored as VTT), so the digest is the publisher's file and two records that fetched the same file hold the same bytes |
| `format` | string | MUST | `vtt`, `srt`, `json` (podcasting 2.0's JSON transcript), `text` or `ttml` |
| `chars` | integer | MUST | the length of the words in characters, as a reader extracts them (cues joined, timings and tags dropped) |
| `words` | integer | MUST | the same, in words |
| `url` | string | MAY | the URL a `feed` text was fetched from |
| `supersedes` | string | MAY | the id of the earlier `heard/v1` line of the same work and text source this one replaces (a corrected text) |
| `extra` | object | MAY | the source's own facts: `file` (an owner-supplied file's name, never its folder), `content_type` (what the server said) |

The words themselves are never in the line (SPEC §1.1: "a line MUST NOT inline such content"): not an excerpt, not a summary. `chars` and `words` let a reader say how long a text is without opening it.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"heard/v1","type":"object",
 "required":["schema","raw_id","of","of_kind","media","title","text_source","language","text","format","chars","words"],
 "properties":{
  "schema":{"const":"heard/v1"},
  "raw_id":{"type":"string","pattern":"^heard:(feed|apple|captions|local):\\S+$"},
  "of":{"type":"string","minLength":1},
  "of_kind":{"enum":["listen","watch"]},
  "media":{"enum":["episode","video"]},
  "title":{"type":"string"},"by":{"type":"string"},
  "text_source":{"enum":["feed","apple","captions","local"]},
  "language":{"type":"string","minLength":2},
  "text":{"type":"object","required":["sha256","path","bytes","media_type"],"properties":{
   "sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"path":{"type":"string"},
   "bytes":{"type":"integer","minimum":0},"media_type":{"type":"string"}}},
  "format":{"enum":["vtt","srt","json","text","ttml"]},
  "chars":{"type":"integer","minimum":0},"words":{"type":"integer","minimum":0},
  "url":{"type":"string"},"supersedes":{"type":"string"},"extra":{"type":"object"}}}
```

Example (synthetic):

```json
{"at":"2026-10-14T06:40:00Z","end":null,"tz":"Europe/Oslo","source":"heard","kind":"heard","tier":2,
 "payload":{"schema":"heard/v1","raw_id":"heard:feed:4f1c0de2a9b87e31","of":"019cadd3-6bc0-7dcd-9133-0000000004b1",
 "of_kind":"listen","media":"episode","title":"Episode 12: the east berth","by":"Havnepodden",
 "text_source":"feed","language":"nb","format":"vtt","chars":41237,"words":7012,
 "url":"https://havn.example.org/podden/12.vtt",
 "text":{"sha256":"3a5c0f9e1d2b4a6c8e0f1a3b5c7d9e1f2a4b6c8d0e2f4a6b8c0d2e4f6a8b0c2d","path":"attachments/3a5c0f9e1d2b4a6c8e0f1a3b5c7d9e1f2a4b6c8d0e2f4a6b8c0d2e4f6a8b0c2d","bytes":52811,"media_type":"text/vtt"}}}
```

## 5. Rules

1. **One line per work and text source.** An episode played three times has three listen lines and one `feed` text; its `apple` text, when the Mac has one too, is a second `heard/v1` line. The `raw_id` is the dedupe key (`(source, raw_id)`, as every adapter's): the step asks the record which keys it holds *before* it fetches or reads anything, so a text the record has is never fetched again.
2. **The line names its listen or watch line and never changes it.** Readers join by `of`. A retraction of the listen line (RFC 0003) does not retract its text; a reader that hides retracted lines hides a `heard` line whose `of` is retracted.
3. **The text is stored as it came.** The step never edits the words, never translates, never summarises. A reader extracts the words (§8) by `format`.
4. **A text is someone else's words, and the line says so.** `heard/v1` is not `transcript/v1`: no speaker of it is a counterpart, no reader of calls (the synthesis, `promises`, `speakers`) reads it, and no `resolution/v1` names its speakers.
5. **A model may read a text only where a model may read the listen line**, and only to write a draft (pencil, RFC 0036): never a fact, never a `heard` line. Nothing in this RFC sends a text to a model.
6. **A corrected text** (a feed that republishes its transcript) is a new line with `supersedes`; the old one stays. The step does not look for corrections: a text, once held, is not fetched again (rule 1). The owner asks for one with `sync heard --refetch` once that exists (open question 4).

## 6. Where the words come from

### 6.1 `feed`: the podcast's own transcript

For each `listen/v1` line with `media` `episode` and an http(s) `extra.transcript_url`, the step fetches the URL once, with a plain GET over HTTPS (or HTTP, when that is what the feed names): no key, no cookie, no referrer; the User-Agent names this project, as the weather source's does. A feed is someone else's data, so a URL that names this machine or its network (`localhost`, or a loopback, private, link-local, reserved, multicast or unspecified address written out) is refused without a request and counted (`skipped_private_host`); a name is resolved and every address checked: the host is resolved (`getaddrinfo`) before the request, and when any address it returns is one of those, the URL is refused and counted the same way, so `127.1`, `2130706433`, `0x7f000001` and a name that resolves to 127.0.0.1 are refused as `127.0.0.1` is. A host that does not resolve is not requested and is a failed fetch (`skipped_fetch_failed`). The same checks run on every redirect's target before it is requested: a target that is not `http(s)`, or whose host is this machine or its network, written out or resolved, is refused and counted the same way, one that does not resolve is a failed fetch, and at most 3 redirects are followed (the fourth is a failed fetch, `skipped_fetch_failed`). Podcasting 2.0 allows a transcript as WebVTT (`text/vtt`), SRT (`application/srt`, `application/x-subrip`), its JSON (`application/json`: `{"segments":[{"body", "startTime", "speaker"?}]}`), plain text (`text/plain`) and HTML (`text/html`). The step stores the first four as they come; HTML is not stored (a page's markup is not a transcript's words) and is a counted skip, `skipped_html`. The format is WebVTT when the body begins `WEBVTT`, whatever the server says (a server that sends a `.vtt` file as `text/plain` is common); else the response's `Content-Type`, else the URL's extension, else the first bytes (a cue number and an arrow; `{`).

The language is the one the text gives (a WebVTT header's `Language:`, a JSON transcript's `language`) when it gives one, else the response's `Content-Language`, else `und`. `<podcast:transcript>` has a `language` attribute, but the Apple Podcasts adapter keeps only the URL (RFC 0019 `extra.transcript_url`); see §10.

### 6.2 `apple`: what Apple Podcasts cached on this Mac

Apple Podcasts on macOS shows transcripts it generates itself and keeps the ones it has fetched in its group container, as TTML (Timed Text Markup Language) files: `~/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Library/Cache/Assets/TTML/`, in folders of Apple's own naming, one file per episode. Apple does not document this folder, its layout or its file names; they are what the files themselves show, and they may move in any macOS release. The step therefore reads every `*.ttml` file under the folder (`LOGBOOK_HEARD_TTML_DIR` names another), whatever the subfolders, and never relies on the layout.

A file is matched to its episode by what the Podcasts store keeps (`MTLibrary.sqlite`, the store the Apple Podcasts adapter reads, `LOGBOOK_PODCASTS_DB` naming another): `ZMTEPISODE.ZTRANSCRIPTIDENTIFIER`, the path of the episode's transcript asset relative to the folder, whose last part is the file's name, and `ZMTEPISODE.ZSTORETRACKID`, the episode's id in Apple's catalogue, which the file's name carries as `transcript_<id>`. The store row gives the episode's `ZUUID`; the listen line's `raw_id` is `apple-podcasts:<ZUUID>@<played>` (RFC 0019), so the row leads to the episode's listen lines. Both columns are confirmed with `PRAGMA table_info` before they are read, as every reader of an app's store does; a store without either matches nothing and says so once, never a traceback. A played episode with no file is counted (`skipped_no_apple_transcript`); a file no played episode claims is not read.

The text is the words of the TTML's paragraphs (`<p>`), each paragraph's spans joined with a space, its language the `xml:lang` of the root element. TTML is parsed only from these local files, never from a fetch (a feed's TTML is refused as an unknown format), with the standard library's parser, which resolves no external entity. Nothing about this part touches the network: the folder and the store are read where they lie, the store opened read-only.

### 6.3 `captions`: a video's captions, supplied by the owner

YouTube publishes no documented, stable way to fetch a video's captions over HTTPS without a key. The Data API's `captions.download` needs OAuth and the video owner's permission; the `timedtext` endpoint the web player calls is undocumented and changes without notice. The step therefore **does not fetch captions and does not scrape**: it reads them from a folder the owner fills with a tool of their choice (`LOGBOOK_HEARD_CAPTIONS_DIR`), one WebVTT file per video named by the video's id: `<video_id>.vtt`, or `<video_id>.<language>.vtt` when the owner keeps several languages. The video itself is never downloaded, by the step or because of it.

For each `watch/v1` line with `action` `watched` and a `video_id`, the step looks for that id's file. `watch/v1` does not keep a video's language (§10), so "the video's language" is what the file says: the language in its name, else the WebVTT header's `Language:`, else `und`. When there are several languages for one video, the first of `LOGBOOK_HEARD_LANGUAGES` (a comma list of BCP 47 tags) that is present wins, else the file without a language, else the first by name; one text is written per video and the others counted (`skipped_captions_other_language`).

### 6.4 `local`: not in this RFC's step

A transcription on the home machine (Whisper through the existing `transcribe` extra) needs the audio. The record holds no podcast audio and never downloads a video, so the step would have to find an episode's audio file on the Mac, which no reader of the record knows how to do today. `local` is reserved, not written; a later amendment says where the audio comes from.

## 7. `sync heard`

`logbook sync heard` is a live source like the others (ADR 0017): it runs by name, joins `sync --all` and the schedule once configured (after every other source but the photo walk, which always runs last, so a run sees the listens the podcasts sync just wrote), holds the writer lock for its run, writes through `Logbook.append_many`, and keeps a watermark in `state/heard.json`.

- **Opt in.** Through the same settings every source uses: its environment variable, and `policy/import.json`. `LOGBOOK_HEARD` names the text sources the owner wants, a comma list of `feed`, `apple` and `captions`; until it is set, `sync --all` skips the source and says so (`LOGBOOK_HEARD not set`), and `sync heard` by name says what to set. A source the owner disabled in `policy/import.json` (`{"source": "heard", …}`) is skipped either way.
- **What it reads.** The record's own `listen/v1` and `watch/v1` lines, through the index (`by_kind` over the days from the start on), never the whole log; then, per work, at most one fetch or one file. The watermark is the `at` of the newest listen or watch line it wrote a text for; a run starts 14 days before it, because a listen or a watch can reach the record days after it happened (the podcasts sync runs after it; a Takeout export arrives when the owner asks for it). A Takeout export imported more than two weeks after its newest watch is reached with `sync heard --since <instant>`, as any source's history is.
- **First run.** A first scheduled run reads the listen and watch lines of the last 14 local days, as every source's does since #302 (`logbook.contrib.first_run`); a run by hand with no watermark reads from the beginning, under the cap.
- **The cap and the delay.** At most `LOGBOOK_HEARD_MAX_FETCHES` network fetches a run (default 20), with `LOGBOOK_HEARD_DELAY_S` seconds between two (default 2.0). A run that reaches the cap stops taking works there and says how many it left for the next run; the watermark is the last work it took, so the next run carries on. Reading the Mac's TTML files and the owner's caption folder is not a fetch and is not capped.
- **A failed fetch** (a refused connection, an HTTP error, a body over 5 MB, a format it does not store) is one counted skip in the run's report (`skipped_fetch_failed`, `skipped_too_large`, `skipped_html`, `skipped_unknown_format`), never retried in the same run. The URL is noted in `state/heard-cache.json` (bookkeeping, never the record) with the day of the attempt; a URL that failed is not tried again for 7 days (`skipped_failed_before`), and never after its third failure, so a dead link costs three requests in all, not one per run. A URL is tried again only while its listen is inside a run's window (14 days before the watermark); once newer texts move the watermark past it, `sync heard --since` reaches it, as any history. The run does not fail and the watermark moves on: one dead transcript never holds back the others. A 429 ends the run's fetching (`skipped_rate_limited`) and is not charged to the URL (the host was busy, the link is not wrong); the works after it are `left_for_next_run`.
- **A dry run** (`sync heard --dry-run`) fetches nothing and stores nothing: each fetch it would make is counted (`would_fetch`), under the same cap; the local texts are read and counted, never written.
- **Never twice.** Before any fetch or read, the step asks the index which `raw_id`s the record holds (`existing`, one SELECT a batch); a work that has its text is passed by without a request.

## 8. The readers

**`logbook show heard [--day D | --since D --until D] [--json]`** is a reader of `show`, as `show year` and `show orgs` are, not a command of its own: `logbook --help` is one screen of 32 commands under 50 lines (the October 2026 audit), and a reader belongs under `show`. It lists the texts the record holds, by the local day of the listen or watch they belong to (§4: `at` is its), latest day first and in time order within a day: the time, the text source, the language, the length (`chars` and `words`), the title and show or channel, and a one-line excerpt, the first words of the text up to 100 characters. Without a window it is the last 14 days. It reads the `heard` lines of the window through the index (`by_kind` on `(kind, day_local)`) and one attachment per line for the excerpt, so its cost is the window's texts, never the record's size. `--json` gives the same rows with `excerpt`, `chars`, `words`, the line's id and its `of`. A sealed line and its text are opened with the identity, as every reader opens one; without it the row says `[sealed heard/v1]` and that there is no identity to open it, and shows nothing else. A text whose `of` is retracted is not listed. Nothing is written.

**`logbook search`** finds words inside the texts. The search table already holds an attachment's words for one kind, `transcript` (`search.body_of` reads the text from the store); `heard` joins it: the row's body is the line's `title` and `by`, then the words of the text (§5 rule 3), never its ids, digest or URL. The index's schema does not change, nor its version; a `heard` line's row is written beside it when it is appended, and `logbook index` rebuilds it with the rest. `search --kinds heard` cuts to them. Tier 2, so searched by default. **In a record that seals** (RFC 0029), a tier-2 line is sealed and the search table never holds the words of a sealed line (`index.rows_of`), so `search` finds neither a heard text nor its title there, exactly as it finds no sealed transcript today. Searching sealed words is the index's question, for every kind at once, not this RFC's.

No page shows a text in this RFC. A later Day row for a listen with its text is RFC 0043's to place.

## 9. Nothing leaves

A text never crosses by default. Two roads copy attachments out of the record, and both hold a `heard` line back unless the destination's entry in `policy/crossing.json` names it:

- `export crossing --to D` (RFC 0005): a `heard` line crosses only when D's entry says `"heard": true` *and* its tier is within the request and the ceiling. Otherwise it stays home, counted with the lines held back by their entry (`held_back_by_entry` in the manifest's counts), and its text is not copied.
- `export share` (the shared page, RFC 0025): the same rule for the page's destination; a `heard` line held back is simply not on the page, and its text not in the bundle.

```json
{"hermes": {"max_tier": 2, "heard": true}}
```

The key is read by this RFC's own module (`logbook.core.heard.crosses`), not by the policy's version (`policy.version`): naming `heard` changes what crosses, not the entry a draft was derived under. The trip bundle carries photos and flights only and never a `heard` line. The other ways out carry lines, never attachments: the vault, the site, the world and the Notion export write a `heard` line's title at most, by their own ceilings, as they would a listen's; `mcp` serves the line, never the text (it opens attachments for `transcript` lines alone). The dream and the synthesis read no `heard` text: neither reads the attachment of a line that is not a call's transcript.

## 10. Where this meets `main`

- **The Apple Podcasts adapter keeps the URL of `<podcast:transcript>`, not its `type` or `language`.** The step therefore takes the format from the response and the language from the text (§6.1). Keeping both under `extra.transcript_type` and `extra.transcript_language` is a one-line change to that adapter, additive to RFC 0019 (frozen: MAY fields under `extra` are allowed), for a later pull request; this one does not touch the adapter.
- **`watch/v1` keeps no language for a video.** Captions take theirs from the owner's file (§6.3).
- **No documented keyless endpoint for YouTube captions** (§6.3): the owner's folder is the only road.
- **Apple's TTML folder is undocumented** (§6.2): the step finds the files by walking the folder and matches them by the store's columns, never by the folder's layout.
- **The adapter registry is generated from `pyproject.toml`**, which this change does not touch: the step is loaded from `adapters.UNLISTED`, after the table, so `sync heard`, `sync --all`, the schedule and `logbook sources` find it as they find every source, and `tests/test_adapter_registry.py` names it as deliberately unregistered until the release lists it (one line, and `scripts/adapter_registry.py`). `sync` gained one option for a source of the record's own lines, `lines(kind, first_day)`, read through the index.
- **A text that lands on a signed day.** A `heard` line's `at` is its listen's, so a text fetched after the owner signed that day is a new line on a signed day. The dream leaves `heard` lines out of its material (they change nothing it reads); whether the Day's readiness should count them as a change since the signature is RFC 0034's to say (open question 7).

## 11. Open questions for the owner

1. **The tier.** §2 argues 2 from the listen line. Is there a case for 3 (a text of a health or money podcast)? The proposal is no: the tier follows the listen line, which is 2.
2. **A replayed episode on a later day.** The text is listed on the day the owner first heard it. Should `logbook show heard --day D` also list the texts of works replayed on D (a join from that day's listens by `raw_id`)? Cheap to add; left out for one rule.
3. **The caption folder's naming.** `<video_id>.vtt` and `<video_id>.<lang>.vtt`. Many caption tools write `<title> [<video_id>].<lang>.vtt`; should the step also find the id between square brackets?
4. **A corrected text.** A `--refetch` that fetches a held feed text again and writes a superseding line only when the bytes differ.
5. **`local`.** Where would the audio of an episode come from: Apple Podcasts' downloaded episodes on the Mac (another undocumented folder), or a folder the owner fills, as for captions?
6. **The crossing key.** `"heard": true` on an entry. Or a list of kinds an entry lets cross that would otherwise stay home (`"also": ["heard"]`), so the next such kind needs no new key?
7. **A signed day.** Should a text fetched after a day was signed count as a change to that day (the Day's "changed since you signed"), or, like the dream, be left out because the listen it belongs to was already there?
