# People's mail

Most of a mailbox is not people: shops, banks, newsletters and the machines that notify. One rule says
which mail is a person's, and the Day page and the crossing read the same rule, so what the page opens
is what crosses. The design is a draft,
[RFC 0045](https://github.com/bighydro/logbook/blob/main/rfcs/0045-peoples-mail.md).

```bash
logbook people mail                                          # the last 30 days, counted
logbook people mail --since 2026-03-01 --until 2026-03-31    # one month
logbook people mail --since 2026-03-01 --json                # each line's class, reason and person ids
```

## The rule

A mail is **a person's mail** when someone the record names as a person is on it:

- a mail you **received**: its sender;
- a mail you **sent**: any of its recipients, `to`, `cc` or `bcc`;

and its sender has not been let go in [Hold](hold.md). "Names as a person" is what `people` means by it
([people](people.md)): the address has a resolution to a person, and that person is not you. Every other
mail is **other mail**, and the reader says why:

| reason | what it means |
|---|---|
| `no_person` | nobody the record names as a person is where the rule looks: a stranger, a company's address, a person only in cc of a mail you received |
| `no_reply` | the sender is a no-reply address (`no-reply@`, `noreply@`, `do-not-reply@`, `mailer-daemon@`, `notifications@` and the like), whatever resolves |
| `agent` | an agent wrote it, or the sender resolves to an agent; no mail source marks one today |
| `let_go` | you let the sender go in Hold; Hold writes no fates yet, so this removes nothing today |
| `sealed` | a sealed mail this machine has no key to open: listed and said, never guessed |

A company is never a person: an address you named as an org's or a company's stays other mail. A
newsletter's list headers and Gmail's tabs are not the rule either: a mail from Per Hansen through the
club's list is still a person's mail. When a mail line carries them (`extra.list`,
`extra.gmail_category`), `--json` shows them as `evidence`, the list as `true` and the tab as its word,
never the headers themselves.

## What it prints

```
mail 2026-03-01 – 2026-03-31: 412 lines
  people's mail: 37 (21 received, 16 sent), from or to 9 people
  other mail: 375 (290 no person on it, 85 a no-reply sender, 0 an agent's)
  let go in Hold: nothing yet; Hold writes no fates
```

Counts only: never an address, never a name, no number beside anyone. `--json` adds each mail line's
id, time, day, direction, class, and the ids of the people that make it a person's (or the reason it is
not), and never an address.

## The crossing

`logbook export crossing` sends people's mail only, whenever mail is among the kinds it crosses, and
counts the rest in the manifest as `mail_held_back`. `--all-mail` sends every mail the tier and the signed
days let through, as before, and the manifest says so ([the crossing](crossing.md#peoples-mail)).

## Replies owed

The Day page's loose ends (RFC 0043) will read *replies owed* from the same rule: for each person the
record names, over the last 90 days, your direct messages with them (never a group's, never an agent's),
your people's mail and your calls; when the last word is theirs (a message, a mail, a call you did not
answer) and is more than a week old, a reply is owed. A call you answered or made is your word. No page
shows them yet.
