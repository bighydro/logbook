### Fixed
- The readers print people by name only, the most days together first, never with a count beside a
  name: `rollup people` reads `Per Hansen  last 2026-06-30 · Office` (was `10 days · 0 nights · … ·
  11 confirmed`), and `show year`'s people section and its page the same; `show asset` and `show
  place` read `with  Anders Vik, Ola Nordmann, Sigrid Moen` (was `Anders Vik (2 days), …`); the
  Library's People page names each person with their last real contact, the evidence uncounted (was
  `10 days together`, `evidence · 11 lines`). `rollup places --with` lists each place's people, `with
  Per Hansen, Liv Berg`, and `rollup people --drifting` each person's last real contact (`last
  2026-06-12`), the quiet channels and the last shared place, without the counts, the fall or the days
  ago. The year's page sets `with` before a place's people, a trip's paper edition names a day's people
  last, and an org proposal on the Manifest the names it was seen under without their count. The counts
  stay in `--json`, unchanged; a person's own page (`show person`, /people/ID) still counts the days
  together.
- No date, clock time or other number sits beside a person's name with only separators between: the
  digest's promise reads `Kari Nordmann, due 2026-06-05 (by Friday)` (was `Kari Nordmann, 2026-06-05`)
  and `rollup listen`'s top artists `Kari Nordmann  played 0.2 h · 4 listens`.
- An event the owner accepts from the dream (`day sign --accept`, `day reflect --sign --accept`) is a
  tier-1 line, and names a person only from the resolutions at tier 1: someone the record knows only
  by tier-2 or tier-3 lines is no attendee, and their name in the title reads `someone`.
