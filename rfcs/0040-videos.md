# RFC 0040 — Videos: a recording file, its scenes, and the owner's attribution

Status: draft · 2026-10-14 · comment period: two weeks · implemented with `sync drive --videos`, `videos fetch`, `videos infer` and `review video` ([docs/adapters/videos.md](https://github.com/bighydro/logbook/blob/main/docs/adapters/videos.md))

A family's home videos are digitised tapes: one file of two to four gigabytes holds many recordings from different years and places, and nothing about the file says where or when any of them was made. Its storage's dates are when it was digitised or uploaded. The record needs four things to hold them honestly: a line that names the file without claiming a time it does not know (`video/v1`, §2); a way to name one stretch of it, a **scene**, that every other line can point at (§1); a model's proposal per scene that is a proposal and never a fact (`draft/v1`, RFC 0036, §3); and the owner's statement of where and when a scene was filmed, in a line of its own beside the file's, never inside it (`attribution/v1`, §4), with the scene's no, a line of its own (`scene-review/v1`, §5), and "ask the family" (§6) for the answers that are not a yes.

`video/v1`, `attribution/v1` and `scene-review/v1` are new profiles, not among RFC 0031's freezes: their schemas may change while this RFC is a draft. The envelope (SPEC §2–3) does not change: no spec version bump, no conformance fixture, no ADR. One draft is amended additively: RFC 0036's `draft/v1` (a scene as the subject of unit `event`). RFC 0037 is not amended: its `entity-review/v1` stays the no of the five kinds of thing the record names, and a scene is none of them.

## 1. Words

- A **video file** is one recording file the owner holds in a storage the record reads (Google Drive today), named by the storage's id.
- A **scene** is one continuous recording inside a video file: from one stop of the camera to the next, or a DVD chapter. It is named by a **scene ref**, the video line's `id` (SPEC §2) and the scene's offsets in seconds as a W3C Media Fragments temporal range, two decimals: `<line id>#t=<start>,<end>` (`019cadd3-6bc0-7dcd-9133-0000000005a0#t=40.00,90.00`). Like RFC 0038's `speaker` ref, it means something only through the line it names: the same tape listed again is a new line and its scenes new refs.
- An **attribution** is the owner's statement that a scene was filmed at a place, or on a date or within a range of dates, or both: one `attribution/v1` line (§4). The video line is never touched by it.

## 2. `video/v1`: the file, by its metadata

`kind` MUST be `video`. `source` is the reader of the storage (`drive-videos`). `tier` MUST be 2: a family's video holds other people's faces and voices, and its name and description may name them. `at` is when the record learned of the file (the listing that found it); `end` is null. **`at` is never a filming time and never the storage's own time**: when a scene was filmed is only ever an attribution.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"video/v1"` | MUST | |
| `raw_id` | string | MUST | the storage's id of the file: the dedupe key (`(source, raw_id)`), so a file is written once however often it is listed |
| `library` | string | MUST | `google-drive` |
| `title` | string | SHOULD | the file's name as the storage shows it |
| `description` | string | MAY | the storage's description of it, when it has one |
| `file` | object | MUST | `{ id, name, path?, mime_type?, url?, resource_key? }`: the storage's id and name, the folders above it from the one listed down, its media type, a link that opens it, and Drive's resource key for an older file, kept so a reader of the bytes can send it |
| `bytes` | integer | SHOULD | the file's size as the storage reports it |
| `duration_s`, `width`, `height` | number, integer | MAY | from the storage's video metadata |
| `digest` | object | SHOULD | `{ md5 }`: the checksum the storage reports, against which a copy is verified. Not `content_hash` (RFC 0002 keeps that for a sha256 of the bytes) |
| `extra` | object | MAY | `drive_created`, `drive_modified`: the storage's own times, RFC 3339 UTC, recorded as what they are, the upload's |

The bytes are never in the record. A copy made to read a file lives in the bookkeeping under `state/` and is deleted once read.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"video/v1","type":"object",
 "required":["schema","raw_id","library","file"],
 "properties":{
  "schema":{"const":"video/v1"},
  "raw_id":{"type":"string","minLength":1},
  "library":{"enum":["google-drive"]},
  "title":{"type":"string"},"description":{"type":"string"},
  "file":{"type":"object","required":["id"],"properties":{
   "id":{"type":"string"},"name":{"type":"string"},"path":{"type":"array","items":{"type":"string"}},
   "mime_type":{"type":"string"},"url":{"type":"string"},"resource_key":{"type":"string"}}},
  "bytes":{"type":"integer","minimum":0},"duration_s":{"type":"number","minimum":0},
  "width":{"type":"integer","minimum":1},"height":{"type":"integer","minimum":1},
  "digest":{"type":"object","properties":{"md5":{"type":"string","pattern":"^[0-9a-f]{32}$"}}},
  "extra":{"type":"object"}}}
```

## 3. The scene's draft: `draft/v1`, unit `event`, a scene as its subject

RFC 0036's `draft/v1`, amended additively: for unit `event` the `subject` MAY be one scene ref (`[<video line id>#t=<start>,<end>]`) where it was the ids of the lines the unit is. The dedupe key of rule 1, `(source, unit, subject, read_head)`, then tells one scene from another. A reader that looks a subject up as a line id (`drafts.by_transcript`) finds no line by that string and passes it by.

`source` is `model:<name>` as for every draft; the reference writes `model:video-rules/1`, the rules that wrote the sentences on two local models' readings, which `extra.models` names. `tier` is the highest of the lines read (the video line and the file's transcript): 2. Every segment is supported or unsupported as RFC 0036 says; a supported segment's `evidence` is the video line (what the frames show) or the file's `transcript/v1` line (what was said), and which frames and which time range it rests on is kept beside the segments under `extra.segments`, `[{ part, frames?: [offset_s], speech?: [[from_s, to_s]] }]`, as a call's synthesis keeps its utterances. `extra` also carries `scene` (`{video, n, of, start_s, end_s, opened_by}`), `frames` (the frame descriptions, never pixels), `proposal` (`{place, when, confidence, when_confidence}` or null: `confidence` the weaker of the place's and the date's, `when_confidence` the date's own, present when there is a `when`), `inference` (the key of models, prompt and scene settings), `models`, `prompt`, `rules` and `settings`. A proposal's `place` is `{type: place|asset, id, registry: logbook, label}`, an entity of RFC 0037 (a place by its `places.json` name, an asset by its `assets.json` id), never a coordinate; its `when` is `{from, to, precision}` (local days, both inclusive; `day`, `month`, `season`, `year` or `range`), never more precise than the evidence. A scene with nothing to go on has one segment that says so and `proposal` null.

