# RFC 0009 — payload profile `event/v1`

Status: draft · 2026-09-18 · comment period: two weeks

One calendar entry as the calendar stored it: a planned thing with a title, a span, maybe a place and people. It is the *planned* layer of a day — what was meant to happen — and the log keeps it beside what did (location, photos, messages), so a Day can show both without confusing them.

## Line

`kind` MUST be `event`. `tier` SHOULD be 1 (SPEC §4: calendar). `at` is the start, `end` the end; both in UTC. An all-day event has `at` at local midnight (converted to UTC using `tz`) and `end` at the next local midnight, and `all_day` true. `source` is the adapter: `ios-calendar`, `google-calendar`, …

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"event/v1"` | MUST | |
| `raw_id` | string | MUST | the calendar's own stable id for the entry (iCal UID, or the store's row id when the UID is absent), suffixed with its last-modified time (see rule 5), e.g. `"<uid>@2026-03-04T10:15:00Z"`. The dedupe key |
| `modified_at` | RFC3339 | MAY | the source's last-modified time |
| `title` | string | SHOULD | the summary, verbatim; may be absent for private entries |
| `calendar` | object | SHOULD | `{ id, name? }` — which calendar it lives in, as the source names it |
| `all_day` | boolean | MUST | |
| `location` | string | MAY | the location text as entered; a coordinate, if the source has one, under `extra` — resolving it is a `resolution/v1` line |
| `organizer` | object | MAY | source-native ref `{ kind, value }` (RFC 0006), usually `email` |
| `attendees` | array | MAY | `[{ ref: { kind, value }, name?, response? }]` with `response` one of `accepted`, `declined`, `tentative`, `none` |
| `status` | string | MAY | `confirmed`, `tentative`, `cancelled` |
| `recurrence` | string | MAY | the recurrence rule as the source stores it (RRULE text), present only on a master entry |
| `recurrence_of` | string | MAY | the master's bare UID (not its suffixed `raw_id`, which changes when the master is edited) this occurrence belongs to, when the source materialises occurrences |
| `notes` | string | MAY | the description body |
| `supersedes` | string | MAY | id of the earlier line for the same entry (rule 5) |

Anything else the source reports MAY be kept under `extra`.

## Rules

1. One line per entry the source stores. A recurring event with no materialised occurrences is one line carrying `recurrence`; expanding it into occurrences is engine work, not adapter work (ADR 0011: log what the source has).
2. Attendees are never resolved here; the adapter keeps the email or handle the calendar has.
3. A cancelled entry is a line with `status: "cancelled"`, not an omission — the plan existed.
4. Sentinel-dated rows (the year 1601, the year 2030 for an open-ended series) are the store's placeholders, not items the source offers, so skipping them is consistent with ADR 0011: an adapter MUST skip rows whose start is outside a plausible window and report how many it skipped.
5. Entries are edited over time, and the log is not. An exported entry is a snapshot: the adapter's `raw_id` includes the last-modified time, so the same entry exported again after a change is a *new* line (the dedupe key differs), carrying `supersedes` = the earlier line's id. Readers show the latest by `supersedes`; the earlier entry is still in the record.

## Example (synthetic)

```json
{"at":"2026-03-03T08:30:00Z","end":"2026-03-03T09:15:00Z","tz":"Europe/Oslo","source":"ios-calendar","kind":"event","tier":1,
 "payload":{"schema":"event/v1","raw_id":"7E0C2D4A-9B1F-4C7E-8A2B-5D3E1F6A9C0B@2026-02-27T16:05:00Z","title":"Boat survey — Tromsø marina",
 "calendar":{"id":"A1B2","name":"Personal"},"all_day":false,"location":"Tromsø småbåthavn",
 "attendees":[{"ref":{"kind":"email","value":"ola@example.org"},"name":"Ola Nordmann","response":"accepted"}],"status":"confirmed"}}
```

## Notes

- **Planned versus happened.** A Day should be able to say "the survey was at 09:30; you were at the marina from 09:12 to 11:40". The first half is this profile; the second is an engine over location lines. Neither is corrected by the other.
- **Why tier 1.** Calendar entries are mostly about the owner's own time. An entry whose *notes* carry someone else's words is still tier 1 by default; a source that wants to be careful MAY set tier 2 on entries with attendees. The tier is set per line, so both are valid.
