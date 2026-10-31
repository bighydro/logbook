# The acts

The record writes itself: trackers, calendars, libraries and mailboxes put their lines in it, and the
readers make days of them. A few things only you can say. These are the **acts**, and each is one
line in the record, appended through `Logbook.append` like every other, never an edit:

| Act | From a terminal | On the page (`logbook serve`) | What it writes |
|---|---|---|---|
| **Name** a place | `logbook setup places review --name N "Hytta"` | *Name this place* on the Places page | the place in `places.json` and one `note/v1` line saying so ([places](places.md#review)) |
| **Star** a line | `logbook star LINE [--note TEXT]`, `logbook unstar LINE` | the star on every row of the Day that is a line, and *Star* in its photo review | one `star/v1` line ([RFC 0041](https://github.com/bighydro/logbook/blob/main/rfcs/0041-star-v1.md)); for a photo, a `keeper/v1` line of lane `memory` ([RFC 0024](https://github.com/bighydro/logbook/blob/main/rfcs/0024-keeper-v1.md)) |
| **With**: who was there | `logbook with DAY NAME [NAME…] [--at HH:MM]` | the *with…* field in the Day's `with` row | one `note/v1` line per person, `with <name>` |
| **Reflect** on the day and **sign** it | `logbook day reflect DAY [--sign]`, `logbook day sign DAY` | *Reflect and sign* at the foot of the Day ([serve](serve.md#reflect-and-sign)) | a `note/v1` line, label `reflection`, and one `signed-day/v1` line ([the signed day](signed-day.md)) |
| **Keep** what the day held and **sign** it | `logbook day sign DAY --keep N,N [--revisit N=YYYY-MM-DD] [--word WORD] [--done T,T --tomorrow T,T --let-go T,T]`, the same under `day reflect DAY --sign` | *Keep and sign*, the Sign form of the evening ([serve](serve.md#keep-and-sign)) | the kept `note/v1` lines (`learned`, `decision`, `idea`, `word`, `task`), a link's `entity/v1`, the photo's star, then the `signed-day/v1` line ([the signed day](signed-day.md#keep-and-sign)) |

The page and the command are one function each: the Day page's star runs `stars.star` and
`stars.unstar`, its *with…* field `presence.state`, so a line written from either is the same line
(the clock aside). The page answers a form only from this machine, and never waits for another
writer: while another command holds the record, an act on the Day says so (`409`) and writes
nothing; see [In a browser](serve.md).

## Star: a line worth keeping

```
$ logbook star 019cadd3-6bc0-7dcd-9133-000000000401 --note "the table by the window"
#5440 star/v1  ★ #312 event  Lunch · the table by the window
$ logbook unstar '#312'
#5441 retraction/v1  unstarred #312 event  Lunch
```

`LINE` is a line's id, or `#SEQ` (`312` alone works too). Any line that stands can be starred: a
calendar entry, a note, a transcript, a call, a mail, a flight, a location fix, a payment, a goal, a
chapter, an event you confirmed from the dream's proposals. A star is not a rating and not a label:
a line is starred or it is not.

**Never a model's draft.** The dream's draft of a day and a call's synthesis (`draft/v1`, RFC 0036)
take no star: a draft is a model's proposal about your record, not yours to keep as a memory. To
confirm what it says, sign the day ([the signed day](signed-day.md)) or star the lines it rests on;
an event it proposed is starred once you have confirmed it, as the event line it became. A row the
policy withholds (a draft above the `dream` entry, *superseded by policy*) carries no star either,
and no star ever shows a line a reader does not show.

**Where a star travels.** A star is written at its line's own time (`at`) and at its line's tier, so
it sits on its line's day and goes wherever its line goes, and nowhere else. A tier says where a
line may travel, never who wrote it: the star on a tier-1 dinner in the calendar crosses to a member
of your circle when that day is shared at tier 1 (`logbook export share day`, or `export crossing`),
the star on a tier-2 recording stays home with the recording, and the star on a tier-3 payment never
shows that the payment was there. A `--note` is the star's caption and travels with it at the same
tier; words for yourself alone belong in a note on the day (`logbook add`). A star whose line was
retracted since does not stand, and never crosses without it.

**Again, and back.** Starring a starred line again with another note writes a new star that
supersedes the first; with the same note, or none, nothing is written. `logbook unstar` takes the
star back as a retraction (RFC 0003), at the star's tier, so the unstar travels where the star did;
`unstar` takes the starred line's id or the id of any of its stars, a superseded one included, and
takes back the star that stands on that line. Starred again later, a line gets a new star: a new act,
a new line. Refused, with one sentence and nothing written: a line the record does not have, a line
that is retracted or superseded (star the one that stands), a mark itself (a star, a keeper, a
retraction), a model's draft, a note of more than one line, an `unstar` of a line that is not starred,
and an `unstar` naming an `art` keeper (the Art album's mark is not a star).

### A photo star is how a Volume picks pictures

A photo's star is the record's older mark for a photo, a **keeper** of lane `memory` (RFC 0024):
`logbook star` on a `photo/v1` line writes one, `source` `manual`, at the photo's tier, the note in
its `note`. A keeper is three things at once:

- the Day's **hero photo**: the Day lists it under the row it falls in, `keeper  IMG_121030.HEIC
  (memory)`, and `logbook show keepers` lists it;
- the **Volume's pick**: a Volume, `logbook show year 2026 --html year.html --print` and
  `logbook show trip ID --html trip.html --print` ([On paper](print.md)), lays out each month's or
  each day's keepers as its page of photos, and nothing else; a star's note is printed under the
  photo as its caption. To choose the pictures of the book, star them; to take one out, unstar it;
- the photo of the Days page's *Starred* list.

A photo your library marked a favourite is starred already: `logbook derive keepers` reads the
favourites (and the `Art` album, lane `art`) into keepers, and `star` on such a photo writes nothing.
`unstar` on a photo retracts its `memory` keepers, the library's included, and a retracted favourite
is never read back in. The `art` lane is the Art album's, not a star, and `unstar` leaves it.

### Where stars show

- **The Day** (`logbook day`, the Day page): a starred line is marked `★` where it is listed, beside
  the signed day's symbols; `--json` carries `stars`, the day's `star/v1` lines standing (`line`,
  `star`, `kind`, `note`), only on a day that has one. A photo's star is its keeper, listed as before.
- **`logbook show`** lists a star line on its day, `★ event 019cadd3… · the table by the window`.
- **The Days page** of `serve` lists the stars of its window under *Starred*, each linked to its row.
- **Exports**: `export share day` carries the stars on the lines it carries; `export trip-bundle`
  carries the stars on its photos and flights ([RFC 0030's amendment](https://github.com/bighydro/logbook/blob/main/rfcs/0030-trip-bundle-v1.md)).

A star derives nothing: it is not evidence of a stay, not company, not a promise.

## With: who was there when the record could not see

```
$ logbook with 2026-06-12 Ola kari --at 12:00
#5442 with Ola Nordmann  2026-06-12 12:00
#5443 with Kari Nordmann  2026-06-12 12:00
```

A calendar names the people it invited, a recording the people who spoke, a photo library the faces
it guessed. The friend who came by unannounced is in none of them. `logbook with` puts them in, in
your words: one `note/v1` line per person, its text `with <name>`, labelled `with`, the person's id
under `extra.person`, tier 2 as every note is, `source` `manual`. It is the line the people reader
already reads as company (SPEC §3.2.5 rule 3, *a note that says "with <Name>"*), so no new profile:
the Day lists the person at the stay the line falls in, confirmed, and `logbook people` counts the
day together (and the night under one roof, when the line falls in the night's stay).

**Names.** A name is what `logbook people NAME` opens: a label (case aside), a first or last name
only one person has, an address or a number the record resolves, or an entity id. Each word given
apart is a name of its own, so quote a name of two words: `logbook with 2026-06-12 "Ola Nordmann"`.
Two names for one person are one line. A name the record does not place — nobody, several people, or you — refuses
the whole statement and writes nothing, with the way to place them: `logbook people review` puts
the people the sources saw under the people the record names, and `logbook people merge` joins two
names for one person ([people](people.md)).

**When.** `--at HH:MM` is that clock on the day as the record defines it, its zone and its
[`day_start`](settings.md): under `06:00`, `--at 02:00` is the small hours after the day's evening.
Give the clock and the person is put at the stay you were at then. Without it, the line is at noon
of a past day, or now when the day is today. A day that has not begun, or a clock still to come, is
refused: `with` says who was there. A person already stated on the day is not stated again (with
`--at`, at that minute).

**A day no device saw.** The night the phones were off, the record has nothing of the day, and the
people reader has nothing to read company from. `with` needs nothing on the day: `logbook with
2026-05-02 Ola --at 23:00` writes the one line, and the Day page's *with…* field writes the same line
(byte for byte but for the clock), on a day whose page says *no device saw this day: say who was
there*. The Day then lists the person in its header, your word marked; with no stay to fall in, the
line is among the day's unplaced items.

**On the Day.** On a day you said who was there, the Day's header has a `with` row: everyone a row
confirms and everyone you stated, your word marked, `with  Kari Nordmann, Ola Nordmann (you said)`;
`--json` carries `stated` (`person`, `name`, `at`, `line`), only on such a day. The stay the line
falls in lists the person as before, `Ola Nordmann (note)`. A day without your word prints as it
always did. The Day page shows the `with` row on every day, with the field to add to it.

## On the page

The Day page of `logbook serve` carries both acts:

- **a star** on every row that is a line: an event, a transcript, a note, a mail thread, a call, a
  flight, an unplaced item, an all-day entry, and each photo a row counts, named. ☆ stars it, ★
  takes the star back, and the page comes back at the row. A keeper's row is a star while it is one.
  A stay or a move is derived from many lines, not a line, and has none; messages are counted, not
  listed, so star one by its id from `logbook show`;
- **the photo review** at its foot: the day's photos with no star, each with *Star* (the photo's
  star, a `memory` keeper) and *Not a keeper*, which stops the review asking about that photo and
  writes no line: the no is the review's own bookkeeping, `state/photo-review.json`, since neither a
  keeper nor a star has a "not" (RFC 0024 rule 3, RFC 0041 rule 4). Both post to `/star`;
- **a *with…* field** in the header's `with` row: type a name and the page completes it from the
  people the record names (a `datalist` filled by the server, no script), several with commas, and a
  clock if you know it.

Both post to the server (`/star`, `/with`), which answers only a form from this machine, one write at
a time, and writes through the same functions as the commands. A static site (`logbook export site`)
shows the stars and carries no form.
