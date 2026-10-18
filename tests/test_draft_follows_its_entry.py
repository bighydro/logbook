"""A draft is held to the entry it was written under (RFC 0036 amendment 1; the wave-1 review's fix of
18 October 2026): a person draft (`dream person`, unit `person`) to the `relationship` entry, every
other unit (day, journey, week, event) to the `dream` entry. Every reader of drafts holds it so: the
door (`logbook serve mcp`), the crossing package and `doctor`, through `drafts.allowed`. A day draft
reads byte for byte as before whatever the `relationship` entry says. Synthetic Oslo persona: Ines
and Ola Nordmann, who do not exist."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook.contrib import doctor, mcp_server
from logbook.contrib.relationship import reader
from logbook.core import crossing, drafts, policy
from logbook.core import day as day_reader
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-06-12"
OLA = "ent-ola-nordmann"  # the person draft's subject, a canonical person's entity id
DAY_TEXT = "A day at the marina."
PERSON_TEXT = "June with Ola was the boat."


def _location(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"dawarich:{at}"},
    }


def _draft(unit: str, subject: str, text: str, evidence: str, entry: str, tier: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA,
        "unit": unit,
        "subject": subject,
        "read_head": "0" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": text, "evidence": [evidence]}],
        "extra": {"prompt": "test/1", "parts": [unit], "policy_version": "0" * 64, "entry": entry},
    }
    if unit == drafts.UNIT_PERSON:
        payload[drafts.WINDOW] = {"from": "2026-06-01", "to": DAY}
    assert drafts.validate(payload) == []
    return {
        "at": f"{DAY}T21:00:00Z",
        "source": "model:local-7b",
        "kind": "draft",
        "tier": tier,
        "payload": payload,
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """12 June 2026: one location, the day's draft and Ola's person draft, both at tier 2."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    lb.append(**_location(f"{DAY}T08:00:00Z"))  # seq 1
    location = str(next(iter(lb.lines()))["id"])
    lb.append(**_draft("day", DAY, DAY_TEXT, location, "dream", 2))  # seq 2
    lb.append(**_draft("person", OLA, PERSON_TEXT, location, "relationship", 2))  # seq 3
    return lb


def _policy(lb: Logbook, relationship: dict[str, Any] | None, dream: int = 2, mcp: int = 2) -> None:
    found: dict[str, Any] = {
        "dream": {"max_tier": dream, "until": "2026-12-31"},
        "mcp": {"max_tier": mcp},
        "circle": {"max_tier": 3},
    }
    if relationship is not None:
        found["relationship"] = relationship
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found), encoding="utf-8")


LIVE = {"max_tier": 2, "until": "2026-12-31"}
EXPIRED = {"max_tier": 2, "until": "2026-06-15"}  # today is the 20th


def _ids(lb: Logbook) -> dict[int, str]:
    return {int(line["seq"]): str(line["id"]) for line in lb.lines()}


def _door(lb: Logbook, name: str, **arguments: Any) -> dict[str, Any]:
    return mcp_server.call(lb.root, name, arguments, allow_tier_3=True)


def _door_drafts(lb: Logbook) -> list[str]:
    rows = _door(lb, "day_lines", day=DAY)["data"]["lines"]
    return [r["id"] for r in rows if r["kind"] == drafts.KIND]


def _crossed(lb: Logbook) -> crossing.Selection:
    req = crossing.request(
        lb, "circle", f"{DAY}T00:00:00Z", "2026-06-13T00:00:00Z", (1, 2, 3), signed_only=False
    )
    return crossing.select(lb, req)


def _disk(_path: Path) -> tuple[int, int, int]:
    return (300 * doctor.GIB, 100 * doctor.GIB, 200 * doctor.GIB)


def _drafts_check(lb: Logbook) -> doctor.Check | None:
    return {c.name: c for c in doctor.run(lb, {}, installed=lambda _m: True, usage=_disk)}.get("drafts")


def test_the_entry_names_agree_with_the_relationship_reader():
    assert drafts.PERSON_ENTRY == reader.ENTRY


def test_a_person_draft_whose_relationship_entry_expired_is_withheld_while_the_day_draft_shows(lb: Logbook):
    _policy(lb, LIVE)
    ids = _ids(lb)
    assert _door_drafts(lb) == [ids[2], ids[3]]
    assert {str(line["id"]) for line in _crossed(lb).lines} >= {ids[2], ids[3]}

    _policy(lb, EXPIRED)
    # the door: the day's draft still shows, the person's is held back and counted, never served
    out = _door(lb, "day_lines", day=DAY)
    assert [r["id"] for r in out["data"]["lines"] if r["kind"] == drafts.KIND] == [ids[2]]
    assert out["data"]["above_ceiling"] == 1 and PERSON_TEXT not in json.dumps(out)
    with pytest.raises(mcp_server.ToolError, match="'relationship' entry"):
        _door(lb, "line", id=ids[3])
    assert _door(lb, "line", id=ids[2])["data"]["id"] == ids[2]
    assert PERSON_TEXT not in json.dumps(_door(lb, "search", text="boat"))
    # the crossing: it stays home and is counted
    sel = _crossed(lb)
    crossed = {str(line["id"]) for line in sel.lines}
    assert ids[2] in crossed and ids[3] not in crossed
    assert sel.counts()["held_back_by_entry"] == 1
    # doctor names it, and why
    check = _drafts_check(lb)
    assert check is not None and check.status == "warn"
    assert f"{OLA} (#3, tier 2)" in check.detail and "expired on 2026-06-15" in check.detail
    assert DAY not in check.detail, "the day's draft is not above the dream entry"
    assert drafts.allowed(lb.root).allows(next(line for line in lb.lines() if line["seq"] == 2))


