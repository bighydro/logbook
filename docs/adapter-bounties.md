# Adapter bounties

The adapters not yet written, each with the export it would read, the profile it would write and the tier. The bounty is the credit line in the CHANGELOG and your name on the adapter; there is no money in it. Pick one, open an issue named `adapter: <source>`, and start from `adapters/template/` ([Contributing](CONTRIBUTING.md), *Adapters*).

**Good first adapter** marks a source whose export is a documented file in a plain format, whose profile already exists, and whose fixture can be written by hand in an hour. Everything else needs a store to reverse, a profile to propose, or an extra to install.

Every adapter obeys the same rules: pure (no network on the default path), never writes the source, never lowers the tier the profile sets, gives every line a stable `raw_id` so a re-import appends nothing (ADR 0017), confirms a SQLite schema with `PRAGMA table_info` before reading it, and is tested on a **synthetic** fixture only. The sample person lives in Oslo and does not exist; her numbers are `07700 900xxx`, her addresses end in `example.org`.

Spotify and Pocket are not on this list: Pocket is in the package (`browse/v1`, a `save` per page) and Spotify is spoken for. The longer wish list, from Letterboxd to boat passage logs, is at the foot of [adapters/README.md](adapters/README.md).

| Source | Export | Profile | Tier | Good first adapter |
|---|---|---|---|---|
| Telegram | Telegram Desktop `result.json` | `message/v1` | 2 | yes |
| Signal | Signal Desktop's SQLCipher store, or an Android `.backup` | `message/v1` | 2 | no |
| Slack | workspace export, JSON per channel per day | `message/v1` | 2 | yes |
| Teams | a Graph or Purview export, JSON | `message/v1` | 2 | no |
| Strava | archive: `activities.csv` plus GPX and FIT | `health-sample/v1` (`workout`), `location/v1` | 3, 1 | yes, the CSV half |
| Garmin | Connect data export, JSON per domain | `health-sample/v1` | 3 | no |
| Oura | account export, CSV and JSON | `health-sample/v1` | 3 | yes |
| Notion | workspace export, Markdown and CSV | `note/v1` | 2 | yes |
| Mac Screen Time | `knowledgeC.db` on this Mac | `activity/v1`, to be proposed | 2 | no |
| HomeKit | none from Apple; Home Assistant's recorder store | `activity/v1`, to be proposed | 1 | no |
| Bank CSVs | one CSV per bank, a mapping file per bank | `transaction/v1` | 3, MUST | yes, each mapping |

## Telegram

**Export.** Telegram Desktop, *Settings → Advanced → Export Telegram data*, format *Machine-readable JSON*: a folder `DataExport_<date>/` with one `result.json` holding every chat as `chats.list[]`, each with `name`, `type` (`personal_chat`, `private_group`, `private_supergroup`, `private_channel`), `id`, and `messages[]` with `id`, `date` (ISO, local to the exporting machine, and `date_unixtime` beside it), `from`, `from_id` (`user123…`), `text` (a string, or a list of strings and typed spans for links and formatting), `reply_to_message_id`, `edited`, and for media `photo`, `file`, `media_type` and `mime_type` naming a file in the folder. A single chat can be exported alone with the same shape.

**Target.** `message/v1` (RFC 0008): one line per message; `chat` `{id, type: direct|group, name}` from the chat's `id` and `type`; `raw_id` `telegram:<chat id>:<message id>`; `from_me` when `from_id` is the exporting account's (the only `personal_chat` whose messages come from both sides, or `--owner` naming it); `sender` `{kind: handle, value: <from_id>, name: <from>}`, never resolved; `text` flattened to a string; `media_kind` from `media_type`; the file hashed into `extra.media` and stored only with `--attachments`. Service messages (joins, pins, calls) are counted, not logged. `at` from `date_unixtime`, never from the local `date`.

**Tier** 2 (MUST). **Good first adapter:** yes. The fixture is one `result.json` of two chats and six messages, written by hand.

