# Google Takeout

One archive, many witnesses. Google's Takeout puts every product in its own folder under `Takeout/`,
and this project reads each with a sub-adapter of its own, all writing `source` `google-takeout`
(ADR 0008). Hand `logbook add` the product's folder, or name the adapter and hand it anything:

```bash
logbook add ~/Takeout/"Google Chat"                     # sniffed: the folder is recognised
logbook add takeout-chat ~/Takeout/"Google Chat"        # or by name, short or long (google-takeout-chat)
logbook add takeout-pay ~/Takeout/"Google Pay" --dry-run   # count against the record, write nothing
logbook add takeout-contacts ~/Takeout/Contacts         # merges with the people the record already knows
```

`--dry-run` runs the adapter, counts how many lines would be added and how many the record already
holds by `(source, raw_id)`, prints what the adapter skipped and why, and writes nothing: not a line,
not an attachment. Re-adding the same export appends nothing either way (ADR 0017): every line has a
`raw_id` the export spells the same way next time.

Every adapter here is pure: it reads the files, never writes them, and never goes on the network. The
fixtures the tests run against are synthetic Takeout folders in `tests/fixtures/takeout/` (the Oslo
persona, who does not exist). Google renames CSV columns and moves keys between exports; the readers
find what they need by what a header or key says, and a column that is not there leaves its field out.

## What each product becomes

| Takeout folder | Adapter (`takeout-…`) | Lines | Tier | Default |
|---|---|---|---|---|
| `Location History (Timeline)/`, `Records.json`, `Timeline.json` | `location` | `location/v1` | 1 | on |
| `Calendar/` | `calendar` (the `ics` adapter) | `event/v1` | 1 | on |
| `Google Photos/` | `photos` | `photo/v1` | 1 | on |
| `Keep/` | `keep` | `note/v1` | 2 | on |
| `Tasks/` | `tasks` | `task/v1` | 2 | on |
| `Chrome/` | `chrome` | `browse/v1` | 2 | on |
| `YouTube and YouTube Music/history/` | `youtube` | `watch/v1` | 2 | on |
| `Google Pay/` | `pay` | `transaction/v1`, `event/v1` for tickets | 3, 1 | on |
| `Google Chat/` | `chat` | `message/v1` | 2 | on |
| `Google Meet/` | `meet` | `call/v1` | 1 | on |
| `Contacts/` | `contacts` | `resolution/v1` | 2 | on |
| `Access Log Activity/` | `access-log` | `event/v1` | 3 | **off** |
| `My Activity/` | `activity` | `browse/v1`, `watch/v1` | 2 | **off** |

"Default" is `policy/import.json`: `logbook init` writes the two noisy products as disabled with a
reason (`every sign-in to every Google service; opt in`, `every search and app opened; opt in`), and a
record made before this file existed gets the same list on its first read. Remove the entry to opt in;
`logbook sources` shows the state. An adapter existing is not a decision to run it.

The first seven are described in the [adapters overview](README.md). The rest:

### Google Pay → `transaction/v1`, `event/v1`

`Google Pay/Google transactions/transactions_<account>.csv` is one row per payment: `Time`,
`Transaction ID`, `Description`, `Product`, `Payment Method`, `Status`, `Amount`, `Fee`, `Net Amount`,
the amount as text with its currency (`-129.00 NOK`, `NOK 2450.00`, `€4,99`). One `transaction/v1`
line per row (RFC 0021), tier 3 always; `--tier` is not an option of this adapter. The amount is signed
from your side: the sign in the text when it has one, else negative, since money left, unless the
status, product or description says refund, received, reversal or credit. The currency is the ISO code
or symbol in the text; `kr` names three currencies, so a row with only that is skipped and counted
(`without a currency`). The description is the merchant, the masked card the account, Completed is
`posted` and Pending `pending`, and the day in your zone is `date` when it differs from the UTC day.

