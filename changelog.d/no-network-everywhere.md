### Tests
- `tests/test_no_network.py` runs every reader `logbook --help` names under the guard that refuses every
  connection, 147 forms where there were 46: `promises` and `promises tasks`, `goal list`, `chapter list`,
  `review` and each of its kinds, `status list`, `people` with `merge`, `review`, `drift` and `nearby`,
  `show person`, `asset` and `place`, `lab introductions` and `lab chapters`, `setup places propose` and
  `review`, `setup assets list`, `setup questions list`, `setup day_start`, `doctor` (with
  `--implausible` and `--packet`), `doctor sources`, `import inbox list`, `import attachments status`
  and `verify`, `key show`, `backup list`, and the dry runs of `derive flights`, `keepers` and
  `descriptions`, `day reflect`, `repair`, `export crossing` and `export trip-bundle`; and `show orgs` and
  `show org NAME` on the orgs of `tests/orgs_record.py`, since the demo names none. Every page `serve`
  answers is read under it too: `/journeys` and one journey, `/people` and one person, and `/world` join
  the eight there were, the Manifest, its people and one org's page read the orgs record, `/today` is
  held to its redirect and `/favicon.ico` to its empty answer. And
  `day reflect DAY --audio FILE`, with the Day page's recording form, is heard under it
  (`tests/test_day_reflect.py`). No reader or page asked for a connection; no code changed.
- `SECURITY.md`, Nothing leaves: `dream` and `transcript synthesize` join the commands behind which a
  socket opens, for the model endpoint the `dream` entry allows.
