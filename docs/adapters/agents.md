# Your own agents: Telegram bots and Claude Code

You talk to agents of your own: bots you run on Telegram, a coding assistant in Claude Code. Those
conversations are part of the record. Your words in them are yours, at their tier, and read like
anything else you wrote. The agent's words sit beside them, marked as machine text, and no reader
takes them for a person's: an agent is never in `people`, never someone's company, never proposed in
`people review`, and its "I'll have it ready by Friday" is never a promise.

```bash
logbook add telegram-export ~/Downloads/"Telegram Desktop"/DataExport_2026-03-02   # your bot chats, both sides
logbook sync telegram                                                            # what you sent your bots since
logbook add claude-sessions ~/.claude/projects                                   # every Claude Code session on this machine
logbook add claude-sessions ~/.claude/projects --dry-run                         # what would be added; nothing written
```

## The machine mark

No payload profile has a slot for "an agent wrote this", and none is invented for it. The mark rides
in the slots the two frozen profiles already leave for a source's own fields
(`logbook/core/machine.py` reads it, and every reader below goes through it):

| Where | The mark | What it means |
|---|---|---|
| `message/v1` (RFC 0008, whose `extra` keeps anything else a source reports) | `extra.machine: true` | the agent wrote this line |
| `message/v1` | `extra.counterpart: {"kind": "agent", "ref": {kind, value}, "name"?, "username"?}` | the line belongs to a conversation with an agent, whoever wrote it; on every line of it, yours and the agent's |
| `transcript/v1` (RFC 0004, whose consumers ignore a participant's fields they do not know) | a participant `{"name": "assistant", "machine": true}` | that participant is an agent, and every turn under its name is machine text |

The counterpart is an **observed entity of kind `agent`**: what a source saw, keyed by its `ref`
(`provider_id` `telegram:<bot id>` for a bot, `provider_id` `claude-code` for the assistant), never
resolved and never a person. RFC 0037 (draft) names the observed entities a review will one day
place: `person`, `org`, `place`, `asset`, `idea`. `agent` is not among them yet; it is defined here,
by these lines, so that an Agents page, when one exists, reads the same field. Only the literal
`true` marks anything, and a line without the mark is read as it always was.

A tier is where a line may travel, never who wrote it: an agent's message is tier 2 because
`message/v1` is, exactly as your own; a session is tier 2 because `transcript/v1` is.

## Telegram: the export

Telegram Desktop → Settings → Advanced → **Export Telegram data**, *Machine-readable JSON*. Tick
**Bot chats**; nothing else is needed, and the file stays small. A chat's own export (⋮ → Export
chat history, in a bot's chat) has the same shape and is read the same way. The export is a folder
holding `result.json` and the media it downloaded beside it.

`logbook add telegram-export <folder>` (or the folder, or its `result.json`: they are sniffed) reads
every chat of type `bot_chat` and nothing else. A personal chat, a group, a channel and your saved
messages are counted (`chats that are not with a bot, never read`) and never opened, so no person's
words come in through here. Your Telegram chats with people are not read by this adapter.

| Field | From |
|---|---|
| `at` | the message's `date_unixtime`; an export older than that field has only a local time without an offset, read in the record's zone |
| `chat` | `{id: <the bot's user id>, type: direct, name: <the bot's name>}` |
| `from_me` | false for a message from the bot (`from_id` `user<bot id>`), true for every other: a private chat with a bot has two sides. When the export names its owner (`personal_information.user_id`), a message from anyone else is counted and skipped |
| `sender` | for the bot's lines: `{kind: provider_id, value: telegram:<bot id>, name: <bot name>}` |
| `text` | the message's text (or caption) with its formatting dropped |
| `media_kind` | the export's own classification: `image`, `voice`, `video`, `gif`, `audio`, `sticker`, `document`, `location`, `contact` |
| `reply_to` | the key of the message replied to, when the export holds it |
| `edited` | when the export says the message was edited; `extra.edited_at` is when |
| `extra` | `counterpart` (the bot, kind `agent`), `machine` (the bot's lines), `view` `export`, `message_id` (the export's own id), `reply_to_message_id`, `forwarded` and `forwarded_from`, `media` and `media_missing` |

**Media is referenced, never copied.** A file the export holds is named under `extra.media` by its
path in the export (`local_path`, POSIX, resolved by its parts and never outside the folder), its
SHA-256, its size, its media type and file name when the export gives them. A file the export left
out (`(File not included…)`), or a path that would leave the folder, is `extra.media_missing`, and
the line is written all the same. `payload.media` is never set: the bytes are not in the record.

**A forward is not your words.** A message you forwarded to a bot keeps `extra.forwarded` and the
name it came from; `promises` never reads it, since what someone else wrote is not a promise of
yours.

## Telegram: live, `sync telegram`

```bash
export LOGBOOK_TELEGRAM_BOT_TOKENS="<bot id>:<secret>,<bot id>:<secret>"   # BotFather's tokens, your own bots
export LOGBOOK_TELEGRAM_OWNER_ID="<your numeric Telegram user id>"
logbook sync telegram
```

A token can read and send as its bot, so it is a password: it lives in the environment (or
`~/.config/logbook/sync.env` for the schedule), never in the record, never in a line, never printed;
an error names the bot by its id or username, never by its token. The owner id is what makes "a
bot's updates are only its chat with you" a rule rather than a hope: a message from anyone else is
counted (`from someone other than the owner, never written as theirs`) and never written, so a
stranger who finds a bot never speaks in your name. A message outside a private chat is counted too.

`sync telegram` asks each bot three read-only methods, with GET and nothing else: `getMe` (who the
bot is), `getWebhookInfo` (whether its updates go to a webhook, and how many are pending) and, only
when updates are pending and no webhook is set, `getUpdates?timeout=0&limit=100`. It never passes
`offset`, so it never confirms an update and your bot's own program still receives every one; it
never passes `allowed_updates`, which would change what the bot is sent; it never calls
`deleteWebhook`, `getFile` or a method that sends. A test holds it to that.

What that leaves is narrow, and it is worth saying plainly:

- **Only your side.** Telegram never sends a bot its own messages, so the bot's replies never come
  through `sync`; they come through the export.
- **Only what is still pending.** The Bot API keeps an update until the bot confirms it, and for 24
  hours at most. A bot that is running confirms its updates as they arrive, so `sync` finds little
  or nothing; it is for what arrived while the bot was down, and for the edits and replies around it.
- **At most the first 100 pending**, since reading further would need an offset, which confirms.
- **A bot on a webhook is not read**: its updates go to the webhook, and `getUpdates` would be
  refused. It is one line naming the bot, the other bots are read, and `sync` exits 1; `sync` never
  touches the webhook.
- **A bot that long-polls** while `sync` asks may see one `409 Conflict` and retry, as the libraries
  do; a bot with nothing pending is never asked, so a quiet bot is never interrupted.

The complete conversation, both sides, is the export's. `sync telegram` writes the same lines by the
same mapping (`extra.view` is `bot`, `extra.message_id` the bot's own id for the message, the
counterpart with its username from `getMe`) and the same key, so a message the export already wrote
is not written again, and the other way round. There is no watermark: what the API holds is small,
every run reads it whole, and the record's dedupe is the mark. `--since` still leaves out what came
before it.

### Why the key is not the message id

Telegram numbers the messages of a private chat per account: the message you send your bot has one
id in your account (the export's) and another in the bot's (the API's). A key on `(chat, message id)`
would dedupe each view against itself and never one against the other. So `raw_id` is what both
sides see alike:

```
<bot id>/<unix seconds>/<me|bot>/<digest>        e.g. 900000001/1772360100/me/3f1c2a9b0d4e
```

the digest being the first twelve hex characters of the SHA-256 of the text (or caption,
whitespace collapsed, NFC) and of whether the message carries media. The n-th message of one chat
with the same four parts gets `~n` after them (three photos sent as an album, in one second, with no
caption). The view's own id stays under `extra.message_id`.

Two consequences, by design. An **edited message** is keyed by the text it has now, which is what
both views give once the edit is made; when `sync` saw the message before the edit too, the version
first sent is a line of its own, beside the edited one. And the `~n` of a burst is counted within
what one view saw: when `sync` sees only the second photo of an album whose first it never saw, the
two views number it differently and the record holds that photo twice. Both are rare, both leave a
line too many rather than one too few, and a duplicate can be retracted.

## Claude Code: the sessions

Claude Code keeps every session on the machine it ran on, under `~/.claude/projects/`: one folder
per project, named from its working directory (`/Users/ines/code/solvind-log` is
`-Users-ines-code-solvind-log`), one `<session id>.jsonl` per session.
`logbook add claude-sessions <folder>` reads the projects folder, one project's folder or one
session's file, each sniffed, so a bare `logbook add ~/.claude/projects` finds them too.

**Your turns** are the text of the `user` entries. **Never yours**, and never kept as anyone's: a
tool's result (the `tool_result` blocks, the entry's `toolUseResult`), which is the machine's
output; an entry marked `isMeta` (a caveat Claude Code adds) or `isCompactSummary` (the model's own
summary of the conversation, written in the user's role); a slash command and its output; the
interrupt marker. **The assistant's turns** are the `text` blocks of the `assistant` entries; its
thinking is never kept, and an API error is not a turn. A **subagent's** conversation (entries
marked `isSidechain`, and a file named `agent-*.jsonl`), whose "user" is the main agent, is
counted and skipped. An image you pasted is counted and never stored.

| Field | From |
|---|---|
| `kind`, `source`, `tier` | `transcript`, `claude-code`, 2 (RFC 0004's; `--tier` sets another for a run) |
| `at`, `end` | the session's first and last entry |
| `participants` | `[{"name": "owner"}, {"name": "assistant", "machine": true}]`: `owner` is a word every reader takes for you, as `me` |
| `content` | the turns as JSON, `{"turns": [{"speaker", "text"}, …]}`, stored once in the attachment store (SPEC §1.1); its `sha256` is the session's digest |
| `title` | Claude Code's own title for the session (its `summary` entry), else the first line of your first turn |
| `raw_id` | `claude-code:<session id>` |
| `extra` | `session` and `project` (the working directory's last part) and `cwd`, `git_branch`, `version` (Claude Code's), `models`, `tool_calls` and `tools` (the calls by tool name: a count, never what they did or returned), `images`, `words` (`{owner, machine}`), `counterpart` (`{kind: agent, ref: {provider_id, claude-code}, name: Claude Code}`), and the counts every transcript has |

**A session that grew.** A session goes on after an import, or is resumed. Run again, a session
whose text differs from the line standing for it is written as a new line, `raw_id` suffixed `:v2`
(`:v3` …), that `supersedes` the line before (`grown since the last import`); an unchanged session
is the same line and nothing is written. The proposals `promises` read in the old line are read
again in the new one under new ids, so a promise you closed against the old line shows as open
again; close it once more. A session Claude Code copied into a new file when you resumed it is a
second session here, as it is there.

## What the readers do with them

- **`people`, `person`, `rollup people`, drift and the company of a stay** count no line of a
  conversation with an agent, whoever wrote it, and no participant marked machine, whatever its
  name: a bot you named after your sister is still not your sister.
- **`people review`** never observes an agent and so never proposes one, not even by its name; a
  record that held agent lines before this version rebuilds its observed table once.
- **`promises`** reads only your own words in a conversation with an agent: your messages to a bot
  and your turns in a session. A message a bot wrote and a message you forwarded are counted under
  `skipped` (`messages_by_an_agent`, `forwarded_messages`); an agent's turn is dropped before your
  turns are read, and a line inside your own turn that its text gives the agent (`assistant: …`,
  pasted back) is dropped too.
- **The dream** gives the model your messages with an agent marked (`agent` on the counterpart,
  `machine` on what it wrote) and tells it that agents are not people (`dream-day/3`, rule 5); an
  agent's words do not decide the language of your day.
- **`day`, `show` and `search`** list and find these lines like any other: an agent's message is a
  message of the day, and a session a transcript of it.
