### Fixed
- `logbook serve` never hangs: a page reads for at most `--limit` seconds (15 by default) and is then
  built in the background, said in one sentence; at most two pages are read at once; a browser that
  leaves stops its reading, and a broken pipe is no longer a traceback; an idle connection is closed.
- A page read while a sync writes reads the record up to the last indexed line instead of rebuilding
  the whole index from under the sync.
- `serve --status` says "not answering" for a server that takes the connection and says nothing for
  5 s, with the command that restarts it; the server's own watchdog leaves for its service manager to
  start it again, and the scheduled run restarts a service that does not answer. `kill -USR1` writes
  every thread's stack to the server's log.

### Added
- CI moves the tag `stable` to each commit of `main` whose every check passed; a machine that updates
  itself installs `@stable` (docs/install.md, "Following stable").
