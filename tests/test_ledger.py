"""`logbook ledger [--month YYYY-MM | --trip ID] [--json]` and `logbook rollup money`: the
transaction/v1 lines (tier 3) placed in context — each at the stay the owner was in, in its trip,
per day; the year by month, by country, by category; a shared expense's shares per person. Amounts
in the line's currency, never converted. Synthetic Oslo persona, fictional merchants; nothing is
written."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import CAFE, KARI, OLA, OLA_ID, PLACES, persona_record, utc

from logbook import cli, ledger
from logbook.store import Logbook

OWNER_ID = "019cadd3-6bc0-7dcd-9133-00000000000a"
OWNER_EMAIL = "owner@example.org"
EN_DASH = "\u2013"
CAFE_PLACE = {"Cafe": {"lat": CAFE[0], "lon": CAFE[1], "radius_m": 120, "kind": "other"}}


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["ledger", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def card(
    at: str,
    amount: float,
    currency: str,
    merchant: str,
    category: str | None = None,
    date: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A Copilot-style card transaction, the owner's side signed (RFC 0021 rule 2)."""
    payload: dict[str, Any] = {
        "schema": "transaction/v1",
        "raw_id": f"tx-{at}-{merchant}",
        "amount": amount,
        "currency": currency,
        "merchant": merchant,
        "account": "acct_0000000000000001",
        "provider": "copilot",
        "status": "posted",
    }
    if category:
        payload["category"] = category
    if date:
        payload["date"] = date
    if extra:
        payload["extra"] = extra
    return {"at": at, "end": None, "source": "copilot", "kind": "transaction", "tier": 3, "payload": payload}


def shared(
    at: str,
    description: str,
    cost: float,
    members: list[tuple[dict[str, str], str | None, float, float]],
    category: str | None = "Dining out",
    deleted: bool = False,
) -> dict[str, Any]:
    """A Splitwise-style expense in NOK: `members` are (ref, name, paid, owed); the owner's own
    member is the one whose ref is `OWNER_EMAIL`."""
    shares = []
    owed = paid = 0.0
    for ref, name, paid_share, owed_share in members:
        entry: dict[str, Any] = {"ref": ref, "paid": paid_share, "owed": owed_share}
        if name:
            entry["name"] = name
        shares.append(entry)
        if ref == {"kind": "email", "value": OWNER_EMAIL}:
            owed, paid = owed_share, paid_share
    extra: dict[str, Any] = {
        "cost": cost,
        "paid_share": paid,
        "owed_share": owed,
        "payment": False,
        "members": shares,
    }
    if deleted:
        extra["deleted"] = True
    payload: dict[str, Any] = {
        "schema": "transaction/v1",
        "raw_id": f"sw-{at}",
        "amount": -owed,
        "currency": "NOK",
        "merchant": description,
        "account": "Sailing",
        "provider": "splitwise",
        "extra": extra,
    }
    if category:
        payload["category"] = category
    return {
        "at": at,
        "end": None,
        "source": "splitwise",
        "kind": "transaction",
        "tier": 3,
        "payload": payload,
    }


ME = {"kind": "email", "value": OWNER_EMAIL}
KARI_REF = {"kind": "email", "value": KARI["email"]}
OLA_REF = {"kind": "email", "value": OLA["email"]}
PER_REF = {"kind": "provider_id", "value": "3"}  # a member the record has no resolution for


def transactions() -> list[dict[str, Any]]:
    """The fortnight's money: a coffee at the cafe, dinner aboard split three ways, a deleted
    ice cream, a hotel in Zürich filed by the day only, a dinner there, and a salary at the office.
    Every merchant is invented."""
    return [
        card(utc("2026-06-10", "12:40"), -185.0, "NOK", "Fjordkaffe", "restaurants"),
        shared(
            utc("2026-06-13", "18:30"),
            "Dinner at anchor",
            90.0,
            [(ME, "Me", 90.0, 30.0), (OLA_REF, "Ola", 0.0, 30.0), (PER_REF, "Per", 0.0, 30.0)],
        ),
        shared(utc("2026-06-14", "13:00"), "Ice cream", 40.0, [(ME, "Me", 40.0, 40.0)], deleted=True),
        # Copilot keeps the day only: `at` is that day's local midnight (RFC 0021 rule 5)
        card(utc("2026-06-16", "00:00"), -210.0, "EUR", "Hotel Musterhof", "travel", date="2026-06-16"),
        card(utc("2026-06-16", "19:30"), -97.5, "EUR", "Zunfthaus Beispiel", "restaurants"),
        card(utc("2026-06-19", "09:00"), 45000.0, "NOK", "Eksempel AS", "income"),
    ]


