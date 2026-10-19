"""Through the door, "all" confirms only what the door can show (RFC 0034 amendment 4, the build
chat's fix of 18 October 2026 after S1's review): the MCP tool `sign_day` with `confirm: "all"`
confirms the page's lines at or under the door's ceiling (the `mcp` entry's `max_tier`) and says how
many lines above it were left unconfirmed, a count and never their content. `day sign --confirm all`
is unchanged: the owner sees the whole page there. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import mcp_server
from logbook.core import policy, store
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-03-01"
SIGNED_AT = "2026-03-02T08:00:00Z"
SECRET = "Ola Nordmann's mooring code is 4711"  # tier 3: never in the door's answer


def _location(at: str, tier: int = 1) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": tier,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"dawarich:{at}"},
    }


def _note(at: str, text: str, tier: int) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": tier,
        "payload": {"schema": "note/v1", "text": text},
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """1 March 2026 (CET): a location, a tier-2 note, a tier-3 note and a location on the page."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(mcp_server, "_today", lambda _lb: "2026-03-02")
    monkeypatch.setattr(policy, "today", lambda: date(2026, 3, 2))
    lb.append_many(
        [
            _location("2026-03-01T07:30:00Z"),  # seq 1
            _note("2026-03-01T10:00:00Z", "Lunch with Ines at the harbour.", 2),  # seq 2
            _note("2026-03-01T12:00:00Z", SECRET, 3),  # seq 3
            _location("2026-03-01T20:00:00Z"),  # seq 4
        ]
    )
    return lb


def _policy(lb: Logbook, max_tier: int) -> None:
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcp": {"max_tier": max_tier, "write": ["sign_day"]}}), encoding="utf-8")


def _ids(lb: Logbook) -> dict[int, str]:
    return {int(line["seq"]): str(line["id"]) for line in lb.lines()}


def _last(lb: Logbook) -> dict[str, Any]:
    return list(lb.lines())[-1]


def test_all_through_the_door_leaves_a_line_above_its_ceiling_unconfirmed(lb: Logbook):
    _policy(lb, 2)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": "all", "at": SIGNED_AT})["data"]
    ids = _ids(lb)
    payload = _last(lb)["payload"]
    assert payload["confirmed"] == [ids[1], ids[2], ids[4]]
    assert payload["page"]["lines"] == 4, "the page signed is still the whole page"
    assert data["confirmed"] == 3 and data["on_page"] == 4
    assert data["above_ceiling"] == 1
    assert data["unconfirmed"] == "1 line above the door's ceiling left unconfirmed"
    said = json.dumps(data, ensure_ascii=False)
    assert SECRET not in said and ids[3] not in said, "a count, never the line"


def test_all_through_the_door_confirms_every_line_when_the_ceiling_is_three(lb: Logbook):
    _policy(lb, 3)
    data = mcp_server.call(
        lb.root, "sign_day", {"day": DAY, "confirm": "all", "at": SIGNED_AT}, allow_tier_3=True
    )["data"]
    ids = _ids(lb)
    assert _last(lb)["payload"]["confirmed"] == [ids[1], ids[2], ids[3], ids[4]]
    assert data["confirmed"] == 4 and data["above_ceiling"] == 0 and data["unconfirmed"] is None


def test_two_lines_above_the_ceiling_are_counted_in_the_plural(lb: Logbook):
    _policy(lb, 1)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": "all", "at": SIGNED_AT})["data"]
    ids = _ids(lb)
    assert _last(lb)["payload"]["confirmed"] == [ids[1], ids[4]]
    assert data["unconfirmed"] == "2 lines above the door's ceiling left unconfirmed"


def test_ids_the_agent_names_and_none_are_as_before(lb: Logbook):
    _policy(lb, 2)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": ["1"], "at": SIGNED_AT})["data"]
    assert _last(lb)["payload"]["confirmed"] == [_ids(lb)[1]]
    assert data["above_ceiling"] == 0 and data["unconfirmed"] is None


