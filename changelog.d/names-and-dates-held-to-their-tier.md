### Fixed
- Names, dates and sources in exports are held to the tier of the lines that give them. An output
  names a person only from resolutions at its own tiers: a name only a tier-2 or tier-3 resolution
  gives is no longer in a tier-1 `export vault`, `export site` or `export trip-bundle`, a name only a
  tier-3 resolution gives is in none below tier 3, and neither is counted in a bundle's
  `held_back.people`. `export site`'s Today, its span and its years and `export world`'s window come
  from the lines that cross, so a tier-3 health line no longer moves them; a vault's day page counts
  only the sources and flights that cross, and a day with none has no page; a trip bundle's
  `trip.json` carries only the flights, stays and moves whose lines cross.
- No date or clock time sits beside a person's name with only separators between: `people not-with`
  writes "from DAY to DAY", a proposed event "from 19:30 to 22:10" after its title, a site's people
  index names only, and a vault's year row puts its people last; the dream holds a sentence that
  sets a date or a clock beside a name, as it holds a count, and a confirmed event's title holds a
  surname and a genitive too.
