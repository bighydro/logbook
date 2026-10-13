# RFC 0038 — Speakers: who spoke, and who they are

Status: draft · 2026-10-13 · comment period: two weeks

A call recording keeps the two sides apart: the owner's microphone on one channel, the far end's audio on the other. A recording made in a room has one channel, so today every word of it reads as the owner's. The record then cannot tell the owner's words from a guest's; it cannot hand a guest a page of their own words; it cannot hold back one person's words when the owner has said that person's words stay home; and the people reader counts a dinner of three as the owner talking to nobody. Attribution is what makes rule 5, *the people in your log are protected before you are*, enforceable for the spoken word: a crossing can only keep someone's words home if the record knows which words are theirs.

This RFC separates the voices of a recording on this machine, gives each an anonymous label in the transcript line, and lets the owner, and only the owner, say whose voice each label is, one line per voice, beside the transcript and never inside it. A model proposes; the owner binds. The voiceprints that make proposals possible are a sealed cache that never leaves the machine.

What it proposes, all of it additive:

- two fields on `transcript/v1` (RFC 0004, frozen), `speakers` and `diarization`, as a dated amendment under RFC 0031 rule 1; a transcript without them stays valid and reads as it does today (§2);
- one ref kind, `speaker`, and four fields on `resolution/v1` (RFC 0006, frozen), likewise additive (§3);
- `review speakers`, a sitting in RFC 0037's `review KIND` shape (§4);
- a voiceprint registry, `voiceprints.age`, sealed, beside `places.json`, rebuilt from the record and never part of it (§5);
- a text-only road for transcripts whose audio is gone, as `draft/v1` (RFC 0036) proposals the owner confirms through the same review (§6);
- one ref kind on `people-review/v1` (RFC 0035, draft), one unit and one segment key on `draft/v1` (RFC 0036, draft), two keys on a `policy/crossing.json` entry (§9) and one settings file, `policy/speakers.json` (§5.5).

The envelope (SPEC §2–3) does not change: no spec version bump, no regenerated conformance fixture, no ADR for it. No profile is new. RFC 0037 is a draft on its own branch at the time of writing; where this RFC leans on it (the `review KIND` shape and the strongest-identifier order), it says what stands if 0037 is not adopted.

## 1. Words

