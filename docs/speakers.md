# Speakers: who spoke

A recording made in a room has one channel, so until now every word of it read as yours. With the
diarizer on this machine, `derive transcripts` separates the voices of each recording it hears and
gives each voice an anonymous label in the `transcript/v1` line: `S1`, `S2`, … for the voices of a
room, `mic` and `system` for the two sides of a call. Nothing leaves the machine, and nothing names
anyone: a label says *a voice*, never *who*.

This page is build 1 of [RFC 0038](rfcs/0038-speakers.md), its §2: the labels at ingest. Saying whose
voice a label is (one `resolution/v1` line per voice, written by you alone), `review speakers`, the
voiceprints that propose a name, and the text-only road for recordings whose audio is gone are later
builds. No `resolution/v1` line is written here, and no reader binds a label to a person.

```bash
uv tool install "openlogbook[transcribe,speakers]"   # the Whisper engine and the diarizer (or pipx install --force)
logbook setup speakers                          # what is here: the engine, each model, what the record holds; no socket
logbook setup speakers --fetch-model            # the one network event: the models, with HF_TOKEN for those requests only
logbook derive transcripts voice-memos          # transcribes, and separates the voices when the models are here
logbook derive transcripts voice-memos --no-speakers   # transcribes only
logbook derive speakers --dry-run               # the transcripts heard before, and what separating them would change
logbook derive speakers [--since DAY] [--speakers N]   # heard again and separated: a new line supersedes each
```

## What a transcript gains

Two payload fields, both optional, added to `transcript/v1` by a dated amendment of
[RFC 0004](https://github.com/bighydro/logbook/blob/main/rfcs/0004-transcript-v1.md) under RFC 0031 rule 1; the JSON Schema of the payload is
[`schema/transcript-v1.schema.json`](https://github.com/bighydro/logbook/blob/main/schema/transcript-v1.schema.json).
A transcript without them is valid, byte for byte what it was, and every reader reads it as before.

- **`speakers`**: the voices, in order of first speech, each `{ label, seconds?, turns, channel?,
  from_me?, name? }`. `seconds` is how long the voice speaks (each voice's own speech: two voices
  that talk over each other for a minute both count the minute); `turns` is how many segments of the
  text are the voice's (the lines of a plain-text transcript, the elements of Granola's JSON); `channel` is `mic` or `system`; `from_me` is `true` on the microphone's voice
  when the source says the microphone is yours and the voice is alone on it; `name` is a name the
  source displayed, never a resolution.
- **`diarization`**: how the labels were made: `engine` (`pyannote`, or the provider whose labels an
  adapter took, `granola`), `model`, `audio` (the digest of the audio heard), `channels` (1 for a
  room, 2 for a call), `overlap_s` (the seconds in which two voices or more speak at once), and
  `spans`, a reference to the spans file.

The dinner of RFC 0038 §11, three voices in one room:

```json
"speakers":[{"label":"S1","seconds":1862.4,"turns":212},{"label":"S2","seconds":861.0,"turns":97},{"label":"S3","seconds":41.5,"turns":4}],
"diarization":{"engine":"pyannote","model":"pyannote/speaker-diarization-3.1","audio":"c41d…","channels":1,"overlap_s":38.2,
 "spans":{"sha256":"a9e2…","path":"attachments/a9e2…","bytes":21877,"media_type":"application/json"}}
```

## The spans file

One JSON object in the attachment store beside the text, sealed when the record seals (SPEC §1.1),
never inline in the line: `format` `speaker-spans/1`; `content`, the digest of the text it labels, so
it is never read against other text; `segments`, one per line of the text in order, `{from, to,
speaker, overlap?}`, seconds from the line's `at` to two decimals, `speaker` the voice that speaks
most of the line (of its words, when the engine gave word times), `null` when nobody did, `overlap`
the other voices that speak a second or more of it; and `turns`, the diarizer's own `{from, to,
speaker}`, overlapping where the voices did. The labels and their counts are in the line, because
every reader that asks *who was in this recording* needs them; the spans grow with the recording and
are in a file, because only the readers that split the words need them.

Its bytes are written one way (sorted keys, no spaces), so the same voices in the same text are the
same file and the same digest.

## Labels

A label is the diarizer's, not a person's, and it means something only inside its line: `S2` of one
recording and `S2` of another are unrelated.

- `S1`, `S2`, … for the voices of one channel, numbered by first speech (the pipeline's own
  `SPEAKER_00` says nothing about order);
- `mic` and `system` for a channel in which one voice speaks; `mic.1`, `mic.2`, … or `system.1`,
  `system.2`, … when several do;
- a label never holds `#` or a line break, and is at most 64 characters, so a later `speaker` ref
  (`<line id>#<label>`) splits at its first `#`.

