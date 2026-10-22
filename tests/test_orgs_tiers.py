"""Nothing of an org's tier-3 lines crosses under a tier-2 policy entry (RFC 0037 §8, §10.2, §10.5,
§11; the owner's decision of 14 October 2026): an org's `status/v1` line is tier 3 with its reason on
the line and never a `note/v1`; the ledger's `transaction/v1` lines are tier 3 and the money is
derived at read time; an `entity/v1` line is tier 2 and never cites a tier-3 line. So a crossing to a
destination whose `policy/crossing.json` entry is `max_tier: 2` carries no org status, no reason, no
ledger line and no figure, and asking that destination for tier 3 is refused with nothing written; a
co-investor edge that rests on a tier-3 line alone is tier 3 and absent through a gate of (1, 2);
every Manifest page through such a gate shows no status, no reason, no money and no transaction; and
the owner's own terminal, which reads every tier, reports the status lines at the tier it shows them,
3. An org's portfolio (RFC 0037 §10.2, amended 15 October 2026) is a field of its tier-3 status line
and of no other kind's, the latest line that carries it deciding, and goes nowhere tier 3 does not:
no crossing, no shared day and no Notion folder carries it, and no gate without 3 shows it or
filters by it. On the synthetic record of `tests/orgs_record.py`: nobody and nothing in it exists."""

from __future__ import annotations

