"""Apple Wallet passes → flight/v1 for air boarding passes (RFC 0013, evidence `tracked`), event/v1
for event tickets and other boarding passes (RFC 0009); loyalty and the rest skipped and counted.
Every pass here is synthetic: the Oslo persona, carrier XY, a PNR that must never reach a line."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, flights
from logbook.adapters import ios_wallet
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
PNR = "ABC123"
NAME = "NORDMANN/KARI"
FLIGHT_LINES = 9  # the flight lines `_passes` yields (two from the two-leg pass)
EVENT_LINES = 3
LINES = FLIGHT_LINES + EVENT_LINES


def _bcbp(*legs: tuple, name: str = NAME, variable: str = "") -> str:
    """An IATA BCBP message: the mandatory items, `variable` as the first leg's conditional field."""
    out = f"M{len(legs)}{name:<20.20}E"
    for i, (frm, to, carrier, number, julian, compartment, seat) in enumerate(legs):
        extra = variable if i == 0 else ""
        out += (
            f"{PNR:<7}{frm:<3}{to:<3}{carrier:<3}{number:<5}{julian:03d}{compartment}{seat:<4}"
            f"{'0001':<5}1{len(extra):02X}{extra}"
        )
    return out


def _pass(folder: Path, name: str, data: dict, *, encoding: str = "utf-8", text: str | None = None) -> Path:
    card = folder / f"{name}.pkpass"
    card.mkdir(parents=True, exist_ok=True)
    body = text if text is not None else json.dumps(data, ensure_ascii=False, indent=2)
    (card / "pass.json").write_bytes(body.encode(encoding))
    return card


def _boarding(serial: str, barcode: str | None = None, **more) -> dict:
    d = {
        "formatVersion": 1,
        "passTypeIdentifier": "pass.org.example.boarding",
        "serialNumber": serial,
        "teamIdentifier": "EXAMPLE123",
        "organizationName": "Example Air",
        "description": "Boarding pass",
        "boardingPass": {
            "transitType": "PKTransitTypeAir",
            "headerFields": [
                {"key": "seat", "label": "Seat", "value": "12A"},
                {"key": "gate", "label": "Gate", "value": "A12"},
            ],
            "primaryFields": [
                {"key": "depart", "label": "Oslo", "value": "OSL"},
                {"key": "destination", "label": "Zurich", "value": "ZRH"},
            ],
            "secondaryFields": [{"key": "passenger", "label": "Passenger", "value": NAME}],
            "auxiliaryFields": [
                {"key": "flightNumber", "label": "Flight", "value": "XY561"},
                {"key": "date", "label": "Date", "value": "14MAR"},
            ],
            "backFields": [{"key": "eTicket", "label": "Ticket", "value": "2204000000000"}],
        },
    }
    if barcode is not None:
        d["barcodes"] = [
            {"format": "PKBarcodeFormatAztec", "message": barcode, "messageEncoding": "iso-8859-1"}
        ]
    d.update(more)
    return d


LEG = ("OSL", "ZRH", "XY", "0561", 73, "Y", "12A")  # 2026-03-14 is day 73 of 2026


