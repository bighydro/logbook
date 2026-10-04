"""Apple Wallet passes → flight/v1 for air boarding passes (RFC 0013, evidence `declared`), event/v1
for tickets and for train and boat passes (RFC 0009); cards and coupons skipped unless dated.
Every pass here is synthetic: carriers XY, YZ and ZX, Ines Nordmann of Oslo, a PNR that must never
reach a line. `pass.json` is the one file read; the barcode, the images and the back are never."""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.contrib import adapters
from logbook.contrib.adapters import apple_wallet
from logbook.core import flights
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
FIXTURE = ROOT / "tests" / "fixtures" / "apple-wallet"
CARDS = FIXTURE / "cards"
UPDATED = FIXTURE / "updated"
PASSES = 12  # pass.json files under cards/; `_passes` adds one that will not parse
FLIGHT_LINES = 3  # XY, YZ, ZX
EVENT_LINES = 5  # train, boat, concert, festival, the dated coupon
LINES = FLIGHT_LINES + EVENT_LINES
PNR = "QX7PLM"
NEVER = (  # what the fixtures carry and no line may: the owner, the booking, the barcode, the credentials
    PNR,
    "Nordmann",
    "NORDMANN",
    "Ines",
    "example.org",
    "TKT-SECRET",
    "ORD-",
    "never-read",
    "C-000001",
    "000777",
    "YZ 0000",
    "0042",
    "M-000777",
)


def _passes(folder: Path) -> Path:
    """The fixture's cards copied under `folder`, as the phone keeps them (one unpacked `.pkpass`
    folder per pass), plus one whose pass.json will not parse (never a fixture: the repository's
    JSON check would refuse it); for `test_import_backup`."""
    shutil.copytree(CARDS, folder, dirs_exist_ok=True)
    (folder / "broken.pkpass").mkdir()
    (folder / "broken.pkpass" / "pass.json").write_text("{ not a pass at all\n", encoding="utf-8")
    return folder


def _drafts(path: Path = CARDS, **options) -> tuple[list[dict], dict[str, int]]:
    counts: dict[str, int] = {}
    drafts = list(apple_wallet.run(path, counts=counts, timezone="Europe/Oslo", **options))
    return drafts, counts


def _flight(drafts: list[dict], carrier: str) -> dict:
    return next(d for d in drafts if d["kind"] == "flight" and d["payload"]["carrier"] == carrier)


def _event(drafts: list[dict], title: str) -> dict:
    return next(d for d in drafts if d["kind"] == "event" and d["payload"].get("title") == title)


def _card(folder: Path, name: str, data: dict) -> Path:
    card = folder / f"{name}.pkpass"
    card.mkdir(parents=True, exist_ok=True)
    (card / "pass.json").write_text(json.dumps(data), encoding="utf-8")
    return card


def _pass(style: str, body: dict, serial: str = "S-1", **more) -> dict:
    return {
        "formatVersion": 1,
        "passTypeIdentifier": "pass.org.example.inline",
        "serialNumber": serial,
        "organizationName": "Example Org",
        "description": "inline",
        style: body,
        **more,
    }


# -- registry and sniff -----------------------------------------------------------------------------------


def test_registry_has_the_wallet_adapter_by_name_and_aliases_and_its_evidence_is_declared():
    assert adapters.named("apple-wallet") is apple_wallet
    assert adapters.named("wallet") is apple_wallet
    assert adapters.named("ios-wallet") is apple_wallet  # the name 0.5.0 gave the adapter
    assert flights.EVIDENCE_OF["apple-wallet"] == "declared"


