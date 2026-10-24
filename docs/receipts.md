# Receipts as payments

`logbook review receipts [--since YYYY-MM-DD] [--json]` proposes the receipt mails the record already
holds as payments, and you confirm each one. It is the money bridge of RFC 0043 §12: until a payment
source (your bank's or card's app, Google Wallet, Splitwise) covers your days, a receipt mail is the
best evidence of a payment the record has. [The ledger](ledger.md) stays the truth. A receipt is only
a proposal, and nothing is written until you accept it.

```bash
logbook review receipts                          # the receipts of the last 90 days, numbered
logbook review receipts --since 2026-09-01       # from a given day
logbook review receipts --since 2026-09-01 --json
logbook review receipts --accept 1,3             # each one becomes a payment (tier 3)
logbook review receipts --reject 2               # not a payment, never proposed again
```

## What it shows

```
5 receipts proposed · 1 already in the record · 0 accepted · 0 not a payment · since 2026-09-01 · tier 3
  1  2026-09-03  Fjordkaffe  CHF -1 234.50  0.80
       fjordkaffe.example.org · an order or no-reply address · a total · the subject says so
  2  2026-09-05  Bokhylla  EUR -12.90  0.80
       bokhylla.example.org · an order or no-reply address · a total · the subject says so
  3  2026-09-08  Seilloftet AS  NOK -1 840.00  0.95
       seilloftet.example.org · an order or no-reply address · org in the Manifest · a total · the subject says so
  4  2026-09-10  Chartroom  USD -12.90  0.80
       chartroom.example.org · an order or no-reply address · the subject's amount · the subject says so · subject only: the line keeps no body
  5  2026-09-14  Bokhylla  EUR +12.90  refund  0.80
       bokhylla.example.org · an order or no-reply address · a total · the subject says so · a refund
  —  2026-09-16  Fjordkiosk  NOK -45.00  already in the record: google-takeout #10
--accept N,N writes each as a payment; --reject N writes that it is not one; both tier 3
```

Each proposal has a number, the day and the merchant. It shows the amount from your side, as the
ledger signs it (a purchase is negative, a refund positive), and a confidence between 0 and 1. The
line below gives the merchant's domain and the reasons. The queue never shows a sender's address:
not in its rows, not in its JSON (`domain` there too), and a display name that is itself an address
is no name. Numbers count from 1 in time order and belong to this
listing: after an accept or a reject, list again before giving more numbers. `review` with no kind
lists this queue with the others. Everything this queue shows is tier 3.

## What it reads

It reads only the record's `mail/v1` lines (RFC 0015), from `--since` (default: 90 days ago) to today.
Nothing is looked up and no model is asked. A mail line keeps:

- `from`, the address and the display name as the message gave them;
- `subject`, when the message has one;
- `body`, when the road kept one: the `text/plain` part, else the HTML stripped to text, at most 64 KB.
  The mbox import, `sync mail` (IMAP) and `sync gmail` all keep it.

The subject is always read. The body is read only when the line keeps one, and a proposal read from
the subject alone says so. Attachments are never opened.

## The rules

A mail is a **receipt candidate** when all of these hold:

1. **You received it** (a mail you sent is never a receipt).
2. **Its sender is a merchant.** That means three things:
   - The sender is not a person the record names: an address a `resolution/v1` line resolves to a
     person is never a merchant, and neither is any of your own addresses.
   - The address is an order or no-reply address (`orders@`, `orders.eu@`, `ordre@`, `no-reply@`,
     `no_reply@`, `auto-confirm@`, `receipts@`, `kvittering@`, `billing@` …), or its domain is bound
     to an org in the Manifest.
   - An org in the Manifest on the domain raises the confidence and gives the merchant its name.
     Otherwise the merchant is the display name without the generic words (`Orders`, `No-Reply`),
     else the first label of the sender's domain.
3. **Its text carries an order or receipt marker**: *receipt*, *your order*, *order confirmation*,
   *invoice*, *kvittering*, *ordrebekreftelse*, *Quittung*, *Rechnung*, *reçu*, *facture* and the
   like, each as a word of its own (*recurring* holds no *reçu*). A refund word (*refund*,
   *refusjon*, *Rückerstattung*, *remboursement*) counts too. A price alone is not a receipt: a
   newsletter that says *from CHF 14.90* is never proposed.
4. **Its text carries an amount with a currency**, in the common forms: `CHF 1'234.50`, `€ 12,90`,
   `12,90 €`, `$12.90`, `US$ 1,250.00`, `NOK 1 840`, `1.234,50 EUR`, `99.- CHF`. `kr` on its own
   names three currencies, so it is not taken as a currency, the same rule the Google Wallet reader
   follows. A number glued to a word (`XY1234`), one after another number and a space (`07700 900123`)
   and one that a code then a number follow (`Ordre 5531 NOK 1 840`, `2026-09 EUR 12.90`) is not the
   amount: the code goes with the number after it.

