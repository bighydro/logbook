### Fixed
- `export notion` lists only promises: your own and the person's own. A request is no longer listed,
  on either side; before, one the person made of you appeared under "Offene Versprechen von mir"
  ([export for Notion](docs/export-notion.md)).
- `export notion` lists only whole sentences: never a line quoted in a reply, a chat line pasted with
  its time stamp, or a run of more than 40 words without a full stop (a whole chat message).
- `export notion --dry-run` says how wide the pages' two long sections are, in totals and never a name:
  `pages: days together: N lines on N pages; promises: N lines (N listed, N more not listed)`.