def test_sniff_recognises_a_folder_of_passes_a_pkpass_folder_a_pkpass_zip_and_nothing_else(tmp_path):
    assert apple_wallet.sniff(CARDS)
    assert apple_wallet.sniff(CARDS / "xy-nordic.pkpass")
    assert apple_wallet.sniff(CARDS / "xy-nordic.pkpass" / "pass.json")
    zipped = tmp_path / "one.pkpass"
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("pass.json", (CARDS / "xy-nordic.pkpass" / "pass.json").read_bytes())
        z.writestr("manifest.json", "{}")
    assert apple_wallet.sniff(zipped)
    zips = tmp_path / "zips"
    zips.mkdir()
    (zips / "a.pkpass").write_bytes(zipped.read_bytes())
    assert apple_wallet.sniff(zips)
    assert not apple_wallet.sniff(tmp_path / "missing")
    assert not apple_wallet.sniff(ROOT / "tests" / "fixtures" / "flighty" / "export.csv")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not apple_wallet.sniff(empty)
    assert adapters.find(CARDS) is apple_wallet


# -- air boarding passes → flight/v1, one style per fictional airline ---------------------------------


def test_the_nordic_style_names_the_route_in_its_keys_and_the_date_in_relevant_date():
    drafts, _ = _drafts()
    assert len([d for d in drafts if d["kind"] == "flight"]) == FLIGHT_LINES
    d = _flight(drafts, "XY")
    p = d["payload"]
    assert d["source"] == "apple-wallet" and d["tier"] == 1 and d["tz"] == "Europe/Oslo"
    assert p["schema"] == "flight/v1" and flights.key(p) == ("2026-03-14", "XY", "561")
    assert p["from"] == {"iata": "OSL", "icao": "ENGM"} and p["to"] == {"iata": "ZRH", "icao": "LSZH"}
    assert p["role"] == "passenger" and p["evidence"] == "declared"
    assert p["observations"] == [{"evidence": "declared", "source": "apple-wallet"}]
    assert p["extra"] == {
        "organization": "Nordic Example Air",
        "seat": "12A",
        "class": "Economy",
        "relevant_date": "2026-03-14T07:05:00+01:00",
    }
    # relevantDate is when Wallet shows the pass (boarding or departure, the airline decides): it is
    # the line's `at` when the pass names no schedule, but never a scheduled time
    assert d["at"] == "2026-03-14T06:05:00Z" and d["end"] is None
    assert "scheduled_departure" not in p and "scheduled_arrival" not in p
    assert p["raw_id"].startswith(apple_wallet.raw_prefix("pass.org.example.xy.boarding", "XY-2026-000561"))


def test_the_continental_style_has_from_to_keys_a_dotted_date_field_and_timed_fields():
    drafts, _ = _drafts()
    d = _flight(drafts, "YZ")
    p = d["payload"]
    assert flights.key(p) == ("2026-03-14", "YZ", "562")  # the leading zero of YZ0562 dropped
    assert p["from"]["iata"] == "OSL" and p["to"]["iata"] == "ZRH"  # from `Oslo (OSL)`, `Zürich (ZRH)`
    assert p["scheduled_departure"] == "2026-03-14T08:40:00Z"
    assert p["scheduled_arrival"] == "2026-03-14T10:55:00Z"
    assert d["at"] == "2026-03-14T08:40:00Z" and d["end"] == "2026-03-14T10:55:00Z"
    assert p["extra"] == {"organization": "Continental Example Airways", "seat": "4C", "class": "Business"}


def test_the_low_cost_style_is_read_by_its_labels_and_its_semantic_tags():
    drafts, _ = _drafts()
    d = _flight(drafts, "ZX")
    p = d["payload"]
    assert flights.key(p) == (
        "2026-03-20",
        "ZX",
        "1234",
    )  # the number from `Flight`, the carrier from `Airline`
    assert p["from"]["iata"] == "OSL" and p["to"]["iata"] == "BGO"  # the fields' labels say DEP and ARR
    assert p["scheduled_departure"] == "2026-03-20T14:30:00Z"  # semantics.originalDepartureDate
    assert p["scheduled_arrival"] == "2026-03-20T15:25:00Z"
    assert d["at"] == "2026-03-20T14:30:00Z" and d["tz"] == "Europe/Oslo"
    assert p["extra"]["seat"] == "21F" and p["extra"]["class"] == "Basic"
    assert p["extra"]["relevant_date"] == "2026-03-20T15:10:00+01:00"


