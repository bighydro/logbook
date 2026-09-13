# Adapters

One adapter per source. `run(input_path, since) -> iterator[dict]` where each dict has the keys `at, end, tz, source, kind, tier, payload` (see SPEC §2) — everything except the chain fields, which the logbook adds on append.

Rules: pure by default (no network), never write to the source, never invent `tier` lower than the source deserves, fixture-tested with **synthetic** data only.

Planned first: `google-takeout`, `apple-health`, `whatsapp`. Wanted: strava, garmin, immich, dawarich, telegram, imessage, bank-csv (generic, with mapping files), spotify, letterboxd, ics.
