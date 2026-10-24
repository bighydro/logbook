"""The Manifest under `logbook serve` (RFC 0037 §7, §11): the orgs the owner named under what they
decided about them, the most recent touch first, the stale ones flagged, the passed with their
reasons (the anti-portfolio); the review queue of `review org` with its evidence folded and its acts;
each org's page with its status form; the people who appear with more than one org. The acts are
POSTs from this machine only, through the functions `review org` and `status org` call, so a page
and the command write the same lines byte for byte; while another command writes the record an act
is a 409 and nothing is written. Phone first: one column, no table, no wider than a phone. An org's
status, its reason and the money are tier 3 and never through a gate without 3; the exported site has
no Manifest. On the synthetic record of `tests/orgs_record.py`: nobody and nothing in it exists."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import phone_width
import pytest
from orgs_record import (
    HAVBRIS,
    KARI,
    KIOSK,
    KIOSK_DOMAIN,
    NEWS_DOMAIN,
    PASSED_REASON,
    ROBAAT_DOMAIN,
    TIDEVANN,
    TODAY,
    VERFT,
    VERFT_REASON,
    evidence_record,
    settle,
    wire,
)
from persona import utc

from logbook import cli
from logbook.contrib import entity_review, orgs, serve
from logbook.core import notes, store
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
AT = f"{TODAY}T19:30:00Z"
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)


@pytest.fixture(scope="module")
def settled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        lb = evidence_record(tmp_path_factory.mktemp("manifest"))
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
    from datetime import UTC, datetime

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
    return {o.label: o.id for o in orgs.named(lb).values()}


# -- the pages -------------------------------------------------------------------------------------------


def test_the_manifest_is_the_orgs_under_their_status_the_most_recent_touch_first(lb: Logbook) -> None:
    page = _get(_site(lb), "/manifest")
    ids = _ids(lb)
    rows = re.findall(r'<li id="([^"]+)"( class="stale")?><p class="head">(.*?)</li>', page, re.S)
    assert [org for org, _cls, _body in rows] == [ids[VERFT], ids[TIDEVANN], ids[HAVBRIS], ids[KIOSK]]
    headings = re.findall(r"<h2>([^<]+)", page)
    assert headings[:2] == ["holding", "passed "], "RFC 0037 §11's headings, in order"
    verft = _text(rows[0][2])
    assert "hold" in verft and "since 2026-04-02 (owner)" in verft
    assert 'last touch 2026-10-09 group "Nordmann Verft": message from Ola' in verft
    assert rows[2][1] == ' class="stale"' and "stale: nothing since 2023-07-01" in _text(rows[2][2])
    assert "last touch 2023-07-01 the ledger" in _text(rows[2][2]) and "transaction" not in rows[2][2]
    assert page.count(' class="stale"') == 1
    passed = page[page.index("<h2>passed") :]
    assert "the anti-portfolio" in passed and html.escape(PASSED_REASON) in passed
    assert f'href="/org/{ids[VERFT]}"' in page and 'href="/manifest/people"' in page
    assert "<table" not in page, "phone first: one column, no table"
    assert VERFT_REASON not in page, "a holding's reason is on its own page; the shelf says a passed one's"


def test_the_queue_is_on_the_manifest_with_its_evidence_folded_and_its_acts(lb: Logbook) -> None:
    page = _get(_site(lb), "/manifest")
    report = entity_review.read(lb, "org")
    ids = re.findall(r'<li class="proposal" id="([^"]+)">', page)
    assert ids == [p.id for p in report.proposals], "the CLI's queue, in its order"
    [new] = [p for p in report.proposals if p.observed.key == ("domain", ROBAAT_DOMAIN)]
    li = page[page.index(f'id="{new.id}"') :].split("</form>")[0]
    assert '<details class="evidence">' in li, "the evidence folded, closed"
    assert f'action="{serve.MANIFEST_REVIEW}"' in li
    assert 'value="name"' in li and 'value="reject"' in li and 'value="Nordmann Robåt"' in li
    assert "seen on mail 1" in _text(li) and "hint company" in _text(li)


def test_an_org_page_is_its_status_form_timeline_people_introductions_documents_and_history(
    lb: Logbook,
) -> None:
    page = _get(_site(lb), f"/org/{_ids(lb)[TIDEVANN]}")
    text = _text(page)
    assert f"<h1>{TIDEVANN} <small>org · tier 3</small>" in page
    assert "tidevann.example.org, git.example.org/nordmann-tidevann" in text
    assert "add" in text and "follow-on with Per" in text
    assert f'action="{serve.MANIFEST_STATUS}"' in page and '<option value="add" selected>' in page
    assert 'mail from Liv Berg "Follow-on round"' in text
    assert "github nordmann-tidevann/tide-clock: Merged pull request #12" in text
    assert "Per Hansen introduced Liv Berg" in text
    people = page[page.index("<h2>People") : page.index("<h2>Documents")]
    assert people.index("Liv Berg") < people.index("Per Hansen")
    history = page[page.index("<h2>Status lines") :]
    assert history.index("first cheque") < history.index("follow-on with Per")
    assert "<h2>Money" not in page and "show the money" in page
    assert "<table" not in page


def test_money_on_an_org_page_only_when_asked_and_through_a_gate_that_holds_tier_three(lb: Logbook) -> None:
    havbris = _ids(lb)[HAVBRIS]
    shown = _get(_site(lb), f"/org/{havbris}", "money=1")
    assert "<h2>Money" in shown and "NOK in 5,000.00, out -120,000.00, net -115,000.00" in shown
    assert "NORDMANN HAVBRIS AS -100,000.00 NOK" in shown
    plain = _get(_site(lb), f"/org/{havbris}")
    assert "<h2>Money" not in plain and "120,000" not in plain and "transaction" not in plain
    gated = _get(_site(lb, tiers=(1, 2)), f"/org/{havbris}", "money=1")
    assert "<h2>Money" not in gated and "120,000" not in gated and "show the money" not in gated


def test_through_a_gate_without_tier_three_no_status_no_reason_and_the_lines_counted(lb: Logbook) -> None:
    site = _site(lb, tiers=(1, 2))
    manifest = _get(site, "/manifest")
    assert "5 status lines not shown" in _text(manifest) and "no status" in manifest
    assert "<h2>holding" not in manifest and "<h2>passed" not in manifest
    for page in (
        manifest,
        *(_get(site, f"/org/{org}") for org in _ids(lb).values()),
        _get(site, "/manifest/people"),
    ):
        for word in (PASSED_REASON, VERFT_REASON, "first cheque", "follow-on with Per", 'class="badge hold"'):
            assert html.escape(word) not in page, word
        assert "NOK" not in page


def test_the_people_page_is_everyone_with_more_than_one_org_and_the_anti_portfolio(lb: Logbook) -> None:
    page = _get(_site(lb), "/manifest/people")
    rows = re.findall(r'<li class="person">(.*?)</li>', page, re.S)
    assert [_text(r).split(" tier")[0] for r in rows] == ["Per Hansen", "Liv Berg", "Ola Nordmann"]
    assert all("tier 1" in _text(r) for r in rows), "each edge rests on a meeting, tier 1"
    assert f'href="/org/{_ids(lb)[KIOSK]}"' in rows[0]
    assert html.escape(PASSED_REASON) in page[page.index("<h2>passed") :]


def test_every_manifest_page_is_one_document_that_fetches_nothing(lb: Logbook) -> None:
    site = _site(lb)
    paths = ["/manifest", "/manifest/people", *(f"/org/{org}" for org in _ids(lb).values())]
    for path in paths:
        response = site.respond(path, "")
        text = response.body.decode("utf-8")
        assert response.status == 200 and response.etag is not None, path
        assert "<script" not in text and response.headers["Content-Security-Policy"] == serve.CSP, path
        for found in REFERENCE.findall(text):
            target = html.unescape(found)
            assert target.startswith("/") and not target.startswith("//"), (path, target)
        assert site.respond(path, "", if_none_match=response.etag).status == 304
    assert site.respond("/org/nobody", "").status == 404
    front = _get(site, "/shelves")  # the shelves listed, under the old navigation
    assert (
        'href="/manifest"' in front
        and '<a href="/people">people</a><a href="/manifest">manifest</a>' in front
    )


def test_no_manifest_page_is_wider_than_a_phone(lb: Logbook) -> None:
    site = _site(lb)
    for path in ("/manifest", "/manifest/people", *(f"/org/{org}" for org in _ids(lb).values())):
        text = _get(site, path, "money=1")
        assert phone_width.problems(text) == [], path
        assert phone_width.phone_breakpoints(phone_width.parse(text)[1]), path


# -- the acts: one path, the command's -------------------------------------------------------------------


def test_the_page_s_acts_write_what_the_command_writes_byte_for_byte(
    settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The four acts, once through the Manifest and once through the commands, on two copies of the
    same record, every clock and every minted id pinned: the same lines, the same head."""
    for module in (entity_review, store, notes):
        monkeypatch.setattr(module, "now_utc", lambda: AT)
    page_side = _copy(settled, tmp_path, monkeypatch, "page")
    cli_side = _copy(settled, tmp_path, monkeypatch, "cli")
    kiosk = _ids(page_side)[KIOSK]
    reason = "too early, and a kiosk is a place"

    def minting() -> None:
        """The same ids on each side: the orgs minted and the lines appended."""
        minted = iter(f"019cadd3-6bc0-7dcd-9133-0000000009{n:02d}" for n in range(100))
        ids = iter(f"019cadd3-6bc0-7dcd-9133-0000000008{n:02d}" for n in range(100))
        monkeypatch.setattr(entity_review, "uuid7", lambda: next(minted))
        monkeypatch.setattr(store, "uuid7", lambda: next(ids))

    minting()
    site = _site(page_side)

    def proposal(lb: Logbook, key: tuple[str, str]) -> entity_review.Proposal:
        return next(p for p in entity_review.read(lb, "org").proposals if p.observed.key == key)

    news, robaat = ("domain", NEWS_DOMAIN), ("domain", ROBAAT_DOMAIN)
    named = " Nordmann  Robåt AS"  # as typed: its spaces are folded by the one writer
    again = PASSED_REASON + " again"
    acts: list[tuple[str, dict[str, str]]] = [
        (serve.MANIFEST_REVIEW, {"id": proposal(page_side, robaat).id, "act": "name", "name": named}),
        (serve.MANIFEST_REVIEW, {"id": proposal(page_side, news).id, "act": "reject"}),
        (serve.MANIFEST_STATUS, {"org": kiosk, "status": "hold", "reason": reason, "at": "2026-10-11"}),
        (serve.MANIFEST_STATUS, {"org": kiosk, "status": "passed", "reason": again, "at": ""}),
    ]  # fmt: skip
    for path, form in acts:
        response = _post(site, path, **form, back="/manifest")
        assert response.status == 303, (path, form, response.body[:300])
        assert response.location == "/manifest"
    monkeypatch.setenv("LOGBOOK_HOME", str(cli_side.root))
    minting()
    cli.main(["review", "org", "--name", str(proposal(cli_side, robaat).number), named])
    cli.main(["review", "org", "--reject", str(proposal(cli_side, news).number)])
    cli.main(["status", "org", KIOSK, "hold", "--reason", reason, "--at", "2026-10-11"])
    cli.main(["status", "org", KIOSK, "passed", "--reason", again])
    capsys.readouterr()

    def lines(root: Path) -> list[dict[str, Any]]:
        return sorted(Logbook(root).lines(), key=lambda line: line["seq"])

    page_lines, cli_lines = lines(page_side.root), lines(cli_side.root)
    assert page_lines == cli_lines
    assert [line["kind"] for line in page_lines[-4:]] == ["entity", "entity-review", "status", "status"]
    assert [line["tier"] for line in page_lines[-4:]] == [2, 2, 3, 3]
    assert Logbook(page_side.root).meta["head"] == Logbook(cli_side.root).meta["head"]
    assert not any(line["kind"] == "note" for line in page_lines), "an org's reason is never a note"
    after = _get(site, "/manifest")
    assert "Nordmann Robåt AS" in after, "the org named on the page is on the shelf"
    files = sorted((page_side.root / "logbook").rglob("*.jsonl"))
    assert files and [f.read_bytes() for f in files] == [
        (cli_side.root / f.relative_to(page_side.root)).read_bytes() for f in files
    ], "the month files, byte for byte"


