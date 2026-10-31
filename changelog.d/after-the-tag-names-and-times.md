### Security

- A page that reads no notes (a tier-1 page) looks exactly as if the day had no reflection: its Sign form carried a digest of the reflection, or of none, and so told the two apart; it carries the last line the page read now, and Sign refuses a form older than the reflection. A page that reads notes but not the tier a reflection is at reads the newest reflection it can see, as if the other were not there.
- `digest`'s tomorrow says the title, then its time after a word (`Ola Nordmann's birthday, from 19:30`), never a clock against a title that opens with a name.
- The ribbon's spoken label says the span, what was lived, then the plan, so no clock stands before `Lived` (whose first letters may be a name, as the demo's Liv); `tasks done` says `“Call Ola Nordmann”, the task of 2026-06-09`, and the rows of `tasks` and `tasks --propose-done` give the due day, the list, the shared words and the ids each after a word.
- A draft's evidence ids follow a word, `from […6742a9f5]`, in `logbook day`, `show trip` and the Day page, so an id that opens with a digit never stands right after a name; the test guard reads the ids as printed.
- The week page holds its goals, places, threads, intention and question to the main guard (`figures.adjacent`, every separator, a date in words, the first name too), not a guard of its own with fewer separators.

### Fixed

- An all-day entry says `all day`, never `from 00:00 to 00:00+1`, whichever calendar carries it: one that another calendar carries timed (a Notion date-only page, a copy of a birthday) and one that runs from a midnight to a later one are all-day too, on the Day's `all day` row, in Today's plan, under the day's ribbon on the week page, and first in `digest`'s tomorrow (`tomorrow.all_day` in its JSON). Two all-day entries have a word between them, `Away with Per Hansen and 17 May dinner`.
- `doctor`'s install hint in a clone is the short `uv sync --extra <name>` where that syncs the environment doctor runs in as it is, and adds `--python` (when the clone's `.python-version`, uv's global pin or `UV_PYTHON` asks for another Python than the venv's) or `--no-default-groups` (when the venv has no dev group) where it would not, so the extra lands in that environment; with `UV_NO_DEV` or `UV_NO_DEFAULT_GROUPS` set it prints no line.
