# The commands

`logbook` has 22 commands, grouped here by what you are doing. `logbook --help` is this list on one
screen; `logbook <command> --help` has a command's arguments. Everything that was a command of its
own before 0.6 still answers to its old name: it prints one line saying the new one and runs it (the
table at the end, generated from the code by `scripts/command_aliases.py`).

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
| `sync` | pull new items from a live source (immich, dawarich, imessage, gcal, granola, ais, adsb, weather); `--all` for every configured one |

## Read

| Command | What it does |
|---|---|
| `show` | one day's lines (default today); a page: `show person\|asset\|place NAME`; a reader: `show year YYYY`, `show trip ID-OR-DAY`, `show trips`, `show days`, `show keepers`, `show stats` |
| `day` | one day read back: the night, country, stays and moves with who and what, flights, health |
| `digest` | one day in 25 lines at most, closing with one question |
| `search` | full-text search through the index: words, `"a phrase"`, `kar*` |
| `people` | everyone the record names, never the owner; `people NAME` is one person's page; `people merge` the same person named twice |
| `rollup` | the record per year: countries, flights, nights, places, people, listen, attention, money; per month or week: health, attention; `rollup ledger` the transactions in context |
| `serve` | the record in a browser, from this machine only; `serve mcp` serves it to an MCP host |

## Derive

| Command | What it does |
|---|---|
| `derive` | `derive stays` reads the record into stays and moves, appending nothing; `derive flights` and `derive keepers` infer lines; `derive transcripts voice-memos` and `derive descriptions keepers` run a local model, nothing leaving the machine |
| `promises` | commitments the transcripts and notes suggest, by rules, as proposals; `promises done ID` closes one; `promises tasks` the tasks, each as it stands |

## Keep

| Command | What it does |
|---|---|
| `verify` | check the chain |
| `backup` | a verified snapshot of the record on another disk; `backup list DEST`; `backup restore SNAPSHOT TARGET` |
| `key` | the record's recipients and this machine's identity: `init`, `show`, `add-recipient`, `remove-recipient`; `key seal --all` seals what was written before the record had recipients; `key circle` the sharing keys |
| `repair` | put the record right, rewriting nothing: `repair retract SEQ REASON`, `repair migrate`, `repair index`, `repair health-units` |

## Share

| Command | What it does |
|---|---|
| `export` | the whole log as one `.jsonl`, day packages, `crossing`, `vault FOLDER`, `site FOLDER`, `trip-bundle TRIP`, or `share day YYYY-MM-DD --to NAME` |

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
