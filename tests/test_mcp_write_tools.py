"""`logbook serve mcp`, the two write tools the owner allows by name (ADR 0022): `sign_day` signs a
day through the same `signing.sign` as `logbook day sign`, and `note_day` appends one `note/v1` line
to a day. Neither is allowed unless the `mcp` entry of `policy/crossing.json` lists it under
`write`; both take the writer lock without waiting, refuse a day outside the write window, and log
counts, never text. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import mcp_server
from logbook.core import policy, signing, store
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-03-01"
TODAY = "2026-03-02"
SIGNED_AT = "2026-03-02T08:00:00Z"  # 09:00 on the 2nd, Oslo
NAME = "Nordmann"  # the persona's family name: in what is written, never in a log line


def _location(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"dawarich:{at}"},
    }


def _note(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """2026-03-01 (CET): two locations and a promise on the page; today is the 2nd."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(mcp_server, "_today", lambda _lb: TODAY)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 3, 2))
    lb.append_many(
        [
            _location("2026-03-01T07:30:00Z"),  # seq 1
            _note("2026-03-01T10:00:00Z", f"I'll send Ola {NAME} the mooring photos by Friday"),  # seq 2
            _location("2026-03-01T20:00:00Z"),  # seq 3
        ]
    )
    return lb


def _policy(lb: Logbook, **entry: Any) -> None:
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1, **entry}}), encoding="utf-8"
    )


BOTH = ["sign_day", "note_day"]


def _call(lb: Logbook, name: str, **arguments: Any) -> dict[str, Any]:
    return mcp_server.call(lb.root, name, arguments)["data"]


def _refused(lb: Logbook, name: str, **arguments: Any) -> str:
    with pytest.raises(ValueError) as e:  # a ToolError, or a SignError the host is shown as one
        mcp_server.call(lb.root, name, arguments)
    return str(e.value)


def _by_seq(lb: Logbook) -> dict[int, dict[str, Any]]:
    return {int(line["seq"]): line for line in lb.lines()}


# -- the policy: allowed by name, or not at all ------------------------------------------------------------


@pytest.mark.parametrize("entry", [{}, {"write": []}, {"write": ["note_day"]}])
def test_sign_day_is_refused_unless_the_policy_names_it(lb: Logbook, entry: dict[str, Any]):
    _policy(lb, **entry)
    said = _refused(lb, "sign_day", day=DAY)
    assert "sign_day" in said and "write" in said and "crossing.json" in said
    assert said.count(". ") == 0, "one plain sentence"
    assert lb.meta["seq"] == 3


@pytest.mark.parametrize("entry", [{}, {"write": ["sign_day"]}])
def test_note_day_is_refused_unless_the_policy_names_it(lb: Logbook, entry: dict[str, Any]):
    _policy(lb, **entry)
    assert "note_day" in _refused(lb, "note_day", day=DAY, text="Grilled.")
    assert lb.meta["seq"] == 3


def test_a_record_without_a_policy_file_allows_no_write_tool(lb: Logbook):
    policy.policy_path(lb.root).unlink(missing_ok=True)
    _refused(lb, "sign_day", day=DAY)
    _refused(lb, "note_day", day=DAY, text="Grilled.")
    assert lb.meta["seq"] == 3


def test_an_expired_entry_allows_no_write_tool(lb: Logbook):
    _policy(lb, write=BOTH, until="2026-03-01")
    said = _refused(lb, "sign_day", day=DAY)
    assert "expired on 2026-03-01" in said
    _refused(lb, "note_day", day=DAY, text="Grilled.")
    assert lb.meta["seq"] == 3


def test_allow_tier_3_has_no_effect_on_writes(lb: Logbook):
    path = policy.policy_path(lb.root)
    path.write_text(json.dumps({"mcp": {"max_tier": 3}}), encoding="utf-8")
    with pytest.raises(mcp_server.ToolError):
        mcp_server.call(lb.root, "sign_day", {"day": DAY}, allow_tier_3=True)
    _policy(lb, write=BOTH)
    written = mcp_server.call(lb.root, "note_day", {"day": DAY, "text": "Grilled."}, allow_tier_3=True)
    assert written["data"]["tier"] == 2


