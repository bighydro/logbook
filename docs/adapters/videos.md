# The family's videos

The family's home videos live in one Google Drive folder: tapes and DVDs digitised years ago, each an
MP4 of two to four gigabytes and an hour or more long, holding many separate recordings from different
years and places, one after another. Their titles are numbers (`Home 01`, `14`), and Drive's dates say
when they were digitised or uploaded, never when anything on them was filmed. Four steps bring them
into the record, and only the owner's own answer ever says where or when a recording was made:

```bash
logbook sync drive --videos                 # one video/v1 line per file, from Drive's metadata; nothing downloaded
logbook videos fetch --models               # once: the speech and vision models videos infer uses
logbook videos fetch                        # the next files into a bounded cache (8 GB), one at a time, md5 verified
logbook videos infer                        # on this machine, no network: the scenes, a draft per scene
logbook review video                        # the proposals, one scene at a time; nothing written unless told
logbook review video --accept 1,2 --reject 3 --ask 4
logbook review video --place 5 "Vollen Brygge" --date 5 "summer 1994"
logbook doctor                              # the videos line: files, fetched, inferred, proposed, confirmed, the cache
```

Every line this writes is tier 2: a family's video holds other people's faces and voices, and its title
may name them. The line formats are [RFC 0040](https://github.com/bighydro/logbook/blob/main/rfcs/0040-videos.md).

## The folder: a setting, never in the repository

`LOGBOOK_DRIVE_VIDEOS_FOLDER` is the folder's Drive id. Open the folder in Drive in a browser: its
address is `https://drive.google.com/drive/folders/<id>`, sometimes followed by `?usp=...`; the id is the
part after `/folders/` and before any `?`, letters, digits, `-` and `_`. Put it in the env file on the
record's home machine, `~/.config/logbook/sync.env`, beside the one Google key's two variables (the
tour's *Google, on one key*):

```bash
printf 'LOGBOOK_DRIVE_VIDEOS_FOLDER=%s\n' '<the folder id>' >> ~/.config/logbook/sync.env
set -a; . ~/.config/logbook/sync.env; set +a   # by hand: the variables into this shell
```

The id is a setting of that machine and never belongs in the record or in a repository. `sync --all`
and the schedule do not list the folder: `sync drive --videos` is run by hand, when the folder changed.

The listing uses the metadata scope `sync drive`'s folder paths already need,
`https://www.googleapis.com/auth/drive.metadata.readonly`. `videos fetch` reads a file's bytes and needs
one more, `https://www.googleapis.com/auth/drive.readonly`: add it to the key's client id in the Workspace
admin console, Security → Access and data control → API controls → Domain-wide delegation. Without it,
`videos fetch` says so in one sentence and fetches nothing. Older Drive files carry a *resource key*;
your own account needs none to read your own files, so nothing fails on one: the line records it and
`videos fetch` sends it.

## `sync drive --videos`: one line per file, from the metadata

The folder and every subfolder below it are listed, a page at a time, asking only for folders and video
files (`mimeType contains 'video/'`), never what is in the trash: the photos and scanned lists beside
the videos are never listed, and a subfolder of photos is walked and gives nothing. One `video/v1` line
per video file, source `drive-videos`, tier 2:

| Field | What it holds |
|---|---|
| `raw_id` | the Drive id: a file is written once however often the folder is listed |
| `library` | `google-drive` |
| `title`, `description` | the file's name; Drive's description, when it has one |
| `file` | `id`, `name`, `path` (the folders from the listed one down), `mime_type`, `url` (opens it in Drive), `resource_key` when Drive keeps one |
| `bytes`, `duration_s`, `width`, `height` | Drive's `size` and its video metadata, when Drive has processed the file |
| `digest` | `{md5}`: the checksum Drive reports, which `videos fetch` verifies the bytes against |
| `extra.drive_created`, `extra.drive_modified` | Drive's own times: the upload, recorded as what they are |

The line's `at` is when the folder was listed: when the record learned of the file. Drive's times are
never the line's time and never a filming time; when a scene was filmed is only ever the owner's
attribution (below). No byte of a video is downloaded. Every run lists the whole folder (it is small, and
only folders and videos are asked for), so a file moved in later is found, and the record's dedupe on the
Drive id writes nothing twice. A quota answer from Drive (its daily limit, or a rate limit that outlasts
the retries) stops the walk: what was listed before it is written, one line says what happened, the
watermark stays where it was, and the run exits 1; run it again later.

## What is downloaded, and when

Only `videos fetch` downloads, and only what `videos infer` is about to read. It takes the video lines
nobody has inferred yet and that are not in the cache, in the folder's order, and downloads them one at
a time into `state/videos/` in the record folder: bookkeeping, never the record, and left out of every
backup. Nothing downloads the folder, and no video is ever copied into the record.

- **The cap.** The cache holds 8 GB unless you give another with `--cache-gb N`, which is kept in
  `state/videos.json` for the next run and for `doctor`; 8 GB holds the largest file of a folder of 2–4
  GB tapes twice over. A file bigger than the cap is refused and said so, with the `--cache-gb` that
  would hold it; the run stops when the next file would take the cache past its cap, and `videos infer`
  makes room as it goes.
- **Verified.** Each file is hashed as it is written and compared with the md5 Drive reported when the
  line was written; a file that does not match is deleted, never kept, and said so.
- **Resumable.** A download that drops, whether the connection fails or the answer just ends short, is
  resumed from the byte it reached (`Range`), three times in a run; past that the part is kept, and the
  next `videos fetch` hashes it and carries on. A file Drive no longer has is said and skipped; a full
  disk stops the run.
- **Once inferred, not again.** A file with scene drafts is not fetched again; `--again` fetches the
  inferred files too, for `videos infer` under other models or settings, or after a release reads the
  picture another way (the key carries how: a file cut by an earlier reading is inferred again).
- `--limit N` fetches at most N files; `--models` instead fetches the speech and vision models `videos
  infer` uses, once (the only other network use of the videos).

## What a scene is, and how it is found

A scene is one continuous recording. A tape holds many, so where and when are proposed per scene,
never per file. `videos infer` asks ffmpeg on this machine (it must be on the PATH; it is told to open
nothing but files) for two signals: the picture's scene score of each frame, from 0 (the same picture)
to 1 (another picture entirely), and the soundtrack's loudness in windows of a quarter of a second.
Every frame is scored against the one before at the file's first frame size and pixel format, so a join
between clips stitched without re-encoding, where the size, the pixel format or the colour tags change,
is scored like any other (ffmpeg would otherwise start its filters again there and score that frame
against nothing). A scene begins at:

- **a cut**: a frame scoring 0.30 or more;
- **a weak cut with a break in the soundtrack**: a frame scoring 0.10 or more when, within half a second
  of it, the loudness of the second after differs from the second before by 6 dB or more, or the sound
  falls silent (-55 dB or less). Two recordings in the same room look alike; their sound seldom does;
- **a gap in the soundtrack**: a second or more of silence, the blank between two recordings on a tape,
  at its middle, whatever the picture does.

A camera that pans, a child running past the lens, someone who stops talking: none of these is a
boundary on its own. Breaks within 3 seconds of the first of a run are one (the strongest kept), so a
glitch of a few frames between two recordings is one boundary, and no run of weak breaks swallows a
strong one beyond it; none is kept within 3 seconds of the file's start or end; every scene is therefore
3 seconds or longer. The rules lean one way on purpose: a sudden change of light inside a recording (a
camera's flash, a lamp) can split it in two, which costs one more draft to answer, while a missed join
would mix two recordings in one proposal. A fade or a dissolve changes the picture too slowly to score a
cut, and is found only when the soundtrack breaks with it. The numbers are hypotheses, as `policy/stays.json`'s
are, and they are part of what a file is inferred under: other settings infer it again.

Of each scene, `videos infer` hears the sound (the transcribe extra, through its own `hear`, the scene's
sound cut out at 16 kHz) and looks at three frames, at a fifth, a half and four fifths of it (one, at its
middle, for a scene under six seconds), each shown to the describe extra's vision model with a prompt of
its own: what is visible, the setting, the season, every text on signs, boats and banners as written,
and the date or time a camcorder burned into the picture; never a person's name, never a guess at the
place. Each frame is deleted as soon as it is read: the descriptions are kept in the scene's draft, the
pixels nowhere.

## What `videos infer` writes

For each cached file not yet inferred under these models, prompt and scene settings, oldest in the
folder first, `--limit N` at most:

- **one `transcript/v1` line for the file**, source `video-transcription`, tier 2: the speech of every scene
  as WebVTT, each cue with its times in the file, so a scene's speech is a time range of it. Its `at` is
  the video line's and its `end` null: when it was said is not known. (Every transcript is presence
  evidence to the stays reader, SPEC §3.2.3 rule 5, so this one sits at the moment the record learned of
  the file, as an instant, and promotes at most the stop the owner was at then. It is no call:
  `transcript synthesize --day` and the 06:00 close leave it out, and `transcript synthesize` named by
  its id or `#seq` refuses it in one sentence, exit 2, so its words go to no model endpoint; the MCP
  server's `line` gives it with `text` null, whatever the ceiling.)
- **one `draft/v1` per scene** (RFC 0036), unit `event`, its `subject` the scene as a media fragment,
  `<video line id>#t=<start>,<end>`, source `model:video-rules/1`, tier 2. Its sentences say what the
  scene shows and says that places or dates it, each citing the video line (the frames) or the
  transcript line (the speech), with the frames and time ranges under `extra.segments`; the proposal
  (`extra.proposal`: a place, a date or date range, a confidence word) beside them; the frame
  descriptions under `extra.frames`; the models, the prompt and the settings it was made under. A
  file inferred again (`videos fetch --again`, other models or settings) writes a new draft per scene,
  which `supersedes` the earlier draft of a scene cut the same way (RFC 0036 rule 2).

The proposals are made by rules, not by a model behind an endpoint, so the draft can say nothing its
evidence does not:

- **a place** only from your own registries: a name of `places.json`, or an asset's name or
  registration of `assets.json` (a boat's name on her hull), read whole, case and punctuation aside, on a
  sign in a frame (`high`), in what was said (`medium` for a name of two words or more, `low` for one
  word; a name shorter than five letters is never matched in speech: "Hjem", "Home"), or in a frame's
  description (`low`). The draft names the place; its coordinates are the registry's, never the draft's.
  A sign that names nothing you have is said, and proposes nothing; two places with the same weight
  propose neither.
- **a date** from the camcorder's burned-in stamp, to the precision it shows: a day, a month, a year;
  a stamp whose day and month could be either way round (`07.08.94`) is one or the other and proposes
  the span from one to the other, and stamps that disagree their range; a stamp that is no real date
  (`31.02.1994`, a date after today) dates nothing; 1 January at midnight is a clock never set and dates
  nothing, and 1 January without a time is proposed `low` and said so; the time in a stamp is never read
  as a year. Without a stamp, a year written in a frame or said aloud (`low`), but never one a shop or a
  banner has stood since ("SINCE 1952", "etablert 1965"), narrowed to spring, summer or autumn when the
  frames agree on the season (the north's seasons); a season alone dates nothing.
- **nothing to go on**: a scene with neither gets a draft that says so, and proposes nothing.

Nothing opens a socket while it runs: no model is fetched (a model that is not here is one sentence
naming `videos fetch --models`), the Hugging Face hub is told it is offline before any engine is even
imported, and ffmpeg opens files only.
The file is deleted from the cache once inferred, unless `--keep`; a run that stops keeps what it wrote
and the next carries on. `--dry-run` says which cached files would be inferred and needs no engine.

## `review video`: one scene at a time

`review video` is one more queue of the one review sitting ([Review](../review.md), RFC 0037): `review`
alone lists it after the person's, the org's, the idea's, the asset's and the place's, `--accept`,
`--reject` and `--json` mean what they mean for every kind, and the options below are its own: any
other kind refuses them, as it refuses a place's. The queue is every scene of each file's latest inference that you have not answered, the surest
proposals first, then the scenes with nothing to go on. Each row shows the file, the scene and its
offsets, the proposal, the sentences with the frames and speech they cite, what the frames showed, and,
when the proposal is one day the rules trust (its date not `low`), where the record had you and your assets that day (the Day's stays, the
assets' positions), or the nearest day within three that has any. On a terminal it asks for each scene:
`y` confirms, `n` refuses, `a` keeps it to ask the family, Enter skips, `q` stops; you are asked with
no lock held, so a scheduled sync never waits on you, and each answer is written at once under the
record's writer lock, as every queue's is. With flags, every number is checked before the first line
is written:

| Answer | Writes |
|---|---|
| `--accept N[,N]` | one `attribution/v1` line per scene, tier 2, source `manual`: the scene (`ref` `{kind: scene, value: <video line id>#t=<start>,<end>}`, `scene` `{video, start_s, end_s}`) bound to the place (`{type: place\|asset, id, registry, label}`) and/or the date or date range (`{from, to, precision}`) proposed, `method` `owner`, the draft, the video and the transcript as evidence. The video's own line is never touched |
| `--place N NAME`, `--date N WHEN` | the same, with your own place (a `places.json` name, an asset's id or name) or date (`1994`, `1994-07`, `1994-07-14`, `summer 1994`, `1994-06..1994-08`), or `none` to leave that part out |
| `--reject N[,N]` | the scene's no: one `scene-review/v1` line (RFC 0040 §5), a line of its own that no queue of a place, an asset or any other kind reads: the scene, `verdict` `different`, the proposal it answers as the draft carried it, the draft, and `supersedes` the scene's standing no when a later inference proposed something else; while the no stands, that proposal is not offered for that scene again: retract it, or refuse what a later inference proposes instead (the new no supersedes it), and it may be asked again |
| `--ask N[,N]` | one open `task/v1` line in the list `videos`, so a later shared page can put the scene before the family; the scene leaves the queue, `--asked` brings it back, and answering it closes the task |
| `--answered` | the scenes you confirmed, to correct one: a new answer supersedes the standing line; the same answer twice writes nothing |
| `--top N` | only the first N scenes of the queue (a place's option too, where it counts places) |

Nothing else writes: no place is added to `places.json`, no line is rewritten, and the review reads the
record and the registries alone, with no connection.

## Tiers

The video line, its transcript and the transcript's text, the scene drafts with their frame
descriptions, the attributions, the noes and the asks are all tier 2, and nothing derived from them is
written lower. They cross only to a destination whose ceiling is 2 or more ([the crossing](../crossing.md));
in a record with recipients they are sealed like every tier-2 line (RFC 0029). The scene drafts are made
by models on this machine and nothing crosses to make them, so no crossing entry governs them as one
governs the dream's.
