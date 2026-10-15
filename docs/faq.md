# Questions

Six questions people asked the first time they saw it. Each answer ends with the files that back it: a page of the docs, a decision record, or a test that fails when the answer stops being true. Where the program does less than you might expect, the answer says so.

A path in `code` is a file in the repository; a test is named `file::test`.

## Is my data sent anywhere?

Not when you read it.

Reading a day, a page of the Library or anything a command prints opens no connection. A test holds the code to that. It replaces every way out of the program with one that refuses and records the attempt, then runs every reader and every page against a demo record. One attempt fails it. It runs on every pull request, on Linux, macOS and Windows. The test guards the code. It does not run inside the program on your machine.

Something crosses only on a command that says so. `sync` reaches the sources you name. `--fetch-model` downloads a model this machine does not have. `dream` sends a day to the model your policy names. `serve mcp` hands lines to an agent on this machine, up to the tier you allow. Where the agent sends them, the program cannot see.

A page you hand someone leaves when you type the command, to the person you name, and your record keeps a line that says it left.

**Where this is written.** [Security](SECURITY.md), *Nothing leaves* · [RULES.md](https://github.com/bighydro/logbook/blob/main/RULES.md), rule 4 · `tests/test_no_network.py` and the `no_network` fixture in `tests/conftest.py` · `.github/workflows/ci.yml` · [The dream](dream.md#the-policy-entry) · [The MCP server](mcp.md) · `tests/test_share.py::test_a_share_is_recorded_as_a_crossing_line`

## Which model reads my days?

None, until you write an entry that names one.

The Day is computed from your lines each time you open it. No model writes it, and the page says so at its foot.

One command hands a day to a model: `dream`. Without a `dream` entry in `policy/crossing.json` it refuses, and nothing is read or sent. After the entry's last day it refuses again. With the schedule installed, it runs every morning by itself.

The entry sets the highest tier the model sees. At 1 it sees where you were and your calendar, and no note and no message. At 2 it sees your notes and messages too. Money and health reach it only at 3. If the entry names a model, every other model is refused.

What comes back is a draft. It sits above your day, marked as a draft, each sentence pointing at the lines it rests on. If more than three sentences in ten rest on nothing, the program refuses the whole answer and writes nothing. Nothing else in the program builds on a draft.

**What the code does not check.** It does not check where the model runs. An entry at tier 3 sends money and health to whatever address you give it, on your machine or on someone else's. Keeping tier 3 at home is your policy. The program does not enforce it.

### A model on your own machine

Some commands run a model on this machine: they transcribe recordings, describe photos, judge promises, tell voices apart and hear a spoken reflection. While they run, the program tells the model's libraries not to fetch anything. The library that tells voices apart reports usage by default, and the program switches that off. A model the machine does not have stops the command until you fetch it, once, with `--fetch-model`.

That is an instruction to the libraries, not a wall. The tests prove that the program's own code opens no connection. They run with a stand-in for the model, so they say nothing about the model itself, and the model files are outside the threat model. Which model you run, and who made it, is your choice. The program does not vouch for it.

`dream` can also send a day to a model server on this machine, at an address such as `http://127.0.0.1:8080`, with no key. That server is a separate program, which you run. The same holds for it.

**Where this is written.** [The Day](day.md) · [In a browser](serve.md#reflect-and-sign), the footer · [The dream](dream.md): *What the dream is, and is not*, *The policy entry*, *The evidence rule*, *The endpoint* · `tests/test_dream.py::test_no_dream_entry_refuses_and_sends_nothing`, `::test_an_expired_entry_refuses`, `::test_under_max_tier_1_no_message_and_no_note_reaches_the_prompt`, `::test_a_tier_3_line_never_reaches_the_prompt_under_max_tier_2`, `::test_the_policy_model_wins_and_a_different_variable_is_refused`, `::test_too_many_unsupported_segments_refuse_and_write_nothing` · `logbook/contrib/model_client.py`, `from_env` · [The schedule](schedule.md) · [Security](SECURITY.md), *Nothing leaves* and *Out of scope* · `tests/test_transcribe.py::test_no_socket_is_opened_during_transcription`, `tests/test_describe.py::test_no_socket_is_opened_while_describing`, `tests/test_promise_judge.py::test_no_socket_is_opened_while_judging` · [Speakers](speakers.md)

## Why open source, and why a pen name?

Because a log you cannot take with you is not yours.

The code is Apache-2.0. The specification is public domain, CC0, so anyone may write a program that reads a logbook without asking. One already exists: logbook-ts, written in TypeScript from the specification alone. On every pull request one program writes a line and the other verifies it. Version 1.0 is frozen only when both agree.

I write as bighydro so the format can be bigger than its author. Nothing personal enters the repository. A check on every commit keeps it out.

**Where this is written.** [Letter 0](letters/2026-10-12-why-i-built-it.md) · `LICENSE` · [SPEC.md](SPEC.md) · [conformance](https://github.com/bighydro/logbook/blob/main/conformance/README.md) and `.github/workflows/ci.yml` · [RULES.md](https://github.com/bighydro/logbook/blob/main/RULES.md), rule 8 · [ADR 0010](adr/0010-identity-of-the-captain.md) · [Security](SECURITY.md), *Housekeeping*

## Can someone else read my record?

Only what you hand them, up to the tier you allow.

You hand someone a page: one day, signed with your key, for one person you name. `policy/crossing.json` holds the highest tier each person may receive. A page carries tier 1, where you were, unless you ask for more. Ask for more than the file allows and nothing is written. Someone the file does not name receives nothing. Every page you hand over is a line in your record. The person keeps it beside their own record, never inside it.

There are three limits. Someone who takes the folder can read tier 1. Once sealing is on, tiers 2 and 3 open only with your key, so they learn where you were and when a message came, and none of the words. The Library shows every tier, so whoever can reach your machine's pages reads all of it. Keep them to your own devices. An agent you connect sees tier 1 unless you raise its ceiling.

**Where this is written.** [The tour](tour.md#handing-a-day-to-a-friend) · [The commands](commands.md) · [ADR 0016](adr/0016-tier-crossing-policy.md) · `tests/test_share.py::test_share_writes_a_signed_bundle_of_the_day`, `::test_the_tier_gate_is_the_policy_s_per_destination`, `::test_a_share_is_recorded_as_a_crossing_line`, `::test_receive_verifies_and_stores_the_page_outside_the_chain` · [Security](SECURITY.md), *Confidentiality at rest* and *The circle* · [SPEC §4](SPEC.md#4-tiers) · [In a browser](serve.md#reaching-it-from-another-device) · [The MCP server](mcp.md)

## What if I stop using it?

Your record stays readable without the program.

It is a folder of plain text: JSON lines, one file a month, and Markdown. Any editor opens it, today or in twenty years. The index the program builds is a cache, kept outside the folder. Delete it and it is rebuilt from the files. A sealed line is an age file, and age has programs in Go, Rust, Python and TypeScript. Your key opens it, and the key is never in the folder. The format is one page, SPEC.md, which anyone may implement without asking.

You can leave at any time, with everything.

**Where this is written.** [SPEC §1](SPEC.md#1-the-folder), and §2, *Sealed lines* · [The tour](tour.md#what-is-in-the-folder) · [ADR 0001](adr/0001-files-are-the-truth.md) · [RFC 0029](rfcs/0029-encryption-at-rest.md) §3 · [Security](SECURITY.md), *Confidentiality at rest* and *The keys* · [The manifesto](https://github.com/bighydro/logbook/blob/main/MANIFESTO.md)

## Is this an app?

Not yet. There is no app to download. The record on a phone is on the roadmap, in the passage called *Everyone*.

What exists is the Library, `logbook serve`: pages your own machine serves to your browser. It answers that machine and no other. A phone reaches it through a tunnel or a private network you set up yourself. `/today` opens today's page, the one to keep on a phone.

At the foot of each day you write a few sentences about it, or say them where your machine can hear. The page proposes the promises it finds in your words, and you tick the ones you made. Then you sign. The evening needs no terminal.

**Where this is written.** [ROADMAP.md](ROADMAP.md), *4 · Everyone* · [In a browser](serve.md): *Three rules*, *Reaching it from another device*, *Reflect and Sign* · `tests/test_serve.py::test_refuses_to_bind_anything_but_loopback` · `tests/test_serve.py::test_today_is_the_current_day_in_the_records_timezone` · [The signed day](signed-day.md)