def ledger_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = persona_record(tmp_path, monkeypatch, places={**PLACES, **CAFE_PLACE})
    meta = lb.meta
    meta["owner_id"] = OWNER_ID
    meta["owner_emails"] = [OWNER_EMAIL]
    lb._save_meta(meta)
    lb.append_many(transactions())
    return lb


# -- the ledger ---------------------------------------------------------------------------------------------


def test_the_month_places_each_transaction_at_the_stay_and_in_its_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = ledger_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "--month", "2026-06")
    assert data["window"]["since"] == "2026-06-10" and data["window"]["until"] == "2026-06-19"
    assert data["count"] == 5 and data["deleted"] == 1
    assert data["totals"] == {
        "NOK": {"spent": -215.0, "received": 45000.0, "net": 44785.0},
        "EUR": {"spent": -307.5, "received": 0.0, "net": -307.5},
    }, "the deleted ice cream is listed, never summed; nothing is converted"
    days = {d["day"]: d for d in data["days"]}
    assert list(days) == ["2026-06-10", "2026-06-13", "2026-06-14", "2026-06-16", "2026-06-19"]
    [coffee] = days["2026-06-10"]["transactions"]
    assert (coffee["merchant"], coffee["amount"], coffee["currency"]) == ("Fjordkaffe", -185.0, "NOK")
    assert coffee["where"]["place"] == "Cafe" and coffee["where"]["label"] == "Cafe"
    assert coffee["where"]["country"] == "NO" and coffee["where"]["by"] == "instant"
    assert coffee["where"]["stay"].startswith("stay:owner:20260610T1000Z")
    assert coffee["trip"] is None and coffee["category"] == "restaurants"
    assert len(coffee["lines"]) == 1 and len(coffee["lines"][0]) == 36
    [dinner] = days["2026-06-13"]["transactions"]
    assert dinner["where"]["label"] == "aboard Solvind" and dinner["where"]["aboard"] == "solvind"
    assert dinner["trip"] == "trip:2026-06-13:2026-06-13"
    assert dinner["amount"] == -30.0 and dinner["account"] == "Sailing"
    assert [(s["name"], s["person"], s["owner"], s["paid"], s["owed"]) for s in dinner["shares"]] == [
        ("you", OWNER_ID, True, 90.0, 30.0),
        ("Ola Nordmann", OLA_ID, False, 0.0, 30.0),
        ("Per", None, False, 0.0, 30.0),
    ], "a member resolves through the record's resolution lines; one it does not know keeps the app's name"
    assert dinner["cost"] == 90.0
    [ice_cream] = days["2026-06-14"]["transactions"]
    assert ice_cream["deleted"] is True and days["2026-06-14"]["totals"] == {}
    hotel, zunfthaus = days["2026-06-16"]["transactions"]
    assert hotel["where"]["by"] == "day", (
        "a transaction filed by the day only is placed by the day's longest stay"
    )
    assert hotel["where"]["place"] is None and hotel["where"]["label"].startswith("47.37")
    assert hotel["where"]["country"] == "CH" and zunfthaus["where"]["country"] == "CH"
    assert hotel["trip"] == zunfthaus["trip"] == "trip:2026-06-15:2026-06-17"
    assert days["2026-06-16"]["totals"] == {"EUR": {"spent": -307.5, "received": 0.0, "net": -307.5}}
    [salary] = days["2026-06-19"]["transactions"]
    assert salary["where"]["place"] == "Office" and salary["amount"] == 45000.0
    trips = {t["id"]: t for t in data["trips"]}
    assert trips["trip:2026-06-15:2026-06-17"]["totals"] == {
        "EUR": {"spent": -307.5, "received": 0.0, "net": -307.5}
    }
    assert trips["trip:2026-06-15:2026-06-17"]["count"] == 2
    assert trips["trip:2026-06-13:2026-06-13"]["count"] == 1
    assert set(trips["trip:2026-06-13:2026-06-13"]["lines"]) == set(dinner["lines"] + ice_cream["lines"]), (
        "the return day is the trip's; a deleted line is listed under it, never counted"
    )
    assert lb.meta["head"] == head, "the ledger is read, never written"
    text = _run(capsys, "--month", "2026-06")
    assert text.splitlines()[0].startswith(f"ledger 2026-06-10 {EN_DASH} 2026-06-19")
    assert "5 transactions" in text and "1 deleted" in text
    assert "NOK 44,785.00" in text and "EUR -307.50" in text
    assert "12:40  NOK -185.00  Fjordkaffe · at Cafe · restaurants · copilot" in text
    assert (
        "aboard Solvind" in text
        and "split 3 ways: you 30.00 (paid 90.00), Ola Nordmann 30.00, Per 30.00" in text
    )
    assert "Ice cream" in text and "deleted" in text
    assert "Hotel Musterhof" in text and "(by day)" in text
    assert f"trip 2026-06-15 {EN_DASH} 2026-06-17" in text