**Which amount.** A total wins over the line items. An amount is a total when the words before it on
its line (or the line above, when it stands alone) say *total*, *sum*, *å betale*, *amount paid* and
not *subtotal*, VAT, *MwSt*, shipping, discount or savings. *Total incl. VAT* and *Sum inkl. mva* are
totals. The largest total wins. In `Total EUR 12.90 (approx. NOK 150.00)`, only the first amount has
*Total* before it. With no total, the amount in the subject is used. Failing that, the one amount the
text names. Failing that, the largest amount, with less confidence.

**A refund** is money coming in. The mail is a refund when its subject says so, or the words before
the chosen amount do (*Refund total*), or a minus sign is on the amount. A footer that mentions
refunds (*non-refundable*, *refund policy*, *refunds within 30 days*) does not make a receipt a
refund.

## What is written, and only when you say

- **`--accept N,N`** writes one `transaction/v1` line per receipt, through the one writer every line
  goes through (`Logbook.append`). The line is tier 3, the tier money always has (RFC 0021).
  - `source` and `provider` are `receipts`; `at` is the time of the mail.
  - `amount`, `currency` and `merchant` are what the queue showed.
  - `raw_id` and `extra.from` are the mail line's id; `extra.confidence` is the confidence;
    `extra.refund` is set for a refund.
  - A mail is never written twice. Under the writer lock, each mail is checked once more for a
    standing receipt's line before anything is written. If one has appeared since the listing,
    nothing is written and the queue says so. A retracted line holds nothing, so a mail whose
    receipt line you retracted can be accepted again.
  - **One payment, one line, within a batch too.** Two mails of one payment (an order and its
    confirmation on the same day) are both proposed while neither is in the record. Accepted
    together, the first is written; the second, of the same merchant, day, currency and amount, is
    refused and counted (`1 duplicate refused`; in the JSON, `verdict: "duplicate"`, `line: null`
    and `same_as` the number written in its place). Listed again, it is already in the record.
- **`--reject N`** writes one `receipt-review/v1` line, kind `receipt-review`, labelled
  `not-a-payment`, with `extra.from` the mail line's id and the words *not a payment*: no amount, no
  currency and no merchant. It is tier 3, like the payments. That mail is never proposed again, unless
  you retract the line.
  - Why not a note: a `note/v1` is tier 2 whoever writes it (RFC 0010). The no is a line of its own,
    as a scene's no is (`scene-review/v1`, RFC 0040 §5), and a receipt is none of the five kinds of
    thing `entity-review/v1` answers for.
- Every number is checked before the first line is written. `--name` and `--all-above` are refused:
  a receipt is accepted by its number.

## Already in the record

Some receipts are already paid in the record: another standing `transaction/v1` line has the same
currency and amount (the same sign), falls within two days of the mail, and names the same merchant
(one name contains the other once case, spaces and punctuation are removed: `Fjordkiosk` and
`FJORDKIOSK AS`). Such a receipt is shown as **already in the record**, with the line that holds it.
It gets no number and is never written.

## When the ledger delivers it later

You may accept a receipt before your payment source is imported. When that source later delivers the
same payment, both lines stand for one payment. The queue lists the pair as **covered**:

```
  —  2026-09-03  Fjordkaffe  CHF -1 234.50  receipt #12 is covered by google-takeout #14, which wins: logbook repair retract 12 "covered by google-takeout #14"
```

The payment source's line wins, and it is counted once already, before you do anything: every reader
that sums the ledger (the Day's spend, `rollup ledger`, `rollup money`, a trip's spend, an org's money,
the money slot) pairs a receipt's line with the payment source's line that holds the same payment, by
the rule above (the currency, the signed amount, within two days, the merchant), and counts the
source's line alone, the receipt named as its evidence (`1 with its receipt` on the Day). One source
line holds one receipt: two dinners of one price are two payments until the source has delivered both.

The receipt's line is still the one to take back, and the row prints the command that does it:
`logbook repair retract SEQ`, a retraction appended through the same writer. A retracted line is out of
every reader, the ledger included. The queue writes nothing on its own: you run the command.

Why not a superseding line? The record's rule (SPEC §3) puts a line that names another in
`payload.supersedes` *in its place*. Only the payment source's own line could do that, and an adapter
does not know the receipt's id. A new line written here to supersede the receipt would be a second
copy of the source's payment. The pairing is a reader's rule of the reference
(`logbook.core.ledger.receipts_held`); writing it into RFC 0021, so that a second implementation pairs
the lines the same way, is an open proposal.

## Who sees it

The queue's output is tier 3, and so is every line `--accept` writes. A reader held to tiers 1 and 2
(an export at the crossing ceiling, a page or a tool that does not carry money) sees no proposal, no
amount, no accepted line and no `not-a-payment` line: everything this writes is tier 3.

## What it costs

The rules run in time linear in the text: a 64 KB body is read in milliseconds, whatever it holds.
One indexed read of the window's mail lines, which are read once and checked by the rules in memory.
On a record of five million lines with half a million mails, the default 90 days is a few thousand
mails; `--since` far back reads every mail of the span. The transactions from two days before
`--since` on, and every receipt's own line, are read once for the dedupe. The `not-a-payment` lines
come through the index's kind and source columns. No other line is read.