- A **recording** is audio the record holds as an attachment (SPEC §1.1), today the `media` of a `voice-memo/v1` line (RFC 0023).
- A **channel** is one track of a recording. A call recorder keeps the owner's **microphone** (`mic`) and the far end's audio (`system`) apart; a room has one channel.
- A **voice** is what the diarizer heard as one speaker in one recording. It has a **label** (`S1`, `S2`, `mic`, `system`) that is anonymous: it says nothing about who.
- A **segment** is one unit of a transcript's text as its content file holds it: a line of `text/plain`, a cue of `text/vtt`, an element of a JSON segments array.
- An **attribution** is one `resolution/v1` line that binds one voice to one person (§3). The transcript line is never touched by it.
- The **owner's voice** is the voice the owner has bound to themselves, or the one voice the source puts on the owner's own microphone (`from_me`, §2.5). Every other voice is a **guest's**, whether or not it is named. A voice nobody has bound is **not yet named**, and is treated as a guest's until the owner says otherwise.
- A person the owner declines to name is **unnamed**: a person, not the owner, with no label (§3.2).
- A **voiceprint** is an embedding of a voice: a vector a speaker model computes from the audio, close to the vectors of the same voice in other recordings. It is biometric. The **registry** holds them (§5).
- The **basis** of an attribution is what it rests on: `channel` (the recording's channel and the call it was), `voice` (the audio is in the store and was heard, or matched against a voiceprint), `text` (the words alone).

## 2. Diarization at ingest: `transcript/v1` gains labels

### 2.1 What runs, and where

`derive transcripts` (the `openlogbook[transcribe]` extra, `logbook/labs/transcribe.py`) hears a recording's audio from the attachment store and writes one `transcript/v1` line (`docs/adapters/voice-memos.md`). With this RFC, when the diarization model is on this machine, the same run, on the same decoded audio, also separates the voices: a diarization pipeline finds who spoke when, each text segment is assigned the voice that speaks most of it, and the line carries the labels. When the model is not on this machine, the run transcribes exactly as today, writes no `speakers`, and says once at the end `speakers: not separated (logbook setup speakers --fetch-model)`; nothing stops. `--no-speakers` turns it off for a run.

Diarization is local. The audio is decoded on this machine and never leaves it; the Hugging Face hub is offline for the run (`HF_HUB_OFFLINE`, as `transcribe` has it today), so no engine can reach out whatever it would do on its own. The model download is the one network event, and it is a command of its own (§2.9).

### 2.2 The fields

Two payload fields, both MAY. A line with neither is a transcript as RFC 0004 defines it, and every reader reads it as before.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `speakers` | array of object | MAY | the voices of the recording, one per label, in order of first speech. Each: `{ label, seconds?, turns, channel?, from_me?, name? }` (below). Not to be confused with `extra.speakers`, the count the file adapter writes |
| `diarization` | object | MUST when `speakers` is present | how the labels were made: `{ engine, model?, audio?, channels, overlap_s?, spans? }` (below) |

A `speakers` entry:

| Key | Type | Req | Meaning |
|---|---|---|---|
| `label` | string | MUST | the voice's anonymous label (§2.4), unique within the line |
| `seconds` | number | SHOULD | how long the voice speaks, from the diarizer's turns; overlaps count for each voice, so the sum may exceed the recording. Absent when the source gives no times |
| `turns` | integer | MUST | how many segments of the content are assigned to the voice |
| `channel` | string | MAY | `mic` or `system`, the channel the voice is on, when the recording keeps channels apart (§2.5) |
| `from_me` | boolean | MAY | `true` when the source says the channel is the owner's own microphone and the channel holds this voice alone; absent is `false`. A statement of the source, never a resolution, as `from_me` is in `message/v1` (RFC 0008) |
| `name` | string | MAY | a name the source displayed for the voice (a provider's speaker name, a VTT `<v Name>` tag), kept so a reader has something to show; never a resolution, as `sender.name` is in `message/v1` |

`diarization`:

| Key | Type | Req | Meaning |
|---|---|---|---|
| `engine` | string | MUST | `pyannote`, `whisperx`, `channels` (no model ran: each channel is one voice, as the source split it), or the provider whose labels the adapter took (`granola`) |
| `model` | string | MAY | the pipeline as its engine names it: `pyannote/speaker-diarization-3.1` |
| `audio` | hex sha256 | MAY | the digest of the audio that was heard, the attachment the recording's line points at; absent when the labels came from a provider and the record holds no audio |
| `channels` | integer | MUST | how many channels the recording has: 1 for a room, 2 for a call that keeps its sides apart |
| `overlap_s` | number | MAY | the seconds in which two voices or more speak at once |
| `spans` | object | SHOULD when the source gives times | the spans file (§2.3), an attachment reference of SPEC §1.1 with `media_type` `application/json`, never inline |

The labels and their counts are in the line because every reader that asks *who was in this recording* (the people reader, the Day, the crossing) needs them and nothing else. The time spans, one per segment, are in a file the line points at, because they grow with the recording (a two-hour dinner is a thousand segments) and only the readers that split the words (the Library, `promises`, a crossing that cuts) need them.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"transcript/v1, the fields RFC 0038 adds","type":"object",
 "properties":{
  "speakers":{"type":"array","minItems":1,"items":{"type":"object","required":["label","turns"],
   "properties":{
    "label":{"type":"string","pattern":"^[^#\\n]{1,64}$"},
    "seconds":{"type":"number","minimum":0},
    "turns":{"type":"integer","minimum":0},
    "channel":{"type":"string","minLength":1},
    "from_me":{"type":"boolean"},
    "name":{"type":"string","minLength":1}},
   "additionalProperties":false}},
  "diarization":{"type":"object","required":["engine","channels"],
   "properties":{
    "engine":{"type":"string","minLength":1},
    "model":{"type":"string","minLength":1},
    "audio":{"type":"string","pattern":"^[0-9a-f]{64}$"},
    "channels":{"type":"integer","minimum":1},
    "overlap_s":{"type":"number","minimum":0},
    "spans":{"type":"object","required":["sha256","bytes","media_type"],
     "properties":{"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"path":{"type":"string","pattern":"^attachments/[0-9a-f]{64}$"},
      "bytes":{"type":"integer","minimum":0},"media_type":{"const":"application/json"}},
     "additionalProperties":false}},
   "additionalProperties":false}},
 "dependentRequired":{"speakers":["diarization"]}}
```

### 2.3 The spans file

One JSON object, stored once under its digest like any attachment, sealed when the line is (SPEC §1.1):

| Key | Meaning |
|---|---|
| `format` | `speaker-spans/1` |
| `content` | the digest of the content file whose segments it labels, so a spans file is never read against other text |
| `segments` | one entry per segment of the content, in the content's order: `{ from, to, speaker, overlap? }`. `from` and `to` are seconds from the line's `at`, two decimals; `speaker` is the label that speaks most of the segment, or `null` when no voice was found in it; `overlap` lists the other labels that speak in it for a second or more |
| `turns` | the diarizer's own turns, `{ from, to, speaker }`, overlapping where the voices did: who spoke when, independent of the text, from which `seconds` were counted and from which a voiceprint is cut (§5) |

The segments of a content file are counted by its media type: the non-empty lines of `text/plain` (one segment a line, as `transcribe` writes it), the cues of `text/vtt` and SRT, the elements of a JSON segments array, the turns of `text/markdown` as RFC 0004's readers parse them. A spans file whose `segments` do not number the content's segments is wrong; a reader that finds one says so and uses `turns` only.

### 2.4 Labels

A label matches `^[^#\n]{1,64}$`, so that a `speaker` ref (§3.1) splits at its first `#`, and is one of:

- `S1`, `S2`, … for the voices of a single channel, numbered by first speech (the pipeline's `SPEAKER_00` is `S1`);
- `mic` and `system` for a channel that holds one voice; `mic.1`, `mic.2`, `system.1`, … when the diarizer finds more than one voice in a channel;
- a provider's own label, verbatim, when an adapter takes the labels from the source (`Speaker 2`, `them`);
- `T1`, `T2`, … for the voices a text proposal separates (§6). These are never in `speakers`: the transcript they divide has none.

A label is the diarizer's, not a person's, and it is only meaningful inside its line: `S2` of one recording and `S2` of another are unrelated. That is why a voice is never identified by its label across recordings (§4.1).

### 2.5 Two channels

A recording that keeps the two sides of a call apart, a call recorder's stereo file with the microphone on one channel and the far end on the other, is diarized one channel at a time. A channel in which the diarizer finds one voice is labelled by the channel (`mic`, `system`); the `mic` voice carries `from_me: true`, because the source says the microphone is the owner's. A channel in which it finds several (a speakerphone in the room, a conference at the far end) is labelled `mic.1`, `mic.2`, … and none of them carries `from_me`: the owner is then proposed by voice like any other voice (§4). With no model on the machine the channels alone are the labels (`engine` `channels`), each channel one voice and the microphone's `from_me`, as the source split them.

A provider that labels each segment by its channel without giving the audio (Granola marks each segment as the microphone's, `me`, or the system audio's, `them`) gets the same shape from its adapter: the labels `mic` and `system` (`system.1`, `system.2` where the provider's own diarization tells the far end's voices apart), `engine` `granola`, no `audio`, `from_me` on the microphone's label, and the provider's display name, when it gives one, as `name`. The far end of a call is not resolved here; the review proposes it from the call (§4.3).

### 2.6 Overlapping speech

People talk over each other. The diarizer's `turns` overlap where they did, and each voice's `seconds` counts its own speech, so two voices that overlap for a minute both count the minute, and `overlap_s` says how much of the recording that was. A text segment spoken over goes to the voice that speaks most of it, with the others under `overlap`. Readers take it two ways, deliberately:

- for whose words a segment is when it is *shown* (the Library, `promises`), it is the `speaker`'s;
- for whose words it holds when something must be *held back* (an exclusion, a crossing, §9), it is the words of the `speaker` and of every voice in `overlap`.

A voiceprint is cut only from turns in which the voice speaks alone (§5), so an evening of interruptions does not blur two people into one. A label that holds two people the diarizer could not tell apart (two siblings, one corner of the table) cannot be bound to both: the owner leaves it not yet named or names it `unnamed` (§4.4), and a later diarization with a speaker-count hint may split it (§2.8).

### 2.7 When the audio is gone

The audio may never have been in the store (a memo imported without `--attachments`), may be missing from a copy of the record (SPEC §1.1: `verify` reports a missing attachment and passes), or the transcript may have come from a provider that never handed over audio. Then:

- **At ingest**, nothing is diarized; `transcribe` needs the audio anyway and skips such a memo as it does today. A provider's own labels, when the source gives them, are taken into `speakers` by the adapter, with no `audio` in `diarization`.
- **At review**, a voice whose recording has no audio in the store cannot be heard, played or matched: it gets no voice score, only the context of §4.3 and the text road of §6, and an attribution of it has basis `text`.
- **Attributions already written stand.** They are lines; the audio was evidence, not a dependency. A registry rebuild (§5.2) skips the recordings whose audio is gone and counts them, so a person's voiceprint is built from what remains.
- **A transcript with no labels and no audio** has one road left: the text proposals of §6.

### 2.8 Transcripts heard before this RFC

`logbook derive speakers [--since DAY] [--speakers N] [--dry-run]` diarizes the standing transcripts that have no `speakers` and whose recording's audio is in the store. The text is heard again, because a `text/plain` transcript keeps no times and the labels need them; the result is a new `transcript/v1` line with the new content, the labels, `supersedes` the old line's id, and `raw_id` `<the old raw_id>#speakers@<the first 12 hex of the spans file's digest>` (the `(source, raw_id)` dedupe would drop a second line under the same `raw_id`; the same spans give the same key and write nothing twice). The old line stays, superseded, as SPEC §3 has every correction. `--speakers N` is a hint to the pipeline that the room held N voices.

That is not free, and the command says so before it writes. A superseding line on a signed day changes the day's page, so the signature reads `page_matches` false until the owner reads the day again (RFC 0034). A sentence heard differently is a new `promises` proposal; SPEC §3.2.10 rule 2 takes a proposal's id from its origin line, so this RFC asks that it take the id of the *first* line of a supersedes chain, and a promise closed on the old line stays closed when its sentence is heard the same. `--dry-run` lists the signed days the run would touch and the closed promises whose sentence changes. Whether backfill should be a line of its own instead is open question 9.

### 2.9 The models, and the one download

Two candidates, both open source and both local:

- **pyannote.audio**, its pretrained pipeline `pyannote/speaker-diarization-3.1` and the embedding model it uses (`pyannote/wespeaker-voxceleb-resnet34-LM`), run directly after either Whisper engine: the turns are computed from the audio, and each text segment is given the voice that speaks most of it, by the segment's times or, where the engine gives them, its words'. It runs on the CPU and on Apple silicon through torch, so it serves both of today's engines (`mlx-whisper`, `faster-whisper`) without replacing either.
- **WhisperX**, which runs `faster-whisper`, aligns every word with a wav2vec2 model and assigns words to pyannote's voices. Its boundaries are better; it replaces the Apple-silicon engine and fetches an alignment model per language.

The recommendation is pyannote.audio behind both engines, with WhisperX an engine a later change may add off Apple silicon. The voiceprints of §5 use the diarization pipeline's own embedding model, so the registry and the diarizer agree on what a voice is; the registry names the model it was built with, and a change of model rebuilds it.

The extra `openlogbook[transcribe]` gains `pyannote.audio`, and with it torch on every platform, Apple silicon included (open question 13). The download is one command and nothing else downloads:

```bash
logbook setup speakers                    # what is here: the engine, the models, the registry, the owner's minutes; no socket
logbook setup speakers --fetch-model      # the one network event: the pipeline and its embedding model, into the Hugging Face cache
logbook setup speakers --rebuild          # the registry, again, from the record (§5.2); no socket
```

pyannote's pretrained pipelines are served by Hugging Face gated behind accepting their conditions; `--fetch-model` reads the owner's own access token from `HF_TOKEN` for that one request, never writes it, never prints it, and says which page to accept the conditions on when the hub refuses. `derive transcripts --fetch-model` still fetches the Whisper model and only that. No other command ever fetches a speaker model: `derive transcripts`, `derive speakers`, `review speakers` and the Library run with the hub offline, and a missing model is one sentence naming `setup speakers --fetch-model`. The network guard of `tests/test_no_network.py` gains `review speakers`, `setup speakers` without `--fetch-model`, and the Library's speaker pages; the socket guard of `tests/test_transcribe.py` covers a run that diarizes. No test loads a model: the diarizer is a fake engine, as `transcribe`, `judge` and `describe` are tested today.

## 3. Attribution: one `resolution/v1` line per voice

The transcript line records what the recording held: the words, the voices, their times. Who a voice belongs to is a judgement, made later, possibly wrong, and it belongs in a line of its own (RFC 0004, *Raw, not resolved*; RFC 0006, *Why this exists*; ADR 0013 rule 7). One `resolution/v1` line binds one voice to one person. Nothing in the transcript changes, ever.

### 3.1 The `speaker` ref

`resolution/v1` gains one ref kind:

| `ref.kind` | `ref.value` | Example |
|---|---|---|
| `speaker` | `<the id of the transcript line that carries the label>#<label>` | `019cadd3-6bc0-7dcd-9133-0000000004a1#S2` |

The value is the line's `id` (SPEC §2), as RFC 0006's `line` kind already names a line, because a label means something only in the line that carries it: a re-diarized transcript is a new line with new labels and new refs. For a text label (§6), the line is the transcript the proposal divided.

The addition is additive in RFC 0031's sense: no field is removed or retyped and no value withdrawn. A reader that does not know `speaker` resolves nothing through it, and loses nothing it read before, because no raw line carries a `speaker` ref in its own fields: the ref exists only to be looked up by a reader that reads `speakers`.

### 3.2 The fields

Four fields, all MAY in the profile, meaningful only on a line whose ref is a `speaker`; a writer MUST NOT put them on a line with any other ref:

| Field | Type | Req (on a `speaker` ref) | Meaning |
|---|---|---|---|
| `basis` | string | MUST | `channel`, `voice` or `text` (§1) |
| `consent` | string | MAY | `yes`, `no` or `unknown`: what the owner stated at review time about whether the person agreed to be recorded (§7). Absent reads as `unknown` |
| `unnamed` | `true` | MAY | the owner declined to name the person: the line names a person minted for this voice, or one minted earlier for a voice the owner said is the same, with no `label` |
| `spans` | object | MUST when `basis` is `text` and the label is a `T` label | the voice's words, `{ content, ranges }`: the digest of the content file and its byte ranges, half-open, `[[from, to], …]`, so that a reader learns the words of a text label from the line itself and never from the draft (RFC 0036 rule 4: no reader derives a fact from a draft) |

And three of RFC 0006's fields, constrained for a `speaker` ref:

- `source` is `manual` and `method` is `owner`. The model proposes; the owner binds. No adapter, no engine, no `dream`, no MCP tool writes a `speaker` resolution, and `policy/crossing.json`'s `write` names no tool that could.
- `confidence` is absent for basis `channel` and `voice`: the owner asserted it with the recording there to hear (RFC 0006: absent means asserted). For basis `text` it is present, the proposal's score divided by 100 and at most `text_confidence_cap` (0.6, §5.5), so a voice named from the words alone never reads as surer than one heard.
- `label` is the person's label at the time, as RFC 0006 has it; absent on an `unnamed` line, and on a line naming the owner, who is never listed (`docs/people.md`).

`entity` names a person: an existing one (`type` `person`, the person's id), the owner (`owner_id` of `logbook.json`, which `docs/people.md` already treats as the owner's entity), or a person minted by this line (RFC 0006, Minting: a new UUIDv7, with `label` when the owner gave a name, without when the owner declined). `alias_of` is allowed as RFC 0006 allows it: a voice may be said to be the same as another voice (`alias_of` a `speaker` ref), and resolves to whatever that one does.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"resolution/v1 with a speaker ref, the fields RFC 0038 adds","type":"object",
 "required":["ref","basis"],
 "properties":{
  "ref":{"type":"object","required":["kind","value"],"properties":{
   "kind":{"const":"speaker"},
   "value":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}#[^#\\n]{1,64}$"}}},
  "basis":{"enum":["channel","voice","text"]},
  "consent":{"enum":["yes","no","unknown"]},
  "unnamed":{"const":true},
  "spans":{"type":"object","required":["content","ranges"],"properties":{
   "content":{"type":"string","pattern":"^[0-9a-f]{64}$"},
   "ranges":{"type":"array","minItems":1,"items":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"integer","minimum":0}}}},
   "additionalProperties":false}}}
```

### 3.3 Rules

1. **The transcript is never rewritten.** An attribution never modifies the line it names (RFC 0006 rule 1). Readers join by ref.
2. **One standing line per voice.** The voice resolves to the entity of the last standing line for its ref (RFC 0006 rule 4), through the alias walk of rule 6. A line that is retracted (RFC 0003) binds nothing; the voice is not yet named again.
3. **A correction is a new line.** Re-attribution after a wrong answer writes a new `resolution/v1` for the same ref with `supersedes` naming the standing one (§4.5); the wrong line stays in the record, superseded, as every correction does (SPEC §3, rule 2 of the ten).
4. **`from_me` is the source's, an attribution is the owner's.** A voice with `from_me` is the owner's without a line. A standing attribution of that voice wins over it (someone else spoke into the owner's phone), and is the only thing that can.
5. **A voice of a transcript that is not standing names nobody.** An attribution whose transcript is retracted or superseded is read by nothing; it stays in the record, as RFC 0006 rule 3 keeps a resolution whose evidence went.
6. **Nothing requires an attribution.** A record without one is complete; every voice in it is not yet named, and is read as a guest's (§3.4).

### 3.4 How readers join the two

A reader finds a transcript's attributions as the standing resolution lines whose `speaker` ref begins with the transcript's id and `#`, which covers the voice labels of `speakers` and the text labels of §6 alike. Each voice is then one of: **the owner's** (bound to `owner_id`, or `from_me` with no attribution); **a person's** (bound to a person with a label); **unnamed** (bound with `unnamed`); **not yet named** (no line). A segment is its voice's, and, for holding back, also the voices' in its `overlap` (§2.6). A transcript without `speakers` and without text attributions is read exactly as today.

- **`people`**, **`people NAME`**, **`rollup people`** (`docs/people.md`). The `transcripts` channel counts a transcript for a person who is a participant (as today) or a voice bound to them, and a voice adds `spoke_s`, the seconds. Days together and nights under one roof come from `with`, below. The owner is never listed. An unnamed person is never a row: the report's head says `and 2 unnamed` and `--json` carries the count. Voices not yet named are not people: the head says `3 voices not yet named · review speakers`. A person's tier rises with an attribution at 3 (§8), as it does with any line.
- **`day`** and `serve`'s Day. A transcript's row gains who spoke: `Middag · you 31 min · Kari Nordmann 14 min · 1 unnamed · recorded with consent: unknown`, the consent shown when a voice that is not the owner's has a `consent` other than `yes` (§7). `--json` gains `speakers` on each entry of `attached.transcripts`: `{ label, person, name, seconds, basis, consent, owner }`, `person` null for an unnamed or not yet named voice.
- **`with`** (SPEC §3.2.5, company at a stay). A voice bound to a person, in a recording that overlaps the stay, is confirmed company with the reason `spoke in <title>`, ahead of rule 2's participant match, and the line's confidence becomes the reader's own `confidence` (a text attribution's 0.4 reads as 0.4). A voice of the `system` channel is the far end of a call: it counts for the person's `transcripts`, never as company, because they were not there. An unnamed voice confirms an unnamed person, counted and never named; a voice not yet named is nobody's company, as a diarizer's `Speaker A` is today. The people reader, the trips and `rollup people` take their days together from here, as they do now.
- **`digest`** names who spoke among the day's people and, once, how many voices of the day are not yet named, with the command.
- **`promises`** (SPEC §3.2.10 rule 3). The speaker of a sentence is the voice of its segment, bound, before every rule of today's; `owner` is true for the owner's voice, and a sentence of a guest's voice is `owed_to_owner` when it reads as a promise. A voice not yet named stays as spoken (`S2`), as a diarizer's label does today.
- **The Library** (`serve`). A transcript is read back segment by segment under each voice's name; a voice not yet named reads `voice 2 · not yet named` and links to *Who spoke?* (§4.6). No page renders a voiceprint, and none but the review shows a similarity.
- **`search`** is unchanged: it indexes no sealed words, and the speakers add none.
- **The crossing** reads whose words a transcript holds (§9).

