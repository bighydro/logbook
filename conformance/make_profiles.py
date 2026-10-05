"""Regenerates the per-profile conformance fixtures of RFC 0031 (SPEC §6.1): one folder under
`conformance/profiles/<profile>/` for each frozen payload profile, holding

    record/        a one-line record (logbook.json and its month file), the line as its RFC's example
                   gives it, with a fixed id and recorded_at so the bytes are stable
    expected.json  the profile, its RFC, the line's canonical content form and content hash, its hash
                   (the record's head) and the local day the line is on
    show.txt       what `logbook show <day>` prints for the record
    day.json       what `logbook day <day> --json` prints
    days.json      what `logbook show days --from <day> --to <day> --json` prints

The fixture is the freeze: an implementation reproduces the canonical form, the hash and the head;
one with `show` prints the row; one with a reader of §6.1's table prints that reader's JSON after
dropping the fields §3.2 marks as a reader's own. Nothing in it is real: the people, the boat, the
flight and the mail are made up (Oslo, example.org, the XY airline, the UK fictional phone range).
Deterministic and re-runnable; `tests/test_conformance_profiles.py` regenerates into a temp folder
and compares byte for byte. Stdlib and the reference only.

    uv run python conformance/make_profiles.py            # rewrite conformance/profiles/
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.core.chain import CONTENT_FIELDS, canonical_json, content_hash
from logbook.core.store import Logbook

HERE = Path(__file__).parent
OUT = HERE / "profiles"
OWNER = "00000000-0000-4000-8000-000000000001"
CREATED = "2026-03-01T06:00:00Z"
R = "2026-10-05T12:00:00Z"  # recorded_at of every line, so every hash is reproducible
LINE_ID = "00000000-0000-4000-8000-000000000001"
TZ = "Europe/Oslo"
H = "7ed527057371e8656f8754fe8e7492c4bc2355234ec458c19d22f4f6ba060354"  # a synthetic digest

Line = dict[str, Any]


def _line(at: str, end: str | None, source: str, kind: str, tier: int, payload: dict[str, Any]) -> Line:
    return {"at": at, "end": end, "tz": TZ, "source": source, "kind": kind, "tier": tier, "payload": payload}


#: the frozen set of RFC 0031, in its order: profile -> (RFC number, the line as the RFC's example gives it)
FROZEN: dict[str, tuple[str, Line]] = {
    "call/v1": (
        "0012",
        _line(
            "2026-03-02T15:04:10Z",
            "2026-03-02T15:11:35Z",
            "ios-calls",
            "call",
            1,
            {
                "schema": "call/v1",
                "raw_id": "3B1F8E2A-6C4D-4F7B-9A0E-2D5C8B1F4A7E",
                "direction": "incoming",
                "answered": True,
                "duration_s": 445,
                "counterparty": {"kind": "phone", "value": "+447700900001"},
                "service": "cellular",
            },
        ),
    ),
    "event/v1": (
        "0009",
        _line(
            "2026-03-03T08:30:00Z",
            "2026-03-03T09:15:00Z",
            "ios-calendar",
            "event",
            1,
            {
                "schema": "event/v1",
                "raw_id": "7E0C2D4A-9B1F-4C7E-8A2B-5D3E1F6A9C0B@2026-02-27T16:05:00Z",
                "title": "Boat survey — Tromsø marina",
                "calendar": {"id": "A1B2", "name": "Personal"},
                "all_day": False,
                "location": "Tromsø småbåthavn",
                "attendees": [
                    {
                        "ref": {"kind": "email", "value": "ola@example.org"},
                        "name": "Ola Nordmann",
                        "response": "accepted",
                    }
                ],
                "status": "confirmed",
            },
        ),
    ),
    "flight/v1": (
        "0013",
        _line(
            "2026-09-27T05:12:00Z",
            "2026-09-27T06:21:00Z",
            "manual",
            "flight",
            1,
            {
                "schema": "flight/v1",
                "raw_id": "2026-09-27:XY:561@3f9a1c2b7e4d",
                "date": "2026-09-27",
                "carrier": "XY",
                "number": "561",
                "from": {"iata": "OSL"},
                "to": {"iata": "ZRH"},
                "actual_departure": "2026-09-27T05:12:00Z",
                "actual_arrival": "2026-09-27T06:21:00Z",
                "role": "pilot",
                "evidence": "declared",
                "observations": [{"evidence": "declared", "source": "manual"}],
            },
        ),
    ),
    "health-sample/v1": (
        "0014",
        _line(
            "2026-03-02T07:00:00Z",
            "2026-03-02T07:15:00Z",
            "apple-health",
            "health",
            3,
            {
                "schema": "health-sample/v1",
                "raw_id": "steps:2026-03-02T07:00:00Z:Watch7,1",
                "type": "steps",
                "value": 250,
                "unit": "count",
                "device": "Watch7,1",
                "source_name": "Apple Watch",
                "extra": {"samples": 3},
            },
        ),
    ),
    "keeper/v1": (
        "0024",
        _line(
            "2026-06-10T10:30:00Z",
            None,
            "keeper-inference",
            "keeper",
            1,
            {
                "schema": "keeper/v1",
                "raw_id": "01a0f6a2-068b-7572-94ea-f492e749c3d6:memory",
                "photo": {
                    "line": "01a0f6a2-068b-7572-94ea-f492e749c3d6",
                    "asset_id": "p-2026-06-10T10:30:00Z",
                    "library": "immich",
                    "file_name": "IMG_101030.HEIC",
                },
                "at": "2026-06-10T10:30:00Z",
                "lane": "memory",
                "source": "immich",
            },
        ),
    ),
    "listen/v1": (
        "0019",
        _line(
            "2026-03-04T20:15:30Z",
            None,
            "shazam",
            "listen",
            2,
            {
                "schema": "listen/v1",
                "raw_id": "shazam:100000001:2026-03-04 21:15:30",
                "media": "track",
                "title": "Fjordsang",
                "artist": "Kari Nordmann",
                "url": "https://www.shazam.com/track/100000001/fjordsang",
                "service": "shazam",
            },
        ),
    ),
    "location/v1": (
        "0001",
        _line(
            "2026-03-01T07:30:00Z",
            None,
            "dawarich",
            "location",
            1,
            {
                "schema": "location/v1",
                "lat": 59.911,
                "lon": 10.750,
                "accuracy_m": 12,
                "provider": "fused",
                "tracker": "iphone",
                "raw_id": "184223",
            },
        ),
    ),
    "mail/v1": (
        "0015",
        _line(
            "2026-03-02T10:15:00Z",
            None,
            "mail",
            "mail",
            2,
            {
                "schema": "mail/v1",
                "raw_id": "kari.nordmann@example.org:a1b2c3@mail.example.org",
                "message_id": "a1b2c3@mail.example.org",
                "thread": "9f8e7d@mail.example.org",
                "from": {"email": "ola@example.org", "name": "Ola Nordmann"},
                "to": [{"email": "kari.nordmann@example.org", "name": "Kari Nordmann"}],
                "subject": "Re: Mooring for the weekend",
                "date": "2026-03-02T11:15:00+01:00",
                "direction": "received",
                "labels": ["Inbox", "Important"],
                "body": "Photos attached. The east berth is free from Friday.\n",
                "size": 48213,
                "account": "kari.nordmann@example.org",
                "attachments": [{"filename": "berth.jpg", "media_type": "image/jpeg", "bytes": 41002}],
                "extra": {
                    "gmail_thread_id": "1795123456789012345",
                    "in_reply_to": "9f8e7d@mail.example.org",
                    "references": ["9f8e7d@mail.example.org"],
                },
            },
        ),
    ),
    "message/v1": (
        "0008",
        _line(
            "2026-03-02T17:42:10Z",
            None,
            "whatsapp",
            "message",
            2,
            {
                "schema": "message/v1",
                "raw_id": "3EB0A1F5C2D4E6B7",
                "chat": {"id": "447700900000@s.whatsapp.net", "type": "direct", "name": "Ola"},
                "from_me": False,
                "sender": {"kind": "phone", "value": "+447700900000"},
                "text": "mooring photos sent, check your mail",
            },
        ),
    ),
    "note/v1": (
        "0010",
        _line(
            "2026-03-04T21:10:00Z",
            None,
            "manual",
            "note",
            2,
            {"schema": "note/v1", "text": "Decided: keep the boat one more season."},
        ),
    ),
    "photo/v1": (
        "0002",
        _line(
            "2026-03-01T09:12:00Z",
            None,
            "immich",
            "photo",
            1,
            {
                "schema": "photo/v1",
                "asset_id": "p-2026-03-01T09:12:00Z",
                "library": "immich",
                "file_name": "IMG_0001.HEIC",
                "media": "image",
                "lat": 59.913,
                "lon": 10.742,
                "camera": "SimPhone 3",
                "width": 4032,
                "height": 3024,
                "live_photo": True,
                "provenance": "camera",
                "faces": 2,
                "people": ["p_17", "p_42"],
            },
        ),
    ),
    "received/v1": (
        "0030",
        _line(
            "2026-06-13T09:00:00Z",
            None,
            "received",
            "received",
            1,
            {
                "schema": "received/v1",
                "raw_id": "p-2026-06-13T09:00:00Z",
                "line": {
                    "id": "01a0ffdb-2a0c-7b3e-8d41-0c7a2f9e1b05",
                    "seq": 411,
                    "at": "2026-06-13T09:00:00Z",
                    "end": None,
                    "tz": TZ,
                    "source": "immich",
                    "kind": "photo",
                    "tier": 1,
                    "payload": {
                        "schema": "photo/v1",
                        "asset_id": "p-2026-06-13T09:00:00Z",
                        "library": "immich",
                        "file_name": "IMG_130900.HEIC",
                        "media": "image",
                        "provenance": "camera",
                        "faces": 1,
                        "people": ["p_17"],
                        "lat": 60.8604,
                        "lon": 8.5506,
                        "raw_id": "p-2026-06-13T09:00:00Z",
                    },
                    "recorded_at": "2026-06-14T18:02:11Z",
                    "prev": "5c0e" + "0" * 60,
                    "hash": "9b1f" + "0" * 60,
                },
                "extra": {
                    "from": "019cadd3-6bc0-7dcd-9133-00000000b000",
                    "sender": "Ola Nordmann",
                    "bundle_id": "01a0ffdb-7c2e-7a1d-9f00-1e2d3c4b5a69",
                    "logbook_head": "53d39fda" + "0" * 56,
                    "package_sha256": "258a4267" + "0" * 56,
                    "received_at": "2026-06-20T08:15:00Z",
                },
            },
        ),
    ),
    "resolution/v1": (
        "0006",
        _line(
            "2026-03-02T09:14:00Z",
            None,
            "manual",
            "resolution",
            2,
            {
                "schema": "resolution/v1",
                "ref": {"kind": "email", "value": "ola@example.org"},
                "entity": {
                    "type": "person",
                    "id": "019cadd3-6bc0-7dcd-9133-043f5aabf2a9",
                    "registry": "logbook",
                },
                "label": "Ola Nordmann",
                "method": "owner",
            },
        ),
    ),
    "retraction/v1": (
        "0003",
        _line(
            "2026-03-02T21:14:00Z",
            None,
            "manual",
            "retraction",
            2,
            {
                "schema": "retraction/v1",
                "supersedes": "0195d1c2-7e40-7d3a-9b1e-4a2f1c8e0b77",
                "seq": 312,
                "reason": "two file paths pasted as a note by mistake",
            },
        ),
    ),
    "story/v1": (
        "0028",
        _line(
            "2026-06-10T18:30:00Z",
            None,
            "manual",
            "story",
            2,
            {
                "schema": "story/v1",
                "raw_id": "story:5a6b1f0e8c3d9a7b2e4f6c8d0a1b3c5e7f9a0b2c4d6e8f0a1b3c5d7e9f1a3b5c",
                "title": "The house by the lake",
                "text": "In 1961 we moved to the house by the lake. Father rowed the furniture across in two "
                "trips; the piano went last, on a raft he had built that morning.",
                "told_at": "2026-06-10T18:30:00Z",
                "refers_to": {"text": "1961", "from": "1961-01-01", "to": "1961-12-31", "precision": "year"},
                "teller": {"ref": {"kind": "email", "value": "ola@example.org"}, "name": "Ola Nordmann"},
                "listener": {
                    "ref": {"kind": "email", "value": "kari.nordmann@example.org"},
                    "name": "Kari Nordmann",
                },
                "confidence": "sure",
                "source": "conversation",
            },
        ),
    ),
    "task/v1": (
        "0016",
        _line(
            "2026-03-04T12:10:00Z",
            None,
            "google-takeout",
            "task",
            2,
            {
                "schema": "task/v1",
                "raw_id": "aGVsbG8tcm9wZQ@2026-03-04T12:10:00Z",
                "title": "Buy the long rope",
                "status": "done",
                "due": "2026-03-05",
                "completed_at": "2026-03-04T12:10:00Z",
                "list": "My Tasks",
                "notes": "30 m, 12 mm. Ask at the chandlery on Storgata 1.",
                "modified_at": "2026-03-04T12:10:00Z",
                "extra": {
                    "hidden": True,
                    "links": [
                        {
                            "type": "email",
                            "description": "the quote",
                            "url": "https://mail.example.org/u/0/#inbox/abc",
                        }
                    ],
                },
            },
        ),
    ),
    "transaction/v1": (
        "0021",
        _line(
            "2026-03-01T23:00:00Z",
            None,
            "copilot",
            "transaction",
            3,
            {
                "schema": "transaction/v1",
                "raw_id": "6f1c2a9e-0000-4000-8000-000000000001",
                "amount": -42.5,
                "currency": "USD",
                "merchant": "Harbour Cafe",
                "category": "restaurants",
                "date": "2026-03-02",
                "account": "acct_0000000000000001",
                "provider": "copilot",
                "status": "posted",
                "extra": {"type": "regular", "recurring": False, "original_name": "HARBOUR CAFE OSLO"},
            },
        ),
    ),
    "transcript/v1": (
        "0004",
        _line(
            "2026-03-01T13:00:00Z",
            "2026-03-01T13:35:00Z",
            "granola",
            "transcript",
            2,
            {
                "schema": "transcript/v1",
                "provider": "granola",
                "raw_id": "note_7f3a2b",
                "title": "Catch-up with Ines",
                "participants": [{"name": "Ines", "email": "ines@example.org"}, {"name": "Ola Nordmann"}],
                "summary": "Ines is moving to Tromsø in May; talked over a northern-lights trip.",
                "language": "en",
                "content": {
                    "sha256": H,
                    "path": f"attachments/{H}",
                    "bytes": 48213,
                    "media_type": "text/markdown",
                },
                "source_uri": "https://granola.example/notes/7f3a2b",
            },
        ),
    ),
    "weather/v1": (
        "0026",
        _line(
            "2026-06-15T22:00:00Z",
            "2026-06-16T22:00:00Z",
            "weather",
            "weather",
            1,
            {
                "schema": "weather/v1",
                "raw_id": "2026-06-16@47.4,8.5",
                "day": "2026-06-16",
                "lat": 47.4,
                "lon": 8.5,
                "t_min_c": 14.1,
                "t_max_c": 26.8,
                "precipitation_mm": 0.3,
                "wind_max_kmh": 18.7,
                "weather_code": 2,
                "sunrise": "2026-06-16T03:30:00Z",
                "sunset": "2026-06-16T19:25:00Z",
                "evidence": "external",
                "provider": "open-meteo",
                "dataset": "archive",
            },
        ),
    ),
}


def _run(root: Path, args: list[str]) -> str:
    """`logbook <args>` on the record at `root`, in this process; its stdout."""
    import os

    out = io.StringIO()
    before = os.environ.get("LOGBOOK_HOME")
    os.environ["LOGBOOK_HOME"] = str(root)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                cli.main(args)
            except SystemExit as e:
                if e.code not in (None, 0):
                    raise AssertionError(
                        f"logbook {' '.join(args)} exited {e.code}:\n{out.getvalue()}"
                    ) from e
    finally:
        if before is None:
            del os.environ["LOGBOOK_HOME"]
        else:
            os.environ["LOGBOOK_HOME"] = before
    return out.getvalue()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # bytes: no CRLF translation on Windows


def build(profile: str, out: Path) -> None:
    """The fixture of one frozen profile under `out` (replaced)."""
    rfc, draft = FROZEN[profile]
    if out.exists():
        shutil.rmtree(out)
    record = out / "record"
    lb = Logbook.init(record, TZ)
    meta = lb.meta
    meta["owner_id"] = OWNER
    meta["created_at"] = CREATED
    lb._save_meta(meta)
    lb.append(
        at=draft["at"],
        end=draft["end"],
        source=draft["source"],
        kind=draft["kind"],
        tier=draft["tier"],
        payload=draft["payload"],
        recorded_at=R,
    )
    (month,) = sorted(record.glob("logbook/*/*.jsonl"))
    line = json.loads(month.read_text(encoding="utf-8"))
    line["id"] = LINE_ID  # outside the hash (SPEC §2); fixed so the bytes are stable
    _write(month, json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    seq, head, errors = lb.verify()
    assert seq == 1 and not errors, (profile, errors)
    local_day = (
        datetime.strptime(line["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(ZoneInfo(TZ))
    )
    day = local_day.strftime("%Y-%m-%d")
    content = {k: line.get(k) for k in CONTENT_FIELDS}
    _write(
        out / "expected.json",
        json.dumps(
            {
                "profile": profile,
                "rfc": rfc,
                "kind": line["kind"],
                "tier": line["tier"],
                "day": day,
                "seq": seq,
                "canonical": canonical_json(content),
                "content_hash": content_hash(line),
                "hash": line["hash"],
                "head": head,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    _write(out / "show.txt", _run(record, ["show", day]))
    _write(out / "day.json", _run(record, ["day", day, "--json"]))
    _write(out / "days.json", _run(record, ["show", "days", "--from", day, "--to", day, "--json"]))
    for stale in list(record.rglob("index.sqlite*")) + list(record.rglob("*.sqlite-journal")):
        stale.unlink()  # the index is a cache, never part of a fixture (ADR 0007)
    shutil.rmtree(record / "policy", ignore_errors=True)  # settings, not record (SPEC §1)
    for folder in sorted((d for d in record.rglob("*") if d.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()  # `init` makes inbox/ and notes/ empty; git keeps no empty folder, nor does this


def main(out: Path = OUT) -> None:
    for profile in FROZEN:
        build(profile, out / profile.split("/")[0])
        print(profile, "->", out / profile.split("/")[0])


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