# -- the acts the test above leaves out: matched, accepted as new, and the form's spaces ----------------


def _pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every clock at AT, and the ids minted from the same two sequences; called once per side, so
    the orgs minted and the lines appended get the same ids on each."""
    for module in (entity_review, store, notes):
        monkeypatch.setattr(module, "now_utc", lambda: AT)
    minted = iter(f"019cadd3-6bc0-7dcd-9133-0000000009{n:02d}" for n in range(100))
    ids = iter(f"019cadd3-6bc0-7dcd-9133-0000000008{n:02d}" for n in range(100))
    monkeypatch.setattr(entity_review, "uuid7", lambda: next(minted))
    monkeypatch.setattr(store, "uuid7", lambda: next(ids))


def _proposal(lb: Logbook, key: tuple[str, str]) -> entity_review.Proposal:
    """The one proposal for the observed org `key`, as the queue stands now."""
    [p] = [p for p in entity_review.read(lb, "org").proposals if p.observed.key == key]
    return p


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    return sorted(Logbook(lb.root).lines(), key=lambda line: line["seq"])


def _same_record(page_side: Logbook, cli_side: Logbook) -> list[dict[str, Any]]:
    """The two sides are one record: the same lines, the same head, the month files byte for byte;
    the lines, in order."""
    page_lines, cli_lines = _lines(page_side), _lines(cli_side)
    assert page_lines == cli_lines
    assert Logbook(page_side.root).meta["head"] == Logbook(cli_side.root).meta["head"]
    files = sorted((page_side.root / "logbook").rglob("*.jsonl"))
    assert files and [f.read_bytes() for f in files] == [
        (cli_side.root / f.relative_to(page_side.root)).read_bytes() for f in files
    ], "the month files, byte for byte"
    return page_lines


def _matched_evidence(lb: Logbook) -> None:
    """What makes the queue propose against an org already named, never as a new one: a group chat
    named like Fjordkiosk AS with Kari in it, and a merchant spelled like it on three ledger lines
    (`merchant_min_lines`). Nobody and nothing here exists."""
    chat = "120363000000000003@g.us"
    messages = [
        {
            "at": utc(day, "09:30"),
            "source": "whatsapp",
            "kind": "message",
            "tier": 2,
            "payload": {
                "schema": "message/v1",
                "raw_id": f"m-{day}-{chat}",
                "chat": {"id": chat, "type": "group", "name": "Fjordkiosk"},
                "from_me": False,
                "text": text,
                "sender": {"kind": "phone", "value": KARI["phone"], "name": "Kari"},
            },
        }
        for day, text in (("2026-04-21", "Deck v2 attached"), ("2026-04-22", "Any questions?"))
    ]
    wires = [
        wire(utc(f"2026-05-0{n}", "12:00"), "FJORDKIOSK AS", -amount, f"wire-kiosk-{n}")
        for n, amount in ((1, 120), (2, 85), (3, 60))
    ]
    lb.append_many([*messages, *wires])


def test_accept_and_reject_of_a_proposal_matched_to_a_named_org_write_what_the_command_writes(
    settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The byte test above names a new org and rejects a new one; the settled queue has nothing left
    that is matched against an org already named. A group chat named like Fjordkiosk AS and a merchant
    spelled like it make two. Accept on the page is `--accept N`: one entity/v1 line binding the group
    to the org, the label the org's, the key the org's domain, no id minted. No is `--reject N`: one
    entity-review/v1 line naming the org, tier 3 since its evidence is the ledger's. The same bytes."""
    base = _copy(settled, tmp_path, monkeypatch, "base")
    _matched_evidence(base)
    page_side = _copy(base.root, tmp_path, monkeypatch, "page")
    cli_side = _copy(base.root, tmp_path, monkeypatch, "cli")
    kiosk = _ids(page_side)[KIOSK]
    group, merchant = ("group", "fjordkiosk"), ("merchant", "fjordkiosk as")
    for key in (group, merchant):
        p = _proposal(page_side, key)
        assert p.canonical is not None and p.canonical.id == kiosk, (key, "matched, never new")
    _pin(monkeypatch)
    site = _site(page_side)
    acts = [
        {"id": _proposal(page_side, group).id, "act": "accept"},
        {"id": _proposal(page_side, merchant).id, "act": "reject"},
    ]
    for form in acts:
        response = _post(site, serve.MANIFEST_REVIEW, **form, back="/manifest")
        assert response.status == 303, (form, response.body[:300])
    monkeypatch.setenv("LOGBOOK_HOME", str(cli_side.root))
    _pin(monkeypatch)
    cli.main(["review", "org", "--accept", str(_proposal(cli_side, group).number)])
    cli.main(["review", "org", "--reject", str(_proposal(cli_side, merchant).number)])
    capsys.readouterr()
    lines = _same_record(page_side, cli_side)
    entity, review = lines[-2], lines[-1]
    assert (entity["kind"], entity["tier"]) == ("entity", 2)
    assert entity["payload"]["entity"]["id"] == kiosk and entity["payload"]["label"] == KIOSK
    assert entity["payload"]["refs"] == [{"kind": "group", "value": "fjordkiosk"}]
    assert entity["payload"]["keys"] == {"org": f"domain:{KIOSK_DOMAIN}"}
    assert len(entity["payload"]["evidence"]) == 2, "the two messages, tier 2, cited"
    assert (review["kind"], review["tier"]) == ("entity-review", 3), "the ledger is its evidence"
    assert review["payload"]["entity"]["id"] == kiosk and review["payload"]["label"] == KIOSK
    assert len(review["payload"]["evidence"]) == 3
    assert entity["payload"]["logbook_head"] == entity["prev"]
    assert review["payload"]["logbook_head"] == review["prev"] == entity["hash"]
    left = [p.observed.key for p in entity_review.read(page_side, "org").proposals]
    assert group not in left and merchant not in left, "placed and answered: gone from the queue"


