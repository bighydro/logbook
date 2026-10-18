# The MCP server

`logbook mcp` serves your record to an agent on this machine over the [Model Context
Protocol](https://modelcontextprotocol.io): the host (an editor, a chat client, an agent runner) starts
`logbook mcp` as a child process and calls its tools over that process's own stdin and stdout. That is the
only transport. Nothing listens on a port, no socket opens, and the record stays where it is. The agent asks;
the readers answer; what it may write goes through `Logbook.append` like everything else, and two of those
writes only when you allow them by name ([below](#write-tools)).

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

Twelve read tools, two write tools, and two more write tools that are refused until your policy names them
([Write tools](#write-tools)). Each read tool is one command you already know, with the same output
as its `--json` (or, for the three that read the lines themselves, as its text):

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
| `day_lines` | `day?` (default today), `kinds?` | `logbook show DAY`, one object per line ([below](#the-lines-themselves)) |
| `line` | `id` | one line in full, a transcript's text included ([below](#the-lines-themselves)) |
| `digest` | `period?` (`day`, `week`), `date?` | `logbook digest DATE`, the text as printed ([below](#the-lines-themselves)) |
| `add_note` | `text`, `at?` | `logbook add "<sentence>"`: one `note/v1` line, tier 2 |
| `promise_done` | `id` | `logbook promises done <id>`: one `task/v1` line |
| `sign_day` | `day`, `confirm?`, `kept?`, `missed?`, `dropped?`, `carried?`, `note?`, `at?` | `logbook day sign DAY`: one `signed-day/v1` line, tier 1; a day signed before keeps its confirmations; only when the policy names it |
| `note_day` | `day`, `text`, `at?`, `kind?` | one `note/v1` line on `day`, tier 2, source `mcp`; only when the policy names it |

`search` is a scan, not the ranked search `logbook search` is ([search](search.md)). It cuts the window
(`since` and `until` are local days, inclusive) and the kinds in the index, reads the standing lines in chain
order, and keeps those whose payload contains `text` anywhere, case aside — a note's words, an event's title, a
mail's subject, a URL. Each hit is the line's envelope and payload without `prev` and `hash`; at most `limit`
(50 by default, 500 at most), and `more` says when there were more. A retracted line is never a hit, and
neither is a retraction.

### The lines themselves

`search` finds a line by a word; the three tools here read the lines without one, so an agent can read a
day, open a line, and get the evening's digest, as the owner does at the command line. Each one's
description, as the host lists it, says in one sentence what the ceiling does to its answer.

- **`day_lines(day?, kinds?)`** is `logbook show DAY`, one object per standing line, in time order (the
  instant, then `seq`, SPEC §3.2): `id`, `seq`, `at`, `end`, `time` (the local clock), `kind`, `profile`
  (`payload.schema`), `source`, `tier`, `counterpart` and `text`. The text is the text part of the row
  `show` prints: a note's first line, `✉ subject — sender`, `who: message`, `title — participants; 12
  turns, 25 min`. The counterpart is whom the line is with, as the record names them: a mail's sender (its
  recipients for one you sent), a message's sender or chat, a transcript's participants, an entry's
  attendees, a call's counterparty; `null` for a location point or a photo. `kinds` keeps only these
  profile families: `mail`, `message`, `transcript`, `note`, `location`, `photo`, `calendar` (the
  `event/v1` lines). A retracted line is left out and counted in `retracted`; a retraction is never a row.
  *Lines above the ceiling are left out and counted in `above_ceiling`, and nothing of them crosses, not
  even an id*: the count comes from a query that reads nothing else of them.
- **`line(id)`** is one line in full: the fields `day_lines` gives, the row `show` prints as `row`, the
  whole `payload`, and `text`, the line's full text where it has one — a note's, a mail's body, a
  message's, and a transcript's turns read from the attachment store as `promises` and the search index
  read them, one `Speaker: text` per turn (`null` when the store does not hold the file, and for a home
  video's soundtrack, which is no call: [its words go to no model](adapters/videos.md)). A retracted line
  is the marker `show` prints, `retracted #seq: reason`, and nothing of the line. *A line above the ceiling
  is refused naming its tier and the ceiling, and nothing else of it*: the index is asked the line's tier
  first, by a query that reads nothing else, and the refusal is `line '…' is tier 3, above the mcp ceiling
  of 2`.
- **`digest(period?, date?)`** is the text `logbook digest DATE` prints ([the digest](digest.md)), line for
  line, under `text`, with `lines` counted; `period` `week` is the seven digests of the ISO week that holds
  `date`, Monday to Sunday, each as the command prints it, a blank line between, with the week under
  `week` and the days digested under `days` (a day that has not come is left out of a week, and refused
  for a day, as the command refuses it). *The digest is read under the ceiling as every reader is: a line
  above it is in no part of it, where, with whom, what attached, the promises due or the question, as if
  it were not in the record* — so the digest at a ceiling of 1 is the digest of a record that holds only
  tier 1, and the test holds it to exactly that. The question bank and the state of what was asked are
  files beside the record, written as the command writes them; the record itself is untouched.

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

Who may read, and from where, is [ADR 0022](adr/0022-the-records-home.md): the server runs on the record's
home, the one machine that holds the writable copy, and an agent anywhere else (a VPS, a cron, a phone)
reaches the record only through this ceiling and the few write tools you allow by name. A cloud model or
service that may see record content gets its own entry in the file, and a temporary one an `until` date:
`{"cloud-model": {"max_tier": 2, "until": "2026-12-31"}}` holds through that day and counts as tier 0 from
the next, so nothing crosses until you write a new date or remove the line; `logbook doctor` names an
entry that has expired. The `dream` entry is one of these: `logbook dream` sends a day to a model only
through `{"dream": {"max_tier": 2, "until": "2026-12-31", "model": "qwen2.5-7b-instruct"}}`, the one
model named there when it names one ([the dream](dream.md)), and `logbook transcript synthesize` sends a
call through the same entry ([the synthesis of a call](transcript-synthesis.md)). What they wrote follows
that entry as well as this one: a `draft` line, a day's draft or a call's synthesis, above the `dream`
entry's `max_tier` today (lowered, expired or removed since it was written) is held back from every tool
as a line above the ceiling is, and counted with them; `line` refuses it naming the entry (ADR 0016,
*Derived material follows the policy, not the head*). A person's draft (`dream person`) is written under the
`relationship` entry instead, and is held to that one the same way: past its `until`, or above its
`max_tier`, it is held back and counted, whatever the `dream` entry allows.

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
is one error naming the file, for every call, until it is fixed. A file that is not JSON is the same
error; neither is ever read as a higher ceiling, and a file that is missing, or names other destinations and
not `mcp`, is the ceiling of 1.

Two things the gate does not do. It does not append a `crossing/v1` line: an export hands a bundle to someone
else and the record keeps the receipt; a tool call answers a question on this machine, and the record is not
the place to log an agent's every question. And it does not change what the two write tools write: `add_note`
is tier 2 whatever the ceiling, as `logbook add` is, so at a ceiling of 1 the agent writes notes it cannot
read back. The answer says so (`readable: false`), and `logbook show` reads them as ever.

## The log

The server writes one line per call on the `logbook.mcp` logger, on stderr (stdout is the transport): the
tool's name, the arguments that are a day, an id, a window or a switch, and the counts of the answer — `day_lines
day=2026-06-10 kinds=note,transcript lines=3 count=3 above_ceiling=1 retracted=0 withheld=4`, `line
id=019c… withheld=0`, or `refused: line '019c…' is tier 3, above the mcp ceiling of 2`. Never a line's
content, never a search's words, never a name: an argument that is text (`search`'s `text`, `person`'s
`name`, `add_note`'s and `note_day`'s `text`, `sign_day`'s ids and `note`) is not logged. A write tool's line
is the tool, the day, and counts: `note_day day=2026-06-09 kind=proposal seq=812 tier=2 chars=41 withheld=0`,
`sign_day day=2026-06-09 seq=813 tier=1 confirmed=14 on_page=15 withheld=0`.

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
writes, and `--inspect` marks the ones that do.

## Write tools

ADR 0022 says it in one sentence: *orchestrators reach the record only through the crossing: read tools under
the ceiling, and the few write tools the owner allows by name.* An orchestrator that builds the Day page used
to print a `day sign` command for you to run by hand, and your verdicts on its proposals lived outside the
record. With the two tools here, the proposals and your verdicts become lines, and the Day page can be rebuilt
from the record alone.

Neither is allowed until the `mcp` entry of `policy/crossing.json` names it under `write`:

```json
{"mcp": {"max_tier": 1, "write": ["sign_day", "note_day"], "write_window_days": 60}}
```

- No `write`, an empty one, or no `mcp` entry at all: no write tool is allowed. Each is refused with one
  sentence, `sign_day is not allowed through the door: the mcp entry of policy/crossing.json does not name it
  under "write"`, and nothing is written. An empty list is a fine place to stay: your own way to reflect and
  sign is the Day page of `logbook serve` ([Reflect and Sign](serve.md#reflect-and-sign)), which never reads
  this file; the door is for an orchestrator elsewhere.
- An entry past its `until` day allows none, whatever it names.
- `write` names only `sign_day` and `note_day`; anything else in it is one error naming the file, for every
  call, as a broken ceiling is.
- `write_window_days` (60 when absent) is how far back the door writes: a day from that many days before today
  through today, in the record's zone, and no other. A day outside it is refused naming the window.
- `--allow-tier-3` has no effect on either. Neither writes above the tier its profile fixes: `sign_day`
  writes `signed-day/v1` at tier 1, `note_day` writes `note/v1` at tier 2 (RFC 0010 makes a note tier 2,
  whoever writes it), and nothing else.

`logbook doctor` shows the tools on its crossing line (`mcp 1 write sign_day,note_day`), and `logbook serve mcp
--inspect` lists them, marked `[writes one line; only when the policy names it]`.

**`sign_day(day, confirm?, kept?, missed?, dropped?, carried?, note?, at?)`** is `logbook day sign DAY` through
the same code, `signing.sign`, with no second implementation: `confirm` is a list of ids or seqs on the page,
`"all"` or `"none"` (each goes alone); the four dispositions are lists of ids or seqs (RFC 0034 amendment 1); `note`
is one line; `at` is the moment you signed, with the same rules as `--at` (amendment 2). The ids are checked
against the page as the command checks them, and a day already signed is signed again, the new line
superseding the old and, without `confirm`, keeping what the old one confirmed, its dispositions and its note
(RFC 0034 amendment 4): a line added to the day since stays unconfirmed, so a re-sign through the door never
confirms a line the owner was not shown; `"all"` confirms the page's lines the door can show, those at or
under its ceiling, and leaves every line above it unconfirmed (RFC 0034 amendment 4, 18 October 2026), since
the orchestrator was never shown them: the answer says how many in `unconfirmed`, `2 lines above the door's
ceiling left unconfirmed`, and `above_ceiling`, a count and never their content (`day sign --confirm all` and the
Library's Sign still confirm the whole page, which the owner sees there). The line is byte for byte what `day sign` writes with the same flags and `--at` (for `"all"`, `--confirm` with the ids it confirmed), source
`manual` included: the signature is yours, carried by the orchestrator. The page signed is the whole page, as
`day sign` signs it, lines above the ceiling included, which the orchestrator cannot read; the answer is the
line's envelope, `header` (the first line `day sign` prints, `2026-06-09: signed 2026-06-09T19:30:00Z as #813
signed-day/v1`), `kept` (what was kept from the signature it supersedes, the sentence `day sign` prints, or
null), and counts: `confirmed`, `on_page`, `dispositions` per word, `above_ceiling` (with `unconfirmed`, null
unless `"all"` left a line above the ceiling unconfirmed), and `supersedes`.

**`note_day(day, text, at?, kind?)`** appends one `note/v1` line: source `mcp`, tier 2, the text exactly as
given, never filtered or trimmed, at most 4000 characters (`NOTE_MAX`; a longer one is refused and nothing is
written). `kind` is one of `note` (the default), `proposal` and `reflection`, carried in the profile's own
slot for a label, `labels: [kind]` (RFC 0010), so a proposal an agent made and the note it came with are told
apart without a new profile. `at`, when given, follows `--at`'s rules and must fall on `day` in the record's
zone; without it the note is now for today and 23:59 of the day for an earlier one. It writes through the
same note path as `logbook day reflect` (`logbook/core/notes.py`), so a reflection carried through the door and
one said at the command line are the same kind of line, but for `source`. The answer is the line's
envelope with `readable` (false at a ceiling of 1: the agent wrote a note it cannot read back), `label` and
`chars`.

Both hold the writer lock for the whole call, like any command that writes, and neither waits for it: when
another writer holds it the call is refused with `another logbook command is writing to this record (logbook
sync, since …); the door does not wait for another writer, so nothing was written`, and the orchestrator tries
again later. `sign_day` reads the head again before it appends, and when it has moved the call is refused with
`the record's head moved … nothing was signed`; neither tool ever retries on its own.

## Testing it

The tests (`tests/test_mcp.py`) drive the server through the SDK's in-process client over the synthetic Oslo
persona: no child process, no socket. They pin the tool list and its schemas, the gate at 1 and 2 (a tier-2
note must not appear at a ceiling of 1), tier 3 behind the flag, a retracted line staying hidden, a broken
policy as one error, every reader answering and writing nothing, and the two writers appending one line each.
`tests/test_mcp_read_tools.py` drives `day_lines`, `line` and `digest` over three synthetic days with lines at
tiers 1, 2 and 3 across location, calendar, note, mail, message, transcript and health: at each ceiling
`day_lines` returns exactly the allowed lines with the right `above_ceiling` and no field of an omitted one,
`line` of a tier-3 transcript refuses at 2 naming the tier and returns the text at 3, and `digest` at each
ceiling matches, line for line, what `logbook digest` prints over a second record holding only the lines at
or below that ceiling; a missing policy file is a ceiling of 1, a broken one is refused; the log holds counts
and never content.
`tests/test_mcp_write_tools.py` holds the two named write tools to the policy: refused without `write`, with
an expired entry and outside the window; `sign_day`'s line byte for byte the line `day sign` writes for the same
flags and `--at`; a re-sign superseding; dispositions in the signature; `note_day` with each kind; another
writer's lock and a moved head refused; a log with counts and never the persona's name.
`logbook mcp --inspect` is the hand check: the table, and a request you can paste.
