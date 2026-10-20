# RFC 0043 — The Day page and its rhythm: ink and pencil, intention against evidence

Status: draft · 2026-10-19 · comment period: two weeks · written during the v1 freeze: it proposes, and builds nothing but one reader change already in this pull request (`draft/v1` forward compatibility, §13.1) · builds on RFC 0027 (reflection), RFC 0034 (the signed day), RFC 0036 (goals, reviews, drafts and chapters), RFC 0037 (entities), RFC 0041 (star) and RFC 0042 (Hold) · proposes amendments to RFC 0027, RFC 0034, `draft/v1` and the dream's prompt, each as text in §13, none adopted by this RFC

The Day page already holds the day: the timeline, the people, the photos, the track, the draft a model
wrote, everything the day held, folded, and at its foot Reflect and Sign. What it does not hold is the
day's **intention**: what the day was meant for. A reflection that sees only what happened can describe a
day; it cannot say whether the day was spent on what mattered. And a page that shows everything shows the
things that slipped no more loudly than the things that went well, so a promise made on Tuesday, a reply
owed since Thursday and a decision taken in passing are as easy to lose on the page as off it.

This RFC is the design the page grows toward. **Reflection is intention against evidence**: what the day
was meant for (the chapter, the goals, the plan) beside what it held, with no verdict drawn. **Nothing
slips**: promises both ways, replies owed and decisions are in one place, each with three verbs. **And
nothing nags**: one question at most, one proposal, one person to reconnect with, and an item left alone
for three days folds away.

Every part below is marked:

- **[main]** — on `main` as this RFC is written: the code, the command or the page exists and is
  documented where the mark says;