## 4. `review speakers`

The sitting is RFC 0037's `review KIND` with the person kind's canonical side and a new observed side: the observed thing is a voice, the canonical thing is a person, and the answers write the lines of §3. It is `logbook review speakers`; until RFC 0037's `review` exists, the same queue and the same answers are `logbook people review --speakers`. It reads the record, the registry and the settings; it opens no connection; it writes only through `Logbook.append`.

### 4.1 The observed voice

People review learned that an observed identity must come from the strongest identifier the observation carries, never from the id a source gives one observation, or one person explodes into a row per observation (`docs/people.md#review`; RFC 0037 §4). A label is exactly such an id. So the queue's row is an **observed voice**, keyed by the strongest identifier a voice carries, in this order:

1. **the far end of a call**: the voice is alone on the `system` channel of a recording that overlaps a `call/v1` line (RFC 0012), and the call's `counterparty` is an email or a phone. The voice is then the observed person of that ref, and its row is keyed as people review keys one: email, else phone;
2. **else the voice itself**: the cluster its voiceprint falls into among the voices not yet named, every voice within the `match` similarity (§5.5) of the cluster's centre. The same unknown guest heard at four dinners is one row with four recordings;
3. **else the name the source displayed** (`name`, §2.2), its words folded and sorted, as people review's name rule;
4. **else the label alone**: a voice with no audio to embed and no name, or with less clean speech than `min_clean_s`. One row per label, which is acceptable only because such voices are few.

