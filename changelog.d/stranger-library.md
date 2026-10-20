### Fixed
- What the Library says to someone reading the record for the first time (#334): the front page
  links Promises, Goals, Agents and the World, as the navigation does; a Day the record holds nothing
  for (`/today` on the demo, read months later) says so and names the record's first and last day,
  each a link; `/gaps` and `/assets` on a record that went quiet before yesterday say when, while
  every silence and age still runs to today; the Day's `with` row says "nobody confirmed; proposed
  below" when a row below proposes who was there; the headers of the Manifest, Ideas, Promises, Goals
  and Agents say "nothing read above tier N" or "no lines" for "tier N" and "tier -", the tiers
  explained on hover; the Manifest and Ideas say why what was seen and not placed has nothing to
  review, so the counts and the sentence under them agree.
- The text of a trip's route names its places (`show trips`, `show year`, `show trip`, `/trips`,
  the Journeys and a Journey's page): an unnamed stay is `near <place>, x km` or the nearest airport's
  city (`Zurich`), the coordinates only where nothing names it or where two stays side by side would
  read the same. The JSON keeps the label SPEC §3.2.6 gives. `show year` names an asset as it is
  registered ("aboard Nordlys", not "aboard nordlys"), and `show year --json` gives each trip's
  `asset_name`.