def test_a_trip_is_its_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger_record(tmp_path, monkeypatch)
    data = _json(capsys, "--trip", "trip:2026-06-15:2026-06-17")
    assert data["window"] == {
        "since": "2026-06-15",
        "until": "2026-06-18",
        "days": ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"],
    }
    assert data["count"] == 2 and [d["day"] for d in data["days"]] == ["2026-06-16"]
    [trip] = data["trips"]
    assert trip["id"] == "trip:2026-06-15:2026-06-17" and trip["route"][0].startswith("47.37")
    text = _run(capsys, "--trip", "trip:2026-06-15:2026-06-17")
    assert "2 transactions" in text and "EUR -307.50" in text
    with pytest.raises(SystemExit):
        _run(capsys, "--trip", "trip:2026-06-08:2026-06-09")
    assert "no trip trip:2026-06-08:2026-06-09" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _run(capsys, "--trip", "weekend")
    assert "not a trip id" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _run(capsys, "--month", "2026-06", "--trip", "trip:2026-06-15:2026-06-17")
    assert "not both" in capsys.readouterr().err


def test_a_retracted_or_corrected_transaction_is_out_and_an_empty_month_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = ledger_record(tmp_path, monkeypatch)
    with lb.index() as idx:
        [coffee] = [
            line for line in idx.by_kind("transaction") if line["payload"]["merchant"] == "Fjordkaffe"
        ]
        [salary] = [
            line for line in idx.by_kind("transaction") if line["payload"]["merchant"] == "Eksempel AS"
        ]
    lb.retract(int(coffee["seq"]), "a test")
    corrected = card(utc("2026-06-19", "09:00"), 45500.0, "NOK", "Eksempel AS", "income")
    corrected["payload"]["raw_id"] = "tx-corrected"
    corrected["payload"]["supersedes"] = str(salary["id"])
    lb.append_many([corrected])
    data = _json(capsys, "--month", "2026-06")
    merchants = [t["merchant"] for d in data["days"] for t in d["transactions"]]
    assert "Fjordkaffe" not in merchants and merchants.count("Eksempel AS") == 1
    assert data["totals"]["NOK"]["received"] == 45500.0, (
        "the correction stands in the superseded line's place"
    )
    data = _json(capsys, "--month", "2026-05")
    assert data["window"] is None and data["count"] == 0 and data["days"] == []
    assert "no transactions" in _run(capsys, "--month", "2026-05")
    with pytest.raises(SystemExit):
        _run(capsys, "--month", "June")
    assert "not a month" in capsys.readouterr().err


def test_an_empty_record_has_no_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert "no transactions" in _run(capsys)
    data = _json(capsys)
    assert data == {
        "window": None,
        "tz": None,
        "count": 0,
        "deleted": 0,
        "totals": {},
        "days": [],
        "trips": [],
    }


# -- the shares ---------------------------------------------------------------------------------------------


def test_shares_resolve_through_resolutions_never_through_faces() -> None:
    from logbook.present import Owner
    from logbook.resolve import Identity

    identities = {
        ("email", OLA["email"]): Identity(OLA_ID, "person", "Ola Nordmann"),
        ("provider_id", "immich:p_17"): Identity("face-person", "person", "Kari Nordmann"),
    }
    owner = Owner(frozenset({OWNER_ID}), frozenset({("email", OWNER_EMAIL)}), frozenset({"me"}))
    members = [
        {"ref": ME, "name": "Me", "paid": 90, "owed": 30},
        {"ref": OLA_REF, "name": "Ola", "paid": 0, "owed": 30},
        {"ref": {"kind": "provider_id", "value": "p_17"}, "name": "Kari", "paid": 0, "owed": 30},
        {"ref": "not a ref", "paid": 0, "owed": 0},
        "not a member",
    ]
    found = ledger.shares({"members": members}, identities, owner)
    assert [(s.name, s.person, s.owner) for s in found] == [
        ("you", OWNER_ID, True),
        ("Ola Nordmann", OLA_ID, False),
        ("Kari", None, False),
    ], "a Splitwise provider id is not a photo library's face id; a member with no ref and no name is skipped"
    assert ledger.shares({}, identities, owner) == []
    assert ledger.shares({"members": "none"}, identities, owner) == []