def _passes(folder: Path) -> Path:
    """The synthetic Wallet: ten air boarding passes of every shape, three tickets, three others."""
    _pass(folder, "01-swiss-style", _boarding("SN-1", _bcbp(LEG), relevantDate="2026-03-14T06:40:00+01:00"))
    _pass(
        folder,
        "02-two-legs",
        _boarding(
            "SN-2",
            _bcbp(
                ("OSL", "CPH", "SK", "0460", 73, "C", "2A"),
                ("CPH", "ZRH", "SK", "0617", 73, "C", "3C"),
                variable=">10101A",
            ),
            relevantDate="2026-03-14T05:00:00Z",
        ),
    )
    _pass(folder, "03-no-year", _boarding("SN-3", _bcbp(LEG)))
    _pass(
        folder,
        "04-bad-relevant-date-dated-field",
        _boarding(
            "SN-4",
            _bcbp(LEG),
            relevantDate="2093-02-01T16:00:00-05:00",
            boardingPass={
                **_boarding("x")["boardingPass"],
                "auxiliaryFields": [{"key": "date", "label": "Date", "value": "14MAR26"}],
            },
        ),
    )
    _pass(
        folder,
        "05-year-boundary",
        _boarding(
            "SN-5", _bcbp(("OSL", "ZRH", "XY", "0561", 365, "Y", "1A")), expirationDate="2026-01-03T00:00:00Z"
        ),
    )
    _pass(
        folder,
        "06-semantics",
        _boarding(
            "SN-6",
            _bcbp(LEG),
            relevantDate="2026-03-14T06:40:00+01:00",
            semantics={
                "originalDepartureDate": "2026-03-14T07:05:00+01:00",
                "originalArrivalDate": "2026-03-14T09:20:00+01:00",
            },
        ),
    )
    _pass(
        folder,
        "07-utf16",
        _boarding("SN-7", _bcbp(LEG), relevantDate="2026-03-14T06:40:00+01:00", voided=True),
        encoding="utf-16",
    )
    broken = json.dumps(_boarding("SN-8", _bcbp(LEG), relevantDate="2026-03-14T06:40:00+01:00"), indent=2)
    _pass(
        folder,
        "08-trailing-comma",
        {},
        text=broken.replace('"description": "Boarding pass",', '"description": "Boarding pass",').replace(
            "\n}", ",\n}"
        ),
    )
    _pass(folder, "09-garbage", {}, text="{ not json at all")
    fields_only = _boarding("SN-10", None, relevantDate="2026-03-14T06:40:00+01:00")
    fields_only["boardingPass"]["primaryFields"] = [
        {"key": "from", "label": "From", "value": "OSL"},
        {"key": "to", "label": "To", "value": "Zurich (ZRH)"},
    ]
    fields_only["boardingPass"]["auxiliaryFields"] = [{"key": "flight", "label": "Flight", "value": "XY 561"}]
    _pass(folder, "10-fields-only", fields_only)
    no_flight = _boarding("SN-11", None, relevantDate="2026-03-14T06:40:00+01:00")
    no_flight["boardingPass"]["primaryFields"] = [{"key": "a", "value": "Somewhere"}]
    no_flight["boardingPass"]["auxiliaryFields"] = []
    _pass(folder, "11-no-flight", no_flight)
    _pass(
        folder,
        "12-concert",
        {
            "formatVersion": 1,
            "passTypeIdentifier": "pass.org.example.tickets",
            "serialNumber": "T-1",
            "organizationName": "Example Tickets",
            "description": "Concert ticket",
            "relevantDate": "2026-05-02T19:00:00+02:00",
            "locations": [{"latitude": 59.914, "longitude": 10.734}],
            "barcodes": [{"format": "PKBarcodeFormatQR", "message": "ORDER-1-SECRET"}],
            "eventTicket": {
                "primaryFields": [{"key": "event-name", "label": "Event", "value": "Spring Concert"}],
                "secondaryFields": [{"key": "venue-name", "label": "Where", "value": "Oslo Konserthus"}],
                "auxiliaryFields": [{"key": "ticket-type", "label": "Ticket", "value": "Standing"}],
                "backFields": [
                    {"key": "order-id", "label": "Order", "value": "#1"},
                    {"key": "ticket-buyer-name", "label": "Buyer", "value": "Kari Nordmann"},
                ],
            },
        },
    )
    _pass(
        folder,
        "13-semantic-ticket",
        {
            "formatVersion": 1,
            "passTypeIdentifier": "pass.org.example.fair",
            "serialNumber": "T-2",
            "organizationName": "Example Fair",
            "description": "Fair ticket",
            "semantics": {
                "eventName": "Boat Fair",
                "eventStartDateInfo": {"date": "2026-06-23T09:00:00+02:00", "ignoreTimeComponents": False},
                "eventEndDate": "2026-06-25T17:00:00+02:00",
                "venueName": "Oslo Spektrum",
                "venueLocation": {"latitude": 59.912, "longitude": 10.754},
                "attendeeName": "Kari Nordmann",
            },
            "eventTicket": {
                "headerFields": [{"key": "header-text", "value": "Boat Fair"}],
                "secondaryFields": [
                    {"key": "registered-for", "label": "Registered for", "value": "Kari Nordmann"}
                ],
                "auxiliaryFields": [{"key": "ticket-code", "label": "Ticket", "value": "0103000000000001"}],
            },
        },
    )
    _pass(
        folder,
        "14-undated-ticket",
        {
            "formatVersion": 1,
            "passTypeIdentifier": "pass.org.example.tickets",
            "serialNumber": "T-3",
            "organizationName": "Example Tickets",
            "description": "Ticket",
            "eventTicket": {
                "headerFields": [{"key": "start-time", "label": "7:00pm", "value": "Oct 05"}],
                "primaryFields": [{"key": "event-name", "value": "Some Night"}],
            },
        },
    )
    _pass(
        folder,
        "15-bus",
        {
            "formatVersion": 1,
            "passTypeIdentifier": "pass.org.example.bus",
            "serialNumber": "B-1",
            "organizationName": "Example Bus",
            "description": "Bus ticket",
            "relevantDate": "2026-04-03T13:00:00Z",
            "expirationDate": "2026-04-03T16:50:00Z",
            "boardingPass": {
                "transitType": "PKTransitTypeBus",
                "primaryFields": [
                    {"key": "origin", "label": "From", "value": "Oslo"},
                    {"key": "destination", "label": "To", "value": "Bergen"},
                ],
                "secondaryFields": [
                    {"key": "passenger", "value": "Kari Nordmann"},
                    {"key": "seat", "value": "22D"},
                ],
                "auxiliaryFields": [
                    {
                        "key": "departs",
                        "label": "Departs",
                        "value": "2026-04-03T15:00:00+02:00",
                        "dateStyle": "PKDateStyleShort",
                        "timeStyle": "PKDateStyleShort",
                    },
                    {
                        "key": "arrival",
                        "label": "Arrives",
                        "value": "2026-04-03T18:50:00+02:00",
                        "dateStyle": "PKDateStyleShort",
                        "timeStyle": "PKDateStyleShort",
                    },
                ],
            },
        },
    )
    for style, serial in (("storeCard", "L-1"), ("coupon", "C-1"), ("generic", "G-1")):
        _pass(
            folder,
            f"16-{style}",
            {
                "formatVersion": 1,
                "passTypeIdentifier": f"pass.org.example.{style}",
                "serialNumber": serial,
                "organizationName": "Example Shop",
                "description": style,
                style: {"primaryFields": [{"key": "member", "value": "Kari Nordmann"}]},
            },
        )
    return folder


