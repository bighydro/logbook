"""The commands of `logbook`, one family per module; `logbook/cli.py` is the entry point.

| module         | commands                                                                       |
|----------------|--------------------------------------------------------------------------------|
| `record.py`    | `init`, `setup`, `stats`, `index`, `verify`, `doctor`, `backup`, `migrate`,    |
|                | `retract`, `repair`, `demo`                                                    |
| `add.py`       | `add`, `import-backup`, `inbox`, `attach`                                      |
| `sync.py`      | `sync`, `sources`, `assets`                                                    |
| `derive.py`    | `derive`, `infer`, `transcribe`, `describe`                                    |
| `day.py`       | `show`, `day`, `digest`, `questions`, `days`, `year`, `search`                 |
| `trips.py`     | `trips`, `trip`                                                                |
| `rollup.py`    | `rollup`, `ledger`                                                             |
| `people.py`    | `people`, `person`                                                             |
| `places.py`    | `places`                                                                       |
| `keepers.py`   | `keepers`                                                                      |
| `promises.py`  | `promises`, `tasks`                                                            |
| `export.py`    | `export`, `import`, `share`, `receive`, `circle`                               |
| `serve.py`     | `serve`, `mcp`                                                                 |

A command is two functions in its family's module: `<command>_arguments(sub)` declares its
arguments and sets `fn=cmd_<command>`; `cmd_<command>(a)` runs it. `parser.py` lists the
`_arguments` functions in the order `logbook --help` shows them. `common.py` holds what the
families share, `skips.py` the phrases for an adapter's counts, `rows.py` the row `show` prints
for one line. A new command goes in the module whose family it belongs to, or a new module when
it starts a family, plus its line in `parser.py`.

`logbook --help` builds every family's arguments and must stay cheap: a family imports an
adapter (`logbook.contrib.adapters.*`) or a model module (`judge`, `describe`, `transcribe`,
`demo_life`) inside the function that runs the command, never at the top of the module, and a
constant the help text needs from one of them is a pinned copy (`tests/test_cli_lazy.py`)."""