## Two channels

A call recorder keeps your microphone on one channel and the far end on the other. Such a recording is
diarized a channel at a time: a channel with one voice is labelled by the channel, and the
microphone's voice carries `from_me: true`; a channel with several voices (a speakerphone in the room,
a conference at the far end) is numbered, and none of them carries `from_me`.

A recording counts as two channels only when its source says so. A `voice-memo/v1` line says it under
`extra.channels`, the file's channels in order, `mic` and `system` once each: `["mic", "system"]`, or
`["system", "mic"]` when the far end is the first channel. No adapter writes that yet; a call
recorder's will. Anything else is one room, an iPhone's stereo memo included: two microphones in one
room are not a call, and no voice of it is `from_me`. A file that does not hold the channels its source
named, or whose channels the diarizer cannot decode apart, is heard as a room too, and the run says so.

**Granola** keeps the two sides apart itself and marks each segment as the microphone's (`me`) or the
system audio's (`them`). `sync granola` takes those marks as the labels: `mic` and `system` (`system.1`,
`system.2` where Granola's own diarization tells the far end's voices apart), `from_me` on `mic`, the
name Granola displayed as `name`, `engine` `granola` and no `audio`, since Granola kept it. With every
segment timed it counts the seconds and writes the spans file, each segment the voice Granola gave it.

## When the audio is gone

A memo imported without `--attachments`, a copy of the record missing a file, a provider that never
handed over audio: nothing is diarized at ingest, `derive transcripts` skips such a memo as it always
did, and nothing breaks. A provider's own marks, when it gives them, are still taken by its adapter.

## Without the extra, or without the models

When the diarizer (the `openlogbook[speakers]` extra) or one of its models is not on this machine,
`derive transcripts` transcribes exactly as before, writes no `speakers`, and says once at the end
which is missing. `openlogbook[transcribe]` alone, the diarizer not installed:

```
speakers: not separated (install openlogbook[speakers], then logbook setup speakers --fetch-model)
```

The extra installed and a model not fetched:

```
speakers: not separated (logbook setup speakers --fetch-model)
```

Without the extra, `setup speakers` and `derive speakers` exit 2 with the first sentence, and
`setup speakers --fetch-model` fetches nothing: the hub client comes with `openlogbook[transcribe]`
too, and models nothing here could run are never downloaded. `derive speakers --dry-run` hears
nothing and needs no extra. `--no-speakers` turns separation off for a run and says nothing of it.

## Heard again: `derive speakers`

A transcript heard before the voices were separated has no times in its text, so the labels cannot be
added to it: the recording is heard again. `derive speakers` takes each standing transcript with no
`speakers` whose recording (the voice memo its `provenance.source` names, not retracted) has its audio
in the store, hears it again with the Whisper model that heard it, separates the voices, and writes a
new `transcript/v1` line with the new text and the labels. That line `supersedes` the old one and
keeps its `source`, `at`, `end`, `tz` and title; its `raw_id` is `<the old raw_id>#speakers@<the first
12 hex of the spans file's digest>`, so the same voices heard in the same text write nothing twice.
The old line stays in the record, superseded, as every correction does. `--speakers N` tells the
diarizer the room held N voices (a call heard a channel at a time does without it, and the command
says so). A transcript from a provider or a file has no recording here and is left alone, counted;
so is one whose memo was retracted or superseded by a later memo line. One recording has one line of
its voices: a recording a standing line has separated already is not heard again.

It is not free, and the command says so before it writes:

- a new line on a signed day changes the day's page, so the signature reads `page_matches` false
  until you sign the day again (`logbook day sign DAY`);
- a promise closed on an old line is proposed again from the new line, a promise's id being its
  line's (SPEC §3.2.10 rule 2): each is listed, by the seq of the task that closed it and its
  sentence, and `promises done ID` closes it again;
- a call's synthesis belongs to the line it was written about: the new line has none until
  `transcript synthesize` writes one.

`--dry-run` lists the transcripts and those costs, writes nothing and needs no engine. A transcript
that a line retracted later no longer supersedes stands again, and hearing it again into the same
spans writes nothing.