@pytest.fixture
def wallet(tmp_path: Path) -> Path:
    return _passes(tmp_path / "wallet")


def _drafts(path: Path, **options) -> tuple[list[dict], dict[str, int]]:
    counts: dict[str, int] = {}
    drafts = list(ios_wallet.run(path, counts=counts, timezone="Europe/Oslo", **options))
    return drafts, counts


def _flight(drafts: list[dict], serial_hint: str) -> dict:
    return next(
        d for d in drafts if d["kind"] == "flight" and d["payload"]["extra"].get("serial_hint") == serial_hint
    )


# -- registry and sniff -----------------------------------------------------------------------------------


def test_registry_has_the_wallet_adapter_by_name_and_alias():
    assert adapters.named("ios-wallet") is ios_wallet
    assert adapters.named("wallet") is ios_wallet
    assert flights.EVIDENCE_OF["ios-wallet"] == "tracked"


def test_sniff_recognises_a_folder_of_passes_a_pkpass_folder_a_pkpass_zip_and_nothing_else(wallet, tmp_path):
    assert ios_wallet.sniff(wallet)
    assert ios_wallet.sniff(wallet / "01-swiss-style.pkpass")
    assert ios_wallet.sniff(wallet / "01-swiss-style.pkpass" / "pass.json")
    zipped = tmp_path / "one.pkpass"
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("pass.json", (wallet / "01-swiss-style.pkpass" / "pass.json").read_bytes())
        z.writestr("manifest.json", "{}")
    assert ios_wallet.sniff(zipped)
    zips = tmp_path / "zips"
    zips.mkdir()
    (zips / "a.pkpass").write_bytes(zipped.read_bytes())
    assert ios_wallet.sniff(zips)
    assert not ios_wallet.sniff(tmp_path / "missing")
    assert not ios_wallet.sniff(ROOT / "tests" / "fixtures" / "flighty" / "export.csv")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not ios_wallet.sniff(empty)


