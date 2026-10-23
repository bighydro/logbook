# RFC 0047 — The Library's doors

Status: draft · 2026-10-22 · for the captain's review before anything visual is built · changes no
line, no envelope, no SPEC · builds on RFC 0034 (the signed day), RFC 0036 (goals, chapters, drafts),
RFC 0037 (entities), RFC 0042 (Hold), RFC 0043 (the Day page) and ADR 0025 (derived tables) · names
RFC 0042's Holdings as the next door and builds none of it

## 1. Why

The Library has grown one page per reader. The navigation now carries fourteen links: Logbook, today,
days, journeys, people, manifest, ideas, promises, goals, agents, places, assets, gaps and world. Each
is a good page. Together they are a filing cabinet. To answer "when did I last see Ola, and where?" you
open People, then a person, then a Day, then the World, and each of those pages is slow on its own.

On a record of millions of lines, a page can wait minutes: several of today's pages read the whole
record each time they are asked for. On the scale harness's synthetic record (`tests/perf`, two
million lines over ten years), the slowest doors take one to three minutes each, cold, and opening
every door at once takes about twenty.

So this RFC proposes fewer doors, each one fast. Four doors, one field and one gear, named in the
words of a life rather than the words of a database. Every page that exists today keeps a home and
every link that exists today keeps working.

## 2. Words

- A **door** is a top-level page in the navigation. There are four in this build: **Today**,
  **Life**, **People** and **Places**.
- **Ask** is one field on every page. It is not a door.
- **The gear** is the machinery: sources, crossings, agents, the Manifest, the data gaps. It is one
  icon at the end of the navigation, not a door.
- A **moment** is when, where and who. It is the atom of every door. A moment is a day (or a span of
  one), the place the owner was, and the people who were there. Every door shows moments, and every
  moment links to the same moment through the other doors.
- A **lens** is how a door looks at a moment: Life by time, People by person, Places by place.
  Moving between doors keeps the moment. It does not start over.
- **Ink** is what the owner wrote or confirmed: a reflection, a signature, a name given, a person
  confirmed present. **Pencil** is what a model drafted or a rule proposed and the owner has not
  confirmed. RFC 0043 named them for the Day; this RFC holds every door to them.
- **Volumes** is the printed edition: a year of a life, bound. It is what the code and the docs call
  "the paper edition" and "the press" today (§10).
- **Holdings** is the fifth door, not in this build (§11).

## 3. Principles

1. **The moment is the atom.** Nothing is shown that is not anchored to a moment or a set of them.
   A count without its moments is a number. A door shows the moments behind every number it shows.
2. **Pivot, never switch.** From any moment you can open the same moment in another lens: a day on
   Life opens its people and its place; a person opens the places and the days you shared; a place
   opens its days and its people. The link keeps the moment in its address (§5).
3. **Ink and pencil everywhere.** Pencil is never mistaken for ink: drafted text is set lighter, in
   the pencil style RFC 0043 gave the Day, with the model's name on hover, and it is never counted as
   the owner's word.
4. **Calm surfaces.** The owner's words and the people come first. Numbers recede: they are small,
   set in the muted colour, and never the first thing on a page. No feed, no streak, no score
   (RULES 7).
5. **Life words, not database words.** A page says "days together", not "lines"; "last seen", not
   "max(at)"; "places you slept", not "stays with nights > 0". The gear may use the machine's words,
   because it is the machine.
6. **Instant.** Every door opens in under 100 ms from what was built ahead of time. Opening every
   door at once is as fast as opening one. No spinner anywhere: a page that is not built yet says
   when it will be, in one sentence, and links to the last one built.
7. **Kind empty states.** An empty door says what will fill it and how, in one sentence: "Nobody
   yet. People appear here once a message, a call or a photo names them." Never "no rows".
8. **Every old address keeps working** (§9).

## 4. The doors

### 4.1 Today: the front door

What the owner reads at 07:00, on a phone. It must work at 375 px wide first and at desktop width
second.

From the top:

1. **The date and where you are.** One line: the day in words, the place of the night, the weather
   if the record holds it.
