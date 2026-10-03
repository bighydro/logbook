"""The commands of `logbook`, one family per module; `logbook/cli.py` is the entry point.

| module        | commands                                                                  |
|---------------|---------------------------------------------------------------------------|
| `record.py`   | `init`, `stats`, `index`, `verify`, `doctor`, `backup`, `migrate`, `retract`, `repair`, |
|               | `demo`                                                                    |
| `add.py`      | `add`, `import-backup`, `inbox`                                           |
| `sync.py`     | `sync`, `sources`, `assets`                                               |
| `derive.py`   | `derive`, `infer`, `transcribe`                                           |
| `day.py`      | `show`, `day`, `digest`, `days`, `year`                                   |
| `people.py`   | `people`, `person`                                                        |
| `places.py`   | `places`                                                                  |
| `rollup.py`   | `rollup`                                                                  |
| `trips.py`    | `trips`                                                                   |
| `keepers.py`  | `keepers`                                                                 |
| `promises.py` | `promises`                                                                |
| `export.py`   | `export`                                                                  |
| `serve.py`    | `serve`, `mcp`                                                            |

A command is two functions in its family's module: `<command>_arguments(sub)` declares its
arguments and sets `fn=cmd_<command>`; `cmd_<command>(a)` runs it. `parser.py` lists the
`_arguments` functions in the order `logbook --help` shows them. `common.py` holds what the
families share, `skips.py` the phrases for an adapter's counts, `rows.py` the row `show` prints
for one line. A new command goes in the module whose family it belongs to, or a new module when
it starts a family, plus its line in `parser.py`; `cli.py` re-exports a name only when something
outside this package imports it."""
