# The commands

`logbook` has 25 commands, grouped here by what you are doing. `logbook --help` is this list on one
screen; `logbook <command> --help` has a command's arguments. Everything that was a command of its
own before 0.6 still answers to its old name: it prints one line saying the new one and runs it (the
table at the end, generated from the code by `scripts/command_aliases.py`).

One writer at a time: a command that appends (`add`, `sync`, `import backup`, and every other through
`append`) holds `state/writer.lock` in the record folder for its whole run, a `sync`'s walk included.
A second writer says `another logbook command is writing to this record (sync immich, since
2026-09-10T06:00:00Z); waiting` and waits; with the global `--no-wait` it refuses and exits 2. A lock
whose process is gone is taken over with one line saying so. Readers (`show`, `day`, `verify`, every
reader) never take it. The lock is the courtesy between writers; what keeps the chain whole is that a
writer reads `logbook.json` again before every batch and writes nothing when the head has moved.

## Start

| Command | What it does |
|---|---|
| `init` | create a logbook (default `~/Logbook`) |
| `setup` | the guided first run, one question at a time, resumable; and the record's settings: `setup places`, `setup assets`, `setup questions`, `setup day_start` ([where your day begins](settings.md)); `setup places review` names the places you return to from what the record already knows, offline, and with `--ask-photos` from what your photo libraries say about the photos already in it ([places](places.md)) |
| `doctor` | the check-up, one line per check, exit 1 on a fail, the crossing ceilings, the record's home (ADR 0022), the last scheduled run, the last restore test and the serve service among them, and lines dated outside their source's plausible range (`--implausible` lists them, [The doctor](doctor.md)); `--packet [--out FILE]` is a diagnostic to send a collaborator, with no line's content, no name, no home path and no value in it, and one probe of the dream endpoint when it is set ([Sending a diagnostic](doctor.md#sending-a-diagnostic)); `doctor sources` lists every adapter and, with `--gaps`, where each went quiet |

## Write

