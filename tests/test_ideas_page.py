"""The Ideas shelf under `logbook serve` (RFC 0037 §7, §11): the ideas the owner named by stage, the
most recent touch first, the stale ones flagged, each with its reason and its evidence folded, the
people it was discussed with counted and named only on its page; the review queue of `review idea`
with its acts; each idea's page with its status form. The acts are POSTs from this machine only,
through the functions `review idea` and `status idea` call, so a page and the command write the same
lines byte for byte; while another command writes the record an act is a 409 and nothing is written
(the owner's decision of 14 October 2026 for every Library act). Phone first: one column, no table.
The exported site has no Ideas. On the synthetic record of `tests/ideas_record.py`, with one more page
titled like the kiosk so the queue holds a match: nobody and nothing in it exists."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import phone_width
import pytest
from ideas_record import (
    CLOCK,
    GARDEN,
    HUB,
    KIOSK,
    KIOSK_REASON,
    SAUNA,
    SAUNA_REASON,
    TODAY,
    ideas_drafts,
    notion,
    record,
    settle,
    task,
)

from logbook import cli
from logbook.contrib import entity_review, entity_status, ideas, serve
from logbook.core import notes, store
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
AT = f"{TODAY}T19:30:00Z"
COPY = "1f2e3d4c-0000-4000-8000-000000000061"  # a page Ines titled like the kiosk, outside the database
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)


@pytest.fixture(scope="module")
def settled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        copy = notion("2026-09-25T10:00:00Z", COPY, "The fjord kiosk", action="created", words=60)
        lb = record(tmp_path_factory.mktemp("ideas"), mp, [*ideas_drafts(), copy])
        settle(lb)
        return lb.root


def _copy(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "lb") -> Logbook:
    root = tmp_path / name
    shutil.copytree(source, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    return Logbook(root)


@pytest.fixture
def lb(settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return _copy(settled, tmp_path, monkeypatch)


def _site(lb: Logbook, tiers: tuple[int, ...] | None = None) -> serve.Site:
    return serve.Site(
        lb, now=lambda: datetime.fromisoformat(f"{TODAY}T12:00:00").replace(tzinfo=UTC), tiers=tiers
    )


def _get(site: serve.Site, path: str, query: str = "") -> str:
    response = site.respond(path, query)
    assert response.status == 200, (path, response.status, response.body[:300])
    return response.body.decode("utf-8")


def _post(
    site: serve.Site, path: str, client: str = LOOPBACK, origin: str | None = None, **form: str
) -> serve.Response:
    return site.write(path, form, client, origin)


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _text(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def _ids(lb: Logbook) -> dict[str, str]:
    return {e.label: e.id for e in ideas.named(lb).values()}


def _proposal(lb: Logbook, key: tuple[str, str]) -> entity_review.Proposal:
    """The one proposal for the observed idea `key`, as the queue stands now."""
    [p] = [p for p in entity_review.read(lb, "idea").proposals if p.observed.key == key]
    return p


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    return sorted(Logbook(lb.root).lines(), key=lambda line: line["seq"])


def _pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every clock at AT, and the ids minted from the same two sequences; called once per side, so the
    ideas minted and the lines appended get the same ids on each."""
    for module in (entity_review, store, notes):
        monkeypatch.setattr(module, "now_utc", lambda: AT)
    minted = iter(f"019cadd3-6bc0-7dcd-9133-0000000009{n:02d}" for n in range(100))
    line_ids = iter(f"019cadd3-6bc0-7dcd-9133-0000000008{n:02d}" for n in range(100))
    monkeypatch.setattr(entity_review, "uuid7", lambda: next(minted))
    monkeypatch.setattr(store, "uuid7", lambda: next(line_ids))


