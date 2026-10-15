# GitHub

What happened on GitHub, one line per act: a commit, an issue or a pull request created, closed or
merged, a review submitted, a comment left. `logbook sync github` reads them from GitHub's API,
read-only; `logbook add github-export` reads an old project's clone, or the account export GitHub
makes, and adds what the API cannot give back: each version of a README or a doc, so the ideas an old
project wrote down have a first-said date. Both write the same line for the same act, so a commit (by
its hash) and an issue (by its number) read both ways are one line. Every line is `event/v1`
(RFC 0009): tier 1 from a public repository, tier 2 from a private one ([below](#the-text-and-the-tier)).

```bash
export LOGBOOK_GITHUB_TOKEN=github_pat_...                  # a fine-grained token, read-only: a password
export LOGBOOK_GITHUB_REPOS='ines-example/sailplan, ines-example/harbour-notes'   # or --all
logbook sync github --dry-run                               # count, write nothing
logbook sync github                                         # then four times a day with the schedule
logbook sync github --since 2026-01-01T00:00:00Z            # every repo from then, once
logbook add github-export ~/code/oldboat                    # an old project's clone: its commits and its docs
logbook add github-export ~/code/sailplan --public          # a clone of a public repository: tier 1
logbook add github-export ~/Downloads/github-export         # GitHub's account export, unpacked
```

## The token and the repos

On GitHub, *Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate
new token*: the repositories it may read (all of yours, or the ones you choose) and, under *Repository
permissions*, **Contents**, **Issues**, **Pull requests** and **Metadata** set to *Read-only*, nothing
else. Keep it in `LOGBOOK_GITHUB_TOKEN` in your shell profile, never in a file of the record. The sync
sends `GET` and nothing else, and a test holds it to that.

`LOGBOOK_GITHUB_REPOS` names the repos, `owner/name`, comma- or space-separated, or the links GitHub
copies (`https://<host>/<owner>/<name>.git`, or the SSH form `git@<host>:<owner>/<name>.git`). `--all` reads
every repo the token sees, less the forks, which are someone else's history (name a fork to read it).
`LOGBOOK_GITHUB_URL` is another address for the API, a GitHub Enterprise Server's
`https://<host>/api/v3`: https, or http to this machine only. A repo the token cannot read is said
on one line, the others are read, the run exits 1 and the watermark stays.

## Who acted

Each line names who acted under `extra.actor`: `login`, `id`, `type` (`User`, `Bot`) and, for a
commit, the author's `name`, and marks them `owner` or `other`. **You are the handles in
`policy/owner.json`**:

```json
{"names": ["Ines Nordmann"], "emails": ["ines.nordmann@example.org"], "phones": [], "handles": ["ines-example"]}
```

`ines-example`, `@ines-example` and `github:ines-example` are one login, case aside. With no handle
listed, the sync takes the token's own user for you and says so; list yours before the first run that
writes, since a line is never rewritten. A commit whose author GitHub links to no account is yours when
its address is one of yours (`owner.json`'s emails, `owner_emails` in `logbook.json`) or its author's
name one of your names. The address is read for that, and to find the login in a GitHub noreply
address, and is never written.

Everyone else is `other`, and a person's login is the line's `organizer`, `{"kind": "handle",
"value": "github:ola-example"}` (a bot's never is): a handle is a name source as a phone number is, so
`logbook people review` lists `github:ola-example` as an observed person, named by the name his commits
give, and proposes him to the person of that name ([People](../people.md)). Your own handles are never
listed, however late you add them to `owner.json`.

## The text, and the tier

`event/v1` has `notes`, "the description body" (RFC 0009), so the text is kept in full, verbatim: a
commit's message, an issue's or a pull request's body, a review's and a comment's text. A README's or a
doc's text is never kept: a version is its digest, its length and its word count, as a Notion page is.

The tier is where a line may travel (tier 1 crosses by default, ADR 0016), never who wrote it, so it
follows **where the words were written**:

- **A public repository's lines are tier 1**, whoever wrote the words: Ola's comment is tier 1 as yours
  is. SPEC §4 and RFC 0009 give `event/v1` tier 1 ("`tier` SHOULD be 1"), and the profile says it
  outright, "an entry whose notes carry someone else's words is still tier 1 by default". Anyone can
  read those words on GitHub already.
- **A private repository's lines are tier 2**, every one of them: a commit's message, an issue's text,
  a review, other people's comments, a doc's version, and a pull request's created, closed and merged
  lines (and the agent mark they carry). Its text was written for the people the repository is shared
  with, so it does not go wherever tier 1 crosses; it crosses at tier 2, when you ask for it, and in a
  record that names recipients it is sealed at rest (RFC 0029). The line says why:
  `extra.tier_reason` is `private repository`. SPEC §4 lets a producer write a higher tier than a
  SHOULD default "for a reason it states", and `event/v1`'s tier is a SHOULD, not a MUST.

**Which repositories are public.** `sync github` takes GitHub's word at each run: the repository as the
API answers it (`GET /repos/{repo}`, or the `--all` list) carries `private` and `visibility`, and a
repository is public only when what it carries says so (`private` false, `visibility` `public`) and
nothing in it says otherwise. An internal repository (GitHub Enterprise) is private, and so is one whose
answer carries no mark (`tier_reason` `repository visibility not known`; the run says so). A repository you make public or private is read at its new tier from the next run on; the lines
already written stay as they are, since a line is never rewritten. `add github-export` reads no
network: GitHub's account export marks each repository it lists, and that mark decides. A clone says
nothing of its visibility, and neither does an export's repository without a mark or an issue of a
repository the export does not list, so their lines are tier 2 (`repository visibility not known`),
and the run says so, unless you pass `--public` for that run. `--public` never makes a repository the
export marks private tier 1, and it decides only the lines not yet in the record: pass it the first
time (`--dry-run` says what the run would do), since adding the same clone again writes nothing.

**The same act read twice.** A line is never rewritten and never written twice: the record knows an act
by its `raw_id` whatever its tier, so the first road to write a commit or an issue decides its tier.
Lines written before private repositories were tier 2 stay at tier 1, and a sync that reads one of
them again writes nothing; a clone added before the sync (tier 2) keeps its commits at tier 2 when the
API later says the repository is public, and the other way round. A commit in two repositories, a
public one and a private one, is one line (`commit/<sha>`), at the tier of the repository read first.

**In a record that seals** (RFC 0029, `recipients` in `logbook.json`), a tier 2 line is sealed at rest
and its `raw_id` blinded, so only the identity can see that the record holds an act sealed. Since the
same act may come at tier 1 or 2, `sync github` and `add github-export` need the identity to write
anything there, a tier 1 line too: without it they refuse on one sentence, before asking GitHub
anything, rather than write a sealed act a second time, plain. `--dry-run` writes nothing and needs none.

## What a line holds

| On the line | What it holds |
|---|---|
| `at` | when the act happened: a commit's author date, an issue's creation, its close, a merge, a review's submission, a comment's creation |
| `raw_id` | `commit/<sha>` (one commit, one line, whichever repo); `<repo>/issues/<n>/created`, `<repo>/pull/<n>/created`, `<repo>/pull/<n>/merged`, `<repo>/issues/<n>/closed@<when>` (closed, reopened and closed again is a second line), `<repo>/pull/<n>/reviews/<id>`, `<repo>/issues/comments/<id>`, `<repo>/pulls/comments/<id>` (on a line of the diff), `<repo>/file/<path>@<blob>` (a doc's version); `<repo>` in lower case |
| `title` | a commit's first line; an issue's or a pull request's title, also on its reviews and comments; a doc's path |
| `notes` | the message, the body, the review or the comment, in full; never a doc's text |
| `calendar` | `{"id": "github", "name": "GitHub"}` for every repo, so two repos' acts are never folded into one |
| `modified_at` | the source's own clock: a commit's committer date, an item's last update; the watermark |
| `organizer` | the person who acted, as a handle ref; absent for a bot or an unlinked author |
| `extra.action` | `committed`, `created`, `closed`, `merged`, `reviewed`, `commented`, `revised` (a doc's version) |
| `extra.repo` | `owner/name` as GitHub spells it |
| `extra.commit`, `extra.issue`, `extra.pull`, `extra.review`, `extra.comment` | what the act was done to, by reference: `{sha, url}`, `{number, url}`, `{id, state, url}`, `{id, url}`; never a copy |
| `extra.branch`, `extra.files` | a commit's branch (the default one) and how many files it changed |
| `extra.files`, `extra.commits`, `extra.base`, `extra.head` | a merge: what it changed, from which branch into which |
| `extra.labels`, `extra.path` | an issue's labels; the file an inline comment is on |
| `extra.file`, `extra.content` | a doc's version: `{path, blob}`, and `{sha256, bytes, media_type, words, words_delta}` |
| `extra.actor` | who acted: `login`, `id`, `type`, `name`, `role` |
| `extra.agent` | `true` when the line's own text carries an agent session's marker (below) |
| `extra.tier_reason` | on a tier 2 line, why: `private repository`, or `repository visibility not known` |

## What an agent did

You build with coding agents whose pull requests are the honest log of what each did. A line is
`agent: true` when its own text carries one of these markers: `Generated with Claude Code` (or
`Generated by`, the link's brackets aside), a session link `claude.ai/code/session_…`, or a commit
trailer `Claude-Session:` or `Co-Authored-By: Claude`. A pull request's body flags every line of it
(created, merged or closed); a commit's message, a review's or a comment's text flags its own line. The
markers are `AGENT_MARKERS` in `logbook/contrib/adapters/github.py`, so a page that lists what agents did
reads `extra.agent` and never guesses.

## Which lines, and the watermark

A run reads, per repo: the commits on its default branch, the issues and pull requests (one list),
the comments on them and on their diffs, each pull request's reviews; every list paged by GitHub's
`Link` header, a next page at another address never followed (the token would go with it). It writes a
line for each act at or after where the repo starts: an item's `created` when it was created then, its
`closed` or `merged` when that happened then, a comment or a review when it was left then. How many
files a commit changed, who closed an issue and who merged a pull request are asked once each, and only
for a line the record does not hold yet. A comment edited after its line was written is not written
again: the record keeps what was said when the sync first read it.

**The watermark is per repo** (`marks` in `state/github.json`): the newest `modified_at` seen there, read
back a week — the commits list filters by the committer's date, and a commit pushed days after it was
made would otherwise be missed. A repo with no mark yet is read from its beginning, so a repo you add to
the list later is read whole; `--since` reads every repo from an exact time; `--dry-run` counts and
writes nothing, and stops on one line at a rate limit instead of waiting it out. The source's first
scheduled run reads every repo from 14 days back, not from its beginning ([the
schedule](../schedule.md#a-sources-first-scheduled-run)); `--since` reads the rest. A run with `--since`,
the scheduled first run among them, marks a repo it found nothing in at that time, so the next run reads
it on from there and never from its beginning. A commit pushed more than a week after it was made comes
in with `--since` or the export.

**Rate limits.** At most ten requests a second. GitHub's secondary limit is waited out as its
`Retry-After` says (a minute when it says nothing), its hourly limit until its reset, a 429 or a server
error after 1, 2, 4… seconds; a wait over five minutes, or a limit that does not lift, stops the run on
one line, exit 1, the watermark where it was, and the next run carries on, the record refusing what it
already holds. `logbook doctor` lists `sync:github` once the variables are set, by name only, and asks
GitHub nothing; `sync --all` and the schedule run it with no more configuration.

## An old project: `add github-export`

`logbook add github-export DIR` reads, by name only (a folder is never guessed to be a project):

- **a clone** — a working copy (`DIR/.git`) or a bare repository — of GitHub or anywhere else: its
  history on the branch `HEAD` names, a line per commit with its message in full and the files it
  changed, and a line per **version of a README or a doc**: a file at the top whose name starts with
  `readme` or ends in `.md`, `.markdown`, `.mdx`, `.rst`, `.adoc`, `.asciidoc`, `.org` or `.textile`, or one
  under `docs/` or `doc/` with one of those or `.txt`. A version is a path's content: its git blob,
  digest, length, words and the words since the path's previous version. The same bytes back at the
  same path later are no new version, so the first-said date stays the first. The repo is named by
  the clone's `origin` when that is a hosting link, else by its folder.
- **GitHub's account export** (*Settings → Account → Export account data*, the migration archive,
  unpacked): each repository's bare clone as above, under the name the export gives, and its issues,
  pull requests (who closed and who merged from its events), reviews and comments as the lines
  `sync github` writes for the same acts, read leniently: a row without what a line needs is skipped
  and counted. Each repository's mark in the export (`private`, `visibility`) sets the tier of all its
  lines, as above.

`--since` keeps the acts at or after it (a doc's earlier versions are still read, so an old version is
never new); `--dry-run` counts; `--public` says the clone, and any repository the export does not mark,
is public, so its lines are tier 1 (a clone's lines are tier 2 without it). Git runs read-only (`rev-parse`, `symbolic-ref`, `config`, `log`,
`cat-file`), never a shell and never fetching: no lazy fetch of a partial clone, no prompt, no
fsmonitor. Adding the same clone again writes nothing, and `add` never says a clone can be deleted: it
is your working copy. A folder that is none of these is one sentence, exit 2.