# -- air boarding passes → flight/v1 ----------------------------------------------------------------------


def test_a_boarding_pass_is_one_tracked_flight_from_its_barcode(wallet):
    drafts, _counts = _drafts(wallet)
    flights_ = [d for d in drafts if d["kind"] == "flight"]
    assert len(flights_) == FLIGHT_LINES
    d = next(
        d
        for d in flights_
        if d["payload"]["raw_id"].startswith(ios_wallet.raw_prefix("pass.org.example.boarding", "SN-1"))
    )
    p = d["payload"]
    assert d["source"] == "ios-wallet" and d["tier"] == 1 and d["tz"] == "Europe/Oslo"
    assert (p["date"], p["carrier"], p["number"]) == ("2026-03-14", "XY", "561")
    assert p["from"] == {"iata": "OSL", "icao": "ENGM"} and p["to"] == {"iata": "ZRH", "icao": "LSZH"}
    assert p["role"] == "passenger" and p["evidence"] == "tracked"
    assert p["observations"] == [{"evidence": "tracked", "source": "ios-wallet"}]
    assert p["extra"]["seat"] == "12A" and p["extra"]["gate"] == "A12" and p["extra"]["compartment"] == "Y"
    assert p["extra"]["organization"] == "Example Air"
    # the relevant date is Wallet's instant for the pass (boarding or departure, the airline decides):
    # kept as given, and the line's `at`, but never written as a scheduled time
    assert p["extra"]["relevant_date"] == "2026-03-14T06:40:00+01:00"
    assert d["at"] == "2026-03-14T05:40:00Z" and d["end"] is None
    assert "scheduled_departure" not in p
    assert flights.key(p) == ("2026-03-14", "XY", "561")


def test_the_pnr_the_passenger_and_the_barcode_never_reach_a_line(wallet):
    drafts, _ = _drafts(wallet)
    text = json.dumps(drafts)
    assert PNR not in text and "NORDMANN" not in text and "Nordmann" not in text
    assert "ORDER-1-SECRET" not in text and "2204000000000" not in text and "0103000000000001" not in text
    assert "#1" not in text


def test_a_two_leg_barcode_is_two_flights(wallet):
    drafts, _ = _drafts(wallet)
    legs = [
        d
        for d in drafts
        if d["payload"]["raw_id"].startswith(ios_wallet.raw_prefix("pass.org.example.boarding", "SN-2"))
    ]
    assert [
        (
            d["payload"]["carrier"],
            d["payload"]["number"],
            d["payload"]["from"]["iata"],
            d["payload"]["to"]["iata"],
        )
        for d in legs
    ] == [
        ("SK", "460", "OSL", "CPH"),
        ("SK", "617", "CPH", "ZRH"),
    ]
    assert legs[0]["payload"]["extra"]["seat"] == "2A" and legs[1]["payload"]["extra"]["seat"] == "3C"
    assert legs[0]["payload"]["raw_id"] != legs[1]["payload"]["raw_id"]


def test_the_year_comes_from_the_pass_never_from_a_guess(wallet):
    drafts, counts = _drafts(wallet)
    by_serial = {d["payload"]["raw_id"].split("@")[0]: d for d in drafts if d["kind"] == "flight"}
    assert counts["skipped_no_year"] == 1  # SN-3: a day of the year and nothing that says which year
    assert ios_wallet.raw_prefix("pass.org.example.boarding", "SN-3") not in by_serial
    # SN-4: a relevantDate in 2093 is not a year; the dated field is
    four = by_serial[ios_wallet.raw_prefix("pass.org.example.boarding", "SN-4")]
    assert four["payload"]["date"] == "2026-03-14" and "relevant_date" not in four["payload"]["extra"]
    assert four["at"] == "2026-03-13T23:00:00Z"  # local midnight at the origin: no instant is known
    # SN-5: day 365, expiring on 3 January: the flight was on the 31st of the year before
    five = by_serial[ios_wallet.raw_prefix("pass.org.example.boarding", "SN-5")]
    assert five["payload"]["date"] == "2025-12-31"


