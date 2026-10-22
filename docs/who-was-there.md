# Who was there

The record sees a lot of who was with you: the people on a calendar entry, the voices of a recording,
the faces your photo library names. It sees none of it for certain. A face is a library's guess; an
invitee may not have come. *Who was there* is how you answer once for a whole stretch, instead of once
a stay, and how you tell the record the two things only you know: who lives with you, and where your
people live. Built from [RFC 0043](https://github.com/bighydro/logbook/blob/main/rfcs/0043-the-day-page.md)
§11 (*Who was there*) and §12 (*Lives with*, *on a journey day*), as commands and readers; no page yet.

Every answer is one `note/v1` line in your words, tier 2, source `manual`, appended through the one
note path like [the other acts](acts.md). Nothing is written unless you say so, and nothing is fetched.

## With, across a stretch

```
$ logbook with --from 2026-06-08 --to 2026-06-12 Ola
#5612 with Ola Nordmann  2026-06-08 13:00
#5613 with Ola Nordmann  2026-06-09 13:00
#5614 with Ola Nordmann  2026-06-10 04:00
#5615 with Ola Nordmann  2026-06-11 13:00
#5616 with Ola Nordmann  2026-06-12 13:00
```

One `with` note per person per day, the same line `logbook with DAY NAME` writes (the same function,
`presence.state`), at the clock of that day's **longest stay**: the middle of the part of it that falls
on the day, so the note lies inside the stay and the Day, `people` and the journeys read the person
there. A day with no stay is stated as `logbook with DAY` states it, at noon (now, for today). A person already stated
on a day is not stated again. Every day is written under one hold of the writer lock, and everything
is checked before the first line: a stretch longer than 60 days, a day still to come, or a name that
is nobody, two people or you is refused in one sentence, and nothing is written.

## Not with

```
$ logbook people not-with Kari --from 2026-06-08 --to 2026-06-14
#5617 note  not-with: Kari Nordmann, 2026-06-08 to 2026-06-14
```

One note labelled `not-with`, the person's id and the stretch under `extra` (`person`, `from`,
`to`). The review-with queue stops proposing that person on those days.

## Lives with, lives in

```
$ logbook people lives-with Kari --from 2026-01-01
#5618 note  lives-with: Kari Nordmann, from 2026-01-01
$ logbook people lives-with Kari --until 2026-09-30      # ends the standing one
$ logbook people lives-in Per Bergen
#5619 note  lives-in: Per Hansen, Bergen
```

A `lives-with` note (`person`, `from`, `until` when given) means that at a **home stay** (a stay at a
place of kind `home` in `places.json`, or near one) that person is with you without asking, so the
queue never asks about them there; away from home their faces propose as anyone's do. `--until`
alone closes the stretch that is open, and is refused when none is. A `lives-in` note (`person`, `city`, `from`) is where they live;
the latest one of a person counts.

Each note is written on the day you say it, and its words are `<label>: <name>, …`: the with module
reads company from a note that says *with Ola*, and the colon keeps these notes out of it. A reader
never parses the words; the label and `extra` say what a note states. A retracted note stands no
more (`logbook repair retract`).

## The review-with queue

```
$ logbook review with --week 2026-W24
who was there, 2026-06-08 – 2026-06-14 (week 2026-W24)
  Kari Nordmann
      faces on 2 photos across 2 days · invited to 'Lunch'
      on Tue 9 Jun, Wed 10 Jun
  Ola Nordmann
      in the meeting notes of 'Boat plans'
      on Thu 11 Jun
  answer: --accept NAME (every day of it) · --accept NAME --days D,D · --not NAME
```

`review with --journey ID` (`trip:FIRST:LAST`, or a day of it), `--week YYYY-Www`, or `--from D1 --to
D2` (60 days at most); `--json` for one object. Per person, on a line of its own, the name; under it
the evidence in words and the days it lies on. The evidence is the with module's:

- **faces** on photos taken by your own camera (below); a photo received in a chat, by AirDrop or
  through a shared album never proposes anyone;
- **invitees** of the calendar entries held at a stay: *invited to 'Lunch'*;
- **the voices and participants of a recording**: *spoke in 2 calls*; of a meeting note-taker's
  transcript (Granola, Meet): *in the meeting notes of 'Boat plans'*.

A day you already answered is not asked again (a `with` note, or a note at the stay that says *with*
them); nor a day you said `not-with`; nor a home stay of someone who lives with you. The strongest come
first (the most days, then the most evidence), ten at most, the rest counted. A name the record does
not place is counted for `logbook people review`, never listed. No number stands beside a name: the
order is the only rank, and the counts live in the sentence of the evidence.

The answers are the acts above:

```
$ logbook review with --week 2026-W24 --accept Kari                     # every day of it that has begun
$ logbook review with --week 2026-W24 --accept Kari --days 2026-06-10   # some days
$ logbook review with --week 2026-W24 --not Ola                         # not with me
```

## Your people in a city

```
$ logbook people city Bergen --journey 2026-07-02
your people in Bergen, on journey trip:2026-07-01:2026-07-03
  Per Hansen  not yet
```

The people the record places in a city, by their `lives-in` note, and with `--journey` whether each
was **seen** on it: confirmed by the with module at one of its stays (a timed calendar entry
they accepted, their voice or name in a recording, a note there that says *with* them), or stated with
you on one of its days (`logbook with`, or an accepted answer of the queue). Names and
*seen* / *not yet*, never a count. No contacts import keeps a city today (the iOS and Google contacts
and WhatsApp's keep names, numbers and addresses only), so the `lives-in` note is the only source.

## Your own camera

A photo proposes a face for presence only when your own camera took it. What each library keeps
of that today:

| Library | What it keeps | What is missing |
|---|---|---|
| Apple Photos | `provenance`: `camera` (a live photo, a camera video, an import by the back or front camera, `ZIMPORTEDBY` 1 or 2, or by the Camera app), `received` (another app, AirDrop or sharing, shared with you: 3, 8, 13), `screenshot`, `other`; and `extra.imported_by` | which device of yours took it, and who added a photo to an iCloud Shared Library |
| Immich | `provenance` from the EXIF (`camera`: a make and model and an original capture time, or a live pair; `received`: a messenger's file name and no EXIF), and `camera`, the make and model | which of the server's users and devices uploaded it (Immich's `ownerId`, `deviceId`): a partner's phone uploading to the same library reads as `camera` too |
| Google Photos (Takeout) | the origin: `mobileUpload` is `camera`, a shared album `received` | the device |

So the rule (`who_was_there.own_camera`) is: `provenance` is `camera`, and no import the line keeps
says it was received. Telling your phone from a partner's in one Immich library needs the adapter to
keep the uploader, which is a change to the adapter, for later.

## Meeting note-takers

The record reads Granola and Google Meet today. Granola's notes become a `transcript/v1` line, tier
3, whose `participants` are the meeting's attendees as Granola names them (name and email), and its
summary a separate `note/v1` line, tier 2. Meet writes one `event/v1` line per conference, tier 1,
its signed-in participants as attendees, and its transcripts as `transcript/v1` lines, tier 3. The
attendees are kept, so the queue reads them as proposals, *in the meeting notes of 'Boat plans'*, as
the with module reads them at the stay. A tier-3 line stays home under the crossing as every
transcript does.

## What is not here yet

The Day page and the timeline still show faces from any library and do not set aside `not-with` or
`lives-with`: that is a change to the with module (`logbook/core/present.py`) the pages share, left to
the slice that builds the page. The journey page's *seen* / *not yet* list and the morning reconnect
read `people_in_city`, and are built with their pages.