- **[in flight]** — in an open pull request (only §13.1, this pull request's own reader change);
- **[proposed]** — nothing builds it; this RFC says what it would be, and another pull request builds it,
  slice by slice (§15).

Nothing here is claimed as built that is not. Where the design meets something `main` does differently,
§14 says what, and which side moves.

The examples are synthetic. The owner is Ines Nordmann of Oslo, who does not exist; Kari Nordmann lives
with her; Ola Nordmann is a friend from the boat club; the yacht is *Solvind*. Ines's goal is "Sail to
Lofoten and back", her chapter "The Fjord Summer", and her idea "Boat-share log". Addresses are
`example.org`, numbers `07700 900xxx`, flights `XY`, aircraft `ZZ-`, vessels MMSI `970xxxxxx`.

## 1. Words

- **Ink** is the record and the owner's words: every observed line, every note, every signature. Ink is
  printed plainly.
- **Pencil** is a model's text: a `draft/v1` line (RFC 0036), every sentence with the lines it rests on or
  marked unsupported. Pencil is printed as pencil: headed with the model's name, greyed where it proposes,
  never run into the ink around it.
- **Intention** is what the day was meant for: the standing chapter, the goals the day touched, the plan
  (the calendar's entries, and the owner's task tool when the record reads it, §9).
- **Evidence** is what the day held: the stays, moves and calls, the lines attached to them.
- A **loose end** is a thing the day leaves open that someone is waiting on: a promise either way, a reply
  owed, a decision with a date to revisit (§4.5).
- **To keep** is the owner's act of turning one piece of pencil into ink: a sentence becomes a note in the
  owner's name, a proposed link becomes a line. Keeping is always a click or a flag; showing never is.
- **The close** is the sequence that ends a day: the evening message, the evening dream, Keep and sign,
  and the morning after (§3.5).
- A **shape** is the arrangement of the page at an hour: morning, live, evening, signed (§3).
- A **lens** is a question the owner wants the pencil to look at every evening, "what did I learn",
  "where did the money go", answered from the day or said to be unanswerable (§4.4).
- A **fold** is a section closed to its summary line.

## 2. Principles

1. **Ink and pencil.** The record and the owner's words are ink; a model's text is pencil. Every pencil
   sentence carries its lines, or the word *unsupported*. RFC 0036's evidence rule, applied to every part
   below. [main, for the draft]
2. **Intention against evidence, no verdict drawn.** The page sets what the day was for beside what it
   held, and stops. It never says *a good day*, *off track*, *73 %*. The owner draws the conclusion, or
   does not.
3. **Everything visible, everything folded.** Nothing is hidden for being small, and nothing takes room for
   being there. Every section has a summary line complete in its counts (`loose ends · 2 promises, 1 reply
   owed`), so a closed fold says what it holds. A section with nothing in it is not a heading: the empty
   ones share one muted row, *Nothing from: lenses, decisions, photos*.
4. **Computed before generated.** What code can count, code counts: the ribbon, the numbers, the
   loose ends, the people who showed up, the closing line of the story. The pencil writes only what code
   cannot, and every number it uses was given to it.
5. **Movement, not anxiety.** At most **one question**, **one proposal** and **one person to reconnect
   with** on a page. An item left untouched for three days folds away into a count. No streak, no score,
   and no number beside a person (VISION: *no metrics near people*).
6. **Freedom.** The question can be ignored forever (VISION). *Let go* is a line the owner writes, never a
   failure the page records. Nothing is overdue on this page; things are open, kept, carried or let go.
7. **One gesture closes the day.** Keep and sign is one form: what is kept, what became of the loose ends,
   and the signature, in one click under one hold of the writer lock (§5).
8. **A proposal never becomes a fact by being shown.** Showing writes nothing. Not a star, not a link,
   not an event, not a note. [main, for the dream's events and the reflection's proposals]
9. **The shape follows the hour.** The morning page looks ahead, the evening page looks back, the signed
   page is the record (§3).
10. **The pencil never moralises or flatters.** No *you should*, no *great job*. It says what the lines
    say and marks what it infers (§7).
11. **The Library's rules are unchanged** (`docs/serve.md`, *Three rules*): this machine only; one
    document with one inline stylesheet, nothing fetched (no web font, no tile server, no script fetched);
    on the Day no script but the *Record* button [main]; one column at phone width [main]; the one `409`
    when another command holds the writer lock [main]; every draft shown by its entry as it counts today
    (`draft/v1` rule 7) [main].

## 3. Four shapes

The Day page takes one of four shapes, chosen from the clock, the day and its signature when the page is
read. A shape is computed and never stored: no line, no state file, nothing in `logbook.json`. `logbook
day` prints the shape it would show beside the date; `?shape=morning|live|evening|signed` asks for another.
[proposed]

| Shape | When | What leads |
|---|---|---|
| **morning** | today, from the day's start until the first stay away from home, or 11:00 | ahead |
| **live** | today, the rest of the day until the evening hour | the day so far |
| **evening** | today from the evening hour (§16 q1), and a past day not yet signed | back, and the close |
| **signed** | any day with a standing signature | the record |

### 3.1 Morning

- **Yesterday in one line**: where the night was, how many lines, signed or not, and the link to close it
  while it is unsigned (§10). [proposed; the morning message's content is [main], `docs/schedule.md`]
- **Today**: what it is for (§4.1); the plan (the calendar's entries [main], and the task tool's, §9
  [proposed]); what is **due** (the open promises due today, as the digest finds them [main]); **who
  you'll see** (attendees of today's timed entries, by name); **birthdays** (a resolution line's
  `extra.birthday`, [main] as a reader field; no contacts adapter writes it yet); **one reconnect** from
  the drift reader (§4.9); and **the week's one proposal**, when the week draft made one (§8).

### 3.2 Live

The day so far: the ribbon (§4.2) with the plan's lane ahead of the clock and the lived lane behind it,
then the page as it is on `main` today. Nothing of the pencil: the evening dream has not run. [proposed;
the page below the ribbon is [main]]

### 3.3 Evening

The pencil first, then the acts:

1. **The goodnight story** (§4.3), opening the pencil.
2. **Lenses** (§4.4).
3. **Loose ends** (§4.5).
4. **Ideas**, touched today (§4.6).
5. **Learned** (§4.7).
6. **Decided** (§4.8).
7. **Keep and sign** (§5).

Then the ink, folded: people, photos and track, everything the day held, looking back, the record.

### 3.4 Signed

What the owner kept, in ink, first: the notes kept at the close, the dispositions given, the signature and
its note. The pencil is folded at the foot, under its head, as the draft is today. A signed day whose page
has changed since says so in the header [main] and offers *Sign again* [main].

### 3.5 The close

| Step | What happens | Mark |
|---|---|---|
| the evening message | at `LOGBOOK_NOTIFY_EVENING_HOUR`, the day's question (RFC 0027) | [main] (#329) |
| the evening dream | `dream day TODAY --evening`: a draft of the day so far (§6) | [proposed] |
| keep and sign | one form, one lock (§5) | [proposed]; Reflect and Sign is [main] |
| late lines attach | a line synced after the signature lands on the day; the header says `the page has changed since` | [main] |
| the 06:00 close | `sync --scheduled --close` runs `dream --catch-up`; under §6 rule 5 it dreams the signed day again only for lines that arrived after the signature | the run is [main]; the rule is [proposed] |
| the morning | the morning message for the day the close closed [main]; the Day's morning shape offers *sign again* when late lines arrived | [main] message, [proposed] offer |
| sign again | a re-signature keeps the confirmations still on the page, its dispositions and its note | [main] (RFC 0034 amendment 4, #324) |

## 4. The parts

### 4.1 What today was for [proposed]

The standing chapter whose stretch holds the day (`chapter` in the Day's JSON, [main]), and the goals the
day **touched**: a standing goal is touched when a line of the day reaches it through an entity the goal's
own words name, or through a review on the day [main for reviews]. Touched is computed by code and never
by the pencil. `· chapter The Fjord Summer · Sail to Lofoten and back, touched by 3 lines`.

With no chapter and no goal standing, the section says so in one muted row and offers the two commands
that set them (`goal add`, `chapter open`), once a week at most; it never invents a purpose for the day.

### 4.2 The ribbon [proposed]

Two lanes across the day's span, inline SVG drawn by the server (as the track is, [main] #325): above, the
**plan** (timed calendar entries; §9's dated tasks as ticks); below, what was **lived** (stays, moves and
calls, from the timeline). No verdict text: no *on time*, *missed*, *overran*. A planned entry the lived
lane does not meet is drawn as itself, and the reader sees the gap. Phone width: the ribbon is the column's
width and its labels fold under it.

### 4.3 The goodnight story [proposed]

The pencil's first part: a few calm, concrete sentences of the day, part `story` (dream-day/4, §7), each
segment evidenced as every segment is. It ends with a **computed closing line**, written by code and not
by the model: what tomorrow holds (`Tomorrow: two entries, the first at 09:00`), or nothing. The story
replaces the dream's `day` paragraph on the evening page; a draft written by dream-day/3 shows its `day`
part in the same place.

### 4.4 Lenses [proposed]

A lens is a question of the owner's bank (RFC 0027, `policy/questions.json`) that the owner wants the
pencil to answer every evening, rather than one the digest asks them. It carries `"ask": "day"` (§13.2).
The dream answers each lens as a segment of part `lens:<id>`, evidenced; a lens the day gives no lines for
is printed by the reader, not the model: *the day doesn't answer this*. A lens is never asked of the owner
and is never the evening's question: the page asks at most one question (§2.5), and a lens is the pencil's
work.

### 4.5 Loose ends [proposed]

Three kinds, computed, never pencil:

- **promises both ways**: the open promises of `logbook promises` (I promised, I was asked; and what was
  promised to the owner) [main, the reader];
- **replies owed**: a message or mail in a direct conversation, from a person the record names, the last
  word in the conversation not the owner's for more than a day [proposed];
- **decisions** with a revisit date due (§4.8) [proposed].

Each item has three verbs: **kept**, **carry**, **let go**. They are written, at the close, as the
signature's dispositions (RFC 0034 amendment 1): kept → `kept`, carry → `carried`, let go → `dropped`.
No fifth word (RFC 0034, *why exactly four values*); `missed` stays on the CLI and is not offered here,
because the page does not grade the owner.

An item carried on three closes folds away into the count (`3 carried a while`), still open, still
reachable, never shown first again until something new touches it.

**Where this meets main** (§14 item 1): a disposition today names a line *on the page being signed*, and
`promises` reads it from the standing signature *of the line's own day*. Most loose ends were made on an
earlier day, so neither the writer nor the reader can carry their verbs today. The design needs RFC 0034
amendment 5 (§13.5); until it lands, a loose end from an earlier day closes through `promises done` [main]
and its *let go* has no writer.

### 4.6 Touched today: connections, idea notes, how the idea moved [proposed]

- **Connections**: the pencil proposes that a line of the day belongs to a canonical entity (RFC 0037),
  "this Notion page is part of *Boat-share log*", as a proposal of kind `link` (§13.3), naming entity ids
  only from the material it was given, never one it made up. Kept, a link is the line
  `entity_review.accept` writes for it [main, the writer], an `entity/v1` line binding the observed
  reference to the canonical entity.
- **Idea notes**: a sentence about an idea, kept as a `note/v1` labelled `idea`, `extra.entity` the idea's
  id.
- **How the idea moved**: the touches of the day, counted as the Ideas shelf counts them [main], and a
  status the pencil proposes (`exploring` → `build`), written only through `entity_status.write` when the
  owner answers [main, the writer].

### 4.7 Learned [proposed]

Sentences of part `learned`, evidenced; one kept is a `note/v1` labelled `learned`.

### 4.8 Decided [proposed]

Sentences of part `decision`, evidenced; one kept is a `note/v1` labelled `decision`, with an optional
`extra.revisit` (a local day). Looking back (§4.12) brings a decision back on its revisit day, and it
joins the loose ends on that day. A call's synthesis already proposes decisions [main]; the page shows
them here, under the call's name, not twice.

### 4.9 People [proposed but for the parts marked]

- **with**: the day's company [main] and the owner's word, marked *(you said)* [main].
- **who showed up**: everyone the day confirms, by name, in the order they first appear, with no count
  beside a name.
- **birthdays**: today's, by name.
- **one reconnect**, on the morning shape only: one person from `people drift` [main, the reader], with
  its reason in words and never in numbers: *you sailed together most of 2022; the last time was in June*.
  Never the same person two mornings running; never someone the owner let go. One at most.

### 4.10 Photos and track [main, #325]

As they are: a strip under each row, the track above the timeline.

### 4.11 Everything the day held [main, #331]

As it is: every line of the day, folded by source, and the messages by conversation.

### 4.12 Looking back [proposed but for the anniversaries]

The same date 1, 2, 3, 5 and 10 years before (the anniversaries' years [main]); for each, the **first
sentence of that day's reflection** when there was one, and the people of the day together [main]; and
the decisions whose revisit day is today (§4.8).

### 4.13 The record, folded [main]

The timeline, unplaced, health, weather, sources, readiness, as `logbook day` prints them.

### 4.14 Close [proposed but for the parts marked]

- **asked of you**: the evening question (RFC 0027), one, ignorable [main]; the delegations and requests
  the reflection read [main];
- **reflect**: your words, typed or said [main];
- **the day in a word**: one optional word, kept as a `note/v1` labelled `word`;
- **Keep and sign** (§5).

## 5. Keep and sign [proposed]

One form at the foot of the evening page, one POST, one hold of the writer lock, in this order:

1. the **kept notes**: each kept sentence as a `note/v1` line through `logbook/core/notes.py` [main, the
   path], labelled `learned`, `idea`, `decision` (with `extra.revisit`) or `word`, `extra.from` the draft's
   id and `extra.segment` its part and its place among the draft's segments;
2. the **link lines**: each kept `link` through `entity_review.accept` [main];
3. the **delegations** ticked, as `reflect.close` writes them today [main];
4. then **the signature**, through `reflect.close` and `signing.sign` unchanged [main], carrying the loose
   ends' dispositions (§4.5).

Every item is checked before the first line is written; any refusal writes nothing. The lock is held from
the reading to the last append; a moved head is `HeadMoved` and nothing is written [main, the rule].

**CLI parity**, so every click has a command that writes the same lines byte for byte:

```
logbook day sign 2026-10-19 --keep 2,5
logbook day reflect 2026-10-19 --text "…" --sign --keep 2,5 --accept 1
```

`--keep` takes the numbers of the pencil's keepable sentences and links as the page numbers them.
`--keep` and the existing `--kept` (a disposition) are one letter apart; §16 q6 asks whether the name
stays.

The Library's *What it is not* (`docs/serve.md`) says the pages write no note but the reflection. Keep and
sign writes kept notes from the page, so that sentence is amended with this slice (§13.6).

## 6. The rules of the evening dream

1. **`dream day TODAY --evening`** writes a draft of the day so far, with `extra.evening: true` and the
   moment it read up to. `dream day` names any day today, today included [main]; the flag and the field
   are [proposed] (§13.3).
2. **The catch-up never dreams today on its own.** `dream --catch-up` reads the days *before* today [main].
   The evening dream is asked for: by the evening shape's *Dream the day so far* button, or the schedule's
   evening run when the owner sets it (§16 q1).
3. **The signature never confirms the draft line.** On `main`, `day sign` without `--confirm` confirms
   every line on the page but retractions and signatures, and a draft line whose `at` falls on the day is
   one of them; the morning dream of yesterday is written today, so today's plain signature confirms it.
   RFC 0036 says a draft is never a confirmation, and a signature that lists the draft's id in `confirmed`
   reads as if it were. Proposed (§13.5): `confirmed` never names a `draft` line; the page digest still
   covers it, so the owner signed what they were shown.
4. **Kept lines never trigger a re-dream.** On `main` the catch-up dreams a day again when the ids it would
   read differ (`extra.read_ids_sha256`); a signature is never material (`EXCLUDED_KINDS`), but a reflection,
   a kept note and an accepted event are. Proposed: a line written by the close (a note or a line whose
   `extra.from` names a draft of the day, the reflection, the delegations) is left out of that comparison.
5. **After a signature, the 06:00 close dreams the day again only when other lines arrived after it**: a
   line on the day with a `seq` above the signature's that rule 4 does not set aside. The new draft
   supersedes the evening one, and the reader shows only its proposals **not yet kept**, under the head
   *since you signed*. "Not yet kept" is matched by content, not by `raw_id`: a confirmed proposal's
   `raw_id` is `<draft id>/<number>`, and the morning draft has another id. The kept line's
   `extra.proposal` carries the proposal's kind and its identifying fields (an event's span and title, a
   link's entity and reference), and a proposal with the same is kept.
6. **A signed day with no late lines is never dreamed again**, unless its entry changed (`draft/v1` rule 7,
   [main]) or the owner asks (`dream day DAY`, [main]).

## 7. The voice of dream-day/4 [proposed]

The prompt after `dream-day/3` (`docs/dream-prompt.md`):

- never moralise and never flatter: no *should*, no praise, no judgement of the day;
- every number is one the material gave; the model counts nothing itself;
- an inference says so, in the sentence: *this is an inference*;
- at most **one proposal** of change (a thing to do differently), beside the proposals to confirm (events,
  links), which are facts to check and not advice;
- **one question** for the reflection, where dream-day/3 asks two;
- the day's language, as `dream.language_of` finds it [main];
- the story calm, concrete, short: what happened, where, with whom, in the order it happened.

Its parts are §13.4's.

## 8. The week page [proposed]

`/week/2026-W42`, the Sunday's week draft [main, `dream week`] grown into a page:

- **seven ribbons**, one per day, each a link to its Day;
- **where the week went**: the week draft's computed numbers (`extra.numbers`, [main]), each with its lines;
- **goals**: each standing goal with the five verdicts of `review goal` [main] (`advancing`, `stalled`,
  `done`, `let go`, `superseded`), and the two honest moves when a goal stalls: **change the days** (the
  week's one proposal) or **change the sentence** (reword the goal, `goal add --supersedes` [main], or let it
  go, `goal review GOAL 'let go'` [main]);
- **keep the proposal** as a `note/v1` labelled `intention` on the Sunday: next week's morning pages show it
  under *what it is for*;
- **the stale question**, one a week [main, #329];
- **people who moved** against the week before (the week draft's `people`, [main]), names only;
- **Hold**: the census's counts and, once RFC 0042 §8 is built, its weight, on the week page only; never a
  name of a file or a sender (RFC 0042 §2 rule 2), and Hold's own weekly act, the sweep, stays Hold's;
- **close the week** through the writers that exist: `review goal` [main], the intention note, `status`
  [main]. No new profile.

## 9. The plan, read and never run [proposed]

The owner keeps tasks in a task tool, and `sync notion` already writes its rows into the record [main]: one
`event/v1` line per edit, tier 1, its title, a database row's `status`, `select`, `multi_select`, `date`
and `checkbox` values by name, its relations, never its body. The page reads the plan from those lines and
from nothing else; it fetches nothing and writes nothing to the task tool.

- **Today's dated tasks**: rows whose `date` is today, five at most, the rest as a count, each linked to
  its line (`/line/ID`).
- **The next trip** as a countdown: *Lofoten in 12 days*.
- **What the plan holds for this city**: the rows that name the city the day's stays are in, three at most.
- **A queued reading note** whose link appears in the day's browse, watch or listen lines.

Today's tasks join the loose ends with the verbs **done** / **tomorrow** / **let go**, written as the
signature's dispositions by the task line's id (`kept`, `carried`, `dropped`). The signed day crosses under
its policy entry with its dispositions (RFC 0034, *the gate on the crossing* [main]); the downstream agent
that runs the task tool reads them and applies them there: done, rolled to tomorrow, archived. Never
deleted. An unsigned day changes nothing. The task lines are edits of earlier days, so this needs the same
RFC 0034 amendment as §4.5 (§13.5).

**One message per time of day across both systems**: when the task tool's agent also sends a morning
message, one of the two is configured off; the record never sends two at one hour.

**When you sign**, a fold before the button: per entry of `policy/crossing.json`, what will cross and what
stays home, and why, from the crossing's own dry run (`export crossing --dry-run` [main]). Mail stays home
until a mail filter exists (people the record names, minus senders let go in Hold, §11), which is its own
RFC.

The week page adds **time by project** (the plan's projects against the lived hours), **the sprint's
outcomes** (the rows the week moved to done), and one fold of **tasks untouched for 90 days**, let go
together in one decision.

## 10. The day boundary [proposed, but for `day_start`]

The design works under either `day_start` [main, RFC 0036], and favours midnight, the default, so the plan
and the record share one clock. Between midnight and the night's first sleep (or 06:00 when no sleep line
says), `/today` shows today's morning shape and offers, first, to close yesterday while it is unsigned
(`/today` redirects by `day_start` today [main]; the offer is proposed). A night that ran past midnight is
drawn faded on the evening's ribbon and named at the top of the next morning: *last night ran on to 01:40*.

## 11. The timeline and the moment [proposed]

**`/timeline`** is a list of moments beside a map, at the zoom levels day, week, month and year, each a
link (no script). A **moment** is a stay, drawn as a card:

- the **place**: its `places.json` name, or, when it has none, the map file's nearest named thing,
  proposed in grey;
- the **time**;
- **faces**: confirmed in ink, proposed in grey with their reason;
- **photos**, the owner's own camera first;
- **paid**, at tier 3;
- what passed **during** the window: messages, calls, Claude and agent conversations, mail from people;
- **what was said**, only when recorded with consent (`transcript/v1`'s consent, [main] as a field);
- **notes**, **gifts**.

**The map**: one offline OpenStreetMap PMTiles file on the home machine, named by `map_file` in
`logbook.json`, read by the server and drawn as inline SVG: no script, nothing fetched, the OpenStreetMap
attribution on every map. The Library's one interactive map is the World page's canvas [main,
`docs/world.md`], which draws no tiles; a second interactive map, on the timeline, comes only after an ADR.

**Who was there**, all proposals: faces from the owner's own camera only; calendar invitees; named speakers
[main]; an agent's meeting proposals. A **review-with queue** per journey or week asks once for a stretch:
*whole stretch* / *some days* / *not with me*, writing `with` notes per day [main, `logbook with`], `with
--from/--to` [new], and a note labelled `not-with` [new].

**Mail**, one rule: a person the record names is on it, minus the senders let go in Hold. The rest is
folded on the page and is what the mail filter keeps home (§9). New mail lines would keep Gmail's category
and whether a `List-Unsubscribe` header was present under `extra`, never the links (§14 item 12).

A **Companies row** (updates from an org's domain, meetings with its people); the **gift act**, a note
labelled `gift`, given or received; the **money slot**, with its gap stated when no payment source covers
the day (*no card lines for this day*).

## 12. What the owner's life adds [proposed]

- **A day is the local calendar day where it began**, and a signed day keeps its zone. On `main` every day
  is grouped in the record's one zone (`logbook.json` `timezone`, SPEC §3.2) under its `day_start`, the
  page digest is over that zone [main], and every line already carries its own `tz` in the envelope. Days
  in the zone where the owner was is a change to SPEC §3.2, which needs a spec version bump, a regenerated
  conformance fixture and an ADR (§14 item 8); `extra.tz` on the signature is not needed for it, since the
  page digest names the zone.
- **Lives with**: a note labelled `lives-with` (a person, from a date) makes that person with the owner at
  home stays without asking: Kari is with Ines at home. Away, her face proposes as anyone's does.
- **Places carry a class** for the night's colour: home, family, aboard, away. `places.json` has `kind`
  (`home`, `asset-berth`, `other`) and `tags` [main]; the class is read from them (`home`, a `family` tag, a
  stay aboard an asset, else away), not a new field.
- **On a journey day the morning reconnect** comes from the people placed in that city (a note labelled
  `lives-in`, or their contact's city) and not yet seen on the journey; the journey page lists them as
  *seen* / *not yet*.
- **A fifth zoom, all years** (`/timeline/life`): per place and per vessel, the visits, the years and who
  was there, names only.
- **The photo of the day**, proposed by the dream and kept at the close as a star with its note (`keeper/v1`,
  RFC 0024 and the 2026-10-14 amendment [main]), not a new note label (§14 item 13).
- **A meeting note-taker's summaries** as *what was said*, under the consent sentence; its attendees as
  proposals.
- **The Companies row grouped by portfolio** [main, `--portfolio`]; an update kept as the holding's status
  through the Manifest's writer, `entity_status.write` [main], in its words (`hold`, `add`, `sell`), not new
  ones.
- **The money bridge**: the ledger as the truth (`docs/ledger.md`); receipt mails proposed at tier 3 until
  the ledger covers the day.

## 13. The amendments

None is adopted by this RFC except §13.1, which this pull request carries. Each is the text its document
would gain.

### 13.1 `draft/v1`, forward compatibility (2026-10-19) [in flight, this pull request]

A reader shows the proposals of the kinds it knows, counts the others in the draft's JSON as
`proposals_unknown`, and does not call the line malformed for an unknown kind; a known kind of the wrong
shape is still malformed; numbers keep their places. Writers stay strict. The text is in
[`draft/v1`](0036-draft-v1.md), *Forward compatibility*. It is what lets §13.3 add `link` without making
every older reader say *malformed*. `bighydro/logbook-ts` needs the same change.

### 13.2 RFC 0027, `ask` [proposed]

> A question MAY carry `"ask"`: `"owner"` (absent is `"owner"`), the digest's question, asked of the owner;
> or `"day"`, a lens, which the dream answers every evening as part `lens:<id>` and which the digest never
> draws. A value outside the two is refused naming the file.

The reader on `main` ignores a key it does not know, so a lens written before the amendment is built would
be drawn as an evening question; the amendment and the digest's skip land together.

### 13.3 `draft/v1` amendment 2 [proposed]

> **A proposal of kind `link`**: `{kind: "link", entity, ref, evidence}`: `entity` a canonical entity id
> the material named, `ref` an observed reference (`{kind, value}`, RFC 0037 §3.2) of a line of the unit,
> `evidence` the line ids, non-empty. A writer drops a link whose entity the material did not name. Kept,
> it is the `entity/v1` line `entity_review.accept` writes, `extra.from` the draft's id.
>
> **`extra.evening`**: `true` on a day draft read before the day ended, with `extra.read_until`, the moment
> read up to. A reader heads it *the day so far*.

### 13.4 dream-day/4, its parts [proposed]

> The parts of a day's dream, in order: `story`, `lens:<id>` (one per lens), `threads`, `learned`,
> `decision`, `ideas`, `questions` (one), `people`, `promises`.

A reader on `main` already prints a part it does not know with no label (`drafts.day_json`), so the new
parts read on an older reader as unlabelled segments, evidenced as before.

### 13.5 RFC 0034 amendment 5, dispositions beyond the page, and drafts never confirmed [proposed]

Found by this RFC's reading of `main` (§14 items 1–2):

> A signature MAY give a disposition to an open commitment of an earlier day, by its line id, in
> `dispositions`, without listing it in `confirmed`; such an id is not on the page, and the page digest is
> unchanged by it. `promises` reads a commitment's disposition from the latest standing signature that
> gives it one, of its own day or a later day.
>
> `confirmed` never names a `draft` line.

### 13.6 The Library's *What it is not* [proposed, with slice C]

> Not an editor: the pages write nothing but the namings, the reviews, an org's or an idea's status, the
> reflection, **the notes kept at the close**, the signature, the stars and the company said above.

## 14. Where this design meets main

Read against RFC 0036, `draft/v1`, RFC 0027, `docs/day.md`, `docs/serve.md`, `docs/dream.md`,
`docs/signed-day.md`, `docs/review.md`, `docs/digest.md`, `docs/people.md`, `docs/promises.md` and the code
on `main`, 19 October 2026. Each finding, and how this RFC answers it:

1. **Dispositions are the page's alone.** RFC 0034 amendment 1 refuses a disposition for a line not on the
   page, and `promises` reads one from the signature of the line's own day; loose ends and the plan's tasks
   are mostly earlier lines. → §4.5, §9, amendment §13.5.
2. **The signature confirms the draft line.** `day sign` without `--confirm` confirms every line on the
   page but retractions and signatures, a draft included. → §6 rule 3, §13.5.
3. **Kept lines re-dream the day.** The catch-up compares the ids it would read; a reflection, a kept note
   and an accepted event change them. → §6 rule 4.
4. **Not yet kept, by `raw_id`, cannot cross drafts.** A confirmed proposal's `raw_id` names its draft. →
   §6 rule 5, matched by content.
5. **Two questions.** dream-day/3 asks two questions for the reflection, the digest asks one, and VISION
   says *one evening question*. → §7: one; lenses are the pencil's work, never asked of the owner (§4.4).
6. **One proposal.** The dream proposes many events, people and promises. → §7: "one proposal" is one of
   change; proposals to confirm are checks, not advice.
7. **`ask` would be silently ignored.** RFC 0027's reader ignores unknown keys, so a lens would be drawn as
   the evening question. → §13.2 lands with the digest's skip.
8. **A day is in the record's zone.** SPEC §3.2 and RFC 0036 group by the record's zone; the page digest
   names it. "The day where it began" is a spec change. → §12, its own RFC with a version bump.
9. **The Library writes no note but the reflection.** → §13.6.
10. **The Library refuses Sign with no reflection** (`docs/serve.md`, *Reflect and Sign*), while freedom says
    the question may be ignored forever. → Keep and sign takes no reflection; `day sign` already signs
    without one [main].
11. **"No script but the record button"** is true of the Day; the Places page and the World page carry
    their own [main]. → §2.11 says *on the Day*.
12. **Gmail's categories are dropped on purpose** (`logbook/contrib/adapters/gmail.py`): IMAP never shows
    them, and the two roads must write the same line. Keeping them under `extra` breaks that dedupe, and RFC
    0042's open question 4 already proposes `extra.list_unsubscribe`. → §11 marks both proposed and leaves them to Hold's
    and the mail filter's RFC.
13. **A photo is kept with a star**, `keeper/v1` (RFC 0024, RFC 0041 for every other line), not a note. →
    §12: the photo of the day is a star with its note.
14. **An org's status words** are `hold`, `add`, `sell`, `let-go`, `exited`, `passed` (RFC 0037); there is
    no `keep` or `watch`. → §12 uses `hold`, `add`, `sell`.
15. **A place's class** overlaps `kind` and `tags`. → §12 derives the class from them.
16. **"No summary"** (`docs/day.md`, *What it is not*): the summary lines are counts, and the story is
    pencil, never the reader's. → `docs/day.md` points here (this pull request).
17. **ADR 0005** says one message a day; `main` already sends a morning and an evening one. → §9's *one per
    time of day* is §16 q7.
18. **Faces** from any photo library are proposed on `main`; the timeline narrows to the owner's camera. →
    §11, proposed, a change to the with module's reasons.
19. **Birthdays** are a reader field with no writer yet (`docs/people.md`). → §3.1 marks it so.
20. **`--keep` and `--kept`.** → §16 q6.

## 15. Slices

Each slice is one pull request after the freeze, test first, and changes no page another slice owns.

- **A — the shapes and the computed parts**: the four shapes, what today was for, the ribbon, loose ends
  as a reader (no verbs yet), people, looking back, *Nothing from*. No model, no new line.
- **B — the dream**: dream-day/4, `--evening`, `extra.evening`, the parts of §13.4, lenses (with §13.2),
  `link` (§13.3), and §6's rules 4 and 5.
- **C — the acts**: Keep and sign, `--keep`, RFC 0034 amendment 5 (§13.5), the Library's sentence (§13.6).
- **D — the week page**.
- **E — the plan and the crossing preview** (§9).

The timeline (§11) and the owner's life (§12) are each an RFC of their own when their turn comes.

## 16. Open questions

1. **The evening hour, and closing on request.** Is the evening shape the notifier's hour
   (`LOGBOOK_NOTIFY_EVENING_HOUR`), a setting of its own, or only when the owner presses *close the day*?
   Recommended: the notifier's hour when set, else 20:00, and always on request.
2. **The owner's lenses.** Which questions are lenses, and who writes them? RFC 0027's bank is still to be
   written by a named author.
3. **The day in a word.** Kept as a note labelled `word`, or as the signature's `note`, which already exists
   and crosses at tier 1?
4. **The names.** *Pencil* and *ink*, and *goodnight story*: do they stay in the interface, or only in this
   RFC?
5. **`people --priority` on a page.** It ranks people by a plain score [main, CLI only]. VISION says no
   metrics near people. Recommended: never on a page.
6. **`--keep` beside `--kept`.** Keep the name, or fold kept sentences into `--accept`, which already takes
   the dream's numbered proposals?
7. **One message per time of day.** Is ADR 0005's *one message a day* amended to one per time of day, as
   `main` already behaves?

## Example (synthetic)

Ines's Sunday, 18 October 2026, aboard *Solvind* with Ola, read at 21:30, unsigned, as the evening shape
would print it:

```
2026-10-18  Sunday · unsigned · evening · chapter The Fjord Summer
  for           Sail to Lofoten and back · touched by 3 lines

  draft         model:qwen2.5-7b-instruct · the day so far · read at 0b7c41e2 · 41 lines
      story     A morning at the berth in Vollen, then four hours under sail with Ola Nordmann.  […0a11, …0a12]
      story     You reefed early and came in before the rain.  […0a14]
                Tomorrow: two entries, the first at 09:00.
      lens:boat The new reefing lines ran cleanly in the gusts; this is an inference.  […0a14]
      lens:money  the day doesn't answer this
      learned   Reefing before the harbour mouth left room to come about.  […0a14]
    ? link 1    "Crew list" belongs to Boat-share log  proposed  […0a20]

  loose ends    1 promise · 1 reply owed
      I promised   to Ola Nordmann  "I'll send the photos by Tuesday."   kept · carry · let go
      reply owed   Kari Nordmann, since Friday                             kept · carry · let go

  Nothing from: decisions, photos
```

Nothing in it is written until Ines presses Keep and sign.
