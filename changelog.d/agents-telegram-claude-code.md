### Adapters
- `telegram`: `logbook add telegram-export <folder>` reads Telegram Desktop's JSON export of your bot chats
  (and nothing else: a chat with a person, a group or a channel is counted and never read) → one
  `message/v1` line per message, your words as yours and the bot's marked `extra.machine`, the bot as
  every line's counterpart (`extra.counterpart`, an observed entity of kind `agent`), media referenced by
  its path and digest and never copied, a forward marked as one. `logbook sync telegram` reads your own
  bots over the Bot API (`LOGBOOK_TELEGRAM_BOT_TOKENS`, `LOGBOOK_TELEGRAM_OWNER_ID`), read-only: `getMe`,
  `getWebhookInfo`, and `getUpdates` only when something is pending, never an offset (no update is
  confirmed, so your bot still gets every one), never a method that sends or changes; a message from
  anyone but you is counted and never written; a bot on a webhook is one line and is left alone. Both
  write the same line under one key, since Telegram gives one message two ids, yours and the bot's.
- `claude-code`: `logbook add claude-sessions ~/.claude/projects` → one `transcript/v1` line per Claude
  Code session, your turns as `owner` and the assistant's as a participant marked machine, the text stored
  once under its digest; tool calls counted by name and their output never kept, nor a subagent's
  conversation, a compaction summary or thinking; words counted per side; the session, project and
  working directory under `extra`. A session that grew is a `:v2` line that supersedes the one before.

### Changed
- An agent is never a person (`docs/adapters/agents.md`): `people`, `person`, drift, the company of a stay
  and `people review` pass over a conversation with one of your agents and a transcript participant marked
  machine, whatever its name; `promises` reads only your own words in it (a bot's message and a forwarded
  one are counted under `skipped`); the dream marks an agent's words for the model and its prompt says
  agents are not people (`dream-day/3`).
