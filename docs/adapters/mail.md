# Mail

One line per message. `logbook add mail` reads a Google Takeout `Mail/` export — `All mail Including
Spam and Trash.mbox`, twenty gigabytes for a mailbox that has been running for fifteen years — or any
mbox file or folder of them, and writes one `mail/v1` line per message (RFC 0015): who, when, the
subject, the thread, the labels, the body as text, the attachments by name and size. Tier 2 by default.

```bash
logbook add mail ~/Takeout/Mail --account you@example.org --skip-labels Spam,Trash   # the whole export
logbook add mail ~/Takeout/Mail/"All mail Including Spam and Trash.mbox" --since 2024-01-01
logbook add mail inbox.mbox --only-labels Inbox,Sent --attachments     # keep the attachments' bytes too
logbook add mail inbox.mbox --dry-run                                   # count, write nothing
logbook add mail inbox.mbox --restart                                   # from the first byte again
```

## What a message becomes

| Field | What it holds |
|---|---|
| `at`, `date` | the `Date` header in UTC, and as written with its own offset; a message with no readable `Date` takes the mbox separator's time and has no `date` (counted) |
| `raw_id`, `message_id` | the `Message-ID` without its brackets, `<account>:` first when `--account` names the mailbox; no `Message-ID` → `sha256:<digest of the message>` (counted). The dedupe key: the same export twice appends nothing |
| `thread` | the root of `References`, else `In-Reply-To`, else the message's own id; Gmail's own thread id is `extra.gmail_thread_id` |
| `from`, `to`, `cc`, `bcc` | `{email, name?}` as the headers spell them, the address lower-cased, the display name as written |
| `direction` | `sent` when the sender is one of `owner_emails` in `logbook.json` or the `--account`, else `received` |
| `labels` | Takeout's `X-Gmail-Labels`, split on commas |
| `body` | the `text/plain` part, else the `text/html` part stripped to text (`extra.body_from: html`); read from at most 64 KB of the part, a longer one cut and flagged `extra.body_truncated` |
| `size` | the message's length in bytes as the export stores it |
| `attachments` | one `{filename, media_type, bytes}` per attachment part, in order; with `--attachments` also `sha256` and `path` in the SPEC §1.1 store |

The people on a message are never resolved here. Every sender and recipient stays in the line as
`{email, name}`, the same ref a `resolution/v1` line names (RFC 0006), so one resolution of an
address covers the calendar, the transcripts and the mail; the names a mailbox uses for an address
are the candidates `people merge` proposes from. The adapter writes no resolution line of its own.

## Built for a 20 GB export

The file is read in 8 MB chunks and scanned for separator lines; one message is in memory at a
time, whatever its size. Headers are parsed by hand, the MIME tree is walked by byte offsets, and an
attachment is never decoded or copied: its length is counted from the base64 text (exact for base64
and unencoded parts). Only with `--attachments` is a part decoded, hashed and put in the store.
On a laptop this reads well over 40 MB/s, so an export of twenty gigabytes is read in under ten
minutes; the record's own writing (`append_many`, a checkpoint every 10,000 lines) is the rest of the
time. Every 10,000 messages a line on stderr says how many were read, how many megabytes, and the rate:

```
  10,000 messages · 412 MB read · 71.3 MB/s
```

**Resuming.** The inbox manifest, `inbox/manifest.json` beside the record, keeps a cursor per file
and per set of options: the byte offset of the last message the record holds, written after every
checkpoint. An import that stops — Ctrl-C, a crash, a full disk — picks up there the next time
`add mail` runs on the same file with the same options (`  All mail.mbox: resuming at 8,421,113,344 of
21,474,836,480 bytes`); a finished one reads nothing (`read to the end already`). The cursor is honoured
only while the file is the same one (the digest of its first 4 KB and its size are checked); a new
export, or `--restart`, reads from the first byte, and an import with other labels, `--since` or
`--account` is another import with a cursor of its own. The record never depends on the manifest:
re-adding an export appends nothing either way (ADR 0017); the cursor only saves the hours of reading.
A dry run never writes it.

**The benchmark.** `tests/test_mail_scale.py` generates a 500 MB synthetic mbox — fictional senders
at `example.org`, six short plain-text messages in ten, three HTML newsletters, one with base64
attachments of 20 KB to 1.5 MB, with threads, folded headers, quoted-printable and mboxrd escapes —
and asserts at least 40 MB/s and a flat peak RSS (under 200 MB for the 500 MB file), in a process of
its own. It is `slow`: `LOGBOOK_SLOW=1 uv run pytest tests/test_mail_scale.py`. The quick tests in
the same file check every message the standard library's `mailbox` finds is a line here, on a file
read in 4 KB chunks so separators fall across chunk boundaries.

## What is counted, never dropped silently

`add` reports: messages without a `Message-ID` (keyed by digest), timed by the mbox separator (no
`Date`), with the body taken from HTML, with the body cut at 64 KB, with undecodable bytes replaced,
attachments referenced or stored, and messages skipped by label. A message with neither a readable
`Date` nor a readable separator is the only one skipped (`skipped_no_date`).

`show` prints `✉ subject — from → to (n attachments)`, never the body; `show --raw` prints the body
under the row.
