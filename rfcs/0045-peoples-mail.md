# RFC 0045 — People's mail: one rule for what the page opens and what crosses

Status: draft · 2026-10-21 · comment period: two weeks · a mechanism RFC: it changes readers and the
crossing's selection, and defines no line · builds on RFC 0006 (resolution), RFC 0015 (mail), RFC 0005
(the crossing package), RFC 0011 (the crossing line) and RFC 0042 (Hold) · the mail filter RFC 0043 §9
and §11 call "its own RFC"

Most of a mailbox is not people. A record that holds three years of mail holds a few hundred mails a
month from the people of the owner's life and several thousand from shops, banks, newsletters and the
machines that notify. The Day page (RFC 0043 §11) opens the first and folds the rest; the crossing
(RFC 0005) has so far sent all of it or none of it. This RFC is the one rule both read, so that what the
page opens is what crosses.

## 1. The rule

A mail line (`mail/v1`) is **a person's mail** when someone the record names as a person is on it:

- for a mail **received** (`direction: "received"`), its sender, `from`;
- for a mail **sent** (`direction: "sent"`), any of its recipients, `to`, `cc` or `bcc`;

and its sender has not been **let go** in Hold (§4). Every other mail line is **other mail**.

A mail that carries no `direction` (RFC 0015 makes it a MUST, but a reader never fails on its absence,
SPEC §5) is read as sent when its `from` is the owner's (below) and as received otherwise.

"Names as a person" is the reader's existing sense (`docs/people.md`, `logbook.core.present`): an address
`{kind: "email", value}` (RFC 0015 rule 2) has a standing `resolution/v1` line (RFC 0006), after the alias
walk, whose entity has `type` `person` or no `type` at all (`present.PERSON_TYPES`), and that entity is
not the owner. The owner is `owner_id`, every address of `owner_emails` and `policy/owner.json`, and every
entity those resolve to (`present.owner_of`). An address is looked up both ways the record's resolutions
spell one, lower-cased and case-folded, as the crossing already does (`crossing._named`).

A cc does not make a received mail a person's: a newsletter that a friend is also on is still the
newsletter's. A sent mail is the owner's word to whoever it went to, and a person among them makes it a
person's.

## 2. What is not a person

Three things look like people on a mail and are not, and the reader tells each the way the record
already does:

1. **A company, or anything that is not a person, by its resolution.** An address resolved to an entity
   of another type (`company`, RFC 0006; `org`, RFC 0037) names nobody here; one resolved to an entity
   of type `agent`, should one ever be written, is an agent's (item 3). The resolution line's
   `entity.type` decides; a reader never guesses a type from the address.
2. **A no-reply address, by a pattern list.** A sender (or recipient) whose address matches the reader's
   no-reply list is never a person, whatever a resolution says of it: `no-reply@`, `noreply@`,
   `do-not-reply@`, `donotreply@`, `mailer-daemon@`, `postmaster@`, `bounce@`, `bounces@`,
   `notification@`, `notifications@`, the `reservations@` and `invite@` addresses and Google Calendar's
   own (`calendar.google.com`) that `present.SYSTEM_ADDRESS` already holds for invitations, and each of
   these followed by `+`, `-` or `.` and more (`noreply+bills@`, `no-reply.billing@`). The list is the
   reader's (`logbook.core.peoples_mail.NO_REPLY_ADDRESS` beside `present.SYSTEM_ADDRESS`), never a
   line, and a change to it is a change to this RFC.
3. **An agent, by the machine mark.** A mail whose `extra.machine` is `true`, or whose
   `extra.counterpart` is `{"kind": "agent", …}`, is an agent's (`logbook.core.machine`, the rule
   `people` and `promises` read messages by). No mail writer on `main` sets either today; the rule is
   here so that the first one that does needs no new reader.

When a received mail is other mail, the reader says why, in this order: `agent` (the mark), `no_reply`
(the sender matched the list), `let_go` (§4), `agent` again (the sender resolves to an entity of type
`agent`), `no_person` (nobody the record names as a person is where the rule looks). A sent mail that is
other mail is `agent` or `no_person`. A sealed mail this machine has no key to open (RFC 0029) is
`sealed`, first of all: the reader lists it and says so, and never guesses whose it is.

## 3. Evidence, never a rule

PR #341 (merged, d5aa382) adds two MAY keys to new mail lines: `extra.gmail_category` (Gmail's tab: `primary`,
`social`, `promotions`, `updates`, `forums`) and `extra.list` (whether the mail carried `List-Id` or
`List-Unsubscribe` headers). When a line carries them, the reader **may show** them beside its class as
evidence: the category as its word, the list mark as `true`, never the headers' values (which hold
addresses and links). They are **never a rule by themselves**:

- a friend's mail sorted under *Updates* is still a person's mail;
- a mail from a person sent through a list, a club newsletter Per Hansen writes and sends, carries
  list headers and is still a person's mail;
- the other road to the same mailbox, IMAP, never sees the category, and the two roads write the same
  line (RFC 0043 §14 item 12), so a rule on it would class one mail two ways.