def test_day_sign_confirm_all_still_confirms_the_whole_page(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _policy(lb, 1)
    cli.main(["day", "sign", DAY, "--confirm", "all", "--at", SIGNED_AT])
    capsys.readouterr()
    ids = _ids(lb)
    assert _last(lb)["payload"]["confirmed"] == [ids[1], ids[2], ids[3], ids[4]]


def test_all_through_the_door_writes_what_day_sign_writes_for_the_ids_it_confirmed(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _policy(lb, 2)
    twin = Path(shutil.copytree(lb.root, tmp_path / "twin"))
    monkeypatch.setattr(store, "uuid7", lambda: "019ca000-0000-7000-8000-000000000001")
    monkeypatch.setattr(store, "now_utc", lambda: "2026-03-02T08:05:00Z")
    monkeypatch.setenv("LOGBOOK_HOME", str(twin))
    cli.main(["day", "sign", DAY, "--confirm", "1,2,4", "--at", SIGNED_AT])
    capsys.readouterr()
    mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": "all", "at": SIGNED_AT})
    month = ("logbook", "2026", "03.jsonl")
    assert lb.root.joinpath(*month).read_bytes() == twin.joinpath(*month).read_bytes()


# The door never confirms what it cannot show, on a first signature too (the owner's answer to #332's
# open question, 19 October 2026): `sign_day` with no `confirm`, on a day not yet signed, confirms the
# page's lines at or under the door's ceiling, as `"all"` does, and counts the rest.


def test_a_first_signature_through_the_door_leaves_a_line_above_its_ceiling_unconfirmed(lb: Logbook):
    _policy(lb, 2)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": SIGNED_AT})["data"]
    ids = _ids(lb)
    payload = _last(lb)["payload"]
    assert payload["confirmed"] == [ids[1], ids[2], ids[4]]
    assert payload["page"]["lines"] == 4 and "supersedes" not in payload
    assert data["confirmed"] == 3 and data["on_page"] == 4 and data["kept"] is None
    assert data["above_ceiling"] == 1
    assert data["unconfirmed"] == "1 line above the door's ceiling left unconfirmed"
    said = json.dumps(data, ensure_ascii=False)
    assert SECRET not in said and ids[3] not in said, "a count, never the line"


def test_a_first_signature_through_the_door_confirms_every_line_when_the_ceiling_is_three(lb: Logbook):
    _policy(lb, 3)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": SIGNED_AT}, allow_tier_3=True)["data"]
    ids = _ids(lb)
    assert _last(lb)["payload"]["confirmed"] == [ids[1], ids[2], ids[3], ids[4]]
    assert data["confirmed"] == 4 and data["above_ceiling"] == 0 and data["unconfirmed"] is None


def test_a_first_signature_with_a_disposition_still_leaves_the_line_above_unconfirmed(lb: Logbook):
    _policy(lb, 2)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "kept": ["2"], "at": SIGNED_AT})["data"]
    ids = _ids(lb)
    payload = _last(lb)["payload"]
    assert payload["confirmed"] == [ids[1], ids[2], ids[4]]
    assert payload["dispositions"] == {ids[2]: "kept"}
    assert data["above_ceiling"] == 1


def test_a_first_signature_through_the_door_writes_what_day_sign_writes_for_the_ids_it_confirmed(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _policy(lb, 2)
    twin = Path(shutil.copytree(lb.root, tmp_path / "twin"))
    monkeypatch.setattr(store, "uuid7", lambda: "019ca000-0000-7000-8000-000000000002")
    monkeypatch.setattr(store, "now_utc", lambda: "2026-03-02T08:05:00Z")
    monkeypatch.setenv("LOGBOOK_HOME", str(twin))
    cli.main(["day", "sign", DAY, "--confirm", "1,2,4", "--at", SIGNED_AT])
    capsys.readouterr()
    mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": SIGNED_AT})
    month = ("logbook", "2026", "03.jsonl")
    assert lb.root.joinpath(*month).read_bytes() == twin.joinpath(*month).read_bytes()


def test_day_sign_without_confirm_still_confirms_the_whole_page(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _policy(lb, 1)
    cli.main(["day", "sign", DAY, "--at", SIGNED_AT])
    capsys.readouterr()
    ids = _ids(lb)
    assert _last(lb)["payload"]["confirmed"] == [ids[1], ids[2], ids[3], ids[4]]


def test_a_re_sign_through_the_door_without_confirm_keeps_what_the_owner_confirmed(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _policy(lb, 2)
    cli.main(["day", "sign", DAY, "--at", SIGNED_AT])  # the owner, who saw the whole page
    capsys.readouterr()
    ids = _ids(lb)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": "2026-03-02T09:00:00Z"})["data"]
    payload = _last(lb)["payload"]
    assert payload["confirmed"] == [ids[1], ids[2], ids[3], ids[4]], "kept, as RFC 0034 amendment 4 says"
    assert payload["supersedes"] == ids[5]
    assert data["above_ceiling"] == 0 and data["unconfirmed"] is None


def test_a_bare_first_signature_under_a_ceiling_over_the_whole_page_writes_what_bare_day_sign_writes(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _policy(lb, 3)
    twin = Path(shutil.copytree(lb.root, tmp_path / "twin"))
    monkeypatch.setattr(store, "uuid7", lambda: "019ca000-0000-7000-8000-000000000003")
    monkeypatch.setattr(store, "now_utc", lambda: "2026-03-02T08:05:00Z")
    monkeypatch.setenv("LOGBOOK_HOME", str(twin))
    cli.main(["day", "sign", DAY, "--at", SIGNED_AT])
    capsys.readouterr()
    mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": SIGNED_AT}, allow_tier_3=True)
    month = ("logbook", "2026", "03.jsonl")
    assert lb.root.joinpath(*month).read_bytes() == twin.joinpath(*month).read_bytes()