def test_a_write_that_names_an_unknown_tool_is_a_policy_error_naming_the_file(lb: Logbook):
    _policy(lb, write=["sign_day", "add_note"])
    assert "crossing.json" in _refused(lb, "sign_day", day=DAY)
    _policy(lb, write=BOTH, write_window_days="sixty")
    assert "write_window_days" in _refused(lb, "note_day", day=DAY, text="Grilled.")


# -- sign_day: day sign's semantics, through the same code ------------------------------------------------


def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The id and `recorded_at` of the next line, fixed, so two writers' lines can be compared."""
    monkeypatch.setattr(store, "uuid7", lambda: "019ca000-0000-7000-8000-000000000001")
    monkeypatch.setattr(store, "now_utc", lambda: "2026-03-02T08:05:00Z")


def _appended(root: Path) -> bytes:
    return (root / "logbook" / "2026" / "03.jsonl").read_bytes().splitlines()[-1]


@pytest.mark.parametrize(
    ("flags", "arguments"),
    [
        # a first signature without `confirm` through the door confirms the lines at or under its ceiling
        # (19 October 2026): #2 is tier 2, above the mcp entry's 1, so `day sign` names the other two
        (["--confirm", "1,3"], {}),
        (
            ["--confirm", "1,3", "--note", "A quiet Sunday."],
            {"confirm": ["1", "3"], "note": "A quiet Sunday."},
        ),
        (["--confirm", "none"], {"confirm": "none"}),
        (["--kept", "2", "--carried", "3"], {"kept": ["2"], "carried": ["3"]}),
        (["--missed", "2", "--dropped", "1"], {"missed": ["2"], "dropped": ["1"]}),
    ],
)
def test_sign_day_writes_byte_for_byte_what_day_sign_writes(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    arguments: dict[str, Any],
):
    _policy(lb, write=BOTH)
    twin = Path(shutil.copytree(lb.root, tmp_path / "twin"))
    _fixed_clock(monkeypatch)
    monkeypatch.setenv("LOGBOOK_HOME", str(twin))
    cli.main(["day", "sign", DAY, "--at", SIGNED_AT, *flags])
    header = capsys.readouterr().out.splitlines()[0]
    data = _call(lb, "sign_day", day=DAY, at=SIGNED_AT, **arguments)
    assert _appended(lb.root) == _appended(twin)
    assert (lb.root / "logbook.json").read_bytes() == (twin / "logbook.json").read_bytes()
    assert data["id"] == "019ca000-0000-7000-8000-000000000001"
    assert data["header"] == header
    assert data["kind"] == "signed-day" and data["tier"] == 1
    assert lb.verify()[2] == []


def test_sign_day_carries_dispositions_into_the_signature(lb: Logbook):
    _policy(lb, write=BOTH)
    ids = {seq: line["id"] for seq, line in _by_seq(lb).items()}
    data = _call(lb, "sign_day", day=DAY, at=SIGNED_AT, confirm=["1"], kept=[ids[2]], carried=["3"])
    p = _by_seq(lb)[4]["payload"]
    assert p["dispositions"] == {ids[2]: "kept", ids[3]: "carried"}
    assert p["confirmed"] == [ids[1], ids[2], ids[3]]
    assert data["confirmed"] == 3 and data["dispositions"] == {"kept": 1, "carried": 1}


def test_re_signing_through_the_door_supersedes(lb: Logbook):
    _policy(lb, write=BOTH)
    first = _call(lb, "sign_day", day=DAY, at=SIGNED_AT)
    second = _call(lb, "sign_day", day=DAY, at="2026-03-02T09:00:00Z", confirm="none")
    assert _by_seq(lb)[5]["payload"]["supersedes"] == first["id"]
    assert second["supersedes"] == first["id"]
    assert signing.summary(_by_seq(lb)[5])[0] == second["header"]


