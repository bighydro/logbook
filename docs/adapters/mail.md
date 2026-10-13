# Mail

One line per message. `logbook add mail` reads a Google Takeout `Mail/` export — `All mail Including
Spam and Trash.mbox`, twenty gigabytes for a mailbox that has been running for fifteen years — or any
mbox file or folder of them, and `logbook sync mail` reads the same mailbox live over IMAP
([below](#mail-imap)); either writes one `mail/v1` line per message (RFC 0015): who, when, the
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

## Mail (IMAP)

`logbook sync mail` reads the same mailbox live, over IMAP, so the record keeps up after the Takeout
import without another export: mail is the last daily source to get a live feed, and `promises` reads
it — the Sent mail most of all, which is where your own commitments are. IMAP is a standard: Gmail is
the first server, not the only one. The configuration is the environment and nothing else:

| Variable | What it is |
|---|---|
| `LOGBOOK_IMAP_HOST` | the server, `imap.gmail.com` for Gmail |
| `LOGBOOK_IMAP_USER` | the mailbox address; it is the `account` on every line and the prefix of its `raw_id`, so `add mail --account <the same address>` and the live pull dedupe each other |
| `LOGBOOK_IMAP_PASSWORD` | an app password. Never logged, never echoed, never written to any file by the command: it lives only in the environment of the user who runs the schedule (`~/.config/logbook/sync.env`, mode 600, which you write) |
| `LOGBOOK_IMAP_PORT` | optional, 993. TLS from the first byte, the certificate and the host name verified; never STARTTLS, never plaintext |
| `LOGBOOK_IMAP_FOLDERS` | optional, comma-separated. Without it: the folder the server flags `\All` — Gmail's `[Gmail]/All Mail`, found through `LIST` with SPECIAL-USE or the older `XLIST` — else `INBOX` and the folder flagged `\Sent` |

Gmail takes an app password only with 2-step verification on the account (Google Account → Security →
2-Step Verification → App passwords); the password is sixteen letters and is the only secret the
source holds.

```bash
logbook sync mail                                 # what is new in each folder since the last run
logbook sync mail --since 2026-03-01T00:00:00Z    # SEARCH SINCE that day instead (the record refuses the overlap)
logbook sync mail --dry-run                       # fetch the headers, count, write nothing
logbook sync mail --restart                       # every folder from its first message again
```

**Read-only, enforced.** A folder is opened with `EXAMINE`, never `SELECT`; bodies are fetched with
`BODY.PEEK[]`, which marks nothing read; `STORE`, `COPY`, `MOVE`, `EXPUNGE`, `APPEND` and every
flag change are absent from the source, and the tests assert on a fake server's command log that
none was ever sent.

**One parser.** Every message goes through the mbox adapter's own `parse_message`, with the
server's `INTERNALDATE` standing where the mbox separator's date would (counted
`date_from_internaldate`): the same fields, the same body cap, the same `raw_id`. Attachments are
named, sized and digested (`sha256`; the bytes are in hand) and never stored.

**Labels are a snapshot.** With Gmail's extension (`X-GM-EXT-1`) the labels and the thread id are
fetched with the message and written where the Takeout import puts `X-Gmail-Labels` and
`X-GM-THRID` — `labels`, spelled as Takeout spells them (`Inbox`, `Sent`), and
`extra.gmail_thread_id` — as they stood at ingest, once; the source never revisits a message to
update them. On a server without the extension the line carries neither.

**The watermark is for economy, the record's refusal is the guarantee.** Per folder the source keeps
`{uidvalidity, uid}` — the folder's `UIDVALIDITY` and the highest UID handled — under `resume` in
`state/mail.json`, written only once the lines up to it are in the record. A connection lost midway
leaves the mark at the last batch written and the next run resumes there; a folder whose
`UIDVALIDITY` changed is read from its first message again, which costs headers and writes nothing
new; a walk after a lost mark writes nothing new either, because the dedupe on `(source, raw_id)`
refuses what the record holds.

**Headers first.** Each batch of 200 UIDs is fetched as `Message-ID` and size alone, the record is
asked which of those it holds (one SELECT), and only the other bodies are fetched, in batches of at
most 32 MB by the sizes reported. The first run over a 400,000-message All Mail after the Takeout
import fetches no body the record would refuse. The progress line per batch says what is true —
`[Gmail]/All Mail: 1,200 fetched, 37 new, 1,163 already in the record` — never a guessed total, and
the summary names each folder's mark.

**Errors are one sentence, never a value.** The login refused names `LOGBOOK_IMAP_USER` and
`LOGBOOK_IMAP_PASSWORD`; TLS failed names `LOGBOOK_IMAP_HOST`; a folder not on the server names the
folder and `LOGBOOK_IMAP_FOLDERS`. `doctor` shows `sync:mail` configured or unconfigured by the
variables' names alone, and `sync --all` runs mail among the quick sources, so the four runs of the
schedule pick it up with no further configuration.

## What is counted, never dropped silently

`add` reports: messages without a `Message-ID` (keyed by digest), timed by the mbox separator (no
`Date`), with the body taken from HTML, with the body cut at 64 KB, with undecodable bytes replaced,
attachments referenced or stored, and messages skipped by label. A message with neither a readable
`Date` nor a readable separator is the only one skipped (`skipped_no_date`).

`sync mail` reports, besides these: messages already in the record by `Message-ID`, whose bodies
were never fetched, and folders read from the first message again because their `UIDVALIDITY`
changed.

`show` prints `✉ subject — from → to (n attachments)`, never the body; `show --raw` prints the body
under the row.
