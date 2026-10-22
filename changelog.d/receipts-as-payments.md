### Added
- `review receipts [--since D] [--json]` proposes the receipt mails the record holds as payments, the
  money bridge until a payment source covers the day (RFC 0043 §12): a received mail from an order or
  no-reply address, or a domain an org of the Manifest binds, never a person the record names, whose
  subject or kept body carries an order or receipt marker and an amount with a currency, read by rules
  (`CHF 1'234.50`, `€ 12,90`, `$12.90`, `NOK 1 840`), the total over the line items, a refund as money in.
  `--accept N,N` writes one tier-3 `transaction/v1` line each (`source: receipts`, `extra.from` the
  mail's line), a second mail of one payment in the same batch refused and counted; `--reject N` one
  tier-3 `not-a-payment` line (`receipt-review/v1`), never proposed again; the queue never shows a
  sender's address, it names a merchant by its domain; a receipt another source
  already holds is shown and never written, and one a payment source delivers later is listed as
  covered, with the retraction that lets the source's line win ([receipts](docs/receipts.md)).