@pytest.mark.parametrize(
    ("arguments", "said"),
    [
        ({"confirm": ["9"]}, "is not a line on the page"),
        ({"confirm": ["none", "1"]}, "goes alone"),
        ({"confirm": "none", "kept": ["2"]}, "goes alone"),
        ({"kept": ["2"], "missed": ["2"]}, "given twice"),
        ({"at": "2026-02-28T12:00:00Z"}, "before 2026-03-01 starts"),
        ({"at": "tomorrow"}, "not an RFC 3339 moment"),
        ({"note": "two\nlines"}, "one line"),
    ],
)
def test_sign_day_refuses_what_day_sign_refuses(lb: Logbook, arguments: dict[str, Any], said: str):
    _policy(lb, write=BOTH)
    assert said in _refused(lb, "sign_day", day=DAY, **arguments)
    assert lb.meta["seq"] == 3


# -- note_day ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", mcp_server.NOTE_KINDS)
def test_note_day_writes_one_note_and_returns_its_id(lb: Logbook, kind: str):
    _policy(lb, write=BOTH)
    text = f"  Sail with Ola {NAME} on Sunday — maybe.  "
    data = _call(lb, "note_day", day=DAY, text=text, at="2026-03-01T21:00:00+01:00", kind=kind)
    line = _by_seq(lb)[4]
    assert data["id"] == line["id"] and data["seq"] == 4
    assert (line["kind"], line["tier"], line["source"]) == ("note", 2, "mcp")
    assert line["at"] == "2026-03-01T20:00:00Z"
    assert line["payload"] == {"schema": "note/v1", "text": text, "labels": [kind]}, "verbatim, unfiltered"
    assert data["readable"] is False, "a tier-2 note at a ceiling of 1"
    assert lb.verify()[2] == []


def test_note_day_without_at_lands_on_the_day(lb: Logbook):
    _policy(lb, write=BOTH)
    _call(lb, "note_day", day=DAY, text="Grilled.")
    with lb.index() as idx:
        assert [line["kind"] for line in idx.day(DAY)].count("note") == 2


def test_note_day_refuses_an_at_off_the_day_an_unknown_kind_and_an_empty_or_long_text(lb: Logbook):
    _policy(lb, write=BOTH)
    assert "not on 2026-03-01" in _refused(lb, "note_day", day=DAY, text="x", at="2026-03-02T08:00:00Z")
    assert "proposal" in _refused(lb, "note_day", day=DAY, text="x", kind="decision")
    assert "empty" in _refused(lb, "note_day", day=DAY, text="   ")
    long = "x" * (mcp_server.NOTE_MAX + 1)
    said = _refused(lb, "note_day", day=DAY, text=long)
    assert str(mcp_server.NOTE_MAX) in said and "x" * 20 not in said
    _call(lb, "note_day", day=DAY, text="x" * mcp_server.NOTE_MAX)
    assert lb.meta["seq"] == 4


# -- the window -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", BOTH)
def test_a_day_outside_the_window_is_refused(lb: Logbook, name: str):
    _policy(lb, write=BOTH)
    extra = {"text": "x"} if name == "note_day" else {}
    assert "write window" in _refused(lb, name, day="2025-12-31", **extra)  # 61 days before today
    assert "write window" in _refused(lb, name, day="2026-03-03", **extra)  # tomorrow
    _policy(lb, write=BOTH, write_window_days=0)
    assert "write window" in _refused(lb, name, day=DAY, **extra)
    _policy(lb, write=BOTH, write_window_days=400)
    lb.append(**_location("2025-12-31T12:00:00Z"))
    _call(lb, name, day="2025-12-31", **extra)


