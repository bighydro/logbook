# Promises

`logbook promises [--since YYYY-MM-DD] [--mine | --theirs] [--source KIND] [--open] [--all] [--judge]
[--json]` reads the record's own words for two things: what you said you would do, and what other
people asked you to do. "I'll send you the photos by Friday", "ich melde mich bis Montag", "mach
ich" in a mail or a message you sent, in your turn of a meeting, in a note; "can you send me the
berth number", "kannst du mir die Liste schicken", "let me know by Thursday" in a mail or a message
you received, in someone else's turn. It looks in every `mail/v1` line (RFC 0015), every
`message/v1` line (RFC 0008: iMessage, WhatsApp, whatever the adapters import), every
`transcript/v1` line (RFC 0004) whose text is in the attachment store and every `note/v1` line
(RFC 0010). The **rules** find every sentence that carries a cue, by regular expressions alone, and
the direction comes from who wrote the line, never from the words. That is the whole reader by
default: no model runs, nothing leaves the machine. The **judge**, a local instruct model, is an
opt-in second reading of your own commitments (`--judge`), as before. What the command prints are
**proposals**, never facts. A sentence that reads like a promise is one until you say so; the
command's job is to make sure you see it.

```bash
logbook promises                        # I promised / I was asked, by rules, oldest first
logbook promises --mine                 # only what you promised
logbook promises --theirs               # only what you were asked
logbook promises --source mail          # only the mail; `message`, `transcript`, `note`; comma-separate or repeat
logbook promises --since 2026-06-08     # from that local day on
logbook promises --open                 # without the ones you have marked done
logbook promises --all                  # every candidate: others' commitments, unresolved speakers, what the judge set aside
logbook promises --json                 # the report as one JSON object, every proposal with its line id
logbook promises done 7c1d2e3f4a5b6c7d  # it was kept: one task/v1 line, status done; --open hides it
logbook promises done 7c1d… --note "photos came Thursday"
logbook day sign 2026-06-11 --confirm 019e…   # the line a row names: the day's signature confirms it (RFC 0034)
logbook promises --judge                # read your commitments with a local model first, then list
```

## The two sections

```
3 promises proposed: 2 you made, 1 asked of you; read by rules, not facts; confirm one with `logbook promises done <id>` or `logbook day sign DAY --confirm <line>`
I promised
  2026-06-08  09:10  to Ola Nordmann   “I'll send the mooring photos by Friday.”  due 2026-06-12? (by Friday)  3b9e5d0f2a71c846  line 019e…-…
  2026-06-11  14:00  to Ola Nordmann   “I will book the crane for next week.”  due 2026-06-15? (next week)  a1f0…  line 019e…-…
I was asked
  2026-06-10  09:20  by Kari Nordmann  “Kannst du mir die Flugnummer schicken?”  08c4…  line 019e…-…
```

<<<<<<< HEAD
- **The day and time** are the line's: a transcript's start, a note's writing time, in the record's
  zone. A transcript's turns carry no time of their own here, so every promise in a meeting is on
  the meeting's hour.
