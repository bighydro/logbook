# RFC 0039 — Anchor: a signed day's hash in a public timestamp proof

Status: draft · 2026-10-14 · comment period: two weeks

A sailor whose boat was at sea during the storm that wrecked the harbour, a pilot whose ferry flight crossed a border on a given evening, a field scientist whose transect was walked on the day the permit allowed: each of them may one day need *I was there, that day* to be checkable by someone who has no reason to trust them. The record already holds most of the answer. Its sources are independent and agree or do not (a tracker, the boat's AIS, the camera, a flight line, the weather); its chain makes every line depend on every line before it (SPEC §3); and the owner's signature on a day, `signed-day/v1` (RFC 0034), binds the page the owner read, line by line, by hash. What it lacks is a witness outside the folder. The chain proves order and integrity to whoever already holds a head; whoever holds the files can recompute every hash from the first line on, and a stranger shown a day years later cannot tell a record kept as it happened from one rebuilt last week.

This RFC adds that witness. `logbook anchor` takes the standing signatures of the days the owner names, makes a salted commitment to each, combines them into one Merkle root, and sends that root, blinded with a random nonce, 32 bytes and nothing else, to a public timestamping service the owner has named in `policy/crossing.json`. The service binds it to a time it cannot later move. The record keeps the salts, the nonces and the proof in one tier-2 line and the file it points at. Years later the owner hands a verifier of their choosing one day's proof: the page's hashes, the lines they choose to show, that day's salt, and the proof file. The verifier checks it with public tools and public data, offline where the protocol allows, with no server of ours and no copy of this program.

Three constraints from the owner shape everything below: **hashes only** (no content crosses, ever), **an open protocol** (a proof must be checkable by anyone with the published specification), and **no server run by the project**.

What it proposes, all of it additive:

- two payload profiles at tier 2: `anchor/v1`, written by `anchor` (§5), and `anchor-export/v1`, the record that a proof left (§6.1);
- one bundle format, `anchor-proof/v1`, written by `anchor export` for one day and one verifier, and the steps a verifier follows (§6); and one attachment format, `anchor-proofs/v1`, in which the record keeps the proofs (§5.3);
- one block on a `policy/crossing.json` entry, `anchor`, naming a protocol and its endpoints, with `write` empty (§5.7);
- one rule for every export: `anchor` and `anchor-export` lines stay home unless the owner names the kind (§5.9);
- the commitment, the batch and the tree (§3), with OpenTimestamps as the recommended protocol and an RFC 3161 authority as the fallback and optional second proof (§4).

The envelope (SPEC §2–3) does not change: no spec version bump, no regenerated conformance fixture, no ADR for it. `signed-day/v1` does not change and no line already written is touched. No reader of SPEC §3.2 changes its JSON. The network is used only by `anchor` and its upgrade, on the owner's command, to destinations the owner named; `anchor export` writes a file.

## 1. Words

- To **anchor** a day is to have a timestamping service bind, at a time it cannot later move, a value that commits to the day's standing signature. The word is the command's and the line's (`anchor`, `anchor/v1`). Elsewhere the docs use *anchor* for a named place on the World page and for a boat at anchor; neither is a command or a kind (open question 15).
- A **signature** here is always RFC 0034's: the `signed-day/v1` line, the owner's reading of a day's page recorded in the chain. It is not a cryptographic signature; nothing in it is signed with a key. The **page** of a day and its digest are RFC 0034's, *The page as shown*.
- A **leaf** is a 32-byte commitment: to one day (a **day leaf**), to the record's head when the batch was made (the **head leaf**), or to nothing (a **fill leaf**). A **salt** is 32 random bytes that make a leaf unguessable. The **seed** is 32 random bytes from which a batch's fill leaves are derived.
- A **batch** is a fixed number of leaves, its **width**, combined into one Merkle tree; its **root** commits to all of them. The **path** of a leaf is the list of sibling hashes that leads from it to the root. A **nonce** is 16 random bytes drawn for one destination; the root **blinded** for that destination, `sha256(root ‖ nonce)`, is the one value that leaves the machine for it.
- A **destination** is a timestamping service named by an entry of `policy/crossing.json`: an OpenTimestamps **calendar**, an RFC 3161 **authority** (a TSA). A **proof** is what a destination hands back: **pending** when it is a promise (an OpenTimestamps calendar's, before its transaction is in a block), **final** when it binds the root to a time by itself.
- A **verifier** is the person the owner hands one day's proof to: an insurer, a race committee, a court, a colleague. An **observer** is anyone who sees what is public: a blockchain, a log, a calendar's or an authority's server.
- **T** is the time a final proof bounds the root by: for a Bitcoin block, its header's time plus two hours (§7.1); for an authority, its `genTime`.

## 2. What an anchor adds, and what it does not

The record can already show that its days agree with each other and that nothing in a chain a person holds was changed after they received it: a crossing line records the head it reflects (RFC 0011), and a member who keeps their packages can hold the owner to it. What none of this gives is a statement to a stranger about *when*: every time in the record is the record's own word. An anchor gives one, and only one: **this value existed before a given Bitcoin block was mined, or when an authority says it did**, which a verifier turns into a time T (§7.1). From that, and from the hashes the value commits to, a verifier concludes that the page, the lines shown and the signature existed in exactly this form no later than T. Everything else a verifier might want to conclude, that the lines are true, that the owner is who they say, that the day was recorded on the day, is not in the anchor, and §7 says so line by line.

## 3. What is anchored

### 3.1 The candidates

Three values could be sent, and one more was considered:

| | Value | Binds | To check it, a verifier needs |
|---|---|---|---|
| A | the signature's content hash, `sha256(content)` of SPEC §3 | the signature's `at`, `end`, `tz`, `source`, `kind`, `tier` and payload: the day, `subject` (the `owner_id`), the confirmed ids, the page digest, the note, the dispositions; through the page digest, the hash of every line on the page | the signature's content fields |
| B | the signature's `hash`, which is the record's **head at signing**: the writer appends the signature under the writer lock and reads the head again before it appends (RFC 0034 amendment 3), so the moment it lands it is the head | everything A binds, and the signature's `seq`, `recorded_at` and `prev`; through `prev`, every line before it in the chain | the whole signature line |
| C | a Merkle root over many days' values | every day's value in it | one value and its path |
| — | the head at anchoring, later than the signature | every line before it, the signature among them | the walk from the signature to that head: the `seq`, content hash and `recorded_at` of every line written in between |

The last is rejected as the way to prove a day: a walk from a signature on 13 June to a head on 21 June discloses how many lines the record took in that week and when each was recorded, to prove one day. It is kept for another purpose, as one leaf among the others (§3.4).

### 3.2 A hash is not hiding

A and B are SHA-256 over inputs a guesser can come close to, and over inputs some people simply hold.

- **Who holds them.** A signature is tier 1 and crosses with the day it signs (RFC 0034 rule 5). Every member a signed day crossed to holds the signature line and can compute A and B exactly; so can an orchestrator reading through the MCP door under any ceiling, and anyone with a copy of the record, key or no key, since tier-1 lines are plain at rest (SPEC §4). If A or B were published, any of them could search a calendar or a log for it and learn that the owner anchored that day, when, and through whom; and, day after day, how often.
- **Who can guess them.** A signature of an empty day signed with `--confirm none` (RFC 0034 amendment 2) has a payload made of the day, the `owner_id`, an empty list and the digest of an empty page, which the day and the zone alone determine; its envelope fields are fixed but for `at`, the moment of signing: to the second, each day between the day lived and the signature is 86,400 candidates (an `at` with fractional seconds, which `--at` may carry, multiplies them). The `owner_id` is in every shared page (RFC 0025, `from`) and every day package. A is then a search over tens of thousands of candidates for each day of that window, unless the signature `supersedes` an earlier one, whose id cannot be guessed; B adds `prev`, which a stranger cannot guess and anyone holding a nearby line of the chain can. RFC 0029 §2 says the same of a sealed line's payload, and answers it the same way.

So the published value MUST be a **commitment** with a secret salt: unguessable without the salt, checkable with it, and the salt is the owner's to hand to the verifier they choose.

### 3.3 The day leaf

For each day anchored, the standing signature of the day (RFC 0034 rule 3) at the time of the run:

```
leaf = sha256( canonical_json({"schema": "anchor-leaf/v1",
                               "page": "<the signature's payload.page.sha256>",
                               "salt": "<64 lowercase hex: 32 random bytes>",
                               "signature": "<the signature's hash>"}) )
```

`canonical_json` is RFC 8785 as SPEC §3 uses it; every digest is lowercase hex in the pre-image and 32 raw bytes as the leaf. The salt is drawn from the operating system's cryptographic random source, fresh for every leaf, and never reused.

- **B, not A**, because it pins the chain: a leaf over the signature's `hash` binds its `prev`, and through it every line the record held when the owner signed. A anchors the signature and the page; B anchors those and the record before them, at the cost, for a verifier shown the signature, of seeing its `seq` (how many lines the record held) and `recorded_at`.
- **The page digest beside it**, although B already binds it, so that a verifier can be shown the page without the signature (§6.5): the signature carries the confirmed ids, the dispositions and the owner's note, and a note in the owner's words is not something every proof should have to show. With the page in the leaf, a verifier checks the page against the leaf and takes the signature's hash as an opaque value; shown the signature too, they check that its hash is that value and that its `page.sha256` is the page.
- **32 bytes of salt, not the 16 of a sealed line** (SPEC §2): a sealed line's digest sits inside the owner's folder; a root is public forever and cannot be withdrawn. 256 bits keeps a search out of reach even for a computer that halves its exponent (a quantum search over 2^256 salts is still 2^128 steps).

### 3.4 The batch

A run puts every leaf it makes into one batch of **width 512** (open question 3):

- one day leaf per day anchored, at a position drawn at random;
- one **head leaf** for the record's head at the moment of the run, at a random position:

  ```
  head = sha256( canonical_json({"schema": "anchor-head/v1", "head": "<the head>",
                                 "salt": "<64 hex: 32 random bytes>", "seq": <the head's seq>}) )
  ```

  It pins every line of the record, signed day or not, to T, for the day the whole record is audited (§6.5); it serves no single day's proof;
- every other position a **fill leaf**, derived from the batch's seed:

  ```
  fill_i = sha256( canonical_json({"schema": "anchor-fill/v1", "index": i,
                                   "seed": "<64 hex: 32 random bytes>"}) )
  ```

The tree is the Merkle Tree Hash of RFC 9162 §2.1.1 over the 512 leaves taken as its entries, each the leaf's 32 bytes: a node is `sha256(0x01 ‖ left ‖ right)` and an entry enters as `sha256(0x00 ‖ leaf)`, so no node can pass for a leaf. With a width that is a power of two the tree is complete and every path is nine hashes long; a path and its check are RFC 9162 §2.1.3. More than 511 days in one run make several batches, each its own root, its own proofs and its own line. A batch with no day leaf at all is allowed (§8, cover batches).

The **root**, blinded for each destination (§3.6), is what leaves the machine. It is also `sha256` of a 65-byte string, `0x01 ‖ left ‖ right` at the top of the tree, which the proof bundle carries as `top.bin` (§6.1) so that stock tools, which timestamp *a file*, check the root as the digest of that file.

### 3.5 Recommendation

Anchor **C over salted B**: per day, a leaf committing to the signature's hash and its page digest under a fresh 32-byte salt; per run, a fixed-width tree of those leaves, one salted head leaf and fill; the root crosses, blinded for each destination. It sends one value per destination per run however many days it covers, so cost and cadence do not grow with the days; it proves any one day with nine hashes and that day's salt, and shows nothing about the others; and it pins, besides each signature, the whole record as it stood.

### 3.6 What is published, and why nothing can be learned from it

**Published:** to each destination of the run, the root **blinded** for that destination: `sha256(root ‖ nonce)`, the nonce 16 random bytes drawn for that destination alone, as the OpenTimestamps client does by default *(to check)*. The nonce is kept with that destination's proof (§5.3) and travels in a bundle (§6.1); without it, a root that leaks cannot be looked up at a calendar, and two destinations cannot tell that they hold the same root. An OpenTimestamps calendar keeps what it received and answers anyone who asks about it; a Bitcoin transaction then carries the calendar's own root over thousands of submissions, never this one; an RFC 3161 authority keeps whatever it keeps. Treat every blinded value as public forever. **Not published:** the root itself, the nonces, the salts, the seed, the positions, the leaves, the pages, the signatures, any line, the `owner_id`, the number of days.

**The argument.** It rests on two assumptions, the same ones every hash commitment rests on:

1. SHA-256 is preimage-resistant and, to anyone who does not know its whole input, its output is indistinguishable from 32 random bytes (the random-oracle reading of SHA-256).
2. Every salt and every seed is 32 fresh bytes, and every nonce 16, from the operating system's cryptographic random source, never reused, written only in the `anchor/v1` lines of its batch and the proofs file they point at, sealed in a record that seals (in one that does not, only when the owner typed `--plain`, §5.5), and disclosed only as §5.9 and §6 say: one day's salt in that day's bundle, the head's salt in an audit, the seed never.

Under them, every leaf of a batch is a SHA-256 output over an input with 256 secret random bits, so the leaves are indistinguishable from independent random bytes (the fill leaves share a seed but never an input), and the root, a function of the leaves alone, is too; so is each blinded value. Concretely:

- **The day's content.** Two batches over the same days with different lines on their pages, or over different days, or from different records, give roots with the same distribution. Nothing on a page, a word, a place, a count, a time, reaches the root except through a salted hash.
- **The owner.** The `owner_id` enters only as part of a signature's content, under B, under a salt. Nothing else about the owner is in a leaf. (Who *sent* the root is another matter: §8.)
- **The people in it.** They are in lines (a message's sender, a call's counterpart, an attendee, a speaker), which enter only as line hashes inside the page digest, inside a salted leaf.
- **How many days, and which.** The width is fixed, the positions random and a fill leaf indistinguishable from a day leaf, so a root over one day, over three hundred, and over none look alike. Without the seed, not even the owner's verifier can count the real leaves (§6.4).
- **Confirmation.** Someone who holds a signature line, its page and every line on it (a member it crossed to, a thief with the files) and wants to test whether the owner anchored that day has nothing to test against in a blinded value or a root alone: either is a function of 511 other leaves they do not have. Holding a path from a disclosed bundle of the same batch, they must find the salt that makes their candidate equal a sibling in it: 2^256 candidates, 2^128 steps for a quantum search. Holding the true line confirms nothing.

What the argument does not cover, and where each is answered: the metadata of sending (address, time, cadence: §8); a salt the owner disclosed, which makes that one day checkable by whoever holds the bundle, which is the point (§6); a broken random source, under which nothing here holds, nor does sealing (RFC 0029); and a future break of SHA-256's one-wayness, which would put the secrecy of every published value in question at once. A published value cannot be withdrawn; renewal (§6.6) protects a proof's *strength*, not a root's *secrecy*.

## 4. The protocols

Each is compared on the same six questions: whom you must trust; what it costs; how long until the proof is final; whether a verifier can check it offline; how long it will last; and what it makes public and linkable. Statements about the services as they run today are from memory and marked *(to check)*; §12 lists them.

### 4.1 OpenTimestamps (Bitcoin)

An open protocol and file format. A client sends a 32-byte digest to one or more **calendars**, public servers run by independent operators *(to check: three or four, listed by the project)*. Each calendar combines the digests it received into a Merkle tree and, every so often, puts that tree's root into a Bitcoin transaction. The client gets back a pending proof at once and, after the transaction is in a block, asks the calendar again and gets the final proof: a short program of append, prepend and hash operations that leads from the digest to the Merkle root in that block's header, ending in an attestation that names the block's height.

- **Trust.** For a final proof: that nobody has rewritten Bitcoin's chain back past that block (its proof of work), and SHA-256. No calendar's word is in a final proof; a calendar can only delay, refuse or lose a submission. For a pending proof: the calendar's promise, which proves nothing.
- **Cost.** Nothing to the owner. The calendar pays one transaction fee for thousands of digests and runs on its operator's goodwill.
- **Delay.** Seconds to submit; a final proof once the calendar's transaction is in a block, usually within hours, longer when fees are high and calendars wait *(to check)*.
- **Offline.** Yes: the proof file holds every step from the root to the block's Merkle root. The one fact from outside is the header of that block: 80 bytes, which a verifier takes from any source they already trust, their own node, a copy of the chain of headers (80 bytes for every block since 2009, under 100 MB in 2026, whose proof of work they can check with no network at all) or several unrelated copies compared. A block's time is accurate to about two hours: the network accepts a header's time when it is after the median of the eleven blocks before it and less than two hours ahead of the nodes' clocks.
- **Longevity.** The format is small, versioned and implemented independently in several languages *(to check)*, and proofs from its first years still verify *(to check)*. Bitcoin's headers are copied in more places than any archive the project could keep. The risks are SHA-256 itself (renewal, §6.6) and, for a pending proof, a calendar that closes before it upgrades; hence several calendars per run and the upgrade as soon as it is ready (§5.6).
- **Public and linkable.** On the chain, nothing of the owner's: one transaction per calendar per round, over everyone's digests. At a calendar: the digest, the moment it arrived, and the network address it came from; and a calendar answers anyone who presents a digest's commitment, so whoever holds a proof can learn when it was submitted. This RFC sends a blinded root (§3.6), so a root without its proof is not enough.

### 4.2 RFC 3161 trusted timestamping

An authority (a TSA) receives a hash and the request's nonce (a number against replay, not §3.6's), and returns a token: the hash, the time (`genTime`), a serial number and a policy, signed with the authority's key under an X.509 certificate.

- **Trust.** The authority: its clock, its key, and its honesty, since it can sign any time it likes; and the certificate chain over its key. A key that leaks puts every token it ever signed in doubt, unless each was renewed before the leak (§6.6).
- **Cost.** Some authorities answer free of charge *(to check)*; a qualified authority under the EU's eIDAS regulation charges per token or by contract, and usually wants an account. A qualified time stamp carries a legal presumption that its date and time are accurate in the member states (eIDAS Art. 41; how it applies in Norway through the EEA is *to check*), which is the one thing here a court may weigh above Bitcoin.
- **Delay.** Seconds; the token is final when it arrives.
- **Offline.** Yes, with the token, the authority's certificate chain, the status of those certificates at `genTime` (a CRL, fetched when the token is made and kept beside it; `openssl ts` reads a CRL, not an OCSP answer *(to check)*), and a root certificate the verifier trusts. `openssl ts -verify` does it, told to judge the chain at `genTime` (§6.3).
- **Longevity.** As long as the chain is trusted or its status was kept. Certificates expire after some years and algorithms age; the standard answer is to renew the evidence before either happens (RFC 4998, evidence records). An authority that closes takes nothing with it if the chain and status were kept.
- **Public and linkable.** Nothing is published. The authority sees the root, the time, the address and, under contract, the account: every token tied to the owner's name.

### 4.3 Transparency logs (Sigstore's Rekor)

A public, append-only Merkle log run for the software supply chain. An entry records an artifact's hash with a signature over it and the public key or certificate that made it; the log returns a proof of inclusion under a signed checkpoint, and witnesses can check that the log never forks.

- **Trust.** The operator for any time it states, and the witnesses for the log's history. The current version of Rekor leaves trusted time to an RFC 3161 authority and no longer signs a time of its own with an entry *(to check)*; with it, the trust is §4.2's plus the log's.
- **Cost.** Free on the public instance.
- **Delay.** Seconds to inclusion.
- **Offline.** Inclusion, yes, from the proof, the checkpoint and the log's public key. Time, only as §4.2 or as the operator's word.
- **Longevity.** The public instance is a service for software signing, not an archive; its logs are sharded and rotated, and it makes no promise this RFC could rely on to keep a personal entry for decades *(to check)*.
- **Public and linkable.** Everything, to everyone, forever: the hash, the signature, the public key and the time are searchable. Every entry needs a signing key, and one key reused across entries ties them all together; a fresh key per entry is one more secret to keep for a proof. With a salted root, the hash itself says nothing; the entries' timing is public to the world rather than to one calendar.

### 4.4 Others worth naming

- **A notice in a widely kept publication.** The oldest way, from the line of work Haber and Stornetta began in 1991; a commercial service built on it has printed digests in a newspaper since the 1990s *(to check)*. Print the root where libraries will keep it. The trust is the publication and its archives; it costs money and a day; it verifies offline from paper; it lasts as long as the archives; and the notice is tied to whoever paid for it. Not for a person's week.
- **Other public chains.** The shape of §4.1 with different trust. A chain that agrees by stake rather than work cannot be checked from its headers alone years later: a verifier needs a recent checkpoint they trust. Its fees are per transaction unless a service aggregates, and the service adds its own server to the trust and the lifetime.
- **Roughtime.** Servers sign a time over a nonce the client chooses, so a response is a small timestamp. It is made for setting clocks: keys rotate, servers make no archival promise, and nothing aggregates.
- **A public repository or post.** A commit's date is its author's word and a push's time is the host's; either is tied to an account. No.

### 4.5 Side by side

| | OpenTimestamps | RFC 3161 authority | Rekor | Newspaper notice |
|---|---|---|---|---|
| Trust for time | Bitcoin's proof of work, SHA-256 | the authority | the operator, or an authority | the publication |
| Cost to the owner | none | none to a fee per token | none | a fee per notice |
| Delay to final | hours | seconds | seconds (time: §4.2's) | a day or more |
| Offline check | yes, given one 80-byte header | yes, given the chain, its status and a root | inclusion yes; time per §4.2 | yes, from paper |
| Longevity | as long as Bitcoin's headers are kept and SHA-256 holds | as long as the chain is trusted or renewed | the operator's | the archive's |
| Public | the root at the calendar; nothing on chain | nothing | everything, searchable | the root, printed |
| Linkable to the owner | network address and timing, at the calendar | address, timing, account | key and timing, to everyone | the payer |

### 4.6 Recommendation and fallback

**OpenTimestamps** is the recommended protocol: no party's word in a final proof, no cost, nothing of the owner's on the chain, a proof that checks offline against one public header, and a format small enough to verify by hand. Its weakness is delay, and a pending proof that is worth nothing until it upgrades.

**An RFC 3161 authority** is the fallback, and the optional second proof of the same root: when hours are too long (a claim filed the same evening), when a court or an insurer wants a token it recognises, or when the calendars are unreachable. It costs trust in one party, and an account if the authority is qualified. One root, two destinations, two proofs: a verifier needs either, and the second costs one request.

**Not Rekor**, for a personal record: public by design, a key per entry to keep, and time from someone else anyway. **Not a chain reached through a service**, which puts a server back into the trust.

## 5. The record's side

### 5.1 A line of its own

The proof cannot live on the signature: a line is never rewritten (SPEC §3), a field added to `signed-day/v1` after the fact would be a rewrite, and a second signature written only to carry a proof would supersede the first and say the owner read the page again when they did not. The proof also arrives hours after the signature, from outside. So an anchor is its own line, `anchor/v1`, which names the signatures it anchored by id and by hash and holds what proves them: the salts, the seed, the positions, the root, the destinations and the proof files.

### 5.2 Line

`kind` MUST be `anchor`. `tier` MUST be 2 (§5.4). `source` is `logbook`: the tool wrote it on the owner's command, as it writes `crossing/v1` (RFC 0011). `at` is when the root crossed: the moment the first destination accepted it; on a line that records a proof becoming final (§5.6), the moment the final proof was received. `end` is null.

### 5.3 Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"anchor/v1"` | MUST | |
| `batch` | object | MUST | `{ width, seed }`: the batch's width (512) and its seed, 64 hex |
| `days` | array | MUST | one object per day leaf, in day order: `{ day, tz, day_start, signature, signature_hash, page, salt, index }`: the local day, the record's zone and `day_start` (RFC 0036) under which its page was rebuilt (§5.5 step 3), the id and the `hash` of the standing signature anchored, its `page.sha256`, the leaf's salt (64 hex) and its position (0 to `width` − 1). Empty only in a cover batch (§8) |
| `head` | object | MAY | `{ seq, hash, salt, index }`: the head leaf, when the run made one |
| `root` | hex sha256 | MUST | the root of the batch: the value that crossed |
| `proofs` | array | MUST | one object per destination the root reached: `{ destination, protocol, endpoints, state, attested }` (below) |
| `file` | attachment reference | MUST | the batch's proofs file, `anchor-proofs/v1` (below), as SPEC §1.1 stores it, `application/json` |
| `policy` | object | MUST | `{ file, versions }`: `file` the record-relative policy path (`policy/crossing.json`); `versions` maps each destination's entry name to the entry's version as RFC 0036 defines `extra.policy_version` (the SHA-256 of the RFC 8785 JSON of its `max_tier`, `until` and `model`). The endpoints the root went to are in each proof |
| `supersedes` | string | MAY | the id of the earlier `anchor/v1` line of the same batch that this one replaces (§5.6) |
| `pad` | string | MUST | the smallest number of `0`s, possibly none, for which the UTF-8 length of `canonical_json(payload)`, the `pad` member included, is a multiple of 16,384. A sealed line's length is its payload's plus a near-constant (age adds a fixed overhead, RFC 0029 §3), so without it a keyless holder would count the days in a batch from the line's length and tell a cover batch by its shortness. With it, a batch of a week and a cover batch are one size; a `days` entry is about 380 bytes, so one step of 16,384 holds about forty days, and a backfill of hundreds of days still shows its size to within one step |

A proof object:

| Field | Type | Req | Meaning |
|---|---|---|---|
| `destination` | string | MUST | the entry's name in `policy/crossing.json` |
| `protocol` | `"opentimestamps"` or `"rfc3161"` | MUST | |
| `endpoints` | array of string | MUST | the calendars or the authority's URL the root was sent to and accepted by |
| `state` | `"pending"`, `"final"` or `"lost"` | MUST | `final`: a complete proof was received (§5.6); `lost`: the owner gave up on a pending proof |
| `attested` | object | MAY | for a final proof, what it says, as a convenience for readers: `{ chain: "bitcoin", height }` for OpenTimestamps, with `time` only when the owner's machine checked the block's header (§5.6); `{ time, serial, authority }` for an authority. A reader that verifies takes these from the file and the header, never from here |

Anything else MAY be kept under `extra`.

**The proofs file.** The proofs are not stored as themselves. An attachment is named by the digest of its plaintext and the name is plain on disk (SPEC §1.1), and a destination holds the bytes it issued: a token, or the whole of a single calendar's proof. It could hash them and find that name in a keyless copy of the record, and tie the copy to its own log of who sent what. So each `anchor/v1` line points at one file of its own, canonical JSON:

```
{"schema": "anchor-proofs/v1", "salt": "<32 lowercase hex: 16 random bytes>",
 "proofs": [{"destination": "<entry>", "protocol": "opentimestamps" | "rfc3161", "nonce": "<32 hex>",
             "proof": "<standard base64 of the proof file>",
             "chain": "<standard base64 of the authority's certificates and their status; rfc3161 only>"}],
 "pad": "<0s to the next multiple of 16,384 bytes>"}
```

The salt makes its name unguessable; the padding hides how many proofs it holds and of which kind. A proof's state is the line's, never the file's. `proof` is the OpenTimestamps file (its first operations append the nonce and hash, §3.6) or the authority's response (`TimeStampResp`, RFC 3161), whose imprint is `sha256(root ‖ nonce)`. A file a tier-2 line points at is sealed with it (SPEC §1.1). A line that records a proof becoming final points at a new file; the earlier one stays, as the earlier line does.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"anchor/v1","type":"object",
 "required":["schema","batch","days","root","proofs","file","policy","pad"],
 "$defs":{"hex":{"type":"string","pattern":"^[0-9a-f]{64}$"},
  "uuid":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
  "ref":{"type":"object","required":["sha256","path","bytes","media_type"],
   "properties":{"sha256":{"$ref":"#/$defs/hex"},"path":{"type":"string","pattern":"^attachments/[0-9a-f]{64}$"},
    "bytes":{"type":"integer","minimum":0},"media_type":{"type":"string","minLength":1}},"additionalProperties":false}},
 "properties":{
  "schema":{"const":"anchor/v1"},
  "batch":{"type":"object","required":["width","seed"],"properties":{
   "width":{"const":512},"seed":{"$ref":"#/$defs/hex"}},"additionalProperties":false},
  "days":{"type":"array","maxItems":511,"items":{"type":"object",
   "required":["day","tz","day_start","signature","signature_hash","page","salt","index"],"properties":{
    "day":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
    "tz":{"type":"string","minLength":1},
    "day_start":{"type":"string","pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$"},
    "signature":{"$ref":"#/$defs/uuid"},"signature_hash":{"$ref":"#/$defs/hex"},"page":{"$ref":"#/$defs/hex"},
    "salt":{"$ref":"#/$defs/hex"},"index":{"type":"integer","minimum":0,"maximum":511}},
   "additionalProperties":false}},
  "head":{"type":"object","required":["seq","hash","salt","index"],"properties":{
   "seq":{"type":"integer","minimum":0},"hash":{"$ref":"#/$defs/hex"},"salt":{"$ref":"#/$defs/hex"},
   "index":{"type":"integer","minimum":0,"maximum":511}},"additionalProperties":false},
  "root":{"$ref":"#/$defs/hex"},
  "proofs":{"type":"array","minItems":1,"items":{"type":"object",
   "required":["destination","protocol","endpoints","state"],"properties":{
    "destination":{"type":"string","minLength":1},
    "protocol":{"enum":["opentimestamps","rfc3161"]},
    "endpoints":{"type":"array","minItems":1,"items":{"type":"string","pattern":"^https://"}},
    "state":{"enum":["pending","final","lost"]},
    "attested":{"type":"object"}}}},
  "file":{"$ref":"#/$defs/ref"},
  "pad":{"type":"string","pattern":"^0*$"},
  "policy":{"type":"object","required":["file","versions"],"properties":{
   "file":{"type":"string","minLength":1},
   "versions":{"type":"object","additionalProperties":{"$ref":"#/$defs/hex"}}}},
  "supersedes":{"$ref":"#/$defs/uuid"},
  "extra":{"type":"object"}}}
```

A writer also keeps what the schema cannot say: positions are distinct across `days` and `head`; the days are distinct; every proof's `destination` is an entry of the policy file named and has one entry in the proofs file; `chain` is present there exactly on an `rfc3161` proof; and `pad` brings the payload to its multiple.

### 5.4 Tier

**2, and a writer MUST NOT write another.** Three reasons:

- **It is the owner's decision about their life.** A signature (tier 1) already says the day was signed and when; it crosses so that a member can tell a signed day from an unsigned one (RFC 0034, *Why tier 1*). An anchor adds that the owner chose to make the day provable to a stranger, and which days they chose. Anchoring the day of an accident says the owner expects a dispute. That is a decision, as a confirmation is (SPEC §4, tier 2), and not something every member should learn by default.
- **It holds the salts.** A salt is the only link between a public root and the record. A tier-1 line would cross by default to every member and lie plain at rest; a tier-2 line is sealed at rest in a record that seals (SPEC §4) and crosses only when the owner asks for tier 2 and the entry allows it, and §5.9 holds it home even then.
- **Tier 3 would protect no better.** The salts hold no words, money or health; tier 3's only extra is that a policy edit alone never lets it cross, which §5.9 already gives this line by kind, without putting the owner's own audit of their anchors behind the gate that guards their bank statements.

The plain envelope still says `kind: anchor` and `at` to whoever holds the files without the key (RFC 0029 §2), and the tier-1 signatures beside it say which days were signed and when. A keyless holder therefore learns when the owner anchored, and can guess that the days signed since the previous anchor line were in it; the padding (§5.3) keeps the line's length from saying how many to closer than about forty days (one step), so that a week's batch and a cover batch (§8) look alike. They learn neither the salts nor the root. A record with no recipients would write the line plain, as it writes every tier-2 line, salts and all; `anchor` refuses there unless the owner types `--plain` (§5.5), and `doctor` names the plain anchor lines.

### 5.5 What `anchor` does

```
logbook anchor DAY [DAY …] | --since DAY [--until DAY]  [--to NAME[,NAME…]]  [--again]  [--as-signed]  [--plain]  [--dry-run]
```

`anchor` is a writer: it runs on the record's home (ADR 0022). It reads the days under the writer lock (steps 2 to 5), sends with the lock released, since a network call may take minutes and holding the lock that long would stop every other writer (step 6), and takes the lock again to append (step 7). A signature written for one of the days in between leaves the anchor on the signature it read, which `doctor` then names (§5.10). In this order, refusing in one sentence and writing nothing at the first failure:

1. **The policy.** Every destination (`--to`, or every entry with an `anchor` block when it is not given) is an entry of `policy/crossing.json` with an `anchor` block (§5.7), a `max_tier` of 1, `write` empty or absent, and an `until` not passed. A destination the file does not name, or names without an `anchor` block, is refused naming the file. A record whose `logbook.json` names no recipients is refused unless `--plain`: the salts would lie plain on disk, and that is a choice the owner types.
2. **The days.** Each day named has a standing signature (RFC 0034 rule 3); an unsigned day is refused by name (`2026-06-14 is not signed: sign it first, or leave it out`). A day whose standing signature is already in a batch with a pending or final proof is skipped and named, unless `--again`.
3. **The page as signed.** For each signature, the page is rebuilt as it was when the owner signed: every line whose `at` falls on the day (with the record's zone and `day_start`, RFC 0036), of every kind but `retraction` and `signed-day`, whose `seq` is below the signature's, in the day's order. Lines appended later have later `seq`s, and the writer read the page and appended under one hold of the lock (RFC 0034 amendment 3), so this is exactly the page the owner read. Its digest MUST equal the signature's `page.sha256`; a mismatch (the zone or `day_start` changed since, or the record was altered) is refused naming the day. A page that has grown since signing (`page_matches` false, RFC 0034 rule 6) is refused too, naming the day and the count (`2026-06-12: the page has 2 lines more than you signed; sign it again, or anchor the page as signed with --as-signed`): the owner most likely wants their latest reading anchored, and anchoring an older one is a choice they type. The zone and `day_start` used go into the line, so that the page can be rebuilt the same way after either setting changes.
4. **The note.** A signature with a `note` is named once: a proof that shows the signature shows the note (§6.5).
5. **The batch.** Salts, the seed and the positions are drawn; the leaves, the tree and the root are computed (§3).
6. **The crossing.** A nonce is drawn for each destination and the blinded root, `sha256(root ‖ nonce)`, is sent to it (§3.6). A destination that fails is named and the run goes on with the others; when none accepted the root, nothing is written and the command exits non-zero.
7. **The line.** The proofs that came back (`pending` for a calendar, `final` for an authority) go into the proofs file, stored as an attachment, and one `anchor/v1` line pointing at it is appended through `Logbook.append` under the writer lock.

`--dry-run` does steps 1 to 4 and prints what would cross and where; it draws nothing, sends nothing and writes nothing.

A crash between steps 6 and 7 leaves a root on a calendar that no line holds the salts of. It is unlinkable to the record forever, and the days are simply not anchored: run again, and the new run makes new salts and a new root. Nothing in it is worth recovering, and nothing of the owner's leaked.

### 5.6 The upgrade

A pending OpenTimestamps proof is worth nothing until the calendar's transaction is in a block. `logbook anchor --upgrade` (and every `anchor` run, first) asks the calendars of every pending proof for its final form, which sends nothing new: the calendar is asked about the commitment it was given. For each batch with a proof that became final, it writes a new proofs file and appends one `anchor/v1` line with the same batch, days, head and root, the proofs' new states, `attested` filled, the new file, and `supersedes` naming the earlier line. The earlier line stays, as every line does; the standing line of a batch is the latest that is not superseded or retracted.

`anchor --upgrade` checks the proof's operations up to the block's Merkle root and does not fetch the block's header; with `--headers FILE` (a file of headers the owner keeps) or a local Bitcoin node named on the entry, it checks that too. `final` on a line therefore means that a complete proof was received, which until a header is checked is the calendar's word that such a block exists (§7.2, item 9): `attested.time` is written only when a header was checked, and `anchor list` and `doctor` name the final proofs no header has checked. A proof still pending after 7 days is named by `doctor`; the owner may give it up (`anchor --give-up ROOT DESTINATION`), which appends one `anchor/v1` line, `at` the moment of giving up, that supersedes the standing line of the batch, points at the same proofs file and sets that destination's proof to `lost`, the others unchanged. The owner then anchors the days again in a new batch.

### 5.7 What crosses, and the entry

What crosses is the root blinded for each destination, 32 bytes, to that destination; on an upgrade, the question about it. Nothing else: no line, no hash of a line, no `owner_id`, no count, not the root itself.

A destination is an entry of `policy/crossing.json` (ADR 0016), as every crossing's is, with one more block:

```json
{"timestamps": {"max_tier": 1, "write": [],
                "anchor": {"protocol": "opentimestamps",
                           "calendars": ["https://ots-a.example.org", "https://ots-b.example.org",
                                         "https://ots-c.example.org"]}},
 "tsa":        {"max_tier": 1, "write": [], "until": "2027-12-31",
                "anchor": {"protocol": "rfc3161", "url": "https://tsa.example.org/tsr"}}}
```

- `max_tier` MUST be 1. The root is derived from tier-1 signature lines and random salts, and reveals nothing above them; the line hashes of tier 2–3 lines inside a page digest reveal nothing either, which is why a signature is tier 1 at all (RFC 0034, *Why tier 1*). A higher ceiling means nothing here and is refused as a broken entry, so that nobody reads it as permission.
- `write` MUST be empty or absent. A timestamping service writes nothing into the record; the proof it hands back is written by `anchor`, on the owner's command, through `Logbook.append`.
- `until` is ADR 0022's: an entry past its day allows nothing.
- `anchor.protocol` is `opentimestamps` with `calendars` (two at least, so that one closing loses nothing) or `rfc3161` with `url`. Optional keys: `via`, a proxy the requests go through (open question 11), and `schedule` (§5.8).
- An entry with an `anchor` block is a destination for `anchor` alone: `export crossing`, `share day`, `export trip-bundle` and the MCP door refuse it by name, so that a timestamping service is never sent a line because its ceiling happens to allow one.
- No entry, no anchor. `init` writes none, and the code ships no calendar or authority: the owner writes the entry by hand, from the docs, as they write every other (`docs/settings.md`: *what may leave, and to whom … by hand*).

**The record of the crossing is the `anchor/v1` line.** ADR 0016 rule 4 asks that every time anything leaves, the chain hold it in order with its destination and the policy in force; the anchor line does, under the hash, with the entry's version, the endpoints and, in its proofs file, the nonce of what was sent. It does not also append a `crossing/v1` line, for two reasons: that profile is tier 1 (RFC 0011) and crosses by default, and would tell every member, every time, that the owner anchored, which §5.4 keeps at tier 2; and its required fields (`window`, `tiers`, `counts`, `package_sha256`) describe a package of lines, of which a root has none. A reader that counts what left the record (RFC 0011 rule 5) reads `anchor` lines beside `crossing` lines. Open question 6 asks whether that is the right trade.

### 5.8 When

**By hand.** `anchor` runs when the owner types it, and never because a day was signed, a sync ran or an orchestrator asked: no MCP tool anchors, and `sign_day` (RFC 0034 amendment 3) does not. `sync --install-schedule` installs nothing for it.

**A schedule only if the owner sets one.** An entry MAY carry `"schedule": "weekly"`: the close of the scheduled run (`docs/schedule.md`) on the first day of the week then starts one detached run, `anchor --scheduled`, and does not wait for it. That run draws a delay at random between 0 and 12 hours and sleeps it, then runs `anchor --upgrade` and anchors every day signed in the past week that no batch holds, through that entry, or, when there is nothing to anchor, sends a cover batch (§8). It takes the writer lock only to read and to append, as §5.5 says. A machine that sleeps or restarts in the meantime loses the run, not the days: they are still unanchored at the next week's close. Absent, the schedule never anchors and never upgrades, exactly as the close never dreams without a `dream` entry.

### 5.9 What stays home

An `anchor/v1` line holds the salts of every day in its batch: handing it over hands over the power to prove all of them. An `anchor-export/v1` line (§6.1) says which day the owner proved and to whom. So, for both kinds:

- every crossing and every page leaves them home and counts them as held back, whatever the tiers asked: `export crossing` (RFC 0005), a shared page (RFC 0025), a trip bundle (RFC 0030), the vault and the site; `export crossing` crosses them only when the owner names the kind (`--kinds anchor`, `--kinds anchor-export`) as well as tier 2, to an entry whose ceiling allows it, and the proofs files they point at go with them as attachments do;
- the MCP door serves none, whatever its ceiling, and writes none;
- `export --sealed` and `backup`, which copy the whole record for the owner, carry them as they carry everything.

A proof leaves one day at a time, as a bundle (§6).

### 5.10 Readers

`show` lists an `anchor/v1` line on the day of its `at`, as it lists any line (a reader's own text: `anchor 6 days, root 3f1c…, timestamps pending`). `logbook anchor list` lists anchored days, each with its batch, the state of each proof and whether the anchored signature still stands. The Day reader and every reader of SPEC §3.2 are unchanged (open question 14). `doctor` names: a pending proof older than 7 days; an anchored signature that no longer stands (the day was signed again since, so the anchor proves the earlier reading); an entry with an `anchor` block whose `max_tier` is not 1, whose `write` is not empty, or that has expired; and, in a record with no recipients, the anchor lines lying plain.

## 6. Verification

### 6.1 The bundle: `anchor-proof/v1`

```
logbook anchor export DAY|--head --to NAME [--tier 1|1,2|1,2,3] [--lines ID,…] [--signature] [--attachments] [--out FILE]
```

One day, for one verifier. The verifier is a destination like any other: an entry of `policy/crossing.json` (`{"insurer": {"max_tier": 1, "write": []}}`), its ceiling, `--tier` and tier 3's double consent (ADR 0016 rule 3) as for every crossing. What the bundle shows:

- always: the page's pre-image, the leaf's pre-image (with the salt), the path and the final proofs of the day's latest anchor of its standing signature (or, naming it, of an earlier signature that was anchored). A day whose anchors are all pending is refused, naming the state: a pending proof proves nothing;
- the day's lines at or under the tier asked, not retracted and not a retraction, as a shared page selects them (RFC 0025), or only those `--lines` names, each a line id or a `seq` as `--confirm` takes them (RFC 0034 rule 4), a line above the tier asked being refused by name; a sealed line is shown opened, carrying `payload_open`, the `{payload, salt}` pre-image of its digest, in place of `payload_enc` (RFC 0029 §15);
- with `--signature`, the signature line;
- with `--attachments`, the files the shown lines point at, as plaintext: a sealed file goes in opened, so that it hashes to its name (SPEC §1.1, RFC 0005);
- with `--head` in place of a day, for an audit of the whole record (§6.5): the same bundle with `head.json`, the head leaf's pre-image `{"schema": "anchor-head/v1", "head", "salt", "seq"}`, in place of `page.json` and `leaf.json`, no lines and no signature, and `day` `"head"` in the manifest.

It is a zip with exactly these members, as RFC 0025's page is, and the same refusals on a receiver's side:

```
manifest.json            the table below
README.txt               §6.3 in words, for someone who has never heard of this program
page.json                the page digest's pre-image: {"day", "tz", "lines": [the page's line hashes]}, RFC 8785
leaf.json                the leaf's pre-image: {"schema": "anchor-leaf/v1", "page", "salt", "signature"}, RFC 8785
path.json                {"width": 512, "index": n, "path": [nine hashes, from the leaf's sibling up]}
proofs/top.bin           the 65 bytes whose SHA-256 is the root (§3.4)
proofs/top.bin.ots       the OpenTimestamps proof, final; its first operations append its nonce and hash
proofs/tsa.bin           the 48 bytes root ‖ nonce whose SHA-256 the authority stamped, when the batch has one
proofs/tsa.bin.tsr       the authority's response
proofs/tsa-chain.pem     the authority's certificates and their status as fetched with the token
lines.jsonl              the lines shown, verbatim; may be empty
signature.jsonl          the signature line, verbatim (with --signature)
attachments/<sha256>     the files of the lines shown (with --attachments)
```

Every hash in `page.json`, `leaf.json`, `head.json`, `path.json` and the manifest is 64 lowercase hex characters. A hash enters a SHA-256 pre-image as 32 raw bytes in the tree (§3.4) and as hex text everywhere else (SPEC §3, §3.3). `page.json`, `leaf.json`, `head.json` and `path.json` are RFC 8785 text with exactly the keys named here and nothing after it, not even a newline, so their bytes hash to the digests the steps compute; `top.bin` and `tsa.bin` are raw bytes.

The proof files are named for their targets so that the stock tools find them by the name alone. `top.bin.ots` is an OpenTimestamps detached timestamp whose file-hash operation is SHA-256 and whose digest is R, the SHA-256 of `top.bin`. The bundle carries no block header: the header is the one fact a verifier must take from a source of their own, never from the party making the claim.

`manifest.json`:

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"anchor-proof/v1"` | MUST | |
| `bundle_id` | uuid | MUST | the `anchor-export/v1` line the export appends carries the same |
| `to` | string | MUST | the verifier, by the entry's name |
| `day` | `YYYY-MM-DD` or `"head"` | MUST | as `page.json` has it; `"head"` for an audit bundle |
| `tz` | IANA name | MUST for a day | as `page.json` has it |
| `day_start` | `HH:MM` | MUST for a day | the record's `day_start` when the day was signed (RFC 0036). Not in any digest: the owner's statement of the day's boundary (§6.5) |
| `created` | RFC3339 UTC | MUST | |
| `root` | hex sha256 | MUST | |
| `shown` | object | MUST | `{ lines, held_back, signature, attachments }`: counts and a boolean |
| `files` | array | MUST | `{ path, sha256, bytes }` for every other member, in path order |

The manifest is not signed (open question 12): what the bundle proves does not depend on who handed it over, and a signature would tie every bundle to one key.

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"anchor-proof/v1 manifest","type":"object",
 "required":["schema","bundle_id","to","day","created","root","shown","files"],
 "properties":{
  "schema":{"const":"anchor-proof/v1"},
  "bundle_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
  "to":{"type":"string","minLength":1},
  "day":{"type":"string","pattern":"^([0-9]{4}-[0-9]{2}-[0-9]{2}|head)$"},
  "tz":{"type":"string","minLength":1},
  "day_start":{"type":"string","pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$"},
  "created":{"type":"string","pattern":"Z$"},
  "root":{"type":"string","pattern":"^[0-9a-f]{64}$"},
  "shown":{"type":"object","required":["lines","held_back","signature","attachments"],"properties":{
   "lines":{"type":"integer","minimum":0},"held_back":{"type":"integer","minimum":0},
   "signature":{"type":"boolean"},"attachments":{"type":"integer","minimum":0}},"additionalProperties":false},
  "files":{"type":"array","items":{"type":"object","required":["path","sha256","bytes"],"properties":{
   "path":{"type":"string","minLength":1},"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},
   "bytes":{"type":"integer","minimum":0}},"additionalProperties":false}}}}
```

Writing the bundle is a crossing, and the chain records it, as every crossing (ADR 0016 rule 4), in one line of its own, `anchor-export/v1`: `kind` `anchor-export`, `tier` 2 (a writer MUST NOT write another), `source` `logbook`, `at` when the bundle was written, `end` null. It is not a `crossing/v1` line, for §5.7's first reason: a tier-1 line would tell every member, and every orchestrator reading through the door, which day the owner proved and to whom, which is what §5.4 keeps at tier 2. It stays home under §5.9.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"anchor-export/v1"` | MUST | |
| `bundle_id` | uuid | MUST | the manifest's |
| `to` | string | MUST | the verifier's entry |
| `day` | `YYYY-MM-DD` or `"head"` | MUST | the day proved, or `"head"` for an audit |
| `anchor` | string | MUST | the id of the `anchor/v1` line whose proofs the bundle carries |
| `tiers` | array of integer | MUST | the tiers asked; empty for `"head"` |
| `counts` | object | MUST | the manifest's `shown`; all zero and `false` for `"head"` |
| `policy` | object | MUST | `{ file, max_tier, version }`: the ceiling in force and the entry's version (RFC 0036) |
| `logbook_head` | hex sha256 | MUST | the head before this line |
| `package_sha256` | hex sha256 | MUST | the digest of `manifest.json` |

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"anchor-export/v1","type":"object",
 "required":["schema","bundle_id","to","day","anchor","tiers","counts","policy","logbook_head","package_sha256"],
 "properties":{
  "schema":{"const":"anchor-export/v1"},
  "bundle_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
  "to":{"type":"string","minLength":1},
  "day":{"type":"string","pattern":"^([0-9]{4}-[0-9]{2}-[0-9]{2}|head)$"},
  "anchor":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
  "tiers":{"type":"array","items":{"enum":[1,2,3]}},
  "counts":{"type":"object"},
  "policy":{"type":"object","required":["file","max_tier","version"]},
  "logbook_head":{"type":"string","pattern":"^[0-9a-f]{64}$"},
  "package_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},
  "extra":{"type":"object"}}}