An answer to a row is an answer for every voice in it: one line per voice, since a line binds one ref (RFC 0006 rule 2). A row's recordings are numbered `N.1`, `N.2`, …, and an answer to `N.2` is for that recording's voice alone, which is how the owner splits a cluster that joined two people.

### 4.2 The queue

```bash
logbook review speakers                          # the queue: voices not yet named, yours first, then recording by recording
logbook review speakers --json                   # the queue, with the evidence, the stable ids and the counts
logbook review speakers --accept 1,2 --consent 2=yes
logbook review speakers --name 3 "Kari Nordmann" # a person the record knows by that label, a ref or an id; else minted
logbook review speakers --unnamed 3              # a person, not the owner, whom the owner will not name
logbook review speakers --unnamed 5 --same-as 3  # the same unnamed person as voice 3, not a new one
logbook review speakers --reject 4
logbook review speakers --all-above 70
logbook review speakers --play 2                 # the voice's first twenty seconds alone, on this machine; nothing written
logbook review speakers --named --recording ID   # the voices of a recording already named, to correct one (§4.5)
```

```
5 voices not yet named in 2 recordings, 4 rows · 37 named · tier 2
   1  [70]  a voice in 2 recordings, 41 min → you: same voice 0.86 (from 212 min of your calls)
      1.1  Sat 2026-10-03 19:40 · Home · "Middag" · S1 · 31 min · "Har du sett hvor høyt vannet står?"
      1.2  Sat 2026-10-10 12:05 · aboard solvind · "Tur" · S1 · 10 min · "Vi går for seil til Drøbak."
   2  [20]  Sat 2026-10-03 19:40 · Home · "Middag" · S2 · 14 min · "Beklager, ferja var sen."
            → Kari Nordmann: on the entry "Middag med Kari" · seen that day (message 18:02) · no voiceprint yet
            that day: Kari Nordmann (calendar, message), Ola Nordmann (message)
   3  [—]   same recording · S3 · 41 s · "Hei, jeg skal bare levere en pakke."
            → ____ (no voice like it, nobody else on the entry)
   4  [50]  Sat 2026-10-10 12:05 · aboard solvind · "Tur" · S2 · 9 min · "Skal vi ta inn et rev?"
            → Ola Nordmann: same voice 0.66 · seen that day (call 08:40)
nothing written: `review speakers --accept N[,N]`, `--name N "…"`, `--unnamed N`, `--reject N[,N]`, `--consent N=yes|no|unknown`, or `--all-above SCORE`
```

Each row shows what the owner needs to remember the evening: the day, the place (the stay the recording overlaps, named as the Day names it), the recording's title, the voice's label and how long it spoke, its first segment quoted, the candidate with what speaks for it, and, for a guest, who else the record resolved that day. The owner's row comes first, since one answer settles most voices; then the recordings in the order they were made, so the evenings are worked through as they happened, and within a recording the voices by seconds spoken; the numbers are the queue's at this head, and `--json` carries a stable `id` per row and candidate, the first 16 hex of the SHA-256 of the row's refs, sorted, and the candidate's id. On a terminal the command asks for each row: `y` accepts, `n` rejects, `u` is unnamed, `p` plays, anything else is a name, Enter skips, `q` stops; after a name or an `unnamed` for a voice that is not the owner's it asks `recorded with their consent? y / n / Enter for unknown`. Each answer is written at once, as `places review` does.

### 4.3 The score

A plain sum, as people review's and RFC 0037's:

| Evidence | Points | What it means |
|---|---|---|
| same voice | up to 70 | the voice's clean speech against the person's voiceprint (§5): 70 at a similarity of `match` or more, falling in a straight line to 0 at `floor`, nothing below it (§5.5). Against the owner's voiceprint as against anyone's |
| the far end of a call | 40 | the voice is alone on the `system` channel and the recording overlaps a `call/v1` line whose `counterparty` resolves to the person |
| on the entry | 15 | the person attends a timed `event/v1` the recording overlaps, held at the same stay (SPEC §3.2.5 rule 1) |
| a participant | 15 | a `participants` entry of the transcript resolves to the person by email, phone or provider id; 5 by a name alone |
| the source's name | 10 | the voice's `name` is the person's label, or a word of it the record gives nobody else |
| seen that day | 5 | another line of the recording's local day resolves to the person: a message, a call, a tagged face |

**Context never stands in for a voice.** A candidate with neither `same voice` nor `the far end of a call` scores 40 at most, however much context it has, so `--all-above` above 40 never takes a guest named by context alone. The first time a guest is recorded there is no voiceprint, and context is all there is; it proposes, low, and the owner's answer is what makes the voiceprint.

**Two close candidates are both shown and neither is taken.** When the two best candidates of a row are within 5 points, the row lists both, and `--all-above` skips it (open question 1).

A voice with no candidate is shown with a blank, `____`, for the owner to name, mark unnamed, or skip.

### 4.4 The owner's say: what each answer writes

Nothing is bound on its own. Every number in one command is checked before the first line is written; a number the queue does not have, one both accepted and rejected, a consent for a row not answered, or a score that is not a whole number exits 2 and writes nothing.

| Answer | Writes |
|---|---|
| `--accept N` | per voice of the row, one `resolution/v1`: the `speaker` ref, `entity` the candidate (a person, or `owner_id` for *you*), `label` the person's, `method` `owner`, `basis` (`channel` for the far end of a call, `voice` when the audio is in the store, else `text`), `consent` when given, `confidence` for basis `text`, `evidence` the transcript and the lines the score rested on, `logbook_head`, and under `extra` the row's id, the score and what matched |
| `--name N "…"` | the same, to the one person the record labels so (case aside), or names by that ref or id; a name nobody has mints a person (RFC 0006, Minting) with that label; a name several people have exits 2 and asks for a ref |
| `--unnamed N` | the same, `entity` a person minted for the voice with no `label`, and `unnamed: true`; with `--same-as M`, the person voice M is already bound to unnamed, so a stranger heard twice is one stranger |
| `--reject N` | one `people-review/v1` line (RFC 0035, with the ref kind `speaker` this RFC adds to it): verdict `different`, `ref` the row's first voice, `refs` every voice of the row, `entity` the candidate. The pair is never proposed again; the voices stay in the queue, with the next candidate or a blank |
| `--consent N=…` | nothing of its own: it sets `consent` on the line the row's answer writes |
| skip | nothing |