The draft is a proposal (rule 4): no reader derives a place or a date from it. Nothing crossed to make it (the models run on the record's machine), so no `policy/crossing.json` entry governs it as the `dream` entry governs a dream's draft; a crossing carries it by its tier like any line.

The file's speech is one `transcript/v1` line (RFC 0004), source `video-transcription`, its content WebVTT whose cues carry their times in the file, `provenance.source` the video line's id, `at` the video line's, `end` null. It is no call: the synthesis of calls (`transcript synthesize`, the 06:00 close) leaves its source out, and refuses it when it is named by its id, so a home video's words reach no model endpoint.

## 4. `attribution/v1`: where and when a scene was filmed, by the owner

`kind` MUST be `attribution`. `source` MUST be `manual` and `method` `owner`: a model proposes, the owner binds; no adapter, model or tool writes one. `tier` is the highest tier of its evidence (SPEC §4): 2 for a family's video. `at` is when the owner said it; `end` is null.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"attribution/v1"` | MUST | |
| `raw_id` | string | MUST | `<scene ref>@<first 12 hex of the SHA-256 of {place, when}>`: the same answer for the same scene is one line |
| `ref` | object | MUST | `{ kind: "scene", value: <scene ref> }` |
| `scene` | object | MUST | `{ video, start_s, end_s }`: the video line's id and the offsets, so a reader needs no parser |
| `place` | object | one of | `{ type, id, registry, label }`: `type` `place` (`id` the `places.json` name) or `asset` (`id` the `assets.json` id), `registry` `logbook` (RFC 0037 §3.3) |
| `when` | object | one of | `{ from, to, precision }`: two local days, both inclusive, and `day`, `month`, `season`, `year` or `range` |
| `method` | `"owner"` | MUST | |
| `draft` | string | MAY | the scene draft confirmed, when there was one |
| `evidence` | array of string | SHOULD | the draft, the video line, the transcript |
| `logbook_head` | hex sha256 | SHOULD | the head the owner answered against |
| `supersedes` | string | MAY | the standing attribution of the same scene this one corrects |
| `extra` | object | MAY | `proposal` (what was proposed) and `changed` (whether the owner's answer differs from it) |

A line carries `place`, `when`, or both, never neither.

**Rules.** 1. An attribution never modifies the line it names; readers join by `ref` (RFC 0006 rule 1, RFC 0038 §3.3 rule 1). 2. One standing line per scene: the last one not retracted and not superseded. 3. A correction is a new line with `supersedes`; the wrong one stays, superseded. 4. A place is an entity of the owner's registries, never a coordinate of the line's own: a map takes the place's coordinates from `places.json` and an asset's from its positions. 5. A scene ref that a later inference with other settings no longer cuts the same way still names its stretch of the file: the attribution stands.

**The review** is RFC 0037 §5's `review KIND` with `KIND` `video`: one more queue of the one review sitting, beside the person, the org, the idea, the asset and the place, and listed with them by `review` alone. `--accept N[,N]` takes what scene N's draft proposes, `--reject N[,N]` writes the scene's no (§5) and `--json` is the queue, or what was written, as for every kind. The scene's own answers are `review video`'s options, refused for every other kind as a place's are refused for the rest: `--place N NAME` and `--date N WHEN` confirm with the owner's own place or date, `--ask N[,N]` keeps the scene to ask the family (§6), `--asked` and `--answered` list the scenes kept to ask and those confirmed, and `--top N`, a place's option too, counts scenes. The lock is the sitting's, one rule for every queue: the queue is read and the owner asked with no lock held, and each answer's lines are appended under the record's writer lock, at once on a terminal; nothing about a scene needs more, and nothing the owner does while looking at one (playing the stretch of the file, say) waits on the lock or holds it.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"attribution/v1","type":"object",
 "required":["schema","raw_id","ref","scene","method"],
 "properties":{
  "schema":{"const":"attribution/v1"},
  "raw_id":{"type":"string"},
  "ref":{"type":"object","required":["kind","value"],"properties":{"kind":{"const":"scene"},
   "value":{"type":"string","pattern":"^[^#\\s]+#t=\\d+(\\.\\d+)?,\\d+(\\.\\d+)?$"}}},
  "scene":{"type":"object","required":["video","start_s","end_s"]},
  "place":{"type":"object","required":["type","id","registry"],"properties":{"type":{"enum":["place","asset"]},"registry":{"const":"logbook"}}},
  "when":{"type":"object","required":["from","to","precision"],"properties":{
   "from":{"type":"string","format":"date"},"to":{"type":"string","format":"date"},
   "precision":{"enum":["day","month","season","year","range"]}}},
  "method":{"const":"owner"},"draft":{"type":"string"},"evidence":{"type":"array","items":{"type":"string"}},
  "logbook_head":{"type":"string","pattern":"^[0-9a-f]{64}$"},"supersedes":{"type":"string"},"extra":{"type":"object"}},
 "anyOf":[{"required":["place"]},{"required":["when"]}]}
```

## 5. The scene's no: `scene-review/v1`

The owner's statement that a scene was **not** filmed where or when its draft proposed, or, for a scene with nothing proposed, that there is nothing to name. It is a line of its own, never RFC 0037's `entity-review/v1`: a scene is not an observed thing of RFC 0037's five kinds, and a no that named a place or an asset under that profile would be read by every reader of `entity-review` lines (`logbook.contrib.entities.reviews`, the person's, the org's, the idea's, the asset's and the place's queues) as a no about that place or asset. No such reader reads this kind.

`kind` MUST be `scene-review`. `source` MUST be `manual` and `method` `owner`: no adapter, model or tool writes one. `tier` MUST be the highest tier of the lines it answers (the draft, the video line, the transcript), and never under 2 (§7). `at` is when the owner said it; `end` is null.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"scene-review/v1"` | MUST | |
| `raw_id` | string | SHOULD | `scene-review:<scene ref>@<first 12 hex of the SHA-256 of {proposal}>`: the same no on the same proposal of the same scene is one line |
| `ref` | object | MUST | the scene's id: `{ kind: "scene", value: <scene ref> }` (§1), as an attribution names it |
| `scene` | object | SHOULD | `{ video, start_s, end_s }`: the ref's video line id and offsets in seconds, so a reader needs no parser; when present, equal to the ref's, and `end_s` after `start_s` (the schema below cannot say either) |
| `verdict` | `"different"` | MUST | the scene was not filmed at the place or on the date or in the range `proposal` names; with `proposal` null, nothing the review offered names it. No other verdict is defined: a yes is an attribution (§4) |
| `proposal` | object or null | MUST | the proposal it answers, exactly as the draft carried it under `extra.proposal` (§3): `{place, when, confidence, when_confidence?}`, or null for a scene with nothing to go on |
| `draft` | string | MUST | the id of the scene draft whose proposal it answers |
| `supersedes` | string | MAY | the scene's standing no this one replaces: a later inference proposed something else for the same scene, and the owner refused that too |
| `method` | `"owner"` | MUST | |
| `evidence` | array of string | SHOULD | the draft, the video line, the transcript |
| `logbook_head` | hex sha256 | SHOULD | the head the owner answered against |
| `extra` | object | MAY | |

**Rules.** 1. A `scene-review` line binds nothing and changes no line: the scene's draft and the video line stand as they were. 2. While a no stands, a review never offers its scene the proposal it answered, from any later draft; a no whose `proposal` is null holds back a later draft with nothing to propose. 3. **One standing no per scene**, as SPEC §3 has every derived reader read a kind: the no not retracted and not named in a later no's `supersedes`. A no on a scene that has a standing no supersedes it: the scene's no is the new one, and the proposal the superseded one answered is held back no longer, so a later inference that proposes it again asks again; `show` lists the superseded no with a mark. 4. Retraction (RFC 0003) applies: a retracted no counts for nothing, the proposal it answered returns, and a no it superseded stands again. 5. A no on a scene with a standing attribution is refused: an attribution is corrected by a new one that supersedes it (§4 rule 3), or retracted. 6. No reader of `entity-review/v1` lines reads a `scene-review/v1` line, and no reader of this RFC reads an `entity-review/v1` line as a scene's no.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"scene-review/v1","type":"object",
 "required":["schema","ref","verdict","proposal","draft","method"],
 "properties":{
  "schema":{"const":"scene-review/v1"},
  "raw_id":{"type":"string"},
  "ref":{"type":"object","required":["kind","value"],"properties":{"kind":{"const":"scene"},
   "value":{"type":"string","pattern":"^[^#\\s]+#t=\\d+(\\.\\d+)?,\\d+(\\.\\d+)?$"}}},
  "scene":{"type":"object","required":["video","start_s","end_s"],"properties":{
   "video":{"type":"string"},"start_s":{"type":"number","minimum":0},"end_s":{"type":"number","minimum":0}}},
  "verdict":{"const":"different"},
  "proposal":{"type":["object","null"]},
  "draft":{"type":"string","minLength":1},
  "supersedes":{"type":"string"},
  "method":{"const":"owner"},
  "evidence":{"type":"array","items":{"type":"string"}},
  "logbook_head":{"type":"string","pattern":"^[0-9a-f]{64}$"},
  "extra":{"type":"object"}}}
