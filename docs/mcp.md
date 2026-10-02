# The MCP server

`logbook mcp` serves your record to an agent on this machine over the [Model Context
Protocol](https://modelcontextprotocol.io): the host (an editor, a chat client, an agent runner) starts
`logbook mcp` as a child process and calls its tools over that process's own stdin and stdout. That is the
only transport. Nothing listens on a port, no socket opens, and the record stays where it is. The agent asks;
the readers answer; the two things it may write go through `Logbook.append` like everything else.

```bash
pip install "openlogbook[mcp]"      # the official Python MCP SDK, the one optional dependency
logbook mcp --inspect               # the tool table and one sample request; needs no record and no SDK
logbook mcp                         # serve the record `logbook` finds (LOGBOOK_HOME, the folder above, ~/Logbook)
logbook mcp --root ~/Logbook        # or this one
logbook mcp --allow-tier-3          # let tier 3 cross when policy/crossing.json allows it for mcp (below)
```

## Pointing a host at it

Every MCP host takes the same three things: a command, its arguments and the environment it runs in. For a
generic host that keeps its servers in a JSON file:

```json
{
  "mcpServers": {
    "logbook": {
      "command": "logbook",
      "args": ["mcp"],
      "env": { "LOGBOOK_HOME": "/Users/you/Logbook" }
    }
  }
}
```

`LOGBOOK_HOME` names the record, as it does for every other command; `--root` in `args` does the same.
A host that cannot find `logbook` on its own path gets the full path from `which logbook`, or runs it through
`uv`: `"command": "uv", "args": ["run", "logbook", "mcp"]` with `"cwd"` set to the checkout. Give the host
the environment the record needs and nothing more: no adapter key is read here, and none should be in reach.

## The tools

Nine read tools and two write tools. Each read tool is one command you already know, with the same output
as its `--json`:

| Tool | Arguments | The command |
|---|---|---|
| `day` | `date?` (YYYY-MM-DD; default today) | `logbook day --json` ([the Day](day.md)) |
| `days` | `from?`, `to?` (both default to the days the record covers) | `logbook days --json`, one object per day |
| `trips` | `year?` | `logbook trips --json` |
| `places` | | `logbook places list`: `places.json`, one object per named place |
| `people` | | `logbook rollup people --json` |
| `person` | `name` | `logbook show person <name> --json` |
| `promises` | `open?`, `since?` | `logbook promises --json` ([promises](promises.md)) |
| `gaps` | `since?` | `logbook sources --gaps --json` |
| `search` | `text`, `since?`, `until?`, `kinds?`, `limit?` | lines whose payload mentions `text`, through the index |
| `add_note` | `text`, `at?` | `logbook add "<sentence>"`: one `note/v1` line, tier 2 |
| `promise_done` | `id` | `logbook promises done <id>`: one `task/v1` line |

`search` is the one tool with no command of its own. It cuts the window (`since` and `until` are local days,
inclusive) and the kinds in the index, reads the standing lines in chain order, and keeps those whose payload
contains `text` anywhere, case aside — a note's words, an event's title, a mail's subject, a URL. Each hit is
the line's envelope and payload without `prev` and `hash`; at most `limit` (50 by default, 500 at most), and
`more` says when there were more. A retracted line is never a hit, and neither is a retraction.

Every answer is one JSON text:

```json
{"data": …, "gate": {"destination": "mcp", "max_tier": 1, "withheld": 23}}
```

`data` is the tool's output. `gate` is what the next section is about: the ceiling the answer was read under,
and how many lines of the record were left out of it because they sit above that ceiling. A client that sees
`withheld` above zero knows the answer is a partial one and can say so.

## The ceiling (ADR 0016)

Every tool's output passes the crossing gate. `policy/crossing.json` — the file that already says how much may
cross to each member of your circle — names the `mcp` destination and the highest tier it may receive:

```json
{"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}}
```

`logbook init` writes it at 1. A record made before this version, whose file does not name `mcp`, has a
ceiling of 1 as well: the one destination with a default, since the client is an agent on your own machine
and tier 1 is what crosses on its own. Raise it by editing the file; the server reads it on every call and
never writes it, so the change takes effect at the next call and nothing needs restarting.

What the ceiling means in practice:

- **At 1** the agent sees locations, calendar entries, photos, calls, flights, trips and crossing lines: the
  record's shape. It does not see notes, messages, mail, transcripts or the resolution lines that name people,
  so `people` and `promises` are empty, `person` knows nobody, and a Day names no company. A display name a
  calendar entry carries is that entry's own content and crosses with it; the overlay that would resolve it
  stays home, as it does for an export.
- **At 2** notes, messages, mail, transcripts, tasks and the names of your circle cross too. This is the
  ceiling to set for an agent that is to work with your notes, your people and your promises.
- **At 3** health samples and money cross as well — and only when you also started the server with
  `--allow-tier-3`. A policy edit alone never lets tier 3 through, as it never does for `logbook export
  crossing`; without the flag, 2 is the most, whatever the file says.

A line above the ceiling is left out *before* anything is derived from it, not blanked out afterwards: the
readers see the record as if the line were not there, so a tier-2 note is not in the Day's attachments, not
in the promises, not in the search, and not in the count of lines a stay carries. The only line that passes
whatever its tier is a retraction — a mark on another line, needed so that line stays hidden — and no tool
ever returns one. The policy file that is not what it should be (an `mcp` entry with no tier of 1, 2 or 3)
is one error naming the file, for every call, until it is fixed.

Two things the gate does not do. It does not append a `crossing/v1` line: an export hands a bundle to someone
else and the record keeps the receipt; a tool call answers a question on this machine, and the record is not
the place to log an agent's every question. And it does not change what the two write tools write: `add_note`
is tier 2 whatever the ceiling, as `logbook add` is, so at a ceiling of 1 the agent writes notes it cannot
read back. The answer says so (`readable: false`), and `logbook show` reads them as ever.

## The write tools

`add_note` appends one `note/v1` line — source `manual`, tier 2, `at` the instant given (RFC 3339 with a zone)
or now — exactly as `logbook add "<sentence>"` does. `promise_done` appends the `task/v1` line that marks one
proposal of `promises` done, exactly as `logbook promises done <id>` does, and writes nothing for a proposal
already done. Both return the envelope of the line written (`seq`, `id`, `at`, `kind`, `tier`), never its
payload. Nothing else writes, and nothing is ever rewritten: `verify` is green after every call, and the index
is extended as a line is appended, as it is for every writer.

The ARCHITECTURE's rule that an agent is an operator, not an author, holds here in the way it holds for the
command line: the agent types what you told it to, under your name, and the line says `manual`. Whether a host
may call a write tool at all is the host's setting, not the server's; most hosts ask before a tool that
writes, and `--inspect` marks the two that do.

## Testing it

The tests (`tests/test_mcp.py`) drive the server through the SDK's in-process client over the synthetic Oslo
persona: no child process, no socket. They pin the tool list and its schemas, the gate at 1 and 2 (a tier-2
note must not appear at a ceiling of 1), tier 3 behind the flag, a retracted line staying hidden, a broken
policy as one error, every reader answering and writing nothing, and the two writers appending one line each.
`logbook mcp --inspect` is the hand check: the table, and a request you can paste.
