"""A re-sign keeps your confirmations (RFC 0034 amendment 4, the owner's v1 choice, 18 October
2026): a day signed again without `--confirm` confirms what the standing signature confirmed, still on
the page and not retracted, and a line added to the day since stays unconfirmed until the owner
confirms it. The four ways to sign again read alike: `day sign DAY`, the MCP tool `sign_day`, `day
reflect DAY --sign` and the Day page's "Sign again". `--confirm all` confirms the whole page and
`--confirm none` nothing, as before; a first signature without `--confirm` still confirms the whole
page. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.commands import day as day_command
from logbook.contrib import mcp_server, serve
from logbook.core import policy, store
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-03-03"  # a Tuesday, CET
FIRST_AT = "2026-03-03T19:00:00+01:00"
AGAIN_AT = "2026-03-04T08:00:00+01:00"
REFLECTION = "Good day on the boat."
WAYS = ("day sign", "sign_day", "day reflect --sign", "Sign again")


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
    """3 March 2026 (CET): two locations and two notes on the page; the door allows `sign_day`, and
    its today is the 4th."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: False)
    monkeypatch.setattr(mcp_server, "_today", lambda _lb: "2026-03-04")
    monkeypatch.setattr(policy, "today", lambda: date(2026, 3, 4))
    lb.append_many(
        [
            _location("2026-03-03T06:30:00Z"),  # seq 1
            _note("2026-03-03T07:00:00Z", "Coffee with Ines at the harbour."),  # seq 2
            _note("2026-03-03T09:00:00Z", "Ola Nordmann called about the mooring."),  # seq 3
            _location("2026-03-03T18:00:00Z"),  # seq 4
        ]
    )
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcp": {"max_tier": 1, "write": ["sign_day"]}}), encoding="utf-8")
    return lb


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    assert e.value.code == 2
    return capsys.readouterr().err


def _by_seq(lb: Logbook) -> dict[int, dict[str, Any]]:
    return {int(line["seq"]): line for line in lb.lines()}


def _ids(lb: Logbook) -> dict[int, str]:
    return {seq: str(line["id"]) for seq, line in _by_seq(lb).items()}


def _last(lb: Logbook) -> dict[str, Any]:
    return _by_seq(lb)[int(lb.meta["seq"])]


def _hidden(form: str) -> dict[str, str]:
    return {
        name: html.unescape(value)
        for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form)
    }