```

### 6.2 What a verifier needs

- the bundle;
- SHA-256 and an exact RFC 8785 serialiser in any language. A JSON library's sorted, compact output is not one: it lays numbers out differently (`19.0` where RFC 8785 writes `19`), and a line's hash then does not recompute. `page.json`, `leaf.json` and `head.json` are RFC 8785 text already, so their bytes hash with no serialiser at all; only the lines shown need one;
- for OpenTimestamps, any implementation of its format, or the format itself, which is short; and the 80-byte header of the block the proof names, from a source the verifier trusts (§4.1);
- for an authority's token, any CMS implementation (`openssl ts`) and a root certificate the verifier trusts for that authority.

Nothing from this project: no server of ours, no program of ours, no account anywhere. With a copy of Bitcoin's headers already at hand, no network at all. A verifier who has this program may run `logbook anchor verify BUNDLE [--headers FILE]`, which follows §6.3 with no network; on the owner's machine, `anchor verify` with no bundle checks the record's own anchor lines, their leaves, roots and proofs files, the same way.

### 6.3 The steps

1. **The bundle.** Every member is listed in `files` and hashes to its entry; nothing else is in the zip. (This checks the package, not the claim.)
2. **The page.** `page.json` has `day`, `tz` and `lines`, a list of 64-hex strings, and its `day` and `tz` are the manifest's. P = `sha256(canonical_json(page))`, which is the SHA-256 of the file's bytes.
3. **Each line shown.** For a line carrying `payload_open`: `sha256(canonical_json(payload_open))` equals `payload.digest`, and `payload_open.payload.schema` equals `payload.of`. Then, for every line, by SPEC §3: `content = canonical_json({at, end, tz, source, kind, tier, payload})` with `payload` as the line holds it (for a sealed line, the reference), and `h = sha256(prev + "|" + seq + "|" + hex(sha256(content)) + "|" + recorded_at)`. `h` equals the line's `hash`, and `h` is in `page.lines`. Each attachment hashes to its name, and a shown line names it: a line names a file when a reference of SPEC §1.1 (`{sha256, path, bytes, media_type}`) anywhere in its `payload`, or in `payload_open.payload`, carries the file's name as `sha256`. A file no shown line names is refused.
4. **The signature, when shown.** Its hash S is recomputed as in step 3; its `payload.schema` is `signed-day/v1`, `payload.day` is the page's `day`, `payload.page.sha256` is P, and `payload.page.lines` is the length of `page.lines`. When it is not shown, S is `leaf.json`'s `signature`, taken as an opaque value.
5. **The leaf.** `leaf.json`'s `schema` is `anchor-leaf/v1`, its `page` is P, its `signature` is S, its `salt` is 64 hex. L = `sha256(canonical_json(leaf))`.
6. **The path.** `path` is nine 64-hex digests; decode each to 32 bytes. With RFC 9162 §2.1.3.2, leaf index `index`, tree size `width`, inclusion path `path` and, as its leaf hash, `sha256(0x00 ‖ L)` (L the 32 raw bytes of step 5), compute R. R equals the manifest's `root`; `top.bin` is 65 bytes beginning `0x01` whose SHA-256 is R, and it is the pre-image of the path's last step.
7. **The time.**
   - *OpenTimestamps.* The proof starts from R (as the digest of `top.bin`); its first operations append the nonce and hash, and the rest lead to a Bitcoin attestation naming a height. The verifier takes that block's header from their source, checks that the proof's result is the header's Merkle root, and reads the header's time; T is that time plus two hours (§7.1). The stock client does this from `proofs/top.bin.ots` beside `proofs/top.bin` against a Bitcoin node it can reach; without one it prints the operations and the block's height, and the verifier compares the result with the header's Merkle root by hand *(to check)*.
   - *An authority.* The first 32 bytes of `tsa.bin` are R; the token's message imprint is SHA-256 over `tsa.bin`; its signature verifies under the certificate in `tsa-chain.pem`; the chain reaches a root the verifier trusts and was valid at `genTime` by the status kept beside it. T is `genTime`. `openssl ts -verify -data proofs/tsa.bin -in proofs/tsa.bin.tsr -CAfile <the root the verifier trusts> -untrusted proofs/tsa-chain.pem -attime <genTime, in epoch seconds> -crl_check` checks the imprint, the signature and the chain as of `genTime` against the CRL kept beside it; without `-attime` it judges an expired certificate by today's date *(to check)*.
8. **The conclusion.** The page labelled `day` in `tz`, with exactly the lines in `page.lines` in that order, existed before the block named was mined (as a bound, T), or by the authority's `genTime`; so did every line shown, byte for byte as hashed, and every attachment shown; and, when shown, the signature with its confirmed ids, dispositions, note and time.

### 6.4 What the verifier learns

| From | They learn |
|---|---|
| `page.json` | the day, the zone, how many lines the page held when signed, and the hash of each |
| the lines shown | everything in them, as for any line handed over; and, from their `seq`, how many lines the record held then |
| `leaf.json` | the salt of this day's leaf, which lets them check this day and no other; S, an opaque hash when the signature is not shown |
| `path.json` | nine hashes indistinguishable from random, the position (random) and the width (always 512): nothing about other days, nor how many there were |
| the proofs | T; the calendars or the authority the owner used; the Bitcoin block |
| the signature, when shown | the `owner_id` (a UUIDv7 in the reference, so the moment the record was made), the confirmed ids and dispositions, the note, the signing moment, and from `seq` how many lines the record held then. Ids are UUIDv7 where the writer followed SPEC §2's recommendation, and a UUIDv7 carries the millisecond it was made: the confirmed ids of hidden lines say when each was written |
| the manifest | the name the owner's policy gives them, `day_start`, the counts shown and held back |

### 6.5 Selective disclosure

A day is proved alone: its leaf has its own salt, and its path is made of hashes that open nothing. Within the day, the owner chooses among three depths:

- **The page only.** *A page of 23 lines for 2026-06-13 in Europe/Oslo existed by T.* Weak alone; the base of the other two.
- **The page and some lines.** The lines that answer the verifier's question, the boat's AIS positions and the owner's location fixes for the storm's hours, and nothing else: the guest's message on the same page stays a hash. Each line shown carries its `seq`, so the record's size is shown from this depth on.
- **The page, the lines and the signature.** Adds that the record holds a signature of the page, with its confirmed set, by the signing moment the signer stated. It shows the note, the confirmed ids and the `owner_id`.

Several days are several bundles. Two bundles from the same batch carry the same root, so a verifier holding both learns they were anchored together; the `owner_id` in a shown signature links bundles across batches. Nothing links a bundle to a day not disclosed.

What a hidden line still gives away, said plainly:

- **Its hash, and a guess.** A hidden line is on the page as its hash, `sha256(prev | seq | content hash | recorded_at)`. A sealed line's content hash covers a random 16-byte salt (SPEC §2), so it cannot be guessed. A tier-1 line is plain, and its content can be: a weather line made from a public station's observation, a fix at a place the verifier knows. A verifier who knows or guesses its `prev` and `seq` (often a neighbour on the page, since lines of one import are consecutive) and its `recorded_at` within seconds can confirm such a guess. Tier 1 is the tier that crosses by default; a line the owner would not have a verifier confirm belongs at tier 2. In a record that does not seal, every hidden line is in this position, whatever its tier. A hidden sealed line rests on its own 16-byte salt, which is out of reach of any search known today; a quantum search would still need 2^64 steps for each guess of its payload, which is why §3.3 gives the published leaves 32 bytes and not 16.
- **The confirmed set names ids, and ids are outside the hash** (SPEC §2). The page binds lines by hash; the signature's `confirmed` binds them by id. A verifier reads `confirmed` as the owner's statement about which ids they confirmed, bound to content only through the ids the shown lines carry, which the hash does not cover (open question 16).
- **The day's boundary is not in the page digest.** The digest binds the day and the zone, not `day_start` (RFC 0036's open question). The manifest states it; a verifier checking that a shown line's `at` falls on the day uses it as the owner's word.

**The whole record.** For an audit of everything, a court's expert given a keyless copy of the record, the owner discloses the head leaf's salt and path (`anchor export --head`). The expert follows steps 1, 6 and 7 with H = `sha256(canonical_json(head))` in L's place, then recomputes the chain of the keyless copy to `seq` without the key (the envelope and the sealed references are plain, SPEC §3) and requires the hash at `seq` to be `head`. The head leaf then shows that every line up to that head, as handed over, existed by T. Lines after it are not covered, and nothing shows there is no second record.

### 6.6 Years later

What must still hold for a proof to verify in twenty years: SHA-256 (collision resistance, so that the owner cannot hold two pages under one leaf; second-preimage resistance, so that nobody else can; its one-wayness, for the secrecy of other days); a copy of Bitcoin's headers or the authority's chain and status; and the specifications, which are public: SPEC (CC0), this RFC, RFC 8785, RFC 9162, the OpenTimestamps format, RFC 3161. The bundle's README states the steps in words, so that a verifier needs neither this repository nor this program (rule 9: nothing in the log needs the software to make sense).

Hashes age. Before SHA-256 weakens, a proof can be renewed: timestamp the proof file itself, and the data it covers, again under a stronger function, so that the old proof is shown to have existed while it was still sound. That is RFC 4998's evidence record, and a later RFC's (open question 13); this one keeps every proof file it receives, so that nothing renewal needs is lost.

## 7. Threat model

### 7.1 What an anchor proves

1. **Existence before the block, or the authority's word.** The value committed to existed before the block the proof names was mined, or before the authority signed its token. A header's time is the miner's, accepted by the network when it is after the median of the eleven blocks before it and less than two hours ahead of the nodes' clocks, so it may sit about two hours either side of the moment of mining, under an honest majority of miners. A verifier who needs a bound takes **T as the header's time plus two hours**, or the time of a later block they trust. An authority's `genTime` is that authority's assertion: the token proves that its key signed this value with this time.
2. **The page by T.** The list of line hashes under the page's `day` and `tz` existed by T, and with it the hashed content of every line on it. Every line shown is shown exactly as it was hashed; every attachment a shown line names by digest is that file. The label is the writer's: that a hidden hash is a line whose `at` falls on that day, and where the day begins, is the owner's word (§6.5).
3. **The signature by T,** when shown: a `signed-day/v1` line with this `subject`, `confirmed`, `dispositions`, `note` and `at` existed by T. Its `at` is the moment the signer stated, any moment from the day's start on (RFC 0034 amendment 2), and its `recorded_at` is the writer's clock; nothing outside the record checks either.
4. **The record before it by T.** Through the signature's `prev`, every line the record held at signing; through the head leaf, every line it held at anchoring. A verifier shown that stretch of the chain sees that its lines existed by T. This binds every hashed field of every line to that point; `id`, `payload_enc` and the stored form are not hashed, and a sealed line's words are bound only through `payload.digest`, which a verifier with the key checks and one without cannot.
5. **Binding under this root.** No other hashed byte verifies under this leaf and this root: a page, a line or a signature changed by one byte after T is not the one anchored. Fields outside the hash change without notice: `id`, `payload_enc`, the stored form. `confirmed` and `dispositions` name ids, so which content a confirmed id names is not bound (§6.5, open question 16). And the owner may hold other anchors of other versions (§7.2, item 6).

### 7.2 What it does not prove

1. **That the lines are true.** An anchor freezes what the sources said; it does not say they were right. A tracker drifts, a clock is wrong, GPS can be spoofed, and a ship's AIS position is the ship's own broadcast, which anyone can transmit. A photo's `at` is its camera's clock, a tracker's its device's; several sources on the owner's own devices agree as easily as one. Independence is of the devices and of who runs them, not of the lines: a source the owner does not run (a public weather station, someone else's AIS receiver) weighs more. Weighing sources is the verifier's business and the record's readers', not the anchor's.
2. **Who.** Not that the owner is a given person: `subject` is a random UUID, the signature is not signed with a key, and the sharing key (RFC 0025) is not in an anchor. Not that the person was where their phone was. Not that the owner signed: an orchestrator the owner allowed `sign_day` writes the same bytes (RFC 0034 amendment 3). Not that the owner made the anchor: anyone who holds the lines can anchor them under a salt of their own, which proves only that they held them by then.
3. **When it was recorded.** An anchor is an upper bound only. A page fabricated in the time between the day and T verifies as well as one recorded as it happened. Anchoring soon after signing shortens that window; it never closes it, and a weekly batch leaves a week.
4. **Completeness.** That nothing was left out before signing. The page binds what was on it, not what was not: a source not imported, a line the owner never wrote.
5. **That the shown lines are the whole story.** The owner picks what to show. A hidden hash may be a line that contradicts a shown one. A retraction or correction written after signing is not on the page (RFC 0034) and is not in the proof; a line retracted before signing is on the page as a hash. A verifier sees only how many lines were held back.
6. **That there is one version.** Salted commitments are unlinkable on purpose, so the owner could have kept two versions of a day, anchored both and shown either. Two versions may be two records, or one chain in which a corrected page was signed again and both signatures anchored; a verifier shown one bundle cannot tell. Only a verifier shown the whole chain sees a fork, and nothing shows them there is no second record.
7. **That the anchored signature still stands.** The owner may have signed the day again since, or retracted the signature (RFC 0003); the anchor proves the reading it anchored.
8. **The times inside.** A line's `at` is its source's claim. The anchor bounds when the record held the claim, not when the thing happened.
9. **Anything, from a pending proof or a borrowed header.** A calendar's pending proof is its promise, and a calendar can lie in one. A header the claimant supplies proves nothing: a proof is as strong as the verifier's own source for the header, and a proof naming a block that source does not have (reorganised away, forged, or a source behind) has no time.
10. **Forever.** A proof holds while SHA-256 holds, while Bitcoin's chain back to that block is not rewritten (for a block months deep, that would cost more work than the network has done since), or while the authority's key was not stolen before the proof was renewed.

### 7.3 Who learns what

| Who | Holds | Learns |
|---|---|---|
| An observer of Bitcoin | the chain | nothing of the owner: their root is not on it |
| A calendar or authority | the root, its arrival time, the sender's address (and an account, at a qualified authority) | that someone at that address anchored something then; over time, the cadence (§8); and, when a verifier checking online asks about the root, that it is being checked; never what, nor how many days |
| Anyone who holds a bundle passed on | the bundle | everything §6.4 lists, and from the proofs the block that holds it and the calendar it went through, not the sender's address; they can present it to anyone, since nothing binds a bundle to the verifier it names (open question 12) |
| A member of the circle | the day's crossed lines and its signature | not that the day was anchored, nor that a proof of it was exported: both lines stay home (§5.9, §6.1). Nothing they hold opens a blinded value or a root |
| A verifier | a bundle | §6.4 |
| Someone with the files, no key | every envelope, tier-1 lines plain | when the owner anchored and exported proofs (the envelopes of `anchor` and `anchor-export` lines), and, beside the tier-1 signatures, a guess at which days each batch held; how many only to within about forty (§5.3, `pad`); not the salts, not the root. In a record with no recipients, where `anchor` ran only with `--plain`, the salts and proofs are plain and they can make bundles |
| Someone with the files and the key | everything | everything the owner can prove; they can make bundles, as they can read every line |

### 7.4 Failures

- **A calendar loses or never upgrades a pending proof.** The others in the run may; `doctor` names a proof pending a week; the owner anchors those days again.
- **A calendar or an authority closes.** A final proof does not need it again. A pending one dies with it; hence two calendars at least.
- **An authority lies about time.** Possible, and the reason the authority is the fallback and a second proof, not the default.
- **The proof file is lost.** It is an attachment: `verify` reports it missing and does not fail (SPEC §1.1), and the anchor then proves nothing. `doctor` names it.
- **The authority's chain or status was not kept.** The token cannot be checked once its certificates expire; `anchor` keeps them with the token, in the proofs file (§5.3).
- **The key is lost.** The salts are sealed with the line, so they are as recoverable as every tier-2 line: RFC 0029 §6.1 requires a printed recovery identity before a record seals anything. A record whose every recipient is lost keeps the anchors' roots and loses the power to prove them.
- **The random source fails.** Nothing holds (§3.6); the same is true of sealing.
- **A Bitcoin block is reorganised away.** A proof upgraded against a block later reorganised away names a block no header source has. `anchor --upgrade` asks the calendar again and records the proof to the block that stands; `anchor verify` with headers reports how deep the block is.

## 8. Linkability over time

The root says nothing (§3.6). The sending says something, to the destinations and to anyone watching the network between: that this address talked to a calendar at this moment. Over months that is a profile:

- **Cadence.** Anchors every evening at 21:40 say that someone signs their days nightly, and in which time zone; a run minutes after each signature puts the signing moment, which members hold, beside the moment a calendar holds; a gap of nine days followed by one batch from a harbour's network says that someone was out of reach for nine days, and roughly where they came ashore.
- **Count.** With a fixed width, a batch never says how many days it holds. Without batching, the number of submissions would be the number of signed days.
- **Address.** Where the owner was, coarsely, at each submission.
- **Account.** At a qualified authority, every request under the owner's name.

What limits it, each the owner's choice and none on by default but the first:

- **Fixed width** (§3.4): the count of days is never in a root. Always on.
- **Batching.** Anchor a week or a month at once, on a later day than the signing; one submission per batch.
- **Random delay.** On a schedule, a uniform wait of 0 to 12 hours before sending (§5.8), so the time of day says nothing.
- **Cover batches.** On a schedule, a batch every week whether or not a day was signed: a batch of fill alone, indistinguishable from any other, and recorded as a line with an empty `days` like any other. The cadence then says only that the owner has a schedule.
- **Where it is sent from.** The record's home (ADR 0022) rather than wherever the owner is: `anchor` runs on the home, so a phone in a harbour sends nothing. A proxy (`via`, open question 11) hides the home's address too.
- **Fewer observers.** Each destination is one more observer; two calendars are enough for redundancy. Each receives the root under its own nonce (§3.6), so two of them comparing notes cannot tell that they hold the same root, and an authority that knows the owner's name cannot use it to name the calendars' anonymous submission.
- **No account-bound authority** unless the token's legal weight is the point.

Aggregation across people helps too: several records anchoring one root together (§9) hide each owner's cadence inside the group's.

## 9. Co-signing later

Two logbooks may come to sign the same day: Ines and her brother Ola, aboard the same boat, each signing their own page of 2026-06-13, and each saying of the other's that it is the same day. How that is written, and with which key, is RFC 0025's amendment the owner calls A5, not written yet. This RFC leaves it every road it needs:

- **A leaf is 32 opaque bytes to the tree.** Leaves are typed by their pre-image's `schema`; a co-signature's leaf (`anchor-cosign/v1`, say, over both signatures' hashes and both pages, salted) joins a batch with no change to §3.4.
- **A batch may hold a leaf another record made.** A leaf reveals nothing (§3.6), so Ola can hand Ines a leaf, she puts it at a random position, sends the root, and hands back the root, the path and the proof. Neither learns the other's salt; one root proves both. `anchor/v1`'s payload is additive, so A5 can add a field for a leaf the record holds but did not make, and a line without it has none.
- **The bundle checks any leaf under a root.** A verifier given both bundles checks each, and sees one root.
- **Nothing here ties a root to one `owner_id`, one record or one key.** A co-signature made with RFC 0025's sharing keys is a line in each record whose hash either can anchor like any other.

## 10. Example (synthetic)

Ines Nordmann sailed *Solvind* the week of 8 June 2026 and signed each evening; she did not sign Sunday the 14th. Her `policy/crossing.json` holds the two entries of §5.7. On Sunday evening:

```
$ logbook anchor --since 2026-06-08 --until 2026-06-14 --to timestamps --dry-run
2026-06-14 is not signed: sign it first, or leave it out
$ logbook anchor --since 2026-06-08 --until 2026-06-13 --to timestamps
anchor: 6 days and the head in a batch of 512; 1 root to timestamps (3 calendars)
  2026-06-11: the signature carries a note; a proof that shows the signature shows the note
  timestamps: 3 calendars accepted the root, each under its own nonce; pending
  appended #48213 anchor/v1 (tier 2)
