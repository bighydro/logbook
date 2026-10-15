### Added
- `export notion FOLDER [--since DAY] [--include-unsigned] [--dry-run]`: the record's facts for the program
  that keeps your Notion, as a crossing. Persons you had contact with in the window, by their emails,
  phones and handles: the last contact and its kind, the days together, the promises open both ways
  (the sentence, its day, its line), and the page in German, emitted whole; ideas with a Notion page:
  the status, your reason note quoted as written, a dated German entry per status; orgs by domain: the
  days they were touched, and nothing else. Anything without a key is left out and counted, and so is a
  sentence that names money. Nothing leaves without the `notion` entry of `policy/crossing.json`; signed
  days only unless the entry says `"include_unsigned": true` and you type `--include-unsigned`; tier 3,
  an org's status and money never. The folder is written fresh each run and one `crossing/v1` line says
  what left; nothing is asked of or created in Notion ([export for Notion](docs/export-notion.md)).
