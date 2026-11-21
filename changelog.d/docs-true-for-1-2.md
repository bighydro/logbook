### Documentation
- The install page names no version: every line installs the newest release, a screen it shows writes
  `X.Y.Z` for the number, and the extras lines pin through `$(logbook --version)`. `pipx inject` gains the
  `--force` without which pipx sees `openlogbook` installed and changes nothing.
- The home server installs the release with `uv tool`; installing from the repository is an aside for
  developers, from the `stable` tag.
- The docs use today's command names (`logbook show year`, `logbook serve mcp`, `logbook import backup`,
  ...) where they used the old ones, which still run; a page about a renamed command says the old name
  once. A test holds every command, subcommand, flag and repository path the README, the docs and the
  changelog fragments name to the parser.
