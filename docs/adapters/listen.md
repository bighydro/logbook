# Listening: Spotify, Apple Music and Apple Podcasts

Three adapters write `listen/v1` lines (RFC 0019) from the services' own exports and stores, beside
the `shazam` adapter that already does: one line per listen, `media` `track` or `episode`, the
title, the performer, the album or the show as the service spells them and never resolved, how
much played, and under `extra` the skip flag and the device when the export carries them. Tier 2,
as the profile says. One reader sums them up: `logbook rollup listen`.

```bash
logbook add spotify ~/Downloads/"Spotify Extended Streaming History"           # the folder: every history file in it
logbook add spotify ~/Downloads/"Spotify Extended Streaming History"/Streaming_History_Audio_2025_3.json
logbook add apple-music ~/Downloads/"Apple Music Activity"/"Apple Music Play Activity.csv"
logbook add apple-music ~/Downloads/"Apple Music Activity"/"Apple Music Library Tracks.csv"
logbook add spotify ~/Downloads/"Spotify Extended Streaming History" --dry-run  # what would be added; nothing written
logbook import-backup ~/Library/Application\ Support/MobileSync/Backup/<udid> --only podcasts  # the phone's Podcasts library
logbook sync apple-podcasts                                                    # this Mac's own Podcasts library, nightly
logbook rollup listen --year 2026                                              # listens, hours, skips, top artists, podcasts, by month
```

Both are file adapters in the sense of [the overview](README.md): pure, no network, never a write
to the export, every line keyed by a `raw_id` so that a second `add` of the same export appends
nothing. Both are sniffed, so a bare `logbook add <path>` finds them; `logbook add spotify <path>`
and `logbook add apple-music <path>` (or `add music`) name them outright.

## Spotify: the extended streaming history

Spotify's account page (Privacy settings → *Download your data* → *Extended streaming history*)
mails a zip a few days later. Inside is one folder, `Spotify Extended Streaming History/`, holding
`Streaming_History_Audio_<years>_<n>.json` and `Streaming_History_Video_<years>.json`: one JSON
array each, one object per stream, with `ts` (when the stream **stopped**, UTC), `ms_played`, the
track's name, album artist and album, its `spotify:track:` URI, or an episode's name, show and
`spotify:episode:` URI, or an audiobook chapter, and the flags `skipped`, `shuffle`, `offline`,
`reason_start`, `reason_end`, the `platform` and the connecting country and IP address. The adapter
reads the folder (every history file in it) or one file, streamed through `ijson` so a decade of
history never sits in memory at once. The shorter *Account data* export (`StreamingHistory0.json`,
end time to the minute, no URI) is not this format and is not read.