```

## 6. Ask the family: an open `task/v1`

"Ask the family" is the owner's to-do, so it is RFC 0016's line, not a new one: `source` `manual`, tier 2, `list` `videos`, `status` `open`, `title` saying which file and which stretch, `raw_id` `videos-ask:<scene ref>@<time>` (rule 2), `extra.scene` the scene ref. A later page shared with the family reads the open ones. When the scene is answered, the task is written again, `done`, superseding it.

## 7. Tiers

| Line | Tier | Why |
|---|---|---|
| `video/v1` | 2, MUST | other people's faces and voices; a title or description may name them |
| `transcript/v1` of a video, and its WebVTT | 2 (RFC 0004) | spoken personal content |
| `draft/v1` of a scene, and its frame descriptions | 2: the highest of what it read | derived data inherits its evidence's tier |
| `attribution/v1` | 2 | its evidence is the draft, the video, the transcript |
| `scene-review/v1` | 2: the highest of the lines it answers, never under 2 | its evidence is the draft, the video, the transcript |
| `task/v1`, list `videos` | 2 (RFC 0016) | the owner's words |

Nothing derived from a family's video is written below 2, so none of it crosses a destination whose ceiling is 1.

## 8. Example (synthetic)

Ines Nordmann of Oslo, who does not exist, lists her family's folder; one tape, `Home 01`, digitised in 2019:

```json
{"at":"2026-10-14T19:30:00Z","end":null,"tz":"Europe/Oslo","source":"drive-videos","kind":"video","tier":2,
 "payload":{"schema":"video/v1","raw_id":"1HomeTape01SyntheticVideoId01","library":"google-drive","title":"Home 01",
 "file":{"id":"1HomeTape01SyntheticVideoId01","name":"Home 01","path":["Familiens videoer"],"mime_type":"video/mp4",
  "url":"https://drive.google.com/file/d/1HomeTape01SyntheticVideoId01/view"},
 "bytes":3221225472,"duration_s":4012.48,"width":720,"height":576,"digest":{"md5":"0f343b0931126a20f133d67c2b018a3b"},
 "extra":{"drive_created":"2019-03-02T10:00:00Z","drive_modified":"2019-03-02T10:41:12Z"}}}
