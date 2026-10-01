# RFC 0021 — payload profile `transaction/v1`

Status: draft · 2026-10-01 · comment period: two weeks

One movement of money as a financial app recorded it: a card payment, a transfer, a salary, a
shared expense on a trip. The line records what the app stored — how much, in what currency, with
whom, on what day, from which account, as the app categorised it — and never what it means: no
budget, no "too much on restaurants", no net worth. Interpretation is an engine's job (ADR 0013).

## Line

`kind` MUST be `transaction`. `tier` MUST be 3: SPEC §4 lists money under tier 3, and an adapter
MUST NOT let an import lower it, however small the amount — a coffee is a place and a time as much
as a sum. `at` is the transaction's instant in UTC when the source has one; a source that keeps a
day only gives `at` as that day's midnight in the record's zone (`tz`), and `date` says which day.
`end` is null. `source` is the adapter: `copilot`, `splitwise`, …

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"transaction/v1"` | MUST | |
| `raw_id` | string | MUST | the source's own stable transaction id. The dedupe key: re-importing the same store appends nothing |
| `amount` | number | MUST | signed, in `currency`: negative when money left the owner (a purchase, a transfer out, the owner's share of a shared expense), positive when it arrived (income, a refund, a repayment). The number as the source stores it, never a string |
| `currency` | string | MUST | ISO 4217 code, upper case, as the source spells it |
| `merchant` | string | SHOULD | the other side as the source shows it: a merchant's cleaned name, a payee, a shared expense's description. Never resolved here; a reader shows it as written |
| `category` | string | MAY | the source's own category for this transaction, as it spells it (Copilot's slug, Splitwise's category name); absent when the app has none or left it empty |
| `date` | string | MAY | `YYYY-MM-DD`, the day the source files the transaction under, when that is what the source keeps or when the day in the record's zone differs from the UTC day of `at` |
| `account` | string | MAY | the account the money moved on, as the source identifies it (an account id, a group's name); absent when the source has one implicit account |
| `provider` | string | MUST | the app that recorded it: `copilot`, `splitwise`, `revolut`, … — the same as `source` for a first-party adapter, different when one source aggregates several providers |
| `status` | string | MAY | `pending` or `posted`, as the source says; absent when the source does not distinguish |
| `note` | string | MAY | the owner's own note on the transaction in the source |
| `extra` | object | MAY | anything else the source reports: its transaction `type`, a recurring flag, the original (uncleaned) merchant string, a shared expense's total and shares, who paid |

## Rules

1. One line per transaction the source stores. A pending transaction and its posted form are the same transaction when the source gives them one id; when it gives two, they are two lines and `status` tells them apart.
2. `amount` is signed from the owner's side, whatever the source's convention. Plaid-style stores (Copilot) keep debits positive; the adapter negates. A shared expense (Splitwise) is logged as the owner's share: the owner's owed share, negative, for an expense; the sum paid or received for a payment between members. The total and every member's shares go under `extra`, never into `amount`.
3. `merchant` and the people under `extra` are never resolved here (RFC 0006). A Splitwise member is `{ kind: "email", value }` with the name the app shows, the same identity a `resolution/v1` ref names; a member without an email is `{ kind: "provider_id", value }`.
4. `category` is the source's, kept as spelled. Two apps' categories are two vocabularies; mapping them onto one is an engine's work.
5. Timestamps are the source's. A source that stores local midnight as a UTC instant (Copilot) gives that instant as `at` and the day in the record's zone as `date`; the adapter does not "correct" either.
6. A transaction the source marks deleted is still a line, with `extra.deleted` true, counted; the log keeps what the source kept.
7. Tier 3 always (above). An import option that lowers the tier of a run (`--tier`) MUST NOT apply to this profile.

## Example (synthetic)

```json
{"at":"2026-03-01T23:00:00Z","end":null,"tz":"Europe/Oslo","source":"copilot","kind":"transaction","tier":3,
 "payload":{"schema":"transaction/v1","raw_id":"6f1c2a9e-0000-4000-8000-000000000001","amount":-42.5,"currency":"USD",
 "merchant":"Harbour Cafe","category":"restaurants","date":"2026-03-02","account":"acct_0000000000000001",
 "provider":"copilot","status":"posted","extra":{"type":"regular","recurring":false,"original_name":"HARBOUR CAFE OSLO"}}}
```

```json
{"at":"2026-03-02T18:30:00Z","end":null,"tz":"Europe/Oslo","source":"splitwise","kind":"transaction","tier":3,
 "payload":{"schema":"transaction/v1","raw_id":"1000000001","amount":-30,"currency":"NOK","merchant":"Dinner at the marina",
 "category":"Dining out","account":"Sailing trip","provider":"splitwise",
 "extra":{"cost":90,"paid_share":90,"owed_share":30,"payment":false,
   "members":[{"ref":{"kind":"email","value":"kari.nordmann@example.org"},"name":"Kari Nordmann","paid":90,"owed":30},
              {"ref":{"kind":"email","value":"ola@example.org"},"name":"Ola Nordmann","paid":0,"owed":30},
              {"ref":{"kind":"provider_id","value":"3"},"name":"Per","paid":0,"owed":30}]}}}
```

## Notes

- **Why tier 3 always.** SPEC §4 names money. A single line is harmless; the set is a ledger, and the crossing policy (RFC 0005) has to be able to treat every transaction the same way. The other profiles let a run lower its tier; this one does not.
- **Why signed, not `direction`.** An engine sums. A sign sums; a direction field needs a branch in every reader, and two readers will branch differently.
- **Why `merchant` and not `counterparty`.** A card store knows a merchant string and nothing more; a shared-expense store knows people and a description. One field for "the other side as shown" covers both; the people, when known, are refs under `extra`.
- **What a phone backup holds.** The apps differ: Copilot keeps its whole transaction table on the phone; Splitwise keeps every expense with every member's shares; Revolut keeps no transactions on the phone at all (its stores hold the profile, market news and a chat), so there is no Revolut adapter from a backup — its CSV export is the way, later.