def test_semantic_tags_give_the_scheduled_times(wallet):
    drafts, _ = _drafts(wallet)
    six = next(
        d
        for d in drafts
        if d["payload"]["raw_id"].startswith(ios_wallet.raw_prefix("pass.org.example.boarding", "SN-6"))
    )
    p = six["payload"]
    assert (
        p["scheduled_departure"] == "2026-03-14T06:05:00Z"
        and p["scheduled_arrival"] == "2026-03-14T08:20:00Z"
    )
    assert six["at"] == "2026-03-14T06:05:00Z" and six["end"] == "2026-03-14T08:20:00Z"


def test_utf16_and_trailing_commas_are_read_and_garbage_is_counted(wallet):
    drafts, counts = _drafts(wallet)
    prefixes = {d["payload"]["raw_id"].split("@")[0] for d in drafts}
    seven = next(
        d
        for d in drafts
        if d["payload"]["raw_id"].startswith(ios_wallet.raw_prefix("pass.org.example.boarding", "SN-7"))
    )
    assert seven["payload"]["extra"]["voided"] is True
    assert ios_wallet.raw_prefix("pass.org.example.boarding", "SN-8") in prefixes
    assert counts["skipped_unreadable"] == 1


def test_a_pass_without_a_barcode_is_read_from_its_fields_or_skipped(wallet):
    drafts, counts = _drafts(wallet)
    ten = next(
        d
        for d in drafts
        if d["payload"]["raw_id"].startswith(ios_wallet.raw_prefix("pass.org.example.boarding", "SN-10"))
    )
    p = ten["payload"]
    assert (p["carrier"], p["number"], p["from"]["iata"], p["to"]["iata"], p["date"]) == (
        "XY",
        "561",
        "OSL",
        "ZRH",
        "2026-03-14",
    )
    assert counts["skipped_no_flight"] == 1


def test_the_same_pass_again_is_the_same_raw_id_and_a_changed_one_is_a_new_observation(wallet, tmp_path):
    first, _ = _drafts(wallet / "01-swiss-style.pkpass")
    again, _ = _drafts(wallet / "01-swiss-style.pkpass")
    assert first[0]["payload"]["raw_id"] == again[0]["payload"]["raw_id"]
    changed = _pass(
        tmp_path / "w2",
        "01",
        _boarding(
            "SN-1",
            _bcbp(("OSL", "ZRH", "XY", "0561", 73, "Y", "14C")),
            relevantDate="2026-03-14T06:40:00+01:00",
        ),
    )
    other, _ = _drafts(changed)
    assert other[0]["payload"]["raw_id"] != first[0]["payload"]["raw_id"]
    assert other[0]["payload"]["raw_id"].split("@")[0] == first[0]["payload"]["raw_id"].split("@")[0]


# -- tickets and other boarding passes → event/v1 ---------------------------------------------------------


def test_an_event_ticket_is_one_event_with_its_title_venue_and_issuer(wallet):
    drafts, _ = _drafts(wallet)
    events = [d for d in drafts if d["kind"] == "event"]
    assert len(events) == EVENT_LINES
    concert = next(d for d in events if d["payload"]["title"] == "Spring Concert")
    p = concert["payload"]
    assert concert["source"] == "ios-wallet" and concert["tier"] == 1 and concert["tz"] == "Europe/Oslo"
    assert concert["at"] == "2026-05-02T17:00:00Z" and concert["end"] is None
    assert p["schema"] == "event/v1" and p["all_day"] is False
    assert p["location"] == "Oslo Konserthus"
    assert p["calendar"] == {"id": "pass.org.example.tickets", "name": "Example Tickets"}
    assert p["extra"]["pass_style"] == "eventTicket" and p["extra"]["description"] == "Concert ticket"
    assert p["extra"]["fields"] == {
        "event-name": "Spring Concert",
        "venue-name": "Oslo Konserthus",
        "ticket-type": "Standing",
    }
    assert p["extra"]["locations"] == [{"latitude": 59.914, "longitude": 10.734}]
    assert p["raw_id"].startswith(ios_wallet.raw_prefix("pass.org.example.tickets", "T-1"))