```

The line opened, as a reader with the key sees it (on disk the payload is sealed, SPEC §2); hashes and salts are placeholders:

```json
{"at":"2026-06-14T19:52:10Z","end":null,"tz":"Europe/Oslo","source":"logbook","kind":"anchor","tier":2,
 "payload":{"schema":"anchor/v1",
  "batch":{"width":512,"seed":"<64 hex>"},
  "days":[{"day":"2026-06-08","tz":"Europe/Oslo","day_start":"00:00","signature":"019cadd3-6bc0-7dcd-9133-00000000a108",
           "signature_hash":"<the hash of the signature of 2026-06-08>","page":"<its page.sha256>",
           "salt":"<64 hex>","index":311},
          {"day":"2026-06-13","tz":"Europe/Oslo","day_start":"00:00","signature":"019cadd3-6bc0-7dcd-9133-00000000a113",
           "signature_hash":"<the hash of the signature of 2026-06-13>","page":"<its page.sha256>",
           "salt":"<64 hex>","index":42}],
  "head":{"seq":48212,"hash":"<the head>","salt":"<64 hex>","index":187},
  "root":"<the root>",
  "proofs":[{"destination":"timestamps","protocol":"opentimestamps",
             "endpoints":["https://ots-a.example.org","https://ots-b.example.org","https://ots-c.example.org"],
             "state":"pending"}],
  "file":{"sha256":"<64 hex>","path":"attachments/<64 hex>","bytes":16384,"media_type":"application/json"},
  "policy":{"file":"policy/crossing.json","versions":{"timestamps":"<64 hex>"}},
  "pad":"000…"}}
