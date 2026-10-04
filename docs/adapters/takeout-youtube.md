# Takeout: YouTube and YouTube Music → `watch/v1`

`Takeout/YouTube and YouTube Music/history/` holds `watch-history` and `search-history`, as JSON when
the owner asked Takeout for JSON and as HTML otherwise, which is Takeout's default. The adapter is
`google-takeout-youtube` (`takeout-youtube`) and reads both flavours; `logbook add` recognises the
files and the `history/` folder:

```bash
logbook add ~/Takeout/"YouTube and YouTube Music"/history
logbook add takeout-youtube ~/Takeout/"YouTube and YouTube Music"/history/watch-history.html --dry-run
```

## What becomes a line

One `watch/v1` line (RFC 0018) per video watched and per search, tier 2, source `google-takeout`,
`at` the entry's time in UTC to the second. `action` is `watched` or `searched`, `title` the video's
title or the search's words, `url` the video's or the results page's, `video_id` the `v=` of a watch,
`channel` `{name, url?}`, `service` `youtube` or `youtube-music` from the product header. An ad
(`From Google Ads` under the details), an entry of another activity (`Visited …`) and one with no
time are skipped and counted; a removed video is a line with no url, counted.

## The two flavours

**JSON** is one array per file of `{header, title, titleUrl?, subtitles?, time, products, details?}`,
streamed with `ijson` (the `stream` extra: `pip install "openlogbook[stream]"`) one entry at a time. `raw_id` is `youtube:<time as spelled>:<sha256(url, else
the title)[:16]>`.

**HTML** is one Material card per entry: a `div.outer-cell` whose `header-cell` names the product,
whose first `content-cell` carries the activity and the video's link, the channel's link and the
time as `<br>`-separated lines, and whose caption cell lists `Products:` and `Details:`. The reader
walks that structure with the standard library's parser, fed a chunk at a time so a history of any
size streams, into the same entry shape, and the mapping is the same.

The HTML spells the time in the owner's own zone by its abbreviation, `Mar 4, 2026, 10:00:00 AM
CET` (newer exports put a narrow no-break space before `AM`; it is read as a space). The reader
never guesses a zone from an abbreviation: a time in `UTC` or `GMT` is read as it is; one whose
abbreviation is what the record's zone (`timezone` in `logbook.json`) uses at that wall-clock time
(`CET` in `Europe/Oslo` in March, `CEST` in June) is read in that zone; any other is skipped and
counted (`unknown zone`), since an export made under another zone says a time this reader cannot
place. `raw_id` carries the time as the file spells it, so the JSON and the HTML of one export are
two spellings of one watch: they dedupe within their own flavour, and an export should be added in
one flavour.

`My Activity/YouTube/MyActivity.json` is the same history under another product; the My Activity
adapter maps it through this adapter's own function, so a watch there and here is one line (it is
off by default; see [Google Takeout](takeout.md)).

The fixtures are `tests/fixtures/takeout/YouTube and YouTube Music/history/` (JSON) and `… (html)/`
(HTML): a rope-splicing video, a song, a removed video, an ad, a visit and a search, all invented.