```

Its second scene shows a sign on a pier; she confirms the place the draft proposed:

```json
{"at":"2026-10-15T18:02:11Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"attribution","tier":2,
 "payload":{"schema":"attribution/v1","raw_id":"019cadd3-6bc0-7dcd-9133-0000000005a0#t=40.00,90.00@5c1e0b2a7d43",
 "ref":{"kind":"scene","value":"019cadd3-6bc0-7dcd-9133-0000000005a0#t=40.00,90.00"},
 "scene":{"video":"019cadd3-6bc0-7dcd-9133-0000000005a0","start_s":40.0,"end_s":90.0},
 "place":{"type":"place","id":"Vollen Brygge","registry":"logbook","label":"Vollen Brygge"},
 "method":"owner","draft":"019cadd3-6bc0-7dcd-9133-0000000005b2",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000005b2","019cadd3-6bc0-7dcd-9133-0000000005a0","019cadd3-6bc0-7dcd-9133-0000000005a1"],
 "logbook_head":"34cb1808a3e7cf1e88351f1dedff1cfbc4ab0a3b1846d04150b8b707cc1d0f2c",
 "extra":{"proposal":{"place":{"type":"place","id":"Vollen Brygge","registry":"logbook","label":"Vollen Brygge"},"when":null,"confidence":"high"},"changed":false}}}
