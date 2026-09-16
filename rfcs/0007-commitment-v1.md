# RFC 0007 — payload profile `commitment/v1`

Status: draft · 2026-09-16 · comment period: two weeks

Something the owner said they would do, or someone said they would do for the owner. A commitment is open until evidence closes it. This is the profile behind "nothing falls through the cracks": the log holds the promise, and the log holds the proof it was kept.

## Line

`kind` MUST be `commitment`. `tier` SHOULD be 2. `at` is when the commitment was made; `end` is the moment it is due, or null when there is no deadline. `source` is where it came from — `manual`, or the adapter/engine that found it (a transcript pass, an email pass).

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"commitment/v1"` | MUST | |
| `text` | string | MUST | what was promised, in the words it was made in |
| `direction` | string | MUST | `owed_by_owner` or `owed_to_owner` |
| `counterparty` | object | SHOULD | who the other party is, source-native: `{ kind, value }` as in `resolution/v1`, or `{ kind: "name", value: "..." }` when only a name is known |
| `due` | RFC3339 | MAY | the deadline, if one was stated. Mirrors `end` |
| `origin` | string | SHOULD | the id of the line it was found in (a transcript, a message) |
| `certainty` | string | MAY | `stated` when the words were explicit, `inferred` when a model read it into them |

## Closing

A commitment is closed by a **separate line**, never by editing it:

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"commitment-close/v1"` | MUST | |
| `closes` | string | MUST | the id of the commitment line |
| `outcome` | string | MUST | `kept`, `dropped`, or `void` (it stopped applying) |
| `evidence` | array | SHOULD | ids of lines that show it: the email that went, the meeting that happened, the payment that cleared |
| `note` | string | MAY | the owner's words |

`kind` MUST be `commitment-close`; tier follows the commitment.

## Rules

1. Open commitments are derived, not stored: a commitment is open when no `commitment-close` closes it. Nothing keeps a mutable status.
2. A commitment closed twice takes the close written last (as in RFC 0003).
3. A model-found commitment (`certainty: "inferred"`) is a draft: a surface MAY show it, and the owner confirms it by writing a `manual` commitment that supersedes it, or retracts it (RFC 0003). An inferred commitment is never closed automatically by another inference.
4. Evidence is a pointer to lines already in the log, never a copy of them.
5. A commitment with no counterparty is valid — a promise to oneself is a commitment.

## Example (synthetic)

```json
{"at":"2026-03-02T19:40:00Z","end":"2026-03-09T00:00:00Z","tz":"Europe/Oslo","source":"manual","kind":"commitment","tier":2,
 "payload":{"schema":"commitment/v1","text":"send Ola the mooring photos","direction":"owed_by_owner",
 "counterparty":{"kind":"email","value":"ola@example.org"},"due":"2026-03-09T00:00:00Z","certainty":"stated"}}
```

and, a week later:

```json
{"at":"2026-03-07T08:12:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"commitment-close","tier":2,
 "payload":{"schema":"commitment-close/v1","closes":"0195e4a1-2b30-7c19-8f02-6d1a9c3b4e55","outcome":"kept",
 "evidence":["0195e6f0-77a2-7bd4-9e11-2c8b0a4f1d93"]}}
```

## Notes

- **Why not a task manager.** A task list holds intentions; this holds *promises to people*, and closes them with evidence rather than a checkbox. The two can coexist — a surface may push an open commitment into whatever task system the owner uses — but the record's version is the one with proof attached.
- **Surfacing.** Which open commitments deserve attention, and when, is a surface's decision (ADR 0005: one evening message), not this profile's.
- **Crossing.** Commitments are the most useful thing an assistant can read and the most personal; tier 2 means they cross only after review (RFC 0005).
