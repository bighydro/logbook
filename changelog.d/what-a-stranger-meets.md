### Fixed
- A night the record does not place reads `not recorded` on Today (`Last night: not recorded`), the Day
  page and `logbook day`; `in transit` only when the Day holds a move or a flight across that night.
  The Day's JSON is unchanged.
- `logbook doctor` before any record exists says `No record yet: run `logbook demo --out ~/Demo/Logbook` to try one, or
  `logbook setup` to start yours.` (it still exits 1). Its install line for an extra is the short one
  for how this Logbook was installed: `pipx inject openlogbook "openlogbook[ais]==…"` (with `PIPX_HOME`
  only when the venv is not in pipx's own home), `uv tool install --force "openlogbook[ais]==…"` (with
  the `--python` the receipt asked for, if any), and in a clone `uv sync --inexact --extra ais`, the
  clone named before it.
- doctor's `home` row is now `schedule` and says what it is: which machine runs the scheduled syncs.
  Its `restore-test` warn says to run `logbook backup DEST` once first when no backup is recorded.
- The Day page and Today, on a machine with no transcription engine, give the command that adds one
  for how this Logbook was installed (doctor's line), never `install openlogbook[transcribe]`.
- The Day page: the `with` row's words and its field are apart (`proposed below · add`); its footer
  says what is true, `Reflect and Sign, the with field and the stars write to your record; nothing
  else here does`, in place of `read-only`; a past day is headed by its weekday alone, the shape's
  name (`morning`, `live`, `evening`) being today's.
- `logbook show stats` names the record's format as such, `record format logbook/0.3`, beside a
  program whose version is another number.
- An asset is printed by its registered name, once: `rollup places`, `rollup nights`, `rollup people`,
  `rollup places --with`, `show year`, `show person`, `show place`, `people` and `places propose` read
  `aboard Nordlys` and `Nordlys (yacht)` (were `aboard nordlys` and `Nordlys (nordlys) (yacht)`). The
  JSON SPEC §6.1 compares keeps the id.
- `show trip`, the trip's page and its paper say the day you came home in words, `back on 21 June`,
  for the morning after the last night (SPEC §3.2.6's `until`, unchanged in the JSON); they said
  `until 2026-06-21`, which read as one night too many.
- `show person` counts a person's days together as `rollup people` does, by the confirmed evidence
  (a face on the morning after a confirmed evening is no day together; the demo's Ola reads 3 days
  in both, was 4), and says so: `first confirmed … · last confirmed …`, `3 days together, by the
  confirmed evidence`, `last 6 shared stays, confirmed or proposed`. `show asset` reads the runs
  aboard as `rollup places` does, so its stays, hours and people agree with it.
- `logbook export --day DAY --out DIR` (and `--days`) reads its ceiling from a `folder` entry of
  `policy/crossing.json`, as the vault and the site do, tier 1 without one; `--tier` may lower it, never
  raise it, and a tier above it is refused naming the entry. Each run that writes a folder appends a
  `crossing/v1` line like every other export: destination `folder`, the folder's last part, the tiers,
  the kinds, the line count and the folder's digest (ADR 0026). It wrote every tier and left no line,
  though the README promises that your record keeps a line that says it left. docs/export.md.
