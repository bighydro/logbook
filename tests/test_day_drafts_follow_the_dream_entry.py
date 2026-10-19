"""Day drafts are held to the `dream` entry in the crossing package too (the owner's answer to #332's
open question, 19 October 2026): #332 made a person draft cross only while the `relationship` entry
allows its tier; every other draft unit (day, journey, week, event) crosses only while the `dream`
entry it was written under allows its tier, whatever the destination's ceiling, and one that stays
home is counted in `held_back_by_entry`. With the `dream` entry live the bundle is byte for byte as
before. Synthetic Oslo persona: Ines and Ola Nordmann, who do not exist."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import videos
from logbook.core import crossing, drafts, policy
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-06-12"
BUNDLE_ID = "019ca000-0000-7000-8000-00000000c0de"
GENERATED_AT = "2026-06-20T08:00:00Z"


def _location(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"dawarich:{at}"},
    }


def _draft(unit: str, subject: object, evidence: str, tier: int, at: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA,
        "unit": unit,
        "subject": subject,
        "read_head": "0" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": f"A {unit} at the marina.", "evidence": [evidence]}],
        "extra": {"prompt": "test/1", "parts": [unit], "policy_version": "0" * 64, "entry": "dream"},
    }
    if unit == drafts.UNIT_PERSON:
        payload[drafts.WINDOW] = {"from": "2026-06-01", "to": DAY}
        payload["extra"]["entry"] = drafts.PERSON_ENTRY
    assert drafts.validate(payload) == []
    return {"at": at, "source": "model:local-7b", "kind": drafts.KIND, "tier": tier, "payload": payload}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """12 June 2026: one location, then a draft of each unit the `dream` entry writes, at tier 2,
    and Ola's person draft at tier 2."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    lb.append(**_location(f"{DAY}T08:00:00Z"))  # seq 1
    location = str(next(iter(lb.lines()))["id"])
    lb.append_many(
        [
            _draft(drafts.UNIT_DAY, DAY, location, 2, f"{DAY}T21:00:00Z"),  # seq 2
            _draft(drafts.UNIT_JOURNEY, [location], location, 2, f"{DAY}T21:01:00Z"),  # seq 3
            _draft(drafts.UNIT_WEEK, "2026-W24", location, 2, f"{DAY}T21:02:00Z"),  # seq 4
            _draft(drafts.UNIT_EVENT, [location], location, 2, f"{DAY}T21:03:00Z"),  # seq 5
            _draft(drafts.UNIT_PERSON, "ent-ola-nordmann", location, 2, f"{DAY}T21:04:00Z"),  # seq 6
        ]
    )
    return lb


def _policy(lb: Logbook, dream: dict[str, Any] | None) -> None:
    found: dict[str, Any] = {
        "circle": {"max_tier": 3},
        "relationship": {"max_tier": 2, "until": "2026-12-31"},
    }
    if dream is not None:
        found["dream"] = dream
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found), encoding="utf-8")


LIVE = {"max_tier": 2, "until": "2026-12-31"}


def _ids(lb: Logbook) -> dict[int, str]:
    return {int(line["seq"]): str(line["id"]) for line in lb.lines()}


def _request(lb: Logbook) -> crossing.Request:
    return crossing.request(
        lb, "circle", f"{DAY}T00:00:00Z", "2026-06-13T00:00:00Z", (1, 2, 3), signed_only=False
    )


def _crossed(lb: Logbook) -> crossing.Selection:
    return crossing.select(lb, _request(lb))