The owner's voice is answered like any other: proposed, never bound by the model. The difference is only that the owner's row is usually one row for hundreds of recordings, and one `y` writes a line for each.

### 4.5 A wrong answer

The record keeps the mistake and the correction. `review speakers --named` lists the voices already named, of one recording with `--recording ID` or of a day with `--day DAY`, numbered as the queue is, each with its standing attribution; any answer to one writes a new line for the same ref with `supersedes` naming the standing line. A wrong no is undone by retracting the `people-review` line (RFC 0035 rule 3). A wrong yes can also be retracted (`repair retract SEQ`), which returns the voice to the queue. In every case the registry forgets the wrong voice at its next write (§5.2), so a mistake never keeps teaching the voiceprint.

### 4.6 In the browser

The Library's Day shows *who spoke?* under a transcript with a voice not yet named, and the link opens the recording's voices with the questions of the terminal: the first lines, the context, the candidate, a player for the voice's first twenty seconds alone, served from the attachment store over the loopback connection, and **Name**, **Not this person**, **Won't name** and **Skip**. They post through the review's own code, as the Places page's *Name this place* does (`docs/serve.md`), and are answered from this machine only: a loopback client and, when the browser sends one, an `Origin` of `127.0.0.1` or `[::1]`; anything else is a `403` and nothing is written.

## 5. Voiceprints

### 5.1 The registry

A voiceprint is an embedding of a voice. It is biometric: it identifies a person by their body, it is the same in every recording of them, and anyone with the model can compare it to any recording anywhere. It is the one thing in this design that could identify a guest who never agreed to be in the record, to someone who has never seen the record. Everything about the registry follows from that.

