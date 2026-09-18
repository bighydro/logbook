# RFC 0008 — payload profile `message/v1`

Status: draft · 2026-09-18 · comment period: two weeks

One message in a conversation — sent or received — from any messaging source: WhatsApp, iMessage/SMS, Signal, Telegram, email is *not* this profile (it has threads, subjects and many recipients; `mail/v1`, to be proposed). The line records what the source stored, nothing more: no sentiment, no extracted tasks, no resolved names.

## Line

`kind` MUST be `message`. `tier` MUST be 2 (SPEC §4: messages are tier 2). `at` is the message's own timestamp as the source stored it (sent time for outgoing, received time for incoming); `end` is null. `source` is the adapter: `whatsapp`, `imessage`, …

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"message/v1"` | MUST | |
| `raw_id` | string | MUST | the source's own stable message id (WhatsApp `ZSTANZAID`, iMessage `guid`). The dedupe key: re-importing the same store appends nothing |
| `chat` | object | MUST | `{ id, type, name? }` — `id` is the source's chat identifier (a JID, a chat guid), `type` is `direct` or `group`, `name` the source's display name if any |
| `from_me` | boolean | MUST | true when the owner sent it |
| `sender` | object | SHOULD when `from_me` is false | the sender as the source identifies them, source-native (RFC 0006 `ref` shape): `{ kind, value }` with `kind` one of `phone`, `email`, `handle`, `provider_id` |
| `text` | string | MAY | the body, verbatim; absent for pure media messages |
| `media` | object | MAY | attachment reference per SPEC §1.1: `{ sha256, path, bytes, media_type }`; absent when the source no longer has the file |
| `media_kind` | string | MAY | `image`, `video`, `audio`, `voice`, `document`, `sticker`, `location`, `contact`, `other` — the source's own classification |
| `reply_to` | string | MAY | `raw_id` of the message this replies to |
| `starred` | boolean | MAY | the owner's own flag in the source |
| `edited` | boolean | MAY | the source says this text was edited after sending |

Anything else the source reports MAY be kept under `extra`.

## Rules

1. One line per message. Group membership, read receipts and reactions are not lines in v1; a source that has them keeps them in `extra`.
2. `sender` is never resolved here. Mapping `4790…` to a person is a `resolution/v1` line (RFC 0006).
3. A deleted message that the source still records as deleted is still a line (with `extra.deleted: true`); the log keeps what the source kept.
4. Timestamps are the source's. Sources disagree about clock and timezone; the adapter converts the source's epoch to UTC and does not "correct" it.
5. A media file the source has lost is not an error: `media` is absent and `media_kind` says what it was.

## Example (synthetic)

```json
{"at":"2026-03-02T17:42:10Z","end":null,"tz":"Europe/Oslo","source":"whatsapp","kind":"message","tier":2,
 "payload":{"schema":"message/v1","raw_id":"3EB0A1F5C2D4E6B7","chat":{"id":"4790000000@s.whatsapp.net","type":"direct","name":"Ola"},
 "from_me":false,"sender":{"kind":"phone","value":"+4790000000"},"text":"mooring photos sent, check your mail"}}
```

## Notes

- **Volume.** A decade of WhatsApp is around a million lines. That is fine for the log (SPEC: files partition by month); it is the index and the engines that must stay streaming.
- **Why tier 2 for everything, even "hi".** The tier is about who wrote it, not what it says; a message body is someone else's words, and the crossing policy (RFC 0005) has to be able to treat every message the same way.
- **The chat, not the conversation.** `chat.id` groups lines; what a conversation *was about* is an engine's judgement, never stored here.
