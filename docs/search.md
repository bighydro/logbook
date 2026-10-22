# Search

`logbook search TEXT [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--kinds note,transcript,message,mail,event]
[--tier 1|2|3] [--limit N] [--standing] [--json]` is full-text search over the record: the words of every line
that carries any, found through the index and read back from the files, grouped by day with the
row `show` prints and a snippet of the matching words. It is a reader (ADR 0013): it derives from
the record at its head and writes nothing.

```bash
logbook search kari                          # every line with the word, tiers 1 and 2
logbook search "zürich hotel"                # both words, in any order, anywhere in the line
logbook search '"with kari"'                 # a phrase: the words in that order
logbook search 'kar*'                        # a prefix: Kari, Karin, Karlsen
logbook search kari --since 2026-06-01 --until 2026-06-30
logbook search standup --kinds event,transcript
logbook search invoice --tier 3              # tier 3 — money, health, the transcripts at 3 — only when you say so
logbook search kari --json                   # the query, the hits by day with rank, snippet and summary
```

## What it prints

```
2026-06-13 Saturday
  12:00  note       manual         Kari said the run was good
         [Kari] said the run was good
2026-06-11 Thursday
  11:00  mail       mail           ✉ Zürich hotel booking — Hotel Example → kari.nordmann@example.org
         …reservations@example.org · Hotel Example · Zürich hotel booking · [kari].nordmann@example.org
2026-06-10 Wednesday
  20:00  note       manual         Dinner with Kari at the cafe, running late
         Dinner with [Kari] at the cafe, running late
3 hits in 3 days
```

One block per local day, the latest day first; inside it one hit per line in time order. The first
row of a hit is the line as `logbook show` prints it on its day — the local time, the kind, the
source, the profile's own summary with senders, attendees and participants named as the record's
resolution lines name them (RFC 0006). The second row is the snippet: up to sixteen words of the
line's text around the match, each matching word in `[brackets]`, `…` where the snippet cuts the
text and `·` between two fields of the line (a title and its text, a mail's subject and its body).
The last row counts. Nothing matches: `nothing matches: <text>`, and a reminder that tier 3 was not
searched when it was not.

`--json` is one object: `query` (`text`, the FTS5 `expression` it became, `since`, `until`,
`kinds`, `max_tier`, `limit`), `hits`, `more` (the limit was reached) and `days`, each with its
`lines` — `seq`, `id`, `at`, `kind`, `source`, `tier`, `rank`, `snippet` and `summary`, the text
part of the `show` row.

## The query

- A **word** matches the word itself, case and accents aside: `zurich` finds `Zürich`, `cafe`
  finds `Café`. It never matches a stem or an inflection: `run` does not find `running`, `Haus`
  does not find `Häuser`, in English or in German. The search is literal.
- A run in **double quotes** is a phrase: the words in that order, adjacent. `"with kari"` finds
  `Dinner with Kari`, not `Kari with`. The shell wants the quotes protected: `'"with kari"'`.
- A term ending in `*` matches by **prefix**: `kar*` finds `Kari` and `Karlsen`; `"with kar*"` the
  phrase with its last word a prefix.
- Several terms must **all** match, anywhere in the line, in any order. There is no `OR`, no `NOT`
  and no field filter: `AND`, `OR`, `NOT`, `NEAR`, a colon and a caret are words like any other,
  so a search for `kind:note` looks for that text. A term with no letter or digit (`-`, `*`) is
  dropped; a query with none at all is refused.
- Punctuation inside a word is a word boundary, as the index tokenises it: `kari.nordmann@example.org`
  is the phrase `kari nordmann example org`, so the address finds the mail and so does `nordmann`.

## What is searched

The index holds the words of every line of a kind that carries any: `note`, `transcript`, `message`,
`mail`, `event`, `task`, `highlight`, `voice-memo`, `browse`, `watch`, `listen`, `trip` and `journey`
(one profile under two spellings, RFC 0031: asking for either kind searches both). A location
point, a photo, a health sample, a call, a flight or a crossing has no words and no row — searching
`Oslo` finds the notes and mails that say it, never the ten thousand points whose reverse geocode
does. `--kinds` narrows to some of the twelve; any other kind is refused with the list.

For each line, every string in its payload at any depth is text: a note's words, a message's and
the names its chat and sender show, a mail's subject, body and the names and addresses on it, a
calendar entry's title, location, notes and attendees, a task's title and notes, a highlight's
quote, a page's title and URL. Not the ids, digests, stamps and types (`raw_id`, `sha256`, `path`,
`media_type`, `thread`, `modified_at`, `status`, …): nobody searches for those, and a snippet never
shows one. A **transcript**'s text lives in the attachment store, never inline (RFC 0004); the
index reads it from there as the promises reader does — WebVTT, SRT, Granola's JSON or
`Speaker: text` prose — and holds every turn as `Speaker: text`, so a sentence said in a meeting is
found and the snippet says who said it. A transcript whose file is not in the store is searched by
its title and participants alone.