```

(`days` holds six entries; two are shown.) The next morning `anchor --upgrade --headers ~/bitcoin-headers.bin`, a copy of the headers Ines keeps, finds two calendars' proofs final, checks the block, and appends the line again with `"state":"final"`, a new proofs file, `"attested":{"chain":"bitcoin","height":961234,"time":"2026-06-14T22:47:13Z"}` (invented numbers) and `"supersedes"` naming #48213's id.

In 2029 the marina's insurer asks whether *Solvind* was at sea on the night of 13 June 2026, when a storm damaged the boats left in the harbour. Ines adds `{"insurer": {"max_tier": 1, "write": []}}` to her policy and runs:

```
$ logbook anchor export 2026-06-13 --to insurer --lines 47731,47732,47790,47791 --out solvind-2026-06-13.zip
anchor-proof/v1: 2026-06-13, 4 lines shown, 19 held back, no signature; root anchored 2026-06-14 (bitcoin)
  appended #61004 anchor-export/v1 (insurer, tier 2)
```

The line it appended (opened; placeholders as before) and the bundle's `manifest.json`:

```json
{"at":"2029-03-02T10:15:00Z","end":null,"tz":"Europe/Oslo","source":"logbook","kind":"anchor-export","tier":2,
 "payload":{"schema":"anchor-export/v1","bundle_id":"019cadd3-6bc0-7dcd-9133-00000000a201","to":"insurer",
  "day":"2026-06-13","anchor":"019cadd3-6bc0-7dcd-9133-00000000a150","tiers":[1],
  "counts":{"lines":4,"held_back":19,"signature":false,"attachments":0},
  "policy":{"file":"policy/crossing.json","max_tier":1,"version":"<64 hex>"},
  "logbook_head":"<the head before this line>","package_sha256":"<the digest of manifest.json>"}}