The registry is one file, `voiceprints.age`, in the record folder beside `places.json` and `assets.json`, so that it lives on the record's home with the record (ADR 0022) and is sealed to the record's own recipients. It is an age file (RFC 0029 §7's form) of one JSON document, replaced whole on each write (a temporary file, then a rename), holding:

- `format` (`voiceprints/1`), the embedding `model` and its digest, `dim`, and the `head` it was last written at;
- `people`: per entity id, the voiceprint (the centre of the person's clean-speech embeddings), the seconds of clean speech it rests on, and the `speaker` refs it was built from;
- `voices`: per `speaker` ref of a voice not yet named, its embedding and its clean seconds, so the review compares without loading a model.

No audio, no words, no names: the names are in the record, and the registry holds ids. Clean speech is the voice's `turns` in which it speaks alone, two seconds at least each; a voice with less than `min_clean_s` of it gets no embedding.

A record that names no `recipients` (SPEC §1) keeps no registry on disk. The review then computes the embeddings it needs in memory for the run, from the audio, with the model, and forgets them on exit; without the extra, it proposes from context and channels alone. `doctor` says which of the two the record is in.

### 5.2 A cache

Rule 2 of the ten, *written as it happens, never rewritten*, is the record's rule. The registry is not the record: like `index.sqlite`, it is a cache in ADR 0001's sense, made from the record and thrown away without loss. It is built from two things the record holds, the audio attachments the transcripts' `diarization.audio` names and the standing attributions (with the `from_me` voices), and `setup speakers --rebuild` makes it again from them. So:

- it is rewritten freely, because nothing in it is a fact: each answer in the review updates the person it named, each `derive transcripts` adds its new voices, and a retracted or superseded attribution leaves the person's voiceprint at the next write, because the voiceprint is recomputed from the refs that stand;
- `verify` ignores it: it is not a line, not an attachment, not in SPEC §1's layout, and not part of conformance;
- `backup` leaves it out, as it leaves `state/` out: it is rebuildable, and one copy of a biometric is the most there should be. A restored record rebuilds it, from the audio, which the backup does carry;
- a model change rebuilds it, since two models' vectors are not comparable; `doctor` says when the file was built with a model that is not the configured one.

### 5.3 It never leaves

The registry is part of no crossing, whatever the tier and whatever a policy entry says: not the crossing package (RFC 0005), the shared page (RFC 0025), the trip bundle (RFC 0030), the vault, the site, an MCP tool's answer, a `dream`'s material, or `export` of any kind. No tier is low enough to describe it, because a tier says what a line may give away (SPEC §4), and the registry is not a line and may give away nothing. Nothing opens it but the review, the Library's *Who spoke?*, the commands that write it (`derive transcripts`, `derive speakers`, `setup speakers`) and `doctor`, which prints that the file exists, when it was built, with which model and for how many people, and never what is in it; the index holds no embedding, and no reader prints a vector. A test of the code that lands with this RFC builds every crossing over a record with a registry and asserts that neither the file nor any of its vectors is in any of them.

### 5.4 The owner's voice

The owner's voice is enrolled without asking, from the owner's own microphone: every voice with `from_me` whose audio is in the store is folded into the owner's voiceprint, and so is every voice the owner has bound to themselves. Enrolment writes no line; it is the registry, and it is rebuilt like the rest. Every other voice is named only by the owner, through the review: a guest's voiceprint begins at the owner's first answer for that guest, and grows with each later one. Until the owner has a call on record or has answered once for themselves, there is no voiceprint of the owner, and the owner's voice is proposed by nothing and asked like any other.

### 5.5 `policy/speakers.json`

One setting, read each run, never a line, backed up with `policy/`:

```json
{"match": 0.75, "floor": 0.5, "min_clean_s": 8, "text_confidence_cap": 0.6, "enrol_unnamed": false, "forget": []}
```

- `match` and `floor` are the similarities at which a voice scores its full 70 points and none (§4.3); they are the embedding model's, hypotheses until calibrated (open question 12), as `policy/stays.json`'s constants are.
- `min_clean_s` is the clean speech, in seconds, below which a voice is neither embedded nor proposed by voice.
- `text_confidence_cap` bounds the `confidence` of a text attribution (§3.2).
- `enrol_unnamed`, `false` by default: an unnamed person's voices are not folded into a voiceprint, so a stranger the owner would not name is not recognised next time either; with `true` they are, and `--same-as` is proposed (open question 7).
- `forget` lists entity ids whose voiceprint the registry never holds and against whom no voice is ever proposed (open question 2).

## 6. Text-only attribution

When there is no audio, the words are all there is. A writer may then read a transcript's text and propose who spoke which part, as a `draft/v1` line (RFC 0036): a proposal, every claim with its evidence or marked unsupported, never a fact until the owner confirms it through the review of §4.

**The writer.** `logbook dream speakers [ID] [--days N]` reads one transcript (or each transcript of the last N days with no `speakers`, no audio and no standing text attributions) and asks a model to divide it into voices. Reading a transcript to divide it is reading other people's words in full, so it is a crossing like the dream's (`docs/dream.md`), governed by an entry of its own, `speakers`, in `policy/crossing.json`: its `max_tier`, its `until`, its `model`. No entry, or an expired one, and it refuses in one sentence; a transcript above the ceiling is not read. A transcript written at tier 3 (the file adapter's default) is divided only under an entry of 3. The owner can point the entry at a model on this machine; whether it must be one is open question 11.

**The line.** RFC 0036's `draft/v1` with two amendments this RFC proposes to that draft profile: the `unit` `transcript`, whose `subject` is `[<the transcript line's id>]` and whose lines are the transcript and the lines of the local days it touches under the ceiling; and the segment key `attribution`, MAY, for that unit only:

| Key | Meaning |
|---|---|
| `label` | the text label the writer gives the voice, `T1`, `T2`, … (§2.4); or the provider's label, when the transcript has one, so a provider's `Speaker 2` is proposed under its own name |
| `spans` | `{ content, ranges }`, as in §3.2: the content file's digest and the byte ranges of this voice's words; absent for a provider's label, whose segments are its own |
| `person` | the person proposed, `{ type, id, registry }` (`owner_id` for the owner), or null: a voice the writer could separate and could not name |
| `score` | the writer's score, 0–100 |

Each segment's `text` says why, in a sentence (`The voice of lines 12–40 is called Kari twice, and Kari Nordmann attends the calendar entry this recording overlaps`), and its `evidence` names the lines it rests on. A segment whose evidence is the transcript alone is `unsupported` (RFC 0036's rule: there is no third shape), and an unsupported segment may divide a voice but never proposes a person: the transcript alone is the claim, not evidence for it.

**The confirmation.** `review speakers` shows the standing text proposals among the voices, with basis `text`, the first words of the span, the evidence, and the draft's id, scored as the writer scored them and never above 40 (context never stands in for a voice, §4.3). Accepting one writes the `resolution/v1` of §4.4 with `basis` `text`, `spans` copied from the proposal (so that no reader ever reads the draft for it), `confidence` the score over 100 capped at `text_confidence_cap`, and `evidence` the draft's id with the segment's evidence. The line is marked as the guess it partly is, and every reader shows a text attribution with its basis: `Kari Nordmann (by the words)`.

## 7. Consent

The capture step is the moment the other person's say begins: whoever pressed record knew who was in the room, and that is the owner, so the owner is the one the record asks. The format does not decide what consent is, whether it was needed, or whether it was valid; it records what the owner states at review time, as the field `consent` on the attribution line, `yes`, `no` or `unknown`, absent meaning `unknown`. It is a statement by the owner, not a legal claim, and no proposal ever fills it: the review asks once per voice the owner names or declines to name, Enter leaves it unknown, and a later statement is a new attribution that supersedes the old (§3.3 rule 3). A reader MAY show `recorded with consent: unknown` (or `no`) beside a transcript that holds a voice not the owner's whose consent is not `yes`, and the Day, the person page and the Library do; no reader and no crossing in this RFC decides anything from the field (open question 14).

## 8. Tiers

SPEC §4: derived data inherits the highest tier of its evidence, and a profile names the tier its producers write by default. Rule 5 of the ten says what someone said to you is the most protected thing in the record.

| What | Tier | Reasoning |
|---|---|---|
| `transcript/v1` with `speakers` | 2, as RFC 0004 says; 3 where its producer writes 3 (the file adapter, `granola`, `wispr-flow` do) | the labels are anonymous, and the counts and times say no more than the words they index. Diarization does not change the tier of a transcript (open question 10) |
| the spans file | the transcript's | a file a tier 2–3 line points at is sealed with it (SPEC §1.1) |
| `resolution/v1`, a `speaker` ref | the transcript's: 2 in practice, 3 when the transcript is 3 | the highest tier of its evidence, as RFC 0006 says, and its evidence always includes the transcript, so it is never lower than the transcript's. It turns a voice into a name, which is more identifying than the voice's label (RFC 0006, *Privacy*) |
| the same, `unnamed` | the same | it names nobody, but it says a person who is not the owner was there and spoke |
| `people-review/v1`, a `speaker` ref | as RFC 0035: the highest tier of its evidence | |
| `draft/v1`, unit `transcript` | the highest tier among the lines it read (RFC 0036): the transcript's at least | the model read the words in full |
| `voiceprints.age` | none, and it never leaves (§5.3) | not a line; biometric; sealed always, kept only where the record can seal it |
| `policy/speakers.json` | a setting, not a line | it holds thresholds and entity ids, no voice |

The chain of reasoning is short: the transcript is tier 2; an attribution of one of its voices is derived from it and inherits tier 2; the voiceprint of that voice is derived from the audio and the attribution together, and is not given a tier at all, because the answer to *where may it cross* is nowhere.

## 9. What the crossing can now enforce

Lines cross verbatim (RFC 0005), so a transcript crosses whole or stays home: cutting a transcript down to one person's words is a derived page, not this RFC (§12). What attribution adds is that a crossing can now know whose words a transcript holds, and two keys on a `policy/crossing.json` entry use it, added to ADR 0016's file as RFC 0036 added `signed_within_days`:

- `exclude_people`, a list of entity ids: a line holding an excluded person's words never crosses through the entry, whatever its tier and whatever the request: a transcript with a voice bound to them (as `speaker` or in `overlap`), a message whose `sender` resolves to them, a mail from them. The attribution and resolution lines that name them stay home too. Absent, nobody is excluded.
- `hold_unattributed`, a boolean: a transcript with a voice not yet named never crosses through the entry. Absent, `false`: today's behaviour, the tier gate alone (open question 15).

```json
{"hermes": {"max_tier": 2, "exclude_people": ["019cadd3-6bc0-7dcd-9133-000000000402"], "hold_unattributed": true},
 "speakers": {"max_tier": 3, "until": "2026-12-31", "model": "qwen2.5-7b-instruct"}}
```

The manifest of a crossing package counts what the keys held back (`counts.held_back_people`, `counts.held_back_unattributed`) and never names whom; the `crossing/v1` line's `policy` carries the keys as the entry has them (RFC 0011, additive); `doctor` prints them on the entry's line. The attribution lines a package ships as its resolution overlay are bounded by the request as every overlay line is (ADR 0016 rule 5). The voiceprint registry crosses through no entry (§5.3).

## 10. Dedupe keys

| What | Key | A second write |
|---|---|---|
| a transcript at ingest | `(source, raw_id)`, as today (ADR 0017) | writes nothing |
| a transcript diarized after the fact (§2.8) | `(source, <raw_id>#speakers@<12 hex of the spans digest>)` | the same spans write nothing; other spans are a new line superseding the last |
| an attribution | the `speaker` ref: one standing line per voice (RFC 0006 rule 4) | the same entity, basis and consent as the standing line write nothing; anything else is a new line with `supersedes` |
| an unnamed person | the `speaker` ref, as an attribution; the person minted once per voice, or reused with `--same-as` | `--unnamed` on a voice already bound unnamed writes nothing |
| a no | `(ref, entity)`, RFC 0035 rule 2, any voice of the row in `ref` or `refs` | writes nothing |
| a text proposal | `(source, unit, subject, read_head)`, RFC 0036 rule 1 | writes nothing |
| a voiceprint | `(entity id, embedding model)` in the registry | not a line: replaced |
| a row in `--json` | the first 16 hex of the SHA-256 of the row's refs, sorted, and the candidate's id | the same row, the same id, at any head that still has it |

## 11. Examples (synthetic)

The owner is Ines Nordmann of Oslo, who does not exist; her `owner_id` here is `019cadd3-6bc0-7dcd-9133-000000000400`. Ola Nordmann (`ola@example.org`, `+4790000001`) and Kari Nordmann (`kari@example.org`, `+4790000002`) are in her contacts. On Saturday 3 October 2026 Kari comes to dinner; Ines records it with Voice Memos, and a neighbour drops off a parcel halfway through. Hashes are shortened.

The dinner, transcribed and diarized at ingest, three voices:

```json
{"at":"2026-10-03T17:40:12Z","end":"2026-10-03T18:52:30Z","tz":"Europe/Oslo","source":"transcription","kind":"transcript","tier":2,
 "payload":{"schema":"transcript/v1","provider":"mlx-whisper","raw_id":"7A1B2C3D-0000-4000-8000-000000000038",
 "title":"Middag","participants":[],"language":"nb",
 "content":{"sha256":"5e0c…","path":"attachments/5e0c…","bytes":38214,"media_type":"text/plain"},
 "provenance":{"source":"019cadd3-6bc0-7dcd-9133-0000000004a0","engine":"mlx-whisper","model":"small"},
 "speakers":[{"label":"S1","seconds":1862.4,"turns":212},{"label":"S2","seconds":861.0,"turns":97},{"label":"S3","seconds":41.5,"turns":4}],
 "diarization":{"engine":"pyannote","model":"pyannote/speaker-diarization-3.1","audio":"c41d…","channels":1,"overlap_s":38.2,
  "spans":{"sha256":"a9e2…","path":"attachments/a9e2…","bytes":21877,"media_type":"application/json"}},
 "extra":{"recording":"7A1B2C3D-0000-4000-8000-000000000038","chunks":8,"segments":313,"format":"text","duration_s":4338}}}
```

The first three of its 313 segments and of its turns, from the spans file; Ines and Kari overlap in the third:

```json
{"format":"speaker-spans/1","content":"5e0c…",
 "segments":[{"from":2.10,"to":6.42,"speaker":"S1"},{"from":6.42,"to":11.80,"speaker":"S2"},{"from":11.80,"to":14.95,"speaker":"S1","overlap":["S2"]}],
 "turns":[{"from":2.04,"to":6.51,"speaker":"S1"},{"from":6.38,"to":12.02,"speaker":"S2"},{"from":11.66,"to":15.10,"speaker":"S1"}]}
```

A call with Ola on Tuesday, recorded on two channels, one voice on each:

```json
{"at":"2026-10-06T07:15:03Z","end":"2026-10-06T07:22:28Z","tz":"Europe/Oslo","source":"transcription","kind":"transcript","tier":2,
 "payload":{"schema":"transcript/v1","provider":"mlx-whisper","raw_id":"7A1B2C3D-0000-4000-8000-000000000039",
 "title":"Samtale","participants":[],"language":"nb",
 "content":{"sha256":"0b77…","path":"attachments/0b77…","bytes":5120,"media_type":"text/plain"},
 "provenance":{"source":"019cadd3-6bc0-7dcd-9133-0000000004a3","engine":"mlx-whisper","model":"small"},
 "speakers":[{"label":"mic","seconds":201.7,"turns":38,"channel":"mic","from_me":true},{"label":"system","seconds":188.3,"turns":35,"channel":"system"}],
 "diarization":{"engine":"pyannote","model":"pyannote/speaker-diarization-3.1","audio":"7b02…","channels":2,"overlap_s":4.1,
  "spans":{"sha256":"e5d0…","path":"attachments/e5d0…","bytes":2954,"media_type":"application/json"}}}}
```

That evening Ines answers the call's one row: the far end, proposed from the call line, whose number resolves to Ola (`[40]`, the far end of a call), accepted:

```json
{"at":"2026-10-06T19:30:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a2#system"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-043f5aabf2a9","registry":"logbook"},"label":"Ola Nordmann",
 "method":"owner","basis":"channel","consent":"unknown",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000004a2","019cadd3-6bc0-7dcd-9133-0000000004e3"]}}
```

The dinner she leaves for later. On Sunday 11 October, after a sail on the Saturday, she sits down with the queue of §4.2. Row 1 accepted: `S1` of the dinner (and of the sail) is Ines, matched against the voiceprint her calls built; one of the two lines it writes:

```json
{"at":"2026-10-11T08:12:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a1#S1"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000400","registry":"logbook"},
 "method":"owner","basis":"voice","evidence":["019cadd3-6bc0-7dcd-9133-0000000004a1"],"logbook_head":"8f1c…",
 "extra":{"proposal":"3c9a51d0e2f4b7a6","score":70,"matched":["same voice 0.86"]}}}
```

Row 2 accepted with `--consent 2=yes`: `S2` is Kari, proposed from the calendar entry and her message that afternoon, there being no voiceprint of her yet:

```json
{"at":"2026-10-11T08:12:30Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a1#S2"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000402","registry":"logbook"},"label":"Kari Nordmann",
 "method":"owner","basis":"voice","consent":"yes",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000004a1","019cadd3-6bc0-7dcd-9133-0000000004e1","019cadd3-6bc0-7dcd-9133-0000000004e2"],
 "logbook_head":"8f1c…","extra":{"proposal":"77b0c2e19a4d5f38","score":20,"matched":["on the entry Middag med Kari","seen that day"]}}}
```

Row 3, `--unnamed 3`: the neighbour, a person who is not Ines, whom she will not name. A person is minted for the voice, with no label:

```json
{"at":"2026-10-11T08:13:10Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a1#S3"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000403","registry":"logbook"},
 "method":"owner","basis":"voice","unnamed":true,"consent":"unknown","evidence":["019cadd3-6bc0-7dcd-9133-0000000004a1"]}}
```

Row 4 of the queue, `--reject 4`: the voice aboard on the 10th is not Ola, whatever its similarity (it was his cousin, whom Ines will name another day). The no, so the pair is never proposed again:

```json
{"at":"2026-10-11T08:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"people-review","tier":2,
 "payload":{"schema":"people-review/v1","verdict":"different",
 "ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a4#S2"},
 "refs":[{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a4#S2"}],
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-043f5aabf2a9","registry":"logbook"},"label":"Ola Nordmann",
 "method":"owner","evidence":["019cadd3-6bc0-7dcd-9133-0000000004a4"],"logbook_head":"8f1c…"}}
```

On Monday 12 October Ines plays the call again: it was Kari who answered Ola's phone. The correction supersedes Tuesday's attribution (its id was `…04b4`); the wrong answer stays in the record, and Ola's voiceprint drops the voice at the registry's next write:

```json
{"at":"2026-10-12T20:05:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a2#system"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000402","registry":"logbook"},"label":"Kari Nordmann",
 "method":"owner","basis":"voice","consent":"unknown","supersedes":"019cadd3-6bc0-7dcd-9133-0000000004b4",
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000004a2"]}}
```


An older recording, a talk on the ferry quay in August 2025, added from a plain-text file by the file adapter (tier 3) with no labels and no audio. A local model divides it under the `speakers` entry; the third segment rests on the transcript alone, so it may divide a voice and names nobody:

```json
{"at":"2026-10-12T21:00:00Z","end":null,"tz":"Europe/Oslo","source":"model:qwen2.5-7b-instruct","kind":"draft","tier":3,
 "payload":{"schema":"draft/v1","unit":"transcript","subject":["019cadd3-6bc0-7dcd-9133-0000000004a5"],
 "read_head":"b2c7…","read_count":6,"language":"nb",
 "segments":[
  {"text":"The voice of lines 1–11 and 41–60 speaks of the note it wrote that morning about the ferry quay.",
   "evidence":["019cadd3-6bc0-7dcd-9133-0000000004a5","019cadd3-6bc0-7dcd-9133-0000000004e6"],
   "attribution":{"label":"T1","spans":{"content":"d71f…","ranges":[[0,1840],[6211,9032]]},
    "person":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000400","registry":"logbook"},"score":40}},
  {"text":"The voice of lines 12–40 is called Kari twice, and Kari Nordmann attends the calendar entry this recording overlaps.",
   "evidence":["019cadd3-6bc0-7dcd-9133-0000000004a5","019cadd3-6bc0-7dcd-9133-0000000004e5"],
   "attribution":{"label":"T2","spans":{"content":"d71f…","ranges":[[1840,6211]]},
    "person":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000402","registry":"logbook"},"score":40}},
  {"text":"A third voice may speak in lines 61–64.","unsupported":true,
   "attribution":{"label":"T3","spans":{"content":"d71f…","ranges":[[9032,9874]]},"person":null,"score":10}}]}}
```

Ines confirms `T2` in the review. The line inherits tier 3 from the transcript, carries the words' byte ranges so no reader needs the draft, and says how sure it is:

```json
{"at":"2026-10-12T21:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":3,
 "payload":{"schema":"resolution/v1","ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a5#T2"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000402","registry":"logbook"},"label":"Kari Nordmann",
 "method":"owner","basis":"text","confidence":0.4,"consent":"unknown",
 "spans":{"content":"d71f…","ranges":[[1840,6211]]},
 "evidence":["019cadd3-6bc0-7dcd-9133-0000000004d1","019cadd3-6bc0-7dcd-9133-0000000004a5","019cadd3-6bc0-7dcd-9133-0000000004e5"],
 "logbook_head":"b2c7…"}}
```

Not a line: part of what `voiceprints.age` holds once opened, on the evening of 11 October (each vector has 256 numbers, of which three are shown; the lists are shortened, Ola among the people left out):

```json
{"format":"voiceprints/1","model":"pyannote/wespeaker-voxceleb-resnet34-LM","model_sha256":"4f8a…","dim":256,"head":"8f1c…",
 "people":{
  "019cadd3-6bc0-7dcd-9133-000000000400":{"voiceprint":[0.0123,-0.0871,0.0402],"clean_s":12720.4,
   "from":["019cadd3-6bc0-7dcd-9133-0000000004a2#mic","019cadd3-6bc0-7dcd-9133-0000000004a1#S1"]},
  "019cadd3-6bc0-7dcd-9133-000000000402":{"voiceprint":[-0.0310,0.0544,0.0917],"clean_s":702.9,
   "from":["019cadd3-6bc0-7dcd-9133-0000000004a1#S2"]}},
 "voices":{
  "019cadd3-6bc0-7dcd-9133-0000000004a4#S2":{"embedding":[0.0072,-0.0145,0.0663],"clean_s":402.0}}}
```

The neighbour is in neither: `enrol_unnamed` is `false`.

## 12. What changes when adopted, and what does not

**Changes**, each in the change that implements it, not in this one:

- RFC 0004 gains a dated amendment, `speakers` and `diarization`, additive under RFC 0031 rule 1. Its fixture under `conformance/profiles/` is unchanged: its line carries neither field.
- RFC 0006 gains a dated amendment, the ref kind `speaker` and the fields `basis`, `consent`, `unnamed` and `spans`, additive likewise; its fixture is unchanged.
- RFC 0035's `people-review/v1` takes the ref kind `speaker`; RFC 0036's `draft/v1` takes the unit `transcript` and the segment key `attribution`. Both are drafts.
- SPEC §3.2.5 rule 2 (company) reads voices by attribution and keeps the far end of a call out of company; §3.2.10 rules 2 and 3 (`promises`) take a sentence's speaker from its voice and a proposal's id from the first line of a supersedes chain. §2–3, the conformance samples and the §4 table are untouched; no profile is new. The demo record has no `speakers`, so the readers compared in §6.1 compare as before.
- ADR 0016's file gains `exclude_people` and `hold_unattributed`; `policy/` gains `speakers.json`; the record folder may hold `voiceprints.age`, which `backup` leaves out.
- `derive transcripts` diarizes when the model is here; `derive speakers` diarizes what was heard before; `setup speakers` fetches and rebuilds; `review speakers` (or `people review --speakers`) and the Library's *Who spoke?* answer; `dream speakers` proposes from the words.
- `docs/people.md`, `docs/day.md`, `docs/serve.md`, `docs/adapters/voice-memos.md`, `docs/backup.md`, `docs/doctor.md` and `SECURITY.md` (the registry, and that it never leaves) say so.

**Does not change**: the envelope, the canonical form and the hash; any line already written; any transcript line, ever, by any attribution; any adapter, none of which binds a voice; the network on any default path, which stays shut; a reader of a record with no `speakers`, which reads as before. A page of one person's own words, the guest's page this RFC makes possible, is a derived excerpt of a transcript and a later RFC's: a shared page (RFC 0025) cut to one voice.

## 13. Open questions

Listed, not solved; each is for the comment period.

1. **Two guests with the same voice score.** Siblings, a parent and a grown child, two colleagues on a bad line: two candidates within a few points of each other, or one cluster that is two people. The review shows both and takes neither (§4.3), and sub-numbers let the owner split a row (§4.1). Is that enough, or should a row whose cluster is wide (its voices far from its centre) always be split by recording, at the cost of more questions? And should the registry keep several centres per person (a voice on the phone and in a room are not the same), which helps here and hurts in the next case?
2. **A guest who later asks to be forgotten.** What the record can do without breaking rule 2: retract every attribution that names them (readers stop naming them, the voices return to *not yet named*, and the owner answers `--unnamed`), add them to `forget` (the registry drops their voiceprint and never proposes them), and add them to `exclude_people` on every entry (their words stay home). What it cannot do is remove their words from the transcript or their voice from the audio, which are the owner's record and are never rewritten. Is a forget migration worth a SPEC change: in the shape of RFC 0029 §10.2's (the chain re-hashed, one `migration/v1` line saying it happened), replacing one voice's words in the transcripts that hold them, and leaving the old head unreproducible by design? Or is a retraction and an exclusion the honest whole of it?
3. **Group calls with more than two channels.** A video call recorder can write one track per participant, often with the participant's address beside it. That is a channel basis far stronger than a voiceprint. Does `channel` take a track name (`track.3`), does a `speakers` entry carry the track's source-native ref (an email, as `participants` does), and does that ref become the observed voice's strongest identifier ahead of the far end of a call? And when a conference arrives mixed on one `system` channel, are its voices diarized inside the channel (`system.1`, `system.2`), as §2.5 says, or left as one?
4. **Speaker labels in the envelope or the payload.** This RFC puts them in the payload, where a transcript's other fields are: additive to a frozen profile, sealed at tier 2–3 with the words, invisible to a reader that does not want them. In the envelope they would be readable without the key (the envelope stays plain, RFC 0029 §2), so a stolen disk would show how many people spoke at every dinner and for how long, and every implementation would need a spec version bump, a regenerated conformance fixture and an ADR for a field most lines never carry. Is there any reader that needs who-spoke without the key, for which the envelope would be worth that?
5. **Inline spans or a file.** The labels and counts are inline, the per-segment spans in a file (§2.2). Inline spans make a line self-contained and a crossing simpler; they also make a two-hour transcript line a hundred kilobytes, sealed, in a month file. Which?
6. **A ref kind on a frozen profile, or a profile of its own.** `speaker` widens `resolution/v1`'s ref kinds and adds four fields that mean something only for it. RFC 0037's open question 1 asks whether the ref kinds should be widened at all or moved to a `resolution/v2`. Is a `speaker/v1` profile (one line per voice, the same fields) cleaner than a resolution whose ref is half the payload's meaning?
7. **The unnamed.** A person is minted per declined voice, with no label (§4.4). That gives the people reader a count and the crossing a person to hold back, and it fills the id space with strangers. With `enrol_unnamed` false, a stranger heard twice is two strangers unless the owner says `--same-as`; with true, the record keeps a voiceprint of someone the owner would not even name. Which default respects them more?
8. **A voice that is no person.** A radio, a television, an announcement on the ferry. The owner can only answer `--unnamed` today, which counts a television as a guest. Is a fourth answer, *not a person*, worth a line of its own (`resolution/v1` cannot say it: every line names a person or an alias), or should the diarizer drop such voices before they get a label, at the risk of dropping a person?
9. **Backfill.** §2.8 supersedes an old transcript with a re-heard one, which re-opens signatures and may change promises. A derived line of its own (`speakers/v1`, `at` the moment of diarization, pointing at the transcript) would leave the day's page and the old words alone, at the cost of a second road to the labels. Which?
10. **Tier 3 for a guest's voice.** Rule 5 says what someone said to you is the highest tier. The file adapter already writes transcripts at 3 for that reason; `transcribe` writes 2. Once diarization knows a recording holds a guest's voice, should the line be written at 3, so that the guest's words are protected as money and health are?
11. **Whose model reads the words.** `dream speakers` sends a transcript's text, other people's words in full, to the model its entry names, which may be anywhere. Should the entry refuse an endpoint that is not on this machine, as `promises --judge` and `describe` never use one?
12. **Calibration.** `match` and `floor` are the model's, and a similarity of 0.75 means different things for different embedding models, languages and microphones. Should the registry learn the owner's own thresholds from their answers (the similarities they accepted and rejected), and is a threshold that moves with the owner's answers still something a second implementation can agree on?
13. **The extra's weight.** pyannote brings torch to every platform, Apple silicon included, where `mlx-whisper` needed none. Is diarization its own extra (`openlogbook[speakers]`), so that a memo can be transcribed without a gigabyte of torch?
14. **Consent and the crossing.** No crossing decides anything from `consent` here (§7). Should an entry be able to say `"consent": "yes"`, so that only transcripts whose every other voice was stated as consenting cross through it? And is `no` a statement the record should accept at all, or a reason for the review to ask whether the recording should be kept?
15. **The default of `hold_unattributed`.** Absent means `false`, today's behaviour, so a nightly consumer like Hermes keeps receiving what it received. Rule 5 argues for `true`: a voice nobody has named is a guest's until the owner says otherwise. Should `init` write `true` into new records' default entries, and should absent mean `true` from some version on?