def _same_record(page_side: Logbook, cli_side: Logbook) -> list[dict[str, Any]]:
    """The two sides are one record: the same lines, the same head, the month files byte for byte."""
    page_lines, cli_lines = _lines(page_side), _lines(cli_side)
    assert page_lines == cli_lines
    assert Logbook(page_side.root).meta["head"] == Logbook(cli_side.root).meta["head"]
    files = sorted((page_side.root / "logbook").rglob("*.jsonl"))
    assert files and [f.read_bytes() for f in files] == [
        (cli_side.root / f.relative_to(page_side.root)).read_bytes() for f in files
    ], "the month files, byte for byte"
    return page_lines


# -- the pages -------------------------------------------------------------------------------------------


def test_the_shelf_is_the_ideas_by_stage_the_most_recent_touch_first_each_with_its_reason(
    lb: Logbook,
) -> None:
    page = _get(_site(lb), "/ideas")
    ids = _ids(lb)
    rows = re.findall(r'<li id="([^"]+)"( class="stale")?><p class="head">(.*?)</li>', page, re.S)
    assert [idea for idea, _cls, _body in rows] == [ids[KIOSK], ids[CLOCK], ids[SAUNA]]
    assert re.findall(r"<h2>([^<]+)", page)[:2] == ["exploring", "spark"], "RFC 0037 §11's order"
    kiosk, clock, sauna = (_text(body) for _id, _cls, body in rows)
    assert "exploring since 2026-09-14 (owner)" in kiosk and KIOSK_REASON in kiosk
    assert "+660 words in 2026" in kiosk and "1 person" in kiosk
    assert rows[1][1] == ' class="stale"' and "stale: nothing since 2023-05-10" in clock
    assert f"killed 2026-10-05: {SAUNA_REASON}" in sauna, "a killed idea sparked again keeps its reason"
    assert '<details class="evidence">' in rows[0][2], "the evidence folded"


def test_the_shelf_counts_who_it_was_discussed_with_and_only_its_page_names_them(lb: Logbook) -> None:
    site = _site(lb)
    shelf = _get(site, "/ideas")
    assert "Ola" not in shelf.split('<h2 id="review">')[0], "the shelf counts, never names"
    page = _get(site, f"/idea/{_ids(lb)[KIOSK]}")
    assert "Ola Nordmann" in _text(page) and 'href="/people/' in page


def test_an_idea_page_is_its_status_form_first_said_timeline_people_documents_and_history(
    lb: Logbook,
) -> None:
    kiosk = _ids(lb)[KIOSK]
    page = _get(_site(lb), f"/idea/{kiosk}")
    text = _text(page)
    assert f'action="{serve.IDEAS_STATUS}"' in page and f'value="{kiosk}"' in page
    assert "first said 2024-03-04" in text and "Timeline 7 lines" in text
    timeline = re.findall(
        r"<li title=\"line [^\"]+\">(.*?)</li>", page.split("<h2>Timeline")[1].split("<h2>")[0]
    )
    assert len(timeline) == 7 and "2026-09-20" in timeline[0] and "2024-03-04" in timeline[-1], "newest first"
    assert "README 2 versions, 210 words" in text and "· 480 words" in text, "documents as references"
    assert "2026-09 +660" in text, "the words by month, no bot's"
    assert "2026-09-14 exploring (owner): " + KIOSK_REASON + " current" in text
    assert "Proposed for this idea" in text, "the queue's match for it: the page titled like it"


def test_every_ideas_page_is_one_document_that_fetches_nothing(lb: Logbook) -> None:
    site = _site(lb)
    for path in ["/ideas", *(f"/idea/{idea}" for idea in _ids(lb).values())]:
        response = site.respond(path, "")
        text = response.body.decode("utf-8")
        assert response.status == 200 and response.etag is not None, path
        assert "<script" not in text and response.headers["Content-Security-Policy"] == serve.CSP, path
        for found in REFERENCE.findall(text):
            target = html.unescape(found)
            assert target.startswith("/") and not target.startswith("//"), (path, target)
        assert site.respond(path, "", if_none_match=response.etag).status == 304
    assert site.respond("/idea/nobody", "").status == 404
    front = _get(site, "/shelves")  # the shelves listed, behind the gear: as the old navigation had them
    front = front[front.index("<main>") :]
    assert 'href="/ideas"' in front and front.index('href="/manifest"') < front.index('href="/ideas"')


