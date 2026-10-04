# The freeze

*4 October 2026 · to whoever is building on Logbook*

You may be writing an adapter for a service we have never heard of, or a notebook that reads the folder on a Sunday, or the second implementation in a language we do not know. Whichever it is, you have been building on drafts. Every payload profile in `rfcs/` says *draft* at the top, and a draft may change under you. This letter says which ones will not.

**What a freeze gives you.** A thing that holds still. From the day RFC 0031 merges, nineteen profiles are frozen: `location`, `photo`, `event`, `message`, `note`, `transcript`, `call`, `mail`, `task`, `flight`, `health-sample`, `listen`, `transaction`, `keeper`, `weather`, `story`, `received`, `resolution` and `retraction`, all at `v1`. A frozen profile may gain a field. It will not lose one, rename one or change one's type, and the readers that read it will keep every key of their JSON with the meaning it has today. Each one gets a conformance fixture, one synthetic line with its hash and what the readers make of it, that both implementations must pass on every push. The fixture is the promise; a change that breaks it fails a job before it reaches you.

**What it costs.** Some profiles you may have wanted frozen are parked instead: `browse`, `watch`, `highlight`, `voice-memo`, `crossing`, the trip line (about to be called `journey`), and the one line a migration writes. The rule that sorted them is plain and we applied it to the code, not to our wishes: a profile is frozen when a reader, a rollup or a derive command of the reference reads it. Those seven are written, some of them in great numbers, and read by nothing yet except the row `show` prints and the words `search` indexes. A schema nobody reads is a schema nobody has tested against a real day, and we would rather tell you it may change than promise a shape we have not had to live with. Adapters keep writing them. Nothing in your record is touched. They are simply not in the v1.0 promise.

Two profiles are going away: `commitment/v1` and its close. Nothing ever wrote them and nothing ever read them. A record that holds one still verifies, since the chain does not care what a payload calls itself, and `show` still prints it.

**What we ask.** If you read a parked profile, say so. Open an issue and tell us which one and what you do with it. That is exactly how a parked profile gets frozen: a reader, a fixture in both implementations, one amendment to the RFC. You reading it is the first of the three, and the one we cannot do for you. If you are the one who wrote the reader, send it.

**The date.** The frozen set does not change before v1.0, and it does not shrink after. v1.0 is the roadmap's last phase; it has no date, and we are not going to invent one for this letter. What we can say is the order: the two deletions, then the rename, then the fixtures on our side, then on the TypeScript side, then the spec's wording. When the five have merged, this letter gets one more paragraph saying so, and nothing else in it changes.

The record holds still by construction. From now on, for these nineteen, so does the shape of what is in it.

— bighydro
