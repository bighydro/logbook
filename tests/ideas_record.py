"""Lines for the idea readers' tests (`review idea`, `show ideas`, the Ideas shelf), built the way the
adapters write them: `sync notion` (`logbook.contrib.adapters.notion`), `sync github` and `add
github-export` (`logbook.contrib.adapters.github`), a task, a call's transcript. Nobody and nothing
here exists: the owner is Ines Nordmann of Oslo, her brother Ola Nordmann
(ola.nordmann@example.org, 07700 900101) talks the ideas through with her; the Notion pages, the
databases, the repositories under `nordmann-verft` and `ines-example`, the tasks and the calls are
made up, and every id is synthetic.

`record` writes any list of drafts into a fresh record whose owner's address is set; `ideas_drafts`
is the whole story, read by the shelf's and the page's tests, and `settle` the owner's sitting on it:

- **the fjord kiosk**: a row of the Ideas database (`Type` `Idea`) since March 2024, edited by Ines
  with its word counts (never a body), a sub-page *Pricing* Ola made in September 2026, a relations
  line the backfill wrote, and an edit an integration (a bot) made; the repository
  `nordmann-verft/fjord-kiosk` (commits, a README in two versions, a commit a bot made); a task.
- **the tide clock**: the repository `ines-example/tide-clock`, first said in its README in May
  2023, and a task that links it.
- **the harbour sauna**: a task, then a call titled *Harbour sauna* with Ola and a note-taking agent.
- **Quarterly taxes**: a row of the same database whose `Type` is `Task`, never an idea; a page
  under it, likewise.
- **Garden notes**: a page that is no row, under the workspace.

**The owner's say** (`settle`), through the functions `review idea` and `status idea` call, at fixed
instants and with fixed minted ids: the kiosk's row named *the fjord kiosk*, its repository and its
title bound to it by one more `entity/v1` line (as `logbook add` writes one), the tide clock's
repository named *the tide clock*, the sauna's title named *the harbour sauna*; the kiosk a spark in
2024 and exploring since September 2026 with a reason, the tide clock exploring since May 2023 and
untouched since (stale), the sauna killed with a reason and sparked again. `Garden notes` and the
kiosk's README of 2024 aside, nothing else is left in the queue but what the owner did not name."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER = {"name": "Ines Nordmann", "email": "ines.nordmann@example.org"}
OLA = {"name": "Ola Nordmann", "email": "ola.nordmann@example.org", "phone": "+447700900101"}
OLA_ID = "019cadd3-6bc0-7dcd-9133-000000000002"
HUB = "1f2e3d4c-0000-4000-8000-000000000010"  # a page holding the Ideas database
IDEAS_DB = "1f2e3d4c-0000-4000-8000-0000000000db"
KIOSK_ROW = "1f2e3d4c-0000-4000-8000-000000000031"
PRICING = "1f2e3d4c-0000-4000-8000-000000000032"
TAXES_ROW = "1f2e3d4c-0000-4000-8000-000000000041"
TAXES_SUB = "1f2e3d4c-0000-4000-8000-000000000042"
GARDEN = "1f2e3d4c-0000-4000-8000-000000000051"
WORKSPACE = {"type": "workspace"}
KIOSK_REPO = "nordmann-verft/fjord-kiosk"
CLOCK_REPO = "ines-example/tide-clock"
HUB_PATH = ["Ines' hub", "Ideas"]  # the titles above a row of the Ideas database, the top first
IDEA_TYPE = {"Type": "Idea"}
TODAY = "2026-10-16"
KIOSK, CLOCK, SAUNA = "the fjord kiosk", "the tide clock", "the harbour sauna"
KIOSK_REASON = "pricing page written; talk to the ferry company first"
SAUNA_REASON = "the harbour board said no to a sauna on the pier"


def _actor(who: str) -> dict[str, Any]:
    if who == "ola":
        return {"id": "u-ola", "name": OLA["name"], "type": "person", "role": "other"}
    if who == "bot":
        return {"id": "u-bot", "name": "Kiosk sync", "type": "bot", "role": "other"}
    if who == "ola-bot":  # an integration Ola named after himself: a bot, whatever its name
        return {"id": "u-ola-bot", "name": OLA["name"], "type": "bot", "role": "other"}
    return {"id": "u-ines", "name": OWNER["name"], "type": "person", "role": "owner"}


def notion(
    at: str,
    page: str,
    title: str | None,
    action: str = "edited",
    parent: Mapping[str, str] | None = None,
    path: Sequence[str] = (),
    who: str | None = "ines",
    words: int | None = None,
    delta: int | None = None,
    properties: Mapping[str, Any] | None = None,
    relations: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """An `event/v1` line as `sync notion` writes it: the page by reference, its title, the titles
    above it, its parent (a row's database under `database` too, as #303 has it), who acted, the
    body as a digest and a word count, a row's properties and relations. `who` None: no actor, as on
    a line `--relations-backfill` wrote."""
    parent = dict(parent) if parent is not None else dict(WORKSPACE)
    extra: dict[str, Any] = {
        "action": action,
        "page": {"id": page, "url": f"https://www.notion.so/{page.replace('-', '')}"},
        "path": list(path),
        "parent": parent,
    }
    if parent.get("type") == "database":
        extra["database"] = {"id": parent["id"]}
    if who is not None:
        extra["actor"] = _actor(who)
    if words is not None:
        body: dict[str, Any] = {"sha256": f"{words:064x}", "bytes": words * 6, "media_type": "text/plain"}
        body["words"] = words
        if delta is not None:
            body["words_delta"] = delta
        extra["body"] = body
    if properties is not None:
        extra["properties"] = dict(properties)
    if relations is not None:
        extra["relations"] = {k: list(v) for k, v in relations.items()}
    payload: dict[str, Any] = {"schema": "event/v1", "raw_id": f"{page}/{at[:10]}/{action}"}
    if title is not None:
        payload["title"] = title
    payload.update(
        {"calendar": {"id": "notion", "name": "Notion"}, "all_day": False, "modified_at": at, "extra": extra}
    )
    return {"at": at, "source": "notion", "kind": "event", "tier": 1, "payload": payload}


def row(at: str, page: str, title: str, database: str = IDEAS_DB, **kw: Any) -> dict[str, Any]:
    """A line of a database row: its parent the database, the titles above it the hub's."""
    kw.setdefault("path", HUB_PATH)
    return notion(at, page, title, parent={"type": "database", "id": database}, **kw)


def github(
    at: str,
    repo: str,
    action: str,
    title: str,
    bot: bool = False,
    words: int | None = None,
    delta: int | None = None,
) -> dict[str, Any]:
    """An `event/v1` line as `sync github` writes it: a commit (its first line the title), or a
    README's version as its digest and word count, never its text; `bot` an act a bot made."""
    extra: dict[str, Any] = {"action": action, "repo": repo}
    if action == "revised":
        content: dict[str, Any] = {"sha256": f"{words or 0:064x}", "bytes": (words or 0) * 6,
                                   "media_type": "text/markdown", "words": words}  # fmt: skip
        if delta is not None:
            content["words_delta"] = delta
        extra["file"] = {"path": title, "blob": f"b{words}"}
        extra["content"] = content
        raw_id = f"{repo}/file/{title}@b{words}".lower()
    else:
        sha = hashlib.sha1(f"{repo}@{at}".encode()).hexdigest()
        raw_id = f"commit/{sha}"
        extra["commit"] = {"sha": sha, "url": f"https://github.com/{repo}/commit/{sha}"}
    login = "kiosk-deps[bot]" if bot else "ines-example"
    extra["actor"] = {"login": login, "type": "Bot" if bot else "User"} | ({} if bot else {"role": "owner"})
    payload = {"schema": "event/v1", "raw_id": raw_id, "title": title,
               "calendar": {"id": "github", "name": "GitHub"}, "all_day": False, "modified_at": at,
               "extra": extra}  # fmt: skip
    return {"at": at, "source": "github", "kind": "event", "tier": 1, "payload": payload}


def task(
    at: str, title: str, url: str | None = None, links: Iterable[str] = (), machine: bool = False
) -> dict[str, Any]:
    """A `task/v1` line: its `url` and its `extra.links` as a source gives them; `machine` a task an
    agent wrote (`extra.machine`, `logbook.core.machine`)."""
    extra: dict[str, Any] = {"links": [{"type": "url", "url": u} for u in links]} if links else {}
    if machine:
        extra["machine"] = True
    payload: dict[str, Any] = {"schema": "task/v1", "raw_id": f"gtasks:{at}:{title}", "title": title,
                               "status": "open", "list": "Ideas"}  # fmt: skip
    if url is not None:
        payload["url"] = url
    if extra:
        payload["extra"] = extra
    return {"at": at, "source": "gtasks", "kind": "task", "tier": 2, "payload": payload}


def transcript(
    at: str, title: str, end: str, agent: bool = False, ola: bool = True, agent_email: str | None = None
) -> dict[str, Any]:
    """A call, `transcript/v1`: Ines, Ola unless `ola` is false, and with `agent` a note-taking agent
    among its participants (`machine`), at `agent_email` when given (one that joined under Ola's)."""
    participants: list[dict[str, Any]] = [{"name": OWNER["name"], "email": OWNER["email"]}]
    if ola:
        participants.append({"name": OLA["name"], "email": OLA["email"]})
    if agent:
        email = agent_email or "notetaker@example.org"
        participants.append({"name": "Notetaker", "email": email, "machine": True})
    return {"at": at, "end": end, "source": "granola", "kind": "transcript", "tier": 2,
            "payload": {"schema": "transcript/v1", "raw_id": f"granola:{at}", "title": title,
                        "participants": participants}}  # fmt: skip


def _resolution(ref: tuple[str, str]) -> dict[str, Any]:
    return {"at": "2023-01-02T08:00:00Z", "source": "manual", "kind": "resolution", "tier": 2,
            "payload": {"schema": "resolution/v1", "ref": {"kind": ref[0], "value": ref[1]},
                        "entity": {"type": "person", "id": OLA_ID, "registry": "logbook"},
                        "label": OLA["name"], "method": "owner"}}  # fmt: skip


def people() -> list[dict[str, Any]]:
    """Ola, resolved from his address and his number."""
    return [_resolution(("email", OLA["email"])), _resolution(("phone", OLA["phone"]))]


def ideas_drafts() -> list[dict[str, Any]]:
    """The three ideas, the row that is no idea and the page that is no row (the module's list)."""
    return [
        *people(),
        notion("2024-03-02T18:00:00Z", HUB, "Ines' hub", action="created"),
        row("2024-03-04T19:00:00Z", KIOSK_ROW, "The fjord kiosk", action="created", words=120,
            properties=IDEA_TYPE),
        row("2026-09-14T19:00:00Z", KIOSK_ROW, "The fjord kiosk", words=480, delta=360,
            properties=IDEA_TYPE),
        notion("2026-09-20T17:00:00Z", PRICING, "Pricing", action="created", who="ola",
               parent={"type": "page", "id": KIOSK_ROW}, path=[*HUB_PATH, "The fjord kiosk"], words=300),
        row("2026-09-21T08:00:00Z", KIOSK_ROW, "The fjord kiosk", who="bot", words=700, delta=220,
            properties=IDEA_TYPE),
        row("2026-09-22T08:00:00Z", KIOSK_ROW, "The fjord kiosk", action="relations", who=None,
            relations={"Areas": [GARDEN]}),
        row("2025-01-10T09:00:00Z", TAXES_ROW, "Quarterly taxes", action="created",
            properties={"Type": "Task"}),
        notion("2025-01-11T09:00:00Z", TAXES_SUB, "Receipts", action="created",
               parent={"type": "page", "id": TAXES_ROW}, path=[*HUB_PATH, "Quarterly taxes"]),
        notion("2026-05-01T07:00:00Z", GARDEN, "Garden notes", action="created", words=40),
        github("2024-04-02T10:00:00Z", KIOSK_REPO, "revised", "README.md", words=90),
        github("2026-09-15T10:00:00Z", KIOSK_REPO, "committed", "Price list page"),
        github("2026-09-16T10:00:00Z", KIOSK_REPO, "revised", "README.md", words=210, delta=120),
        github("2026-09-17T03:00:00Z", KIOSK_REPO, "committed", "Bump the toolchain", bot=True),
        task("2026-09-18T07:00:00Z", "Fjord kiosk"),
        github("2023-05-06T10:00:00Z", CLOCK_REPO, "revised", "README.md", words=150),
        task("2023-05-08T07:00:00Z", "Tide clock enclosure", url=f"https://github.com/{CLOCK_REPO}/issues/2"),
        task("2026-08-30T07:00:00Z", "Harbour sauna"),
        transcript("2026-10-03T16:00:00Z", "Harbour sauna", "2026-10-03T16:40:00Z", agent=True),
    ]  # fmt: skip


def record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drafts: Iterable[Mapping[str, Any]],
    settings: Mapping[str, Any] | None = None,
) -> Logbook:
    """A fresh record under `tmp_path`, found through LOGBOOK_HOME, its owner's address set, the
    drafts written through `Logbook.append_many`; `settings` as `policy/entities.json`."""
    import json

    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    lb.set_owner_emails([OWNER["email"]])
    if settings is not None:
        policy = lb.root / "policy"
        policy.mkdir(exist_ok=True)
        (policy / "entities.json").write_text(json.dumps(dict(settings)) + "\n", encoding="utf-8")
    lb.append_many([dict(d) for d in drafts])
    return lb


