### Added
- `claude-export`: `logbook add claude-export <zip>` reads the Claude apps' data export (Settings → Privacy
  → Export data; the zip as it came, the folder it unpacks to, or its `conversations.json`) → one
  `transcript/v1` line per conversation in the shape and tier of a Claude Code session: your turns as
  `owner` and the assistant's as a participant marked machine, the text stored once under its digest,
  words counted per side; the conversation's id, its name as the title, its project's name and its created
  and updated times under `extra`. Files you gave or uploaded are named and counted, never copied (the text
  the apps extracted from them never read); tool calls counted by name, their input and output never kept;
  thinking never kept; `users.json` never opened; only the branch a conversation stands on when the export
  links its messages; the thinking and the artifacts an older export writes inline are dropped, never kept.
  A conversation that grew is a `:v2` line that supersedes the one before; an unchanged one writes nothing,
  nor does an export older than one already imported; a malformed one is skipped and counted; `--dry-run`
  says how many conversations, new, grown, unchanged and older. `people`, `promises` and the dream read
  these lines as they read Claude Code's: your words count, the assistant's never
  (`docs/adapters/agents.md`).

### Fixed
- `promises` never reads a line you pasted back into your own turn under an agent's own name
  (`Claude: …`, `Claude Code: …`) as your promise: it is the agent's, as a line under `assistant:` already
  was.
- `claude-sessions`: an older copy of a session (a backup, an earlier export) added after a newer one is
  never written back over it; it writes nothing, as an unchanged session does.