def test_the_booking_reference_the_passenger_the_barcode_and_the_credentials_never_reach_a_line():
    drafts, _ = _drafts()
    text = json.dumps(drafts, ensure_ascii=False)
    for secret in NEVER:
        assert secret not in text, secret
    assert "barcode" not in text and "backFields" not in text and "fields" not in text


def test_a_pass_with_no_readable_flight_or_no_date_or_no_json_is_skipped_and_counted(tmp_path):
    drafts, counts = _drafts(_passes(tmp_path / "wallet"))
    assert len(drafts) == LINES
    assert counts["skipped_no_flight"] == 1  # a route nothing on the pass names
    assert counts["skipped_no_date"] == 1  # `14MAR`: a day with no year, and no relevantDate
    assert counts["skipped_unreadable"] == 1


def test_a_code_may_sit_in_the_label_and_a_bare_number_takes_the_carrier_from_the_semantic_tags(tmp_path):
    card = _card(
        tmp_path,
        "labelled",
        _pass(
            "boardingPass",
            {
                "transitType": "PKTransitTypeAir",
                "primaryFields": [
                    {"key": "p1", "label": "OSL", "value": "Oslo"},
                    {"key": "p2", "label": "CPH", "value": "Copenhagen"},
                ],
                "auxiliaryFields": [{"key": "a1", "label": "Flight", "value": "77"}],
            },
            relevantDate="2026-07-01T10:00:00+02:00",
            semantics={"airlineCode": "XY"},
        ),
    )
    (card / "icon.png").write_bytes(b"not an image at all")  # never opened
    drafts, counts = _drafts(card)
    assert counts == {}
    p = drafts[0]["payload"]
    assert flights.key(p) == ("2026-07-01", "XY", "77")
    assert p["from"]["iata"] == "OSL" and p["to"]["iata"] == "CPH"


def test_a_city_in_capitals_is_not_a_code_and_an_airline_name_does_not_hide_the_semantic_code(tmp_path):
    _card(
        tmp_path,
        "caps",
        _pass(
            "boardingPass",
            {
                "transitType": "PKTransitTypeAir",
                "primaryFields": [
                    {"key": "from", "label": "From", "value": "NEW YORK JFK"},
                    {"key": "to", "label": "To", "value": "OSLO GARDERMOEN OSL"},
                ],
                "secondaryFields": [
                    {"key": "flight", "label": "Flight", "value": "561"},
                    {"key": "airline", "label": "Airline", "value": "Nordic Example Air"},
                ],
            },
            relevantDate="2093-01-01T00:00:00Z",  # a placeholder year the issuer wrote: not an instant
            relevantDates=[{"startDate": "2026-07-02T10:00:00-04:00"}],
            semantics={"airlineCode": "XY"},
        ),
    )
    drafts, counts = _drafts(tmp_path)
    assert counts == {}
    p = drafts[0]["payload"]
    assert flights.key(p) == ("2026-07-02", "XY", "561")
    assert p["from"]["iata"] == "JFK" and p["to"]["iata"] == "OSL"
    assert p["extra"]["relevant_date"] == "2026-07-02T10:00:00-04:00"


# -- tickets, trains, boats, and dated coupons → event/v1 ----------------------------------------------


def test_a_train_pass_is_an_event_from_origin_to_destination_with_its_transit_type():
    drafts, _ = _drafts()
    assert len([d for d in drafts if d["kind"] == "event"]) == EVENT_LINES
    d = _event(drafts, "Oslo S → Bergen")
    p = d["payload"]
    assert d["source"] == "apple-wallet" and d["tier"] == 1 and d["tz"] == "Europe/Oslo"
    assert p["schema"] == "event/v1" and p["all_day"] is False
    assert d["at"] == "2026-04-03T06:25:00Z" and d["end"] == "2026-04-03T13:05:00Z"
    assert p["calendar"] == {"id": "pass.org.example.rail.ticket", "name": "Example Rail"}
    assert p["extra"] == {
        "pass_style": "boardingPass",
        "transit_type": "train",
        "organization": "Example Rail",
        "seat": "Coach 3, seat 41",
        "relevant_date": "2026-04-03T08:25:00+02:00",
    }
    assert "location" not in p


