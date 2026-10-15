# Logbook

> The machines knew. I didn't.
>
> — [Letter 0](docs/letters/2026-10-12-why-i-built-it.md)

**The record.** Your phone, your photos, your calendar and your messages already keep your days. Logbook gathers them once, into one folder you hold. Nothing in it is ever rewritten.

**How you live with it.** In the evening you open the day in a browser, on your laptop or on your phone. It shows where you slept, where you went and who was there. You write a few sentences about it. Then you sign it, to say you have read it.

**What never happens.** No feed, no followers, no account. No model writes your day. A model's draft is marked as a draft. Nothing leaves without a name. Every way out is an entry in one file you write, naming who receives and how much.

![The Day of 17 June for Ines Nordmann, who does not exist: a week aboard](docs/serve.png)

[Why I built it](docs/letters/2026-10-12-why-i-built-it.md) · [The manifesto](MANIFESTO.md) · [First questions](docs/faq.md)

## Try it

A month of a person who does not exist, on your own machine:

```bash
brew install bighydro/logbook/logbook       # Mac. Elsewhere: pipx install openlogbook
logbook demo --out ~/Demo/Logbook
LOGBOOK_HOME=~/Demo/Logbook logbook serve
```

Then open http://127.0.0.1:8765/day/2026-06-17. Never opened a terminal? [The install, step by step](docs/install.md).

Your own record starts with `logbook setup`, one question at a time: [the first hour](docs/first-hour.md).

## Record it. Recount it. Hand a page.

- **Record it.** The exports and apps you already have, written once as lines in files you hold: photos, messages, mail, calendars, places, health, money, flights, boats.
- **Recount it.** Days, journeys, people and years, computed from those lines each time you look.
- **Hand a page.** A signed day for one person you name. They can hand theirs back.

The rules are ten, and short: [RULES.md](RULES.md).

## For builders

The format is one page, [SPEC.md](SPEC.md), in the public domain. A second program, [logbook-ts](https://github.com/bighydro/logbook-ts), was written from it alone, in another language. Version 1.0 waits until both agree on every record. Start with [CONTRIBUTING.md](CONTRIBUTING.md) or [the docs](docs/index.md).

Alpha. The code is Apache-2.0; the specification is CC0.
