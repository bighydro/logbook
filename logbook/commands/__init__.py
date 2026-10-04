"""The commands of `logbook`, one family per module; `logbook/cli.py` is the entry point.

| module         | commands                                                                         |
|----------------|----------------------------------------------------------------------------------|
| `record.py`    | `init`, `setup` (the wizard; `places`, `assets`, `questions` are declared in     |
|                | their own families), `doctor` (`sources` in `sync.py`), `verify`, `backup`,      |
|                | `key` (`seal`; `circle` in `export.py`), `repair` (`retract`, `migrate`,         |
|                | `index`, `health-units`), `demo`, and `show stats`                               |
| `add.py`       | `add`; `import backup`, `import inbox`, `import attachments`                     |
| `sync.py`      | `sync`; `doctor sources`; `setup assets`                                         |
| `derive.py`    | `derive`: `stays`, `flights`, `keepers`, `transcripts`, `descriptions`           |
| `day.py`       | `show` (a day, a page, `year`, `days`), `day`, `digest`, `search`;               |
|                | `setup questions`                                                                |
| `trips.py`     | `show trips`, `show trip`                                                        |
| `keepers.py`   | `show keepers`                                                                   |
| `rollup.py`    | `rollup`, with `rollup ledger`                                                   |
| `people.py`    | `people`, `people NAME`, `people merge`                                          |
| `places.py`    | `setup places`                                                                   |
| `promises.py`  | `promises`, with `promises tasks`                                                |
| `export.py`    | `export` (with `export share day`), `import` (with `import trip-bundle`,         |
|                | `import page`), `key circle`                                                     |
| `serve.py`     | `serve`, with `serve mcp`                                                        |
| `lab.py`       | `lab`                                                                            |
| `aliases.py`   | the old top-level names and the words each became; `cli.main` rewrites them      |

The 22 top-level commands, their groups and their order are `parser.GROUPS` and `parser.ARGUMENTS`;
`docs/commands.md` lists them with the old names (the October 2026 audit, Decision 1).

A command is two functions in its family's module: `<command>_arguments(sub)` declares its arguments
and sets `fn=cmd_<command>`; `cmd_<command>(a)` runs it. `parser.py` lists the `_arguments`
functions in the order `logbook --help` shows them, and the groups it shows them in. `common.py`
holds what the families share, `skips.py` the phrases for an adapter's counts, `rows.py` the row
`show` prints for one line, `setup.py` the wizard behind `logbook setup`. A new command goes in the
module whose family it belongs to, or a new module when it starts a family, plus its line in
`parser.py`; a verb under an existing command is registered from that command's `_arguments`
function, which may call another family's (`setup_arguments` calls `places_arguments`). `logbook
--help` builds every family's arguments and must stay cheap: a family imports an adapter
(`logbook.contrib.adapters.*`) or a labs module (`logbook.labs.*`: the model code) inside the
function that runs the command, never at the top of the module, and a constant the help text needs
from one of them is a pinned copy (`tests/test_cli_lazy.py`).
"""
