# The commands

`logbook` has 22 commands, grouped here by what you are doing. `logbook --help` is this list on one
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
| `setup` | the guided first run, one question at a time, resumable; and the record's settings: `setup places`, `setup assets`, `setup questions` |
| `doctor` | the check-up, one line per check, exit 1 on a fail; `doctor sources` lists every adapter and, with `--gaps`, where each went quiet |

## Write

| Command | What it does |
|---|---|
| `add` | a sentence in your words, an export file, a folder of them, or `flight "LX 561 NCE ZRH …"` |
| `import` | `import backup DIR` reads every phone source of an iOS backup; `import trip-bundle FOLDER` a trip another record exported; `import page FILE` a day someone shared; `import inbox` what is in `inbox/`; `import attachments` the attachment store |
| `sync` | pull new items from a live source (immich, dawarich, imessage, gcal, granola, ais, adsb, weather); `--all` for every configured one, immich last; an interrupted immich walk resumes, `--restart` walks the library again |

## Read

| Command | What it does |
|---|---|
| `show` | one day's lines (default today); a page: `show person\|asset\|place NAME`; a reader: `show year YYYY`, `show trip ID-OR-DAY`, `show trips`, `show days`, `show keepers`, `show stats` |
| `day` | one day read back: the night, country, stays and moves with who and what, flights, health, whether every usual source is in, and whether you signed it; `day sign YYYY-MM-DD [--note TEXT] [--confirm ID,ID] [--kept ID,ID] [--missed ID,ID] [--dropped ID,ID] [--carried ID,ID]` signs it, and says what became of the commitments on it ([the signed day](signed-day.md)) |
| `digest` | one day in 25 lines at most, closing with one question |
| `search` | full-text search through the index: words, `"a phrase"`, `kar*` |
| `people` | everyone the record names, never the owner; `people NAME` is one person's page; `people merge` the same person named twice |
| `rollup` | the record per year: countries, flights, nights, places, people, listen, attention, money; per month or week: health, attention; `rollup ledger` the transactions in context |
| `serve` | the record in a browser, from this machine only; `serve mcp` serves it to an MCP host |

## Derive

| Command | What it does |
|---|---|
| `derive` | `derive stays` reads the record into stays and moves, appending nothing; `derive flights` and `derive keepers` infer lines; `derive transcripts voice-memos` and `derive descriptions keepers` run a local model, nothing leaving the machine |
| `promises` | what you promised and what you were asked, from mail, messages, transcripts and notes, by rules, as proposals, in two sections with the line id a signed day confirms; `promises done ID` closes one; `promises tasks` the tasks, each as it stands |

## Keep

| Command | What it does |
|---|---|
| `verify` | check the chain |
| `backup` | a verified snapshot of the record on another disk; `backup list DEST`; `backup restore SNAPSHOT TARGET` |
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
