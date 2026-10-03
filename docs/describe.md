# Describing keepers

`logbook describe keepers [--since YYYY-MM-DD] [--limit N] [--photos DIR ...] [--model NAME] [--fetch-model]
[--dry-run] [--json]` has a local vision model look at each photo you marked a keeper (RFC 0024) and write
down what is in it: one factual sentence and a short list of the visible things. The words go into the
record as a derived note (RFC 0010), on the photo's day, beside the keeper. A photo is described once,
however many lanes it is in and however often the command runs. No model runs unless you ask, never a
cloud one, and nothing leaves the machine: the engine is `mlx-vlm` on Apple silicon, an optional extra,
with the Hugging Face hub told it is offline while it runs. The model is never told who is in the picture
or where it was taken, is told not to guess either, and an answer that names a face your library knows is
refused.

```bash
logbook describe keepers                                      # every keeper whose photo file is reachable, oldest first
logbook describe keepers --since 2026-06-01 --limit 20        # twenty this run; the next run carries on
logbook describe keepers --photos ~/Pictures/Photos\ Library.photoslibrary   # where the originals are
logbook describe keepers --photos ~/Pictures/Photos\ Library.photoslibrary --photos /Volumes/Archive/2026
logbook describe keepers --dry-run                            # what would be described; no engine needed, nothing written
logbook describe keepers --fetch-model                        # download the model first; the only time the command uses the network
logbook describe keepers --model mlx-community/Qwen2-VL-7B-Instruct-4bit   # a larger model
logbook show 2026-06-10                                       # the description under its keeper
```

Without the engine, or with a model not yet on this machine, the command prints the two lines that put
them there and exits 2:

```
describe: no vision engine is installed; install openlogbook[describe] (mlx-vlm, Apple silicon only)
  install:  pip install "openlogbook[describe]"      # or: uv tool install "openlogbook[describe]"; Apple silicon only
  fetch:    logbook describe keepers --fetch-model   # downloads mlx-community/Qwen2-VL-2B-Instruct-4bit once; the only network use
```

## What is written

One `note/v1` line per photo, `source` `description`, tier 2 (a note is tier 2, RFC 0010), `at` and `tz`
the photo line's, so the note sits on the photo's day at the photo's time:

```json
{"at":"2026-06-10T17:00:00Z","end":null,"tz":"Europe/Oslo","source":"description","kind":"note","tier":2,
 "payload":{"schema":"note/v1","raw_id":"01a0f6a2-068b-7572-94ea-f492e749c3d6",
  "text":"A wooden sailing boat moored at a stone quay under a grey sky.\nVisible: boat, quay, ropes, sky",
  "extra":{"derived":true,"engine":"mlx-vlm","model":"mlx-community/Qwen2-VL-2B-Instruct-4bit",
   "photo":{"line":"01a0f6a2-068b-7572-94ea-f492e749c3d6","asset_id":"9B4E2C10-5F3A-4D21-8A7B-000000000001","library":"apple-photos","file_name":"IMG_1700.HEIC"},
   "keeper":"01a0f6a2-1b2c-7d3e-9f40-5a6b7c8d9e0f","things":["boat","quay","ropes","sky"]}}}
```

- `raw_id` is the photo line's id: the `(source, raw_id)` dedupe of the store means a photo is described
  once, whatever model is set later and however many keepers point at it (a photo in both lanes has one
  description). A description you retract is never written again, as a retracted keeper is not.
- `text` is the sentence, then `Visible: …` on a second line, so `logbook search boat` finds the photo.
- `extra.derived` says the words are a model's, never yours; `extra.engine` and `extra.model` say which;
  `extra.photo` is the photo as the keeper names it (`{line, asset_id, library, file_name?}`);
  `extra.keeper` the keeper line the run read; `extra.things` the list, cleaned.
- The chain is appended to, one line per photo as soon as it is described, so an interrupted run keeps
  what it did. Nothing is ever rewritten.