| Command | What it does |
|---|---|
| `add` | a sentence in your words, an export file, a folder of them, or `flight "LX 561 NCE ZRH …"` |
| `import` | `import backup DIR` reads every phone source of an iOS backup; `import trip-bundle FOLDER` a trip another record exported; `import page FILE` a day someone shared; `import inbox` what is in `inbox/`; `import attachments` the attachment store |
| `sync` | pull new items from a live source (immich, dawarich, imessage, beeper, gcal, drive, gtasks, meet, gaudit, granola, mail, gmail, notion, ais, adsb, weather); `--all` for every configured one, immich last; beeper: `--networks` chooses the bridged networks; an interrupted immich walk resumes, `--restart` walks the library again; `sync mail` reads a mailbox over IMAP, read-only, resumed per folder from the last batch written (`LOGBOOK_IMAP_HOST`, `_USER`, `_PASSWORD`; `--since` searches from that day, `--restart` drops the marks); `sync notion` writes what happened to each Notion page on each day, one `event/v1` line per page, day and action, never the page's text (`LOGBOOK_NOTION_TOKEN`; `LOGBOOK_NOTION_ROOTS`, `LOGBOOK_NOTION_OWNER_ID`); `sync gmail`, `sync gcal`, `sync drive`, `sync gtasks`, `sync meet` and `sync gaudit` read Gmail (the line `sync mail` writes), the calendars you own, Google Drive's activity with each file's folder path, Google Tasks, your Meet calls (and their transcripts, as Granola's are) and your own sign-ins from the Workspace's login audit log (never the address), read-only, with one Workspace service account, a scope per source (`LOGBOOK_DRIVE_SA_KEY`, `LOGBOOK_DRIVE_USER`; gcal reads its iCal feeds, `LOGBOOK_GCAL_URLS`, only without them; the tour's *Google, on one key*); `--install-schedule` runs `sync --scheduled` (`sync --all`, then `doctor`, the outcome to `state/last-run.json`, one message when something is wrong) at 00:00, 12:00 and 18:00, and at 06:00 `sync --scheduled --close`, which closes the day (the dream's catch-up after the sync); `--system` for a machine nobody logs in to |
| `goal` | your goals, one `goal/v1` line each in your own words, tier 2 ([goals](goals.md)): `goal add TEXT --horizon life\|year\|quarter [--from DAY] [--until DAY] [--supersedes GOAL]` writes one (a goal reworded is a new goal that supersedes the old); `goal review GOAL advancing\|stalled\|done\|let-go\|superseded [--note TEXT] [--at DAY\|RFC3339] [--period day\|week\|month\|quarter\|year]` your verdict on it, on the day it is about (written in October about August, it is on the August Day); `goal list [--open] [--json]` every standing goal with its latest review; `goal import FILE [--horizon H] [--from DAY] [--review DISPOSITION [--at DAY] [--period P] [--note TEXT]] [--dry-run]` the first backfill, one goal per line of a text file (`text \| horizon \| from`), one verdict for all of them when given |
| `chapter` | a stretch of your life you name, one `chapter/v1` line, tier 2: `chapter open NAME [--from DAY] [--to DAY] [--rules TEXT]`, `chapter close [--to DAY]` (the open chapter written again with its last day), `chapter list [--json]`; chapters do not overlap, and the Day's header names the chapter a day is in ([goals](goals.md#chapters)) |

## Read

| Command | What it does |
|---|---|
| `show` | one day's lines (default today); a page: `show person\|asset\|place NAME`; a reader: `show year YYYY`, `show trip ID-OR-DAY`, `show trips`, `show days`, `show keepers`, `show stats` |
| `day` | one day read back: the night, country, stays and moves with who and what, flights, health, whether every usual source is in, and whether you signed it; `day sign YYYY-MM-DD [--note TEXT] [--confirm ID,ID\|none] [--at RFC3339] [--kept ID,ID] [--missed ID,ID] [--dropped ID,ID] [--carried ID,ID]` signs it, says what became of the commitments on it, with `--confirm none` confirms nothing and still signs, and with `--at` carries the moment you clicked, not the moment it ran ([the signed day](signed-day.md)); `day reflect YYYY-MM-DD [--text TEXT \| --audio FILE \| --mic SECONDS \| --from-wispr [SEQ]] [--at RFC3339] [--sign [--accept N,N\|none]] [--dry-run]` closes it in your words: the reflection typed, heard on this machine, recorded on macOS, or the day's Wispr Flow dictation that begins with "reflect", written as one `note/v1` line, its commitments, delegations and dispositions proposed by rules, and with `--sign` the day signed with the ones you accept ([closing the day by voice](signed-day.md#closing-the-day-by-voice)); the days together 1, 2, 3, 5 and 10 years ago as `anniversaries`, off with `--no-anniversaries` |
| `digest` | one day in 25 lines at most, closing with one question |
| `search` | full-text search through the index: words, `"a phrase"`, `kar*` |
| `people` | everyone the record names, never the owner; `people --priority` ranks them by a plain score; `people NAME` is one person's page; `people merge` the same person named twice; `people review` who the sources saw that the record has not placed, proposed against the people it names, accepted or rejected only when told, `--from-google` with your Google contacts as names for it, never lines; `people drift [--min-days N] [--quiet-days M] [--year YYYY] [--show]` who you used to see and have drifted from; `people nearby PLACE \| --journey ID \| --days FROM TO [--radius KM]` who has been seen where you are about to go ([people](people.md)); `people ingest NAME --window FROM TO` and `people ask NAME QUESTION`, the relationship reader, experimental, no model wired yet (`logbook/contrib/relationship/README.md`) |
| `rollup` | the record per year: countries, flights, nights, places, people, listen, attention, money; per month or week: health, attention; `rollup ledger` the transactions in context |
| `serve` | the record in a browser, from this machine only (`/today` is today's Day); `--install-service [--system]` keeps it running by launchd or systemd, `--status` says whether it answers; `serve mcp` serves it to an MCP host |

## Derive

| Command | What it does |
|---|---|
| `derive` | `derive stays` reads the record into stays and moves, appending nothing; `derive flights` and `derive keepers` infer lines; `derive transcripts voice-memos` and `derive descriptions keepers` run a local model, nothing leaving the machine |
| `promises` | what you promised and what you were asked, from mail, messages, transcripts and notes, by rules, as proposals, in two sections with the line id a signed day confirms; `promises done ID` closes one; `promises tasks` the tasks, each as it stands |
| `dream` | `dream day YYYY-MM-DD [--dry-run] [--show-prompt]`: a model reads the day under the `dream` entry of `policy/crossing.json` and writes one `draft/v1` line, the day in a paragraph, the threads it moved, two questions, the people and promises it proposes, every sentence with the lines it came from or marked unsupported; a proposal, shown on the Day above your note, never a fact; `dream --catch-up [--days N]` dreams each of the last N days that has no draft or whose lines changed, one line per day ([the dream](dream.md)) |

## Keep

| Command | What it does |
|---|---|
| `verify` | check the chain |
| `backup` | a verified snapshot of the record on another disk; `backup list DEST`; `backup restore SNAPSHOT TARGET`; `backup --restore-test` restores the latest snapshot into a temporary folder and verifies it, monthly on the schedule |
| `key` | the record's recipients and this machine's identity: `init`, `show`, `add-recipient`, `remove-recipient`; `key seal --all` seals what was written before the record had recipients; `key circle` the sharing keys |
| `repair` | put the record right, rewriting nothing: `repair retract SEQ REASON`, `repair migrate`, `repair index`, `repair fork [--apply]` (two chains forked at one head: diagnose, and move the orphan chain out into `repair/`), `repair health-units` |

## Share

| Command | What it does |
|---|---|
| `export` | the whole log as one `.jsonl`, day packages, `crossing` (signed days only unless `--unsigned`), `vault FOLDER`, `site FOLDER`, `trip-bundle TRIP`, or `share day YYYY-MM-DD --to NAME` |

## Try

| Command | What it does |
|---|---|
| `demo` | a synthetic record to try the commands on; nothing in it is real |
| `lab` | readers still finding their shape ([the lab](labs.md)); read-only |

## The old names

Every name below still works, hidden from `--help`: it prints one line on stderr, `` `logbook X` is
now `logbook Y Z` ``, and runs the new command with the same arguments and exit status, printing the
same thing. A script or an alias in your shell keeps working; change it when you like. The table is
written by `scripts/command_aliases.py` from `logbook/commands/aliases.py`, and a test holds the two
together.

<!-- aliases:start -->
| Was | Is now |
|---|---|
| `logbook assets` | `logbook setup assets` |
| `logbook attach` | `logbook import attachments` |
| `logbook circle` | `logbook key circle` |
| `logbook days` | `logbook show days` |
| `logbook describe` | `logbook derive descriptions` |
| `logbook import-backup` | `logbook import backup` |
| `logbook inbox` | `logbook import inbox` |
| `logbook index` | `logbook repair index` |
| `logbook infer` | `logbook derive` |
| `logbook keepers` | `logbook show keepers` |
| `logbook ledger` | `logbook rollup ledger` |
| `logbook mcp` | `logbook serve mcp` |
| `logbook migrate` | `logbook repair migrate` |
| `logbook person` | `logbook people` |
| `logbook places` | `logbook setup places` |
| `logbook questions` | `logbook setup questions` |
| `logbook receive` | `logbook import page` |
| `logbook retract` | `logbook repair retract` |
| `logbook seal` | `logbook key seal` |
| `logbook share` | `logbook export share` |
| `logbook sources` | `logbook doctor sources` |
| `logbook stats` | `logbook show stats` |
| `logbook tasks` | `logbook promises tasks` |
| `logbook transcribe` | `logbook derive transcripts` |
| `logbook trip` | `logbook show trip` |
| `logbook trips` | `logbook show trips` |
| `logbook year` | `logbook show year` |
<!-- aliases:end -->