def test_accept_of_a_new_proposal_and_the_form_s_spaces_write_what_the_command_writes(
    settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Four acts the byte test above does not run. Accept of a proposal for a new org (the form offers
    Name; the handler takes `accept` as `--accept N` does: the org named as the sources named it, its
    id minted, the same on both sides). Name with the box emptied to spaces, `--name N "  "`: the
    sources' name again. A hold reaffirmed with a reason typed with tabs, doubled spaces and a line
    break, on a day typed with spaces around it, the org by its id on the command as the page names
    it: the one writer folds the reason and strips the day. And a hold with the reason box left blank,
    what the command without --reason writes. The same bytes."""
    page_side = _copy(settled, tmp_path, monkeypatch, "page")
    cli_side = _copy(settled, tmp_path, monkeypatch, "cli")
    ids = _ids(page_side)
    news, robaat = ("domain", NEWS_DOMAIN), ("domain", ROBAAT_DOMAIN)
    reason = "  came\tback  to it\r\n after the  summer "
    day = " 2026-10-10 "  # as typed: the one writer strips it
    _pin(monkeypatch)
    site = _site(page_side)
    acts: list[tuple[str, dict[str, str]]] = [
        (serve.MANIFEST_REVIEW, {"id": _proposal(page_side, news).id, "act": "accept"}),
        (serve.MANIFEST_REVIEW, {"id": _proposal(page_side, robaat).id, "act": "name", "name": "   "}),
        (serve.MANIFEST_STATUS, {"org": ids[HAVBRIS], "status": "hold", "reason": reason, "at": day}),
        (serve.MANIFEST_STATUS, {"org": ids[KIOSK], "status": "hold", "reason": "   ", "at": ""}),
    ]  # fmt: skip
    for path, form in acts:
        response = _post(site, path, **form, back="/manifest")
        assert response.status == 303, (path, form, response.body[:300])
    monkeypatch.setenv("LOGBOOK_HOME", str(cli_side.root))
    _pin(monkeypatch)
    cli.main(["review", "org", "--accept", str(_proposal(cli_side, news).number)])
    cli.main(["review", "org", "--name", str(_proposal(cli_side, robaat).number), "   "])
    cli.main(["status", "org", ids[HAVBRIS], "hold", "--reason", reason, "--at", day])
    cli.main(["status", "org", KIOSK, "hold"])
    capsys.readouterr()
    lines = _same_record(page_side, cli_side)
    nytt, robaat_line, havbris, kiosk = lines[-4:]
    assert [line["kind"] for line in lines[-4:]] == ["entity", "entity", "status", "status"]
    assert nytt["payload"]["label"] == "Nordmann Nytt", "accepted, not named: the sources' name"
    assert nytt["payload"]["entity"]["id"] == "019cadd3-6bc0-7dcd-9133-000000000900", "minted, the same"
    assert robaat_line["payload"]["label"] == "Nordmann Robåt", "a name of spaces is no name"
    assert robaat_line["payload"]["entity"]["id"] == "019cadd3-6bc0-7dcd-9133-000000000901"
    assert havbris["payload"]["reason"] == "came back to it after the summer", "folded once, by the writer"
    assert havbris["at"] == "2026-10-10T21:59:00Z", "the day's last minute in Oslo"
    assert havbris["payload"]["entity"]["id"] == ids[HAVBRIS]
    assert "reason" not in kiosk["payload"], "a blank box is no reason, as no --reason is"
    assert kiosk["at"] == AT and kiosk["payload"]["status"] == "hold"
    assert not any(line["kind"] == "note" for line in lines), "an org's reason is never a note"


def test_two_acts_in_one_command_rest_on_one_head_the_page_s_two_posts_on_two(
    settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`review org --name N "…" --reject M` is one sitting: the queue is read once and both lines carry
    the head it was read at, so the second line's `logbook_head` is the head before the first line was
    written. The Manifest has no two-act form; each POST reads the queue again under the writer lock,
    so its second line carries the head the first moved it to. That one field (and so the hash) is the
    only difference; one act a command is the page's equal, byte for byte (the tests above)."""
    page_side = _copy(settled, tmp_path, monkeypatch, "page")
    cli_side = _copy(settled, tmp_path, monkeypatch, "cli")
    news, robaat = ("domain", NEWS_DOMAIN), ("domain", ROBAAT_DOMAIN)
    _pin(monkeypatch)
    site = _site(page_side)
    acts = [
        {"id": _proposal(page_side, robaat).id, "act": "name", "name": "Nordmann Robåt AS"},
        {"id": _proposal(page_side, news).id, "act": "reject"},
    ]
    for form in acts:
        assert _post(site, serve.MANIFEST_REVIEW, **form).status == 303, form
    monkeypatch.setenv("LOGBOOK_HOME", str(cli_side.root))
    _pin(monkeypatch)
    before = entity_review.read(cli_side, "org")
    numbers = [str(_proposal(cli_side, key).number) for key in (robaat, news)]
    cli.main(["review", "org", "--name", numbers[0], "Nordmann Robåt AS", "--reject", numbers[1]])
    capsys.readouterr()
    page_lines, cli_lines = _lines(page_side), _lines(cli_side)
    assert page_lines[:-1] == cli_lines[:-1], "the first act, the same bytes"
    named, page_no, cli_no = page_lines[-2], page_lines[-1], cli_lines[-1]
    assert cli_no["payload"]["logbook_head"] == before.head == named["prev"], "the sitting's head"
    assert page_no["payload"]["logbook_head"] == named["hash"] == page_no["prev"], "re-read under the lock"

    def but_the_head(line: dict[str, Any]) -> dict[str, Any]:
        return {**line, "hash": None, "payload": {**line["payload"], "logbook_head": None}}

    assert but_the_head(page_no) == but_the_head(cli_no)


def test_an_act_while_another_command_writes_is_a_409_and_writes_nothing(lb: Logbook) -> None:
    """The owner's word of 14 October 2026: a Library act never waits for another writer; it says so
    in one sentence, a 409, and writes nothing."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = lb._lock_path()
    site = _site(lb)
    report = entity_review.read(lb, "org")
    forms = [
        (serve.MANIFEST_REVIEW, {"id": report.proposals[0].id, "act": "reject"}),
        (serve.MANIFEST_STATUS, {"org": _ids(lb)[KIOSK], "status": "hold", "reason": "came back to it"}),
    ]
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        holder = {"pid": other.pid, "command": "sync immich", "since": "2026-10-12T06:00:00Z"}
        lock.write_text(json.dumps(holder), encoding="utf-8")
        seq = int(lb.meta["seq"])
        for path, form in forms:
            response = _post(site, path, **form)
            body = _text(response.body.decode("utf-8"))
            assert response.status == 409, (path, response.status)
            assert "sync immich" in body and "nothing was written" in body
            assert int(Logbook(lb.root).meta["seq"]) == seq
    finally:
        other.kill()
        other.wait()
        lock.unlink(missing_ok=True)
    assert _post(site, *forms[1][:1], **forms[1][1]).status == 303, "and once it is free, written"


def test_a_page_that_reads_no_tier_three_offers_no_act_and_takes_none(lb: Logbook) -> None:
    """An org's status is tier 3, a no on a merchant may be, and the queue's merchants rest on ledger
    lines: a Manifest read through a gate without tier 3 renders neither the status form nor the
    queue, and refuses both acts, 403, nothing written. `logbook serve` reads every tier."""
    site = _site(lb, tiers=(1, 2))
    kiosk = _ids(lb)[KIOSK]
    for path in ("/manifest", f"/org/{kiosk}"):
        page = _get(site, path)
        assert serve.MANIFEST_STATUS not in page and serve.MANIFEST_REVIEW not in page, path
        assert 'class="proposal"' not in page, path
    seq = lb.meta["seq"]
    report = entity_review.read(lb, "org")
    for path, form in (
        (serve.MANIFEST_STATUS, {"org": kiosk, "status": "hold", "reason": "came back to it"}),
        (serve.MANIFEST_REVIEW, {"id": report.proposals[0].id, "act": "reject"}),
    ):
        refused = _post(site, path, **form)
        assert refused.status == 403 and "tier 3" in _text(refused.body.decode("utf-8")), path
    assert Logbook(lb.root).meta["seq"] == seq
    assert serve.MANIFEST_STATUS in _get(_site(lb), f"/org/{kiosk}"), "every tier read: the form is there"


def test_a_settings_file_the_record_refuses_is_a_500_on_an_act_and_writes_nothing(lb: Logbook) -> None:
    """A `policy/entities.json` that is not what it should be is the record's fault, not the form's:
    the review act, which reads it, answers 500 with the reason, never a dropped connection, and
    writes nothing. (The status act reads no setting of it.)"""
    site = _site(lb)
    report = entity_review.read(lb, "org")
    (lb.root / "policy" / "entities.json").write_text(json.dumps({"merchant_min_lines": 0}), encoding="utf-8")
    seq = lb.meta["seq"]
    response = _post(site, serve.MANIFEST_REVIEW, id=report.proposals[0].id, act="reject")
    assert response.status == 500 and "merchant_min_lines" in response.body.decode("utf-8")
    assert Logbook(lb.root).meta["seq"] == seq


def test_an_act_on_a_stale_or_bad_form_writes_nothing(lb: Logbook) -> None:
    site = _site(lb)
    seq = lb.meta["seq"]
    report = entity_review.read(lb, "org")
    kiosk = _ids(lb)[KIOSK]
    gone = _post(site, serve.MANIFEST_REVIEW, id="0000000000000000", act="reject")
    assert gone.status == 409 and "not in the queue" in gone.body.decode("utf-8")
    assert _post(site, serve.MANIFEST_REVIEW, id=report.proposals[0].id, act="dance").status == 400
    refused = _post(site, serve.MANIFEST_STATUS, org=kiosk, status="let-go", reason=" ")
    assert refused.status == 400 and "must say why" in refused.body.decode("utf-8")
    assert _post(site, serve.MANIFEST_STATUS, org=kiosk, status="dormant").status == 400
    assert _post(site, serve.MANIFEST_STATUS, org=kiosk, status="hold", at="2099-01-01").status == 400
    assert _post(site, serve.MANIFEST_STATUS, org="nobody", status="hold").status == 409
    same = _post(site, serve.MANIFEST_STATUS, org=kiosk, status="passed", reason=PASSED_REASON)
    assert same.status == 400, "the same status with the same reason: main's writer refuses it"
    for path in serve.MANIFEST_PATHS:
        assert site.respond(path, "").status == 405
    assert Logbook(lb.root).meta["seq"] == seq


def test_an_act_from_off_this_machine_is_refused(lb: Logbook) -> None:
    site = _site(lb)
    seq = lb.meta["seq"]
    kiosk = _ids(lb)[KIOSK]
    form = {"org": kiosk, "status": "hold", "reason": "came back to it"}
    for client in ("192.168.1.20", "203.0.113.9", ""):
        response = site.write(serve.MANIFEST_STATUS, form, client, None)
        assert response.status == 403 and "this machine" in response.body.decode("utf-8")
    for origin in ("http://example.org", "http://localhost:8765", "null"):
        assert site.write(serve.MANIFEST_STATUS, form, LOOPBACK, origin).status == 403
    assert Logbook(lb.root).meta["seq"] == seq
    ok = site.write(
        serve.MANIFEST_STATUS, {**form, "back": "https://example.org/x"}, LOOPBACK, "http://127.0.0.1:8765"
    )
    assert ok.status == 303 and ok.location == f"/org/{kiosk}", "a back that is not the server's own: the org"
    assert Logbook(lb.root).meta["seq"] == seq + 1


# -- nothing public changes ------------------------------------------------------------------------------


def test_serving_the_manifest_writes_nothing(lb: Logbook) -> None:
    site = _site(lb)
    site.respond("/manifest", "")  # the observed table, built once, is the index's
    head, before = lb.meta["head"], _files(lb.root)
    for path in ("/manifest", "/manifest/people", *(f"/org/{org}" for org in _ids(lb).values())):
        site.respond(path, "money=1")
    after = _files(lb.root)
    assert Logbook(lb.root).meta["head"] == head
    assert {k: v for k, v in after.items() if not k.startswith("index")} == {
        k: v for k, v in before.items() if not k.startswith("index")
    }


def test_the_exported_site_has_no_manifest_and_names_no_org(
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
    assert not any("manifest" in name or name.startswith("org") for name in files)
    words = (PASSED_REASON, VERFT_REASON, "/manifest", "anti-portfolio", "badge hold", "The Manifest")
    for name, body in files.items():
        text = body.decode("utf-8", "replace")
        for word in words:
            assert word not in text, (name, word)