| Field | From |
|---|---|
| `at`, `end` | `ts` less `ms_played` (when playback started); `ts` (when it stopped) |
| `raw_id` | `spotify:<URI without its spotify: prefix>:<ts as spelled>` — `spotify:track:1a2b…:2026-03-04T20:19:03Z` |
| `media` | `track` for a track, `episode` for a podcast episode |
| `title`, `artist`, `album` | the track's name, album artist and album, as Spotify spells them |
| `title`, `show` | an episode's name and its show |
| `url` | the open.spotify.com page of the URI |
| `played_s` | `ms_played` in seconds |
| `extra` | `ms_played`, `skipped`, `device` (Spotify's `platform`), `reason_start`, `reason_end`, `shuffle`, `offline`, `country` (`conn_country`) |

A stream of 0 ms — a track touched and skipped at once — is a listen with `played_s` 0 and its
skip flag, since the export says the owner put it on; `rollup listen` counts it as a listen and
adds no hours for it. An audiobook chapter is skipped and counted (RFC 0019 has tracks and
episodes, not books). A row that names nothing — a local file, an item since removed — is skipped
and counted. An older export (no `platform`, no `skipped`, a `username` column) reads with what it
has: no `device`, no `skipped` under `extra`. The IP address and the username are never kept.

## Apple Music: the three CSVs of Apple's data export

[privacy.apple.com](https://privacy.apple.com) → *Request a copy of your data* → *Apple Media
Services information* delivers `Apple_Media_Services.zip`, and in it `Apple Music Activity/`. Three
of its files describe listening, three ways; the adapter reads whichever one it is given, by its
header, and finds the columns by name, so a column it does not need may be missing or new.

**`Apple Music Play Activity.csv`** is the record of listening: one row per player event. The
adapter writes one line per `PLAY_END` row (a `PLAY_START`, a lyric view and the rest are counted,
not lines): `at` the event's start and `end` its end, `title` the `Song Name` (or the older export's
`Content Name`), `artist`, `duration_s` from the media duration and `played_s` from the play
duration, and under `extra` `ms_played`, `skipped` (true for `TRACK_SKIPPED_FORWARDS` and the like,
false for `NATURAL_END_OF_TRACK`, absent for a pause or a scrub), `device` (the `Device Identifier`
Apple assigns), `end_reason` as Apple spells it, and `offline`. The file carries no track id, so
`raw_id` is `apple-music:<sha256 of the artist and title, 16 hex>:<start as spelled>` — the rule
`browse/v1` and `watch/v1` use for a source with no id of its own. The Apple ID and the client's IP
address are never kept.

**`Apple Music Library Tracks.csv`** is one row per track in the library with its `Last Played
Date`, `Play Count` and `Skip Count`. As with `apple-podcasts`, the store keeps one row per track
and moves its time, so the adapter writes one line per last-played time it sees: `raw_id`
`apple-music:<Apple Music Track Identifier, else Track Identifier>@<Last Played Date as spelled>`,
`at` that time, `end` null, `title`, `artist`, `album`, `duration_s`, `extra.play_count` and
`extra.skip_count`. A track never played is counted (RFC 0019 rule 5). Added after every export,
this turns the library into a sparse listening history; it is not a record of every play.

**`Apple Music - Play History Daily Tracks.csv`** is coarse: one row per track per day, with the
`Hours` of the day it played in (`20, 21`), the milliseconds played that day, play and skip counts,
and `Track Description` as `Artist - Title`. The adapter writes one line per row at the first hour
listed, read in the record's zone (rule 4: the file gives no zone), `played_s` the day's total,
`extra.hours`, `extra.play_count`, `extra.skip_count` and `extra.end_reason`; `raw_id`
`apple-music:<Track Identifier>:<Date Played> <Hours as spelled>`. A row with no hour is at the
day's local midnight.

The three files describe the same listening with three different keys, so they do **not** dedupe
against one another: adding all three triples the count. Add the play activity, which is the
complete record; add the library only from an export that has no play activity; add the daily
history only when neither is there. A re-add of the same file appends nothing.

## Apple Podcasts: the library, from the phone's backup or the Mac

Apple Podcasts keeps its library in one Core Data store, `MTLibrary.sqlite`: on the Mac under
`~/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/`, on the phone under
the app group `group.com.apple.podcasts` at `Documents/MTLibrary.sqlite`, which an iPhone backup
carries. `import-backup --only podcasts` copies it out of the backup into
`inbox/ios-backup-<udid>/apple-podcasts/` with its `-wal`/`-shm` and runs the adapter on the copy;
`logbook sync apple-podcasts` reads the Mac's own store, nightly (`LOGBOOK_PODCASTS_DB` names
another); `logbook add apple-podcasts <copy>` reads any copy. One mapping for all three, so the
phone and the Mac dedupe each other (ADR 0017).

The store has one row per episode and overwrites its last-played time when the episode is played
again, so the adapter writes one line per last-played time it sees (RFC 0019 rule 1): `raw_id`
`apple-podcasts:<episode uuid>@<last played>`. Added after every backup or sync, that turns one
row per episode into a sparse listening history; it is not a record of every play.