def test_a_boat_pass_is_an_event_with_no_end():
    drafts, _ = _drafts()
    d = _event(drafts, "Oslo → Kiel")
    assert d["at"] == "2026-05-09T12:00:00Z" and d["end"] is None
    assert d["payload"]["extra"]["transit_type"] == "boat"
    assert d["payload"]["extra"]["class"] == "Outside, 2 berths"


def test_an_event_ticket_is_one_event_with_its_name_venue_and_start():
    drafts, _ = _drafts()
    d = _event(drafts, "Spring Concert")
    p = d["payload"]
    assert d["at"] == "2026-05-02T17:00:00Z" and d["end"] is None
    assert p["location"] == "Oslo Konserthus"
    assert p["calendar"] == {"id": "pass.org.example.tickets", "name": "Example Tickets"}
    assert p["extra"] == {
        "pass_style": "eventTicket",
        "organization": "Example Tickets",
        "relevant_date": "2026-05-02T19:00:00+02:00",
    }
    assert p["raw_id"].startswith(apple_wallet.raw_prefix("pass.org.example.tickets", "T-2026-11204"))


def test_semantic_tags_name_the_event_its_span_and_its_venue():
    drafts, _ = _drafts()
    d = _event(drafts, "Fjord Festival")
    assert d["at"] == "2026-06-20T10:00:00Z" and d["end"] == "2026-06-20T21:00:00Z"
    assert d["payload"]["location"] == "Bygdøy"


def test_a_dated_coupon_is_one_event_named_after_the_issuer_and_undated_cards_are_counted(tmp_path):
    drafts, counts = _drafts()
    d = _event(drafts, "Example Coffee")
    assert d["at"] == "2026-02-28T09:00:00Z" and d["payload"]["extra"]["pass_style"] == "coupon"
    assert "skipped_coupons" not in counts
    assert counts["skipped_store_cards"] == 1 and counts["skipped_generic_passes"] == 1
    _card(tmp_path, "c", _pass("coupon", {"primaryFields": [{"key": "offer", "value": "10% off"}]}))
    _card(tmp_path, "g", _pass("generic", {}, serial="S-2", relevantDate="2026-01-05T09:00:00Z"))
    drafts, counts = _drafts(tmp_path)
    assert counts == {"skipped_coupons": 1}
    assert [d["payload"]["title"] for d in drafts] == ["Example Org"]
    assert drafts[0]["payload"]["extra"]["pass_style"] == "generic"


def test_a_ticket_with_only_a_day_is_an_all_day_event_and_one_with_no_date_is_counted(tmp_path):
    _card(
        tmp_path,
        "day",
        _pass(
            "eventTicket",
            {
                "primaryFields": [{"key": "event", "value": "Open Day"}],
                "auxiliaryFields": [{"key": "date", "label": "Date", "value": "7 Nov 2026"}],
            },
        ),
    )
    _card(tmp_path, "none", _pass("eventTicket", {"primaryFields": [{"key": "event", "value": "?"}]}, "S-2"))
    drafts, counts = _drafts(tmp_path)
    assert counts == {"skipped_no_date": 1}
    (d,) = drafts
    assert d["payload"]["all_day"] is True
    assert d["at"] == "2026-11-06T23:00:00Z" and d["end"] == "2026-11-07T23:00:00Z"


def test_since_drops_earlier_lines():
    drafts, _ = _drafts(since="2026-04-01T00:00:00Z")
    assert all(d["at"] >= "2026-04-01T00:00:00Z" for d in drafts)
    assert len(drafts) == 4  # train, boat, concert, festival


# -- a zip, raw ids, the record ------------------------------------------------------------------------


