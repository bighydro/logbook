# RFC 0023 — payload profile `voice-memo/v1`

Status: draft · 2026-10-01 · comment period: two weeks

One recording the owner made on purpose: a voice memo, a dictated thought, a rehearsal, a snatch of a
conversation they chose to keep. The line records that a recording was made — when, how long, what the
owner called it — and points at the audio in the attachment store (SPEC §1.1). It does not say what was
said: transcription is a later, local step that writes a `transcript/v1` line pointing back at this one
(RFC 0004), and never happens inside the adapter.

## Line

`kind` MUST be `voice-memo`. `tier` SHOULD be 2: a recording is the owner's own voice, the class of
spoken personal content RFC 0004 puts under tier 2. `at` is when the recording started, `end` when it
stopped (`at` plus the duration), `null` when the store gives no duration. `tz` is the record's zone
unless the store keeps one. `source` is the adapter: `voice-memos` (Apple's app), ….

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"voice-memo/v1"` | MUST | |
| `raw_id` | string | MUST | the store's own id for the recording (Voice Memos' `ZUNIQUEID`); the `(source, raw_id)` dedupe key |
| `title` | string | SHOULD | what the owner, or the app, called it, verbatim (`New Recording 12`, a place name the app chose, the owner's words) |
| `duration_s` | number | SHOULD | the recording's length in seconds, as the store keeps it |
| `file_name` | string | SHOULD | the audio file's name in the store (`20260302 201407.m4a`); the suffix says the container when `media_type` cannot |
| `media` | object | SHOULD | the audio: a SPEC §1.1 reference `{sha256, path, bytes, media_type}` when the bytes are in the store, else `{sha256, bytes, media_type}` with no `path` — the digest names the file, the store does not have it (rule 2) |
| `folder` | string | MAY | the app's folder the recording is filed in, when the store keeps the name in the clear |
| `extra` | object | MAY | anything else the source keeps that is not the audio's content: Voice Memos' `flags`, whether the store had evicted the local copy |

## Rules

1. **One recording, one line.** Every recording the store lists is a line, whether or not its audio file is present; one whose audio is missing from the store (evicted to iCloud, deleted on disk) is a line without `media`, counted `media_missing`.
2. **The audio is content-addressed and optional.** An adapter MUST compute the file's SHA-256 and MAY put the bytes in the §1.1 store, only when asked (`logbook add --attachments`, `import-backup --attachments`); without that the line carries the digest, byte count and media type and no `path`. A later run with `--attachments` writes the same line (same `raw_id`), so nothing is appended, but it does put the files in the store, where the digest the earlier line carries finds them.
3. **Nothing inline.** No waveform, no transcript, no snippet of audio in the line (SPEC §1.1).
4. **Timestamps are the source's.** `at` is the store's recording date converted to UTC, not the file's modification time and not the date in the file's name; a row without one is skipped and counted (`skipped_no_date`).
5. **Media types are the container's.** `audio/mp4` for an `.m4a` (ISO base media, `M4A ` brand); `video/quicktime` for Voice Memos' `.qta` composition (a QuickTime container holding audio, `qt  ` brand); `audio/x-caf` for a `.caf`; `application/octet-stream` when the adapter does not know, with `file_name` carrying the suffix.

## Example (synthetic)

```json
{"at":"2026-03-02T20:14:07Z","end":"2026-03-02T20:15:49Z","tz":"Europe/Oslo","source":"voice-memos","kind":"voice-memo","tier":2,
 "payload":{"schema":"voice-memo/v1","raw_id":"7A1B2C3D-0000-4000-8000-000000000001","title":"Idea for the talk",
 "duration_s":102.4,"file_name":"20260302 211407.m4a",
 "media":{"sha256":"9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08","path":"attachments/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08","bytes":1638400,"media_type":"audio/mp4"}}}
```

## JSON Schema

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"voice-memo/v1","type":"object",
 "required":["schema","raw_id"],
 "properties":{
  "schema":{"const":"voice-memo/v1"},
  "raw_id":{"type":"string","minLength":1},
  "title":{"type":"string","minLength":1},
  "duration_s":{"type":"number","minimum":0},
  "file_name":{"type":"string","minLength":1},
  "media":{"type":"object","required":["sha256","bytes","media_type"],
   "properties":{"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"path":{"type":"string","pattern":"^attachments/[0-9a-f]{64}$"},
    "bytes":{"type":"integer","minimum":0},"media_type":{"type":"string","minLength":1}},"additionalProperties":false},
  "folder":{"type":"string","minLength":1},
  "extra":{"type":"object"}},
 "additionalProperties":false}
```

## Notes

- **Why not `transcript/v1` with empty text.** A transcript is words; a recording without words yet is not a transcript with nothing in it, and a reader that lists transcripts should not list a hundred silent lines. When the local transcription step runs it writes a `transcript/v1` line whose `content` is the text and whose `extra.recording` is this line's `raw_id`; this line stays what it was.
- **Why the title is kept.** Voice Memos names a recording after the place it was made unless the owner renames it; either way it is what the owner sees in the list and how they will look for it. A place name is tier-2 content like the rest of the line.
- **Sources.** `voice-memos` reads Voice Memos' `CloudRecordings.db` with the audio files beside it (`Recordings/` on an iPhone, copied out by `logbook import-backup`; `~/Library/Group Containers/*.com.apple.VoiceMemos.shared/Recordings/` on a Mac).