## The models, and the one download

The diarizer is [pyannote.audio](https://github.com/pyannote/pyannote-audio)'s pipeline
`pyannote/speaker-diarization-3.1`, its own extra, `openlogbook[speakers]`, which brings torch to every
platform (and CUDA's libraries on Linux). `openlogbook[transcribe]` does not bring it, so a memo is
transcribed without a gigabyte of torch; a machine that separates voices installs both,
`openlogbook[transcribe,speakers]`. It runs on the CPU and on Apple silicon behind either Whisper
engine. The pipeline
reads two more models, `pyannote/segmentation-3.0` and the embedding model
`pyannote/wespeaker-voxceleb-resnet34-LM`; all three are gated on Hugging Face. Accept the conditions
on each model's page while signed in, make a read token, and:

```bash
HF_TOKEN=hf_… logbook setup speakers --fetch-model
```

That is the one network event, and the only command that fetches a speaker model. The token is read
from `HF_TOKEN` for those requests and nothing else: never written, never printed. When the hub
refuses, the command names the page to accept the conditions on. `derive transcripts --fetch-model`
fetches the Whisper model and only that.

Every run that separates voices does it with the hub offline (`HF_HUB_OFFLINE`, and the switch the hub
client read when it was first imported, set for the run and put back after) and with pyannote.audio's
own usage reporting, which its 4.x releases switch on by default, switched off
(`PYANNOTE_METRICS_ENABLED=0`). The audio is decoded on this machine and never leaves it. The same guard
now serves every command that runs a local model (`transcribe.offline`, which `promises --judge` and
`describe` use, set the variables only, which the hub client ignores once imported). A cache the hub
says holds the models but whose files are not whole (an interrupted fetch) stops the run with one
sentence naming `setup speakers --fetch-model`. A test separates voices with every socket refused; no
test loads a model: the diarizer is a fake, as the transcription engine is.

## Reading them back

`show`, the Day and `serve`'s Day name a transcript's voices after its title (and `show` drops a
writer's `0 turns` beside them, and marks a transcript heard again `superseded by #N`):

```
  09:15  transcript transcription  Samtale · you 3 min · Ola Nordmann 3 min
```

A voice reads as the name its source displayed, else its label; the owner reads as `you` only from
`from_me`, the source's statement, never from a guess. `day --json` gives a transcript's entry
`speakers`, only when the line has voices: `{label, person, name, seconds, basis, consent, owner}`,
`person`, `basis` and `consent` null until a later build lets you say whose a voice is (`basis`
`channel` for the `from_me` voice). A transcript that another standing transcript of the day
supersedes is not listed beside it. A transcript without `speakers` reads exactly as before.

## Four assumptions that stand

RFC 0038 leaves fifteen questions open for its comment period. Four of them were asked of it from the
start, and this build stands on the RFC's present answer to each until the comment period settles it:

1. **Two guests with the same voice score.** A label is a voice as the diarizer heard it, not a person:
   two people it could not tell apart are one label, and two labels may be one person. This build
   names nobody, so nothing is merged or split here; the review (a later build) shows two close
   candidates and takes neither, and a later diarization with `--speakers N` may split a label.
2. **A guest who asks to be forgotten.** The transcript and the audio are your record and are never
   rewritten. What a later build can do is retract the lines that name them and keep their words
   home; this build writes nothing that names anyone, so there is nothing of theirs to retract.
3. **Group calls with more than two channels.** A recording is one room, or two channels, `mic` and
   `system`. A conference that arrives mixed on the far end's channel is diarized inside it
   (`system.1`, `system.2`); a recorder that writes one track per participant is not read as such yet.
4. **Labels in the payload, not the envelope.** The labels are payload fields, sealed with the words at
   tier 2 and 3, invisible to a reader that does not want them: no spec version bump, no regenerated
   conformance fixture, no new ADR. A stolen disk shows nothing of who spoke.

## Not in this build

- naming a voice, `review speakers`, voiceprints, the text-only road and the crossing's keys (RFC 0038
  §3–§9);
- the `channels` engine of §2.5 (two channels labelled with no model on the machine): §2.1 has the run
  transcribe exactly as before without the model, and this build follows §2.1;
- SPEC §3.2.10 rule 2's change that RFC 0038 asks for (a promise's id from the first line of a
  supersedes chain): the SPEC is unchanged, which is why `derive speakers` says what it reopens.
