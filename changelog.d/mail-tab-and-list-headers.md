### Adapters
- Mail lines keep Gmail's inbox tab and the list headers, never their links (RFC 0015, amendment of
  20 October 2026): every new line from `add mail` (a Takeout or any mbox), `sync mail` and `sync gmail`
  may carry `extra.gmail_category` (`primary`, `social`, `promotions`, `updates`, `forums`; from Takeout's
  `Category …` labels and the API's `CATEGORY_*`, never over IMAP, which does not say the tab) and
  `extra.list` (`unsubscribe`, `one_click`, `id` from `List-Unsubscribe`, `List-Unsubscribe-Post` and
  `List-Id`, of which only the list-id itself is kept). The unsubscribe URLs and `mailto` addresses,
  and a `List-Id`'s phrase, links and addresses, are never kept. `labels`, `raw_id` and every
  dedupe key are unchanged; lines already in the record are not rewritten, so older lines lack both keys.
  A list header that does not parse is kept by its name and counted.

### Added
- `logbook lab hold census senders` counts, per sender, its mails with `List-Unsubscribe` and in
  Promotions, Social or Updates, in the report and its JSON (`list_unsubscribe`, `tabs`,
  `lists_and_tabs`); the terminal summary gives the totals and still prints no address.
