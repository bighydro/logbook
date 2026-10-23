# The companies a day touched

The orgs you named in the Manifest ([entities](entities.md)) show up in a day's lines: a mail from
one of their addresses, a meeting with someone of theirs, a link into one of their repositories.
`logbook lab companies DAY` reads them back for one day, each with what touched it and the lines
([RFC 0043](https://github.com/bighydro/logbook/blob/main/rfcs/0043-the-day-page.md), §11 and §12).
It writes nothing. It is a [lab](labs.md) reader while the Day page it is for is still being built:
its JSON may change before it settles.

```
$ logbook lab companies 2026-09-15
2026-09-15 · 2 companies
Angel
  Nordmann Tidevann AS  add
    meeting  Verft board  with Liv Berg  #16
Fund I
  Nordmann Verft AS  hold
    meeting  Verft board  with Ola Nordmann  #16
$ logbook lab companies 2026-10-09
2026-10-09 · 1 company
Fund I
  Nordmann Verft AS  hold
    update  Board pack October  with Ola Nordmann  #15
```

## What touches an org

Through the refs the record binds to the org, the way `show orgs` finds its touches, on a line of the
day that stands (not retracted, not superseded):

| What | The line |
|---|---|
| **update** | a mail from an address at one of the org's domains |
| **mail** | a mail to someone there, or copied to them |
| **meeting** | a calendar entry with an attendee (who did not decline) or the organizer at one of its domains; a transcript with a participant there; a call whose counterparty is an address there |
| **document** | a link into one of its repositories: a page browsed, a task, an act `sync github` wrote |

Each touch names the people of theirs on the line, by the record's name for the address, else the
name the mail, the transcript or the calendar entry shows, else *someone at* the org (*someone at
Nordmann Verft AS*): never a bare address. Your own addresses and domain are never an
org's, and a
calendar's rooms are the service's. A group chat and a merchant bind an org too; neither is an
update, a meeting or a document, and what was paid is the money slot's (below).

## Status and portfolio: tier 3

An org's status (`hold`, `add`, `sell`, `exited`, `passed`, `let-go`) is tier 3 (RFC 0037 §8), and so
is its portfolio, the field of its latest status line that carries one (`logbook status org NAME hold
--portfolio "Fund I"`; RFC 0037 §10.2 as amended on 15 October 2026; the Manifest's `entity/v1` line
never carries one). A row says them only where tier 3 is read, and the rows group by portfolio, in
its words, the orgs in none last under *no portfolio*. Your terminal reads every tier. Through a gate
without 3 (a page served at a lower entry) no row carries a status or a portfolio, every row is in one
group, and the reading says *status not shown: an org's status is tier 3, and this reads no tier 3*.

`--json` gives `day`, `statuses` (whether tier 3 was read), `hidden` (the sentence, when it was not)
and `groups`, each a `portfolio` and its `companies`: `org`, `name`, `status`, `portfolio` and the
`touches`, each `what`, `kind`, `line`, `seq`, `title` and `people`.

The reader is `logbook.contrib.companies.companies_of(lb, day, tiers=None)`. It reads one day's lines
through the index and the naming lines by kind, as `show orgs` does; never a sweep of the record's
mail.

## The money slot

What a day paid is `logbook.core.money.money_in(lb, start, end, tiers=None)`: the `transaction/v1`
lines of the local days `start` to `end`, each with its merchant, amount and currency, and the totals
per currency, read as [the ledger](ledger.md) reads them (a correction stands in place of the line it
corrects; a retracted line is out; a line the source marks deleted is listed, marked, and never
summed). Every one of them is tier 3, and so is where they end: through a gate without 3 nothing of it
is shown, not a line, a total or a date.

It never shows an empty sum. A payment source covers the days from its first transaction line to its
last; when none covers the day, it says so from the record's own lines:

- *No payment source covers this day — the last ends 2026-10-06*, for a day after the last line;
- *… — the first begins 2026-10-01*, for a day before the first;
- *… — the record holds no payment lines*, for a record with none;
- *No card lines for this day*, for a day inside the span with nothing paid.

A window that runs past the last line lists what it holds and names the days past it. There is no
command of its own: the Day page will show it. Receipt mails proposed as payments are not read here.