| Field | From |
|---|---|
| `at` | `ZLASTDATEPLAYED`, the last-played time; `end` null |
| `title`, `show`, `publisher` | the episode's title; the show's title and author from `ZMTPODCAST`, else the episode's own author |
| `url` | the episode's web page, else its enclosure |
| `duration_s`, `played_s` | `ZDURATION`; `ZPLAYHEAD` when above zero |
| `completed` | the playhead within 30 s of the duration, or rewound to zero with a play counted (the app rewinds an episode played to the end); absent when the store has no playhead column, false when it cannot show either — never a guess |
| `published` | `ZPUBDATE` |
| `extra` | `play_count`; `transcript_url`, the transcript the episode's feed publishes (`<podcast:transcript>`), when the store keeps its URL and it is an http(s) URL |

The columns are discovered with `PRAGMA table_info`; only the title, the uuid and the last-played
time are required, every other column is read when present and left out when not, and a store
without the shows' table still reads, without `show`. An episode never played, or without a title,
is skipped and counted (rule 5). The store is opened read-only and immutable, never written.

**Transcripts are recorded, never fetched.** `extra.transcript_url` is the URL and nothing more:
the adapter, like every reader, never touches the network. Apple's own transcript identifiers,
which are not public URLs, are never recorded. Fetching the transcripts the record points at —
an explicit, separate `logbook fetch transcripts` that would read each URL once and keep the text
as a `transcript/v1` line with the listen as its provenance, in the manner of `logbook transcribe
voice-memos` — is the follow-up, not part of this adapter, and not written yet.

## The rollup: `logbook rollup listen`

```bash
logbook rollup listen                     # the whole record, per year
logbook rollup listen --year 2026
logbook rollup listen --since 2026-01-01 --until 2026-03-31 --json
```

Per calendar year of the window: the **listens**, the **hours** played (`played_s` summed; a line
with no playhead, a Shazam tag, is a listen with no hours and is counted under `untimed`), the
**skipped** lines (`extra.skipped` true), the lines per **service**, the podcast **episodes** with
their hours, the **top artists** — the tracks' performers as the services spell them, ranked by
hours played, then listens; ten — the **podcasts** section, the episodes' hours **by show** (the
shows as the services spell them, by hours then episodes) and **by month**, printed only for a
year with an episode — and **by month**, every month the window touches with its hours, listens
and skips, a month with no listen printed as an em dash and never a zero. The window is
`--year`, or `--since`/`--until`, clipped to the days the record's listen lines cover. The lines
standing are read: a correction that `supersedes` a line wins, the latest when a line was corrected
more than once, and a retracted line is out. Read through the index, nothing written. Under `--json`
every number carries the ids of the lines it came from. Every `listen/v1` line counts, whichever
adapter wrote it: `spotify`, `apple-music`, `shazam`, `apple-podcasts`, the demo's.

```
listen 2026-01-01 – 2026-03-20
  2026  10 listens · 2.3 h · 2 skipped · 1 without a playhead · 3 episodes · spotify 8, apple-podcasts 1, shazam 1
        top artists
          Ola Nordmann                 0.3 h · 3 listens
          Kari Nordmann                0.2 h · 4 listens
        podcasts  3 episodes · 1.8 h
          by show
            Havnepodden                  1.5 h · 2 episodes
            Knots Weekly                 0.2 h · 1 episode
          by month
            2026-01  0.2 h · 1 episode
            2026-02  —
            2026-03  1.5 h · 2 episodes
        by month
          2026-01  0.3 h · 2 listens
          2026-02  0.3 h · 1 listen
          2026-03  1.6 h · 7 listens · 2 skipped
```

The rollup lives in `logbook/core/listen_rollup.py`, in `rollup.py`'s manner but beside it, so the
listening rollup grows without touching the others.

## `add --dry-run`

`logbook add <export> --dry-run` (any file adapter, named or sniffed) runs the adapter and says how
many lines would be added and how many are already in the record — the same `(source, raw_id)` rule
`add` dedupes with — and what the adapter skipped, and writes nothing: no line, no index, not even
`logbook.json`. A sentence or a declared flight is one line, written or not, so `--dry-run` is
refused for them.
