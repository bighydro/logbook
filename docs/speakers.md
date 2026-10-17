# Speakers: who spoke

A recording made in a room has one channel, so until now every word of it read as yours. With the
diarizer on this machine, `derive transcripts` separates the voices of each recording it hears and
gives each voice an anonymous label in the `transcript/v1` line: `S1`, `S2`, … for the voices of a
room, `mic` and `system` for the two sides of a call. Nothing leaves the machine, and nothing names
anyone: a label says *a voice*, never *who*.

This page covers builds 1 to 3 of [RFC 0038](rfcs/0038-speakers.md): the labels at ingest (§2);
saying whose voice a label is, one `resolution/v1` line per voice, written by you alone through `review
speakers`, which the readers then join ([Who they are](#who-they-are), §3–§4); and the voiceprints that
let the review propose a name by how a voice sounds, a sealed cache that never leaves the machine
([Voiceprints](#voiceprints), §5). The browser's *Who spoke?* and the text-only road for recordings
whose audio is gone are later builds.

```bash
uv tool install "openlogbook[transcribe,speakers]"   # the Whisper engine and the diarizer (or pipx install --force)
logbook setup speakers                          # what is here: the engine, each model, what the record holds; no socket
logbook setup speakers --fetch-model            # the one network event: the models, with HF_TOKEN for those requests only
logbook derive transcripts voice-memos          # transcribes, and separates the voices when the models are here
logbook derive transcripts voice-memos --no-speakers   # transcribes only
logbook derive speakers --dry-run               # the transcripts heard before, and what separating them would change
logbook derive speakers [--since DAY] [--speakers N]   # heard again and separated: a new line supersedes each
logbook setup speakers --rebuild                # the voiceprint registry made again from the record; no socket
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

A voice not yet named reads as the name its source displayed, else its label; the owner reads as `you`
from `from_me`, the source's statement, or from your own answer, never from a guess. `day --json` gives
a transcript's entry `speakers`, only when the line has voices: `{label, person, name, seconds, basis,
consent, owner}` (what each holds once a voice is named: [Who they are](#who-they-are)). A transcript
that another standing transcript of the day supersedes is not listed beside it. A transcript without
`speakers` reads exactly as before.

## Who they are

A label says *a voice*. Who that voice is, is yours to say, and nothing says it for you: no adapter,
no model, no `dream` and no tool binds a voice. Each answer is one `resolution/v1` line beside the
transcript (RFC 0006, amended for RFC 0038 §3), and the transcript itself never changes.

```bash
logbook review speakers                          # the queue: voices not yet named, numbered, with the evidence
logbook review speakers --json                   # the same, with each row's stable id and the counts
logbook review speakers --accept 4 --name 1 me   # row 4 is whom it proposes; row 1 is you
logbook review speakers --name 2 "Kari Nordmann" --consent 2=yes
logbook review speakers --name 3 "Per Hansen"    # a name nobody has: a person is minted under it
logbook review speakers --unnamed 3              # a person, not you, whom you will not name
logbook review speakers --unnamed 5 --same-as 3  # the same unnamed person as voice 3
logbook review speakers --reject 4               # not that person; never proposed again
logbook review speakers --all-above 40           # every row whose one best candidate scores 40 or more
logbook review speakers --play 2                 # the voice's first twenty seconds alone, here; nothing written
logbook review speakers --named --recording ID   # the voices of a recording already named, to correct one
logbook review speakers --named --day 2026-10-03
```

### The queue

A row is an *observed voice*, keyed by the strongest thing the voice carries, never by its label
across recordings: the far end of a call (the one voice on the `system` channel of a recording that
overlaps a `call/v1` line whose counterparty is an address or a number) is keyed by that address or
number, so every call with one number is one row; else the voice itself: voices not yet named that
sound alike, each within `match` of the others' centre in the [voiceprints](#voiceprints), are one row,
so the same guest heard at four dinners is one row of four recordings (never two voices of one
recording: two labels the diarizer kept apart are not merged by a guess); else the name the source
displayed, its words folded and sorted; else the label alone, one row per voice. A row with several
recordings numbers them `N.1`, `N.2`, …, and `--accept 4.2` answers that recording's voice alone,
which is how a row that joined two people is split. Your own microphone's voice (`from_me`) is yours
without a question and never in the queue; a row the voiceprints propose you for comes first, since
one answer settles most voices.

```
4 voices not yet named in 2 recordings, 4 rows · 0 named · tier 2
   1  [20]  Sat 2026-10-03 19:40 · Home · "Middag" · S1 · 31 min · "Har du sett hvor høyt vannet står?"
            → Kari Nordmann: on the entry "Middag med Kari" · seen that day (message 18:02) (as good for S2, S3 of the recording: not taken by --all-above)
            that day: Kari Nordmann (message, calendar)
   2  [20]  same recording · S2 · 14 min · "Beklager, ferja var sen."
            → Kari Nordmann: on the entry "Middag med Kari" · seen that day (message 18:02) (as good for S1, S3 of the recording: not taken by --all-above)
            that day: Kari Nordmann (message, calendar)
   3  [20]  same recording · S3 · 42 s · "Hei, jeg skal bare levere en pakke."
            → Kari Nordmann: on the entry "Middag med Kari" · seen that day (message 18:02) (as good for S1, S2 of the recording: not taken by --all-above)
            that day: Kari Nordmann (message, calendar)
   4  [40]  Tue 2026-10-06 09:15 · Home · "Samtale" · system · 3 min · "I'll call the yard tomorrow."
            → Ola Nordmann: the far end of the call 09:15
            that day: Ola Nordmann (call)
nothing written: `review speakers --accept N[,N]`, `--name N "…"`, `--unnamed N`, `--reject N[,N]`, `--consent N=yes|no|unknown`, or `--all-above SCORE`
```

Each row says the day, the place (the stay the recording overlaps, as `people` names it), the
recording's title, the voice's label and how long it spoke, its first words, the candidate and what
speaks for it, and who else the record saw that day. The rows run in the order the recordings were
made, and within a recording by how long each voice spoke. On a terminal the command asks row by row: `y` accepts, `n` rejects, `u` is unnamed, `p`
plays, anything else is a name, Enter skips, `q` stops; after a name or `unnamed` for a voice that is
not yours it asks `recorded with their consent? y / n / Enter for unknown`. Each answer is written at
once.

### The score

A plain sum per candidate and voice, a row's the lowest of its voices':

| Evidence | Points |
|---|---|
| the same voice: the voice's embedding against the person's voiceprint, 70 at a similarity of `match` or more, falling in a straight line to 0 at `floor`, nothing below it; against yours as against anyone's | up to 70 |
| the far end of a call: the voice is alone on `system` and the recording overlaps a call whose counterparty is the person | 40 |
| on the entry: the person attends a timed calendar entry the recording overlaps, held at the same stay | 15 |
| a participant: the transcript's `participants` name the person by address, number or provider id; by a name alone | 15; 5 |
| the source's name: the name the source displayed for the voice is the person's, or a word of it nobody else's has | 10 |
| seen that day: another line of the recording's day is the person's (a message, a call, a tagged face, their voice in another recording), one not already counted above | 5 |

Context never stands in for a voice: with neither the same voice nor the far end of a call a candidate
scores 40 at most, so `--all-above` over 40 never names a guest from context alone. The first time a
guest is recorded there is no voiceprint of them: context proposes, low, and your answer is what makes
the voiceprint. Two candidates within 5 points are both
shown and neither is taken; context belongs to the recording, not to one voice of it, so a person who
is the best for two voices of one recording at the same score is shown for each and taken by
`--all-above` for neither. A person already named for one voice of a recording, you included, is not
proposed for its others. A pair you said no to, and a person under `forget` in `policy/speakers.json`,
are never proposed. You are proposed by your voice alone (`→ you: same voice 0.86`); until you have a
call on record or have answered once for yourself there is no voiceprint of you, and you answer `me`.
With `enrol_unnamed`, a voice that sounds like a person you would not name is proposed as `the same
unnamed person`, and accepting it writes `--unnamed` for that person, not a new one. `matched` says
`same voice 0.86`, the similarity, never the vectors; a row of several recordings reads as its least
similar voice, as it scores.

### What each answer writes

Every number of one command is checked before the first line is written; a number the queue does not
have, a voice answered twice (`--accept 2 --reject 2`, or `2` and `2.1`), a consent for a row the
command does not answer, a consent for your own voice, a score that is not a whole number, or a name
several people have exits 2 and writes nothing.

| Answer | Writes, per voice of the row |
|---|---|
| `--accept N` | one `resolution/v1`: `ref` `{kind: speaker, value: "<transcript id>#<label>"}`, `entity` the candidate, `label` the person's, `method` `owner`, `basis`, `consent` when stated, `evidence` the transcript and the lines the score rested on, `logbook_head`, and under `extra` the row's id, the score and what matched |
| `--name N "…"` | the same, to `me` (your `owner_id`, no `label`, no consent), the one person the record labels so (case aside), a person by id or by a ref the record resolves (`email:…`, `phone:…`); a name nobody has mints a person with that label, once per name in a command |
| `--unnamed N` | the same, `entity` a person minted with no `label`, and `unnamed: true`; one person for the row; with `--same-as M`, the person voice M is bound to unnamed (or the one minted for M in the same command) |
| `--reject N` | one `entity-review/v1` line of type person (RFC 0035 amendment 1: `people-review/v1` is read and no longer written): `ref` the row's first voice, `refs` every voice, `entity` the candidate |
| `--consent N=…` | nothing of its own: the `consent` of the line N's answer writes (`yes`, `no` or `unknown`; absent reads as `unknown`) |

`basis` is `channel` when the person is the far end of the call the recording overlaps, `voice` when
the recording's audio is in the store, and `text` otherwise, which then carries `confidence`: the
score the record gives that person for that voice, over 100 and at most `text_confidence_cap` (0.6)
of `policy/speakers.json`, whichever flag named them; a person the record scored nothing for (a name
only you knew, `--unnamed`, `me`) the cap itself, your word being the most a voice named without its
audio may say. So a voice named without its audio never reads as surer than one heard.
A line is tier 2, or the transcript's when that is higher. The same person, basis and consent as the
voice's standing line (a consent left out reading as `unknown`), a no the record already holds, and
`--unnamed` on a voice already unnamed write nothing and say so; an answer that names the same
person again keeps the consent stated before unless it states another. Two labels may be one person
(a voice the diarizer split): naming one person for a second voice of a recording is allowed, and
said (`Kari Nordmann is also S2 of the recording`); the queue does not propose a person for a
recording's other voices once one is theirs. A ref given to `--name`
(`email:…`, `phone:…`) that no person of the record has is refused, never minted as a name.

The line RFC 0038 §11 writes for the call's far end:

```json
{"schema":"resolution/v1","ref":{"kind":"speaker","value":"019cadd3-6bc0-7dcd-9133-0000000004a2#system"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-043f5aabf2a9","registry":"logbook"},"label":"Ola Nordmann",
 "method":"owner","basis":"channel","evidence":["019cadd3-6bc0-7dcd-9133-0000000004a2","019cadd3-6bc0-7dcd-9133-0000000004e3"],
 "logbook_head":"8f1c…","extra":{"proposal":"3c9a51d0e2f4b7a6","score":40,"matched":["the far end of the call 09:15"]}}
```

Its JSON Schema is [`schema/resolution-v1-speaker.schema.json`](https://github.com/bighydro/logbook/blob/main/schema/resolution-v1-speaker.schema.json).

### A wrong answer

The record keeps the mistake and the correction. `--named --recording ID` (its id or seq) or `--named
--day DAY` lists the voices already named, numbered as the queue is, each with its standing line; any
answer to one (`--name`, `--unnamed`, or `--accept N --consent N=…` to state the consent again) writes
a new line for the same voice that `supersedes` the standing one, and the wrong line stays in the
record. A wrong no is undone by retracting its line, and the pair is proposed again; a wrong yes by
`logbook repair retract SEQ`, which returns the voice to the queue. A transcript heard again (`derive
speakers`) is a new line with new labels: its voices are new refs, back in the queue, and the old
line's answers name nothing on it. `people merge` moves a person's addresses and numbers, never a
voice: a voice bound to the person merged away stays bound to them, and so they stay a row of
`people`, until you name it again here; the merge says how many (`1 voice stays bound to Kari`).

### How the readers read it

Each voice of a standing transcript is then yours (bound to you, or `from_me` with no line; a line
binding your microphone's voice to someone else wins over `from_me`: someone else spoke into your
phone), a person's, unnamed, or not yet named.

- **The Day** names who spoke and says the consent you stated for the guests, when it is not `yes`:
  `Middag · you 31 min · Kari Nordmann 14 min · 1 unnamed · recorded with consent: unknown`. In `day
  --json` each voice is `{label, person, name, seconds, basis, consent, owner}`: `person` your id for
  your voice and the person's for theirs, null for an unnamed voice and one not yet named; `name` the
  person's label (for a voice not yet named, the name its source displayed); `consent` as stated,
  `unknown` when a guest's line states none.
- **With** (who was there): a voice bound to a person, in a recording that overlaps the stay, is
  confirmed company, `spoke in Middag`, ahead of the participants, at the line's `confidence` (a `text`
  attribution's 0.2 reads as 0.2), else 1.0, your own assertion. The far end of a call (the `system`
  channel) spoke and was not there: never company, not even through that recording's participants. An
  unnamed voice is counted, `with.unnamed`, and never named; a voice not yet named is nobody's company.
- **People** count a voice bound to someone on their `transcripts` channel, the far end of a call
  included, with `spoke_s`, the seconds; the person page says `spoke 14 min`. A person you would not
  name is never a row: the head says `and 1 unnamed`, the JSON `unnamed`, and how many voices are not
  yet named, `review speakers`. `rollup people` counts a year's unnamed the same way.
- **Promises** take a sentence's speaker from the voice of its segment, through the spans file: your
  voice's sentences are yours, a guest's are owed to you, a voice not yet named stays as spoken (`S2`).
- **The digest** says who spoke that day and, once, how many voices wait, with the command.

## Voiceprints

A voiceprint is an embedding of a voice: a short list of numbers the speaker model computes from the
audio, close to the numbers of the same voice in any other recording. That makes it biometric: it
recognises a person by their body, in a recording anyone could make, and it could recognise a guest
who never agreed to be in your record to someone who has never seen it. Everything below follows
from that (RFC 0038 §5).

### The registry

The voiceprints are one file, `voiceprints.age`, in the record folder beside `places.json`: one JSON
document, `voiceprints/1`, sealed with age to the record's own recipients ([Encryption at
rest](https://github.com/bighydro/logbook/blob/main/rfcs/0029-encryption-at-rest.md)), written whole each time to a temporary name beside it and renamed
over it, so a crash leaves the old file or the new one and never half; the plaintext never touches the
disk. It holds the embedding model and the digest of its files, the length of its vectors and the
head it was written at; per person (by entity id, never a name) their voiceprint, the centre of their
voices' embeddings weighted by clean seconds, the clean seconds it rests on, and the voices it was
built from, each with its own embedding, so a voiceprint can be recomputed at any write without the
model; and each voice not yet named with its embedding, so the review compares without loading the
model. No audio, no words, no names.

A voice is embedded from its **clean speech** only: its turns in the spans file less every moment
another voice speaks, each piece two seconds or more, so an evening of interruptions does not blur
two people into one. A voice with less than `min_clean_s` of it (8 seconds) is neither embedded nor
proposed by voice. The model is the diarization pipeline's own,
`pyannote/wespeaker-voxceleb-resnet34-LM`, so the registry and the diarizer agree on what a voice is.

A record that names no recipients keeps no registry on disk. The review then hears the voices it
compares for that run, from the audio, when the `speakers` extra and its models are on this machine,
and forgets them when it ends; without them it proposes from context and the channels alone. That
costs a decoding of every recording with voices at each `review speakers`; a record sealed to
recipients pays it once, in the file.

### A cache, never the record

The registry is made from what the record holds, the audio the transcripts' `diarization.audio`
names, their spans files and the attributions that stand, and is thrown away without loss, like
`index.sqlite`:

```bash
logbook setup speakers                  # registry   voiceprints.age written 2026-10-11 10:12 with pyannote/wespeaker-voxceleb-resnet34-LM, for 3 people, you among them; 2 voices not yet named
logbook setup speakers --rebuild        # made again from the record, with the model; no socket
```

- A `derive transcripts` or `derive speakers` that separates a recording adds its voices, and hears
  any other voice the file should hold and does not; the run says `voiceprints: 4 voices heard; 3
  people, you among them, 2 voices not yet named`. A run with nothing new to hear does not load the
  model and leaves the file as it is.
- Every answer in `review speakers` that writes a line updates it, without the model: the person you
  named gains the voice; a voice named away, retracted or whose transcript was heard again leaves the
  voiceprint it was in, because each voiceprint is recomputed from the answers that stand. The queue
  itself reads the file as the record stands now, so a retracted answer counts for nothing at once.
- A model change makes it again from the record: two models' vectors cannot be compared.
- A recording whose audio is not in the store is skipped and counted; the answers already written
  stand.
- `verify` ignores the file; `backup` leaves it out, one copy of a biometric being the most there
  should be. A restored record makes it again: `setup speakers --rebuild`, from the audio the backup
  carries.
- `logbook key add-recipient` and `key remove-recipient` seal it again to the new recipients with
  the record's lines and files, in the same hold of the writer lock: before the record when a
  recipient goes, so a removed identity opens no copy of it even when the change stops half way,
  and after it when one comes. A file this machine cannot open or seal again is removed, to be made
  again, and so is one whose sealing again was interrupted; a link under its name is removed, never
  read through, and what it pointed at is left as it was, said. One that can be neither sealed again
  nor removed (another program holds it open) stops a removal before the record is touched.

A voice the file let go (one you answered `--unnamed`, or a person under `forget`) and that later
returns to being kept (the answer retracted, `forget` emptied) is heard again by the next `derive`
that separates a recording, or by `setup speakers --rebuild`; until then it is compared as a voice
without a voiceprint.

### Your voice

Your voice is enrolled without a question and without a line: every voice with `from_me` (your own
microphone on a call recorder, alone on its channel) whose audio is in the store, and every voice you
have bound to yourself (`--name N me`, or accepting a row that proposed you), is folded into your
voiceprint. Every other voiceprint begins with your first answer for that person and grows with each
later one.

### `policy/speakers.json`

One setting, read each run, never a line, backed up with `policy/`. Without the file, the defaults:

```json
{"match": 0.75, "floor": 0.5, "min_clean_s": 8, "text_confidence_cap": 0.6, "enrol_unnamed": false, "forget": []}
```

- `match` and `floor`: the similarities at which a voice scores its full 70 points and none. They are
  the embedding model's, hypotheses until calibrated, as `policy/stays.json`'s constants are.
- `min_clean_s`: the clean speech, in seconds, below which a voice is neither embedded nor proposed by
  voice.
- `text_confidence_cap`: the most a `text` attribution's `confidence` may say.
- `enrol_unnamed`, `false`: the voices of a person you would not name are folded into no voiceprint,
  so a stranger you would not name is not recognised next time either. With `true` they are, and the
  queue proposes `the same unnamed person`.
- `forget`: entity ids (as `people --json` gives them) whose voiceprint is never kept and against whom
  no voice is ever proposed. Their voices leave the file at its next write. An entry that is no
  one's id (a typo, a name, an id in capitals) matches no one and forgets no one.

A file that is not this shape is refused in one sentence naming the key, and nothing is written: a
number outside 0 to 1, `floor` not below `match`, seconds below 0, an `enrol_unnamed` that is not
`true` or `false`, a `forget` that is not a list of non-empty strings, a key that is no setting.

### It never leaves

The registry is part of no crossing, whatever the tier and whatever a policy entry says: not the
crossing package, a shared page, a trip bundle, the vault, the site, an MCP tool's answer, a dream's
material, a backup or any export. A tier says what a line may give away, and the registry is not a
line. Nothing opens it but `review speakers`, the commands that write it (`derive transcripts`, `derive
speakers`, `setup speakers --rebuild`), `setup speakers` and `doctor`, which say that it is there, when
and with which model it was written and for how many people, never what is in it ([the
doctor](doctor.md#voiceprints)). The index holds no embedding, and no reader prints a vector: the
review says `same voice 0.86`, a similarity. A test builds every crossing and export over a record
with a registry and looks in each for the file and for every one of its vectors, as text and as
packed numbers.

## Assumptions that stand

RFC 0038 leaves fifteen questions open for its comment period. Four of them were asked of it from the
start, and this build stands on the RFC's present answer to each until the comment period settles it:

1. **Two guests with the same voice score.** A label is a voice as the diarizer heard it, not a person:
   two people it could not tell apart are one label, and two labels may be one person. The review
   shows two close candidates and takes neither, a row's `N.2` answers one recording alone, and a
   later diarization with `--speakers N` may split a label; a label two people share is left not yet
   named, or named `--unnamed`.
2. **A guest who asks to be forgotten.** The transcript and the audio are your record and are never
   rewritten. What the record can do is retract the attribution lines that name them (their voices
   return to *not yet named*) and list them under `forget` in `policy/speakers.json`, so the
   registry drops their voiceprint at its next write and no voice is ever proposed as theirs; keeping
   their words home is the crossing's keys, a later build.
3. **Group calls with more than two channels.** A recording is one room, or two channels, `mic` and
   `system`. A conference that arrives mixed on the far end's channel is diarized inside it
   (`system.1`, `system.2`); a recorder that writes one track per participant is not read as such yet.
4. **Labels in the payload, not the envelope.** The labels are payload fields, sealed with the words at
   tier 2 and 3, invisible to a reader that does not want them: no spec version bump, no regenerated
   conformance fixture, no new ADR. A stolen disk shows nothing of who spoke.

Build 3 stands on two more:

- **The unnamed** (open question 7). `enrol_unnamed` is `false` by default: a person you would not
  name is minted for the voice and kept in no voiceprint, so a stranger heard twice is two strangers
  unless you say `--same-as`.
- **Calibration** (open question 12). `match` and `floor` are fixed settings, 0.75 and 0.5 by
  default; the registry does not learn your thresholds from your answers.

## Not in these builds

- the browser's *Who spoke?* (§4.6), the text-only road (§6), and the crossing's keys (§9);
- the `channels` engine of §2.5 (two channels labelled with no model on the machine): §2.1 has the run
  transcribe exactly as before without the model, and this build follows §2.1;
- SPEC §3.2.10 rule 2's change that RFC 0038 asks for (a promise's id from the first line of a
  supersedes chain): the SPEC is unchanged, which is why `derive speakers` says what it reopens;
- the SPEC's own words for the readers RFC 0038 §12 changes (§3.2.5 rule 2, voices by attribution
  and the far end of a call out of company; §3.2.10 rule 3, a sentence's speaker from its voice): the
  readers do it, as [Who they are](#who-they-are) says, and the SPEC text follows when the RFC is
  adopted; the demo record has no voices, so every reader compared under §6.1 compares as before;
- `people review --speakers`, the RFC's stand-in until `review` existed: `review speakers` is it.