def clock(minute: int = 0) -> Iterator[str]:
    """Fixed instants on the sitting's day, a minute apart."""
    for m in range(minute, 60):
        yield f"{TODAY}T18:{m:02d}:00Z"


def settle(lb: Logbook) -> dict[str, str]:
    """The owner's sitting (the module's list), through the functions `review idea` and `status idea`
    call (the Ideas shelf's acts call the same), at fixed instants and with fixed minted ids; the
    ideas' ids by label."""
    from logbook.contrib import entity_review, entity_status

    instants = clock()
    minted = (f"019cadd3-6bc0-7dcd-9133-0000000003{n:02d}" for n in range(1, 100))
    ids: dict[str, str] = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(entity_review, "now_utc", lambda: next(instants))
        mp.setattr(entity_review, "uuid7", lambda: next(minted))
        for key, label in (
            (("page", f"notion:{KIOSK_ROW}"), KIOSK),
            (("repo", f"github.com/{CLOCK_REPO}"), CLOCK),
            (("title", "harbour sauna"), SAUNA),
        ):
            report = entity_review.read(lb, "idea")
            [p] = [p for p in report.proposals if p.new and p.observed.key == key]
            [written] = entity_review.accept(lb, report, [(p, label)])
            ids[label] = str(written.lines[0]["payload"]["entity"]["id"])
        refs = [
            {"kind": "repo", "value": f"github.com/{KIOSK_REPO}"},
            {"kind": "title", "value": "fjord kiosk"},
        ]
        entity_review.write_entity(
            lb,
            {"schema": "entity/v1", "entity": {"type": "idea", "id": ids[KIOSK], "registry": "logbook"},
             "label": KIOSK, "refs": refs, "method": "owner"},
            at=next(instants),
        )  # fmt: skip
    for label, status, reason, day in (
        (KIOSK, "spark", None, "2024-03-04"),
        (KIOSK, "exploring", KIOSK_REASON, "2026-09-14"),
        (CLOCK, "exploring", None, "2023-05-10"),
        (SAUNA, "killed", SAUNA_REASON, "2026-10-05"),
        (SAUNA, "spark", None, "2026-10-10"),
    ):
        entity_status.write(lb, "idea", label, status, reason, at=day, today=TODAY)
    return ids
