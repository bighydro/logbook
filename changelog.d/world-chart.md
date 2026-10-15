### Added
- `logbook export world --style chart`: the record on a period chart, beside the globe in the same folder
  (`world-chart.html`; [the chart](docs/world.md#the-chart)). Mercator's sea chart drawn on the canvas with
  no image in it: sepia paper, the coasts of the same Natural Earth land hachured, a compass rose and its
  thirty-two rhumb lines, the graticule engraved with a graduated border, names and dates in the system's
  serif; stays as pricked positions, journeys as dashed tracks with day marks, assets named along their
  tracks; the globe's scrubber, line for line; the paper stays light in dark mode. The track is evidence:
  the page's record JSON is the globe's byte for byte, a track is the straight segments between its own
  fixes, an asset is at its last fix (never between two), and a day mark is at a recorded position, dated
  by the record's own days.
- `export world --chart FILE --control-points FILE --chart-credit "…"`: your own scanned chart (PNG or
  JPEG) as the paper. Three or more control points (pixel → lat, lon) fit an affine transform (a scan), or
  with six or more a projective one (a chart photographed at an angle); each point's leave-one-out
  residual is shown in a corner, and a fit worse than 1 % of the image's diagonal is refused, as are
  points in a line or a mirror image. The image is carried in the page (at most 4 MiB; a PNG over it
  downscaled, a JPEG refused), with its EXIF, XMP, text, profile and anything after its end left out, and
  nothing is fetched: the page's policy stays `default-src 'none'`. The legend credits the chart in your
  words.
- `export world --journey ID`: one page per journey, in either style — a trip as `show trips` names it
  (`trip:FIRST:LAST`, its days to the return day) or one `journey/v1` line (its days, it alone) — each its
  own file and its own `crossing/v1` line.
