### Fixed
- `export notion` counts a person's days together over their whole history in the record, not the
  export's window: `days_together` with `first_together` and `last_together` in the facts, and on the
  page "Tage zusammen: N (zuerst …, zuletzt …)", or no line at all when there are none. Before, every
  page said "seit" the window's first day, and most said 0 ([export for Notion](docs/export-notion.md)).
- `export notion` lists only the open promises said in the 365 days before the export, from a
  conversation the person is a direct party to (a one-to-one chat, a mail you are both on and no list
  sent, a call they spoke in), newest first, at most ten a side, then "und N weitere"
  (`promises_more` in the facts). Before, a page listed every promise of the window, group chats
  included.
- `export notion` leaves out a promise that talks of money without a figure (a payment, an invoice, a
  transfer, a price, in German or English) and counts it under `sentences_with_money`, as one with a
  sum.