```

Its fourth scene, a snowy road, the draft placed at home; she says it was not, and the scene leaves the queue with its proposal, which no later draft brings back while the no stands:

```json
{"at":"2026-10-15T18:04:40Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"scene-review","tier":2,
 "payload":{"schema":"scene-review/v1","raw_id":"scene-review:019cadd3-6bc0-7dcd-9133-0000000005a0#t=130.00,170.00@a508e5d324d3",
 "ref":{"kind":"scene","value":"019cadd3-6bc0-7dcd-9133-0000000005a0#t=130.00,170.00"},
 "scene":{"video":"019cadd3-6bc0-7dcd-9133-0000000005a0","start_s":130.0,"end_s":170.0},
 "verdict":"different",
 "proposal":{"place":{"type":"place","id":"Hjem","registry":"logbook","label":"Hjem"},"when":null,"confidence":"medium"},
 "draft":"019cadd3-6bc0-7dcd-9133-0000000005b4","method":"owner",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000005b4","019cadd3-6bc0-7dcd-9133-0000000005a0","019cadd3-6bc0-7dcd-9133-0000000005a1"],
 "logbook_head":"4d0f6a2e9b18c3757e0a1d2c6b5f8e9a7c3b2d1e0f9a8b7c6d5e4f3a2b1c0d9e"}}
```

## 9. Open questions

1. **A model's proposals.** The reference proposes by rules over two local models' readings, so no sentence can claim more than its evidence. A local instruct model could read a scene's speech and frames together (a birthday song and a cake are a birthday), under the same evidence rule; whether that is worth its unpredictability is open.
2. **People in a scene.** Faces and voices are the people's, not the scene's place or time; binding a voice is RFC 0038's, and a face's is not yet anyone's. This RFC binds nothing to a person.
3. **The map and the family's page.** `export world` will read the standing attributions (a scene at a place, on a date) when a later change wires them in; the family's shared page will read the open asks. Neither is part of this RFC.
4. **A file replaced in the storage under the same id** keeps the md5 its line recorded, and no copy of the new bytes can be verified against it. Should a changed checksum be a new line superseding the old (and its scenes' attributions follow by offset), or a line of its own?
5. **The transcript's `at`.** Every transcript is presence evidence to the stays reader (SPEC §3.2.3 rule 5); a video's transcript has no known time, so it sits, as an instant, at the moment the record learned of the file. Should the stays reader leave out a transcript whose `extra.time_unknown` is true? (The readers of what was said already do: the synthesis never sends one to a model, and `promises` never reads one, both by its `source`.)
