# RFC 0048 — payload profile `social/v1`: an act on a social network

Status: draft · 2026-10-30 · comment period: two weeks

One act between the owner and an account on a social network, as the network's own export recorded it: the owner followed an account or was followed by one, marked it a close friend, blocked or restricted it, asked to follow it or was asked, stopped following it; liked a post, commented on one, liked a story, searched for a profile. The first writer is the `instagram` adapter (Meta's "Export your information" archive); an export of another network that keeps the same acts writes the same profile with its own `network`.

`social/v1` is a new profile, not one of the RFC 0031 freezes: its schema may change while this RFC is a draft.

## Why a new profile

Nothing standing fits, and each near miss would bend a frozen profile:

- `message/v1` (RFC 0008) is one message in a conversation; a follow has no conversation and no body, and a comment on a post sits in no chat the export names.
- `browse/v1` (RFC 0017) is a page the owner opened; its `url` is MUST and its `action` is `visit`, `bookmark` or `save`. A follower is not a page the owner opened, and a like is not a bookmark.
- `event/v1` (RFC 0009) is the calendar's planned layer of a day. `github` writes its acts as events with a reason of its own, but a follow listed among a day's plans would be read as a plan.
- `resolution/v1` (RFC 0006) says which entity an identifier refers to, at the time it was resolved; a follow is a relationship at the time it began, and writing one as a resolution would mint people the owner never confirmed.
- `watch/v1` (RFC 0018) carries YouTube's searches beside its watches because they are the same history; a profile search is not a watch.

One profile with an `action`, as `browse/v1` and `watch/v1` have, rather than one per act: every act has the same fields (an instant, a counterpart, maybe a url or a text), and a profile per act would be the same table eight times.

## Line

`kind` MUST be `social`. `tier` MUST be 2: who the owner follows, blocks and searches for says as much about them as their browsing does, and a comment carries their words to someone else's post. `at` is the act's time as the export gives it; `end` is null. `source` is the adapter (`instagram`); `tz` is the record's zone.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"social/v1"` | MUST | |
| `raw_id` | string | MUST | `<action>:<the act's time as the export spells it>:<first 16 hex of sha256 of the counterpart, the url and the text>` — no export gives the act an id, and the act, its instant and what it was about are its identity. The same export read twice, in either folder layout, gives the same ids |
| `network` | string | MUST | `instagram`, … |
| `action` | string | MUST | `follow`, `followed_by`, `close_friend`, `block`, `restrict`, `follow_request_sent`, `follow_request_received`, `unfollow`, `like`, `comment`, `story_like`, `search` |
| `counterpart` | object | SHOULD | the other account, source-native (RFC 0006 `ref` shape): `{ kind: "handle", value: "<network>:<handle>" }`, the handle in lower case. For a like or a comment, the owner of the post; for a search, the profile searched for |
| `url` | string | MAY | the link the export gives: the profile, the post |
| `text` | string | MAY | a comment's words, verbatim |
| `supersedes` | string | MAY | id of the earlier line this one replaces |

Anything else the source reports MAY be kept under `extra` (`instagram`: `list`, the export file's name without its number, e.g. `pending_follow_requests`).

## Rules

1. One line per act the export lists. A follower listed in two exports is one line (the same `raw_id`); an account followed, unfollowed and followed again is three lines, when the exports show all three.
2. The counterpart is never resolved here. A handle becomes a person by a `resolution/v1` line the owner confirms (`people review`), never by the adapter, and never by matching it to a name.
3. A list is a snapshot, not a history. An account missing from a later export's followers is not an `unfollow`: only the network's own list of unfollows says that.
4. An act without a time is skipped and counted. The record has no instant to put it on, and an export's `0` is no time.
5. A `social` line is not company (SPEC §3.2.5), not evidence of a stay and not a message exchanged: no reader counts a follower as someone the owner was with.

## Example (synthetic)

```json
{"at":"2026-05-06T00:00:00Z","end":null,"tz":"Europe/Oslo","source":"instagram","kind":"social","tier":2,
 "payload":{"schema":"social/v1","raw_id":"followed_by:1778025600:99b384026587ee43","network":"instagram",
 "action":"followed_by","counterpart":{"kind":"handle","value":"instagram:ola.example"},
 "url":"https://www.instagram.com/ola.example","extra":{"list":"followers"}}}
```

## Open questions

1. Should a reader show the day's `social` lines at all, and where? Nothing reads them yet; they are kept so the record has them.
2. Should `people review` observe a counterpart (a handle followed both ways) as a person? Today it reads mail, message, transcript and event lines only, and a follower list would fill the queue with accounts that have no name to match by.
