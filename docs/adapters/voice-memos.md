# Voice memos and their transcripts

Two steps, two lines. `logbook add voice-memos` (or `import-backup --only voice-memos`) writes one
`voice-memo/v1` line per recording Apple's Voice Memos app holds (RFC 0023): when it started, how
long it ran, what you called it, and the audio by digest. `logbook transcribe voice-memos` then
writes one `transcript/v1` line per memo (RFC 0004) with the words, heard by a model running on this
machine. The memo line never changes; the transcript sits beside it and points back.

```bash
logbook add voice-memos ~/backup/voice-memos/CloudRecordings.db --attachments   # the audio into attachments/
logbook transcribe voice-memos --dry-run        # which memos would be transcribed; nothing written, no engine needed
logbook transcribe voice-memos --fetch-model    # the first time: download the model, then transcribe
logbook transcribe voice-memos                  # every standing memo with its audio in the store and no transcript yet
logbook transcribe voice-memos --since 2026-03-01 --model medium
logbook transcribe voice-memos --no-speakers    # transcribe only, even with the speaker models here
logbook derive speakers --dry-run               # transcripts heard before the voices were separated
```

`logbook transcribe` is `logbook derive transcripts` since 0.6; both spellings run the same command.

## The recording: `voice-memo/v1`

The adapter reads `CloudRecordings.db` with the audio files beside it (under `Recordings/` as
`import-backup` copies them out, or next to the store as the phone and the Mac keep them). Every
recording is a line, whether or not its file is there; one whose file is gone is a line without
`media`, counted. The audio is hashed a chunk at a time and the line carries `{sha256, bytes,
media_type}`; only with `--attachments` are the bytes put in the record's attachment store (SPEC
§1.1), and then the reference also carries its `path`. A second `add --attachments` writes no new
line (same `raw_id`) but does put the files in the store, where the digest the earlier line carries
finds them. Tier 2.

Transcription needs the bytes: a memo whose audio is not in the store is skipped and counted
("without their audio in the store (import with --attachments)").

## The words: `transcript/v1`

`logbook transcribe voice-memos` reads the record through its index, finds every `voice-memo` line
that stands (not retracted, not superseded by a later line), whose audio is in the store, and for
which no transcript line exists yet, and transcribes them in time order. Each memo becomes one line:

