"""Regenerates the synthetic sample logbook. A fictional person, a fictional town, one week.
Deterministic: fixed ids are not required by the spec, but fixed recorded_at keeps the head stable.

Three lines carry values that RFC 8785 lays out differently from Python's json.dumps (SPEC §3.1):
120.0, 0.0, 1e20, 1e-06 and an object key outside the BMP. A canonicaliser that gets those wrong
cannot reproduce the head."""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import FORMAT
from logbook.store import Logbook

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
]
for at, end, src, kind, tier, payload in rows:
    lb.append(at=at, end=end, source=src, kind=kind, tier=tier, payload=payload, recorded_at=R)
# fixed ids so the fixture is byte-stable across regenerations
for f in sorted(ROOT.glob("logbook/*/*.jsonl")):
    out = []
    for i, line in enumerate(f.read_text().splitlines(), 1):
        row = json.loads(line)
        row["id"] = f"00000000-0000-4000-8000-{i:012d}"
        out.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    f.write_text("\n".join(out) + "\n")
(ROOT / "notes" / "2026").mkdir(parents=True, exist_ok=True)
(ROOT / "notes" / "2026" / "2026-03-07.md").write_text("A good week. The decision is made; now live it.\n")
seq, head, errors = lb.verify()
assert not errors, errors
(HERE / "expected.json").write_text(json.dumps({"format": FORMAT, "seq": seq, "head": head}, indent=2) + "\n")
print("sample logbook:", seq, "lines, head", head)