## Signal

**Export.** Signal has no export. Signal Desktop keeps `sql/db.sqlite`, encrypted with SQLCipher, the key in `config.json` beside it (on recent versions wrapped by the OS keychain). Signal Android writes `signal-<date>.backup`, encrypted with a 30-digit passphrase the owner typed once; the iPhone keeps nothing a backup carries in clear. Reading either needs an extra (`sqlcipher3`, or a port of the Android backup framing), so this is an `openlogbook[signal]` adapter, and the passphrase comes from one environment variable, never a flag, as `import-backup` does for an encrypted iPhone backup.

**Target.** `message/v1`: one line per row of `messages` (Desktop) or `sms` and `mms` (Android); `chat` from the conversation, `direct` or `group`; `raw_id` the message's own id; `sender` `{kind: phone}` or `{kind: handle}` for an ACI-only contact, never resolved; media by digest. Disappearing messages that the store still holds are lines; those it has already dropped are not, and nothing is reconstructed.

**Tier** 2 (MUST). **Good first adapter:** no. The fixture is a tiny SQLCipher store made by the test itself with a known key; nothing from a real account.

## Slack

**Export.** A workspace admin's *Settings & administration → Workspace settings → Import/Export → Export*: a zip with `channels.json`, `users.json`, and one folder per public channel holding `<YYYY-MM-DD>.json`, each a list of messages with `ts` (the id, a second with microseconds), `user`, `text` (with `<@U…>` mentions and `<url|label>` links), `thread_ts`, `files[]`, `subtype` for joins and bot posts, and `user_profile`. Direct messages and private channels are in the export only on the plans that allow it; a user cannot export their own DMs.

**Target.** `message/v1`: one line per message; `chat` `{id: <channel id>, type: group, name: <channel name>}`; `raw_id` `slack:<channel id>:<ts>`; `from_me` from `--owner <user id>` or `owner_emails` matched against `users.json`; `sender` `{kind: handle, value: <user id>, name: <display name>}`, never resolved; `text` with mentions and links unwrapped to their labels; `reply_to` the thread's root `ts`; `files` hashed into `extra.media` when present in the zip. Joins, bot posts and channel topic changes are counted, not logged.

**Tier** 2 (MUST). **Good first adapter:** yes. The fixture is a folder of two channels and three days, `users.json` with three synthetic users.

## Teams

**Export.** Microsoft gives a person no chat export. An admin exports through the Graph *Teams export API* (`getAllMessages`, JSON per message with `id`, `createdDateTime`, `from.user`, `body.content` as HTML, `attachments`, `chatId` or `channelIdentity`) or through Purview eDiscovery, which produces a PST or a JSON of the same shape. The adapter reads a folder of those JSON files.

**Target.** `message/v1`: one line per message; `chat` the chat or channel, `direct` for a one-to-one chat, `group` otherwise; `raw_id` the message `id`; `sender` `{kind: email}` when the export carries the user's address, else `{kind: provider_id}`; `body.content` stripped to text as the `mail` adapter strips HTML, without a library. System messages (membership, meeting start) are counted.

**Tier** 2 (MUST). **Good first adapter:** no: the shape depends on which export an admin ran, and the fixture has to be invented from the Graph documentation.

## Strava

