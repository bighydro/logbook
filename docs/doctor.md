# The doctor

`logbook doctor` is the check-up: one line per check, `pass`, `warn` or `fail`, and exit 1 when
anything fails. It reads and never writes, but for the file `--packet --out` names. The checks and
their rules are listed in the module's own documentation (`logbook/contrib/doctor.py`); the schedule
runs it four times a day ([The schedule](schedule.md)). `logbook doctor sources --gaps` says where
each source went quiet; `logbook doctor --packet` is the diagnostic to send a collaborator ([Sending
a diagnostic](#sending-a-diagnostic)).

## The files the lines name

The `record` line is `verify` on the files, and looks for every attachment a line names as `verify` does
([When verify fails](recovery.md#the-files-the-lines-name)). The missing ones are counted in the pass and
are not a warn, since SPEC §1.1 allows them:

```
pass  record  1,204 lines, head 4dc18fde900d…, verified; 3 attachments missing (SPEC §1.1 allows it; `logbook attach status`); /Users/ines/Logbook
```

Their bytes are not hashed here, nor a sealed one opened: the doctor runs four times a day, and a store of
photos is read by `logbook verify` by hand, or by `logbook backup --verify`.

`logbook doctor --attachments` names them: per source, the most first, each standing line whose file the
store lacks, with its kind, its time and the first twelve characters of the digest, then the count by
source ([the attachment store](attachments.md#the-lines-whose-file-is-missing)). It exits 0 and changes
nothing.

## Agents

A record with a line marked machine text, or a `policy/agents.json` that names a sender, gets an `agents`
line after `owner` ([your own agents](adapters/agents.md)): the standing lines marked machine per source
(a message an agent wrote, a transcript with an agent among its participants), the most first, and how
many senders the file names, the owner's own bots the Beeper adapters mark.

```
pass  agents  lines marked machine: telegram 412, beeper-telegram 96, claude-code 31; 1 sender named in policy/agents.json
```

It reads the transcripts and the messages of the sources that write the mark (`telegram`, `beeper`,
`beeper-<network>`), from the index when it is current. A file that is not the shape is a **fail** naming it.

## Voiceprints

A record whose transcripts carry voices, or that keeps a voiceprint registry, gets a `voiceprints`
line after `assets` ([Voiceprints](speakers.md#voiceprints), RFC 0038 §5). It says that the file is
there, when it was written and, opened with this machine's identity, with which embedding model and
for how many people; never what is in it:

```
pass  voiceprints  voiceprints.age written 2026-10-11 10:12 with pyannote/wespeaker-voxceleb-resnet34-LM, for 3 people, you among them; 2 voices not yet named
```

A **warn** when the file was written with a model that is not the configured one, whose vectors it
cannot compare (`logbook setup speakers --rebuild` makes it again), or when it will not open with this
machine's identity. On a machine without the identity it says only that the file is there and when.
A record that names no recipients keeps no registry, and the line says so: the review hears the
voices it compares for each run and keeps nothing. A record with voices and no file yet: `none yet:
logbook setup speakers --rebuild makes voiceprints.age`; on a machine without the identity, which
writes no registry, what a write there answers: `none, and none is written here: no identity on this
machine, and voiceprints.age is sealed to the record's recipients and needs one`. (Such a machine
sees the voices only of transcripts written before the record had recipients; of sealed ones it sees
none, and says nothing.) The line opens the file and writes nothing.

## Where the day begins

A record whose day does not begin at midnight ([`day_start`](settings.md)) gets a `day-start` line
after `index`: a pass naming the boundary (`pass  day-start  the day begins at 06:00: a line before 06:00
belongs to the day before`); a **warn** when `index.sqlite` was built under another boundary, naming
both (the next reader rebuilds it, or `logbook repair index` does now); a **fail** when the value is not
a clock `HH:MM`, which every reader that groups by day refuses. A record whose day begins at midnight,
with an index that agrees, has no such line.

## What leaves, and what may be fetched

The `crossing` line lists each entry of `policy/crossing.json` as it counts today (`mcp 1`, `hermes 2
until 2026-12-31`, `heard 2 fetch`). When `LOGBOOK_HEARD` names `feed` and no `heard` entry lets a
transcript be fetched, it says which entry to write, `{"heard": {"max_tier": 2, "fetch": true}}`. The
`world` line says what `export world` and the Library's `/world` show: tier 1 alone when the file names
no `world` entry, and the entry that adds the chapters, `{"world": {"max_tier": 2}}`. A folder that
`export --day` or `--days` writes reads its ceiling from the `folder` entry, tier 1 without one, as the
vault and the site read theirs; `--tier` may lower it, never raise it; and the record keeps a crossing
line for it, as for every export ([a day to a folder](export.md)).

## Drafts the policy no longer allows

A draft follows the `dream` entry of `policy/crossing.json`, not the head ([the dream](dream.md), *When
the entry changes*). When a day's standing draft is above what the entry allows today (the ceiling
lowered, the `until` passed, the entry removed), no reader shows it, and a `drafts` line after
`crossing` names the days: ``warn  drafts  1 day(s) with a draft above what the dream entry allows, which
no reader shows: 2026-06-10 (#5440, tier 3); the 'dream' entry allows max_tier 2 now; `logbook dream
--catch-up` dreams them again under it``. A record with no such day has no line.

## Calls without a synthesis

When `policy/crossing.json` has a `dream` entry, a `synthesis` line after `drafts` counts the calls
(`transcript/v1` lines) that have no synthesis ([the synthesis of a
call](transcript-synthesis.md#the-week-the-close-covers)), in three parts, each only when it counts any:
those of the last 7 days and today, which the 06:00 close synthesizes; those before, which the close
leaves, with the `--since` that reaches the oldest; and those above the entry's `max_tier`, which never
leave the machine:

```
pass  synthesis  4 calls without a synthesis: 1 since 2026-10-07, which the 06:00 close synthesizes (`dream --catch-up`); 2 before 2026-10-07, which the close leaves: `logbook dream --catch-up --since 2026-08-21`; 1 above the dream entry's max_tier 2, which stays on this machine
```

It is a pass: the close leaves older calls by design, so a record with years of transcripts does not
send them all to the model one morning. A record without a `dream` entry, or whose every call has a
synthesis, has no such line. A retracted or superseded call is not counted, nor a call whose synthesis
was made under another version of the entry: it has one.

## The family's videos

When the record names the family's videos (`sync drive --videos`) or the cache under `state/videos/`
exists, one `videos` line says how many video files the record holds and their size, how many `videos
fetch` has fetched and `videos infer` has inferred, how many wait in the cache, how many scenes the
latest inference of each file found, how many it proposed a place or a date for and how many you
confirmed with `review video`, and the cache against its cap:

```
pass  videos  25 video files in the record (78.4 GB); 6 fetched, 5 inferred, 1 waiting in the cache; 212 scenes, 61 proposed, 14 confirmed; cache 3.1 GB of 8.0 GB
```

A cache over its cap (a cap lowered with `--cache-gb` below what it holds) or a `state/videos.json` that
is not the shape is a warn. Nothing is asked of Drive ([Videos](adapters/videos.md)).

## The Google key

When either variable of the Google service-account key is set (`LOGBOOK_DRIVE_SA_KEY`,
`LOGBOOK_DRIVE_USER`), one `google` line comes before the `sync:` lines of the sources it covers: the key
file present and a service-account key, the user an address, which of `gmail`, `gcal`, `drive`, `gtasks`,
`meet` and `gaudit` are on it, a source switched off in `policy/import.json` named as disabled, and what
`people review --from-google` reads on it —
`pass  google  key present, user set; sources on the key: gmail, gcal, drive, gtasks, meet, gaudit; people
review --from-google: contacts, other contacts`. A key not set,
not readable or not a service-account key, or a user that is not an address, is a warn naming the
variable. The line reads the key on this machine and asks Google nothing, and never prints the path or
the address ([the tour, *Google, on one key*](tour.md#google-on-one-key)).

## A source whose history was never read

A source's first scheduled run reads its last 14 days, not its whole history ([the
schedule](schedule.md#a-sources-first-scheduled-run)). Until a run reads the rest (`--since` before
that window, or `--restart`), the source's `sync:` line says so after what it says of the
variables: ``pass  sync:drive  configured (LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER); first run bounded
to 14 days; history not read (before 2026-09-25: `logbook sync drive --since <date>`)``. The note never
changes the line's status: nothing is broken, and the history may be one you never want read.

## Implausible dates

A calendar entry a parser placed in 1948, or a mail a sender's broken clock dated 2612, is not a
day of the owner's life. The `dates` line counts the lines whose timestamp lies outside their
source's plausible range, per source with the earliest and the latest, and warns:
`warn  dates  2 line(s) dated outside their source's plausible range: ics 1 (1948-03-01 to
1948-03-01); mail 1 (2612-03-01 to 2612-03-01); …`. The ranges are: calendar entries (kind
`event`) from 1970-01-01 to now plus 5 years; mail from 1990-01-01 to now plus 1 day; every other
line from 1970-01-01 to now plus 1 day. A record overrides them per source in
`policy/plausible.json`, either field optional — `{"sources": {"ios-calendar": {"earliest":
"1960-01-01", "ahead": "10y"}}}`, `ahead` a count of years or days (`5y`, `1d`); a file that is not
this shape is a fail naming it. Nothing is deleted, hidden or rewritten: the lines stay in the log
and in every reader as they were written. `logbook doctor --implausible` lists them, one row each:
the line id, the source, the kind, the timestamp and the range it missed, then the count.

## The extras

One `extra:` line per optional extra the doctor knows, `ais`, `crypto`, `sealed`, `speakers` and
`transcribe`, in that order after `dates`: a pass naming the package that makes it, or a **warn** with
its install line ([optional extras](install.md#optional-extras)). They are this machine's, so a
`doctor` that finds no record prints them too, after its failed `record` line.

```
pass  extra:ais         websockets is installed
pass  extra:crypto      cryptography is installed
pass  extra:sealed      pyrage is installed
warn  extra:speakers    pyannote.audio not installed: pipx inject openlogbook "openlogbook[speakers]==0.7.0"
pass  extra:transcribe  faster-whisper is installed
```

`transcribe` passes on either Whisper engine, `mlx-whisper` or `faster-whisper`. `speakers` is its own
extra, apart from `transcribe` since it brings torch, so a machine that transcribes voice memos without
telling the voices apart has that one warn. Nothing is imported to find out, since an engine loads its
model on import: a module is looked for on the path, and pyannote.audio by its installed distribution,
as `derive speakers` asks for it. A pass says the package is here, not that its models are: `logbook
setup speakers --fetch-model` fetches those.

## Sending a diagnostic

When something fails — the dream's model endpoint answers 500, a sync adapter stops, the service will
not stay up — a collaborator needs to see this machine without seeing the record. `logbook doctor
--packet` prints a plain-text packet to send instead of a description put together by hand;
`--out FILE` writes it to a file. It holds:

- **machine**: the OS and its version, the platform string, the architecture, the RAM, the Python and
  openlogbook versions, and which extras are installed, with the version of each package that makes one.
- **record**: the line count and the head as `logbook.json` names them (the head is a hash, not a
  line), the format, where the day begins and whether `index.sqlite` is current. No line is read.
- **sources**: one line per live source the record uses or the last scheduled run listed — configured,
  or the variables it still needs by name; the last run's result and lines; and the date of its
  watermark in `state/<name>.json`, the date alone (`immich: configured; last run ok, 12 lines;
  watermark 2026-10-12`).
- **schedule and service**: which installs of the schedule this machine has, the last scheduled run
  (when, the lines per source, the sources that failed, the doctor's counts and the names of the
  checks that warned or failed), and the serve services with their ports.
- **dream endpoint**: the host and port of `LOGBOOK_DREAM_ENDPOINT` (never its path), the model, the
  policy's `dream` entry, the temperature the request carries (`temperature: 0.2 (the default)`, the
  value of `LOGBOOK_DREAM_TEMPERATURE`, or `none`, when no temperature field is sent), and one probe: the dream's own request, the key as its bearer token when
  `LOGBOOK_DREAM_KEY` is set, with the fixed prompt `Reply with the single word ready.` where a day
  would be, sent once. The reply's HTTP status and body follow as they came (up to 64 KiB): a model's
  error is not the record's content. A 400 whose body names the temperature adds `hint: set
  LOGBOOK_DREAM_TEMPERATURE=none for a model that takes no temperature`.
- **environment**: the names of the variables set that logbook reads — every `LOGBOOK_*`, the proxies,
  the config and cache folders — never a value.
- **sync log** and **service log**: the last 40 lines of each, from `~/Library/Logs/logbook-sync.log`
  and `~/Library/Logs/logbook-serve.log` on macOS, from the journal on Linux (`journalctl` for the
  timers and the service installed here); none elsewhere.

The probe is the packet's one network call, and it is made only when `LOGBOOK_DREAM_ENDPOINT` is set and
a model is named (`LOGBOOK_DREAM_MODEL`, or the `model` of the policy's `dream` entry), and only while
the policy's `dream` entry allows the dream: the probe carries your key to the endpoint, so with no
`dream` entry, or one past its `until`, it is not sent and the packet says why (`probe: not sent, …`).
Without them nothing is fetched. Unlike `doctor`'s `serve` line, the packet does not ask the service's port whether
a server answers: that would be a second request.

Whatever the packet quotes rather than writes — a log line, the reply, an error, a source's result — is
scrubbed first, the longest match first:

| replaced by | what |
| --- | --- |
| `~` | the home directory, as given and resolved, with either separator |
| `[record]` | the record's folder |
| `[owner]` | the owner's names and each word of them, handles (with and without `@`), addresses and numbers from `policy/owner.json` and `owner_emails`, and the login name unless it is a generic account (`root`, `admin`, `runner`, …); a number is found by its last eight digits however it is spaced, so `+44 7700 900461`, `07700900461` and `(+44) 7700-900-461` are one |
| `[host]` | this machine's name, in full and before its first dot |
| `[place]`, `[asset]` | the names of the places in `places.json` and of the assets in `assets.json`, as written |
| `[NAME]` | the value of the variable `NAME`: every `LOGBOOK_*` but `LOGBOOK_HOME`, `LOGBOOK_DREAM_MODEL` and `LOGBOOK_DREAM_TEMPERATURE`, every proxy, and any variable named like a key, a token or a password |

A `policy/owner.json` that cannot be read is said at the top: the owner's names are then not replaced.
What the packet does not know it cannot replace — another person's name a sync printed, a calendar's
title — so read it before you send it.
