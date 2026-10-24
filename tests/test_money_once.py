"""A payment with its receipt is counted once. The money bridge (`review receipts`, RFC 0043 §12) writes
a receipt's own `transaction/v1` line until a payment source delivers the payment; when the card's line
arrives, the two are one payment: the card's line is the payment, counted once in every total that sums
the ledger — the Day's spend (`day`), `money_in`, `rollup ledger`, `rollup money`, the trip's spend and
an org's money — and the receipt's line is its evidence, never a second payment. Through a gate without
tier 3 none of it shows: no amount, no merchant, no receipt.

Synthetic: the Oslo persona's Zürich trip (Ines Nordmann does not exist), a dinner at an invented
restaurant at example.org, the card in CHF; the orgs of the Manifest for an org's money."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from orgs_record import HAVBRIS, HAVBRIS_MERCHANT, TODAY, settled_record
from persona import persona_record, utc

from logbook import cli
from logbook.contrib import receipts, serve, trip_page
from logbook.core import day as day_reader
from logbook.core import ledger, money, reading
from logbook.core.store import Logbook

DAY = "2026-06-16"  # the Tuesday in Zürich: dinner with Ola
WEEK = "2026-W25"
OWNER = "ines@example.org"
SENDER = {"email": "receipts@zunfthaus.example.org", "name": "Zunfthaus Beispiel"}
DINNER_BODY = """Receipt

2 x Menu of the day      CHF 80.00
Wine                     CHF 6.00
Total paid               CHF 86.00

Zunfthaus Beispiel, an invented restaurant"""
CARD_MERCHANT = "ZUNFTHAUS BEISPIEL ZUERICH"


def card(at: str, amount: float, merchant: str, n: int) -> dict[str, Any]:
    """A card payment as Google Wallet's Takeout writes it (`takeout/pay.py`): tier 3."""
    return {
        "at": at, "source": "google-takeout", "kind": "transaction", "tier": 3,
        "payload": {"schema": "transaction/v1", "raw_id": f"pay:{n}", "amount": amount, "currency": "CHF",
                    "merchant": merchant, "provider": "google-pay", "status": "posted"},
    }  # fmt: skip


def receipt_mail(at: str) -> dict[str, Any]:
    return {
        "at": at, "source": "mail", "kind": "mail", "tier": 2,
        "payload": {"schema": "mail/v1", "raw_id": f"mail:{at}", "message_id": f"{at}@zunfthaus.example.org",
                    "thread": f"{at}@zunfthaus.example.org", "from": SENDER,
                    "to": [{"email": OWNER, "name": "Ines Nordmann"}], "subject": "Your receipt",
                    "body": DINNER_BODY, "direction": "received", "size": 900},
    }  # fmt: skip


def _accept_the_receipt(lb: Logbook) -> dict[str, Any]:
    """The owner confirms the mailed receipt in review before the card's line has arrived."""
    report = receipts.read(lb, since="2026-06-01", today=date(2026, 6, 21))
    (proposal,) = [p for p in report.proposals if p.domain == "zunfthaus.example.org"]
    assert (proposal.amount, proposal.currency) == (-86.0, "CHF")
    (written,) = receipts.accept(lb, report, [proposal])
    assert written.line is not None
    return dict(written.line)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The persona's fortnight; on the Tuesday in Zürich a tram ticket by card, then dinner, whose
    receipt comes by mail and is accepted as a payment; the card's own line for the dinner arrives
    after (the source wins)."""
    found = persona_record(tmp_path, monkeypatch)
    found.set_owner_emails([OWNER])
    found.append_many(
        [
            card(utc(DAY, "08:10"), -4.40, "ZVV Tram", 1),
            receipt_mail(utc(DAY, "21:40")),
        ]
    )
    _accept_the_receipt(found)
    found.append_many([card(utc(DAY, "21:38"), -86.0, CARD_MERCHANT, 2)])
    return found


def _ids(lb: Logbook) -> dict[str, str]:
    lines = list(Logbook(lb.root).lines())
    return {
        "receipt": next(
            str(x["id"]) for x in lines if x["kind"] == "transaction" and x["source"] == "receipts"
        ),
        "dinner": next(
            str(x["id"])
            for x in lines
            if x["kind"] == "transaction" and x["payload"]["merchant"] == CARD_MERCHANT
        ),
        "tram": next(
            str(x["id"])
            for x in lines
            if x["kind"] == "transaction" and x["payload"]["merchant"] == "ZVV Tram"
        ),
        "mail": next(str(x["id"]) for x in lines if x["kind"] == "mail" and x["payload"]["from"] == SENDER),
    }


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> Any:
    return json.loads(_run(capsys, *args, "--json"))


SPENT = {"CHF": {"spent": -90.4, "received": 0.0, "net": -90.4}}


def test_the_day_counts_the_dinner_once_and_shows_its_receipt_as_its_evidence(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = _ids(lb)
    spend = _json(capsys, "day", DAY)["spend"]
    assert spend["count"] == 2 and spend["totals"] == SPENT
    assert spend["merchants"] == ["ZVV Tram", CARD_MERCHANT], "the receipt's merchant is no second payment"
    assert spend["lines"] == [ids["tram"], ids["dinner"]]
    assert spend["receipts"] == [{"line": ids["receipt"], "mail": ids["mail"], "of": ids["dinner"]}]
    (row,) = [r for r in _run(capsys, "day", DAY).splitlines() if r.lstrip().startswith("spend")]
    assert "CHF -90.40" in row and "2 transactions" in row and "1 with its receipt" in row, row


def test_a_day_without_a_receipt_keeps_the_spend_it_had(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only a day a receipt stands behind says so: the Day's object is otherwise unchanged."""
    lb.append_many([card(utc("2026-06-17", "12:00"), -12.0, "Kiosk Beispiel", 3)])
    spend = _json(capsys, "day", "2026-06-17")["spend"]
    assert set(spend) == {"count", "deleted", "totals", "merchants", "lines"}