def test_no_ideas_page_is_wider_than_a_phone(lb: Logbook) -> None:
    site = _site(lb)
    for path in ["/ideas", *(f"/idea/{idea}" for idea in _ids(lb).values())]:
        text = _get(site, path)
        assert phone_width.problems(text) == [], path
        assert phone_width.phone_breakpoints(phone_width.parse(text)[1]), path


# -- the acts: one path, the command's -------------------------------------------------------------------


def test_the_page_s_acts_write_what_the_command_writes_byte_for_byte(
    settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Five acts, once through the Ideas pages and once through the commands, on two copies of the same
    record, every clock and every minted id pinned: a match accepted, a new idea named (with the
    spaces a form may carry), a new one rejected, a status with a reason on a past day (its note first,
    RFC 0037 §10.5) and a killed now; the same lines, the same head, the month files byte for byte."""
    page_side = _copy(settled, tmp_path, monkeypatch, "page")
    cli_side = _copy(settled, tmp_path, monkeypatch, "cli")
    copy, garden, hub = ("page", f"notion:{COPY}"), ("page", f"notion:{GARDEN}"), ("page", f"notion:{HUB}")
    named = "  the  garden   notes "  # as typed: its spaces are folded by the one writer
    reason, why = "the ferry company said yes to a trial", "the clock is on every chartplotter already"
    _pin(monkeypatch)
    site = _site(page_side)
    clock_id = _ids(page_side)[CLOCK]
    acts: list[tuple[str, dict[str, str]]] = [
        (serve.IDEAS_REVIEW, {"id": _proposal(page_side, copy).id, "act": "accept"}),
        (serve.IDEAS_REVIEW, {"id": _proposal(page_side, garden).id, "act": "name", "name": named}),
        (serve.IDEAS_REVIEW, {"id": _proposal(page_side, hub).id, "act": "reject"}),
        (serve.IDEAS_STATUS, {"idea": _ids(page_side)[KIOSK], "status": "build", "reason": reason,
                              "at": "2026-10-11"}),
        (serve.IDEAS_STATUS, {"idea": clock_id, "status": "killed", "reason": why, "at": ""}),
    ]  # fmt: skip
    for path, form in acts:
        response = _post(site, path, **form, back="/ideas")
        assert response.status == 303, (path, form, response.body[:300])
        assert response.location == "/ideas"
    monkeypatch.setenv("LOGBOOK_HOME", str(cli_side.root))
    _pin(monkeypatch)
    cli.main(["review", "idea", "--accept", str(_proposal(cli_side, copy).number)])
    cli.main(["review", "idea", "--name", str(_proposal(cli_side, garden).number), named])
    cli.main(["review", "idea", "--reject", str(_proposal(cli_side, hub).number)])
    cli.main(["status", "idea", KIOSK, "build", "--reason", reason, "--at", "2026-10-11"])
    cli.main(["status", "idea", CLOCK, "killed", "--reason", why])
    capsys.readouterr()
    lines = _same_record(page_side, cli_side)
    assert [line["kind"] for line in lines[-7:]] == ["entity", "entity", "entity-review", "note", "status",
                                                     "note", "status"]  # fmt: skip
    assert all(line["tier"] == 2 for line in lines[-7:])
    assert lines[-6]["payload"]["label"] == "the garden notes", "the name as the writer folds it"
    status, note = lines[-1]["payload"], lines[-2]
    assert status["reason"] == why and status["note"] == note["id"] and note["payload"]["text"] == why
    assert "the garden notes" in _get(site, "/ideas"), "the idea named on the page is on the shelf"


def test_an_act_while_another_command_writes_is_a_409_and_writes_nothing(lb: Logbook) -> None:
    """The owner's word of 14 October 2026: a Library act never waits for another writer; it says so
    in one sentence, a 409, and writes nothing."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = lb._lock_path()
    site = _site(lb)
    report = entity_review.read(lb, "idea")
    forms = [
        (serve.IDEAS_REVIEW, {"id": report.proposals[0].id, "act": "reject"}),
        (serve.IDEAS_STATUS, {"idea": _ids(lb)[KIOSK], "status": "build", "reason": "the trial is booked"}),
    ]
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        holder = {"pid": other.pid, "command": "sync notion", "since": "2026-10-16T06:00:00Z"}
        lock.write_text(json.dumps(holder), encoding="utf-8")
        seq, before = int(lb.meta["seq"]), _files(lb.root / "logbook")
        for path, form in forms:
            response = _post(site, path, **form)
            body = _text(response.body.decode("utf-8"))
            assert response.status == 409, (path, response.status)
            assert "sync notion" in body and "nothing was written" in body
            assert body.count(". ") <= 1, "one sentence"
            assert int(Logbook(lb.root).meta["seq"]) == seq and _files(lb.root / "logbook") == before
    finally:
        other.kill()
        other.wait()
        lock.unlink(missing_ok=True)
    assert _post(site, *forms[1][:1], **forms[1][1]).status == 303, "and once it is free, written"


def test_an_act_holds_the_writer_lock_as_logbook_serve_and_never_waits(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page's hold is the first and outermost: named `logbook serve`, `wait` False. Bounded: a
    regression to waiting would hang the 409 test for good (its sleeping holder is never reaped while
    the act waits, so its pid stays alive)."""
    seen: list[tuple[str | None, bool | None]] = []
    writer = Logbook.writer

    def spy(self: Logbook, command: str | None = None, wait: bool | None = None, notice: Any = None) -> Any:
        seen.append((command, wait))
        return writer(self, command=command, wait=wait, notice=notice)

    monkeypatch.setattr(Logbook, "writer", spy)
    site = _site(lb)
    form = {"idea": _ids(lb)[KIOSK], "status": "build", "reason": "the trial is booked"}
    assert _post(site, serve.IDEAS_STATUS, **form).status == 303
    assert seen and seen[0] == ("logbook serve", False), seen


def test_a_head_that_moved_under_a_status_act_is_a_409_and_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer that ignored the lock moved the head between the status writer's read and its re-check:
    `HeadMoved`, a 409 in one sentence, and the act wrote nothing."""
    read = entity_status._read

    def read_then_moved(lb_: Logbook) -> Any:
        found = read(lb_)
        Logbook(lb_.root).append(**task("2026-10-16T10:00:00Z", "An intruder's task"))  # re-enters the lock
        return found

    monkeypatch.setattr(entity_status, "_read", read_then_moved)
    site = _site(lb)
    seq = int(lb.meta["seq"])
    form = {"idea": _ids(lb)[KIOSK], "status": "build", "reason": "the trial is booked"}
    response = _post(site, serve.IDEAS_STATUS, **form)
    body = _text(response.body.decode("utf-8"))
    assert response.status == 409, (response.status, body[:300])
    assert "head moved" in body and "nothing was written" in body and body.count(". ") <= 1
    assert int(Logbook(lb.root).meta["seq"]) == seq + 1, "the intruder's line, and no status or note"
    assert all(line["kind"] != "status" for line in Logbook(lb.root).lines() if int(line["seq"]) > seq)


def test_an_act_on_a_stale_or_bad_form_writes_nothing(lb: Logbook) -> None:
    site = _site(lb)
    seq = lb.meta["seq"]
    report = entity_review.read(lb, "idea")
    kiosk = _ids(lb)[KIOSK]
    gone = _post(site, serve.IDEAS_REVIEW, id="0000000000000000", act="reject")
    assert gone.status == 409 and "not in the queue" in gone.body.decode("utf-8")
    assert _post(site, serve.IDEAS_REVIEW, id=report.proposals[0].id, act="dance").status == 400
    refused = _post(site, serve.IDEAS_STATUS, idea=kiosk, status="killed", reason=" ")
    assert refused.status == 400 and "must say why" in refused.body.decode("utf-8")
    assert _post(site, serve.IDEAS_STATUS, idea=kiosk, status="hold").status == 400, "an org's word"
    assert _post(site, serve.IDEAS_STATUS, idea=kiosk, status="build", at="2099-01-01").status == 400
    assert _post(site, serve.IDEAS_STATUS, idea="nobody", status="build").status == 409
    for path in serve.IDEAS_PATHS:
        assert site.respond(path, "").status == 405
    assert Logbook(lb.root).meta["seq"] == seq


def test_an_act_from_off_this_machine_is_refused(lb: Logbook) -> None:
    site = _site(lb)
    seq = lb.meta["seq"]
    kiosk = _ids(lb)[KIOSK]
    form = {"idea": kiosk, "status": "build", "reason": "the trial is booked"}
    for client in ("192.168.1.20", "203.0.113.9", ""):
        response = site.write(serve.IDEAS_STATUS, form, client, None)
        assert response.status == 403 and "this machine" in response.body.decode("utf-8")
    for origin in ("http://example.org", "http://localhost:8765", "null"):
        assert site.write(serve.IDEAS_STATUS, form, LOOPBACK, origin).status == 403
    assert Logbook(lb.root).meta["seq"] == seq
    ok = site.write(
        serve.IDEAS_STATUS, {**form, "back": "https://example.org/x"}, LOOPBACK, "http://127.0.0.1:8765"
    )
    assert ok.status == 303 and ok.location == f"/idea/{kiosk}", (
        "a back that is not the server's own: the idea"
    )
    assert int(Logbook(lb.root).meta["seq"]) == int(seq) + 2, "the reason's note, then the status line"


def test_a_page_that_reads_no_tier_two_offers_no_act_and_takes_none(lb: Logbook) -> None:
    site = _site(lb, tiers=(1,))
    kiosk = _ids(lb)[KIOSK]
    page = _get(site, "/ideas")
    assert serve.IDEAS_REVIEW not in page and 'class="proposal"' not in page
    seq = lb.meta["seq"]
    refused = _post(site, serve.IDEAS_STATUS, idea=kiosk, status="build", reason="the trial is booked")
    assert refused.status == 403 and "tier 2" in _text(refused.body.decode("utf-8"))
    assert Logbook(lb.root).meta["seq"] == seq


# -- nothing public changes ------------------------------------------------------------------------------


def test_serving_the_ideas_writes_nothing(lb: Logbook) -> None:
    site = _site(lb)
    site.respond("/ideas", "")  # the observed table, built once, is the index's
    head, before = lb.meta["head"], _files(lb.root)
    for path in ("/ideas", *(f"/idea/{idea}" for idea in _ids(lb).values())):
        site.respond(path, "")
    after = _files(lb.root)
    assert Logbook(lb.root).meta["head"] == head
    assert {k: v for k, v in after.items() if not k.startswith("index")} == {
        k: v for k, v in before.items() if not k.startswith("index")
    }


def test_the_exported_site_has_no_ideas_and_names_no_idea(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "site"
    policy = lb.root / "policy" / "crossing.json"
    data = json.loads(policy.read_text(encoding="utf-8")) if policy.exists() else {}
    data["site"] = {"max_tier": 2}
    policy.write_text(json.dumps(data), encoding="utf-8")
    try:
        cli.main(["export", "site", str(out), "--tier", "1,2"])
    except SystemExit as e:
        assert not e.code, capsys.readouterr().err
    capsys.readouterr()
    files = _files(out)
    assert files, "the site was written"
    assert not any("idea" in name for name in files)
    for name, body in files.items():
        text = body.decode("utf-8", "replace")
        for word in (KIOSK_REASON, SAUNA_REASON, "/ideas", "/idea/", KIOSK, SAUNA):
            assert word not in text, (name, word)
