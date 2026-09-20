# Adapters

One adapter per source. A module with three names: `NAME` (the `source` it writes), `sniff(path) -> bool` ("is this file mine?", cheap, never raises) and `run(input_path, since) -> iterator[dict]` where each dict has the keys `at, end, tz, source, kind, tier, payload` (see SPEC §2) — everything except the chain fields, which the logbook adds on append. Give every line a stable `payload.raw_id`; `logbook add` skips lines whose `(source, raw_id)` are already in the log, so re-adding an export appends nothing.

Adapters built by the project ship inside the package under `logbook/adapters/` (ADR 0012); the first are `dawarich`, `google-takeout-location` (Google Takeout's Records.json and the on-device Timeline.json; the `logbook/adapters/takeout/` package will gain photos, calendar and activity as siblings) and `ios-contacts` (an iPhone's AddressBook.sqlitedb → one `resolution/v1` line per phone number and email address, minting the record's person and company ids — how a record gets its people, ADR 0013.2) and `whatsapp` (an iPhone's ChatStorage.sqlite → one `message/v1` line per message, RFC 0008; media by digest only until the §1.1 store exists). Third-party adapters are separate packages registering the `logbook.adapters` entry point. `logbook add <file-or-folder>` tries every registered adapter's `sniff` and runs the first match.

Rules: pure by default (no network), never write to the source, never invent `tier` lower than the source deserves, fixture-tested with **synthetic** data only.

Planned first (ADR 0008): `google-takeout`, `apple-health`, then `email`.

Wanted — pick one and open an issue with the adapter template: immich, dawarich, strava, garmin, apple-fitness, eight-sleep, oura, withings, telegram, imessage, signal, gmail, ics-calendar, google-calendar, flighty, flightradar24, notion, obsidian, spotify, apple-music, letterboxd, goodreads, kindle-highlights, youtube-history, chrome-history, twitter-archive, instagram-export, bank-csv (generic, with per-bank mapping files), revolut, paypal, amazon-orders, uber, airbnb, vivino, steam, boat-passage logs.