# -- rollup money --------------------------------------------------------------------------------------------


def test_rollup_money_by_month_country_and_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = ledger_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    cli.main(["rollup", "money", "--year", "2026", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["kind"] == "money" and data["window"]["since"] == "2026-06-10"
    [year] = data["years"]
    assert year["year"] == "2026" and year["count"] == 5 and year["deleted"] == 1
    assert year["totals"] == {
        "NOK": {"spent": -215.0, "received": 45000.0, "net": 44785.0},
        "EUR": {"spent": -307.5, "received": 0.0, "net": -307.5},
    }
    [june] = year["by_month"]
    assert june["month"] == "2026-06" and june["count"] == 5 and june["totals"] == year["totals"]
    assert [(c["country"], c["count"]) for c in year["by_country"]] == [("NO", 3), ("CH", 2)]
    assert year["by_country"][1]["totals"] == {"EUR": {"spent": -307.5, "received": 0.0, "net": -307.5}}
    assert [(c["category"], c["count"]) for c in year["by_category"]] == [
        ("restaurants", 2),
        ("Dining out", 1),
        ("income", 1),
        ("travel", 1),
    ]
    assert year["by_category"][0]["totals"]["NOK"]["spent"] == -185.0
    assert year["by_category"][0]["totals"]["EUR"]["spent"] == -97.5
    assert len(year["lines"]) == 6 and all(len(id_) == 36 for id_ in year["lines"])
    assert lb.meta["head"] == head
    cli.main(["rollup", "money", "--year", "2026"])
    text = capsys.readouterr().out
    assert text.startswith(f"money 2026-06-10 {EN_DASH} 2026-06-19")
    assert (
        "2026  5 transactions · 1 deleted · EUR -307.50 · NOK 44,785.00 (in 45,000.00, out -215.00)" in text
    )
    assert "2026-06        5 transactions · 1 deleted" in text
    assert "NO             3 transactions" in text and "CH             2 transactions" in text
    assert "restaurants" in text and "Dining out" in text


def test_rollup_money_without_categories_and_with_an_unplaced_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many([card(utc("2026-03-02", "10:00"), -42.5, "NOK", "Brødbua")])
    cli.main(["rollup", "money", "--json"])
    data = json.loads(capsys.readouterr().out)
    [year] = data["years"]
    assert year["by_category"] == [] and year["by_country"] == [
        {
            "country": None,
            "count": 1,
            "deleted": 0,
            "totals": {"NOK": {"spent": -42.5, "received": 0.0, "net": -42.5}},
            "lines": year["lines"],
        }
    ], "no track that day: the transaction is nowhere, and says so"
    cli.main(["rollup", "money"])
    text = capsys.readouterr().out
    assert "unplaced       1 transaction · NOK -42.50" in text and "by category" not in text
    cli.main(["ledger", "--json"])
    data = json.loads(capsys.readouterr().out)
    [bread] = data["days"][0]["transactions"]
    assert bread["where"] is None and bread["trip"] is None
    cli.main(["ledger"])
    assert "Brødbua · nowhere · copilot" in capsys.readouterr().out


def test_rollup_money_of_an_empty_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    cli.main(["rollup", "money", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["years"] == [] and data["window"]["since"] is None
    cli.main(["rollup", "money"])
    assert "nothing in the window" in capsys.readouterr().out


# -- the day ------------------------------------------------------------------------------------------------


def test_the_day_gains_a_spend_line_when_transactions_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger_record(tmp_path, monkeypatch)
    cli.main(["day", "2026-06-16", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["spend"]["count"] == 2
    assert data["spend"]["totals"] == {"EUR": {"spent": -307.5, "received": 0.0, "net": -307.5}}
    assert data["spend"]["merchants"] == ["Hotel Musterhof", "Zunfthaus Beispiel"]
    assert len(data["spend"]["lines"]) == 2
    cli.main(["day", "2026-06-16"])
    text = capsys.readouterr().out
    assert "  spend         EUR -307.50 · 2 transactions · Hotel Musterhof, Zunfthaus Beispiel" in text
    cli.main(["day", "2026-06-14", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["spend"]["count"] == 0 and data["spend"]["deleted"] == 1 and data["spend"]["totals"] == {}
    cli.main(["day", "2026-06-14"])
    assert "  spend         1 deleted" in capsys.readouterr().out
    cli.main(["day", "2026-06-11", "--json"])
    assert json.loads(capsys.readouterr().out)["spend"] is None
    cli.main(["day", "2026-06-11"])
    assert "spend" not in capsys.readouterr().out
