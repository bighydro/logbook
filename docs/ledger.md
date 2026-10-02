# The ledger

`logbook ledger [--month YYYY-MM | --trip ID] [--json]` reads the record's money back in context.
A `transaction/v1` line (RFC 0021) is one movement of money as the app recorded it: an amount in a
currency, the merchant, the app's own category. It is tier 3, and it never crosses: no export, no
page and no MCP tool carries one past the crossing ceiling (RFC 0005, ADR 0016). What the line does
not say is where you were. The ledger says it. It is a reader (ADR 0013): a function of the record
at its head, derived every time and never written.

```bash
logbook ledger                          # every day with a transaction, in context
logbook ledger --month 2026-06          # one calendar month
logbook ledger --trip trip:2026-06-15:2026-06-17   # one trip's days, by the id `trips --json` prints
logbook ledger --month 2026-06 --json   # the same, one JSON object, every entry with its line id
logbook rollup money --year 2026        # the year by month, by country, by category
```

## What it shows

```
ledger 2026-06-10 – 2026-06-19: 5 transactions · 1 deleted · EUR -307.50 · NOK 44,785.00 (in 45,000.00, out -215.00)
  2026-06-10  Wednesday · NOK -185.00
    12:40  NOK -185.00  Fjordkaffe · at Cafe · restaurants · copilot
  2026-06-13  Saturday · NOK -30.00
    18:30  NOK -30.00  Dinner at anchor · aboard Solvind · Dining out · splitwise · trip 2026-06-13 – 2026-06-13 · split 3 ways: you 30.00 (paid 90.00), Ola Nordmann 30.00, Per 30.00
  2026-06-14  Sunday
    13:00  NOK -40.00  Ice cream · aboard Solvind · Dining out · splitwise · trip 2026-06-13 – 2026-06-13 · shares: you 40.00 (paid 40.00) · deleted
  2026-06-16  Tuesday · EUR -307.50
    00:00  EUR -210.00  Hotel Musterhof · at 47.3769,8.5417 (Zurich) (by day) · travel · copilot · trip 2026-06-15 – 2026-06-17
    19:30  EUR -97.50  Zunfthaus Beispiel · at 47.3769,8.5417 (Zurich) · restaurants · copilot · trip 2026-06-15 – 2026-06-17
  2026-06-19  Friday · NOK 45,000.00
    09:00  NOK 45,000.00  Eksempel AS · at Office · income · copilot
  trips
    2026-06-13 – 2026-06-13  aboard Solvind · 1 transaction · NOK -30.00
    2026-06-15 – 2026-06-17  47.3769,8.5417 (Zurich) · 2 transactions · EUR -307.50
```

Every merchant above is invented, and so is the person.

**Where.** Each transaction is placed at the stay you were in at its instant: the same stays the
Day and the trips read (`derive stays`). The place's name when the stay is at a named place in
`places.json`; `aboard <asset>` when it is aboard one; else the coordinates with what is near, the
rule the trips' route uses (`near <place>, x km` within 5 km, else the city of the nearest large
airport in parentheses). The country is the stay's, by the rule `rollup countries` uses. A source
that keeps the day only, not the hour (Copilot: `date` given, `at` that day's local midnight, RFC
0021 rule 5), has no instant to place: the transaction is placed by the day, at the stay that
held the longest part of it, and the row says `(by day)`. A transaction at an instant the track
does not cover is `nowhere`, and says so.

**Trips.** A transaction is in a trip when its day is one of the trip's, the first day to the
return day ([trips](rollups.md)); the trips of the window are listed with their spend. `--trip`
takes the id `trips --json` prints, `trip:<first day>:<last night>`, reads only those days, and
refuses an id that is no trip.

**Shares.** A shared expense (Splitwise, `extra.members`) shows each member's share: the member's
ref resolved through the record's resolution lines (RFC 0006) to the person it names, else the
name the app shows; your own member is `you`. A photo library's face tag is never a resolution
here: a member is a person the record names, or the app's word. The owner is known from
`owner_id` and `owner_emails` in `logbook.json` and the aliases in `policy/owner.json`.

**Amounts.** In the line's currency, signed from your side (negative out, positive in), and
nothing is converted: every total is per currency, a trip in two currencies has two totals.
`in` and `out` are printed when money went both ways. A transaction the source marks deleted
(`extra.deleted`) is listed and marked, and never counted or summed. A correction that
`supersedes` an earlier line stands in its place; a retracted line is out.

**The window.** Without a flag, the days the record has a transaction on. `--month` is one
calendar month, clipped to them; a month with none says so.

## The Day

When a day has a transaction line, `logbook day` gains one line after the health line: the totals
per currency, how many transactions, the merchants.

```
  health        sleep 7.2 h · 8,412 steps · resting 55 bpm
  spend         EUR -307.50 · 2 transactions · Hotel Musterhof, Zunfthaus Beispiel
```

Under `--json` it is `spend`: `count`, `deleted`, `totals`, `merchants`, `lines`; `null` on a day
with none.

## rollup money

`logbook rollup money [--year YYYY | --since DAY --until DAY] [--json]` sums the same entries per
year: the transactions that count and the deleted ones, the totals per currency; then by month,
by country (the country of the stay each transaction is placed at; the unplaced apart) and, when
any line has one, by the source's own category, as the app spells it. Two apps' categories are
two vocabularies (RFC 0021 rule 4); nothing maps them onto one.

```
money 2026-06-10 – 2026-06-19
  2026  5 transactions · 1 deleted · EUR -307.50 · NOK 44,785.00 (in 45,000.00, out -215.00)
        by month:
        2026-06        5 transactions · 1 deleted · EUR -307.50 · NOK 44,785.00 (in 45,000.00, out -215.00)
        by country (of the stay each transaction is placed at):
        NO             3 transactions · NOK 44,785.00 (in 45,000.00, out -215.00)
        CH             2 transactions · EUR -307.50
        by category (the source's own):
        restaurants    2 transactions · EUR -97.50 · NOK -185.00
        Dining out     1 transaction · NOK -30.00
        income         1 transaction · NOK 45,000.00
        travel         1 transaction · EUR -210.00
```

The window is clipped to the days the record has a transaction on. Under `--json`, each year has
`count`, `deleted`, `totals`, `by_month`, `by_country`, `by_category` and `lines`; every bucket
carries its `count`, `deleted`, `totals` and `lines`.

## What it does not do

No budget, no "too much on restaurants", no net worth, no exchange rate: the ledger places and
sums what the apps recorded and interprets nothing (ADR 0013). A transaction's tier is 3 whatever
its size, and `logbook add --tier` never lowers it (RFC 0021 rule 7).