| Field | What it holds |
|---|---|
| `source` | `transcription`, whatever engine heard it, so the same memo is one line on any machine |
| `kind`, `tier` | `transcript`; 2 (RFC 0004), or the memo's own tier when that is higher |
| `at`, `end`, `tz` | the memo's |
| `payload.raw_id` | the memo's own `raw_id`: the dedupe key, so a re-run writes nothing twice (ADR 0017) |
| `payload.provider` | the engine: `mlx-whisper` or `faster-whisper` |
| `payload.provenance` | `{"source": <the memo line's id>, "engine": …, "model": "small"}` |
| `payload.title` | the memo's title |
| `payload.participants` | empty: a memo is the owner's own voice; nothing is resolved here |
| `payload.language` | what the engine detected on the first chunk, as it names it (`en`, `nb`) |
| `payload.content` | the text, one segment per line, a `text/plain` file in `attachments/` by digest; never inline |
| `payload.extra` | `recording` (the memo's `raw_id`, as RFC 0023 says), `chunks`, `segments`, `duration_s`, `turns` 0, `speakers` 0 |
| `payload.speakers` | only when the voices were separated (below): the voices, `S1`, `S2`, … or `mic`/`system`, each with its `seconds` and `turns` |
| `payload.diarization` | with `speakers`: `{engine, model, audio, channels, overlap_s, spans}`, the spans file in `attachments/` beside the text |

The transcript never carries `supersedes`. A memo that was retracted is left alone; a memo another
memo line supersedes (a re-import after a trim) is left alone and the standing one is transcribed,
its transcript pointing at the standing line.

A synthetic example, the Oslo persona's:

```json
{"at":"2026-03-02T20:14:07Z","end":"2026-03-02T20:15:49Z","tz":"Europe/Oslo","source":"transcription","kind":"transcript","tier":2,
 "payload":{"schema":"transcript/v1","provider":"mlx-whisper","raw_id":"7A1B2C3D-0000-4000-8000-000000000001",
 "title":"Idea for the talk","participants":[],"language":"nb",
 "content":{"sha256":"3f1a…","path":"attachments/3f1a…","bytes":412,"media_type":"text/plain"},
 "provenance":{"source":"019a2c3d-0000-7000-8000-000000000042","engine":"mlx-whisper","model":"small"},
 "extra":{"recording":"7A1B2C3D-0000-4000-8000-000000000001","chunks":1,"segments":7,"format":"text","turns":0,"speakers":0,"duration_s":102}}}
```

## The voices (RFC 0038)

When the diarizer and its models are on this machine (`logbook setup speakers` says whether they are;
`logbook setup speakers --fetch-model` fetches them, the one download), the same run separates the
voices of each memo on the audio it decoded, and the line gains `speakers` and `diarization`: each
line of the text is given the voice that speaks most of it (the engine is asked for word times), a
spans file goes into `attachments/` beside the text, and the progress line says how many voices it
heard (`Middag: 4,212 words, nb, 3 voices, 41.8s`). Without the diarizer the line is exactly as
before, and the run ends with one sentence:

```
speakers: not separated (logbook setup speakers --fetch-model)
```

`--no-speakers` turns separation off for a run. A memo is one room, its voices `S1`, `S2`, … by first
speech, unless its source says the file keeps a call's two sides apart, `extra.channels` naming the
file's channels in order (`["mic", "system"]`); then each channel is heard on its own and the
microphone's voice is `from_me` when it is alone there. Memos transcribed before the voices could be
separated are heard again by `logbook derive speakers`, each into a new line that supersedes the old
one. The fields, the labels, the spans file, the cost of hearing a transcript again and what the
readers show are on [Speakers](../speakers.md).

## Resumable

One line is appended per memo as soon as it is heard, and the command prints a line per memo as it
goes (`2026-03-02 21:14  Idea for the talk: 212 words, nb, 3.4s`). Stop it at any point: what was
heard is in the record, and the next run skips every memo that already has a transcript and carries
on with the rest. `--since YYYY-MM-DD` takes memos from that local day on. `--dry-run` lists what
would be transcribed and needs no engine installed.

Long recordings are heard in fixed windows of ten minutes; segment times are offset by the window's
start and the language detected on the first window is asked of every later one, so one recording is
heard in one language. A recording with no words in it writes no line and is counted.

## The engine, and nothing leaves the machine

Transcription is an optional extra, installed with `openlogbook[transcribe]`: on Apple silicon that
is [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (it decodes audio with
`ffmpeg`, which must be on the PATH), anywhere else [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
The engine is found at run time; with neither installed the command stops with a message naming the
extra. `--model` names a Whisper size (`tiny`, `base`, `small`, `medium`, `large-v3`; `small` by
default) or a Hugging Face repository; a size becomes `mlx-community/whisper-<size>-mlx` or
`Systran/faster-whisper-<size>`.

Audio never leaves the machine and the command opens no network connection: while it transcribes,
the Hugging Face hub is told it is offline (`HF_HUB_OFFLINE=1`, and the switch the hub client read
when it was first imported), so the engines cannot reach out whatever they would do on their own, and
pyannote.audio's own usage reporting is switched off (`PYANNOTE_METRICS_ENABLED=0`). The one exception
is explicit: a Whisper model not yet on this machine stops the command, and `--fetch-model` downloads
it before the first chunk is heard; it never fetches a speaker model, which is `setup speakers
--fetch-model`'s alone. The extra brings pyannote.audio, and with it torch, on every platform. A test
fakes the engine and the diarizer, feeds them a two-second synthetic WAV and refuses every socket for
the length of the run; no model is downloaded in CI.