**Export.** *Settings → My Account → Download or Delete Your Account → Request Your Archive*: a zip with `activities.csv` (one row per activity: id, date, name, type, elapsed and moving time, distance, elevation, average heart rate and more, column names in the account's language) and `activities/` holding each activity's original file, `.gpx`, `.tcx` or `.fit.gz`.

**Target.** Two profiles. From the CSV, `health-sample/v1` (RFC 0014) type `workout`: `at` the activity's start, `end` from the elapsed time, `value` the duration in seconds, `extra.activity` the type, `distance_m`, `energy_kcal`, and the average heart rate as `extra`, never as a `heart_rate` line (it is an average, not a reading); `raw_id` `strava:workout:<activity id>`. From the GPX or FIT file, `location/v1` (RFC 0001) points with `tracker` `strava` and `raw_id` `strava:<activity id>:<unix seconds>`, so a day's track shows the run. The CSV half ships first and is complete on its own; the FIT half is a second issue, since FIT needs a decoder and `.fit.gz` files are large.

**Tier** 3 for the workout lines (health; SHOULD), 1 for the location points. **Good first adapter:** yes, the CSV half. The fixture is a six-row `activities.csv` with English headers and one with Norwegian ones.

## Garmin

**Export.** *Account → Data Management → Export Your Data*: a zip, after a wait, with `DI_CONNECT/DI-Connect-Fitness/<user>_summarizedActivities.json`, `DI-Connect-Wellness/` with sleep, heart rate, steps and stress as one JSON per day range, `DI-Connect-Aggregator/` with daily totals, and `DI-Connect-Uploaded-Files/` with every activity's FIT file. Keys are camel-cased, times are epoch milliseconds in GMT with a separate local offset, and the set of files moves between exports.

**Target.** `health-sample/v1`: `workout` spans from the summarized activities, `sleep` stages from the sleep files (Garmin's `deep`, `light`, `rem`, `awake` mapped to the profile's tokens; `light` to `core`), `resting_hr` and `hrv` readings, `steps` buckets from the daily totals when no finer data is present; `device` the product name; `raw_id` `garmin:<type>:<id or bucket start>`. A reading the Garmin app relayed from Apple Health is skipped and counted, as `withings` does.

**Tier** 3 (SHOULD). **Good first adapter:** no. The export is wide, undocumented and changes shape; the first version should read two files and count the rest.

## Oura

**Export.** The account page on the web, *Export data*: CSVs for sleep, readiness and activity, one row per day, with bedtime start and end, total sleep, time in each stage, lowest and average heart rate, HRV, and a JSON of the same through the v2 API for owners who run their own pull. Times are ISO with an offset.

**Target.** `health-sample/v1`: one `sleep` span per stage per night when the export carries the stage timeline (the API's `sleep` documents do; the CSV carries totals only, which become one `asleep` span per night and are said to be a total under `extra`); `resting_hr` (the night's lowest) and `hrv` (the night's average, in ms) as readings at the night's end; `steps` as a day bucket when nothing finer is there; `device` `oura`; `raw_id` `oura:<type>:<day or document id>`.

**Tier** 3 (SHOULD). **Good first adapter:** yes, the CSV. The fixture is a five-night CSV written by hand.

## Notion

**Export.** *Settings → Workspace → Export all workspace content*, format *Markdown & CSV*: a zip in which every page is `<Title> <32-hex page id>.md`, every database `<Title> <id>.csv` (one row per page, with the database's properties as columns, `Created` and `Last edited` among them when the database shows them) plus a folder of its rows as pages, and sub-pages nested in folders. The Markdown carries no timestamp of its own.

**Target.** `note/v1` (RFC 0010): one line per page, `text` the Markdown body, `title` from the file name, `folder` the path from the export root, `raw_id` `notion:<page id>@<modified>` where the modification time is the parent database's `Last edited` property when there is one, else the zip entry's time, and the adapter says which under `extra.time_from`; a page with neither is placed at the export's time and counted. A database CSV is not a line; its rows are, as pages. Images and files beside the page are hashed and stored only with `--attachments`.

**Tier** 2 (MUST). **Good first adapter:** yes. The fixture is a folder of four pages and one database, synthetic.

## Mac Screen Time

**Export.** None from Apple. This Mac keeps `~/Library/Application Support/Knowledge/knowledgeC.db`, a SQLite store the terminal can read with Full Disk Access: `ZOBJECT` rows whose `ZSTREAMNAME` is `/app/usage` or `/app/inFocus`, `ZSTARTDATE` and `ZENDDATE` as seconds since 2001, `ZVALUESTRING` the bundle id, with `ZSTRUCTUREDMETADATA` for the device. The phone's equivalent is not in a backup. A live adapter on the Mac itself, like `imessage`, reading a copy of the store.

**Target.** No profile fits. An app in the foreground for a span is not a browse, not a note, not an event; it is the `activity/v1` profile `rfcs/README.md` lists as to be written. Propose it first: `kind` `activity`, a span, `app` the bundle id, `device`, `raw_id` `screen-time:<device>:<start>:<bundle id>`; the window title never, the content never. Then the adapter.

**Tier** 2: what you were doing on the computer is as private as what you were reading. **Good first adapter:** no. An RFC comes first, and the schema of `knowledgeC.db` shifts between macOS versions, so every column is confirmed by `PRAGMA table_info` and a missing one leaves its field out.

## HomeKit

**Export.** None. The Home app keeps its data in iCloud and offers no export; a backup carries the home's configuration, not its history. The practical source is a home hub the owner runs: Home Assistant's `home-assistant_v2.db` (the recorder's `states` and `events` tables, a row per state change with `last_updated_ts` and the entity id) or Homebridge's log. The adapter reads a copy of the recorder store, or Home Assistant's history export (CSV per entity from the history panel).

**Target.** The same `activity/v1` profile Screen Time needs, or a sibling: a state change of a thing in the home (a door opened, a light on, someone arrived) is an occurrence, not a calendar entry. `raw_id` `home-assistant:<entity id>:<last_updated_ts>`; `extra` the state and its attributes; nothing a camera saw.

**Tier** 1 by default: a door that opened at 18:04 says you were home, as a location point does; the owner may raise it. **Good first adapter:** no, until the profile exists.

## Bank CSVs, by country

**Export.** Every bank gives a CSV of an account's transactions from its web site, and no two agree: the separator (`,` or `;`), the decimal mark (`.` or `,`), the date format, whether the amount is one signed column or two unsigned ones (debit and credit), the encoding (UTF-8, Latin-1, UTF-16 with a BOM), and the column names in the bank's language. Challenger banks (Revolut, Monzo, Wise, N26) are the regular ones: one signed `Amount`, an ISO date, a `Currency` column, English headers.

**Target.** One adapter, `bank-csv`, that writes `transaction/v1` (RFC 0021) and reads one **mapping file** per bank from `logbook/tables/banks/<country>-<bank>.json`: the header it recognises the CSV by (the sniff), the separator, decimal mark, encoding and date format, which columns are the date, the amount or the debit and credit pair, the counterparty and the memo, and the sign convention. `provider` is the mapping's name, `account` from `--account` or a column when the bank writes one, `merchant` the counterparty as written, `raw_id` the bank's transaction id when there is one, else `<provider>:<date>:<sha256 of the row>[:16]` and counted as such. `amount` is signed from the owner's side (rule 2), whatever the bank's convention.

The first mapping ships with the adapter; every further mapping is its own one-file issue with its own synthetic fixture. Wanted first, one bank per country to open the door: Norway (DNB or SpareBank 1: `;`-separated, comma decimals, debit and credit columns), the UK (Monzo or Starling), Germany (a Sparkasse CSV, `;`-separated, the CAMT column set), Switzerland (PostFinance or UBS), the Netherlands (ING), the US (Chase), and Revolut, which is one format across countries.

**Tier** 3, MUST, and an import option cannot lower it (RFC 0021 rule 7). **Good first adapter:** yes. The adapter is a few hundred lines; each mapping is a day. A fixture is ten rows for the Oslo persona, every merchant invented, every amount round; a real statement never enters the tree, scrubbed or not.

## Claiming one

Open an issue titled `adapter: <source>` saying which export you hold and which profile you will write; the captain answers within the week. One adapter per PR, named the same. The expected output file is generated on the first test run and checked in, so the review reads the fixture, the mapping and the expected lines side by side. A profile that does not exist yet goes through `rfcs/` first, two weeks of comment, then the adapter.
