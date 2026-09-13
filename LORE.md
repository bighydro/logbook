# Lore — where the logbook comes from

A project needs to know its ancestors. Logbook has two lines of descent, human and computational, and they turn out to be the same line.

## I. The human logbook

**The knot and the board.** In the 1500s a sailor measured a ship's speed by throwing a flat wooden board — the *log* — over the stern on a line knotted at fixed intervals, and counting how many knots ran out while a small sandglass emptied. Speed at sea is still given in *knots* because of that board. The readings were entered in a book beside the helm: the log-book. Course, speed, wind, weather, position, every few hours, in ink, in order, initialled by the officer of the watch. Within a century "logbook" meant the whole record of a voyage: who came aboard, who died, what was sighted, what was decided. It was never written for an audience. It was written because things happened, and because later someone would need to know what actually occurred.

**Truth by construction.** A ship's log is admissible in court. Entries are made at the time, in sequence, in a bound book with numbered pages; an error is struck through with a single line so the original stays legible, and the correction is initialled. Nothing is erased. Nothing is written later and backdated. Three rules — append only, corrections as new entries, never delete — that are four hundred years older than any database and identical to the ones this project enforces.

**The voyages we know only because someone kept the book.** Antonio Pigafetta kept the diary of Magellan's circumnavigation (1519–22); only eighteen men came home, and most of what we know of the first voyage around the earth is his book. James Cook's journals fixed the coastlines of the Pacific. Charles Darwin kept a diary aboard *Beagle* for five years (1831–36); *On the Origin of Species* grew out of those notebooks, twenty years later, because he could reread what he had actually seen rather than what he remembered seeing. Robert Falcon Scott's last diary was found beside his body in the Antarctic in 1912; Shackleton's men kept theirs on the ice for two years and every one of them came home. Lighthouse keepers, weather stations, station masters, mine foremen: for three centuries the ordinary world was run by people making dated entries in ruled books, and the climate scientists of our own century now reconstruct the weather of the 1800s from ships' logs, because those pages are the only instruments that were there.

**The captain's logbook and the pilot's.** Every pilot alive keeps a logbook. It is a legal document: date, aircraft, route, hours, landings, who was in command. A licence is granted on the strength of it and can be lost over it. It is the one place where a pilot's life in the air is true, and pilots are sentimental about theirs in a way they are about nothing else. The captain's log — the phrase is now a joke from television — was the same thing at sea: the commander's own record, in the first person, of what was decided and why.

**The private book.** Beside the official log there was always another book. Marcus Aurelius wrote his *Meditations* for no reader but himself; the Greek title is simply "to himself". Samuel Pepys kept a diary in shorthand for nine years (1660–69) and recorded the plague, the Great Fire, and his own small vanities with equal care; nobody read it for a century and a half. Benjamin Franklin ruled a small book into thirteen virtues and marked each evening's faults with a dot — the first self-tracker. Leonardo's notebooks, Thoreau's journal, the commonplace books in which people for centuries copied what they wanted to keep: none of these were feeds. They were written by one person, for that person, to be reread.

**The captain of my soul.** William Ernest Henley wrote *Invictus* in 1875 from a hospital bed, after losing a foot to tuberculosis of the bone:

> I am the master of my fate,
> I am the captain of my soul.

The poem is a claim of ownership over one's own voyage. A logbook is the instrument that makes the claim true: you cannot be the captain of a voyage no one recorded.

## II. The computational logbook

**Same word, same object.** When engineers needed a name for an ordered, append-only, timestamped record of what a machine had done, they took the sailor's word. Operating systems have written *log files* since the 1960s; Unix `syslog` (Eric Allman, 1980s) gave every program a common place to write a dated line. The metaphor was exact: something happened, write it down, in order, don't go back.

**The log as the truth.** Database engineers discovered that the log was not a byproduct of the database — it *was* the database. The write-ahead log (formalised in the ARIES papers, C. Mohan and colleagues, 1992) writes every change to an append-only file *before* touching the tables, so that after a crash the tables can be rebuilt from the log, but the log can never be rebuilt from the tables. Journaling filesystems did the same for disks. Leslie Lamport's *Time, Clocks, and the Ordering of Events* (1978) showed that in a distributed system the only thing that can be agreed on is an order of events — a log. Jay Kreps's essay *The Log* (LinkedIn, 2013), which led to Apache Kafka, says it in one sentence: the log is the source of truth; every table, index, cache and view is a derived, disposable projection of it. This project's first principle — the log is immutable, moments are disposable, notes are sacred — is that sentence applied to a life.

**Making the log unforgeable.** Ralph Merkle (1979) showed how to hash a tree of records so that changing any leaf changes the root. Stuart Haber and W. Scott Stornetta (1991) chained timestamped documents by hashing each one together with the previous — a linked hash chain, built so that no one, not even the keeper, could later alter a page without breaking every page after it. Git (2005) made every commit a hash of its content and its parent, so that a repository's history is verifiable by anyone who holds it. Bitcoin (2008) put the same chain in public. Logbook uses the 1991 version: one person's private chain, verifiable by that person, needing no one else's agreement. The ship's log struck a line through errors and initialled the page; the hash chain is the initial.

