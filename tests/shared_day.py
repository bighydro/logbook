"""Two synthetic records that share one Saturday both ways, for the shared-page tests (RFC 0025).
Nobody here exists: Ines Nordmann and Ola Nordmann are the Oslo persona and her brother, both in
`Europe/Oslo`; the day is 2026-06-13, the weekend aboard the yacht Solvind of `persona.py`.

Everything is fixed so the bundles regenerate byte for byte on any machine: the owner ids, every
line's `id` and `recorded_at`, the attachments' bytes, the `created` stamp of each share and the two
sharing keys, whose seeds are derived from fixed synthetic strings below — they sign nothing but
these fixtures. The committed form lives under `tests/fixtures/share/`."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, note, photo, transcript, utc

from logbook.core import share
from logbook.core.store import Logbook

DAY = "2026-06-13"
NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # the DNS namespace, as demo.py uses it
INES_ID = str(uuid.uuid5(NAMESPACE, "share-fixture:ines"))
OLA_ID = str(uuid.uuid5(NAMESPACE, "share-fixture:ola"))
INES_SEED = hashlib.sha256(b"logbook share fixture: ines, synthetic, signs nothing real").digest()
OLA_SEED = hashlib.sha256(b"logbook share fixture: ola, synthetic, signs nothing real").digest()
RECORDED = "2026-06-14T06:00:00Z"  # every line's `recorded_at`: the Sunday morning sync
CREATED = "2026-06-14T18:00:00Z"  # when each page was shared
INES_BUNDLE = "019cadd3-6bc0-7dcd-9133-00000000a001"  # the bundle ids, fixed for the fixture
OLA_BUNDLE = "019cadd3-6bc0-7dcd-9133-00000000a002"
ANCHORAGE = (59.8500, 10.6000)
PHOTO_BYTES = b"\xff\xd8\xff\xe0 not a photo: synthetic bytes for the shared-page fixture \xff\xd9"
TRANSCRIPT_TEXT = b"Ola: Anchor's holding.\nIne: Good. Dinner at eight.\n"
RETRACTED_TEXT = "wrong chat, sorry"
FIXTURES = Path(__file__).parent / "fixtures" / "share"


def _id(n: int) -> str:
    return f"019cadd3-6bc0-7dcd-9133-0000000000{n:02x}"


def _ref(data: bytes, media_type: str) -> dict[str, Any]:
    sha256 = hashlib.sha256(data).hexdigest()
    return {"sha256": sha256, "path": f"attachments/{sha256}", "bytes": len(data), "media_type": media_type}


def _location(at: str, where: tuple[float, float]) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": where[0], "lon": where[1], "raw_id": f"trk:{at}"},
    }


def _steps(at: str, count: int) -> dict[str, Any]:
    return {
        "at": at,
        "end": at,
        "source": "apple-health",
        "kind": "health-sample",
        "tier": 3,
        "payload": {"schema": "health-sample/v1", "type": "steps", "value": count, "unit": "count"},
    }


def _message(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "whatsapp",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "raw_id": f"wa:{at}",
            "chat": {"id": "120363000000000001@g.us", "type": "group", "name": "Crew"},
            "from_me": True,
            "text": text,
        },
    }


def ines_drafts() -> list[dict[str, Any]]:
    """Ines's Saturday aboard: a fix the evening before (not the day), two fixes, the morning's
    steps (tier 3), a photo at the anchorage with its file, a note, a message she took back, and a
    fix after local midnight (the Sunday)."""
    picture = photo(utc(DAY, "19:30"), ANCHORAGE)
    picture["payload"]["media"] = _ref(PHOTO_BYTES, "image/jpeg")
    drafts = [
        _location(utc("2026-06-12", "23:00"), ANCHORAGE),
        _location(utc(DAY, "09:00"), ANCHORAGE),
        _steps(utc(DAY, "08:00"), 4120),
        picture,
        note(utc(DAY, "21:00"), "Anchored off Hovedøya with Ola. Still water, late light."),
        _message(utc(DAY, "21:30"), RETRACTED_TEXT),
        _location(utc(DAY, "22:00"), ANCHORAGE),
        _location(utc("2026-06-14", "00:30"), ANCHORAGE),
    ]
    drafts.append(
        {
            "at": utc(DAY, "21:35"),
            "source": "manual",
            "kind": "retraction",
            "tier": 2,
            "payload": {"schema": "retraction/v1", "supersedes": _id(6), "seq": 6, "reason": "wrong chat"},
        }
    )
    for n, draft in enumerate(drafts, 1):
        draft["id"], draft["recorded_at"] = _id(n), RECORDED
    return drafts


def ola_drafts() -> list[dict[str, Any]]:
    """Ola's Saturday: a fix, a photo of the same anchorage, a transcript with its text as an
    attachment, and a note — the note and the transcript are tier 2."""
    talk = transcript(
        utc(DAY, "20:00"), utc(DAY, "20:10"), "Anchor watch", [{"name": "Ola"}, {"name": "Ines"}]
    )
    talk["payload"]["content"] = _ref(TRANSCRIPT_TEXT, "text/plain")
    drafts = [
        _location(utc(DAY, "09:05"), ANCHORAGE),
        photo(utc(DAY, "19:31"), ANCHORAGE),
        talk,
        note(utc(DAY, "22:00"), "Great weekend aboard Solvind."),
    ]
    for n, draft in enumerate(drafts, 0x10):
        draft["id"], draft["recorded_at"] = _id(n), RECORDED
    return drafts


def _record(root: Path, owner_id: str, drafts: list[dict[str, Any]], files: list[bytes]) -> Logbook:
    lb = Logbook.init(root, TZ)
    lb.set_meta(owner_id=owner_id)
    for data in files:
        lb.attach(data)
    lb.append_many(drafts)
    return lb


def ines_record(tmp_path: Path) -> Logbook:
    """Ines's record under `tmp_path/ines`, Ola allowed to tier 2; the stray message is retracted
    by a line of the drafts, so the head is fixed too."""
    lb = _record(tmp_path / "ines", INES_ID, ines_drafts(), [PHOTO_BYTES])
    _allow(lb, "ola", 2)
    return lb


def ola_record(tmp_path: Path) -> Logbook:
    """Ola's record under `tmp_path/ola`, Ines allowed to tier 1 only."""
    lb = _record(tmp_path / "ola", OLA_ID, ola_drafts(), [TRANSCRIPT_TEXT])
    _allow(lb, "ines", 1)
    return lb


def _allow(lb: Logbook, name: str, max_tier: int) -> None:
    path = lb.root / "policy" / "crossing.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy[name] = {"max_tier": max_tier}
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")


def install_keys() -> None:
    """The two sharing keys at `~/.config/logbook/share/<owner_id>.key` — the test's temporary home
    (`tests/conftest.py`), never the real one."""
    for owner_id, seed in ((INES_ID, INES_SEED), (OLA_ID, OLA_SEED)):
        share.write_key(share.key_path(owner_id), seed)


def both(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, Logbook]:
    """Both records and both keys; `LOGBOOK_HOME` points at Ines's."""
    install_keys()
    ines, ola = ines_record(tmp_path), ola_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(ines.root))
    return ines, ola


def use(monkeypatch: pytest.MonkeyPatch, lb: Logbook) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))


__all__ = ["CREATED", "DAY", "FIXTURES", "INES_BUNDLE", "INES_ID", "OLA_BUNDLE", "OLA_ID", "both", "use"]
