"""Nothing of an org's tier-3 lines crosses under a tier-2 policy entry (RFC 0037 §8, §10.2, §10.5,
§11; the owner's decision of 14 October 2026): an org's `status/v1` line is tier 3 with its reason on
the line and never a `note/v1`; the ledger's `transaction/v1` lines are tier 3 and the money is
derived at read time; an `entity/v1` line is tier 2 and never cites a tier-3 line. So a crossing to a
destination whose `policy/crossing.json` entry is `max_tier: 2` carries no org status, no reason, no
ledger line and no figure, and asking that destination for tier 3 is refused with nothing written; a
co-investor edge that rests on a tier-3 line alone is tier 3 and absent through a gate of (1, 2);
every Manifest page through such a gate shows no status, no reason, no money and no transaction; and
the owner's own terminal, which reads every tier, reports the status lines at the tier it shows them,
3. On the synthetic record of `tests/orgs_record.py`: nobody and nothing in it exists."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import UTC, datetime
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
from logbook.contrib import orgs, serve
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
    code, _out, err = _run(capsys, "export", "crossing", "--to", "hermes", "--since", SINCE, "--until", UNTIL,
                           "--tier", "1,2", "--unsigned", "--out", str(out))  # fmt: skip
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
    assert re.search(r"<h1>The Manifest <small>4 orgs[^<]*tier 2</small>", manifest), "the page's tier is 2"
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
