# Weather

The weather of the places your days were spent at, one `weather/v1` line (RFC 0026) per local day and
place: the lowest and highest temperature, the precipitation, the strongest wind, a WMO weather code,
sunrise and sunset. The places come from your own track, the values from Open-Meteo's free historical
archive, and nothing finer than a tenth of a degree ever leaves the machine.

```bash
logbook sync weather --dry-run                       # how many cluster-days, how many requests; nothing fetched
logbook sync weather                                 # since the last run (or the record's first day), to yesterday
logbook sync weather --since 2026-06-01 --until 2026-06-30
logbook day 2026-06-16                               # … weather  14°–27° · 0.3 mm · wind 19 km/h · partly cloudy · sun 05:30–21:25
```

Tier 1, `evidence` `external`: the line says what a provider says about a 10 km square on a day, and
no reader derives presence, company or an act from it.

## What is asked, and about where

For every local day of the window the command takes the owner's overnight stay (the night of the day,
as `derive stays` and the Day read it) and every stay of three hours or more that touches the day,
including the anchorages of a stay aboard a boat. Each place is rounded to **one decimal of latitude
and longitude** — about 11 km north to south and, at Oslo, 6 km east to west — and the day's places
are deduped after rounding: home and an office across town are one place, so one line. A day the
track does not place (no stay reached three hours, the night was in transit) gets no line.

The window: `--since` and `--until` are local days. Without `--until` the window ends yesterday
(today is not over). Without `--since` it starts a week before the last day the previous run covered
(`state/weather.json`), so points that reach the record late still get their days; the first run
starts at the record's first day with a location line. Days already in the record are counted as
already there and not written again; the cache (below) means they are not fetched again either, so a
backfill with `--since` costs only the days that are new.

## Open-Meteo

[Open-Meteo](https://open-meteo.com/) serves daily values from a reanalysis for any point on earth from
1940 on, free for non-commercial use, without a key. Days older than a week come from the archive API
(`archive-api.open-meteo.com`, which runs a few days behind the present); the last seven days from the
forecast API (`api.open-meteo.com`), whose past days are the model's analysis, not a forecast. Open-Meteo's
data is under CC BY 4.0: a page that shows these lines should say "Weather data by Open-Meteo.com".

One request covers one place and a run of days: the days a place needs are sorted and split only where
a gap exceeds a week or a run a year, so a fortnight at one place is one request and a year at home is
one too. Between requests the command waits a second. The provider asks for fewer than 600 calls a
minute and 10,000 a day; a record's whole history is a few hundred requests, and the daily run is a
handful. A request that fails is said on stderr, the others still go out, the run exits 1 and the
watermark stays where it was, so the next run asks again.

## The cache

Every day a response carries — the days asked for and the days between them — is kept under
`<root>/inbox/weather/<lat>_<lon>/<day>.json`, under the rounded coordinates, so a re-run never
refetches, and a stay that appears later for a day already fetched costs no request. `inbox/` is not
the record (SPEC §1): the cache can be deleted and the lines stand. A day the provider had no values
for (a place in the sea before the model covered it) is not cached and is counted
(`skipped … days the provider had no values for`), so it is asked again another time.

## `sync --all` and the schedule

`logbook sync --all` and the twice-daily schedule leave weather out unless you say so: set
`LOGBOOK_WEATHER=1` in the environment — for the schedule, a line in `~/.config/logbook/sync.env` —
and the source joins the run, each run covering the days since the last. Unset or `0`, the summary says
`weather  skipped (LOGBOOK_WEATHER not set)` and nothing is asked. By name, `logbook sync weather` needs
no variable. A `{"source": "weather"}` entry in `policy/import.json` disables it either way.

## What the readers show

- `day` adds one `weather` row after the health line when the day has lines: the place of the night
  when the day has one, else the first, and `· 2 places` when the day was spent in more than one. The
  JSON carries the row with every place of the day under `places`, each with its line id. A day with
  no weather lines has no row and `"weather": null`.
- `year` adds one `weather` row — the coldest and warmest day, the precipitation summed over the days
  (the wettest place of a day, so two places never count one rain twice), the wet days (1 mm or more),
  the strongest wind, and how many of the year's days have a line — and the HTML page a section.
- `trips` says the same for each trip's days, first to the return day, after the people.
- `serve` shows the Day's row under a Weather heading.

## Privacy

What leaves the machine is a GET to Open-Meteo with a latitude and a longitude of one decimal, two
dates, the list of daily variables, and the record's time zone; no key, no account, no cookie, no
referrer; the user agent names this software and its version. The provider learns that someone asked
about a 10 km square on some days — a valley, not a street; a town, not a house — and over many
requests, the squares a person's life touches. If that is more than you want a third party to know,
leave `LOGBOOK_WEATHER` unset, run the command for the days you choose, or disable the source in
`policy/import.json`. The line, the cache and the request all carry the same rounded coordinates:
the stays themselves stay in the location lines, and nothing here lets a reader of the weather lines
rebuild them. The request never carries the record's owner id or any identifier of yours.

The reference adapter is `logbook/adapters/weather.py`; the clustering and the readers' side are in
`logbook/weather.py`; the tests run against a fake Open-Meteo in memory and never open a socket, and one
of them checks every request URL for a coordinate with more than one decimal.
