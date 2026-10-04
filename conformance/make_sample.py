"""Regenerates the synthetic sample logbook. A fictional person, a fictional town, one week.
Deterministic: fixed ids are not required by the spec, but fixed recorded_at keeps the head stable.

Three lines carry values that RFC 8785 lays out differently from Python's json.dumps (SPEC §3.1):
120.0, 0.0, 1e20, 1e-06 and an object key outside the BMP. A canonicaliser that gets those wrong
cannot reproduce the head.

The first sixteen lines are the v0.2 sample and never change. The lines after them, all on the
Sunday, carry one payload of each profile added since (RFCs 0011 to 0024, and a location with a
`subject`), shaped as their RFCs describe, so a verifier meets every schema the reference writes.
Nothing in it is real: the person, the boat, the flight, the book and the mail are made up."""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import FORMAT
from logbook.core.store import Logbook

HERE = Path(__file__).parent
ROOT = HERE / "sample-logbook"
if ROOT.exists():
    shutil.rmtree(ROOT)
lb = Logbook.init(ROOT, "Europe/Oslo")
meta = lb.meta
meta["owner_id"] = "00000000-0000-4000-8000-000000000001"
meta["created_at"] = "2026-03-01T06:00:00Z"
lb._save_meta(meta)

R = "2026-03-08T20:00:00Z"  # recorded_at for every line, so the head is reproducible
rows = [
    (
        "2026-03-01T07:30:00Z",
        None,
        "sim-phone",
        "location",
        1,
        {
            "schema": "location/v1",
            "lat": 59.911,
            "lon": 10.750,
            "accuracy_m": 12,
            "alt_m": 120.0,
            "speed_mps": 0.0,
        },
    ),
    (
        "2026-03-01T08:05:00Z",
        "2026-03-01T08:40:00Z",
        "sim-phone",
        "location",
        1,
        {"schema": "location/v1", "lat": 59.913, "lon": 10.742, "accuracy_m": 8, "note": "walk"},
    ),
    (
        "2026-03-01T09:00:00Z",
        "2026-03-01T10:00:00Z",
        "sim-calendar",
        "event",
        1,
        {"schema": "event/v1", "title": "Coffee with Ines", "attendees": ["ines@example.org"]},
    ),
    (
        "2026-03-01T09:12:00Z",
        None,
        "sim-camera",
        "photo",
        1,
        {"schema": "photo/v1", "file": "IMG_0001.jpg", "lat": 59.913, "lon": 10.742, "camera": "SimPhone 3"},
    ),
    (
        "2026-03-01T21:00:00Z",
        None,
        "manual",
        "note",
        2,
        {
            "schema": "note/v1",
            "text": "Ines is moving to Tromsø in May. Ask her about the northern lights trip.",
        },
    ),
    (
        "2026-03-01T22:30:00Z",
        "2026-03-02T06:45:00Z",
        "sim-watch",
        "sleep",
        3,
        {
            "schema": "health-sample/v1",
            "metric": "sleep",
            "hours": 8.25,
            "calibration": {"gain": 1e21, "offset": 1e20, "epsilon": 1e-06},
        },
    ),
    (
        "2026-03-02T12:10:00Z",
        None,
        "sim-bank",
        "transaction",
        3,
        {"schema": "transaction/v1", "amount": -14.50, "currency": "EUR", "merchant": "Bakeri Nord"},
    ),
    (
        "2026-03-02T12:15:00Z",
        None,
        "sim-camera",
        "photo",
        1,
        {"schema": "photo/v1", "file": "IMG_0002.jpg", "camera": "SimPhone 3"},
    ),
    (
        "2026-03-03T17:00:00Z",
        "2026-03-03T18:10:00Z",
        "sim-watch",
        "workout",
        1,
        {"schema": "activity/v1", "sport": "run", "distance_km": 9.8},
    ),
    (
        "2026-03-03T21:00:00Z",
        None,
        "manual",
        "note",
        2,
        {"schema": "note/v1", "text": "First 10k since the winter. Slow, happy."},
    ),
    (
        "2026-03-05T06:00:00Z",
        "2026-03-05T08:15:00Z",
        "sim-flights",
        "flight",
        1,
        {"schema": "flight/v1", "from": "OSL", "to": "CPH", "carrier": "SIM", "number": "SIM123"},
    ),
    (
        "2026-03-05T10:00:00Z",
        "2026-03-05T11:30:00Z",
        "sim-calendar",
        "event",
        1,
        {"schema": "event/v1", "title": "Board meeting", "attendees": ["j@example.org", "k@example.org"]},
    ),
    (
        "2026-03-05T21:00:00Z",
        None,
        "manual",
        "decision",
        2,
        {
            "schema": "decision/v1",
            "text": "Say yes to the Copenhagen role.",
            "rationale": "closer to the sea",
            "revisit": "2026-09-05",
        },
    ),
    (
        "2026-03-06T19:30:00Z",
        None,
        "sim-messages",
        "message",
        2,
        {
            "schema": "message/v1",
            "chat": "Ines",
            "direction": "in",
            "text": "Landed? Dinner Sunday?",
            "reactions": {
                chr(0x1F600): 2,
                chr(0xFB33): 1,
            },  # UTF-16 order: U+1F600 first; code-point order: last
        },
    ),
    (
        "2026-03-07T18:00:00Z",
        "2026-03-07T21:00:00Z",
        "sim-calendar",
        "event",
        1,
        {"schema": "event/v1", "title": "Dinner with Ines", "location": "Bakeri Nord"},
    ),
    (
        "2026-03-07T21:30:00Z",
        None,
        "manual",
        "note",
        2,
        {"schema": "note/v1", "text": "Told her about Copenhagen. She laughed and said she'd visit by boat."},
    ),
    # -- v0.5: one line per profile added since v0.2, all on Sunday the 8th -----------------
    (  # location/v1 with a subject (RFC 0001, ADR 0018): the boat's position, not the owner's
        "2026-03-08T06:00:00Z",
        None,
        "ais",
        "location",
        1,
        {
            "schema": "location/v1",
            "lat": 59.905,
            "lon": 10.735,
            "speed_mps": 2.6,
            "heading_deg": 184,
            "tracker": "aisstream",
            "raw_id": "aisstream:999000001:1772949600",
            "subject": "solvind",
            "extra": {"mmsi": "999000001"},
        },
    ),
    (  # health-sample/v1 (RFC 0014), kind `health`
        "2026-03-08T06:30:00Z",
        "2026-03-08T06:45:00Z",
        "apple-health",
        "health",
        3,
        {
            "schema": "health-sample/v1",
            "raw_id": "steps:2026-03-08T06:30:00Z:SimWatch",
            "type": "steps",
            "value": 250,
            "unit": "count",
            "device": "SimWatch",
            "source_name": "Sim Watch",
        },
    ),
    (  # call/v1 (RFC 0012)
        "2026-03-08T07:05:00Z",
        "2026-03-08T07:12:25Z",
        "ios-calls",
        "call",
        1,
        {
            "schema": "call/v1",
            "raw_id": "00000000-0000-4000-8000-00000000c001",
            "direction": "incoming",
            "answered": True,
            "duration_s": 445,
            "counterparty": {"kind": "phone", "value": "+4790000001"},
            "service": "cellular",
        },
    ),
    (  # browse/v1 (RFC 0017)
        "2026-03-08T08:00:00Z",
        None,
        "safari",
        "browse",
        2,
        {
            "schema": "browse/v1",
            "raw_id": "safari:763113600:1a6ee1a9f1c5be3e",
            "url": "https://havn.example.org/winter-guide",
            "title": "Oslofjord: a winter guide",
            "action": "visit",
            "browser": "safari",
        },
    ),
    (  # watch/v1 (RFC 0018)
        "2026-03-08T08:30:00Z",
        None,
        "google-takeout",
        "watch",
        2,
        {
            "schema": "watch/v1",
            "raw_id": "youtube:2026-03-08T08:30:00.123Z:5e2a4f0c9d1b7a3e",
            "action": "watched",
            "title": "Splicing a three-strand rope",
            "url": "https://www.youtube.com/watch?v=aB3dE5fG7hI",
            "video_id": "aB3dE5fG7hI",
            "channel": {"name": "Knots by Ola"},
            "service": "youtube",
        },
    ),
    (  # task/v1 (RFC 0016)
        "2026-03-08T09:00:00Z",
        None,
        "google-takeout",
        "task",
        2,
        {
            "schema": "task/v1",
            "raw_id": "aGVsbG8tcm9wZQ@2026-03-08T09:00:00Z",
            "title": "Buy the long rope",
            "status": "done",
            "due": "2026-03-09",
            "completed_at": "2026-03-08T09:00:00Z",
            "list": "Boat",
            "modified_at": "2026-03-08T09:00:00Z",
        },
    ),
    (  # mail/v1 (RFC 0015); the attachment is referenced by digest, not stored (rule 5)
        "2026-03-08T09:30:00Z",
        None,
        "mail",
        "mail",
        2,
        {
            "schema": "mail/v1",
            "raw_id": "kari@example.org:a1b2c3@mail.example.org",
            "message_id": "a1b2c3@mail.example.org",
            "from": {"email": "ines@example.org", "name": "Ines"},
            "to": [{"email": "kari@example.org", "name": "Kari"}],
            "subject": "Mooring for the weekend",
            "date": "2026-03-08T10:30:00+01:00",
            "direction": "received",
            "body": "The east berth is free from Friday.\n",
            "account": "kari@example.org",
            "attachments": [
                {
                    "filename": "berth.jpg",
                    "media_type": "image/jpeg",
                    "sha256": "9c56cc51b374c3ba189210d5b6d4bf57790d351c96c47c02190ecf1e430635ab",
                    "bytes": 41002,
                }
            ],
        },
    ),
    (  # listen/v1 (RFC 0019)
        "2026-03-08T10:00:00Z",
        None,
        "shazam",
        "listen",
        2,
        {
            "schema": "listen/v1",
            "raw_id": "shazam:100000001:2026-03-08 11:00:00",
            "media": "track",
            "title": "Fjordsang",
            "artist": "Kari Nordmann",
            "service": "shazam",
        },
    ),
    (  # trip/v1 (RFC 0020): a parking session, one place, tier 3 because it carries a price
        "2026-03-08T10:30:00Z",
        "2026-03-08T12:30:00Z",
        "easypark",
        "trip",
        3,
        {
            "schema": "trip/v1",
            "raw_id": "easypark:114681@2026-03-08T10:30:00Z",
            "mode": "parking",
            "provider": "easypark",
            "from": {"name": "Storgata 1-36", "code": "8291", "latitude": 59.9139, "longitude": 10.7522},
            "price": {"amount": 58, "currency": "NOK"},
            "status": "completed",
        },
    ),
    (  # transaction/v1 (RFC 0021)
        "2026-03-08T11:00:00Z",
        None,
        "sim-bank",
        "transaction",
        3,
        {
            "schema": "transaction/v1",
            "raw_id": "00000000-0000-4000-8000-00000000d001",
            "amount": -42.5,
            "currency": "NOK",
            "merchant": "Bakeri Nord",
            "category": "restaurants",
            "date": "2026-03-08",
            "account": "acct_0000000000000001",
            "provider": "sim-bank",
            "status": "posted",
        },
    ),
    (  # flight/v1 (RFC 0013), evidence `tracked`
        "2026-03-08T13:10:00Z",
        "2026-03-08T14:24:00Z",
        "sim-flights",
        "flight",
        1,
        {
            "schema": "flight/v1",
            "raw_id": "fx-0002@8c1d0e5a9b2f",
            "date": "2026-03-08",
            "carrier": "SIM",
            "number": "124",
            "from": {"iata": "CPH"},
            "to": {"iata": "OSL"},
            "scheduled_departure": "2026-03-08T13:05:00Z",
            "actual_departure": "2026-03-08T13:10:00Z",
            "scheduled_arrival": "2026-03-08T14:20:00Z",
            "actual_arrival": "2026-03-08T14:24:00Z",
            "aircraft": {"type": "A320", "registration": "ZZ-ABC"},
            "role": "passenger",
            "evidence": "tracked",
            "observations": [{"evidence": "tracked", "source": "sim-flights"}],
        },
    ),
    (  # highlight/v1 (RFC 0022)
        "2026-03-08T15:00:00Z",
        None,
        "apple-books",
        "highlight",
        2,
        {
            "schema": "highlight/v1",
            "raw_id": "00000000-0000-4000-8000-00000000e001",
            "type": "highlight",
            "title": "The Long Ships",
            "author": "Frans G. Bengtsson",
            "quote": "They sailed west until the coast was a line and then was nothing.",
            "note": "the moment the book turns",
            "location": "epubcfi(/6/14!/4/2/8,/1:0,/1:66)",
        },
    ),
    (  # voice-memo/v1 (RFC 0023); the audio is referenced by digest, not stored (no `path`)
        "2026-03-08T16:00:00Z",
        "2026-03-08T16:01:42Z",
        "voice-memos",
        "voice-memo",
        2,
        {
            "schema": "voice-memo/v1",
            "raw_id": "00000000-0000-4000-8000-00000000f001",
            "title": "Idea for the talk",
            "duration_s": 102.4,
            "file_name": "20260308 170000.m4a",
            "media": {
                "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                "bytes": 1638400,
                "media_type": "audio/mp4",
            },
        },
    ),
    (  # crossing/v1 (RFC 0011): the record's own note that a window left it
        "2026-03-08T19:00:00Z",
        None,
        "logbook",
        "crossing",
        1,
        {
            "schema": "crossing/v1",
            "destination": "hermes",
            "bundle_id": "00000000-0000-4000-8000-0000000000c1",
            "window": {"from": "2026-03-01T00:00:00Z", "to": "2026-03-08T00:00:00Z"},
            "tiers": [1],
            "counts": {
                "logged": 16,
                "crossed": 8,
                "held_back": 8,
                "by_tier": {"1": 8, "2": 6, "3": 2},
                "by_kind": {"location": 2, "event": 3, "photo": 2, "flight": 1},
                "resolutions": 0,
                "resolutions_held_back": 0,
                "attachments": {"included": 0, "bytes": 0, "missing": 0},
            },
            "policy": {"file": "policy/crossing.json", "max_tier": 2},
            "logbook_head": "53d39fdad121ce8e448221bbdaa9c86396c16347d050bf630035d6f1d37088e6",
            "package_sha256": "9afdd1bd5f7e4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a1908f7e6d5c4b3",
        },
    ),
    (  # keeper/v1 (RFC 0024): the first photo marked a memory; `at` is the photo's, so the line is
        # written after the others and still belongs to the 1st (chain order is not time order)
        "2026-03-01T09:12:00Z",
        None,
        "keeper-inference",
        "keeper",
        1,
        {
            "schema": "keeper/v1",
            "raw_id": "00000000-0000-4000-8000-000000000004:memory",
            "photo": {
                "line": "00000000-0000-4000-8000-000000000004",
                "asset_id": "IMG_0001",
                "library": "sim-camera",
                "file_name": "IMG_0001.jpg",
            },
            "at": "2026-03-01T09:12:00Z",
            "lane": "memory",
            "source": "sim-camera",
        },
    ),
]
for at, end, src, kind, tier, payload in rows:
    lb.append(at=at, end=end, source=src, kind=kind, tier=tier, payload=payload, recorded_at=R)
# fixed ids so the fixture is byte-stable across regenerations; bytes, so Windows writes no CRLF
for f in sorted(ROOT.glob("logbook/*/*.jsonl")):
    out = []
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        row["id"] = f"00000000-0000-4000-8000-{i:012d}"
        out.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    f.write_bytes(("\n".join(out) + "\n").encode("utf-8"))
(ROOT / "notes" / "2026").mkdir(parents=True, exist_ok=True)
(ROOT / "notes" / "2026" / "2026-03-07.md").write_bytes(b"A good week. The decision is made; now live it.\n")
# the sample is the folder SPEC §1 names; the policies `init` writes are settings, not record
shutil.rmtree(ROOT / "policy", ignore_errors=True)
seq, head, errors = lb.verify()
assert not errors, errors
(HERE / "expected.json").write_bytes(
    (json.dumps({"format": FORMAT, "seq": seq, "head": head}, indent=2) + "\n").encode("utf-8")
)
print("sample logbook:", seq, "lines, head", head)
