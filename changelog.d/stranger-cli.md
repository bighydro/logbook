### Fixed
- `doctor`'s `extra:*` hints add the missing extra to this Logbook exactly as it is installed, or print
  no line (#334): this venv's pip (uv's pip in a venv uv made) at the installed version; `pipx runpip`
  in the venv pipx made, which keeps its Python, its options and its suffix; `uv tool install --force`
  on the Python running now, at the installed version or git commit, with every extra already there,
  the index options and each companion at its installed version; in a checkout, `uv sync --inexact
  --no-default-groups` on the Python running now, which removes nothing and brings back no group. It
  prints no line and says in one sentence why and where in docs/install.md to read under Homebrew,
  beside a receipt it cannot read or one naming a password or token, where uv's receipt names another
  Python, where the source may have changed since (a folder, a URL, a wheel), outside a venv, and
  under `uvx` or `uv run --with`, whose environment is uv's cache.
- `setup` never adopts the demo record: it says it is the demo, how to make your own (`unset LOGBOOK_HOME`,
  then `logbook setup`) and exits 2 without writing. `logbook demo` marks the record it writes (`"demo"` in
  `logbook.json`); a demo 0.7.0 wrote is known by its owner (#334).
- `init` on a folder that holds a record says so in one sentence and exits 2, never a traceback; with no
  path it makes the record where `LOGBOOK_HOME` points, as every other command finds it (#334).
- `doctor`'s hints name the current commands (`logbook repair index`, `logbook setup places add …`) (#334).
- `logbook --help` says where a newcomer starts; `dream` names `person`; `init --help` describes `path` and
  `--timezone` (#334).
- `show person` counts the open promises with the person (`logbook promises` lists them), or says none
  open, in place of a note about RFC 0007; the MCP `person` tool gives the same counts and command, under
  its ceiling, never a promise's words (#334).
- `demo --out` on a record says which `--out` to pick, and that an earlier demo may be removed (#334).
- `setup`'s timezone question says in words which zone Enter takes and that the other is an example; `setup
  places propose --top N` prints the total and how many it shows (#334).