## 4. Minus let go: the hook, and why it removes nothing yet

RFC 0042 §4 proposes a **fate** per Hold item, `let-go` among them, an item of sort `sender` keyed by an
address or a domain. A sender let go is never a person's mail again, whatever resolves: the owner said
so. The reader takes the set of senders let go as an input (`Rule.let_go`, a set of `(kind, value)`
refs, `email` or `domain`) and classes such a mail `other`, reason `let_go`.

**Until Hold writes fates, that set is empty and the subtraction removes nothing.** `logbook lab hold`
writes reports under `state/hold/` and no line; no reader may take a report for a fate. When a fate line
lands (its own profile, under RFC 0042), the reader fills the set from the standing fates and this RFC
gains a dated line naming it.

## 5. The reader

`logbook.core.peoples_mail` (`docs/mail-people.md`):

- `read(lb, first, last)`: every mail line of the local days `[first, last]` that stands (not retracted,
  not superseded), each classed `person`, with the person ids that make it so, or `other`, with its
  reason (§2); and the counts. Read through the index: the resolution and retraction lines once, the
  window's mail lines through the `(kind, day_local)` index. On a record of five million lines this is
  the window's mail and the resolutions, never a full scan.
- `logbook people mail [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json]`: the counts by default (the
  last 30 days ending today), never an address and never a name in the terminal; `--json` adds each
  line's id, class, reason, evidence and person ids, never an address.
- `replies_owed(lb, day)` (RFC 0043 §4.5's *replies owed*): for each person the record names, over the
  90 days ending `day`, their direct conversations with the owner, in messages (a direct chat, never a
  group, never an agent's), people's mail (this rule) and calls; when the latest word among them is
  theirs (a message they sent, a mail they sent the owner, a call from them the owner did not answer)
  and is older than a week before `day`, the reply is owed. It returns the person's id and the ids of
  their lines since the owner's last word. A call the owner answered, or made, is the owner's word.
  RFC 0043 §4.5 says *more than a day*; this RFC proposes a week (open question 2).

## 6. The crossing

`logbook export crossing` (RFC 0005) applies the rule when mail is among the kinds asked for (`--kinds`
names `mail`, or no `--kinds` at all): only people's mail crosses. A mail line held back by the rule is
counted in the manifest's `counts` as `mail_held_back`, and, since a crossing line's counts are the
manifest's (RFC 0011), on the `crossing/v1` line too. The key is written whenever the window held a mail
line the tier, kind and signed-day gates let through, so a package without mail is what it was, byte
for byte; it is `0` when every such mail was a person's.

`--all-mail` lifts the rule and keeps the behaviour from before this RFC: every mail the other gates let
through crosses. The manifest says so, `policy.mail: "all"`, as does the line's `policy`; without the
flag neither key is written. Everything else the crossing does is unchanged: a held-back mail's
resolutions, attachments and stars stay home with it, as for any line that does not cross.

## 7. What this does not do

- It writes no line and changes no profile; `mail/v1` is untouched and the envelope is untouched.
- It does not touch the mail adapters or Hold.
- It does not move a person's mail to a higher tier, nor other mail to a lower one: tiers are SPEC §4's.
- It does not decide what the Day page shows; RFC 0043 slice A reads `read` and `replies_owed`.
- It does not filter a trip bundle (RFC 0030), which selects its own lines and still carries every
  mail its trip's window holds at its tiers; the rule reaches it in its own change.

## 8. Open questions

1. **A received mail with a person in cc only** (a school's mail copied to Kari Nordmann): other mail by
   §1. Recommended: keep it so; the owner can name the school's sender a person if they want it opened.
2. **The threshold of a reply owed**: a week (this RFC, the brief it was written from) or more than a day
   (RFC 0043 §4.5)? Recommended: a week on the page's first day, a setting later if the owner asks.
3. **Default of the crossing**: people's mail by default, `--all-mail` to lift it (this RFC), or the
   opposite until a member asks? Recommended: as written; it is the safer default and says so.

## Example (synthetic)

A record in Oslo holds three mails on 1 March 2026. Kari Nordmann's address, `kari@example.org`, resolves
to a person; `harbour@example.org` resolves to a `company`.

| mail | direction | from | to | class |
|---|---|---|---|---|
| "Mooring for the weekend" | received | `kari@example.org` | the owner | `person` (Kari) |
| "Your invoice" | received | `no-reply@harbour.example.org` | the owner | `other`, `no_reply` |
| "Berth 14" | sent | the owner | `harbour@example.org` | `other`, `no_person` |

`logbook people mail --since 2026-03-01 --until 2026-03-01` prints:

```
mail 2026-03-01 – 2026-03-01: 3 lines
  people's mail: 1 (1 received, 0 sent), from or to 1 person
  other mail: 2 (1 no person on it, 1 a no-reply sender, 0 an agent's)
  let go in Hold: nothing yet; Hold writes no fates
```

A crossing of that day with `--tier 1,2 --kinds mail` carries the first mail, `counts.mail_held_back: 2`.
