# Takeout: Maps (your places) → candidates for `places propose`, reviews as `highlight/v1`

`Takeout/Maps (your places)/` holds two GeoJSON files, one Feature per place with the point in
`geometry.coordinates`: `Saved Places.json`, the starred and saved places (`Title`, the day they were
saved under `Published`, the business name and address under `Location`), and `Reviews.json`, the
owner's reviews (the rating, the words, the date and the place). The adapter is `google-takeout-maps`
(`takeout-maps`); `logbook add` recognises either file and the folder.

```bash
logbook add ~/Takeout/"Maps (your places)"                       # the reviews become lines; the saved places are counted
logbook places propose --takeout ~/Takeout                        # the saved places as candidates for the unnamed stays
logbook places propose --takeout ~/Takeout --write                # Enter takes the saved place's name
logbook places import-takeout ~/Takeout --write                   # or every saved place into places.json at once
```

## A saved place is a name, not a line

Nothing happened at an instant when a place was starred, so a saved place is never a line: it is a
name for coordinates, which is what `places.json` holds (`logbook places`). `add` counts them
(`saved places left to places propose`) and writes nothing for them. They reach the record two ways:

- **`places propose --takeout PATH`** feeds them as candidates. `PATH` is the `Takeout/` root, the
  `Maps (your places)/` folder, the `Saved/` folder of list CSVs, or one file. Under each unnamed stay
  the saved places within 300 m are listed, nearest first, with the list they were saved to (`Saved
  Places`, `Want to go`, `Starred places`, the owner's own lists) and the day they were saved:

  ```
    1.   2.0 h · 59.9074,10.7390 · 1 stay   stay:owner:20260610T0800Z@59.9074,10.7390
          suggested: Havnekontoret
          saved: Havnekontoret · 59.9075,10.7389 · Saved Places · saved 2026-02-11 · 10 m away
  1 saved place near no unnamed stay; `logbook places add` names one:
          59°51'00.0"N 10°39'00.0"E · 59.8500,10.6500 · Saved Places · saved 2026-03-04
  ```

  The nearest saved place is the suggested name, ahead of a Timeline visit's semantic type (a name
  beats *Restaurant*); with `--write`, Enter adopts it and the naming goes in the record as a
  `note/v1` line, as any naming does. The saved places near no unnamed stay, and not already a named
  place, are listed after the proposals for `places add --lat --lon`. Under `--json` each proposal
  carries `saved` and the object `saved_elsewhere`, each candidate `{name, lat, lon, list, saved_at,
  address?, metres?}`.
- **`places import-takeout PATH [--write]`** proposes every saved place as an entry of `places.json`
  in bulk, never changing an entry already there.

A saved place without coordinates (a list CSV whose url names a place id, the `(0, 0)` Google gives a
place it could not locate) is reported and never geocoded: nothing goes on the network.

## A review is a highlight

A review is the owner's own words on a place at a date, which is what `highlight/v1` (RFC 0022)
carries for a book: one line per review, kind `highlight`, tier 2, source `google-takeout`, `at` the
review's date. The place's name is the `title` (its address when it has no name), the words are the
`quote` with `type` `highlight`, and stars with no words are a `bookmark` of the place; the address
is `location`; under `extra` the `rating` (1–5), the Maps `url`, the point as `lat`/`lon` and the
`country`. `raw_id` is `maps-review:<date as spelled>:<sha256(url, else the name)[:16]>`, so a
re-import appends nothing. Google has spelled the file two ways (`five_star_rating_published`,
`review_text_published`, `date`, `location.name`; earlier `Star Rating`, `Review Comment`,
`Published`, `Location.Business Name`) and the reader looks for both. A review with no date or no
place is skipped and counted.

The fixtures are `tests/fixtures/takeout/Maps (your places)/` and `tests/fixtures/takeout/Saved/`:
the Oslo persona's harbour office, a bathing spot and a chart shop, none of which exist.
