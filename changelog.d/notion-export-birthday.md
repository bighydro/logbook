### Added
- `export notion` gives each person's `birthday` in the facts, read off a resolution line
  (`YYYY-MM-DD`, or `--MM-DD` without the year), or null, also when two cards disagree; nothing else
  the line holds there is passed through, and the page has no line for it. A birthday binds nothing,
  so its line passes the gate as a fact's does: at the entry's tiers, on a day you have signed unless
  the entry and `--include-unsigned` lift the gate, not retracted. Held back, it is counted with the
  other lines held back, never beside a name; the dry run says how many persons would leave with one
  ([export for Notion](docs/export-notion.md); from #459 by localboy21).