The window is local days, inclusive, in the record's zone (`--since`, `--until`; the whole record
without them). A **retracted** line is never a hit, and neither is a retraction. A line that is not
**standing** because a later line of its own kind `supersedes` it (SPEC §3) is still a hit, marked:
its row ends `· superseded by #N`, the line that took its place, in the words `show` uses for the
kinds it marks (search marks every kind), and in `--json` every hit carries `standing` (true or
false) and `superseded_by` (the id of that line, else `null`). A superseder that is itself
retracted supersedes nothing, and a line of another kind naming it does not count, as every reader
has it. `--standing` leaves the superseded hits out and lets the next by rank take their place, so
`--limit` still counts standing hits; nothing is left out without it. The mark is read from the
index's `lines_kind_supersedes` lookup, not from the search table, so no rebuild is needed for it.

## Tiers

Tiers 1 and 2 are searched by default. Tier 3 — money and health, and the transcripts the reference
adapters write at 3 — is searched only with `--tier 3`, as `export crossing` crosses it only with
`--tier 1,2,3` and `mcp` serves it only with `--allow-tier-3`; `--tier 1` searches tier 1 alone. No
line is ever printed above the tier asked for, and a search that finds nothing says when tier 3 was
left out.

## Ranking and the limit

The hits are ranked by FTS5's bm25 — a line where the words are rarer and denser ranks higher —
and the best `--limit` (50 by default) are kept, in the query, before anything is read from the
files. What is shown is those hits grouped by day, latest first: the rank decides which lines
you see, the day where you read them. When the limit was reached the last row says so; narrow the
window or the kinds, or raise `--limit`. `--json` carries every hit's `rank` (lower is better).

## The index

The words sit in one FTS5 table, `search`, inside `index.sqlite` (schema 6), beside the `lines`
table that locates every line: the rowid is the line's `seq`, the body its words, and `kind`,
`tier` and `day` beside them so the query cuts the kinds, the tier and the window inside the table
and the join to `lines` is one lookup per hit kept. The tokeniser is `unicode61` — case and
diacritics folded, no stemmer in any language — which is what makes the search literal.

The table is written as the index is: `Logbook.append` and `append_many` add each new line's words
in the same transaction as its row, so a note added a second ago is found with no rebuild; `logbook
index` rebuilds the table with the rest, reading every transcript's text from the store once; a
record whose index was built by an earlier schema is rebuilt once, by the first reader that opens
it. Like the rest of the index the table is a cache (ADR 0007): the files are the record, `verify`
never opens it, and deleting `index.sqlite` loses nothing.

The cost of a query is the lines that contain the words, never the size of the record: a name in a
record of two million lines answers in well under a second, the first time, from a cold file
(`tests/test_search.py`, `LOGBOOK_SLOW=1`). A very common word — one in most lines — costs its
matches, every one of them ranked; narrow with a second word or a window.

A Python whose SQLite was built without FTS5 (every official build has it; a distribution's may
not) builds an index with no search table and `logbook search` says so and exits 1; every other
reader is unaffected.

