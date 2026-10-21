# Questions

Six questions people asked the first time they saw it. Each answer ends with the files that back it: a page of the docs, a decision record, or a test that fails when the answer stops being true. Where the program does less than you might expect, the answer says so.

A path in `code` is a file in the repository; a test is named `file::test`.

## Is my data sent anywhere?

Not when you read it.

Reading a day, a page of the Library or anything a command prints opens no connection. A test holds the code to that. It replaces every way out of the program with one that refuses and records the attempt, then runs every reader and every page against a demo record. One attempt fails it. It runs on every pull request, on Linux, macOS and Windows. The test guards the code. It does not run inside the program on your machine.

Something crosses only on a command that says so. `sync` reaches the sources you name. `--fetch-model` downloads a model this machine does not have. `dream` and `transcript synthesize` send a day or a call, and `people ask` what passed between you and one person, to the model your policy names. `serve mcp` hands lines to an agent on this machine, up to the tier you allow. Where the agent sends them, the program cannot see. If you set them up, two short messages a day say the page is ready and ask the evening question. They carry the date, a count, the question and, if you set one, a link to the page. Nothing else.

A page you hand someone leaves when you type the command, to the person you name, and your record keeps a line that says it left.

**Where this is written.** [Security](SECURITY.md), *Nothing leaves* and *The daily messages* · [RULES.md](https://github.com/bighydro/logbook/blob/main/RULES.md), rule 4 · `tests/test_no_network.py` and the `no_network` fixture in `tests/conftest.py` · `.github/workflows/ci.yml` · [The dream](dream.md#the-policy-entry) · [The synthesis of a call](transcript-synthesis.md) · [The MCP server](mcp.md) · `tests/test_share.py::test_a_share_is_recorded_as_a_crossing_line` · [The relationship reader](relationship.md): *The entry*, *The model* · [The digest](digest.md#delivery), *Delivery* · [The schedule](schedule.md#the-daily-loop-the-morning-and-the-evening-message), *The daily loop* · `logbook/contrib/notify.py`, `ready_text` and `question_text` · `tests/test_notify_daily.py::test_after_the_close_one_message_the_date_the_count_and_the_link`, `::test_a_question_filled_from_the_day_is_not_sent`

## Which model reads my days?

None you did not ask for.

The Day is computed from your lines each time you open it. No model writes it, and the page says so at its foot.

Four commands send your lines to a model server, each through its own entry in `policy/crossing.json`. `dream` drafts a day, a journey or a week, and `transcript synthesize` a recorded call, both through the `dream` entry. `people ask` and `dream person` read what passed between you and one person, through the `relationship` entry. Without its entry a command refuses, and nothing leaves the machine. After the entry's last day it refuses again. With the schedule installed, the 06:00 close dreams the days that ended and the week's calls.

The entry sets the highest tier the model sees. At 1 it sees where you were and your calendar, and no note and no message. At 2 it sees your notes and messages too. Your health and your recorded calls reach it only at 3. If the entry names a model, every other model is refused.

What comes back is a draft. It sits above your day, marked as a draft. Each passage points at the lines it rests on, or is marked as resting on nothing. If more than three passages in ten rest on nothing, the program refuses the whole answer and writes nothing. Nothing else in the program builds on a draft.

**What the code does not check.** It does not check where the dream's model runs. An entry at tier 3 sends your health and your calls to whatever address you give it, on your machine or on someone else's. Keeping tier 3 at home is your policy. The program does not enforce it. The people reader is stricter for now: its model is a cloud one, so its entry may not go above tier 2.

### A model on your own machine

Some commands run a model on this machine: they transcribe recordings, describe photos, judge promises, tell voices apart and hear a spoken reflection. They need no entry, since the model runs here. While they run, the program tells the model's libraries not to fetch anything. The library that tells voices apart reports usage by default, and the program switches that off. A model the machine does not have is never fetched by itself. Only `--fetch-model` downloads one.

That is an instruction to the libraries, not a wall. The tests prove that the program's own code opens no connection. They run with a stand-in for the model, so they say nothing about the model itself, and the model files are outside the threat model. The program does not vouch for the models, or for who made them.

`dream` can also send a day to a model server on this machine, at an address such as `http://127.0.0.1:8080`, with no key. That server is a separate program, which you run. The same holds for it.

**Where this is written.** [The Day](day.md) · [In a browser](serve.md#reflect-and-sign), the footer · [The dream](dream.md): *What the dream is, and is not*, *The policy entry*, *The evidence rule*, *The endpoint* · `tests/test_dream.py::test_no_dream_entry_refuses_and_sends_nothing`, `::test_an_expired_entry_refuses`, `::test_under_max_tier_1_no_message_and_no_note_reaches_the_prompt`, `::test_a_tier_3_line_never_reaches_the_prompt_under_max_tier_2`, `::test_the_policy_model_wins_and_a_different_variable_is_refused`, `::test_too_many_unsupported_segments_refuse_and_write_nothing` · `logbook/contrib/model_client.py`, `from_env` · [The synthesis of a call](transcript-synthesis.md) · [The schedule](schedule.md#the-four-runs-and-the-0600-close) · [The relationship reader](relationship.md): *The entry*, *`dream person`* · `logbook/contrib/relationship/reader.py`, `CLOUD_CEILING` · `tests/test_dream_person.py::test_dream_person_is_refused_without_the_entry_and_sends_nothing` · `tests/test_draft_follows_its_entry.py::test_a_person_draft_is_held_to_the_relationship_ceiling_not_the_dreams` · [Security](SECURITY.md), *Nothing leaves* and *Out of scope* · `tests/test_transcribe.py::test_no_socket_is_opened_during_transcription`, `tests/test_describe.py::test_no_socket_is_opened_while_describing`, `tests/test_promise_judge.py::test_no_socket_is_opened_while_judging` · [Speakers](speakers.md)

## Why open source, and why a pen name?

Because a log you cannot take with you is not yours.

The code is Apache-2.0. The specification is public domain, CC0, so anyone may write a program that reads a logbook without asking. One already exists: logbook-ts, written in TypeScript from the specification. On every pull request one program writes a line and the other verifies it. Version 1.0 is frozen only when both agree.

I write as bighydro so the format can be bigger than its author. Nothing personal enters the repository. Before a change merges, a check on my machine reads it for anything of mine.

**Where this is written.** [Letter 0](letters/2026-10-12-why-i-built-it.md) · `LICENSE` · [SPEC.md](SPEC.md) · [conformance](https://github.com/bighydro/logbook/blob/main/conformance/README.md) and `.github/workflows/ci.yml` · [RULES.md](https://github.com/bighydro/logbook/blob/main/RULES.md), rule 8 · [ADR 0010](adr/0010-identity-of-the-captain.md) · [Security](SECURITY.md), *Housekeeping*

## Can someone else read my record?

Only what you hand them, up to the tier you allow.

You hand someone a page: one day, signed with your key, for one person you name. `policy/crossing.json` holds the highest tier each person may receive. A page carries tier 1, where you were, unless you ask for more. Ask for more than the file allows and nothing is written. Someone the file does not name receives nothing. Every page you hand over is a line in your record. The person keeps it with their record, never in its chain.

There are three limits. Someone who takes the folder can read tier 1. Once sealing is on, tiers 2 and 3 open only with your key. Lines written before stay plain until you seal them, with one command. Then whoever takes the folder learns where you were and when a message came, and none of the words. The Library shows every tier, so whoever can reach your machine's pages reads all of it. Keep them to your own devices. An agent you connect sees tier 1 unless you raise its ceiling.

**Where this is written.** [The tour](tour.md#handing-a-day-to-a-friend) · [The commands](commands.md) · [ADR 0016](adr/0016-tier-crossing-policy.md) · `tests/test_share.py::test_share_writes_a_signed_bundle_of_the_day`, `::test_the_tier_gate_is_the_policy_s_per_destination`, `::test_a_share_is_recorded_as_a_crossing_line`, `::test_receive_verifies_and_stores_the_page_outside_the_chain` · [Security](SECURITY.md), *Confidentiality at rest* and *The circle* · [SPEC §4](SPEC.md#4-tiers) · [In a browser](serve.md#reaching-it-from-another-device) · [The MCP server](mcp.md)

## What if I stop using it?

Your record stays readable without the program.

It is a folder of files. Your lines are JSON, one file a month, and any editor opens them, today or in twenty years. The photos and recordings they point at sit beside them, each as its own file. The index the program builds is a cache, kept outside the folder. Delete it and it is rebuilt from the files. A sealed line carries what it says as an age file. age is an open format, with programs in Go, Rust and TypeScript. Your key opens it, and the key is never in the folder. The format is one page, SPEC.md, which anyone may implement without asking.

You can leave at any time, with everything.

**Where this is written.** [SPEC §1](SPEC.md#1-the-folder), and §2, *Sealed lines* · [The tour](tour.md#what-is-in-the-folder) · [ADR 0001](adr/0001-files-are-the-truth.md) · [RFC 0029](rfcs/0029-encryption-at-rest.md) §3 · [Security](SECURITY.md), *Confidentiality at rest* and *The keys* · [The manifesto](https://github.com/bighydro/logbook/blob/main/MANIFESTO.md)

## Is this an app?

Not yet. There is no app to download. The record on a phone is on the roadmap, in the passage called *Everyone*.

What exists is the Library, `logbook serve`: pages your own machine serves to your browser. It answers that machine and no other. A phone reaches it through a tunnel or a private network you set up yourself. `/today` opens today's page, the one to keep on a phone.

At the foot of each day you write a few sentences about it. Once a transcription model is installed, you can say them instead. The page proposes the promises it finds in your words, and you tick the ones you made. Then you sign. On the machine itself, or from a phone through a tunnel, the evening needs no terminal. Through a private network's own proxy, you can read the pages but not sign them.

**Where this is written.** [ROADMAP.md](ROADMAP.md), *4 · Everyone* · [In a browser](serve.md): *Three rules*, *Reaching it from another device*, *Reflect and Sign* · `tests/test_serve.py::test_refuses_to_bind_anything_but_loopback` · `tests/test_serve.py::test_today_is_the_current_day_in_the_records_timezone` · [The signed day](signed-day.md)
