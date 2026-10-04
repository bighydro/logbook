"""Google Takeout Google Pay/ → transaction/v1 (RFC 0021) for the transactions CSV, event/v1 (RFC 0009)
for the passes that are tickets. Every amount, card and pass here is synthetic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters.takeout import pay

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Google Pay"
CSV = FIX / "Google transactions" / "transactions_123456789012.csv"
PASSES = FIX / "Passes"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _lines(path=FIX, **kw):
    return list(pay.run(path, timezone=TZ, **kw))


def test_registry_has_pay_as_a_file_adapter_under_both_names():
    assert adapters.named("google-takeout-pay") is pay and adapters.named("takeout-pay") is pay
    assert isinstance(pay, adapters.Adapter)
    for path in (FIX, CSV, CSV.parent, PASSES, PASSES / "3388000000000000000.pass-ev-0001.json"):
        assert adapters.find(path) is pay, path


def test_sniff_recognises_the_csv_the_passes_and_their_folders_only(tmp_path):
    assert not pay.sniff(ROOT / "tests" / "fixtures" / "pocket" / "part_000000.csv")
    assert not pay.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep" / "Boat list.json")
    assert not pay.sniff(tmp_path) and not pay.sniff(tmp_path / "x.csv")
    (tmp_path / "x.json").write_text('{"id": "1", "state": "ACTIVE"}', encoding="utf-8")
    assert not pay.sniff(tmp_path / "x.json")


def test_every_transaction_and_ticket_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(pay.run(FIX, timezone=TZ, counts=counts))
    transactions = [line for line in lines if line["kind"] == "transaction"]
    events = [line for line in lines if line["kind"] == "event"]
    assert len(transactions) == 5 and len(events) == 3
    for line in lines:
        assert set(line) == ENVELOPE and line["source"] == "google-takeout" and line["tz"] == TZ
    for line in transactions:
        assert line["tier"] == 3 and line["payload"]["schema"] == "transaction/v1"
        assert line["payload"]["provider"] == "google-pay" and line["end"] is None
    for line in events:
        assert line["tier"] == 1 and line["payload"]["schema"] == "event/v1"
    assert counts == {
        "skipped_no_amount": 1,
        "skipped_no_currency": 1,
        "skipped_no_timestamp": 1,
        "skipped_store_cards": 1,
        "skipped_coupons": 1,
        "skipped_no_date": 1,
    }
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_amounts_are_signed_from_the_owners_side_and_currencies_read_from_the_text():
    by = {line["payload"]["raw_id"]: line for line in _lines(CSV)}
    coffee = by["pay:TXN-0000000001"]
    assert coffee["at"] == "2026-06-10T10:35:12Z"
    assert coffee["payload"] == {
        "schema": "transaction/v1",
        "raw_id": "pay:TXN-0000000001",
        "amount": -129.0,
        "currency": "NOK",
        "merchant": "Kaffebrenneriet Oslo",
        "account": "Visa •••• 1234",
        "provider": "google-pay",
        "status": "posted",
        "extra": {"product": "Google Pay", "amount_text": "-129.00 NOK", "net_amount": "-129.00 NOK"},
    }
    marina = by["pay:TXN-0000000002"]["payload"]
    assert marina["amount"] == -2450.0 and marina["currency"] == "NOK"  # unsigned: money left
    refund = by["pay:TXN-0000000003"]["payload"]
    assert refund["amount"] == 129.0 and refund["status"] == "refunded"
    app = by["pay:TXN-0000000004"]["payload"]
    assert app["amount"] == -4.99 and app["currency"] == "EUR"  # the symbol and the comma
    assert app["extra"]["fee"] == "€0,00"
    ferry = by["pay:TXN-0000000005"]
    assert ferry["payload"]["amount"] == -45.0 and ferry["payload"]["status"] == "pending"
    assert ferry["payload"]["date"] == "2026-06-18"  # 23:00 UTC is the next day in Oslo


def test_tickets_become_events_and_names_on_the_pass_never_do():
    by = {line["payload"]["raw_id"]: line for line in _lines(PASSES)}
    concert = by["pay-pass:3388000000000000000.pass-ev-0001"]
    assert concert["at"] == "2026-06-20T17:00:00Z" and concert["end"] == "2026-06-20T19:30:00Z"
    assert concert["payload"] == {
        "schema": "event/v1",
        "raw_id": "pay-pass:3388000000000000000.pass-ev-0001",
        "title": "Fjordsang: summer concert",
        "calendar": {"id": "google-pay:event_ticket", "name": "Oslo Konserthus"},
        "all_day": False,
        "location": "Oslo Konserthus, Munkedamsveien 14, 0250 Oslo",
        "extra": {"pass_type": "EVENT_TICKET", "state": "ACTIVE", "seat": {"row": "7", "seat": "12"}},
    }
    ferry = by["pay-pass:3388000000000000000.pass-tr-0002"]["payload"]
    assert ferry["title"] == "Aker brygge → Nesoddtangen" and ferry["extra"]["transit_type"] == "FERRY"
    flight = by["pay-pass:3388000000000000000.pass-fl-0003"]
    assert flight["payload"]["title"] == "XY 561 OSL → ZRH"
    assert flight["at"] == "2026-06-15T07:05:00Z" and flight["end"] == "2026-06-15T09:15:00Z"  # local, Oslo
    assert flight["payload"]["extra"]["local_times"] is True
    assert flight["payload"]["extra"]["seat"] == "14A" and flight["payload"]["extra"]["gate"] == "E14"
    for line in by.values():
        text = repr(line)
        assert "Per Persona" not in text and "PERSONA" not in text and "accountId" not in text


def test_since_cuts_on_at():
    assert [line["payload"]["raw_id"] for line in _lines(since="2026-06-20T00:00:00Z")] == [
        "pay-pass:3388000000000000000.pass-ev-0001"
    ]


def test_tier_cannot_be_lowered_by_the_import_option(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "takeout-pay", str(CSV), "--tier", "1"])
    assert e.value.code == 2 and "--tier is not an option" in capsys.readouterr().err


def test_cli_add_sniffs_the_folder_and_dry_run_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", "takeout-pay", str(FIX), "--dry-run"])
    out = capsys.readouterr().out
    assert "google-takeout-pay: 8 lines would be added, 0 already in the record (dry run" in out
    assert "1 without an amount" in out and "1 without a currency" in out
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 8 lines from google-takeout-pay" in out
    assert "1 store and loyalty cards" in out and "1 coupons" in out and "1 without a date" in out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-pay" in capsys.readouterr().out
    cli.main(["show", "2026-06-10"])
    assert "Kaffebrenneriet" in capsys.readouterr().out


FIX_2026 = ROOT / "tests" / "fixtures" / "takeout-2026-10" / "Google Pay"


def test_the_2026_clock_reads_every_transaction():
    counts: dict[str, int] = {}
    lines = list(pay.run(FIX_2026, timezone=TZ, counts=counts))
    assert [line["at"] for line in lines] == [
        "2026-10-01T10:35:12Z",
        "2026-10-02T18:02:00Z",
        "2026-10-02T23:30:00Z",
    ]
    assert counts == {"skipped_no_timestamp": 1}
    coffee = lines[0]["payload"]
    assert (
        coffee["raw_id"] == "pay:TXN-0000000101"
        and coffee["amount"] == -129.0
        and coffee["currency"] == "NOK"
    )
    assert lines[2]["payload"]["date"] == "2026-10-03"  # 23:30 UTC is the next day in Oslo


def test_a_date_column_a_currency_column_and_a_row_without_an_id_still_read(tmp_path):
    import hashlib

    csv = tmp_path / "transactions_1.csv"
    csv.write_text(
        "Date,Transaction ID,Description,Product,Payment method,Status,Amount,Currency,Fee,Net amount\n"
        "2026-10-01 10:35:12 UTC,TXN-1,Kaffebrenneriet Oslo,Google Pay,Visa •••• 1234,Completed,"
        "-129.00,NOK,,-129.00\n"
        "2026-10-02 18:02:00 UTC,,Oslo Marina AS,Google Pay,Visa •••• 1234,Completed,2450.00,NOK,,2450.00\n",
        encoding="utf-8",
    )
    assert pay.sniff(csv) and adapters.find(csv) is pay
    counts: dict[str, int] = {}
    lines = list(pay.run(csv, timezone=TZ, counts=counts))
    assert len(lines) == 2 and counts == {"no_transaction_id": 1}
    coffee = lines[0]["payload"]
    assert coffee["raw_id"] == "pay:TXN-1" and coffee["amount"] == -129.0 and coffee["currency"] == "NOK"
    assert coffee["extra"]["amount_text"] == "-129.00"
    marina = lines[1]["payload"]
    digest = hashlib.sha256(b"Oslo Marina AS|2450.00|NOK").hexdigest()[:16]
    assert marina["raw_id"] == f"pay:2026-10-02T18:02:00Z:{digest}"
    assert marina["amount"] == -2450.0 and marina["currency"] == "NOK"
