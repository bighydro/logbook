# Gifts

What you gave someone, and what you were given, is something only you can say. The **gift act** is
one line in the record, in your words, appended through `Logbook.append` like every other line and
never an edit ([RFC 0043](https://github.com/bighydro/logbook/blob/main/rfcs/0043-the-day-page.md),
§11 and §12).

```
$ logbook add gift 2026-10-10 "Per Hansen" "a book on knots"
#54 given to Per Hansen: a book on knots
$ logbook add gift 2026-10-11 Ola "cloudberry jam" --received
#55 received from Ola Nordmann: cloudberry jam
```

## What it writes

One `note/v1` line ([RFC 0010](https://github.com/bighydro/logbook/blob/main/rfcs/0010-note-v1.md))
through the notes path every note on a day takes (`logbook/core/notes.py`):

- the **text** is the gift in your words, as you typed it, never filtered;
- the **label** is `gift`;
- the **person** is under `extra.recipient` when you gave it and under `extra.giver` with `--received`: the
  person's entity id, as the record's resolution lines name them;
- **tier 2**, as every note is; source `manual`.

No new profile: a reader that does not know gifts reads a note.

**When**: on the day as every note on a past day is, at its last minute (23:59, or 05:59 the next
morning when your day begins at 06:00, [where your day begins](settings.md)); now when the day is
today. A day that has not begun is refused: a gift is written on the day it changed hands. The same
gift said twice on one day, the same person, the same way and the same words, is one line.

## The name

`NAME` is the person `logbook people NAME` would open: a label (case aside), a unique first or last
name, an entity id, or an address the record resolves. A name the record cannot place is refused in
one sentence, and nothing is written:

```
$ logbook add gift 2026-10-11 Nordmann "a jar of honey"
add: 'Nordmann' names several people: Ines Nordmann, Kari Nordmann, Ola Nordmann; nothing was written
```

The same for a name that is nobody the resolution lines name, and for your own name: a gift is given
to someone or received from them. `logbook people review` places the people the sources saw under the
names the record holds.

## Reading them back

```
$ logbook people gifts
1 given, 1 received
2026-10-10  given to Per Hansen: a book on knots  #54
2026-10-11  received from Ola Nordmann: cloudberry jam  #55
$ logbook people gifts Per
gifts with Per Hansen
1 given, 0 received
2026-10-10  given to Per Hansen: a book on knots  #54
```

`logbook people gifts [NAME] [--json]` lists every gift both ways, in the day's order, or one person's; a
retracted gift is not listed (`logbook repair retract`). `--json` gives `person`, `name`, `given`,
`received` and each gift's `day`, `direction`, `person`, `name`, `what` and `line`.

The reader is `logbook.core.gifts.gifts(lb, person=None, window=None)`: a person's name as above, and
a window of local days `(first, last)`. Through a gate without tier 2 it lists nothing, since every
note is tier 2. A person's page is to print one row for it, under the person's name and never beside
it, `gifts  3 given, 1 received: logbook people gifts NAME` (`gifts.counts`), once the person page takes it.

## What it is not

- **Not a score.** No count of gifts stands beside a person's name, on a page or in the terminal,
  and nothing is ranked by them.
- **Not a model's.** A gift is written only when you say it; a draft may mention one, and never
  writes it.
- **Not a receipt.** What a gift cost is the ledger's, at tier 3 ([the ledger](ledger.md)); a gift
  note is tier 2 and says only what you wrote.