def test_a_pkpass_zip_is_read_like_the_unpacked_folder(tmp_path):
    zipped = tmp_path / "one.pkpass"
    with zipfile.ZipFile(zipped, "w") as z:
        for name in ("pass.json", "manifest.json", "icon.png"):
            z.write(CARDS / "xy-nordic.pkpass" / name, name)
    unpacked, _ = _drafts(CARDS / "xy-nordic.pkpass")
    from_zip, _ = _drafts(zipped)
    assert from_zip == unpacked


def test_the_same_pass_again_is_the_same_raw_id_and_an_updated_pass_is_a_new_observation():
    first, _ = _drafts(CARDS / "xy-nordic.pkpass")
    again, _ = _drafts(CARDS / "xy-nordic.pkpass")
    assert first == again
    (updated,), _ = _drafts(UPDATED)
    assert updated["payload"]["raw_id"] != first[0]["payload"]["raw_id"]
    assert updated["payload"]["raw_id"].split("@")[0] == first[0]["payload"]["raw_id"].split("@")[0]
    assert flights.key(updated["payload"]) == flights.key(first[0]["payload"])
    assert PNR not in apple_wallet.raw_prefix("pass.org.example.xy.boarding", PNR)  # a serial can be one


def test_lines_append_validate_an_updated_pass_supersedes_and_a_tracked_flight_wins(tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    drafts, _ = _drafts()
    assert lb.append_many(flights.reconcile(lb, drafts)) == LINES
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
    assert lb.append_many(flights.reconcile(lb, _drafts()[0])) == 0  # the same Wallet again
    # the airline pushed a delay and a new seat: the same serial, a later relevantDate
    counts: dict[str, int] = {}
    assert lb.append_many(flights.reconcile(lb, _drafts(UPDATED)[0], counts)) == 1
    assert counts["merged"] == 1
    last = [ln for ln in lb.lines() if ln["kind"] == "flight"][-1]
    first = next(ln for ln in lb.lines() if ln["kind"] == "flight" and ln["payload"]["carrier"] == "XY")
    assert last["payload"]["supersedes"] == first["id"]
    assert last["payload"]["extra"]["seat"] == "14C"
    assert last["payload"]["extra"]["relevant_date"] == "2026-03-14T09:50:00+01:00"
    assert last["at"] == "2026-03-13T23:00:00Z"  # rule 3 recomputes `at`: no schedule, so local midnight
    assert last["payload"]["evidence"] == "declared"
    assert [o["source"] for o in last["payload"]["observations"]] == ["apple-wallet", "apple-wallet"]
    # then a tracker's export of the flight: tracked over declared, the seat travels along
    tracked = flights.build(
        source="flighty",
        raw_id="fx-1@abc",
        airports=flights.Airports.load(),
        date="2026-03-14",
        carrier="XY",
        number="561",
        from_={"iata": "OSL"},
        to={"iata": "ZRH"},
        times={"actual_departure": "2026-03-14T08:58:00Z", "actual_arrival": "2026-03-14T11:02:00Z"},
    )
    assert lb.append_many(flights.reconcile(lb, [tracked])) == 1
    last = [ln for ln in lb.lines() if ln["kind"] == "flight"][-1]
    assert last["source"] == "flighty" and last["payload"]["evidence"] == "tracked"
    assert last["payload"]["extra"]["seat"] == "14C"
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES + 2
    # the payloads only: `id`, `hash`, `prev` and `raw_id` are hex, and a digit-only secret such as
    # "0042" turns up inside a hash by chance (one PR run in several did)
    text = "\n".join(json.dumps(ln["payload"], ensure_ascii=False) for ln in lb.lines())
    for secret in NEVER:
        assert secret not in text, secret


def test_the_cli_adds_a_wallet_by_content_and_reports_the_skips(tmp_path, monkeypatch, capsys):
    from logbook import cli

    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    Logbook.init(root, "Europe/Oslo")
    cli.main(["add", str(_passes(tmp_path / "wallet"))])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from apple-wallet" in out
    assert "1 passes that would not parse" in out
    assert "1 boarding passes without a readable flight" in out
    assert "1 store and loyalty cards" in out and "1 generic passes" in out