`Google Pay/Passes/<id>.json` is one file per pass in Wallet. An event ticket, a transit pass or a
flight pass is one `event/v1` line (RFC 0009), tier 1: the event's name (or `Aker brygge →
Nesoddtangen`, or `XY 561 OSL → ZRH`), its span, the venue as `location`, the issuer as the calendar;
seat, gate, terminal and the transit type under `extra`. A time with no zone on a flight pass is read in
the record's zone and flagged `extra.local_times`. The ticket holder's name, the passenger's name and an
account number are never written. Loyalty cards, offers and gift cards are counted, not lines.

### Google Chat → `message/v1`

`Google Chat/Groups/<DM xxxx | Space xxxx>/messages.json`, one folder per conversation, with
`group_info.json` and the attached files beside it, and `Google Chat/Users/<User xxxx>/user_info.json`,
you. One `message/v1` line per message (RFC 0008), tier 2. The chat is the folder's name; a `DM` or a
two-member group is `direct` and named for the other member, a space is `group` and named by
`group_info.json`. `from_me` is whether the sender is you: `owner_emails` in `logbook.json` when set,
else the one user under `Users/`; with neither every message reads as received and the run says so.
The sender is an email ref with the name Chat showed, never resolved (RFC 0006). The first attached
file is hashed into `media` and stored only with `--attachments`; reactions, links and the topic go
under `extra`. `raw_id` is `chat:<message_id>`; a message without one is keyed by its date as spelled
and its text, and counted.

### Google Meet → `call/v1`

`Google Meet/Call history/Call history.csv`, one row per call you were in. One `call/v1` line per row
(RFC 0012), tier 1: `outgoing` when the organizer is you (`owner_emails`), `incoming` otherwise, with
nobody named every call is incoming and the run says so; `answered` true (you joined, even a call
nobody else came to); the duration and the end when it lasted; the organizer as an email ref when not
you; `service` `meet`; the meeting code, the participant count, the product, the device and the call
type under `extra`, with your `role`. `raw_id` is `meet:<conference id>`.

### Contacts → `resolution/v1`

`Contacts/All Contacts/All Contacts.vcf`, every contact as a vCard, and one folder per label repeating
the contacts under it; a folder with `All Contacts/` is read from that file alone. One entity per card
(a person, or a company when only `ORG` is set) and one `resolution/v1` line per email and phone (RFC
0006), as `ios-contacts` writes them: emails lower-cased, phones through the shared normaliser with
`LOGBOOK_DIAL_PREFIX`, `raw_id` the ref. **Merging:** `logbook add` hands the adapter every ref the
record already resolves; a card whose email or phone the record knows takes that entity's id (nothing is
minted for a person `ios-contacts` resolved) and only its refs the record does not yet hold become
lines, the known ones counted (`already resolved in the record`). A second import of the same people,
from either source, appends nothing. A card with no email and no phone is skipped and counted.

### Access Log Activity → `event/v1` at tier 3 (off by default)

`Access Log Activity/Activities - A list of Google services accessed by.csv`, one row per access to a
Google service from your account: when, which product, what (a sign-in, a password change), from which
address, with which browser, and, when Google had them, the device and the city it placed the address
at. One `event/v1` line per row, **tier 3**: a sign-in from a city on a date says where your devices were,
which is a location fact as sensitive as a transaction. The title is `Gmail: Sign in`, the calendar
`Google Account access`, the location the city and country when the row has either; the address, the
user agent, the device and the place go under `extra`. Every open of Gmail is a row, so the source is
off until you say otherwise.

### My Activity → `browse/v1`, `watch/v1` (off by default)

`My Activity/<Product>/MyActivity.json`, when you asked Takeout for JSON (the `.html` is not read).
What fits a profile is a line, tier 2: a search and a visited result are `browse/v1` visits with the
query or page as the title and `google-<product>` as the browser; an app opened under Android is a
visit to its Play Store page, browser `android`; a YouTube entry goes through the YouTube adapter's own
mapping (ADR 0017), so a watch here and the same watch in `YouTube and YouTube Music/history/` are one
line. A Chrome entry is skipped and counted: `Chrome/History.json` has the same visit with Chrome's own
clock, and `takeout-chrome` reads that. Ads, entries with no url or no time, and other activities
(`Viewed area …`, `Said …`) are skipped and counted. Google's guess at where you were when you
searched is kept as text under `extra.location_hint`, never as a location line.

## What is not read

Gmail is its own adapter (`mail`, `logbook add mail ~/Takeout/Mail`). Drive, Maps (saved places go
through `logbook places import-takeout`), Fit, Play, Assistant, Home, News, Shopping, Voice and the rest
of the archive are not read yet; drop a folder in `inbox/` and it stays there until an adapter exists.
A whole `Takeout/` folder handed to `add` is walked file by file today (the package's own `walk` is on
the roadmap), so hand it a product's folder, or the archive one product at a time.