def test_money_in_counts_the_dinner_once_on_the_day_and_in_the_week(lb: Logbook) -> None:
    ids = _ids(lb)
    for start, end in ((DAY, DAY), ("2026-06-15", "2026-06-21")):
        found = money.money_in(lb, start, end)
        assert found.totals == SPENT, (start, end)
        assert [p.line for p in found.payments] == [ids["tram"], ids["dinner"]]
        assert {p.line: p.receipt for p in found.payments} == {
            ids["tram"]: None,
            ids["dinner"]: ids["receipt"],
        }
        assert found.to_json()["payments"][1]["receipt"] == ids["receipt"]


def test_the_ledger_and_rollup_money_count_it_once(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    ids = _ids(lb)
    book = _json(capsys, "rollup", "ledger", "--month", "2026-06")
    assert book["count"] == 2 and book["totals"] == SPENT
    (day,) = [d for d in book["days"] if d["day"] == DAY]
    assert day["totals"] == SPENT
    assert [(t["lines"], t["receipt"]) for t in day["transactions"]] == [
        ([ids["tram"]], None),
        ([ids["dinner"]], ids["receipt"]),
    ]
    text = _run(capsys, "rollup", "ledger", "--month", "2026-06")
    assert sum(1 for row in text.splitlines() if "-86.00" in row) == 1, text
    (year,) = _json(capsys, "rollup", "money")["years"]
    assert year["count"] == 2 and year["totals"] == SPENT
    assert ids["receipt"] not in year["lines"]


def test_the_trip_s_spend_counts_it_once(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    ids = _ids(lb)
    spend = _json(capsys, "show", "trip", DAY)["spend"]
    assert spend["by_currency"] == [{"currency": "CHF", "amount": -90.4, "count": 2}]
    assert [(t["line"], t.get("receipt")) for t in spend["transactions"]] == [
        (ids["tram"], None),
        (ids["dinner"], ids["receipt"]),
    ]


def test_the_card_posted_two_days_later_is_still_the_same_payment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A card often posts a day or two after the meal: the receipt's line on the Tuesday and the
    card's on the Thursday are one payment, counted on the card's day, in a day's window and a week's."""
    lb = persona_record(tmp_path, monkeypatch)
    lb.set_owner_emails([OWNER])
    lb.append_many([receipt_mail(utc(DAY, "21:40"))])
    _accept_the_receipt(lb)
    lb.append_many([card(utc("2026-06-18", "06:00"), -86.0, CARD_MERCHANT, 2)])
    lines = list(Logbook(lb.root).lines())
    receipt = next(str(x["id"]) for x in lines if x["source"] == "receipts" and x["kind"] == "transaction")
    dinner = next(
        str(x["id"]) for x in lines if x["source"] == "google-takeout" and x["kind"] == "transaction"
    )
    assert _json(capsys, "day", DAY)["spend"] is None, "the Tuesday holds the receipt, not the payment"
    thursday = _json(capsys, "day", "2026-06-18")["spend"]
    assert thursday["totals"] == {"CHF": {"spent": -86.0, "received": 0.0, "net": -86.0}}
    assert thursday["receipts"] == [{"line": receipt, "mail": thursday["receipts"][0]["mail"], "of": dinner}]
    days = [money.money_in(lb, d, d).totals for d in ("2026-06-15", DAY, "2026-06-17", "2026-06-18")]
    assert [t.get("CHF", {}).get("net") for t in days] == [None, None, None, -86.0]
    assert money.money_in(lb, "2026-06-15", "2026-06-21").totals["CHF"]["net"] == -86.0
    (year,) = _json(capsys, "rollup", "money")["years"]
    assert year["count"] == 1 and year["totals"]["CHF"]["net"] == -86.0


def test_two_receipts_and_one_card_line_are_two_payments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One card line is the evidence of one receipt: two dinners of the same price at the same place,
    the card's second line not yet delivered, are two payments, one of them by its receipt alone."""
    lb = persona_record(tmp_path, monkeypatch)
    lb.set_owner_emails([OWNER])
    lb.append_many([receipt_mail(utc("2026-06-15", "21:40")), receipt_mail(utc(DAY, "21:40"))])
    report = receipts.read(lb, since="2026-06-01", today=date(2026, 6, 21))
    receipts.accept(lb, report, report.proposals)
    lb.append_many([card(utc(DAY, "21:38"), -86.0, CARD_MERCHANT, 2)])
    totals = money.money_in(lb, "2026-06-15", "2026-06-21").totals
    assert totals == {"CHF": {"spent": -172.0, "received": 0.0, "net": -172.0}}
    assert _json(capsys, "rollup", "money")["years"][0]["count"] == 2
    covered = _json(capsys, "review", "receipts", "--since", "2026-06-01")["covered"]
    assert len(covered) == 1, "the queue names one receipt to take back, not both"


def test_a_tier_1_or_2_page_shows_no_amount_no_merchant_and_no_receipt(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    for tiers in ((1,), (1, 2)):
        data = day_reader.read(lb, DAY, tiers=tiers)
        assert data["spend"] is None, tiers
        shown = "\n".join(day_reader.rows(data))
        assert "spend" not in shown and not re.search(r"86[.,]00|90[.,]40|ZUNFTHAUS|ZVV", shown), tiers
        assert money.money_in(lb, DAY, DAY, tiers=tiers).payments == []
        with lb.index():
            rd = reading.read(lb, "2026-06-15", "2026-06-21", tiers=tiers)
        assert ledger.ledger(rd).entries == []
        trip = trip_page.read(lb, DAY, tiers=tiers)
        assert trip["spend"] is None, tiers
        assert receipts.read(lb, since="2026-06-01", tiers=tiers).withheld


def test_the_week_page_the_week_draft_and_the_digest_sum_no_money(lb: Logbook) -> None:
    """They show no money at all, so nothing there can count a payment twice."""
    site = serve.Site(lb)
    page = site.respond(f"/week/{WEEK}", "").body.decode("utf-8")
    assert not re.search(r"CHF|86[.,]00|90[.,]40|-86|ZUNFTHAUS", page)
    from logbook.contrib import digest

    found = json.dumps(digest.read(lb, DAY))
    assert not re.search(r"CHF|86[.,]00|90[.,]40|ZUNFTHAUS|ZVV", found)


def test_an_org_s_money_counts_a_wire_once_when_its_receipt_is_in_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logbook.contrib import orgs

    lb = settled_record(tmp_path, monkeypatch)
    lb.append(
        at=utc("2023-06-13", "09:30"),
        source=receipts.SOURCE,
        kind="transaction",
        tier=3,
        payload={
            "schema": "transaction/v1", "raw_id": "mail-havbris-2", "amount": -20000, "currency": "NOK",
            "merchant": HAVBRIS_MERCHANT, "provider": receipts.PROVIDER, "extra": {"from": "mail-havbris-2"},
        },
    )  # fmt: skip
    havbris = orgs.find(lb, HAVBRIS)
    shown = orgs.page(lb, havbris.id, money=True, today=TODAY)
    assert shown.money == {"2023": {"NOK": {"in": 5000.0, "out": -120000.0, "net": -115000.0}}}
    (row,) = [
        r
        for r in orgs.shelf_of(lb, orgs.read(lb, orgs.gate(None, True), TODAY), year="2023").rows
        if r.org.id == havbris.id
    ]
    assert row.money == {"NOK": {"in": 5000.0, "out": -120000.0, "net": -115000.0}}


def _receipt_line(
    lb: Logbook, at: str, amount: float, merchant: str, mail: str, currency: str = "CHF"
) -> str:
    """A receipt's line as `review receipts --accept` writes it (`receipts.accept`)."""
    line = lb.append(
        at=at,
        source=receipts.SOURCE,
        kind="transaction",
        tier=3,
        payload={
            "schema": "transaction/v1", "raw_id": mail, "amount": amount, "currency": currency,
            "merchant": merchant, "provider": receipts.PROVIDER, "extra": {"from": mail},
        },
    )  # fmt: skip
    return str(line["id"])


def test_the_pairs_are_the_same_whichever_window_reads_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receipt on the 8th, the card's line on the 10th, another receipt of the same price on the 12th:
    the first is the card's evidence and the second a payment of its own, read day by day or by the
    fortnight; the days add up to the fortnight."""
    lb = persona_record(tmp_path, monkeypatch)
    _receipt_line(lb, utc("2026-06-08", "12:00"), -86.0, "Zunfthaus Beispiel", "mail-1")
    lb.append_many([card(utc("2026-06-10", "06:00"), -86.0, CARD_MERCHANT, 2)])
    second = _receipt_line(lb, utc("2026-06-12", "12:00"), -86.0, "Zunfthaus Beispiel", "mail-2")
    days = [f"2026-06-{d:02d}" for d in range(8, 22)]
    nets = [money.money_in(lb, d, d).totals.get("CHF", {}).get("net", 0.0) for d in days]
    assert nets[0] == 0.0 and nets[2] == -86.0 and nets[4] == -86.0
    assert sum(nets) == money.money_in(lb, days[0], days[-1]).totals["CHF"]["net"] == -172.0
    (alone,) = money.money_in(lb, "2026-06-12", "2026-06-12").payments
    assert alone.line == second and alone.receipt is None


def test_of_two_receipts_the_card_line_holds_the_nearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    early = _receipt_line(lb, utc("2026-06-15", "20:00"), -86.0, "Zunfthaus Beispiel", "mail-1")
    late = _receipt_line(lb, utc("2026-06-16", "21:40"), -86.0, "Zunfthaus Beispiel", "mail-2")
    lb.append_many([card(utc("2026-06-16", "21:38"), -86.0, CARD_MERCHANT, 2)])
    (paid,) = [p for p in money.money_in(lb, "2026-06-16", "2026-06-16").payments]
    assert paid.receipt == late
    assert [p.line for p in money.money_in(lb, "2026-06-15", "2026-06-15").payments] == [early]


def test_a_receipt_through_a_gate_without_tier_3_is_never_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tier-2 transaction line (a hand-added one; RFC 0021 lines are tier 3) and a receipt's tier-3
    line: a reader of tiers 1 and 2 counts the one it reads and names no receipt, neither its line nor
    its mail."""
    lb = persona_record(tmp_path, monkeypatch)
    receipt = _receipt_line(lb, utc(DAY, "21:40"), -86.0, "Zunfthaus Beispiel", "mail-1")
    lb.append_many([{**card(utc(DAY, "21:38"), -86.0, CARD_MERCHANT, 2), "tier": 2}])
    for tiers in ((1, 2), (2,)):
        data = day_reader.read(lb, DAY, tiers=tiers)
        assert data["spend"] is not None and "receipts" not in data["spend"], tiers
        shown = "\n".join(day_reader.rows(data))
        assert "receipt" not in shown and receipt not in json.dumps(data) and "mail-1" not in json.dumps(data)
    assert day_reader.read(lb, DAY)["spend"]["receipts"][0]["line"] == receipt


def test_a_line_without_a_currency_holds_no_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    no_currency = card(utc(DAY, "21:38"), -86.0, CARD_MERCHANT, 2)
    del no_currency["payload"]["currency"]
    lb.append_many([no_currency])
    _receipt_line(lb, utc(DAY, "21:40"), -86.0, "Zunfthaus Beispiel", "mail-1", currency="")
    assert _spend_count(lb) == 2


def _spend_count(lb: Logbook) -> int:
    spend = day_reader.read(lb, DAY)["spend"]
    assert spend is not None
    return int(spend["count"])


def test_two_unnamed_senders_of_one_price_on_one_day_are_two_payments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither sender gives a name or a registered domain, so both are `a sender`: still two senders."""
    lb = persona_record(tmp_path, monkeypatch)
    lb.set_owner_emails([OWNER])
    for n, email in enumerate(("orders@localhost", "receipts@intranet")):
        mail = receipt_mail(utc(DAY, f"1{n}:00"))
        mail["payload"]["from"] = {"email": email}
        lb.append_many([mail])
    report = receipts.read(lb, since="2026-06-01", today=date(2026, 6, 21))
    assert [p.merchant for p in report.proposals] == ["a sender", "a sender"]
    written = receipts.accept(lb, report, report.proposals)
    assert [w.verdict for w in written] == ["accepted", "accepted"]
    assert _spend_count(lb) == 2
