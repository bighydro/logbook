# RFC 0019 — payload profile `listen/v1`

Status: draft · 2026-10-01 · comment period: two weeks

Something the owner heard: a song Shazam identified, a podcast episode Apple Podcasts played, later a Spotify or Apple Music history. One profile for tracks and episodes, so that "what was I listening to that week" is one query, with `media` telling a song from a show.

## Line

`kind` MUST be `listen`. `tier` MUST be 2. `at` is when the listen happened as the source recorded it: Shazam's tag time, Podcasts' last-played time; `end` is null unless the source keeps when playback stopped. `source` is the adapter (`shazam`, `apple-podcasts`, …); `tz` is the record's zone, which also localises a source whose times are floating (Shazam's export has no offset).

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"listen/v1"` | MUST | |
| `raw_id` | string | MUST | `<service>:<the source's id>:<time as the source spells it>` — a track identified twice is two listens; `apple-podcasts:<episode uuid>@<last played>` for a store that keeps one row per episode and moves its time (a snapshot per listen, as `note/v1`) |
| `media` | string | MUST | `track` or `episode` |
| `title` | string | MUST | the track's or episode's title as the service kept it |
| `artist` | string | MAY | a track's performer, as the service names them; never resolved |
| `show` | string | MAY | an episode's podcast, as the service names it |
| `publisher` | string | MAY | who makes the show, when the source keeps it apart from the show's name |
| `album` | string | MAY | a track's album |
| `url` | string | MAY | the service's page for the track or episode |
| `duration_s` | number | MAY | the whole track's or episode's length in seconds, when known |
| `played_s` | number | MAY | how far playback got, in seconds, when the source keeps a playhead |
| `published` | RFC3339 UTC | MAY | an episode's publication time |
| `service` | string | MUST | `shazam`, `apple-podcasts`, `spotify`, … |
| `supersedes` | string | MAY | id of the earlier line this one replaces |

Anything else the source reports MAY be kept under `extra`: Shazam's track key, Podcasts' play count.

## Rules

1. One line per listen. A Shazam tag is one listen whether or not the song was played after; a Podcasts episode is one listen per last-played time (the store moves the time when the episode is played again, which makes a new line with a new `raw_id`).
2. `artist` and `show` are the service's words, kept as spelled; a `resolution/v1` line may name them later, never the adapter.
3. `duration_s` is the whole work; `played_s` is how much was heard. A reader that wants "listened to the end" compares the two, with the slack it chooses.
4. A time the source gives without a zone (Shazam's `TagTime`) is read in the record's zone and `tz` says so; one with a `Z` or an offset is read as given.
5. An episode a store holds but never played is not a listen and not a line; it is counted.

## Example (synthetic)

```json
{"at":"2026-03-04T20:15:30Z","end":null,"tz":"Europe/Oslo","source":"shazam","kind":"listen","tier":2,
 "payload":{"schema":"listen/v1","raw_id":"shazam:100000001:2026-03-04 21:15:30","media":"track","title":"Fjordsang",
 "artist":"Kari Nordmann","url":"https://www.shazam.com/track/100000001/fjordsang","service":"shazam"}}
```

## Notes

- **Why one profile for tracks and episodes.** They share every field but two names (`artist`, `show`), and a day's listening is one list. `media` is the one field a reader filters on.
- **Why Shazam is a listen.** A tag says the owner heard the song and wanted to know what it was; that is a stronger record of hearing it than a streaming log's autoplay.
- **Why Podcasts gives one line per last-played time.** The store keeps one row per episode and overwrites `ZLASTDATEPLAYED`; the history is lost in the source, so the record keeps each state it saw. A nightly `sync` therefore turns one row into a sparse listening history.