def _sign_again(lb: Logbook, way: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """Sign DAY again the `way` named, with no confirmation given; the signature it wrote."""
    if way == "day sign":
        _run(capsys, "day", "sign", DAY, "--at", AGAIN_AT)
    elif way == "sign_day":
        mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": AGAIN_AT})
    elif way == "day reflect --sign":
        _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign")
    else:
        site = serve.Site(lb)
        assert site.write(
            f"/day/{DAY}/reflect", {"text": REFLECTION, "act": "reflect"}, "127.0.0.1", None, None
        )
        page = site.respond(f"/day/{DAY}", "").body.decode("utf-8")
        found = re.search(r'<form class="sign"[^>]*>.*?</form>', page, re.S)
        assert found is not None and "Sign again" in found.group(0)
        form = {k: v for k, v in _hidden(found.group(0)).items() if k != "act"}
        response = site.write(f"/day/{DAY}/sign", {**form, "act": "sign"}, "127.0.0.1", None, None)
        assert response.status == 303, response.body[:300]
    line = _last(lb)
    assert line["kind"] == "signed-day"
    return line


@pytest.mark.parametrize("way", WAYS)
def test_a_re_sign_keeps_the_earlier_confirmations_and_confirms_no_line_added_since(
    lb: Logbook, capsys: pytest.CaptureFixture[str], way: str
):
    _run(capsys, "day", "sign", DAY, "--confirm", "1,2", "--at", FIRST_AT)  # seq 5
    first = _by_seq(lb)[5]
    lb.append(**_note("2026-03-03T12:00:00Z", "A line the owner has not read."))  # seq 6, on the page
    again = _sign_again(lb, way, capsys)
    ids = _ids(lb)
    p = again["payload"]
    assert p["supersedes"] == first["id"]
    assert ids[6] not in p["confirmed"], "a line added since is never confirmed silently"
    assert ids[3] not in p["confirmed"] and ids[4] not in p["confirmed"], "what was left out stays out"
    kept = [ids[1], ids[2]]
    if way in ("day reflect --sign", "Sign again"):  # the reflection, written by the act, joins them
        reflection = next(line for line in lb.lines() if line["payload"].get("text") == REFLECTION)
        kept.append(str(reflection["id"]))
    assert p["confirmed"] == kept
    assert p["page"]["lines"] == 5 + (way in ("day reflect --sign", "Sign again")), "the page as it is now"
    assert lb.verify()[2] == []


@pytest.mark.parametrize("way", WAYS)
def test_the_four_ways_keep_the_same_lines(
    lb: Logbook, capsys: pytest.CaptureFixture[str], way: str, tmp_path: Path
):
    """Whatever the way, the lines of the page kept are the same: the confirmations kept are a rule of
    the signature, not of the door it came through."""
    _run(capsys, "day", "sign", DAY, "--confirm", "2,4", "--at", FIRST_AT)  # seq 5
    again = _sign_again(lb, way, capsys)
    ids = _ids(lb)
    assert [i for i in again["payload"]["confirmed"] if i in (ids[1], ids[2], ids[3], ids[4])] == [
        ids[2],
        ids[4],
    ]


def test_a_first_signature_without_confirm_still_confirms_the_whole_page(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "sign", DAY, "--at", FIRST_AT)
    ids = _ids(lb)
    assert _last(lb)["payload"]["confirmed"] == [ids[1], ids[2], ids[3], ids[4]]


def test_confirm_all_confirms_the_whole_page_on_a_re_sign_and_goes_alone(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "sign", DAY, "--confirm", "1", "--at", FIRST_AT)  # seq 5
    lb.append(**_note("2026-03-03T12:00:00Z", "Read now."))  # seq 6
    _run(capsys, "day", "sign", DAY, "--confirm", "all", "--at", AGAIN_AT)  # seq 7
    ids = _ids(lb)
    assert _by_seq(lb)[7]["payload"]["confirmed"] == [ids[1], ids[2], ids[3], ids[6], ids[4]]
    assert "goes alone" in _refused(capsys, "day", "sign", DAY, "--confirm", "all,2", "--at", AGAIN_AT)
    assert lb.meta["seq"] == 7, "nothing written"
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": "all", "at": AGAIN_AT})["data"]
    assert data["confirmed"] == 5 and _last(lb)["payload"]["confirmed"] == [
        ids[1],
        ids[2],
        ids[3],
        ids[6],
        ids[4],
    ]


def test_confirm_none_still_confirms_nothing_on_a_re_sign(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _run(capsys, "day", "sign", DAY, "--confirm", "1,2", "--at", FIRST_AT)
    _run(capsys, "day", "sign", DAY, "--confirm", "none", "--at", AGAIN_AT)
    assert _last(lb)["payload"]["confirmed"] == []
    mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": "none", "at": AGAIN_AT})
    assert _last(lb)["payload"]["confirmed"] == []


def test_a_re_sign_after_confirming_nothing_keeps_nothing_and_takes_a_disposition(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    """A standing signature that confirmed nothing is kept as nothing: the re-sign confirms nothing
    either, and a disposition given confirms its line, refused by neither (the line is confirmed by
    the disposition, not by `--confirm none`, which was not typed)."""
    _run(capsys, "day", "sign", DAY, "--confirm", "none", "--at", FIRST_AT)  # seq 5
    _run(capsys, "day", "sign", DAY, "--at", AGAIN_AT)  # seq 6
    assert _by_seq(lb)[6]["payload"]["confirmed"] == []
    _run(capsys, "day", "sign", DAY, "--kept", "2", "--at", AGAIN_AT)  # seq 7
    ids = _ids(lb)
    assert _by_seq(lb)[7]["payload"]["confirmed"] == [ids[2]]
    assert _by_seq(lb)[7]["payload"]["dispositions"] == {ids[2]: "kept"}


def test_a_re_sign_adds_the_lines_given_a_disposition_to_what_it_keeps(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "sign", DAY, "--confirm", "1", "--at", FIRST_AT)
    mcp_server.call(lb.root, "sign_day", {"day": DAY, "carried": ["3"], "at": AGAIN_AT})
    ids = _ids(lb)
    assert _last(lb)["payload"]["confirmed"] == [ids[1], ids[3]]


def test_a_kept_line_retracted_since_is_dropped_not_refused(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _run(capsys, "day", "sign", DAY, "--confirm", "1,2", "--at", FIRST_AT)  # seq 5
    lb.retract(2, "the wrong harbour")  # seq 6
    _run(capsys, "day", "sign", DAY, "--at", AGAIN_AT)  # seq 7
    ids = _ids(lb)
    assert _by_seq(lb)[7]["payload"]["confirmed"] == [ids[1]]


def test_day_sign_says_what_it_kept(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _run(capsys, "day", "sign", DAY, "--confirm", "1,2", "--at", FIRST_AT)
    out = _run(capsys, "day", "sign", DAY, "--at", AGAIN_AT)
    assert "2 lines confirmed of 4 on the page" in out
    assert "keeps from the signature it supersedes (#5): 2 lines confirmed" in out


def test_a_re_sign_keeps_the_dispositions_and_the_note_and_what_is_typed_wins(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    """As `day reflect --sign` and "Sign again" keep them (`reflect.signature`): a commitment the
    standing signature said was carried stays carried, a flag typed now replaces it on its line, and
    the note stays unless `--note` is given."""
    _run(
        capsys,
        "day",
        "sign",
        DAY,
        "--confirm",
        "1",
        "--carried",
        "2",
        "--kept",
        "3",
        "--note",
        "Calm.",
        "--at",
        FIRST_AT,
    )
    _run(capsys, "day", "sign", DAY, "--at", AGAIN_AT)  # seq 6
    ids = _ids(lb)
    p = _by_seq(lb)[6]["payload"]
    assert p["confirmed"] == [ids[1], ids[2], ids[3]]
    assert p["dispositions"] == {ids[2]: "carried", ids[3]: "kept"} and p["note"] == "Calm."
    _run(capsys, "day", "sign", DAY, "--kept", "2", "--note", "Done.", "--at", AGAIN_AT)  # seq 7
    p = _by_seq(lb)[7]["payload"]
    assert p["dispositions"] == {ids[2]: "kept", ids[3]: "kept"} and p["note"] == "Done."
    assert p["confirmed"] == [ids[1], ids[2], ids[3]]


def test_a_re_sign_through_the_door_is_byte_for_byte_the_command_s(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "sign", DAY, "--confirm", "1,2", "--kept", "2", "--at", FIRST_AT)
    lb.append(**_note("2026-03-03T12:00:00Z", "A line the owner has not read."))
    twin = Path(shutil.copytree(lb.root, tmp_path / "twin"))
    monkeypatch.setattr(store, "uuid7", lambda: "019ca000-0000-7000-8000-000000000001")
    monkeypatch.setattr(store, "now_utc", lambda: "2026-03-04T08:05:00Z")
    monkeypatch.setenv("LOGBOOK_HOME", str(twin))
    _run(capsys, "day", "sign", DAY, "--at", AGAIN_AT)
    data = mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": AGAIN_AT})["data"]
    month = Path("logbook") / "2026" / "03.jsonl"
    assert (lb.root / month).read_bytes() == (twin / month).read_bytes()
    assert data["kept"] == "keeps from the signature it supersedes (#5): 2 lines confirmed, kept 1"


def test_a_disposition_typed_as_a_seq_with_leading_zeros_replaces_the_one_kept(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    """`--kept 02` names #2 as `signing.sign` reads it, so it replaces the disposition kept on #2 and is
    never refused as given twice."""
    _run(capsys, "day", "sign", DAY, "--confirm", "1", "--carried", "2", "--at", FIRST_AT)
    _run(capsys, "day", "sign", DAY, "--kept", "02", "--at", AGAIN_AT)
    ids = _ids(lb)
    assert _last(lb)["payload"]["dispositions"] == {ids[2]: "kept"}
