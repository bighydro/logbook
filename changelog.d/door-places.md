### Added
- The Library's Places door (RFC 0047 §4.4), at `/places`: the globe of your life, drawn on the page as
  one inline SVG with home near the centre (the coastlines when `setup map` names the offline map file,
  the graticule alone without it), your places as dots and your trips as arcs, the lived ones muted and
  the ones ahead dashed and labelled; a time scrubber over the years of your life (`/places?at=YYYY`);
  Next, the trips and visits ahead from your calendar and your plan, each linking its span on Life;
  and Your places, home first, each with what it is in your words or a pencil placeholder. The
  register of `places.json` and the review queue stay under it, as they were.
- `/places/ID`: one place, with its days as a strip over the years (each a link to its Day), the people
  who were there with you, by closeness, and the trips that passed through it. `export site` writes a
  page per place beside `places.html`.