- **Who** is the speaker when the transcript resolves one. The source's label for the turn
  (`Ola Nordmann:` in Markdown, `<v Ola Nordmann>` in WebVTT, Granola's `speaker.name`) is matched
  to the line's `participants`, and their email, phone or provider id to a person through the
  record's resolution lines (RFC 0006), the same way the with module places a transcript's
  participants at a stay. A bare name the record labels one person by resolves too. `me` and your
  own names are `you`; so is a note, since a note is yours. A diarizer's `Speaker A`, or a name
  nobody has resolved, stays as spoken, with no person behind it. Text that carries its own labels
  belongs to them: a line of a note or of a turn that begins `Speaker 2:` (or with the name of a
  participant, of a person the record resolves, or of you) is that speaker's, whatever label the
  source put on the turn and whoever's note it is in; you are `you` only when the label resolves to
  one of your identities. A word before a colon that names nobody (`Plan:`) is text.
- **The sentence** is quoted as written, whitespace collapsed, never paraphrased.
- **The due hint** is there when the sentence carries a date phrase, with a `?` because it is a
  reading of the words, not a deadline anyone agreed. It is resolved against the day the sentence
  was said: a weekday is the next one strictly after that day (`by Friday` on a Thursday is
  tomorrow; on a Friday it is next week's); `next week` is its Monday; `this week` and `by the end of
  the week` the Friday on or after the day; `tomorrow`, `morgen`, `übermorgen`, `tonight`, `heute
  Abend`, `in two weeks`, `in drei Tagen`, `next month`; a month and a day (`by June 20`, `20 June`,
  `bis 20. Juni`, `bis zum 20.6.`) the next such date; `the 5th` and `am 5.` the next fifth.
- **The id** is a digest of the origin line's id and the quoted sentence, case and whitespace
  aside: sixteen hex characters. The same sentence in the same line has the same id however often
  the command runs, and whichever extractor found it (below).
- **`done`** after the due hint marks a proposal you closed; `--open` leaves those out.
- **`kept`, `missed on 2026-06-14`, `dropped`, `carried`** is what the signed day of the line the
  promise was read in says became of it ([the signed day](signed-day.md), RFC 0034 amendment 1):
  kept and dropped close the promise, missed closes and flags it, carried leaves it open; `--open`
  leaves the first three out.

Under `--json` the report is one object: `since`, `open_only`, `judged_only` (false under
`--all`), `threshold` (0.6), `extractor` (`name`, `version`, and `languages` for the rules), `judge`
(what a `--judge` run just did: `engine`, `model`, `candidates`, `judged`, `unparsed`; null when
none ran), `unjudged` (how many candidates have no verdict yet), `proposals` and `skipped`. Each
proposal carries `id`, `status` (`open` or `done`), `closed_by` (the task line's id), `disposition`
(`value`, `day` and `line`, the signed-day line's, when the standing signature of its day disposed
of the line it was read in; null otherwise), `day`, `at`,
`line` (the origin), `seq`, `kind` (`transcript` or `note`), `source`, `title`, `speaker` (`label`,
`spoken`, `person`, `owner`, or null), `direction` (`owed_by_owner` when you said it,
`owed_to_owner` when a resolved person did, null when nobody is behind the label), `certainty`
(always `inferred`: the words were read into a promise, never stated as one), `language`, `cue` (the
words that made it a promise, as written), `class`, `quote`, `due` (`phrase` and `date`, or null)
and `judgement` (below, or null). The fields are this reader's own; `commitment/v1` (RFC 0007), which
they once mirrored, was withdrawn by RFC 0031.
=======
**I promised** is every commitment cue in a line you wrote: a mail whose sender is one of your
addresses, a message with `from_me`, your turn of a transcript, a note. **I was asked** is every
request cue in a line you received: a mail from someone else, a message not from you, another's
turn. A request cue in your own words ("can you send me the invoice?" in a mail you sent) is you
asking, and is not proposed; a commitment cue in someone else's words ("I'll send you the photos"
from Ola) is theirs, and `--all` lists it in a third section with the candidates nobody resolves
and the ones the judge set aside. The order inside a section is the day's.

Each row is:

- **The day and time** of the line: a mail's `Date`, a message's own stamp, a transcript's start,
  a note's writing time, in the record's zone. A transcript's turns carry no time of their own, so
  every promise in a meeting is on the meeting's hour.
- **The counterpart**, `to` whom you promised or `by` whom you were asked: the person the record
  resolves (RFC 0006) behind the address, the number or the name, else the name the source wrote,
  else the address or number itself. In a mail you sent it is the first recipient who is not you;
  in a message you sent in a direct chat it is the one person the chat's id names (a WhatsApp JID
  is a phone number, iMessage names a chat by the address) or the chat's name; in a group chat the
  group's name; in your turn of a transcript the other participant; a note has none and says
  `(note)`.
- **The sentence** as written, whitespace collapsed, never paraphrased.
- **The due hint** when the sentence carries a date phrase, with a `?` because it is a reading of
  the words, not a deadline anyone agreed. It is resolved against the day the sentence was said: a
  weekday is the next one strictly after that day (`by Friday` on a Thursday is tomorrow; on a
  Friday it is next week's); `next week` is its Monday; `this week` and `by the end of the week`
  the Friday on or after the day; `tomorrow`, `morgen`, `übermorgen`, `tonight`, `heute Abend`,
  `in two weeks`, `in drei Tagen`, `next month`; a month and a day (`by June 20`, `20 June`, `bis
  20. Juni`, `bis zum 20.6.`) the next such date; `the 5th` and `am 5.` the next fifth.
- **The judgement**, when the judge has read it (below).
- **`done`** when you closed it; `--open` leaves those out.
- **The proposal's id**: a digest of the origin line's id and the quoted sentence, case and
  whitespace aside, sixteen hex characters. The same sentence in the same line has the same id
  however often the command runs, and whichever extractor found it. `promises done` takes it.
- **The line** it was read in, by its id. `logbook day sign DAY --confirm <id>` takes it (RFC
  0034, [signed-day](signed-day.md)): a signed day confirms the lines you name, so the mail or the
  message that carries the promise can be among the day's confirmed facts while the promise itself
  stays a proposal.

## Who wrote it

Direction is never read from the words. A mail is yours when its `from` is one of your addresses:
`owner_emails` in `logbook.json`, the `emails` of `policy/owner.json`, or any address a resolution
line gives your `owner_id`; when none of those match but the import marked it `sent` (it knew the
mailbox), that counts too. A message is yours when the adapter stored `from_me`. A transcript's turn
is yours when its speaker resolves to you: the source's label (`Ola Nordmann:` in Markdown, `<v
Ola Nordmann>` in WebVTT, Granola's `speaker.name`) matched to the line's `participants` and their
email, phone or provider id to a person, `me` and your own names from `policy/owner.json` as you.
A note is yours, except for text that carries its own labels (`Speaker 2:`, or a name the record
knows), which belongs to that speaker. A request from a diarizer's `Speaker A`, who is not you, is
counted as asked of you; a commitment from one is nobody's and shows under `--all`.

A mail body is read up to the first reply header (`On … wrote:`, `Am … schrieb …:`, `-----Original
Message-----`, `From:`) or signature delimiter (`-- `), and lines that begin with `>` are left out,
so a reply that quotes your promise never proposes it again. A message is read whole; a transcript
is read by its media type as before (WebVTT and SRT cues, Granola's JSON segments, `Speaker: text`
prose). A transcript whose text is not in the store, and a mail or a message with no text, is
counted and skipped, never a traceback. A retracted line, and one a later line `supersedes`, is
not read.

## The cues

A sentence is proposed when it carries one of these. Only the first cue in a sentence counts, and
it decides the class. A commitment cue is ignored when it is negated right after (`I will not`,
`I'll never`, `ich werde nicht`, `mach ich nicht`) or the sentence ends in a question mark; a
request cue is read in a question or not, since most requests are questions.

| Class | English | German |
|---|---|---|
| `future` | `I'll`, `I will`, `I shall`, `I'm going to`, `we'll`, `we will`, `we're going to`, `I promise`; at the head of a sentence or after `ok`, `sure`, `yes`: `will do`, `on it`, `consider it done`, `leave it with me`, `count on me` | `ich werde`, `ich schicke`, `ich sende`, `ich melde mich`, `ich kümmere mich`, `ich rufe`, `ich bringe`, `ich liefere`, `ich erledige`, `ich besorge`, `ich übernehme`, `ich buche`, `ich bestelle`, `ich bezahle`, `ich prüfe`, `ich organisiere`, `ich hole`, `ich mache`, `ich verspreche`, `ich sage Bescheid`, the same with `wir`, and the verb first: `mach ich`, `schick ich dir`, `melde ich mich`, `erledige ich`, `kümmere ich mich`; `versprochen`, `wird gemacht`, `wird erledigt`, `geht klar` |
| `obligation` | `I need to`, `I have to`, `I must`, `I've got to`, `I ought to`, and with `we` | `ich muss`, `wir müssen` |
| `offer` | `let me` (not `let me know`), `I can send`, `I can bring`, `I can check`, `I can call`, `I can book`, `I can pay`, `I can fix`, `I can sort`, `I can look`, `I can do that` | |
| `deadline` | a sentence of at most eight words that is a date phrase beginning `by`, `before`, `until`: `By Friday.`, `Photos by Friday.` | the same with `bis`, `spätestens`: `Bis Freitag, versprochen.` |
| `request` | `can you`, `could you`, `would you`, `will you` (not `can you believe`, `imagine`, `will you be`, `would you like`), `would you mind`, `any chance you could`, `are you able to`; `please` with a verb of doing (`please send`, `please confirm`, `please let me know`, `please have a look`); at the head of a sentence: `send me`, `bring me`, `call me`, `forward me`, `remind me`, `tell me`, `show me`, `give me`, `get back to me`; `let me know`, `don't forget to`, `make sure you`, `remember to`, `I need you to`, `I'd appreciate it if you`, `it would be great if you`, `can I have`, `could we get`, `you need to`, `you have to`, `you must` | `kannst du`, `könntest du`, `würdest du`, `können Sie`, `könnten Sie`, `würden Sie`, `magst du` (not `kannst du dir vorstellen`, `glauben`, `erinnern`), `wärst du so nett`, `bist du so lieb`; `bitte` with a verb (`bitte schick`, `bitte bestätige`, `bitte überweise`); at the head of a sentence: `schick mir`, `bring mir`, `ruf mich`, `zeig mir`, `schreib mir`, `hol mir`, `leih mir`; `schicken Sie mir`, `rufen Sie mich`; `sag mir Bescheid`, `gib Bescheid`, `melde dich`, `vergiss nicht`, `denk dran`, `ich brauche von dir`, `wir bitten um`, `um Rückmeldung`, `schau mal`, `mach mal`, `du musst`, `Sie müssen` |

Only the first person counts for a commitment: `he will send`, `they'll get back` and `will you`
propose nothing of that class. The rules are plain regular expressions over sentences (cut at a
full stop, `!` or `?` that does not follow a digit, and at every line break); they will miss a
promise phrased another way ("expect the draft tomorrow morning") and propose a sentence that is
none ("bis Freitag dann!" as a farewell), which is why nothing here is a fact until you close it.
The list above is the whole list (`promises._CUES`, `promises._ASKS`); a cue you miss is a pull
request with a sentence in the recall test.

**How well it reads.** `tests/test_promises_wider_net.py` holds a synthetic fortnight of the Oslo
persona (`tests/fixtures/promises/wider-net.json`): 24 planted commitments and 12 planted requests
across mail, iMessage, WhatsApp and one transcript, among 60 distractor lines (others' promises,
your own questions, negations, quoted replies, newsletters, chit-chat). The test asserts recall of
at least 20 of 24 and 10 of 12 and precision of at least 0.8, and prints the numbers; the rules
read 22 of 24, 11 of 12, at precision 0.97. The three misses are the three sentences planted with
no cue on purpose; the one false proposal is the farewell.

## The JSON

Under `--json` the report is one object: `since`, `open_only`, `mine_only`, `theirs_only`,
`sources` (the kinds read, in `mail`, `message`, `transcript`, `note` order), `all`, `threshold`
(0.6), `extractor` (`name`, `version`, and `languages` for the rules), `judge` (what a `--judge`
run just did; null when none ran), `unjudged` (how many commitments have no verdict yet),
`proposals` and `skipped`. Each proposal carries `id`, `status` (`open` or `done`), `closed_by` (the
task line's id), `day`, `at`, `line` (the origin, for `day sign --confirm`), `seq`, `kind` (`mail`,
`message`, `transcript` or `note`), `source` (the adapter), `title` (a transcript's or a note's
title, a mail's subject), `speaker` (`label`, `spoken`, `person`, `owner`, or null), `role`
(`promise` when you made it, `request` when you were asked, `theirs` when a resolved person made
it, null when nobody is behind the label), `counterpart`, `direction` (`owed_by_owner` for a
promise and a request, `owed_to_owner` for theirs, null otherwise), `certainty` (always
`inferred`), `language`, `cue`, `class`, `quote`, `due` (`phrase` and `date`, or null) and
`judgement` (below, or null). The fields are this reader's own; `commitment/v1` (RFC 0007), which
they once mirrored, was withdrawn by RFC 0031. The MCP tool `promises` returns the same proposals
([mcp](mcp.md)).
>>>>>>> 3bc9dd7 (docs: promises reads mail and messages; the two sections, the cues, the recall numbers)

## The judge

`--judge` reads every commitment the rules found that has no verdict yet, oldest first, with a
local instruct model, and prints one progress line per candidate on stderr. A request is never
judged: the judge's question is whether a sentence is a commitment, and a request is not one. The
model sees the candidate sentence marked among the two sentences before and after it in the same
line, across turns, each with who said it as the report names them (`you`, `Ola Nordmann`, `Speaker
A`); the kind of line, its title or subject and the counterpart; the day; your name as the record
resolves it; and the names the record resolves in that line. It answers one JSON object, sampled at
temperature 0, so the same candidate gets the same verdict from the same model:

| Field | What |
|---|---|
| `is_commitment` | whether the sentence is a specific thing a specific person said they will or must do; "we'll see", "I'll have a look", "let me think" and reports of what someone else will do are not |
| `by` | who made it: `owner`, a name from the list, or `unknown` |
| `to` | whom it binds them to: `owner`, a name, or `unknown` |
| `what` | the commitment in one line, in the speaker's own words shortened |
| `due` | `YYYY-MM-DD`, resolved against the day it was said, or null when the words name no day |
| `confidence` | 0 to 1 |

A judged candidate **stays** in its section when the verdict is a commitment at confidence 0.6 or
above (`promises.THRESHOLD`) and is set aside otherwise; `--all` lists what was set aside, with the
verdict. A judged row carries the verdict after the due hint: the confidence, `by <name>` when it
is not the speaker, `to <name>` when known, and `no 0.95` for a judged non-commitment. The due hint
is the verdict's day when it gave one, else the rules' reading with its phrase. The quote stays the
sentence as written, since the id is a digest of it.

```
judged 10 candidates with mlx-lm (mlx-community/Qwen2.5-7B-Instruct-4bit)
2 promises proposed: 2 you made, 0 asked of you; read by rules, not facts; 10 judged (a commitment at confidence 0.6 or above stays); confirm one with `logbook promises done <id>` or `logbook day sign DAY --confirm <line>`
I promised
  2026-06-08  09:10  to Ola Nordmann  “I'll send the mooring photos by Friday.”  due 2026-06-12?  0.92 to Ola Nordmann  3b9e5d0f2a71c846  line 019e…-…
  2026-06-11  14:00  to Ola Nordmann  “I will book the crane for next week.”  due 2026-06-15? (next week)  0.8 to Ola Nordmann  a1f0…  line 019e…-…
I was asked
  none
```

**The verdicts are kept in the record**, outside the chain, in `policy/promises-cache.json`:
`{"version": 1, "judgements": {"<candidate id>": {"is_commitment", "by", "to", "what", "due",
"confidence", "engine", "model", "judged_at"}}}`, the ids sorted. A candidate is judged once,
however often the command runs and whatever `--model` is set later; the model that read it is in
its entry. The file is rewritten after every verdict, so an interrupted run keeps what it did and
the next carries on; `--limit N` judges at most N candidates in one run. An answer with no whole
verdict in it is counted, not kept, and the next `--judge` tries that candidate again. Delete an
entry, or the file, to have a candidate judged afresh.

**The engine** is `mlx-lm`, Apple's MLX runner for language models, with
`mlx-community/Qwen2.5-7B-Instruct-4bit` by default (`judge.DEFAULT_MODEL`); `--model` names any
instruct model the hub serves in MLX format. It needs the extra: `uv pip install
'openlogbook[judge]'`, Apple silicon only; without it `--judge` stops with the message that says
so, and everything else works. It is imported only when `--judge` runs, and while it runs the hub
is told it is offline (`HF_HUB_OFFLINE`), so no socket is opened for any reason. A model not yet on
the machine stops the command naming the one flag that fetches it, `--fetch-model`, which
downloads the model before the first candidate and nothing else, ever. There is no cloud model and
there will not be one: a record's words are read on the record's machine.

The judge is a second reading of the rules' candidates, never a third extractor: it changes neither
a proposal, nor its id, nor what `done` writes, and it writes nothing to the chain.

## Closing one: `promises done <id>`

`done` appends one `task/v1` line (RFC 0016) and nothing else: `source` `manual`, `kind` `task`,
tier 2, `at` now. Its payload is the sentence as `title`, `status` `done`, the due hint as `due`
when there was one, `completed_at`, `list` `promises`, your `--note` as `notes`, and under `extra`
the proposal's `promise` id, its `origin` line, the `speaker` and the `extractor` that proposed it,
so a reader can trace the close back to the words. `raw_id` is `promise:<id>@<time>`, the snapshot
form the profile asks for. Nothing is edited: the mail, the message, the transcript and the note
stay as they were, and the close is a line beside them. A request closes the same way: you were
asked, you did it, one task line says so.

`--open` hides a proposal whose latest standing task line (by `extra.promise`) has status `done`
or `cancelled`, and one whose day's standing signature kept, missed or dropped the line it was read
in (a carried one is still open, and `done` closes it as any other). `done` on a proposal already
closed, by a task line or by the signed day, writes nothing and says so; an id the record
does not propose is refused with status 2. A proposal is yours to close only: the command never
closes one on its own, and nothing it reads can close another.

Why `task/v1`? `commitment/v1` and `commitment-close/v1` (RFC 0007) were the lines a confirmed
promise and its keeping would have become. Nothing ever wrote or read them, and RFC 0031 withdrew
them. The one act the owner takes is "that was done", and RFC 0016's task is the line that says
exactly that with a title and a status.

## Replacing the rules with a model

The command does not know the rules. `promises.extract(lb, since, extractor=RULES, sources=...)`
takes any object with a `name`, a `version` and `__call__(text) -> list[Match]`, where a `Match` is
the quoted sentence, the cue, the class (`future`, `obligation`, `offer`, `deadline` or `request`),
the language, the date phrase and, when the extractor resolved it itself, the due day. The
extractor sees text and returns sentences; the command owns the record, who wrote each line, the
counterparts, the days and the closes, and never lets an extractor write. A local model that reads
a text and returns the same shape slots in with no change to the report, the ids (a digest of line
and sentence, so a model quoting the same sentence agrees with the rules) or `done`, whose task
lines record which extractor proposed what.

## What it does not do

It does not read the free-text notes files (`notes/<YYYY>/<date>.md`) or calendar entries. It does
not know whether a promise was kept: that is `logbook promises tasks --propose-done`'s question
([tasks](tasks.md)), asked of the mail, the calendar and the transactions. The counterpart is whom
the line was with, not whom a promise binds in a group: a promise in a group chat is `to` the
group, and a request in one may have been to everyone. It does not write commitments, retract
anything, or run a model you did not ask for.