## In the Library

`logbook serve` has the same search at `/search` (`logbook/contrib/search_page.py`), under
**search** in the navigation: a form with one field, the words as you would type them after
`logbook search`, sent as a GET. It calls the two functions the command calls (`search.query`,
`search.search`), so the words, the phrases, the prefixes, the ranking and the retracted lines are
the command's own.

```
/search?q=kari                          every line with the word
/search?q=kari&kind=note                notes only (trip and journey are one kind, as with --kinds)
/search?q=kari&year=2026                lines of 2026 only, by local day
/search?q=harbour&kind=note&page=2      the next fifty
```

- **The tier is the page's.** The hits are held to the Library's tier gate as every other page
  holds its lines: `logbook serve` reads every tier on this machine, as its Day and `/line/ID` do,
  so a search there finds tier 3 too; a gated page (`export site`'s, a test's `Site(tiers=…)`) finds
  only what its gate lets through, and a hit above it is not on the page and not in a page's
  count; a gate of some tiers only (1 and 3) searches further until its page is full. The header
  says the highest tier among the hits shown.
- **A hit** is one row under its day, the date a link to the Day: its local time, a link to the
  Day too, to the hit's own row on it for a note, a mail and a calendar entry (the kinds the Day
  lists as rows of their own; a message is under its conversation there); its kind; an excerpt of
  up to sixteen words around the match, each matching word marked (the command's `[brackets]`,
  drawn; a bracket the record itself holds, `[urgent]` in a note, stays as written); and its line's
  id, a link to `/line/ID`, the line as the record holds it. A hit a later line supersedes says so
  as the command does, `superseded by #N`, a link to that line, when the page's gate lets that line
  through; a correction above the gate is no mark.
- **The filters are links**: every kind with words and every year the record runs over (its span,
  as the front page says it, whatever the gate), the filter in force in bold and *every* to take
  it off. They are never counted: a count would cost
  the matches of the words a second time, and would say how many lines a gate holds back. A filter
  that finds nothing says so in its sentence (`In 2025, nothing in the record matches marina.`). Nothing about a filter is kept in the browser: the
  address is the whole search, so it can be bookmarked, reloaded and sent back to.
- **The pages are links** of fifty hits. The rank decides which page a hit is on, the day where it
  is read on that page, as the command does with `--limit`. Page 20 is the last (a thousand hits);
  past that, a kind or a year narrows the search.
- An empty query is the form and nothing else. A query that finds nothing says so in one sentence.

The page is the Library's: one document with the Day's tokens and type, no script, nothing fetched,
no reference but the server's own paths, nothing written, and phone width first, every link and
control a 44 px target. No person is a filter and no number stands beside a name. An exported site
(`logbook export site`) has no server to answer a form, and has no search.

A page of hits is kept by its tag like every page of the record (`Site.etag`): asked again at the
same head, it is not searched again (a millisecond). Otherwise the cost is the command's: the
matches of the words, never the size of the record. On the five-million-line synthetic record of
`scripts/bench_library.py` (ten years, 4 vCPUs), a fresh query in a running server answers in
0.07 to 0.9 s — a name (`kari`, 205,000 lines) 0.63 s, a word (`fjord`) 0.45 s, a phrase
(`"running late"`, 346,000 lines) 0.87 s, a name and a word together 0.07 s, page 5 of `fjord`
0.46 s, each with its superseded hits marked — and `kari` from a cold disk, the first request after a restart with nothing in the
operating system's cache, 1.5 s. A word in most lines costs its matches, every one ranked: the
persona's surname, in 2.2 million of the five million, takes 4 s, as `logbook search` does.
Narrow with a second word, a kind or a year.

## What it is not

Not a question answered: it finds the lines that say the words, and ranks them; it does not read
them for you. Not a scan: the MCP `search` tool still reads the standing lines of a window and
keeps those whose payload contains the text, behind the crossing gate ([mcp](mcp.md)); this
command is the ranked search through the table, for the owner at the keyboard, with the tiers as
its only gate.
