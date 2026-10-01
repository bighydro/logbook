# RFC 0017 — payload profile `browse/v1`

Status: draft · 2026-10-01 · comment period: two weeks

A page the owner opened, bookmarked or saved for later: Chrome's history and bookmarks from a Google Takeout export, Safari's `History.db` from an iPhone backup or the Mac, a Pocket export. One profile for all of them, so that "what was I reading on the 4th" is one query however many browsers and apps the owner uses.

## Line

`kind` MUST be `browse`. `tier` MUST be 2: browsing history is as private as mail, whatever the page; a reader that wants to share a day never shares it by default. `at` is the visit time, or the time the bookmark or save was made; `end` is null (a browser records when a page was opened, not when it was left). `source` is the adapter (`google-takeout`, `safari`, `pocket`); `tz` is the record's zone.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"browse/v1"` | MUST | |
| `raw_id` | string | MUST | `<app>:<time as the source spells it>:<first 16 hex of sha256(url)>` — no browser keeps a stable visit id across exports, and the instant plus the page is the visit's identity. Chrome `chrome:<time_usec>:…`, a Chrome bookmark `chrome-bookmark:<add_date>:…`, Safari `safari:<visit_time>:…`, Pocket `pocket:<time_added>:…` |
| `url` | string | MUST | the page, as the source spells it; an entry with no url is skipped and counted |
| `title` | string | MAY | the page's title as the source kept it; absent when empty |
| `action` | string | MUST | `visit` (the page was opened), `bookmark` (kept in the browser's bookmarks), `save` (kept in a read-later app) |
| `browser` | string | MUST | the app that recorded the entry: `chrome`, `safari`, `firefox`, `pocket`, … |
| `transition` | string | MAY | how a visit came about, Chrome's `page_transition` lower-cased (`link`, `typed`, `auto_bookmark`, `reload`, `form_submit`, …); absent for a source that does not say |
| `folder` | string | MAY | a bookmark's folder path, `/`-joined from the root (`Bookmarks bar/Boat`) |
| `tags` | array of string | MAY | a saved page's tags, as the app spells them |
| `status` | string | MAY | a saved page's state: `unread` or `archived` |
| `supersedes` | string | MAY | id of the earlier line this one replaces |

Anything else the source reports MAY be kept under `extra`: Chrome's `page_transition_qualifier` and `client_id`, Safari's `load_successful` when false, a redirect's position.

## Rules

1. One line per visit, bookmark or save. Two visits to one page are two lines; a bookmark and a visit to the same page are two lines with different `action`.
2. The url is kept whole, query string included. The profile does not strip tracking parameters or resolve redirects: what the browser recorded is what the record keeps, and a reader may clean on its way out.
3. A bookmark's `at` is when it was added, when the source keeps that; a bookmark with no date is skipped and counted (the record has no instant to put it on).
4. The same history reached two ways is one line: Safari's `History.db` from a phone backup and from the Mac it syncs to spell the same visit the same way, and so does Chrome's export of a profile synced to two machines. The `raw_id` is built from the visit, never from the file or the device.
5. Nothing here is the page's content. A page worth keeping is an attachment (SPEC §1.1) on a `note/v1` line, not a `browse/v1` field.

## Example (synthetic)

```json
{"at":"2026-02-11T08:00:00Z","end":null,"tz":"Europe/Oslo","source":"google-takeout","kind":"browse","tier":2,
 "payload":{"schema":"browse/v1","raw_id":"chrome:1770796800000000:1a6ee1a9f1c5be3e","url":"https://vans.example.org/booking/42",
 "title":"Van hire - Oslo","action":"visit","browser":"chrome","transition":"typed"}}
```

## Notes

- **Why one profile for visits and bookmarks.** A bookmark is a visit the owner chose to remember; the same `url`, `title` and time fields describe it, and `action` tells the two apart. A third profile for read-later apps would be the same fields a third time, so Pocket writes `save`.
- **Why tier 2 and not 1.** SPEC §4 lists "public activity" at tier 1. Reading is not public: a browser's history says what the owner was looking up, which is the most private thing a record holds short of money and health.
- **Why `raw_id` hashes the url.** A url can be two kilobytes; the id is for dedupe, not for reading, and sixteen hex digits of its digest beside the instant are enough to tell two visits in one microsecond apart.
