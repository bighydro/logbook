# RFC 0018 — payload profile `watch/v1`

Status: draft · 2026-10-01 · comment period: two weeks

A video the owner watched, or a search they made to find one: YouTube's watch and search history from a Google Takeout export today; a Netflix or Plex viewing history tomorrow. Not `browse/v1` (RFC 0017): a visit says a page was opened, a watch says what was playing and who made it, and a reader asking "what did I watch that winter" wants the channel and the title, not a url.

## Line

`kind` MUST be `watch`. `tier` MUST be 2: what the owner watches is as private as what they read. `at` is when the video was opened or the search made, as the service recorded it; `end` is null (YouTube's export does not say how long the video played; a source that does MAY set `end`). `source` is the adapter (`google-takeout`, …); `tz` is the record's zone.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"watch/v1"` | MUST | |
| `raw_id` | string | MUST | `<service>:<time as the export spells it>:<first 16 hex of sha256(url, else title)>`: the export has no entry id, and the instant plus the video is the entry's identity |
| `action` | string | MUST | `watched` or `searched` |
| `title` | string | MUST | the video's title as the service kept it; for a search, the query as typed. A video the service has removed keeps the words the export gives (`a video that has been removed`) |
| `url` | string | MAY | the video's page, or the search's results page; absent for a removed video |
| `video_id` | string | MAY | the service's id for the video (YouTube's `v=`), when the url carries one |
| `channel` | object | MAY | `{ name, url? }` — who published it, as the service names them; never resolved |
| `service` | string | MUST | `youtube`, `youtube-music`, `netflix`, … — the product that played it, as the export distinguishes them |
| `supersedes` | string | MAY | id of the earlier line this one replaces |

Anything else the source reports MAY be kept under `extra`.

## Rules

1. One line per watch and one per search. Watching the same video twice is two lines.
2. An advertisement is not a watch. YouTube's export marks an ad with `details: [{name: "From Google Ads"}]`; such an entry is skipped and counted, never a line.
3. An activity that is neither a watch nor a search (`Visited YouTube Music`, a post viewed) is skipped and counted; the profile does not grow a third action until a reader needs it.
4. `channel` is the service's name for the publisher, kept as spelled. A `Topic` channel of YouTube Music is an artist's name with ` - Topic` on the end; the profile keeps it as is, and a reader may trim it.
5. A search's `title` is the query, so one `title` search covers both. The url is the results page the export gives.

## Example (synthetic)

```json
{"at":"2026-03-04T09:00:00Z","end":null,"tz":"Europe/Oslo","source":"google-takeout","kind":"watch","tier":2,
 "payload":{"schema":"watch/v1","raw_id":"youtube:2026-03-04T09:00:00.123Z:5e2a4f0c9d1b7a3e","action":"watched",
 "title":"Splicing a three-strand rope","url":"https://www.youtube.com/watch?v=aB3dE5fG7hI","video_id":"aB3dE5fG7hI",
 "channel":{"name":"Knots by Ola","url":"https://www.youtube.com/channel/UCa1b2c3d4e5f6g7h8i9j0k1l"},"service":"youtube"}}
```

## Notes

- **Why not `browse/v1`.** A url and a title describe a page; a watch has a publisher and a service, and its title is a work's name rather than a page's. Keeping it apart lets a reader count videos without filtering urls.
- **Why searches are here and not in `browse/v1`.** A YouTube search is a step toward a watch, and the two sit on one timeline; a browser's address-bar search is a visit. Each stays with its history.
- **Why `end` is usually null.** Takeout records when a video was opened, not how long it played. Writing a guessed duration would be invention; a source that keeps the play time (a Plex log) can set `end`.
