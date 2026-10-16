"""The named orgs read back — `show orgs` (the shelf), `show org NAME` (one org's page) and the
readers under them in `logbook.contrib.orgs`, over the lines main's entities foundation writes: the
orgs under the headings of RFC 0037 §11, the most recent touch first, a stale flag by the reader's
rule (`policy/entities.json` `stale_days`, the status and the last touch); the anti-portfolio; the
people who appear with more than one org, each edge as high a tier as its lines; one org's timeline,
people, introductions, documents and status lines; money derived from the ledger at read time and
shown only when asked and through a gate that holds tier 3; an org's status, and its reason on that
line, never through a gate without 3. On the synthetic record of `tests/orgs_record.py`: nobody and
nothing in it exists."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from orgs_record import (
    HAVBRIS,
    KARI,
    KIOSK,
    PASSED_REASON,
    TIDEVANN,
    TODAY,
    VERFT,
    VERFT_DOMAIN,
    VERFT_REASON,
    evidence_record,
    settle,
    wire,
)
from persona import utc

from logbook import cli
from logbook.contrib import entity_status, orgs
from logbook.core.store import Logbook


@pytest.fixture(scope="module")
def settled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        lb = evidence_record(tmp_path_factory.mktemp("orgs-shelf"))
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


# -- the shelf -------------------------------------------------------------------------------------------


def test_the_shelf_puts_the_orgs_under_their_status_the_most_recent_touch_first(lb: Logbook) -> None:
    s = orgs.shelf(lb, today=TODAY)
    assert [(name, [r.org.label for r in rows]) for name, rows in s.grouped()] == [
        ("holding", [VERFT, TIDEVANN, HAVBRIS]),
        ("passed", [KIOSK]),
    ]
    assert [r.last.day if r.last else None for r in s.rows] == [
        "2026-10-09",
        "2026-10-01",
        "2026-04-20",
        "2023-07-01",
    ], "Havbris's last touch is its last wire: a ledger line touches it, money or not"
    assert s.rows[3].last_text == "the ledger", "without money: no merchant, no figure"
    assert [r.status.status if r.status else None for r in s.rows] == ["hold", "add", "passed", "hold"]
    assert [r.since for r in s.rows] == ["2026-04-02", "2026-10-02", "2026-06-14", "2023-06-15"]
    verft = s.rows[0]
    assert verft.last_text == 'group "Nordmann Verft": message from Ola'
    assert [p.name for p in verft.people] == ["Ola Nordmann", "Per Hansen", "Liv Berg"], "the most days first"
    assert verft.documents == 3 and verft.money is None
    assert s.tier == 3 and s.withheld == 0, "the status lines are tier 3, and every one is read"
    assert s.on == TODAY and s.money is False


def test_a_hold_with_nothing_for_three_years_is_stale_and_a_passed_never_is(lb: Logbook) -> None:
    """Main's rule (`stale_days`, a hold over 1095 days), counted from the later of the status's
    day and the last touch (RFC 0037 §10.6), its last wire."""
    s = orgs.shelf(lb, today=TODAY)
    stale = {r.org.label: (r.stale, r.stale_since) for r in s.rows}
    assert stale[HAVBRIS] == (True, "2023-07-01"), "held since 2023-06-15, its last wire 2023-07-01"
    assert stale[KIOSK] == (False, None), "passed: a status the setting does not name is never stale"
    assert stale[VERFT] == (False, None) and stale[TIDEVANN] == (False, None)
    assert not orgs.shelf(lb, today="2026-06-30").rows[-1].stale, "1095 days to the day is not over"
    assert orgs.shelf(lb, today="2026-07-01").rows[-1].stale
    path = lb.root / "policy" / "entities.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**settings, "stale_days": {"add": 5}}), encoding="utf-8")
    assert {r.org.label for r in orgs.shelf(lb, today=TODAY).rows if r.stale} == {HAVBRIS, TIDEVANN}, (
        "add after 5 days: the status on 2026-10-02, the last touch on 2026-10-01"
    )


def test_the_anti_portfolio_is_the_passed_orgs_with_their_reasons(lb: Logbook) -> None:
    s = orgs.shelf(lb, today=TODAY)
    [passed] = s.passed
    assert passed.org.label == KIOSK and passed.status is not None
    assert passed.status.reason == PASSED_REASON and passed.since == "2026-06-14"
    assert s.to_json()["passed"] == [{"id": passed.org.id, "name": KIOSK, "reason": PASSED_REASON}]


def test_the_co_investor_graph_is_everyone_with_more_than_one_org(lb: Logbook) -> None:
    graph = orgs.shelf(lb, today=TODAY).graph
    assert [(g.name, [o.label for o in g.orgs], g.tier) for g in graph] == [
        ("Per Hansen", [KIOSK, TIDEVANN, VERFT], 1),
        ("Liv Berg", [TIDEVANN, VERFT], 1),
        ("Ola Nordmann", [TIDEVANN, VERFT], 1),
    ], "the meetings put each with each org, and a calendar entry is tier 1"
    assert all(g.name not in ("Kari Nordmann", "Anders Vik") for g in graph), "one org each"


def test_a_co_investor_edge_from_a_tier_three_line_is_tier_three_and_never_under_two(lb: Logbook) -> None:
    """Kari split a payment to Havbris (the ledger's `extra.members`): the only line that puts her
    with Havbris is tier 3, so the edge between Fjordkiosk and Havbris is tier 3, shown with money
    and through no gate without 3."""
    line = wire(utc("2023-06-20", "12:00"), "NORDMANN HAVBRIS AS", -15000, "wire-havbris-4")
    line["payload"]["extra"] = {
        "members": [{"ref": {"kind": "email", "value": KARI["email"]}, "name": "Kari"}]
    }
    lb.append_many([line])
    shown = {g.name: g for g in orgs.shelf(lb, money=True, today=TODAY).graph}
    assert [o.label for o in shown["Kari Nordmann"].orgs] == [KIOSK, HAVBRIS] and shown[
        "Kari Nordmann"
    ].tier == 3
    assert orgs.shelf(lb, money=True, today=TODAY).tier == 3
    for hidden in (orgs.shelf(lb, today=TODAY), orgs.shelf(lb, tiers=(1, 2), money=True, today=TODAY)):
        assert "Kari Nordmann" not in {g.name for g in hidden.graph}
        assert all(g.tier <= 2 for g in hidden.graph)


# -- one org ---------------------------------------------------------------------------------------------


def test_an_org_page_is_its_timeline_people_introductions_documents_and_status_lines(lb: Logbook) -> None:
    tidevann = orgs.find(lb, "tidevann")
    page = orgs.page(lb, tidevann.id, today=TODAY)
    assert [(i.day, i.kind) for i in page.timeline][:3] == [
        ("2026-10-01", "mail"),
        ("2026-09-20", "event"),
        ("2026-09-15", "event"),
    ]
    assert page.timeline[1].what == "github nordmann-tidevann/tide-clock: Merged pull request #12"
    assert page.timeline[1].via == "repo" and page.timeline[0].via == "domain"
    assert {i.kind for i in page.timeline} == {"mail", "event", "browse"}
    assert [p.name for p in page.people] == ["Liv Berg", "Per Hansen", "Ola Nordmann"]
    [intro] = page.introductions
    assert (intro.by, intro.introduced, intro.day) == ("Per Hansen", ["Liv Berg"], "2026-05-04")
    assert [(d.kind, d.name) for d in page.documents if d.kind == "repo"] == [
        ("repo", "git.example.org/nordmann-tidevann/tide-clock")
    ]
    assert [(s.status, s.reason, s.standing, s.current, s.tier) for s in page.history] == [
        ("hold", "first cheque", True, False, 3),
        ("add", "follow-on with Per", True, True, 3),
    ], "the add supersedes the hold: both stand, one is in force"
    assert page.status is not None and page.status.status == "add" and page.tier == 3


def test_a_retracted_status_is_said_so_and_the_one_before_stands(lb: Logbook) -> None:
    tidevann = orgs.find(lb, TIDEVANN)
    [add] = [line for line in lb.lines() if line["kind"] == "status" and line["payload"]["status"] == "add"]
    lb.retract(int(add["seq"]), "the follow-on fell through")
    page = orgs.page(lb, tidevann.id, today=TODAY)
    assert [(s.status, s.standing, s.current) for s in page.history] == [
        ("hold", True, True),
        ("add", False, False),
    ]
    assert page.status is not None and page.status.status == "hold"


def test_money_only_with_money_and_only_through_a_gate_that_holds_tier_three(lb: Logbook) -> None:
    havbris = orgs.find(lb, HAVBRIS)
    shown = orgs.page(lb, havbris.id, money=True, today=TODAY)
    assert shown.money == {"2023": {"NOK": {"in": 5000.0, "out": -120000.0, "net": -115000.0}}}
    wires = [i for i in shown.timeline if i.kind == "transaction"]
    assert wires[0].what == "NORDMANN HAVBRIS AS +5,000.00 NOK" and {i.tier for i in wires} == {3}
    assert {i.via for i in wires} == {"merchant"}, "the merchant ref the owner accepted"
    for hidden in (
        orgs.page(lb, havbris.id, today=TODAY),
        orgs.page(lb, havbris.id, tiers=(1, 2), money=True, today=TODAY),
    ):
        assert hidden.money is None and all(i.kind != "transaction" for i in hidden.timeline)
    rows = {r.org.label: r for r in orgs.shelf(lb, money=True, year="2023", today=TODAY).rows}
    assert rows[HAVBRIS].money == {"NOK": {"in": 5000.0, "out": -120000.0, "net": -115000.0}}
    assert rows[VERFT].money == {}, "a merchant seen once is no ref of Verft's: its wire is no touch"
    assert all(r.money is None for r in orgs.shelf(lb, tiers=(1, 2), money=True, today=TODAY).rows)


def test_through_a_gate_without_tier_three_no_status_no_reason_and_the_status_lines_counted(
    lb: Logbook,
) -> None:
    s = orgs.shelf(lb, tiers=(1, 2), today=TODAY)
    assert [name for name, _ in s.grouped()] == ["no status"]
    assert all(r.status is None and not r.stale for r in s.rows)
    assert s.withheld == 5 and s.tier == 2
    text = json.dumps(s.to_json())
    for word in (PASSED_REASON, VERFT_REASON, "first cheque", '"status": "hold"', '"status": "passed"'):
        assert word not in text, word
    assert [line for line in orgs.shelf_rows(s)][1] == "  5 status lines not shown: an org's status is tier 3"
    verft = orgs.find(lb, VERFT, tiers=(1, 2))
    page = orgs.page(lb, verft.id, tiers=(1, 2), today=TODAY)
    assert page.status is None and page.history == [] and page.hidden and page.tier == 2
    assert "withheld" not in page.to_json(), "a page says no status here, never how many: that would tell"
    assert VERFT_REASON not in json.dumps(page.to_json())


# -- the commands ----------------------------------------------------------------------------------------


def test_show_orgs_prints_the_headings_the_passed_reason_and_the_people_across_orgs(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _err = _run(capsys, "show", "orgs")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("orgs · 4 · ") and lines[0].endswith(" · tier 3 · money not shown")
    assert lines[1] == "holding"
    assert lines[2].startswith(f"  {VERFT}     hold since 2026-04-02 (owner) · last touch 2026-10-09 group")
    assert "stale: nothing since 2023-07-01" in lines[4] and "last touch 2023-07-01 the ledger" in lines[4]
    kiosk = (
        f"  {KIOSK}         passed since 2026-06-14 (owner) · last touch 2026-04-20 mail from Kari Nordmann"
        ' "Follow-up" · 2 people (Kari Nordmann, Per Hansen) · 2 documents'
    )
    assert lines[5:7] == ["passed", kiosk]
    assert lines[7] == f"                        reason: {PASSED_REASON}"
    assert lines[8:] == [
        "people with more than one org",
        f"  Per Hansen: {KIOSK}, {TIDEVANN}, {VERFT}",
        f"  Liv Berg: {TIDEVANN}, {VERFT}",
        f"  Ola Nordmann: {TIDEVANN}, {VERFT}",
    ]
    assert "NOK" not in out
    code, out, _err = _run(capsys, "show", "orgs", "--json", "--money", "--year", "2023")
    data = json.loads(out)
    assert [o["name"] for o in data["orgs"]] == [VERFT, TIDEVANN, KIOSK, HAVBRIS]
    assert data["money"] is True and data["year"] == "2023"
    assert data["orgs"][3]["money"] == {"NOK": {"in": 5000.0, "out": -120000.0, "net": -115000.0}}
    code, _out, err = _run(capsys, "show", "orgs", "verft")
    assert code == 2 and "one org is `show org NAME`" in err
    code, _out, err = _run(capsys, "show", "orgs", "--money", "--year", "last")
    assert code == 2 and "not a year" in err


def test_show_org_is_one_org_s_page_and_money_only_with_money(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _err = _run(capsys, "show", "org", "verft")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == f"{VERFT} ({VERFT_DOMAIN}, nordmann verft) · org · tier 3"
    assert lines[1] == f"  hold since 2026-04-02 (owner): {VERFT_REASON}"
    code, out, _err = _run(capsys, "show", "org", "havbris")
    assert "NOK" not in out and "transaction" not in out
    code, out, _err = _run(capsys, "show", "org", "havbris.example.org", "--money")
    assert "  2023 NOK in 5,000.00, out -120,000.00, net -115,000.00" in out
    assert "  2023-06-12  transaction NORDMANN HAVBRIS AS -100,000.00 NOK" in out
    code, out, _err = _run(capsys, "show", "org", "Nordmann Tidevann", "--json")
    assert json.loads(out)["org"]["label"] == TIDEVANN and json.loads(out)["money"] is None
    code, _out, err = _run(capsys, "show", "org", "nordmann")
    assert code == 2 and "names 3 orgs" in err
    code, _out, err = _run(capsys, "show", "org")
    assert code == 2 and "say which org" in err


def test_nothing_is_written_by_reading(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    orgs.shelf(lb)  # the observed table, if anything, is built once by the first reader; the record never
    head, before = lb.meta["head"], _files(lb.root)
    orgs.shelf(lb, money=True)
    orgs.page(lb, orgs.find(lb, VERFT).id, money=True)
    _run(capsys, "show", "orgs", "--money")
    _run(capsys, "show", "org", "verft", "--json")
    assert Logbook(lb.root).meta["head"] == head
    after = _files(lb.root)
    assert {k: v for k, v in after.items() if not k.startswith("index")} == {
        k: v for k, v in before.items() if not k.startswith("index")
    }


def test_a_status_written_through_main_s_writer_is_on_the_shelf_at_once(lb: Logbook) -> None:
    entity_status.write(lb, "org", KIOSK, "hold", "came back to it", at=TODAY, today=TODAY)
    row = next(r for r in orgs.shelf(lb, today=TODAY).rows if r.org.label == KIOSK)
    assert row.heading == "holding" and row.status is not None and row.status.reason == "came back to it"
    assert orgs.shelf(lb, today=TODAY).passed == [], "the anti-portfolio is the current status's"


# -- what the independent review found ---------------------------------------------------------------------


def test_the_stale_flag_the_last_touch_and_the_order_never_move_with_money(lb: Logbook) -> None:
    """A ledger line is a touch through the org's merchant ref (RFC 0037 §1) whenever the reader reads
    tier 3; `--money` only decides whether its figures and its rows are shown."""
    lb.append_many([wire("2026-10-01T10:00:00Z", "NORDMANN HAVBRIS AS", -1000, "wire-havbris-late")])
    plain, money = orgs.shelf(lb, today=TODAY), orgs.shelf(lb, money=True, today=TODAY)
    for a, b in zip(plain.rows, money.rows, strict=True):
        assert (a.org.id, a.stale, a.stale_since, a.last and a.last.day) == (
            b.org.id,
            b.stale,
            b.stale_since,
            b.last and b.last.day,
        )
    havbris = next(r for r in plain.rows if r.org.label == HAVBRIS)
    assert havbris.last is not None and havbris.last.day == "2026-10-01" and not havbris.stale
    assert havbris.last_text == "the ledger" and havbris.money is None
    text = "\n".join(orgs.shelf_rows(plain))
    assert "1,000" not in text and "NORDMANN HAVBRIS AS" not in text, "no merchant, no figure without money"
    page = orgs.page(lb, havbris.org.id, today=TODAY)
    assert all(i.kind != "transaction" for i in page.timeline) and not page.stale


def test_an_org_whose_naming_line_is_retracted_stays_by_its_status_lines(lb: Logbook) -> None:
    """RFC 0037 §3.4 rule 3: retracting the minting line leaves the org's status lines standing, and
    the reader shows them under the id with the label the status line carries."""
    kiosk = orgs.find(lb, KIOSK)
    [named] = [line for line in lb.lines() if line["kind"] == "entity" and line["payload"]["label"] == KIOSK]
    lb.retract(int(named["seq"]), "named in error")
    s = orgs.shelf(lb, today=TODAY)
    [passed] = s.passed
    assert (passed.org.id, passed.org.label, passed.org.refs) == (kiosk.id, KIOSK, [])
    assert passed.status is not None and passed.status.reason == PASSED_REASON
    assert passed.last is None, "its domain is bound by no standing line: nothing touches it"
    assert orgs.find(lb, "fjordkiosk").id == kiosk.id
    assert orgs.page(lb, kiosk.id, today=TODAY).status is not None
    assert KIOSK not in {o.label for o in orgs.named(lb, (1, 2)).values()}, "its status lines are tier 3"


def test_two_orgs_of_one_label_are_told_apart_on_the_shelf(lb: Logbook) -> None:
    from logbook.contrib import entity_review

    report = entity_review.read(lb, "org")
    [robaat] = [p for p in report.proposals if p.observed.key == ("domain", "robaat.example.org")]
    entity_review.accept(lb, report, [(robaat, VERFT)])
    rows = [line for line in orgs.shelf_rows(orgs.shelf(lb, today=TODAY)) if line.startswith(f"  {VERFT}")]
    assert len(rows) == 2
    assert any(f"{VERFT} (domain:{VERFT_DOMAIN})" in row for row in rows)
    assert any(f"{VERFT} (domain:robaat.example.org)" in row for row in rows)