```

```json
{"schema":"anchor-proof/v1","bundle_id":"019cadd3-6bc0-7dcd-9133-00000000a201","to":"insurer",
 "day":"2026-06-13","tz":"Europe/Oslo","day_start":"00:00","created":"2029-03-02T10:15:00Z","root":"<the root>",
 "shown":{"lines":4,"held_back":19,"signature":false,"attachments":0},
 "files":[{"path":"README.txt","sha256":"<64 hex>","bytes":5120},
          {"path":"leaf.json","sha256":"<64 hex>","bytes":228},
          {"path":"lines.jsonl","sha256":"<64 hex>","bytes":2310},
          {"path":"page.json","sha256":"<64 hex>","bytes":1556},
          {"path":"path.json","sha256":"<64 hex>","bytes":641},
          {"path":"proofs/top.bin","sha256":"<64 hex>","bytes":65},
          {"path":"proofs/top.bin.ots","sha256":"<64 hex>","bytes":1843}]}
```

The insurer's assessor opens the zip on a laptop with no network, recomputes the four AIS and location lines, the page of 23 hashes, the leaf and the path, and checks the OpenTimestamps proof against the header of block 961234 from a copy of Bitcoin's headers the firm keeps. They learn that four lines with these `at`s and these positions, and a page labelled 13 June 2026, Europe/Oslo, listing them among 23, existed in this form before block 961234 was mined, whose header says 00:47 Oslo time on 15 June: no later, taking the header's time plus two hours, than about 02:47 Oslo time on 15 June 2026. That the page is Ines's, that the vessel is *Solvind* and that the positions are true is not in the proof: the first is Ines's word, the second the MMSI in the lines against a registry, the third the sources' agreement, weighed by the assessor. A page written on the 14th and dated the 13th would verify the same. They do not learn what the other nineteen lines were, which other days she anchored, or what her note of the 11th said.

## 11. What changes when adopted, and what does not

**Changes**, each in the change that implements it:

- `rfcs/README.md` lists `anchor/v1`, `anchor-export/v1`, `anchor-proofs/v1` and `anchor-proof/v1` among the drafts; the SPEC §4 table gains `anchor/v1` and `anchor-export/v1` in its tier-2 row (MUST) when the profiles are adopted, as every profile's row is added. Both are new profiles, not among RFC 0031's freezes: their schemas may change while this RFC is a draft, and they freeze only by RFC 0031's process.
- `policy/crossing.json` entries may carry an `anchor` block (ADR 0016's file, one key more), and `doctor` checks it (§5.10).
- `export crossing`, `share day`, `export trip-bundle`, `export vault`, `export site` and the MCP door leave `anchor` and `anchor-export` lines home (§5.9) and refuse an entry with an `anchor` block (§5.7): RFC 0005, RFC 0025 and RFC 0030 each gain one sentence.
- RFC 0011 rule 5 reads: readers that count what left the record join `crossing`, `anchor` and `anchor-export` lines; ADR 0016 rule 4 gains the sentence that an anchor's crossing is recorded by its `anchor/v1` line and a proof's by its `anchor-export/v1` line (§5.7, §6.1).
- `policy/crossing.json`'s reader accepts the `anchor` block and checks it as §5.7 says; the `write` check stays as it is, since an empty list names no tool.
- New commands: `anchor`, `anchor --upgrade`, `anchor --give-up`, `anchor list`, `anchor export`, `anchor verify`; the close runs `anchor` only under an entry's `schedule`. An extra for OpenTimestamps and RFC 3161 parsing (the ASN.1 of a token), named when the code lands, never needed by anything else.
- `docs/signed-day.md`, `docs/crossing.md`, `docs/settings.md`, `docs/schedule.md`, `docs/doctor.md` and `SECURITY.md` say so, the last with the calendar, the authority and the public observer in its threat model; a new `docs/anchor.md` holds the verifier's steps in the README's words.
- `tests/test_no_network.py` holds `anchor verify`, `anchor list` and `anchor export` to no network; `anchor` and `anchor --upgrade` open connections only to the endpoints of the entries they were given, which a test with the network refused shows.

**Does not change**: the envelope, the canonical form and the hash; `signed-day/v1` and every line already written; the readers of SPEC §3.2 and their JSON; the conformance samples; any adapter; the network on any default path, which stays shut; a record that never anchors, which reads and writes as before.

**Compatibility.** Additive throughout. A reader that does not know `anchor/v1` keeps the line and shows it as an unknown kind (SPEC §5: a reader MUST NOT fail on a payload it cannot interpret), and `verify` checks its chain like any line's. An implementation without this RFC never writes one; a record that holds one is valid to it. The proof files are attachments: `verify` reports one missing and does not fail (SPEC §1.1). A crossing written by an implementation without §5.9 would carry anchor lines when asked for tier 2, which is why §5.9 is a rule of every exporter and not of this command.

## 12. Facts from memory

This draft was written without consulting the services' current documentation. Before it is adopted, these are to be checked against it, and the text corrected where they are wrong: the number and operators of the public OpenTimestamps calendars, the usual delay to a final proof, the independent implementations of the format and the age of the oldest proofs that still verify, what the stock client does without a Bitcoin node, whether it finds a proof's target by its name, and that it blinds a digest with a nonce before sending it (§3.6, §4.1, §6.3); which RFC 3161 authorities answer free of charge, how eIDAS's Art. 41 applies in Norway through the EEA, and how `openssl ts -verify` judges an expired chain (`-attime`) and which status it reads (a CRL, not an OCSP answer) (§4.2, §6.3); whether Rekor's current version still signs a time with an entry, and what its public instance promises about keeping entries (§4.3); the newspaper service of §4.4; and the licence of the OpenTimestamps reference client (open question 20). Nothing in §3, §5 or §6 depends on these beyond the names of the protocols.

## 13. Open questions

Each with the answer this draft recommends.

1. **What the leaf commits to.** The signature's hash and its page digest, salted (§3.3), or the content hash alone, which shows a verifier no `seq` and no `recorded_at`? *Recommended: the hash and the page.* The chain before the signature is pinned only through `prev`, and the page in the leaf is what lets a proof leave the note out.
2. **Salt length.** 32 bytes, or 16 as a sealed line's? *Recommended: 32.* A root is public forever; a sealed line's digest is not.
3. **Batch width.** 512 fixed, or the next power of two above the days in the run? *Recommended: 512 fixed.* A leap year fits; a path is nine hashes; and a width that varies would put the count of days back into every proof.
4. **The head leaf.** On by default, or only when asked? *Recommended: on.* It costs one leaf and gives the whole record a witness, signed days or not; disclosing it is a separate, deliberate export.
5. **Tier.** 2, 3, or 1 without the salts? *Recommended: 2, as §5.4 argues,* with the kind held home by every export (§5.9). Splitting the salts into a second line would make two lines that must never be separated.
6. **No `crossing/v1` line.** The anchor line records the submission (§5.7) and a tier-2 `anchor-export/v1` line records a proof leaving (§6.1); neither appends a tier-1 crossing line, as every other crossing does. *Recommended: yes, both at tier 2.* A tier-1 line would tell every member, and every orchestrator at the door, the owner's anchoring cadence and which day they proved to whom; the audit loses nothing if it reads three kinds. The cost is a second road for the record of a crossing, which RFC 0011 and ADR 0016 then name.
7. **The protocol.** OpenTimestamps by default and an authority as fallback and optional second proof (§4.6)? *Recommended: yes;* Rekor not supported.
8. **Shipped endpoints.** Should the code or `init` carry a default list of calendars? *Recommended: no.* The owner writes the entry from the docs; a default would be a network destination nobody chose, and the list changes faster than releases.
9. **Schedule.** By hand only, with `schedule` on the entry as the one way to automate (§5.8)? *Recommended: yes,* weekly at most, with the random delay and cover batches always on when a schedule is set.
10. **Cover batches.** Always on a schedule, or a separate switch? *Recommended: always on a schedule.* A schedule without cover reveals the signing habit it was meant to hide.
11. **A proxy.** A `via` key on the entry (a SOCKS URL, typically a local Tor), no default? *Recommended: yes, as an option.* It is the only way to hide the home's address from the calendars, and it is one more moving part, so it stays the owner's choice.
12. **A signed bundle.** Should `anchor export` sign the manifest with the sharing key (RFC 0025)? *Recommended: no by default, `--sign` to add it.* A verifier who already holds the owner's key gains a statement of who handed it over; every other verifier gains a key that links all the owner's bundles.
13. **Renewal.** Should this RFC define renewing proofs before SHA-256 weakens? *Recommended: no, a later RFC,* in the shape of RFC 4998; this one keeps every proof file so that nothing renewal needs is lost.
14. **The Day reader.** Should `day` say *anchored* in its header and JSON? *Recommended: not now.* The Day's JSON is compared between implementations (SPEC §6.1) and an addition is a SPEC change; `anchor list` answers the question without one.
15. **The name.** `anchor` is also the World page's word for a named place and what a boat does in a bay. *Recommended: keep `anchor`* for the command and the kind; the World page's use is a label, and can become *places* if the two are ever confused.
16. **The confirmed set and ids.** The signature confirms lines by id, outside the hash (§6.5). Should RFC 0034 gain an optional `confirmed_hashes`, so that a proof binds what was confirmed by content? *Recommended: yes, as an amendment to RFC 0034,* additive and optional; anchors do not wait for it.
17. **A proof that never upgrades.** After how long is a pending proof given up, and by whom? *Recommended: `doctor` names it after 7 days; the owner gives it up by hand and anchors again.* Calendars upgrade within hours, so a week means it is lost; giving up stays a human act because it writes a line.
18. **A key inside the leaf.** Should a day leaf also carry an Ed25519 signature over the signature's hash under the record's sharing key (RFC 0025), so that an anchor says *the holder of this key had this day by T*? *Recommended: no.* Every bundle would then carry a signature that anyone holding the owner's public key, every member of the circle, can test, linking every proof to the owner; and the key says nothing to a stranger who does not already know whose it is. A key's statement about a day belongs to co-signing (§9), where it is the point.
19. **A grown page.** Refuse to anchor a signature whose page has grown since signing, or anchor it with a warning? *Recommended: refuse, with `--as-signed` to anchor the earlier reading* (§5.5 step 3). The owner most likely wants the latest reading anchored, and the other is a choice worth typing.
20. **The OpenTimestamps code.** Depend on the project's own client library, shell out to its command, or implement the format here? *Recommended: implement it here,* from its documentation and its test vectors, in the extra §11 names: the format is a few hundred lines to parse and the calendar protocol is two HTTP requests, the reference client's licence is to be checked against this repository's Apache-2.0 *(to check)*, and a verifier written from the format alone is what a second implementation will need anyway.

## Notes

- **Why not publish the signature's hash and be done.** Because every member a day crossed to holds that hash already, and a public hash they can search for is a public record of which days the owner made provable (§3.2). The salt costs 32 bytes per day and removes that.
- **Why one root per run and not one per day.** Cost and cadence would grow with the days, and every submission would say a day was signed. One root says neither.
- **Why fill instead of a smaller tree.** A tree as small as the run tells every verifier how many days were anchored with theirs. Fill makes a batch of one and a batch of three hundred look the same to everyone but the owner, for the price of hashes nobody stores.
- **Why this is not a share.** VISION.md says *no public-by-default; every share names a person*. A root is not a share: it carries nothing of the record (§3.6), and it is sent only when the owner types `anchor`. What carries something, a proof bundle, names its verifier in the policy and is written into the chain like every page.
- **The 1991 chain and the 2008 one.** LORE.md: the record uses Haber and Stornetta's chain, one person's, needing no one else's agreement; Bitcoin put the same chain in public. An anchor keeps it that way. The record stays private and complete without a witness; the public chain is used only as a witness to one 32-byte value, the way the service built on their work prints one digest where many will see it.
- **Why no server of ours.** A project server would be a party a verifier has to trust, a lifetime the proof depends on, and an observer of every owner's cadence. Public calendars and Bitcoin's headers outlive any project; a proof that needs none of our servers needs none of us.
- **Why the bundle carries `top.bin`.** Stock tools timestamp files, not roots. The 65 bytes whose hash is the root let a verifier use them unchanged, and are the last step of the path in any case.
- **Why the proof stays home inside the line, not beside the record.** A file next to the record would be lost by the first copy that misses it; inside the record it is backed up, sealed and verified with everything else (attachments are record, not cache: SPEC §1.1).
