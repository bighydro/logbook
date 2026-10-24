### Added
- `show plan [DAY] [--json] [--coverage]` reads the plan you keep in Notion back from the lines `sync notion`
  wrote, for one day: today's open tasks (dated today, or overdue in the current sprint; five, the rest
  counted; between sprints, one line says no overdue task is shown), the current sprint and its dates and the next trip as a countdown, each row with its Notion
  link and never its text. It reads tier-1 `sync notion` lines and nothing else. Which databases are which
  is a `plan` entry in `policy/notion.json`; without it, one sentence. `--coverage` says how much of each
  database the record knows. Nothing is written, to the record or to Notion (RFC 0043 §9;
  [the plan](docs/plan.md)).
