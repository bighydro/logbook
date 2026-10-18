# The shelves: promises, goals, agents

Three shelves of the Library in `logbook serve`, after Ideas in the navigation. Each one only reads:
there is no form on them and nothing is written. Each reads through the server's tier gate, as the
other shelves do. A line above the gate is not listed, not counted and not reachable by its own
address, and the page's header gives the highest tier it read. No page opens a connection or runs a
model.

## Promises — `/promises`

These are the promises the record's own words suggest, as `logbook promises` reads them
([promises](promises.md)), in three sections:

- **Open** comes first, oldest first: your promises and what was asked of you, carried ones included.
- **Kept**, newest first: closed by `logbook promises done ID` (a task line marked done), or kept on a
  signed day.
- **Dropped**, newest first: closed by a task line marked cancelled, or dropped or missed on a signed
  day.

Each row gives who it is with, the sentence as written, the day it was said, the due hint, and the
line it was read in, linked on its Day. In a conversation with one of your agents, the agent is
named as the agent, never as a person. Rows are read by rules: they are proposals, not facts.

**The local model's verdict** shows where `logbook promises --judge` has already given one. The page
uses the reader's own words, its parts apart: the judge's due day, then `judged` and its confidence,
by whom and to whom. Nothing is judged here. A promise the judge set aside is not listed, as in `logbook promises`.

**One person.** `/promises?person=NAME` keeps the promises with one person: the counterpart, or a name
the line resolves. The names to choose from head the page. An agent is never one of them.

**One promise.** `/promises/ID` shows the sentence, the sentences around it as the reader read them,
the verdict, and the evidence. The evidence is the transcript (or note, mail, message) line it was
read in, linked on its Day, plus the task line or the signed day that closed it.

The gate covers what closed a promise too. A task line or a signature above the gate does not close
the promise on that page.

## Goals — `/goals`

[Goals, reviews and chapters](goals.md) are your own words.

The page opens with **the chapter** you are in today, its rules, and any clash with another standing
chapter. The other chapters are listed under it.

Then come **the goals by horizon**: life, this year, this quarter. Open goals come first. Each shows its
standing wording, its state (open, done, let go, superseded, past), and the latest verdict you gave
it with the day the verdict is for.

If there are no goals yet, the page says how to add the first:

```bash
logbook goal import ~/goals.txt      # one goal a line: `Sail the whole coast to Lofoten | life`
```

**One goal.** `/goals/ID` takes the id of any line of the goal's chain, the first wording included. It
shows the goal, its earlier wordings, and every review newest first: the disposition, the period, the
day, the note, and when it was written if that was later.

Goals, reviews and chapters are tier 2. A page whose gate does not read tier 2 says so, and shows none
of them.

## Agents — `/agents`

These are your sessions with your own agents ([your own agents](adapters/agents.md)), by day, latest
first. Each page holds fourteen days (`?page=N`), and `?day=YYYY-MM-DD` shows one day. The words of
a session are read only for the days on the page. Sessions and bot chats are tier 2, as #279 wrote
them (a `--tier` on import sets another), so a page that does not read tier 2 shows none and says so.
A session is one of these:

- a Claude Code session, or a conversation from the Claude apps' export: one standing transcript line
  (a session that grew is its latest line);
- a day of messages with one Telegram bot.

Each session shows:

- **the source**, and the agent's name;
- **the length**: minutes, your turns and the agent's, the words on each side, and the tool calls, as
  the source counted them;
- **your words**: the first three turns, each cut at 280 characters with the whole turn in a fold,
  and the rest folded whole;
- **the agent's summary**: the provider's own summary when it made one. Otherwise it is the title the
  source gave the session (Claude Code's own summary, the apps' name for a conversation), when that is
  not your own first line;
- **the agent's words**, folded whole and marked as machine text.

A session at a lower tier than the review that names it (below) is shown at the review's tier.

A forward you sent a bot is someone else's words. It is never shown as yours.

### Which goal a session served (provisional)

A session served a goal only when a review of that goal says so. The review names the session's line
(or one of its messages) under `extra.lines`:

```json
{"schema": "review/v1", "goal": "<goal line id>", "disposition": "advancing", "period": "day",
 "note": "the planner session", "extra": {"lines": ["<session line id>"]}}
```

The session then links the goal, and the goal's page lists the session. No goal is ever guessed from
a session's words. `extra` is where RFC 0036 lets a review keep anything else; the key `lines` is this
page's reading and is provisional until an amendment of RFC 0036 names it. No command writes
`extra.lines` yet, so on a record today no session shows a goal.