def test_semantic_tags_name_the_event_its_span_and_its_venue(wallet):
    drafts, _ = _drafts(wallet)
    fair = next(d for d in drafts if d["kind"] == "event" and d["payload"]["title"] == "Boat Fair")
    assert fair["at"] == "2026-06-23T07:00:00Z" and fair["end"] == "2026-06-25T15:00:00Z"
    assert fair["payload"]["location"] == "Oslo Spektrum"
    assert fair["payload"]["extra"]["locations"] == [{"latitude": 59.912, "longitude": 10.754}]
    assert (
        "registered-for" not in fair["payload"]["extra"]["fields"]
        and "ticket-code" not in fair["payload"]["extra"]["fields"]
    )


def test_a_ticket_with_no_date_is_skipped_and_counted(wallet):
    _, counts = _drafts(wallet)
    assert counts["skipped_no_date"] == 1


def test_a_bus_boarding_pass_is_an_event_from_origin_to_destination(wallet):
    drafts, _ = _drafts(wallet)
    bus = next(
        d for d in drafts if d["kind"] == "event" and d["payload"]["extra"].get("transit_type") == "bus"
    )
    assert bus["payload"]["title"] == "Oslo → Bergen"
    assert bus["at"] == "2026-04-03T13:00:00Z" and bus["end"] == "2026-04-03T16:50:00Z"
    assert bus["payload"]["extra"]["pass_style"] == "boardingPass"
    assert (
        bus["payload"]["extra"]["fields"]["seat"] == "22D"
        and "passenger" not in bus["payload"]["extra"]["fields"]
    )


def test_loyalty_cards_coupons_and_generic_passes_are_skipped_and_counted(wallet):
    _, counts = _drafts(wallet)
    assert (
        counts["skipped_store_cards"] == 1
        and counts["skipped_coupons"] == 1
        and counts["skipped_generic_passes"] == 1
    )


def test_since_drops_earlier_lines(wallet):
    drafts, _ = _drafts(wallet, since="2026-04-01T00:00:00Z")
    assert all(d["at"] >= "2026-04-01T00:00:00Z" for d in drafts)
    assert len(drafts) == 3


# -- a zip, the record, the merge with Flighty ---------------------------------------------------------


def test_a_pkpass_zip_is_read_like_the_unpacked_folder(wallet, tmp_path):
    zipped = tmp_path / "one.pkpass"
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("pass.json", (wallet / "01-swiss-style.pkpass" / "pass.json").read_bytes())
    unpacked, _ = _drafts(wallet / "01-swiss-style.pkpass")
    from_zip, _ = _drafts(zipped)
    assert from_zip == unpacked


def test_lines_append_validate_and_a_flighty_export_of_the_same_flight_supersedes_them(
    wallet, tmp_path, monkeypatch
):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    drafts, _ = _drafts(wallet)
    assert lb.append_many(flights.reconcile(lb, drafts)) == LINES
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
    assert lb.append_many(flights.reconcile(lb, _drafts(wallet)[0])) == 0
    tracked = flights.build(
        source="flighty",
        raw_id="fx-1@abc",
        airports=flights.Airports.load(),
        date="2026-03-14",
        carrier="XY",
        number="561",
        from_={"iata": "OSL"},
        to={"iata": "ZRH"},
        times={"actual_departure": "2026-03-14T06:12:00Z", "actual_arrival": "2026-03-14T08:19:00Z"},
    )
    counts: dict[str, int] = {}
    assert lb.append_many(flights.reconcile(lb, [tracked], counts)) == 1
    assert counts["merged"] == 1
    last = [ln for ln in lb.lines() if ln["kind"] == "flight"][-1]
    assert last["source"] == "flighty" and last["payload"]["supersedes"]
    assert {o["source"] for o in last["payload"]["observations"]} == {"ios-wallet", "flighty"}
    assert last["payload"]["extra"]["seat"] == "12A"  # what the pass knew travels along
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES + 1