def test_the_window_holds_sixty_days_back_by_default(lb: Logbook):
    _policy(lb, write=BOTH)
    _call(lb, "note_day", day="2026-01-01", text="x")  # 60 days before today


# -- the lock ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", BOTH)
def test_another_writer_is_refused_plainly_without_waiting(lb: Logbook, name: str):
    _policy(lb, write=BOTH)
    path = lb.root / "state" / "writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = {"pid": os.getppid(), "command": "logbook sync", "since": "2026-03-02T08:00:00Z"}
    path.write_text(json.dumps(holder), encoding="utf-8")
    extra = {"text": "x"} if name == "note_day" else {}
    said = _refused(lb, name, day=DAY, **extra)
    assert "another logbook command is writing to this record (logbook sync" in said
    assert lb.meta["seq"] == 3
    assert json.loads(path.read_text(encoding="utf-8")) == holder, "the other writer's lock is left"


def test_a_head_that_moves_while_the_page_is_read_is_refused(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    _policy(lb, write=BOTH)
    read = signing.page

    def page_then_append(*args: Any, **kwargs: Any) -> Any:
        found = read(*args, **kwargs)
        Logbook(lb.root).append(**_location("2026-03-01T21:00:00Z"))  # a writer inside this process's hold
        return found

    monkeypatch.setattr(signing, "page", page_then_append)
    said = _refused(lb, "sign_day", day=DAY, at=SIGNED_AT)
    assert "head moved" in said and "nothing was signed" in said
    assert [line["kind"] for line in lb.lines()].count("signed-day") == 0


# -- the log: counts, never text --------------------------------------------------------------------------


def test_the_log_carries_counts_and_never_text(lb: Logbook, caplog: pytest.LogCaptureFixture):
    _policy(lb, write=BOTH)
    caplog.set_level(logging.INFO, logger="logbook.mcp")
    _call(lb, "note_day", day=DAY, text=f"Ola {NAME} is coming aboard.", kind="proposal")
    _call(lb, "sign_day", day=DAY, at=SIGNED_AT, note=f"With Ines {NAME}.", kept=["2"])
    _refused(lb, "note_day", day=DAY, text=f"Ola {NAME} " * 1000)
    _refused(lb, "sign_day", day=DAY, confirm=[f"Ines {NAME}"])
    _policy(lb)
    _refused(lb, "note_day", day=DAY, text=f"Ola {NAME}")
    lines = [r.getMessage() for r in caplog.records if r.name == "logbook.mcp"]
    assert len(lines) == 5
    assert NAME not in caplog.text and "Ines" not in caplog.text and "aboard" not in caplog.text
    assert lines[0].startswith("note_day day=2026-03-01 kind=proposal") and "chars=" in lines[0]
    assert lines[1].startswith("sign_day day=2026-03-01")
    # the note written above is on the page, at tier 2 above the door's ceiling of 1: a first signature
    # through the door leaves it unconfirmed, and #2, above it too, is confirmed by its disposition
    assert "confirmed=3 on_page=4 above_ceiling=1" in lines[1], "the note written above is on the page"


# -- what the host sees -----------------------------------------------------------------------------------


def test_inspect_lists_the_write_tools(capsys: pytest.CaptureFixture[str]):
    cli.main(["serve", "mcp", "--inspect"])
    out = capsys.readouterr().out
    for name in BOTH:
        assert f"\n{name}(" in out
    assert 'write tools, allowed by name in the mcp entry\'s "write": sign_day, note_day' in out


def test_doctor_shows_the_write_tools_on_the_crossing_line(lb: Logbook):
    from logbook.contrib import doctor

    _policy(lb, write=BOTH)
    assert "mcp 1 write sign_day,note_day" in doctor.crossing_check(lb.root).detail
    _policy(lb, write=BOTH, until="2026-03-01")
    assert "write" not in doctor.crossing_check(lb.root).detail.split(";")[0]
    _policy(lb)
    assert "write" not in doctor.crossing_check(lb.root).detail