**The dream of a machine that remembers for you.** Vannevar Bush described the *memex* in 1945 — a desk that stores everything a person reads and the trails between them. Ted Nelson's Xanadu, Douglas Engelbart's augmentation, and the hypertext that became the web all descend from it. Steve Mann wore a camera and computer through the 1990s, logging his life continuously. Gordon Bell at Microsoft spent the 2000s on MyLifeBits, scanning and recording everything he did, and wrote *Total Recall* (2009) about it. The Quantified Self movement (Gary Wolf and Kevin Kelly, 2007) turned self-tracking into a practice. Every one of these got the *record* right and left the *recount* and the *circle* unbuilt: a life captured and never read back, held by one person or one company, shared with no one. Logbook is the next step on that trail, with the two missing parts.

## III. Fusing the two sciences

The fusion is not a metaphor; the same structure appears on both sides.

| Computer science | Human science | In Logbook |
|---|---|---|
| The log is the source of truth; views are derived and disposable | Autobiographical memory is reconstructive: we do not replay the past, we rebuild it each time from fragments, and the rebuild drifts (Bartlett, 1932; Loftus) | The record is fixed; the recount is a view that can be regenerated, and every sentence links to its evidence so the drift is visible |
| Write-ahead: record before you act on it | The *experiencing self* and the *remembering self* disagree; memory keeps the peak and the end and drops the duration (Kahneman) | Observations are written at the time by instruments; the evening note is the remembering self's line, kept separate and marked as such |
| Idempotent replay; recompute from history when the rules improve | Reminiscence: rereading a diary changes what a memory means without changing what happened | Engines are versioned and re-run over all history; notes are never touched |
| Hash chain: tamper-evident, verifiable by the holder | Narrative identity: a self is the story a person can tell about the connected events of their life (McAdams) | A verifiable chain is a story that cannot be quietly rewritten, by you or anyone |
| Access control, capability tokens | Trust is built in dyads, one relationship at a time, by reciprocal disclosure (Altman & Taylor's social penetration theory) | The circle: a page for a page, named person to named person, no broadcast |
| Garbage collection is forbidden; the log is never pruned | Forgetting is the default: the Ebbinghaus curve (1885) drops most of a day within a week | Never prune. The instrument remembers so that you may forget freely and reread when it matters |
| Derived metrics: counters, dashboards | Gratitude and expressive writing measurably improve wellbeing (Pennebaker, 1986; Emmons & McCullough, 2003) — and extrinsic rewards crowd out intrinsic motivation (Deci) | Reveal, never reward: the logbook may show you a first or a milestone; it never scores you |

The rule of thumb for any new feature: find its twin on the other side of the table. If a computing idea has no human counterpart, it is plumbing and should be invisible. If a human idea has no computing counterpart, it is a note — and notes are sacred.

## IV. The statement against the attention economy

Herbert Simon said it in 1971: a wealth of information creates a poverty of attention. The industry that followed — Tim Wu called its practitioners *the attention merchants* — learned to harvest that scarce attention and sell it. Aza Raskin designed infinite scroll in 2006 and has spent years apologising for it. Shoshana Zuboff named the model *surveillance capitalism* (2019): your record, held by someone else, used to predict and steer you. Neil Postman had warned in 1985 that we were amusing ourselves to death; Jaron Lanier gave ten arguments for deleting your accounts; Cal Newport wrote the manual for leaving.

Every one of these critics described the disease. Fewer built the alternative, and the alternative cannot be "less feed"; it has to be a different object. A feed is other people's present, ranked by a machine to keep you looking, held by a company, measured in your attention. A logbook is your own past, in order, held by you, measured in nothing. The feed asks *what is happening?* and never lets you finish answering. The logbook asks *what happened?* and lets you close the book.

The design decisions follow directly:

- **No feed.** There is no page that shows other people's lives. There is a page that shows one day of yours.
- **No audience.** Sharing is a page handed to a named person who hands one back. There is no post, no follower, no public.
- **No counts.** Nothing is liked, viewed, or ranked. Nothing near a person has a number.
- **No engagement loop.** One evening question; ignore it forever and nothing happens.
- **No harvest.** The files are on your disk. There is no server to sell to, no model trained on you without your key.
- **Reveal, never reward.** The logbook can tell you it was your hundredth flight hour or your first time in Portugal. It cannot give you a badge for it.

Social media promised connection and delivered an audience. A logbook makes the old promise honestly: you, your voyage, the few people you choose to show it to — and a book that will still open in fifty years, because it is only paper made of files.

*You are the captain of your ship. This is the log.*

— bighydro, captain of this one