2. **What's open.** Promises both ways (yours and theirs, with whom and since when), the plan
   (today's tasks from the task tool, read and never run, RFC 0043 §9), replies owed. At most
   seven, the oldest first. Each opens its moment.
3. **One memory.** "A year ago today": the day one year back, or the nearest year that holds
   something worth showing (a starred photo, a signed reflection, a trip). One, never a list. It
   opens on Life at that day.
4. **Reflect and Sign.** The Day page's two acts (RFC 0034, RFC 0043), at the foot, the same forms
   and the same writes as today.

Today is the Day page's morning shape (RFC 0043 §5) promoted to the front door. `/day/DATE` remains
the page of any one day, and it is reached from every door.

### 4.2 Life

One timeline of the owner's life, zoomable, with the current chapter and the year's goals above it.

- **At the top:** the current chapter (its name, since when, its rules in the owner's words) and the
  year's goals, each with its last review. In ink, or in pencil when a model drafted them.
- **Below:** one zoomable timeline. The zoom levels are **day, week, trip, year and life**. The
  timeline runs from the owner's birth to a bounded future. The bounds are a record setting,
  `life` in `logbook.json` (for the persona: `{"from": "1986-07-01", "to": "2035-12-31"}`). Without
  the setting, the timeline runs from the record's first day to the end of next year. It never runs
  to the last line the record holds: a calendar entry in 2055 is not a reason to draw thirty years of
  nothing (the World's slider did exactly that; #379 fixes it).
- **On the timeline:** chapters as bands, goals as threads that run from their start to their review,
  reflections on their days (ink), drafts on theirs (pencil), ideas moving through their stages (RFC
  0037), trips as spans, and the gaps where the record is silent, drawn as silence and not as an
  error.
- **What folds in:** Days (`/days`), Journeys (`/journeys`), Trips (`/trips`), looking back (the
  Day's 1, 2, 3, 5 and 10 years), the gaps (`/gaps`, the owner's side of it: when the record is
  silent), Goals (`/goals`) and the Ideas shelf (`/ideas`). Each becomes a zoom or a band of Life.
- **Volumes** (§10) is printed from Life: a year, bound.

Life opens on the current chapter, at the week zoom, with today in view.

### 4.3 People

Everyone, by closeness. Closeness is days together in the last year, then calls and messages, then
how long you have known them. It is not a score and it is never shown as a number. It is only the
order.

Each person is a thread:

- days together, as a strip over the years, each day a link to that day on Life;
- last contact, in words ("lunch at the harbour, 12 days ago");
- promises both ways, open first;
- what was said: the last few messages and transcripts with them, at the tier the page reads, each
  with its moment;
- the places you shared, each a link to Places;
- in pencil, what a model drafted about them (`draft/v1` unit `person`), with its evidence.

The review queue (`people review`) stays on People, below the people, and out of the way.

### 4.4 Places

The globe. Trips as arcs between the places of a life. The places themselves: home, the cabin, the
cities. Each place opens its days (on Life) and its people (on People). The World page (`/world`)
becomes this door. The Places review queue (`setup places review`) stays here, below the globe.

### 4.5 Ask

One field, at the top of every page, on every door.

- **v1 searches the whole record, instantly.** Words, names, places and dates, through the index and
  never through the files. A result is a moment, not a line: when, where, who, and the words that
  matched, each opening its moment on the door that fits it. Held to the page's tier (a page that
  reads tier 1 searches tier 1).
- **v2 answers questions in natural language** ("when did I last sail with Ola?"), only where the
  crossing policy has a `chat` entry naming the model and its tier ceiling, as every other crossing
  does (ADR 0016). Every answer cites the record lines it used, each a link to the line and its
  moment. An answer without a citation is not shown. The question and the answer are never written
  to the record unless the owner keeps them (a `note/v1`, in ink, the owner's act).

### 4.6 The gear

The machinery, honest and out of the way, behind one icon at the end of the navigation. In this
build it holds:

- **Sources:** what each source sent and when it last spoke (today's `/gaps`, its machine side, and
  `doctor`'s source checks);
- **Crossings:** what left, when, to where, under which policy entry;
- **Agents:** the sessions with an agent (`/agents`);
- **The Manifest:** the orgs and the people with more than one (`/manifest`, `/manifest/people`,
  `/org/ID`);
- **Assets:** the registered assets and their last fix (`/assets`), exactly as it is today, until
  Holdings is built (§11);
- **The build:** when each door was last built, how long it took, and the command that builds it
  again (phases 4 and 5 of the build plan).

## 5. Addresses

Every door has one address, and every address can carry a moment:

| door | address | with a moment |
|---|---|---|
| Today | `/` | (always today) |
| Life | `/life` | `/life?at=2026-06-15`, `/life?at=2026-06&zoom=week`, `/life?trip=2026-06-15/2026-06-20` |
| People | `/people` | `/people/ID?at=2026-06-15` (scrolled to that day of the thread) |
| Places | `/places` | `/places/ID?at=2026-06-15`, `/places?trip=2026-06-15/2026-06-20` |
| Ask | `/ask?q=…` | (the results are moments) |
| The gear | `/gear` | `/gear/sources`, `/gear/crossings`, `/gear/agents`, `/gear/manifest`, `/gear/assets` |
| One day | `/day/2026-06-15` | (it is a moment) |
| One line | `/line/ID` | unchanged |

`/day/DATE` and `/line/ID` keep their addresses: they are linked from signed pages, printed pages,
notes and other people's shared pages.

## 6. The navigation

```
Today   Life   People   Places                    [ Ask …            ]   ⚙
```

On a phone the four doors are a bar at the foot of the screen and Ask is at the top. There is room
for a fifth door between Places and Ask; it stays empty until Holdings is built.

## 7. Ink and pencil, everywhere

The Day page already marks them (RFC 0043 §3). This RFC extends the same two styles to every door:

- **Ink:** the owner's text in the body face, at full contrast.
- **Pencil:** a model's or a rule's text in the same face, lighter, with a thin dotted underline and
  the model's or rule's name on hover. Confirming it (the existing acts: sign, name, accept) turns it
  to ink in place.
- Counts and dates are neither: they are facts the record holds, set small in the muted colour.

## 8. Speed: built ahead, served as files

The doors are not computed when they are asked for. They are built ahead of time, after the 06:00
close and after every sign, reflect or name, and served as files. The server keeps only the writing
actions. This is phases 4 to 6 of the build plan, and it does not depend on the design above. Two
rules from it shape the design:

- **No door may need a whole-record computation at request time.** If a door needs one, it is
  computed in the build, by delta (ADR 0025), never in the request.
- **A page no build wrote is rendered once and kept.** A Day a year ago or a `/days` window the
  owner chose is rendered on the first request and saved beside the built pages, so the next visit
  is a file and the next build builds it again. Between builds a page is as of its build. This is
  what phase 4 (#382) does.

## 9. Every page today, and its new home

Every address below keeps working. A page that moved answers with a redirect (301) to its new home,
carrying the moment it named (the query is translated, not dropped). The gear's pages keep their
contents exactly.

| today | what it is | new home | redirect |
|---|---|---|---|
| `/` | the front page: the shelves listed | Today | stays |
| `/today` | redirect to today's Day | Today | 302 → `/` (today) |
| `/day/DATE` | one day | stays; reached from every door | stays |
| `/day/DATE/reflect`, `/day/DATE/sign` | the Day's two acts (POST) | stay | — |
| `/star`, `/with` | the Day's acts on its lines (POST) | stay | — |
| `/days?from=&to=` | a window of days | Life, day zoom | 301 → `/life?from=&to=&zoom=day` |
| `/trips?year=` | the trips of a year | Life, trip zoom | 301 → `/life?year=&zoom=trip` |
| `/journeys?year=` | the journeys of a year | Life, trip zoom | 301 → `/life?year=&zoom=trip` |
| `/journeys/FIRST/LAST` | one journey | Life, at that trip | 301 → `/life?trip=FIRST/LAST` |
| `/journeys/name` | name a journey (POST) | stays (Life's form posts here) | — |
| `/goals`, `/goals/ID` | the goals, one goal | Life: goals at the top, a goal as a thread | 301 → `/life?goal=ID` |
| `/ideas`, `/idea/ID` | the ideas by stage, one idea | Life: ideas moving | 301 → `/life?idea=ID` |
| `/ideas/review`, `/ideas/status` | the Ideas' acts (POST) | stay | — |
| `/gaps` | where each source went quiet | the gear (sources); Life draws the silence | 301 → `/gear/sources` |
| `/promises`, `/promises/ID` | promises both ways | Today (open ones); People (by person) | 301 → `/` and `/people/ID?promise=ID` |
| `/people?year=` | people by days together | People | stays |
| `/people/ID` | one person | People | stays |
| `/people/review` | the people review (POST) | stays | — |
| `/places` | named places and the review | Places | stays |
| `/places/review` | the places review (POST) | stays | — |
| `/world?from=&to=` | the globe | Places | 301 → `/places?from=&to=` |
| `/assets` | the registered assets | the gear, unchanged, until Holdings (§11) | 301 → `/gear/assets` |
| `/manifest`, `/manifest/people`, `/org/ID` | the orgs | the gear | 301 → `/gear/manifest…` |
| `/manifest/review`, `/manifest/status` | the Manifest's acts (POST) | stay | — |
| `/agents?page=` | sessions with an agent | the gear | 301 → `/gear/agents?page=` |
| `/line/ID`, `/photo/ID` | one line; a photo's pixels | stay | stays |

Pages proposed in open pull requests have a home too: the week page (#376) is Life at the week
zoom; the timeline (#361) is Life itself; search in the Library (#363) is Ask v1.

Outside the Library:

| today | new home |
|---|---|
| `logbook export site` | unchanged: it is also the builder of the doors (phase 4) |
| `logbook year … --print`, `logbook trip … --print`, "the paper edition", "the press" | Volumes (§10) |
| `logbook serve --status` | unchanged; it also says when each door was last built |

## 10. Volumes

The printed edition is called **Volumes**: a year of a life, bound. Today the code and the docs call
it "the paper edition" (`print_page.py`, `print_layout.py`, `docs/print.md`, `docs/year.md`) and "the
press" ("the press's pick" for a starred photo, RFC 0024 and RFC 0041). The name "Days Press" is not
in the repository; these two names are what it means.

The rename, once this RFC is adopted, in one pull request:

- every user-facing word: the help of `--print`, the docs, the Day page's star text ("the Volume's
  pick"), the changelog fragment;
- `docs/print.md` becomes `docs/volumes.md`, with a redirect page for the old name;
- `logbook volume 2026` as the command, with `logbook year 2026 --html PATH --print` kept as an alias
  that prints one line saying the new name;
- the RFC texts that say "the press" get a dated amendment line, not a rewrite.

The module names (`print_page`, `print_layout`) stay: they are not seen by the owner, and renaming
them breaks every pending branch for no reader's benefit.

## 11. Holdings: the next door

Holdings is the fifth door: investments, homes, boats, cars, and the census of everything owned
(RFC 0042, Hold). It is not in this build. This RFC reserves its place in the navigation, between
Places and Ask, and its address, `/holdings`. Until it is built, `/assets` stays exactly as it is,
reachable from the gear. When Holdings is built, `/assets` redirects to it.

## 12. What this RFC does not change

No line, no profile, no envelope, no SPEC. Every write keeps its form, its address and its code path.
The readers keep their JSON (SPEC §6.1). The tier gates are the same: a door reads what the page's
gate allows, and a built page is owned by the record's user, mode 0600, never exported and never
crossed.

## 13. The order of the build

After this RFC is approved, one pull request per door, in this order: Today, Life, People, Places,
then Ask v1, then Ask v2, then the gear. Each with screenshots from the demo record at desktop and
phone width, light and dark, and an independent review of the screenshots alone before it merges.

## 14. Open questions

1. **Closeness.** Days together in the last year, then contact, then years known: is that the order
   you want on People, or should the people you live with always come first?
2. **The memory on Today.** Exactly one year ago, or the best day near it in any year? And what is
   "best": a starred photo, a signed reflection, a trip?
3. **The `life` setting.** A birth date and an end year in `logbook.json`, or a `chapter/v1` named
   "Born" that the timeline reads? The first is simpler; the second keeps it in the record, signed.
4. **Promises.** Open promises on Today and each person's on People: is there still a page of all
   promises, or does the gear keep the full list?
5. **Gaps.** The record's silences drawn on Life, the sources' silences in the gear. Is that split
   right, or should the gear keep both?
6. **Ideas and goals.** As threads on Life, or as a shelf of their own under Life?
7. **Ask v2's model.** Which model does the `chat` entry name by default, local or remote, and what
   tier ceiling does it start at? (The proposal: none by default; v2 is off until the owner adds
   the entry.)
8. **Redirects.** 301 (permanent, browsers remember) or 302 (temporary, for a while, in case the
   homes move again)? The proposal: 302 for one release, then 301.
9. **Volumes.** One volume per calendar year, or one per chapter when a chapter spans years?
10. **Holdings' place.** Between Places and Ask, as proposed, or inside the gear until it is built?
11. **Built pages on a sealed record.** A built page holds what the Library shows, and on a sealed
    record (RFC 0029) that includes tier 2–3 lines, in plain text on this disk (`0600`, in the cache
    folder, never in the record's folder). RFC 0029 §8 refused to keep a plaintext index for exactly
    that reason: it blinds `raw_id` and rejected a decrypted index on disk. Are built pages of tier 2–3
    lines allowed on disk in plain text, or does a sealed record build tier 1 only unless the owner
    opts in?
