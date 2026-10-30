# Instagram → `message/v1`, `call/v1`, `photo/v1`, `social/v1`

Instagram gives you everything it keeps about your account as one download: your direct messages,
who you follow and who follows you, your posts, stories and reels, your likes, comments and searches.
The adapter is `instagram` (`instagram-export` works too) and reads that download as it comes, the zip
or the folder it unpacks to; nothing is unpacked to disk and nothing is copied out of it.

## Ask Instagram for the export

In the Instagram app:

1. Your profile → the menu (☰) → **Accounts Center** → **Your information and permissions** →
   **Export your information** → **Create export**.
2. Pick the Instagram account, then **Export to device**.
3. **Customize information**: leave everything ticked (the adapter reads only what it needs, below).
   **Date range: All time.** **Format: JSON** — not HTML, which is the default and which Logbook does
   not read. Media quality does not matter to the record: media are hashed, never stored.
4. **Start export**. Instagram mails you when it is ready, from a few minutes to a few days later;
   download the zip (or each part, when it comes in parts) from the same page.

## Import it

```bash
logbook add instagram ~/Downloads/instagram-kari.n.example-2026-10-30.zip --dry-run
logbook add instagram ~/Downloads/instagram-kari.n.example-2026-10-30.zip
```

`--dry-run` reads everything, counts what would be new and writes nothing. A bare
`logbook add ~/Downloads/instagram-….zip` finds the adapter by itself. The unpacked folder works the
same way. An export in several zips is several `add`s, one per zip.

Adding the same export again writes nothing; adding a newer export later writes only what is new
(`N already in the record (same source and raw_id), nothing written twice`). Once added, the zip can
go: `logbook inbox list` says it is in the record, and `logbook inbox clean` moves or deletes it.

An HTML export is refused with one sentence and nothing is read: ask again, with **Format: JSON**.

## What becomes a line

All at tier 2, source `instagram`.

| What | Line | Notes |
|---|---|---|
| A direct message, in your inbox, your message requests or an archived chat | `message/v1` | `chat` is the conversation (`group` when more than two people are in it), `text` the message, `media_kind` its first attachment's kind; reactions, a shared post or reel (its link and its owner's handle), and each attachment's path in the export, digest and size under `extra` |
| A call in a chat | `call/v1` | who placed it, whether it connected, how long |
| An image or video of your posts, stories and reels | `photo/v1` | library `instagram`, the caption and the post it belongs to under `extra.post`, the place when the export kept the photo's coordinates |
| A follower, an account you follow, a close friend, a block, a restriction, a follow request sent or received, an account you stopped following | `social/v1` | `action` says which; the account as `instagram:<handle>` |
| A post you liked, a comment you wrote, a story you liked, a profile you searched for | `social/v1` | the post's owner, or the profile, as `instagram:<handle>`; a comment's words in `text` |

`social/v1` is a new profile, a draft: [RFC 0048](https://github.com/bighydro/logbook/blob/main/rfcs/0048-social-v1.md)
says why no standing profile fits.

**Not read**, and never opened: ads and the advertisers that used your activity, logins, devices and
security, your profile beyond your name, preferences and topics, and everything else the export holds.

## Meta's text encoding

Every string in Meta's JSON is stored as its UTF-8 bytes read as latin-1, so `Båten ⛵` arrives as
`B\u00c3\u00a5ten \u00e2\u009b\u00b5`. The adapter reads each one back before it writes anything; the record holds `Båten ⛵`.

## Two layouts

Exports since 2023 put most folders under `your_instagram_activity/` and the followers under
`connections/followers_and_following/`; older ones have `messages/`, `followers_and_following/`,
`content/` at the top. The adapter finds every file by its name, never by its folder, so both read
the same, and an older export and a newer one of the same account dedupe against each other.

## People

The export names the people in a chat by their **display name** only (`Ola Nordmann`), never by
handle; handles appear with follows, likes, comments, searches and shared posts. A message's sender
is therefore `instagram:<display name>`, kept as the name Instagram showed. Nobody is merged on import:

```bash
logbook people review
```

proposes each Instagram sender against the people the record already knows by the same name — from
your contacts, WhatsApp, mail — with the evidence, and writes nothing until you accept a proposal.

## Which one is you

Your messages are told from the others' by the name and username of the export's own profile. When
those are missing, the one person in every chat is taken for you, and the import says so (`also 1
owner taken as the one person in every chat`). When even that cannot tell, nothing is read, and the
message says to add your name as Instagram shows it to `policy/owner.json`:

```json
{"names": ["Kari Nordmann"]}
```

## Media

An attachment is referenced by its path inside the export and hashed (SHA-256 and size), never
copied into the record. `LOGBOOK_INSTAGRAM_HASH_MEDIA=0` skips the hashing for a quicker read and keeps
only the paths. A file the export does not hold (Instagram leaves some out) is marked
`media_missing`.