import dataclasses
import html
import json
import re
import shutil
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from orgs_record import (
    HAVBRIS,
    HAVBRIS_MERCHANT,
    KARI,
    KIOSK,
    PASSED_REASON,
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
from logbook.commands import export as export_command
from logbook.contrib import entities, entity_review, entity_status, notion_export, orgs, serve
from logbook.core import assets, notes, places, policy, store
from logbook.core.store import Logbook

SINCE, UNTIL = "2023-01-01T00:00:00Z", "2026-10-13T00:00:00Z"  # every line of the record is inside
REASONS = (PASSED_REASON, VERFT_REASON, "first cheque", "follow-on with Per")  # every org reason written
AMOUNTS = ("100000", "-120000", "5000.0", "-250000", "-15000")  # on the ledger's lines, or derived from them
LEDGER = (  # a ledger line as the bundle would spell it: its schema, its merchant field
    "transaction/v1",
    f'"merchant": "{HAVBRIS_MERCHANT}"',
    f'"merchant": "{VERFT}"',
)
STATUS_BADGE = re.compile(r'class="badge (?:hold|add|sell|exited|passed|let-go)"')
STATUS_SINCE = re.compile(r"since \d{4}-\d{2}-\d{2} \((?:owner|dream)")


@pytest.fixture(scope="module")
def settled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        lb = evidence_record(tmp_path_factory.mktemp("orgs-tiers"))
        settle(lb)
        return lb.root


@pytest.fixture
def lb(settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(settled, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    return Logbook(root)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    try:
        cli.main(list(argv))
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _record_files(root: Path) -> dict[str, bytes]:
    """The record's own files, the index (rebuilt by any reader) aside."""
    return {k: v for k, v in _files(root).items() if not k.startswith("index")}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def _site(lb: Logbook, tiers: tuple[int, ...] | None = None) -> serve.Site:
    return serve.Site(
        lb, now=lambda: datetime.fromisoformat(f"{TODAY}T12:00:00").replace(tzinfo=UTC), tiers=tiers
    )


def _get(site: serve.Site, path: str, query: str = "") -> str:
    response = site.respond(path, query)
    assert response.status == 200, (path, query, response.status, response.body[:300])
    return response.body.decode("utf-8")


def _text(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def _ids(lb: Logbook) -> dict[str, str]:
    return {o.label: o.id for o in orgs.named(lb).values()}


def _no_org_status(line: dict[str, Any]) -> bool:
    payload = line.get("payload") or {}
    return not (line.get("kind") == "status" and (payload.get("entity") or {}).get("type") == "org")


def _no_org_status_note(line: dict[str, Any]) -> bool:
    payload = line.get("payload") or {}
    about = ((payload.get("extra") or {}).get("entity") or {}).get("type")
    return not (line.get("kind") == "note" and "status" in (payload.get("labels") or []) and about == "org")


# -- the crossing ----------------------------------------------------------------------------------------


def test_a_crossing_under_a_ceiling_of_two_carries_no_org_status_no_reason_and_no_ledger_line(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The settled record, every Havbris wire accepted as the org's merchant: a crossing to `hermes`
    under `max_tier: 2`, over a window that covers every line, carries every tier-2 line and nothing
    of tier 3, and the bytes of the bundle hold no reason and no figure. Then the same destination
    asked for tier 3 is refused, naming the policy file, and nothing is written anywhere."""
    lines = list(lb.lines())
    statuses = [line for line in lines if line["kind"] == "status"]
    wires = [line for line in lines if line["kind"] == "transaction"]
    entity_lines = [line for line in lines if line["kind"] == "entity"]
    # what the record holds, so that what follows is about something
    assert len(statuses) == 5 and {line["tier"] for line in statuses} == {3}, "an org's status is tier 3"
    assert {line["payload"]["entity"]["type"] for line in statuses} == {"org"}
    assert {line["payload"].get("reason") for line in statuses} == {*REASONS, None}, "each reason on its line"
    assert not [line for line in lines if line["kind"] == "note"], (
        "no note/v1 at all: an org's reason is never one"
    )
    assert all(_no_org_status_note(line) for line in lines)
    assert len(wires) == 4 and {line["tier"] for line in wires} == {3}, "the ledger is tier 3"
    assert [line["payload"]["merchant"] for line in wires].count(HAVBRIS_MERCHANT) == 3
    assert ("merchant", "nordmann havbris as") in _named(lb)[HAVBRIS].refs, "the merchant bound to the org"
    tiers = {str(line["id"]): int(line["tier"]) for line in lines}
    # four orgs named, then the group, the code-host org and the merchant accepted: seven lines
    assert len(entity_lines) == 7 and all(line["tier"] == 2 for line in entity_lines), (
        "an entity/v1 is tier 2, the one that binds a merchant too"
    )
    assert all(tiers[cited] <= 2 for line in entity_lines for cited in line["payload"].get("evidence", [])), (
        "an entity/v1 line never cites a tier-3 line (RFC 0037 §8)"
    )

    policy = lb.root / "policy" / "crossing.json"
    policy.write_text(json.dumps({"hermes": {"max_tier": 2}}), encoding="utf-8")
    out = tmp_path / "out"
    # `--all-mail`: this is the tier ceiling's test, and the orgs' mail is no person's (RFC 0045)
    code, _out, err = _run(capsys, "export", "crossing", "--to", "hermes", "--since", SINCE, "--until", UNTIL,
                           "--tier", "1,2", "--unsigned", "--all-mail", "--out", str(out))  # fmt: skip
    assert code == 0, err
    crossed = _jsonl(out / "entries.jsonl")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["policy"]["max_tier"] == 2 and manifest["tiers"] == [1, 2]
    assert manifest["counts"]["logged"] == len(lines), "the window covers every line of the record"
    assert manifest["counts"]["held_back"] == len(statuses) + len(wires), "the tier-3 lines, and only those"
    assert manifest["counts"]["by_tier"]["3"] == 0
    assert crossed and all(int(line["tier"]) <= 2 for line in crossed)
    ids = {str(line["id"]) for line in crossed}
    assert {str(line["id"]) for line in entity_lines} <= ids, "the orgs' names cross at 2"
    assert not ids & {str(line["id"]) for line in statuses}, "no status line of an org"
    assert not ids & {str(line["id"]) for line in wires}, "no ledger line"
    assert all(_no_org_status(line) for line in crossed)
    assert all(line["kind"] != "status" for line in crossed), "every status in this record is an org's"
    assert all(
        line["kind"] != "transaction" and line["payload"].get("schema") != "transaction/v1"
        for line in crossed
    )
    assert all(_no_org_status_note(line) for line in crossed)
    for name, data in sorted(_files(out).items()):
        text = data.decode("utf-8", "replace")
        for word in (*REASONS, *AMOUNTS, *LEDGER, "status/v1"):
            assert word not in text, (name, word)
    # the merchant's name reaches the bundle as the tier-2 entity line's folded `merchant` ref and the
    # review's words that matched it (RFC 0037 §8), on no other line
    named_by = [line for line in crossed if HAVBRIS_MERCHANT in json.dumps(line, ensure_ascii=False)]
    assert named_by and {line["payload"]["schema"] for line in named_by} == {"entity/v1"}
    assert {line["tier"] for line in named_by} == {2}

    # the same destination asked for tier 3: refused before anything is written
    head, before = Logbook(lb.root).meta["head"], _record_files(lb.root)
    refused = tmp_path / "refused"
    code, out_text, err = _run(capsys, "export", "crossing", "--to", "hermes", "--since", SINCE, "--until",
                               UNTIL, "--tier", "1,2,3", "--unsigned", "--out", str(refused))  # fmt: skip
    assert code == 2 and out_text == ""
    assert err.startswith("export crossing: ") and "above the ceiling for 'hermes'" in err
    assert str(policy) in err and "max_tier 2" in err
    assert not refused.exists(), "no bundle"
    assert Logbook(lb.root).meta["head"] == head, "no crossing/v1 line"
    assert _record_files(lb.root) == before, "no watermark, no policy change, nothing"


def _named(lb: Logbook) -> dict[str, Any]:
    return {o.label: o for o in orgs.named(lb).values()}


# -- the co-investor graph ---------------------------------------------------------------------------------


def test_a_co_investor_edge_resting_on_a_tier_three_line_alone_is_tier_three_and_never_under_two(
    lb: Logbook,
) -> None:
    """Kari split a wire to Havbris (`extra.members` of a `transaction/v1` line): the only line that
    puts her with Havbris is tier 3, so her edge between Fjordkiosk and Havbris is tier 3, there with
    money at every tier and absent through a gate of (1, 2), in the reader and on the people page."""
    line = wire(utc("2023-06-20", "12:00"), HAVBRIS_MERCHANT, -15000, "wire-havbris-4")
    line["payload"]["extra"] = {
        "members": [{"ref": {"kind": "email", "value": KARI["email"]}, "name": "Kari"}]
    }
    lb.append_many([line])
    shown = orgs.shelf(lb, money=True, today=TODAY)
    kari = next(g for g in shown.graph if g.name == "Kari Nordmann")
    assert [o.label for o in kari.orgs] == [KIOSK, HAVBRIS] and kari.tier == 3
    assert shown.tier == 3 and shown.money is True
    assert [g["tier"] for g in shown.to_json()["graph"] if g["name"] == "Kari Nordmann"] == [3]

    hidden = orgs.shelf(lb, tiers=(1, 2), money=True, today=TODAY)
    assert hidden.graph, "the edges that rest on meetings stay"
    assert "Kari Nordmann" not in {g.name for g in hidden.graph}
    assert all(g.tier <= 2 for g in hidden.graph)
    data = hidden.to_json()
    assert data["tier"] == 2 and data["money"] is False and data["year"] is None
    assert data["withheld"] == 5 and data["passed"] == []
    assert all(r["money"] is None for r in data["orgs"]), "money asked for, and not shown without 3"
    assert all(r["status"] is None and r["reason"] is None and r["since"] is None for r in data["orgs"])
    assert {r["heading"] for r in data["orgs"]} == {"no status"}
    assert [g["name"] for g in data["graph"]] == ["Per Hansen", "Liv Berg", "Ola Nordmann"], (
        "Kari is one of Fjordkiosk's people at 2 and on no edge: her other org rests on a tier-3 line"
    )
    text = json.dumps(data, ensure_ascii=False)
    for word in (*REASONS, *AMOUNTS, *LEDGER, HAVBRIS_MERCHANT, "NOK", '"status": "hold"', '"status": "add"',
                 '"status": "passed"'):  # fmt: skip
        assert word not in text, word

    page = _get(_site(lb, tiers=(1, 2)), "/manifest/people")
    rows = re.findall(r'<li class="person">(.*?)</li>', page, re.S)
    assert [_text(r).split(" tier")[0] for r in rows] == ["Per Hansen", "Liv Berg", "Ola Nordmann"]
    assert all("tier 1" in _text(r) for r in rows) and "tier 3" not in page
    assert "Kari Nordmann" not in page and HAVBRIS_MERCHANT not in page
    every = re.findall(r'<li class="person">(.*?)</li>', _get(_site(lb), "/manifest/people"), re.S)
    assert "Kari Nordmann" not in [_text(r).split(" tier")[0] for r in every], (
        "at every tier too: the page asks for no money, and without it a ledger line is no touch"
    )


# -- the Manifest pages ------------------------------------------------------------------------------------


def test_through_a_gate_of_one_and_two_every_manifest_page_shows_no_status_no_reason_and_no_money(
    lb: Logbook,
) -> None:
    site = _site(lb, tiers=(1, 2))
    ids = _ids(lb)
    pages = {
        (path, query): _get(site, path, query)
        for path in ("/manifest", "/manifest/people", *(f"/org/{org}" for org in ids.values()))
        for query in ("", "money=1")
    }
    for (path, query), page in pages.items():
        text = _text(page)
        for word in (*REASONS, "NOK", "120,000", "100,000", "5,000", "250,000", "15,000", HAVBRIS_MERCHANT):
            assert word not in text, (path, query, word)
        assert not STATUS_BADGE.search(page), (path, query, "a status badge")
        assert not STATUS_SINCE.search(text), (path, query, "a status's since")
        assert '<p class="reason">' not in page and "the anti-portfolio" not in text, (path, query)
        assert "<h2>holding" not in page and "<h2>passed" not in page, (path, query)
        assert "<h2>Money" not in page and "show the money" not in text, (path, query)
        assert "transaction" not in text, (path, query, "a transaction row, or any word of the ledger")
    manifest = pages[("/manifest", "")]
    assert re.search(
        r'<h1>The Manifest <small title="[^"]*">4 orgs[^<]*nothing read above tier 2</small>', manifest
    ), "the page's tier is 2"
    assert "5 status lines not shown" in _text(manifest) and "<h2>no status</h2>" in manifest
    assert len(re.findall(r'<li id="([^"]+)"', manifest)) == 4, "every org listed, under no status"
    said = "status not shown: an org's status is tier 3, and this reads no tier 3"
    for label, org in ids.items():
        page = pages[(f"/org/{org}", "")]
        assert said in _text(page), (label, said)
        assert not re.search(r"\d+ status lines? not shown", _text(page)), (
            label,
            "an org's page never counts its status lines: a count would tell which orgs have one",
        )
        assert f"{label} <small>org · tier 2</small>" in html.unescape(page), label
        assert "none this page may show" in _text(page), label


# -- the owner's terminal ----------------------------------------------------------------------------------


def test_the_owner_s_terminal_reads_every_tier_and_reports_the_status_lines_at_tier_three(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """`show orgs --json` and `show org NAME --json` read every tier and say so: the shelf is tier 3,
    every row with a status line is tier 3, and every status line in a page's history carries the
    tier it was read at, 3 (RFC 0037 §8)."""
    code, out, _err = _run(capsys, "show", "orgs", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["tier"] == 3 and data["withheld"] == 0
    assert [r["status"] for r in data["orgs"]] == ["hold", "add", "passed", "hold"]
    assert all(r["tier"] == 3 for r in data["orgs"]), "a row with a status line is tier 3"
    assert [p["reason"] for p in data["passed"]] == [PASSED_REASON]
    code, out, _err = _run(capsys, "show", "orgs")
    assert code == 0 and out.splitlines()[0].endswith(" · tier 3 · money not shown"), (
        "read on the clock's day"
    )
    ids = _ids(lb)
    history = {
        VERFT: [("hold", VERFT_REASON)],
        KIOSK: [("passed", PASSED_REASON)],
        TIDEVANN: [("hold", "first cheque"), ("add", "follow-on with Per")],
        HAVBRIS: [("hold", None)],
    }
    for label, expected in history.items():
        code, out, _err = _run(capsys, "show", "org", ids[label], "--json")
        assert code == 0, label
        page = json.loads(out)
        assert page["org"]["label"] == label and page["tier"] == 3 and page["hidden"] is False
        assert [(s["status"], s["reason"], s["tier"], s["standing"]) for s in page["history"]] == [
            (status, reason, 3, True) for status, reason in expected
        ], label
        assert (page["status"]["status"], page["status"]["reason"]) == expected[-1], label
        code, out, _err = _run(capsys, "show", "org", ids[label])
        assert code == 0 and out.splitlines()[0].endswith(" · org · tier 3"), label


# -- the portfolio (RFC 0037 §10.2, amended 15 October 2026) -------------------------------------------------

FUND, ANGEL = "Fund I", "Angel"  # two portfolios, free text as the owner types them
NOW = f"{TODAY}T18:30:00Z"  # 20:30 in Oslo on the sitting's day: the clock the portfolio tests read
IDEA_ID = "019cadd3-6bc0-7dcd-9133-000000000401"
ANY_ENTRY = (1, 2, 3)  # every max_tier a policy/crossing.json entry may hold


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every clock a writer reaches reads NOW: the stamps of the store, the notes, the review writer
    and the exports, and the owner's today (`notes.today_in`), so a status given today is on TODAY."""
    instant = datetime.fromisoformat(NOW)
    for module in (store, notes, entity_review, export_command):
        monkeypatch.setattr(module, "now_utc", lambda: NOW)
    monkeypatch.setattr(notes, "today_in", lambda days: days.today(instant).isoformat())


def _seq(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


def _after(lb: Logbook, seq: int) -> list[dict[str, Any]]:
    return sorted((x for x in Logbook(lb.root).lines() if int(x["seq"]) > seq), key=lambda x: int(x["seq"]))


def _other_kinds(lb: Logbook) -> None:
    """An idea, a place and an asset beside the orgs, each of a kind that takes a status of its own."""
    idea = entities.entity_payload("idea", IDEA_ID, "the fjord kiosk", refs=[("title", "fjord kiosk")])
    entity_review.write_entity(lb, idea, at=utc("2026-10-01", "12:00"))
    places.add(lb.root, places.Place("Hytta", 59.9, 10.75, 120))
    assets.add(lb.root, assets.Asset("solvind", "yacht", "Solvind", mmsi="970000001"))


def _status(capsys: pytest.CaptureFixture[str], lb: Logbook, *argv: str) -> dict[str, Any]:
    """`status org …` through the command; the one line it wrote."""
    seq = _seq(lb)
    code, _out, err = _run(capsys, "status", "org", *argv)
    assert code == 0, (argv, err)
    [line] = _after(lb, seq)
    return line


def _in_portfolios(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """Nordmann Verft and Fjordkiosk in Fund I, Nordmann Tidevann in Angel, Havbris in none."""
    _status(capsys, lb, VERFT, "add", "--portfolio", FUND)
    _status(capsys, lb, KIOSK, "hold", "--reason", "came back to it", "--portfolio", FUND)
    _status(capsys, lb, TIDEVANN, "sell", "--portfolio", ANGEL)


def _nothing_of_a_portfolio(text: str, where: object) -> None:
    for word in (FUND, ANGEL, '"portfolio": "F', '"portfolio": "A', "portfolio Fund", "portfolio Angel"):
        assert word not in text, (where, word)


def test_a_portfolio_rides_on_an_org_s_tier_three_status_line_and_on_no_other_kind_s(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """`status org ORG DISPOSITION --portfolio TEXT` writes one status/v1 line, tier 3, the portfolio in
    its `portfolio` field with its words collapsed, and nothing else: no entity/v1 line, no note. A
    status for an idea, a place or an asset with a portfolio, even an empty one, is refused in one
    sentence before anything is written, and the same status without it is written. The profile and
    the tier rules hold a line to the same."""
    _other_kinds(lb)
    seq = _seq(lb)
    code, out, err = _run(capsys, "status", "org", TIDEVANN, "sell", "--portfolio", "  Fund   I ")
    assert code == 0, err
    [line] = _after(lb, seq)
    assert (line["kind"], line["source"], line["tier"]) == ("status", "manual", 3), "an org's status: tier 3"
    payload = line["payload"]
    assert (payload["status"], payload["portfolio"]) == ("sell", FUND), "its words collapsed"
    assert entities.validate_status(payload) == []
    assert "note" not in payload and "reason" not in payload
    assert f"portfolio {FUND}" in out, "what was written is said"
    # the profile: a string, an empty one clearing, and on an org's line only
    assert entities.validate_status({**payload, "portfolio": ""}) == [], "an empty one clears"
    assert any("portfolio" in p for p in entities.validate_status({**payload, "portfolio": 7}))
    idea = entities.status_payload("idea", IDEA_ID, "the fjord kiosk", "spark", portfolio=FUND)
    assert any("only an org's" in p for p in entities.validate_status(idea))
    # the tier: the line that carries it is an org's status line, tier 3 and never 2
    assert entities.tier_problems(entities.STATUS_SCHEMA, 3, {}, "org") == []
    assert entities.tier_problems(entities.STATUS_SCHEMA, 2, {}, "org"), "an org's status is never at 2"

    head, before = Logbook(lb.root).meta["head"], _record_files(lb.root)
    others = (
        ("idea", "the fjord kiosk", "spark"),
        ("place", "Hytta", "let-go"),
        ("asset", "Solvind", "sold"),
    )
    for kind, name, disposition in others:
        for text in (FUND, "", "   "):
            code, out, err = _run(capsys, "status", kind, name, disposition, "--reason", "because",
                                  "--portfolio", text)  # fmt: skip
            assert (code, out) == (2, ""), (kind, text)
            assert err.startswith("status: ") and err.count("\n") == 1 and "org" in err, (kind, err)
            assert err.rstrip("\n").count(". ") == 0, (kind, "one sentence")
        with pytest.raises(entity_status.StatusError):
            entity_status.write(lb, kind, name, disposition, "because", portfolio=FUND)
    assert Logbook(lb.root).meta["head"] == head, "no line"
    assert _record_files(lb.root) == before, "no note, no registry entry closed: nothing"
    for kind, name, disposition in others:  # the same status, without a portfolio, is written
        code, _out, err = _run(capsys, "status", kind, name, disposition, "--reason", "because")
        assert code == 0, (kind, err)
    written = [x for x in _after(lb, seq) if x["kind"] == "status"]
    assert [x["payload"]["entity"]["type"] for x in written] == ["org", "idea", "place", "asset"]
    assert ["portfolio" in x["payload"] for x in written] == [True, False, False, False]
    assert [x["tier"] for x in written] == [3, 2, 2, 2]
    code, _out, err = _run(capsys, "status", "list", "org", "--portfolio", FUND)
    assert code == 2 and "nothing else" in err


def test_the_writer_refuses_another_kind_s_portfolio_before_it_reads_the_record_or_takes_the_lock(
    lb: Logbook, pinned: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The writer's own check (`entity_status.check_portfolio`), not the profile's: a portfolio for an
    idea, a place or an asset, even an empty one, is refused in the writer's one sentence before
    `entity_status.write` takes the writer lock or reads the record, so here, with both made to fail,
    the refusal is the same and nothing is written. The profile's check on the payload stands behind
    it (`validate_status`), but a line is never built for a kind that takes none."""
    _other_kinds(lb)
    head, before = Logbook(lb.root).meta["head"], _record_files(lb.root)

    def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the record was read, or the writer lock taken, before the refusal")

    monkeypatch.setattr(entity_status, "_read", never)
    monkeypatch.setattr(Logbook, "writer", never)
    others = (
        ("idea", "the fjord kiosk", "spark"),
        ("place", "Hytta", "let-go"),
        ("asset", "Solvind", "sold"),
    )
    for kind, name, disposition in others:
        for text in (FUND, "", "   "):
            code, out, err = _run(capsys, "status", kind, name, disposition, "--reason", "because",
                                  "--portfolio", text)  # fmt: skip
            assert (code, out) == (2, ""), (kind, text, err)
            assert err.startswith("status: a portfolio is an org's") and "takes none" in err, (kind, err)
            assert err.count("\n") == 1 and err.rstrip("\n").count(". ") == 0, (kind, text, "one sentence")
            with pytest.raises(entity_status.StatusError, match="takes none"):
                entity_status.write(lb, kind, name, disposition, "because", portfolio=text)
    assert Logbook(lb.root).meta["head"] == head and _record_files(lb.root) == before, "nothing written"


def test_an_org_s_portfolio_is_the_field_of_its_latest_status_line_that_carries_it(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each status line the writer appends supersedes the one before, yet a line without the field
    leaves the portfolio as it stood: the latest line that carries the field decides, whether or not
    a later one superseded it. A retracted line counts for nothing, so the one before decides again;
    an empty field clears it, and a line without the field after that leaves it cleared. The shelf,
    the page, the status list and the reader itself agree at every step."""

    def now() -> dict[str, str | None]:
        rows = {r.org.label: r.portfolio for r in orgs.shelf(lb, today=TODAY).rows}
        code, out, err = _run(capsys, "show", "org", TIDEVANN, "--json")
        assert code == 0, err
        assert json.loads(out)["portfolio"] == rows[TIDEVANN], "the page and the shelf agree"
        code, out, err = _run(capsys, "status", "list", "org", "--json")
        assert code == 0, err
        listed = {r["label"]: r["portfolio"] for r in json.loads(out)["entities"]}
        assert listed == rows, "the status list and the shelf agree"
        with Logbook(lb.root).index() as idx:
            read = entities.portfolios([*idx.retractions(), *idx.by_kind("status")])
        assert read == {_ids(lb)[label]: p for label, p in rows.items() if p is not None}
        return rows

    assert now() == {VERFT: None, KIOSK: None, TIDEVANN: None, HAVBRIS: None}, "nothing set yet"
    first = _status(capsys, lb, TIDEVANN, "sell", "--portfolio", FUND, "--at", "2026-10-05")
    assert now()[TIDEVANN] == FUND
    quiet = _status(capsys, lb, TIDEVANN, "hold", "--reason", "kept", "--at", "2026-10-07")
    assert quiet["payload"]["supersedes"] == first["id"] and "portfolio" not in quiet["payload"]
    assert now()[TIDEVANN] == FUND, "a status without the field leaves the portfolio as it stood"
    moved = _status(capsys, lb, TIDEVANN, "add", "--portfolio", ANGEL, "--at", "2026-10-09")
    assert now()[TIDEVANN] == ANGEL, "the latest line that carries it"
    Logbook(lb.root).retract(int(moved["seq"]), "entered under the wrong fund")
    assert now()[TIDEVANN] == FUND, "a retracted line counts for nothing: the one before decides again"
    cleared = _status(capsys, lb, TIDEVANN, "sell", "--portfolio", "", "--at", "2026-10-10")
    assert cleared["payload"]["portfolio"] == "", "the field carried, empty"
    assert now()[TIDEVANN] is None, "an empty field clears it"
    _status(capsys, lb, TIDEVANN, "hold", "--reason", "holding again", "--at", "2026-10-11")
    assert now()[TIDEVANN] is None, "a line without the field after it leaves it cleared"
    _status(capsys, lb, TIDEVANN, "add", "--portfolio", " fund  i")
    assert now() == {VERFT: None, KIOSK: None, TIDEVANN: "fund i", HAVBRIS: None}, "one org's line, one org"

    _code, out, _err = _run(capsys, "show", "org", TIDEVANN, "--json")
    history = [(s["status"], s["portfolio"], s["standing"]) for s in json.loads(out)["history"]]
    assert history == [
        ("hold", None, True),
        ("add", None, True),
        ("sell", FUND, True),
        ("hold", None, True),
        ("add", ANGEL, False),
        ("sell", "", True),
        ("hold", None, True),
        ("add", "fund i", True),
    ], "every line says what it carried; the retracted one is said so"
    code, out, _err = _run(capsys, "show", "org", TIDEVANN)
    assert code == 0 and "  portfolio fund i" in out.splitlines()
    code, out, _err = _run(capsys, "show", "orgs")
    [row] = [x for x in out.splitlines() if x.lstrip().startswith(TIDEVANN)]
    assert code == 0 and "add since 2026-10-12 (owner) · portfolio fund i · " in row
    code, out, _err = _run(capsys, "status", "list", "org")
    [row] = [x for x in out.splitlines() if x.lstrip().startswith(TIDEVANN)]
    assert code == 0 and "portfolio fund i" in row


def test_a_change_of_portfolio_is_written_and_a_status_that_changes_nothing_is_still_refused(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0037 §9's key, as amended on 15 October 2026: a status equal to the standing one is
    refused on its day, and on a later day without a new reason, unless it moves the portfolio; a
    line that moves it says something new, the same day too. Giving the portfolio that stands
    changes nothing and is refused as before."""
    assert _status(capsys, lb, VERFT, "hold", "--portfolio", FUND)["payload"]["portfolio"] == FUND, (
        "hold since April, no new reason: written, because it moves the portfolio"
    )
    head = Logbook(lb.root).meta["head"]
    for argv in (("hold",), ("hold", "--portfolio", "fund  I"), ("hold", "--reason", "still")):
        code, _out, err = _run(capsys, "status", "org", VERFT, *argv)
        assert code == 2 and "one status a day" in err, argv
    assert Logbook(lb.root).meta["head"] == head, "nothing written"
    assert _status(capsys, lb, VERFT, "hold", "--portfolio", ANGEL)["payload"]["portfolio"] == ANGEL
    assert _status(capsys, lb, VERFT, "hold", "--portfolio", "")["payload"]["portfolio"] == ""
    code, _out, err = _run(capsys, "status", "org", VERFT, "hold", "--portfolio", "")
    assert code == 2 and "one status a day" in err, "cleared already: nothing to move"
    code, _out, err = _run(capsys, "status", "org", HAVBRIS, "hold", "--portfolio", "", "--at", "2026-10-01")
    assert code == 2 and "to reaffirm it, say why" in err, "none to clear: a later day, no new reason"


def test_a_line_that_only_moves_the_portfolio_keeps_the_day_the_status_took_effect(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A status equal to the standing one, written only to move the portfolio, does not say the status
    began again: the line carries `since`, the day the standing status took effect, so the shelf, the
    page and the status list still say when the hold began, and the stale flag stays where it was. A
    line that also gives a new reason reaffirms, and restarts both, as before. "One status a day"
    reads the line's own day; a respelled portfolio moves nothing, and the refusal names it."""
    ids = _ids(lb)
    moved = _status(capsys, lb, VERFT, "hold", "--portfolio", FUND)
    assert (moved["payload"].get("since"), "reason" in moved["payload"]) == ("2026-04-02", False)
    again = _status(capsys, lb, VERFT, "hold", "--portfolio", ANGEL)  # the same day: it moves again
    assert again["payload"]["since"] == "2026-04-02", "the day the hold took effect, carried on"
    [row] = [r for r in orgs.shelf(lb, today=TODAY).rows if r.org.id == ids[VERFT]]
    assert (row.status.status, row.since, row.portfolio) == ("hold", "2026-04-02", ANGEL)
    code, out, _err = _run(capsys, "show", "org", VERFT, "--json")
    assert code == 0 and json.loads(out)["status"]["since"] == "2026-04-02"
    code, out, _err = _run(capsys, "status", "list", "org", "--json")
    [listed] = [r for r in json.loads(out)["entities"] if r["id"] == ids[VERFT]]
    assert code == 0 and (listed["since"], listed["portfolio"]) == ("2026-04-02", ANGEL)
    head = Logbook(lb.root).meta["head"]
    code, _out, err = _run(capsys, "status", "org", VERFT, "hold", "--reason", "still")
    assert code == 2 and "one status a day" in err, "two lines today already: the line's own day"
    code, _out, err = _run(capsys, "status", "org", VERFT, "hold", "--portfolio", "angel")
    assert code == 2 and f"in {ANGEL} already" in err and "one status a day" in err, err
    assert Logbook(lb.root).meta["head"] == head

    def havbris() -> orgs.Row:
        [found] = [r for r in orgs.shelf(lb, today=TODAY).rows if r.org.id == ids[HAVBRIS]]
        return found

    assert (havbris().since, havbris().stale) == ("2023-06-15", True), "a hold gone stale"
    quiet = _status(capsys, lb, HAVBRIS, "hold", "--portfolio", FUND)
    assert quiet["payload"]["since"] == "2023-06-15"
    assert (havbris().since, havbris().stale, havbris().portfolio) == ("2023-06-15", True, FUND), (
        "moving the portfolio is no fresh look at the position: still stale"
    )
    looked = _status(capsys, lb, HAVBRIS, "hold", "--reason", "still holding", "--portfolio", ANGEL)
    assert "since" not in looked["payload"], "a new reason reaffirms: the hold is restated today"
    assert (havbris().since, havbris().stale, havbris().portfolio) == (TODAY, False, ANGEL)


# -- the portfolio's reader rule, line by line -------------------------------------------------------------

ORG_A, ORG_B = "019cadd3-6bc0-7dcd-9133-000000000501", "019cadd3-6bc0-7dcd-9133-000000000502"
LINE_ID = "019cadd3-6bc0-7dcd-9133-0000000006{seq:02d}"


def _line(seq: int, kind: str, payload: dict[str, Any], at: str) -> dict[str, Any]:
    envelope = {"at": at, "end": None, "tz": "Europe/Oslo", "source": "manual", "kind": kind}
    tier = 3 if kind == "status" else 2
    return {"seq": seq, "id": LINE_ID.format(seq=seq), **envelope, "tier": tier, "payload": payload}


def _crafted_status(
    seq: int, status: str, day: str, org: str = ORG_A, kind: str = "org", **field: Any
) -> dict[str, Any]:
    """A status/v1 line as a hand would craft it: `portfolio=` carried only when given."""
    payload = {
        "schema": "status/v1",
        "entity": {"type": kind, "id": org},
        "status": status,
        "proposed_by": "owner",
    }
    return _line(seq, "status", {**payload, **field}, f"{day}T10:00:00Z")


def _crafted_retraction(seq: int, of_seq: int) -> dict[str, Any]:
    hide = {
        "schema": "retraction/v1",
        "supersedes": LINE_ID.format(seq=of_seq),
        "seq": of_seq,
        "reason": "wrong",
    }
    return _line(seq, "retraction", hide, "2026-10-12T10:00:00Z")


def test_the_portfolio_reader_takes_the_last_carrying_line_in_chain_order_of_an_org_s_lines_alone() -> None:
    """`entities.portfolios` over crafted lines, the record aside: chain order (`seq`) decides, not the
    day, so a line backdated before the one before it still decides, as it decides the current status;
    the value's words are collapsed; a line of another kind, even one whose disposition is also an
    org's (a place let go), an org's line with a disposition not an org's, and a value that is not a
    string count for nothing; a legacy `company` is an org; a retraction hides a line and a retraction
    of that retraction (which the writer refuses, RFC 0003 rule 1) does not bring it back, for the
    portfolio exactly as for the status; a whitespace-only value clears; the order given is nothing."""
    lines = [
        _crafted_status(1, "hold", "2026-10-01", portfolio="  Fund   I "),
        _crafted_status(2, "add", "2026-10-03"),
        _crafted_status(3, "hold", "2026-10-03", org=ORG_B, kind="company", portfolio=ANGEL),
        _crafted_status(4, "let-go", "2026-10-04", org="Hytta", kind="place", reason="sold", portfolio=FUND),
        _crafted_status(5, "spark", "2026-10-04", portfolio="Nope"),
        _crafted_status(6, "sell", "2026-10-09", portfolio="Fund II"),
        _crafted_status(7, "hold", "2026-10-05", portfolio=ANGEL),  # backdated: an earlier day, a later seq
        _crafted_status(8, "add", "2026-10-10", portfolio=7),
        _crafted_retraction(9, 7),
        _crafted_retraction(10, 9),
        _crafted_status(11, "hold", "2026-10-11", portfolio="   "),
        _crafted_status(12, "add", "2026-10-12"),
    ]
    held = {ORG_B: ANGEL}
    expected = {
        1: {ORG_A: FUND}, 2: {ORG_A: FUND}, 3: {ORG_A: FUND, **held}, 4: {ORG_A: FUND, **held},
        5: {ORG_A: FUND, **held}, 6: {ORG_A: "Fund II", **held}, 7: {ORG_A: ANGEL, **held},
        8: {ORG_A: ANGEL, **held}, 9: {ORG_A: "Fund II", **held}, 10: {ORG_A: "Fund II", **held},
        11: held, 12: held,
    }  # fmt: skip
    for n, want in expected.items():
        assert entities.portfolios(lines[:n]) == want, n
        assert entities.portfolios(reversed(lines[:n])) == want, (n, "in any order")
    standing = entities.statuses(lines)
    assert [s.seq for s in standing[("org", ORG_A)]] == [1, 2, 6, 8, 11, 12], (
        "the same lines stand for the status"
    )
    assert standing[("org", ORG_B)][0].kind == "org" and ("place", "Hytta") in standing
    assert entities.portfolio_field({"portfolio": " a  b "}) == "a b" and entities.portfolio_field({}) is None
    assert (
        entities.portfolio_field({"portfolio": "  "}) == ""
        and entities.portfolio_field({"portfolio": 7}) is None
    )


def test_a_status_backdated_before_the_standing_one_decides_the_portfolio_as_it_decides_the_status(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--at` a day before the standing status's day: the line comes later in the chain, supersedes the
    standing one and is the current status (`entities.statuses`, chain order), so its portfolio is the
    org's too, whatever the days say; the shelf, the page, the status list and the reader agree. A
    whitespace-only portfolio is the empty one: it clears."""
    sell = _status(capsys, lb, TIDEVANN, "sell", "--portfolio", FUND, "--at", "2026-10-09")
    back = _status(capsys, lb, TIDEVANN, "hold", "--reason", "re-read the papers", "--portfolio", ANGEL,
                   "--at", "2026-10-05")  # fmt: skip
    assert back["at"] < sell["at"] and int(back["seq"]) > int(sell["seq"]), "earlier day, later in the chain"
    assert back["payload"]["supersedes"] == sell["id"]
    code, out, err = _run(capsys, "show", "org", TIDEVANN, "--json")
    assert code == 0, err
    page = json.loads(out)
    assert (page["status"]["status"], page["status"]["since"]) == ("hold", "2026-10-05"), "chain order"
    assert page["portfolio"] == ANGEL, "the same order decides the portfolio"
    [row] = [r for r in orgs.shelf(lb, today=TODAY).rows if r.org.label == TIDEVANN]
    assert (row.status.status, row.since, row.portfolio) == ("hold", "2026-10-05", ANGEL)
    code, out, err = _run(capsys, "status", "list", "org", "--json")
    assert code == 0, err
    [listed] = [r for r in json.loads(out)["entities"] if r["label"] == TIDEVANN]
    assert (listed["status"], listed["portfolio"]) == ("hold", ANGEL)
    with Logbook(lb.root).index() as idx:
        assert entities.portfolios([*idx.retractions(), *idx.by_kind("status")])[_ids(lb)[TIDEVANN]] == ANGEL
    blank = _status(capsys, lb, TIDEVANN, "hold", "--portfolio", "   ")
    assert blank["payload"]["portfolio"] == "", "whitespace alone is the empty one: it clears"
    assert all(r.portfolio is None for r in orgs.shelf(lb, today=TODAY).rows if r.org.label == TIDEVANN)


def test_an_org_named_by_its_status_lines_alone_keeps_its_portfolio(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0037 §3.4 rule 3: every `entity/v1` line naming the org retracted, its status lines standing,
    the org stays named under the status line's label, and its portfolio is read from those lines as
    before: on the shelf, on the page, and through the filter."""
    _in_portfolios(lb, capsys)
    org = _ids(lb)[TIDEVANN]
    with Logbook(lb.root).index() as idx:
        naming = [x for x in idx.by_kind("entity") if x["payload"]["entity"]["id"] == org]
    assert naming, "the record names it by entity/v1 lines"
    for line in naming:
        Logbook(lb.root).retract(int(line["seq"]), "named twice")
    assert _ids(lb)[TIDEVANN] == org, "still named, by its status lines"
    [row] = [r for r in orgs.shelf(lb, today=TODAY).rows if r.org.id == org]
    assert (row.org.label, row.portfolio) == (TIDEVANN, ANGEL)
    code, out, err = _run(capsys, "show", "org", TIDEVANN, "--json")
    assert code == 0, err
    assert json.loads(out)["portfolio"] == ANGEL
    code, out, err = _run(capsys, "show", "orgs", "--portfolio", ANGEL, "--json")
    assert code == 0 and [r["id"] for r in json.loads(out)["orgs"]] == [org], err


def test_through_a_gate_without_tier_three_the_record_itself_holds_no_portfolio(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The record read through a gate without tier 3 holds no portfolio at all, not one it then
    withholds (`orgs._read` reads them only when the gate reads 3), so no row, page or filter built
    from it can carry one; and a record that held one would still say none through such a gate.
    Through (1, 2, 3), and through no gate at all, it holds each org's, by id."""
    _in_portfolios(lb, capsys)
    ids = _ids(lb)
    for tiers in ((1, 2), (2,)):  # the orgs are named by tier-2 lines, so these gates still name them
        gated = orgs.read(lb, orgs.gate(tiers), TODAY)
        assert ids[VERFT] in gated.orgs and not gated.statuses_read, tiers
        assert gated.portfolios == {} and all(gated.portfolio(o) is None for o in gated.orgs), tiers
        assert orgs.held(gated) == [] and orgs.page_of(lb, gated, ids[VERFT]).portfolio is None, tiers
        assert orgs.shelf_of(lb, gated, portfolio=FUND).rows == [], tiers
        leaky = dataclasses.replace(gated, portfolios={o: FUND for o in gated.orgs})
        assert all(leaky.portfolio(o) is None for o in leaky.orgs) and orgs.held(leaky) == [], tiers
    for tiers in ((1, 2, 3), None):
        every = orgs.read(lb, orgs.gate(tiers), TODAY)
        assert every.portfolios == {ids[VERFT]: FUND, ids[KIOSK]: FUND, ids[TIDEVANN]: ANGEL}, tiers
        assert orgs.held(every) == [ANGEL, FUND], tiers


# -- the portfolio stays home --------------------------------------------------------------------------------


def test_no_crossing_carries_a_portfolio_under_any_entry(
    lb: Logbook, pinned: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under an entry of every ceiling, `export crossing` at the most the entry lets cross without
    the owner typing tier 3 (ADR 0016: a policy edit alone never lets tier 3 cross) carries no status
    line and no word of a portfolio; an entry below 3 refuses tier 3 asked for, writing nothing."""
    _in_portfolios(lb, capsys)
    policy_file = lb.root / "policy" / "crossing.json"
    for ceiling in ANY_ENTRY:
        policy_file.write_text(json.dumps({"hermes": {"max_tier": ceiling}}), encoding="utf-8")
        tiers = "1" if ceiling == 1 else "1,2"
        out = tmp_path / f"crossing-{ceiling}"
        code, _out, err = _run(capsys, "export", "crossing", "--to", "hermes", "--since", SINCE, "--until",
                               UNTIL, "--tier", tiers, "--unsigned", "--out", str(out))  # fmt: skip
        assert code == 0, (ceiling, err)
        crossed = _jsonl(out / "entries.jsonl")
        assert crossed and all(line["kind"] != "status" for line in crossed), ceiling
        assert all("portfolio" not in json.dumps(line["payload"]) for line in crossed), ceiling
        for name, data in sorted(_files(out).items()):
            _nothing_of_a_portfolio(data.decode("utf-8", "replace"), (ceiling, name))
        if ceiling < 3:
            head, before = Logbook(lb.root).meta["head"], _record_files(lb.root)
            refused = tmp_path / f"refused-{ceiling}"
            code, _out, err = _run(capsys, "export", "crossing", "--to", "hermes", "--since", SINCE,
                                   "--until", UNTIL, "--tier", "1,2,3", "--unsigned", "--out",
                                   str(refused))  # fmt: skip
            assert code == 2 and "above the ceiling" in err and not refused.exists(), ceiling
            assert Logbook(lb.root).meta["head"] == head and _record_files(lb.root) == before, ceiling


def test_no_shared_day_carries_a_portfolio_under_any_entry(
    lb: Logbook, pinned: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The day the portfolios were written, shared under an entry of every ceiling, at the default
    tier and at the most the entry lets go without the owner typing 3: no status line, no word of a
    portfolio in the page; an entry below 3 refuses `--tier 3`, writing nothing."""
    _in_portfolios(lb, capsys)
    policy_file = lb.root / "policy" / "crossing.json"
    for ceiling in ANY_ENTRY:
        policy_file.write_text(json.dumps({"ola": {"max_tier": ceiling}}), encoding="utf-8")
        for tier in (min(ceiling, 2), None):  # the most it lets go untyped, and the default
            out = tmp_path / f"share-{ceiling}-{tier}.zip"
            asked = () if tier is None else ("--tier", str(tier))
            code, _out, err = _run(
                capsys, "export", "share", "day", TODAY, "--to", "ola", *asked, "--out", str(out)
            )
            assert code == 0, (ceiling, tier, err)
            with zipfile.ZipFile(out) as page:
                members = {name: page.read(name) for name in page.namelist()}
            lines = _jsonl_bytes(members["lines.jsonl"])
            assert all(line["kind"] != "status" for line in lines), (ceiling, tier)
            assert lines or (tier or 1) < 2, (ceiling, tier, "the orgs named that day are tier 2 and go")
            held_back = json.loads(members["manifest.json"])["held_back"]
            assert held_back >= 3, (ceiling, tier, "the three status lines of the day stay home")
            for name, data in sorted(members.items()):
                _nothing_of_a_portfolio(data.decode("utf-8", "replace"), (ceiling, tier, name))
        if ceiling < 3:
            head = Logbook(lb.root).meta["head"]
            code, _out, err = _run(capsys, "export", "share", "day", TODAY, "--to", "ola", "--tier", "3",
                                   "--out", str(tmp_path / f"refused-{ceiling}.zip"))  # fmt: skip
            assert code == 2 and "above the ceiling" in err, ceiling
            assert Logbook(lb.root).meta["head"] == head, ceiling


def test_no_notion_folder_carries_a_portfolio_under_any_entry(
    lb: Logbook,
    pinned: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`export notion` under a `notion` entry of every ceiling, unsigned days let in: the orgs reach
    the folder as touched, never with a status or a portfolio (tier 3 never goes to Notion)."""
    _in_portfolios(lb, capsys)
    monkeypatch.setattr(policy, "today", lambda: date.fromisoformat(TODAY))
    policy_file = lb.root / "policy" / "crossing.json"
    for ceiling in ANY_ENTRY:
        entry = {"max_tier": ceiling, "write": [], "include_unsigned": True}
        policy_file.write_text(json.dumps({"notion": entry}), encoding="utf-8")
        out = tmp_path / f"notion-{ceiling}"
        code, _out, err = _run(
            capsys, "export", "notion", str(out), "--since", "2023-01-01", "--include-unsigned"
        )
        assert code == 0, (ceiling, err)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["tiers"] == [t for t in (1, 2) if t <= ceiling], "tier 3 never goes to Notion"
        if ceiling >= 2:
            assert json.loads((out / "orgs.json").read_text(encoding="utf-8"))["orgs"], "the orgs are there"
        for name, data in sorted(_files(out).items()):
            _nothing_of_a_portfolio(data.decode("utf-8", "replace"), (ceiling, name))
    assert notion_export.TIERS == (1, 2)


def test_through_a_gate_without_tier_three_no_portfolio_is_shown_and_none_filters(
    lb: Logbook, pinned: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every tier read (the owner's terminal, `logbook serve`): `show orgs --portfolio` and the
    Manifest's filter show the orgs in that portfolio, case and spaces aside, and the org's page its
    portfolio. Through a gate of (1, 2): no row carries a portfolio, no filter is offered, and a filter
    asked for shows no org at all, the same for a portfolio that holds orgs and one that holds none,
    so that nothing tells which orgs a portfolio holds."""
    _in_portfolios(lb, capsys)
    ids = _ids(lb)
    code, out, err = _run(capsys, "show", "orgs", "--portfolio", "fund  i", "--json")
    assert code == 0, err
    data = json.loads(out)
    assert sorted(r["name"] for r in data["orgs"]) == [KIOSK, VERFT]
    assert {r["portfolio"] for r in data["orgs"]} == {FUND} and data["portfolios"] == [ANGEL, FUND]
    code, out, _err = _run(capsys, "show", "orgs", "--portfolio", ANGEL)
    assert out.splitlines()[0].startswith(f"orgs · 1 in {ANGEL} · ")
    assert [x.strip().split("  ")[0] for x in out.splitlines() if x.startswith("  N")] == [TIDEVANN]
    code, out, _err = _run(capsys, "show", "orgs", "--portfolio", "Fund IX")
    assert code == 0 and "no org is in Fund IX" in out and f"{ANGEL}, {FUND}" in out
    code, _out, err = _run(capsys, "show", "orgs", "--portfolio", "  ")
    assert code == 2 and "--portfolio" in err
    code, _out, err = _run(capsys, "show", "org", VERFT, "--portfolio", FUND)
    assert code == 2 and "show orgs" in err

    every = _site(lb)
    manifest = _get(every, "/manifest")
    assert f'href="/manifest?portfolio={FUND.replace(" ", "%20")}"' in manifest, "the filter, offered"
    filtered = _get(every, "/manifest", f"portfolio={FUND.replace(' ', '%20')}")
    assert sorted(re.findall(r'<li id="([^"]+)"', filtered)) == sorted([ids[VERFT], ids[KIOSK]])
    assert 'name="back" value="/manifest?page=1&amp;portfolio=Fund%20I"' in filtered, (
        "the queue's acts come back to the filtered shelf"
    )
    page = _get(every, f"/org/{ids[TIDEVANN]}")
    assert f"portfolio {ANGEL}" in _text(page) and f'name="portfolio" value="{ANGEL}"' in page
    assert _get(every, "/manifest", "portfolio=%20%20") == manifest, "a blank filter is every org"

    for asked in (None, FUND, ANGEL, "Fund IX"):
        shelf = orgs.shelf(lb, tiers=(1, 2), portfolio=asked, today=TODAY)
        data = shelf.to_json()
        assert data["portfolios"] == [], asked
        assert [r["name"] for r in data["orgs"]] == ([] if asked else [r.org.label for r in shelf.rows])
        if asked is None:
            assert len(data["orgs"]) == 4 and all(r["portfolio"] is None for r in data["orgs"])
        text = json.dumps({k: v for k, v in data.items() if k != "portfolio"}, ensure_ascii=False)
        _nothing_of_a_portfolio(text + "\n".join(orgs.shelf_rows(shelf)).replace(f"in {asked}", ""), asked)
    gated = _site(lb, tiers=(1, 2))
    pages = {
        asked: _get(gated, "/manifest", f"portfolio={asked.replace(' ', '%20')}")
        for asked in (FUND, "Fund IX")
    }
    assert pages[FUND] == pages["Fund IX"], "one answer for every portfolio asked: no oracle"
    assert not re.findall(r'<li id="', pages[FUND]) and "a portfolio is tier 3" in _text(pages[FUND])
    for path in ("/manifest", *(f"/org/{org}" for org in ids.values())):
        _nothing_of_a_portfolio(_get(gated, path), path)
        assert "?portfolio=" not in _get(gated, path), path


def _jsonl_bytes(data: bytes) -> list[dict[str, Any]]:
    return [json.loads(s) for s in data.decode("utf-8").splitlines() if s.strip()]


# -- the form ------------------------------------------------------------------------------------------------


def _pin_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ids the store mints from one sequence, called once per side, so the same lines get the
    same ids on each."""
    ids = iter(f"019cadd3-6bc0-7dcd-9133-0000000007{n:02d}" for n in range(100))
    monkeypatch.setattr(store, "uuid7", lambda: next(ids))


def _post(site: serve.Site, path: str, **form: str) -> serve.Response:
    return site.write(path, form, "127.0.0.1", None)


def test_the_status_form_s_portfolio_writes_what_the_command_writes_byte_for_byte(
    settled: Path,
    tmp_path: Path,
    pinned: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The org page's status form and `status org` on two copies of one record, every clock and id
    pinned: a portfolio typed (its spaces as typed), a box emptied (`--portfolio ""`), a box left as
    the page showed it (no `--portfolio` at all), with and without a reason and a day. The same
    lines, the same head, the month files byte for byte."""
    page_side, cli_side = (tmp_path / "page", tmp_path / "cli")
    shutil.copytree(settled, page_side)
    shutil.copytree(settled, cli_side)
    monkeypatch.setenv("LOGBOOK_HOME", str(page_side))
    page_lb = Logbook(page_side)
    ids = _ids(page_lb)
    _pin_ids(monkeypatch)
    site = _site(page_lb)
    forms = [
        {"org": ids[VERFT], "status": "add", "portfolio": "  Fund   I", "portfolio_was": ""},
        {"org": ids[TIDEVANN], "status": "hold", "reason": "back to holding", "at": "2026-10-11",
         "portfolio": ANGEL, "portfolio_was": ""},
        {"org": ids[VERFT], "status": "sell", "reason": "", "at": "", "portfolio": "", "portfolio_was": FUND},
        {"org": ids[KIOSK], "status": "hold", "reason": "came back to it",
         "portfolio": "", "portfolio_was": ""},
        {"org": ids[TIDEVANN], "status": "add", "portfolio": f" {ANGEL} ", "portfolio_was": ANGEL},
        {"org": ids[TIDEVANN], "status": "sell", "portfolio": "angel", "portfolio_was": ANGEL},
    ]  # fmt: skip
    for form in forms:
        response = _post(site, serve.MANIFEST_STATUS, **form, back=f"/org/{form['org']}")
        assert response.status == 303, (form, response.body[:300])
    monkeypatch.setenv("LOGBOOK_HOME", str(cli_side))
    _pin_ids(monkeypatch)
    for argv in (
        (VERFT, "add", "--portfolio", "  Fund   I"),
        (TIDEVANN, "hold", "--reason", "back to holding", "--at", "2026-10-11", "--portfolio", ANGEL),
        (VERFT, "sell", "--portfolio", ""),
        (KIOSK, "hold", "--reason", "came back to it"),
        (TIDEVANN, "add"),
        (TIDEVANN, "sell", "--portfolio", "angel"),
    ):
        code, _out, err = _run(capsys, "status", "org", *argv)
        assert code == 0, (argv, err)
    page_lines = sorted(Logbook(page_side).lines(), key=lambda x: int(x["seq"]))
    cli_lines = sorted(Logbook(cli_side).lines(), key=lambda x: int(x["seq"]))
    assert page_lines == cli_lines
    carried = [x["payload"].get("portfolio") for x in page_lines[-6:]]
    assert carried == [FUND, ANGEL, "", None, None, "angel"], (
        "a box left alone carries none; a box respelled carries the new spelling, as the command does"
    )
    assert [x["tier"] for x in page_lines[-6:]] == [3] * 6
    assert Logbook(page_side).meta["head"] == Logbook(cli_side).meta["head"]
    files = sorted((page_side / "logbook").rglob("*.jsonl"))
    assert files and [f.read_bytes() for f in files] == [
        (cli_side / f.relative_to(page_side)).read_bytes() for f in files
    ], "the month files, byte for byte"


def test_the_portfolio_form_while_another_command_writes_is_a_409_and_writes_nothing(
    lb: Logbook, pinned: None
) -> None:
    """The form's portfolio goes through the one writer under the record's lock, never waiting: while
    another command writes, a 409 in one sentence, nothing written; once it is free, written. Through
    a gate without tier 3 there is no form, and its post is refused."""
    import subprocess
    import sys

    site = _site(lb)
    org = _ids(lb)[VERFT]
    form = {"org": org, "status": "add", "portfolio": FUND, "portfolio_was": ""}
    page = _get(site, f"/org/{org}")
    assert 'name="portfolio"' in page and 'name="portfolio_was"' in page and serve.MANIFEST_STATUS in page
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = lb._lock_path()
    seq = _seq(lb)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        holder = {"pid": other.pid, "command": "sync immich", "since": "2026-10-12T06:00:00Z"}
        lock.write_text(json.dumps(holder), encoding="utf-8")
        response = _post(site, serve.MANIFEST_STATUS, **form)
        body = _text(response.body.decode("utf-8"))
        assert response.status == 409 and "sync immich" in body and "nothing was written" in body
        assert _seq(lb) == seq
    finally:
        other.kill()
        other.wait()
        lock.unlink(missing_ok=True)
    gated = _site(lb, tiers=(1, 2))
    assert 'name="portfolio"' not in _get(gated, f"/org/{org}")
    assert _post(gated, serve.MANIFEST_STATUS, **form).status == 403 and _seq(lb) == seq
    assert _post(site, serve.MANIFEST_STATUS, **form).status == 303, "and once it is free, written"
    [line] = _after(lb, seq)
    assert line["payload"]["portfolio"] == FUND and line["tier"] == 3