`show <day>` prints the description under the first keeper row for its photo, indented to the text column
and without a clock of its own; when no keeper for the photo is standing on the day (you retracted it), the
note is a row of its own, `note  description  IMG_1700.HEIC: A wooden sailing boat …`.

```
2026-06-10
  hero  IMG_1700.HEIC, IMG_1030.HEIC
  10:30  photo      immich         camera=SimPhone 3, file_name=IMG_1030.HEIC, …
  10:30  keeper     keeper-inference hero photo (memory): IMG_1030.HEIC
                                   A table set for two with bread and coffee by a window. · table, bread, coffee, window
  17:00  keeper     keeper-inference hero photo (memory): IMG_1700.HEIC
                                   A wooden sailing boat moored at a stone quay under a grey sky. · boat, quay, ropes, sky
  17:00  keeper     keeper-inference hero photo (art): IMG_1700.HEIC
```

## What the model is asked, and what it may not say

The prompt is fixed (`describe.PROMPT`) and the model sees nothing but the pixels and that prompt: no file
name, no date, no location, no face, no caption. It is asked for one JSON object, `{"description": one
factual sentence, "things": [short lowercase noun phrases]}`, and told two things it must never do:

- **Never name or identify a person.** Faces are the photo library's job: the names it gave them are on
  the photo line (`extra.faces`) and `keepers --people` reads them, proposed and never confirmed. The model
  writes "a person", "two people", "a child". An answer that carries any word of a face's name the library
  put on that photo is refused: counted (`N answers could not be read`), never written, tried again on the
  next run.
- **Never guess where the picture was taken.** No place, city, country, landmark, shop or brand. Where you
  were is what the location lines say; a model's guess from a skyline is not an observation and has no
  place in the record.

The answer is read as the first JSON object in it, fences and prose aside. The sentence has its whitespace
collapsed; the things are lowercased, trimmed, deduplicated, anything over four words dropped, at most
twelve kept; a `things` that came back as one comma-separated string is split. An answer with no sentence
is no description.

## Where the file is

A photo line points at pixels it does not hold (RFC 0002). The command looks in two places, in this order:

1. **The record's own store.** A `media`, `attachments`, `file` or `content` reference of the §1.1 shape
   whose `path` is `attachments/<sha256>` and whose file is there.
2. **The folders `--photos` names**, any number of them. An Apple Photos library (a folder ending in
   `.photoslibrary`) is read by the asset's UUID, which is the name of its original under
   `originals/<first character of the UUID>/`, so nothing is walked; any other folder is walked once per
   run into a map of file names (case aside, since both macOS and Windows ignore it) and the photo found
   by its `file_name`.

A keeper whose photo file is in neither is a counted skip (`skipped 3 without its photo file …`), never an
error; so is a keeper whose photo line is not in the record. Immich keeps its originals on the server; the
record has no path to them, so Immich keepers are described when a `--photos` folder holds a copy by file
name.

## The engine

`openlogbook[describe]` is `mlx-vlm` and `pillow-heif` (for the HEIC originals a phone takes), both on Apple
silicon only; elsewhere the extra installs nothing and the command says so. The model is any vision model
the hub serves in MLX format, by repository name (`--model`); the default is a 4-bit Qwen2-VL-2B, about
1.5 GB, which reads a photo in a second or two on a laptop. The model is sampled at temperature 0 for at
most 200 tokens. `--fetch-model` downloads it once; every run after that sets `HF_HUB_OFFLINE` for its
duration, so the engine cannot reach out whatever it would do. A faked engine in the tests asserts that no
socket is opened while a run is under way.

## What it does not do

- It does not pick keepers (RFC 0024 rule 1: a keeper is your act). It describes the ones you marked.
- It does not describe every photo. The library has thousands; the keepers are the ones worth words.
- It does not caption with people or places, as above.
- It does not read the description back into the Day, the trip or the year pages yet; `show` and `search`
  do.