@pytest.mark.parametrize("relationship", [None, {"max_tier": 2}], ids=["no entry", "no until"])
def test_a_person_draft_without_a_lend_to_the_reader_is_withheld(lb: Logbook, relationship: Any):
    _policy(lb, relationship)
    assert _door_drafts(lb) == [_ids(lb)[2]]
    check = _drafts_check(lb)
    assert check is not None and f"{OLA} (#3, tier 2)" in check.detail


def test_a_person_draft_is_held_to_the_relationship_ceiling_not_the_dreams(lb: Logbook):
    _policy(lb, {"max_tier": 1, "until": "2026-12-31"}, dream=3, mcp=3)
    ids = _ids(lb)
    location = ids[1]
    lb.append(**_draft("person", "ent-ines", "Ines sailed too.", location, "relationship", 1))  # seq 4
    ids = _ids(lb)
    assert _door_drafts(lb) == [ids[2], ids[4]], "the tier-1 person draft shows; the tier-2 one is held to 1"
    with pytest.raises(mcp_server.ToolError, match="above max_tier 1 of the 'relationship' entry"):
        _door(lb, "line", id=ids[3])
    allowed = drafts.allowed(lb.root)
    lines = {int(line["seq"]): line for line in lb.lines()}
    assert allowed.allows(lines[2]) and not allowed.allows(lines[3]) and allowed.allows(lines[4])
    row = drafts.withheld_json(lines[3], allowed)
    assert row["max_tier"] == 1 and "'relationship' entry" in row["why"] and "dream person" in row["why"]
    sel = _crossed(lb)
    assert {str(line["id"]) for line in sel.lines} >= {ids[2], ids[4]} and ids[3] not in {
        str(line["id"]) for line in sel.lines
    }
    check = _drafts_check(lb)
    assert check is not None and f"{OLA} (#3, tier 2)" in check.detail and "max_tier 1" in check.detail
    assert "ent-ines" not in check.detail


def test_a_person_draft_the_dream_entry_would_withhold_is_shown_under_its_own(lb: Logbook):
    _policy(lb, LIVE, dream=1)
    ids = _ids(lb)
    assert _door_drafts(lb) == [ids[3]], (
        "the day's draft is above the dream's 1, Ola's under the relationship's 2"
    )
    assert _door(lb, "line", id=ids[3])["data"]["id"] == ids[3]
    with pytest.raises(mcp_server.ToolError, match="above max_tier 1 of the 'dream' entry"):
        _door(lb, "line", id=ids[2])


def _day_outputs(lb: Logbook) -> list[str]:
    """Everything a reader says of the day's draft: the Day's draft block (or its withheld row), the
    door's, the door's line, the crossing's copy and doctor's sentence about days."""
    check = _drafts_check(lb)
    sel = _crossed(lb)
    door = _door(lb, "day", date=DAY)["data"]
    days = [part for part in ("" if check is None else check.detail).split(" · ") if "day(s)" in part]
    return [
        json.dumps(
            {k: v for k, v in day_reader.read(lb, DAY).items() if k.startswith("draft")}, sort_keys=True
        ),
        json.dumps({k: v for k, v in door.items() if k.startswith("draft")}, sort_keys=True),
        json.dumps(_door(lb, "line", id=_ids(lb)[2])["data"], sort_keys=True),
        json.dumps([line for line in sel.lines if line["seq"] == 2], sort_keys=True),
        *days,
    ]


@pytest.mark.parametrize("dream", [1, 2, 3])
def test_a_day_draft_reads_byte_for_byte_alike_whatever_the_relationship_entry_says(lb: Logbook, dream: int):
    _policy(lb, None, dream=dream, mcp=3)
    before = _day_outputs(lb) if dream > 1 else None
    for relationship in (LIVE, EXPIRED, {"max_tier": 1, "until": "2026-12-31"}, {"max_tier": 2}):
        _policy(lb, relationship, dream=dream, mcp=3)
        if before is None:  # above the dream's ceiling: withheld alike, with the same row and words
            with pytest.raises(mcp_server.ToolError, match="'dream' entry"):
                _door(lb, "line", id=_ids(lb)[2])
            assert day_reader.read(lb, DAY)["draft_withheld"]["max_tier"] == 1
            continue
        assert _day_outputs(lb) == before, relationship


def test_the_door_names_the_relationship_entry_when_both_entries_withhold_a_person_draft(lb: Logbook):
    _policy(lb, {"max_tier": 1, "until": "2026-12-31"}, dream=1, mcp=3)  # equal ceilings: nothing sorted
    ids = _ids(lb)
    with pytest.raises(mcp_server.ToolError, match="above max_tier 1 of the 'relationship' entry"):
        _door(lb, "line", id=ids[3])
    with pytest.raises(mcp_server.ToolError, match="above max_tier 1 of the 'dream' entry"):
        _door(lb, "line", id=ids[2])
    assert _door_drafts(lb) == []