def _bundle(lb: Logbook, out: Path) -> dict[tuple[str, ...], bytes]:
    """The package's files, byte for byte, written with a pinned id and clock (nothing appended)."""
    req = _request(lb)
    sel = crossing.select(lb, req)
    head = str(lb.meta["head"])
    manifest = crossing.build_manifest(lb, req, sel, GENERATED_AT, BUNDLE_ID, head)
    crossing.write_bundle(lb, sel, manifest, out, req)
    return {p.relative_to(out).parts: p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


@pytest.mark.parametrize(
    "dream",
    [
        {"max_tier": 2, "until": "2026-06-15"},  # expired: today is the 20th
        {"max_tier": 1, "until": "2026-12-31"},  # lowered below the drafts' tier
        None,  # removed
    ],
    ids=["expired", "lowered", "removed"],
)
def test_a_draft_the_dream_entry_no_longer_allows_stays_home_and_is_counted(lb: Logbook, dream: Any):
    _policy(lb, dream)
    ids = _ids(lb)
    sel = _crossed(lb)
    crossed = {str(line["id"]) for line in sel.lines}
    for seq in (2, 3, 4, 5):  # day, journey, week, event: the destination's ceiling is 3, the dream's lower
        assert ids[seq] not in crossed, seq
    assert ids[1] in crossed, "a line that is not a draft is the tier's alone"
    assert ids[6] in crossed, "a person draft follows the relationship entry, which is live"
    assert sel.counts()["held_back_by_entry"] == 4
    assert sel.counts()["by_kind"] == {"draft": 1, "location": 1}


def test_a_draft_at_or_under_a_lowered_dream_entry_still_crosses(lb: Logbook):
    _policy(lb, {"max_tier": 1, "until": "2026-12-31"})
    location = _ids(lb)[1]
    lb.append(**_draft(drafts.UNIT_DAY, DAY, location, 1, f"{DAY}T22:00:00Z"))  # seq 7, tier 1
    ids = _ids(lb)
    sel = _crossed(lb)
    crossed = {str(line["id"]) for line in sel.lines}
    assert ids[7] in crossed and ids[2] not in crossed
    assert sel.counts()["held_back_by_entry"] == 4


def test_a_person_draft_is_still_held_to_the_relationship_entry_alone(lb: Logbook):
    _policy(lb, {"max_tier": 1, "until": "2026-12-31"})
    path = policy.policy_path(lb.root)
    found = json.loads(path.read_text(encoding="utf-8"))
    found["relationship"] = {"max_tier": 2, "until": "2026-06-15"}  # expired
    path.write_text(json.dumps(found), encoding="utf-8")
    sel = _crossed(lb)
    assert _ids(lb)[6] not in {str(line["id"]) for line in sel.lines}
    assert sel.counts()["held_back_by_entry"] == 5, "four drafts under the dream's 1, Ola's under none"


def test_with_the_dream_entry_live_the_bundle_is_byte_for_byte_as_before(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _policy(lb, LIVE)
    sel = _crossed(lb)
    assert [int(line["seq"]) for line in sel.lines] == [1, 2, 3, 4, 5, 6]
    assert "held_back_by_entry" not in sel.counts(), "nothing held: the key is not written"
    now = _bundle(lb, tmp_path / "now")
    # before: a draft of any unit but a person's was the tier's and the signed days' alone
    person = drafts.person_allowed(lb.root)
    monkeypatch.setattr(drafts, "allowed", lambda _root: drafts.Allowed(policy.TIERS[-1], person=person))
    before = _bundle(lb, tmp_path / "before")
    assert now == before
    entries = now[(crossing.ENTRIES_FILE,)].decode("utf-8").splitlines()
    assert [json.loads(line)["seq"] for line in entries] == [1, 2, 3, 4, 5, 6]
    # every line verbatim, as the record holds it: nothing of the bundle was filtered or rewritten
    record = lb.root.joinpath("logbook", "2026", "06.jsonl").read_bytes().splitlines()
    assert now[(crossing.ENTRIES_FILE,)].splitlines() == record
    manifest = json.loads(now[(crossing.MANIFEST_FILE,)])
    assert manifest["counts"] == {
        "logged": 6,
        "crossed": 6,
        "held_back": 0,
        "held_back_unsigned": 0,
        "by_tier": {"1": 1, "2": 5, "3": 0},
        "by_kind": {"draft": 5, "location": 1},
        "resolutions": 0,
        "resolutions_held_back": 0,
        "attachments": {"included": 0, "bytes": 0, "missing": 0},
    }


def test_export_crossing_says_which_entry_held_the_drafts(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _policy(lb, {"max_tier": 1, "until": "2026-12-31"})
    cli.main(
        [
            "export",
            "crossing",
            "--to",
            "circle",
            "--since",
            f"{DAY}T00:00:00Z",
            "--until",
            "2026-06-13T00:00:00Z",
            "--tier",
            "1,2",
            "--unsigned",
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert "4 draft(s) held back: the entry they were written under (the 'dream' entry" in out
    assert "person draft(s)" not in out


def test_a_video_scenes_draft_names_no_entry_and_still_crosses_by_its_tier(lb: Logbook):
    """A scene's draft (`labs/scenes.py`) is written by the rules on this machine from lines that never
    crossed, under no entry: it crosses by its tier like any line, whatever the `dream` entry says."""
    _policy(lb, None)
    location = _ids(lb)[1]
    scene = _draft(drafts.UNIT_EVENT, [f"{location}#t=0.00,40.00"], location, 2, f"{DAY}T22:00:00Z")
    scene["source"] = videos.DRAFT_SOURCE
    lb.append(**scene)  # seq 7
    ids = _ids(lb)
    sel = _crossed(lb)
    crossed = {str(line["id"]) for line in sel.lines}
    assert ids[7] in crossed and ids[5] not in crossed, "the scene's draft crosses; the call's synthesis not"
    assert sel.counts()["held_back_by_entry"] == 4


def test_the_scene_source_agrees_with_the_video_reader():
    assert videos.DRAFT_SOURCE.startswith(drafts.SCENE_SOURCE)
    assert not drafts.under_entry({"kind": drafts.KIND, "source": videos.DRAFT_SOURCE})
    assert drafts.under_entry({"kind": drafts.KIND, "source": "model:local-7b"})
