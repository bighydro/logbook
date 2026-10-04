### Changed
- One package, three tiers: the modules of `logbook` now live under `logbook/core/` (the format and the
  readers a second implementation is held to), `logbook/contrib/` (the adapters, import-backup, sync,
  the exports, the derived readers whose output is a reader's own) and `logbook/labs/` (everything that
  runs a model), with the commands one module per family under `logbook/commands/`. Nothing a user runs
  changes: every command prints the same bytes. Every 0.5 import path (`logbook.store`,
  `logbook.adapters.immich`) still imports the same module, with a DeprecationWarning, until 0.7;
  `docs/migration-0.6.md` lists the moves. `logbook --help` loads no adapter and no model code, and
  `import logbook.cli` is thirteen times cheaper than before.
- `ijson` is the extra `openlogbook[stream]`, not a dependency: the five adapters that stream a large JSON
  export import it when they read one, and `logbook add` names the extra when it is missing. `[share]` is
  an alias of `[encrypted]`: either installs `cryptography`. The `logbook.adapters` entry points list every
  built-in adapter, in the registry's order, and a test keeps the two lists equal.
