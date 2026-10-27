# What you heard

The record knows which podcast episodes you played (Apple Podcasts, `listen/v1`) and which videos you
watched (YouTube's watch history from a Takeout export, `watch/v1`). `sync heard` adds what was *said*
in them: the episode's transcript or the video's captions, stored once in the attachment store, and one
`heard/v1` line beside the listen or watch it belongs to. `logbook show heard` lists them; `logbook search`
finds words inside them. The design is [RFC 0046](https://github.com/bighydro/logbook/blob/main/rfcs/0046-what-you-heard.md) (draft).

The words are someone else's, published to anyone. The line is tier 2 all the same, because it says
you heard them, as the listen line does. Nothing leaves: a crossing and a shared page leave every text
home unless the destination's entry names it (below).

## Turn it on

```bash
export LOGBOOK_HEARD=feed,apple,captions   # the text sources you want; any of the three
logbook sync heard --dry-run               # what it would fetch and read, nothing written
logbook sync heard
```

`feed` fetches a transcript from the podcast's host, and each fetch tells that host which episode you
played, a tier-2 fact like the listen itself. So the variable alone fetches nothing: `feed` needs a
`heard` entry in `policy/crossing.json` that says so, with the tier of the listens (2) and, if you like,
an `until`:

```json
{"heard": {"max_tier": 2, "fetch": true, "until": "2026-12-31"}}
```

Without it, or once it has expired, every feed transcript is a counted skip (`feed transcript not
fetched`), the entry is checked before any request or lookup, and one line says what to write;
`logbook doctor` names the entry on its crossing line. `apple` and `captions` read files on this
machine and need no entry.

Until `LOGBOOK_HEARD` is set, `sync --all` and the schedule skip the source and say so. Once set, the
schedule runs it after every other source but the photo walk, so it sees the listens the podcasts sync
wrote. A dry run fetches nothing: it counts what it would fetch. To switch it
off without unsetting the variable, list it in `policy/import.json` as any source:
`{"disabled": [{"source": "heard", "reason": "not now"}]}`.

| Variable | What it does |
|---|---|
| `LOGBOOK_HEARD` | the text sources: `feed`, `apple`, `captions` (a comma list). Required |
| `LOGBOOK_HEARD_MAX_FETCHES` | network fetches a run at most (default 20); the rest wait for the next run |
| `LOGBOOK_HEARD_DELAY_S` | seconds between two fetches (default 2) |
| `LOGBOOK_HEARD_CAPTIONS_DIR` | the folder of caption files, for `captions` |
| `LOGBOOK_HEARD_LANGUAGES` | which caption language wins when a video has several, e.g. `nb,en` |
| `LOGBOOK_HEARD_TTML_DIR` | Apple Podcasts' transcript folder, when it is not the Mac's own |
| `LOGBOOK_PODCASTS_DB` | Apple Podcasts' store, as for `sync apple-podcasts` |

## Where the words come from

**`feed` — the podcast's own transcript.** Many feeds publish an episode's transcript
(`<podcast:transcript>`); `sync apple-podcasts` keeps its URL on the listen line and never fetches it.
`sync heard` fetches it, once: WebVTT, SRT, podcasting 2.0's JSON and plain text are kept exactly as
they came; an HTML transcript is skipped and counted, and so is a URL that points at this machine or
your own network or any address that is not on the public internet (`localhost`, `127.0.0.1`,
`192.168.…`, the tailnet's `100.64.0.0/10` and Tailscale's `100.100.100.100`), which is never requested,
nor a port other than 80 and 443. A host name (a MagicDNS name among them), or an address not written
out in full (`127.1`), is looked up once and refused if any address it gives is one of those; a host
that does not look up is a failed fetch, never a request. The connection goes to the address that was
checked and no other, never through a proxy your environment names, while the name is still what the
host and its certificate are checked against: a name that answers differently the second time is
never asked twice. A redirect is followed only to another public `http(s)` address, three at most, and
each hop is checked and connected the same way; one that points at this machine, your network, another
scheme or port, or from an `https` page to `http`, is refused before it is requested. At most `LOGBOOK_HEARD_MAX_FETCHES` a run, two
seconds apart. A fetch that fails is one counted skip; the same URL is not tried again for a week, and
never after its third failure.

**`apple` — what Apple Podcasts cached on this Mac.** The app keeps the transcripts it shows as TTML
files under `~/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Library/Cache/Assets/TTML/`.
Apple does not document that folder: it is where the files are today, and a macOS update may move it
(`LOGBOOK_HEARD_TTML_DIR` then names the new one). Each file is matched to its episode through the
Podcasts store's own columns, read-only. Nothing is fetched.

**`captions` — a video's captions, from your folder.** YouTube has no documented way to fetch a
video's captions without a key, and the record does not scrape. So the captions come from a folder you
fill with a tool of your choice, named by the video's id:

```
~/Captions/aB3dE5fG7hI.vtt        # one language
~/Captions/aB3dE5fG7hI.nb.vtt     # or one file per language
~/Captions/aB3dE5fG7hI.en.vtt
```

`export LOGBOOK_HEARD_CAPTIONS_DIR=~/Captions`, and the next `sync heard` writes a line for every
watched video whose id has a file. The video itself is never downloaded.

**`local` — a transcription on this machine.** Reserved, not built: the record holds no audio of a
podcast or a video to transcribe.

## What was heard

```bash
logbook show heard                             # the last 14 days
logbook show heard --day 2026-10-14
logbook show heard --since 2026-10-01 --until 2026-10-14
logbook show heard --day 2026-10-14 --json
```

```
2026-10-14 Wednesday
  08:40  feed      nb  41,237 chars  7,012 words  Episode 12: the east berth — Havnepodden
         «Velkommen til Havnepodden. I dag snakker vi om østkaia, og om hvorfor…»
  21:05  captions  en   3,912 chars    702 words  Splicing a three-strand rope — Knots by Ola
         «Today we splice a three-strand rope. First, unlay about a hand's width…»
```

A text is listed on the day of the listen or watch it belongs to: the first time you played the work.
Playing an episode again writes no second text. A sealed text needs your identity to show anything;
without it the row says `[sealed heard/v1]`.

## Searching inside

`logbook search` finds words inside every text, as it finds them in a call's transcript. In a record
that seals (after `logbook key init`), a text's line is sealed and the search index never holds the
words of a sealed line, so search finds no heard text there, as it finds no sealed transcript:

```bash
logbook search splice                 # every line with the word, the texts among them
logbook search '"east berth"' --kinds heard
```

## Nothing leaves

A crossing (`export crossing --to D`) and a shared page (`export share`) leave every `heard` line,
and its text, at home unless the destination's entry in `policy/crossing.json` says so:

```json
{"hermes": {"max_tier": 2, "heard": true}}
```

The crossing counts what it left home under `held_back_by_entry`. The trip bundle never carries a
text; the vault, the site, the world and the Notion export never copy an attachment; `mcp` serves the
line, never the text.
