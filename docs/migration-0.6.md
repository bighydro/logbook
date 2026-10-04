# Migrating to 0.6: one package, three tiers

0.6 keeps one package, `logbook` (the distribution is still `openlogbook`, the command is still
`logbook`), and sorts its modules into three tiers under it: `logbook/core/` (the format and the
readers a second implementation is held to), `logbook/contrib/` (the adapters, the imports, the
exports, the derived readers whose output is a reader's own) and `logbook/labs/` (everything that
runs a model). The commands live under `logbook/commands/`, one module per family, and `cli.py`
is a thin entry point. [ARCHITECTURE.md](ARCHITECTURE.md) describes the tree; `logbook/layout.py`
declares it, and `tests/test_layout.py` holds the tree to the table.

Nothing a user runs changes: every command, flag and help text prints the same bytes, the
conformance head is the same, and the record is untouched. What changes is where code imports
from.

## The old import paths work until 0.7

Every module path 0.5 had still imports. `import logbook.store` imports `logbook.core.store` and
registers that same module object under the old name, so there is one copy of every module, a
patch through either name lands on it, and `logbook.store is logbook.core.store`. The first import
of each old path warns once, a `DeprecationWarning` attributed to the line that imported it. The
old names go in **0.7**.

To find them in your code, make the warning an error once:

```sh
python -W error::DeprecationWarning -c "import your_module"
pytest -W error::DeprecationWarning
```

The shim is `logbook/_shim.py`, a finder on `sys.meta_path` installed when `logbook` is imported;
the table it reads is `logbook.layout.MOVED`. A type checker does not see the old paths: it
resolves `logbook.core.store`, not `logbook.store`.

## The 62 moves

| 0.5 | 0.6 | |
|---|---|---|
| `logbook.apps` | `logbook.core.apps` |  |
| `logbook.assets` | `logbook.core.assets` |  |
| `logbook.attachments` | `logbook.core.attachments` |  |
| `logbook.chain` | `logbook.core.chain` |  |
| `logbook.countries` | `logbook.core.countries` |  |
| `logbook.crossing` | `logbook.core.crossing` |  |
| `logbook.day` | `logbook.core.day` |  |
| `logbook.days` | `logbook.core.days` |  |
| `logbook.drifting` | `logbook.core.drifting` |  |
| `logbook.events` | `logbook.core.events` |  |
| `logbook.export` | `logbook.core.export` |  |
| `logbook.flights` | `logbook.core.flights` |  |
| `logbook.health` | `logbook.core.health` |  |
| `logbook.index` | `logbook.core.index` |  |
| `logbook.keepers` | `logbook.core.keepers` |  |
| `logbook.ledger` | `logbook.core.ledger` |  |
| `logbook.listen_rollup` | `logbook.core.listen_rollup` |  |
| `logbook.pages` | `logbook.core.pages` |  |
| `logbook.people` | `logbook.core.people` |  |
| `logbook.places` | `logbook.core.places` |  |
| `logbook.policy` | `logbook.core.policy` |  |
| `logbook.present` | `logbook.core.present` |  |
| `logbook.reading` | `logbook.core.reading` |  |
| `logbook.repair` | `logbook.core.repair` |  |
| `logbook.resolve` | `logbook.core.resolve` |  |
| `logbook.rollup` | `logbook.core.rollup` |  |
| `logbook.sealing` | `logbook.core.sealing` | tiers 2–3 sealed at rest (RFC 0029), new on main while 0.6 was built |
| `logbook.search` | `logbook.core.search` |  |
| `logbook.share` | `logbook.core.share` |  |
| `logbook.stays` | `logbook.core.stays` |  |
| `logbook.store` | `logbook.core.store` |  |
| `logbook.story` | `logbook.core.story` |  |
| `logbook.trips` | `logbook.core.trips` |  |
| `logbook.weather` | `logbook.core.weather` |  |
| `logbook.year` | `logbook.core.year` |  |
| `logbook.adapters` | `logbook.contrib.adapters` | and every adapter under it (`logbook.adapters.takeout.maps` is `logbook.contrib.adapters.takeout.maps`) |
| `logbook.asset_status` | `logbook.contrib.asset_status` |  |
| `logbook.attach` | `logbook.contrib.attach` |  |
| `logbook.backup` | `logbook.contrib.backup` |  |
| `logbook.demo` | `logbook.contrib.demo` |  |
| `logbook.digest` | `logbook.contrib.digest` |  |
| `logbook.doctor` | `logbook.contrib.doctor` |  |
| `logbook.gaps` | `logbook.contrib.gaps` |  |
| `logbook.inbox` | `logbook.contrib.inbox` |  |
| `logbook.ios_backup` | `logbook.contrib.ios_backup` |  |
| `logbook.ios_backup_crypto` | `logbook.contrib.ios_backup_crypto` |  |
| `logbook.mcp_server` | `logbook.contrib.mcp_server` |  |
| `logbook.people_merge` | `logbook.contrib.people_merge` |  |
| `logbook.print_layout` | `logbook.contrib.print_layout` |  |
| `logbook.print_page` | `logbook.contrib.print_page` |  |
| `logbook.promises` | `logbook.contrib.promises` |  |
| `logbook.questions` | `logbook.contrib.questions` |  |
| `logbook.schedule` | `logbook.contrib.schedule` |  |
| `logbook.serve` | `logbook.contrib.serve` |  |
| `logbook.taskdone` | `logbook.contrib.taskdone` |  |
| `logbook.trip_bundle` | `logbook.contrib.trip_bundle` |  |
| `logbook.trip_page` | `logbook.contrib.trip_page` |  |
| `logbook.vault` | `logbook.contrib.vault` |  |
| `logbook.demo_life` | `logbook.labs.demo_life` |  |
| `logbook.describe` | `logbook.labs.describe` |  |
| `logbook.judge` | `logbook.labs.judge` |  |
| `logbook.transcribe` | `logbook.labs.transcribe` |  |
| `logbook.setup` | `logbook.commands.setup` | the wizard drives the commands, so it lives with them |

`logbook.adapters` moves whole: the registry (`logbook.contrib.adapters`) and every adapter module
under it, the Google Takeout sub-adapters included. The entry-point group third-party adapters
register under is still `logbook.adapters`; its name did not change, only the package behind it.

## The names that lived in `logbook.cli`

`logbook/cli.py` held every command. The commands now live in `logbook/commands/`, one module per
family (`record`, `add`, `sync`, `derive`, `day`, `trips`, `rollup`, `people`, `places`, `keepers`,
`promises`, `export`, `serve`; `common`, `skips` and `rows` for what they share; `parser` for the
help order). `logbook.cli.main` stays. Any other name `logbook.cli` had (`cmd_show`, `record_stats`,
`SKIP_PHRASES`, `_tz_default`, ...) still resolves, found in its family's module with a
DeprecationWarning that names where it lives now, and goes in 0.7.

That lookup hands back the family's binding, so a test that patched `logbook.cli.<name>` must
patch the family module instead (`monkeypatch.setattr(logbook.commands.record, "_LOCALTIME", ...)`):
patching the attribute on `logbook.cli` changes nothing the command sees.

## Extras

`openlogbook[encrypted]` and `openlogbook[share]` are one extra under two names (`cryptography`);
either installs the same thing. `ijson`, which five adapters stream large JSON exports with, is no
longer a dependency of the package but the extra `openlogbook[stream]`; an adapter that needs it
and does not find it says so by name, and nothing else is affected.
