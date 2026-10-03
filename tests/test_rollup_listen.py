"""`logbook rollup listen [--year Y | --since DAY --until DAY]`: listens, hours and skips per
year, the top artists by hours, and hours by month from the `listen/v1` lines standing (RFC 0019),
a month without a listen printing an em dash and never a zero. Synthetic Oslo persona; nothing is
appended."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import TZ

from logbook import cli
from logbook.store import Logbook

EM_DASH = "\u2014"
EN_DASH = "\u2013"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["rollup", "listen", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _listen(
    at: str,
    title: str,
    artist: str | None = None,
    played_s: float | None = None,
    skipped: bool | None = None,
    source: str = "spotify",
    show: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "listen/v1",
        "raw_id": f"{source}:{title}:{at}:{played_s}",
        "media": "episode" if show else "track",
        "title": title,
        "service": source,
        **extra,
    }
    if artist:
        payload["artist"] = artist
    if show:
        payload["show"] = show
    if played_s is not None:
        payload["played_s"] = played_s
    if skipped is not None:
        payload["extra"] = {"skipped": skipped}
    return {
        "at": at,
        "end": None,
        "tz": TZ,
        "source": source,
        "kind": "listen",
        "tier": 2,
        "payload": payload,
    }


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """One listen on New Year's Eve 2025 (Oslo), one in January, a corrected one in February, six in
    March — two of them skipped, one a podcast episode, one a Shazam tag with no playhead — and a
    retracted one. The correction stands, the retracted line is out."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    kari, ola = "Kari Nordmann", "Ola Nordmann"
    drafts = [
        _listen("2025-12-31T22:00:00Z", "Old Year", kari, 600, False),  # 23:00 on 31 December in Oslo
        _listen("2026-01-01T00:30:00Z", "Midnight", kari, 360, False),
        _listen("2026-02-10T18:00:00Z", "Clove Hitch", ola, 7200, False),  # too long: corrected below
        _listen("2026-03-04T20:15:30Z", "Fjordsang", kari, 213, False),
        _listen("2026-03-04T20:19:03Z", "Bowline", ola, 30, True),
        _listen("2026-03-04T20:19:34Z", "Bowline", ola, 0, True),
        _listen("2026-03-05T06:10:00Z", "Episode 12: the east berth", None, 1800, False, show="Havnepodden"),
        _listen("2026-03-06T18:00:00Z", "Fjordsang (Live)", kari, 240, False),
        _listen("2026-03-04T20:15:30Z", "Fjordsang", kari, source="shazam"),
        _listen("2026-03-07T10:00:00Z", "Mistake", ola, 3600, False),  # retracted below
    ]
    lb.append_many(drafts)
    with lb.index() as idx:
        wrong = next(line for line in idx.by_kind("listen") if line["payload"]["title"] == "Clove Hitch")
        mistake = next(line for line in idx.by_kind("listen") if line["payload"]["title"] == "Mistake")
    lb.append_many(
        [_listen("2026-02-10T18:00:00Z", "Clove Hitch", ola, 1200, False, supersedes=str(wrong["id"]))]
    )
    lb.retract(int(mistake["seq"]), "not mine")
    return lb


def test_listen_per_year_with_top_artists_and_hours_by_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "--year", "2026")
    assert data["kind"] == "listen"
    assert data["window"]["since"] == "2026-01-01" and data["window"]["until"] == "2026-03-07"
    assert [y["year"] for y in data["years"]] == ["2026"]
    (year,) = data["years"]
    assert year["listens"] == 8 and year["hours"] == 1.1 and year["played_s"] == 3843
    assert year["skipped"] == 2 and year["untimed"] == 1, "the Shazam tag has no playhead"
    assert year["by_service"] == {"spotify": 7, "shazam": 1}
    assert year["episodes"] == {
        "listens": 1,
        "hours": 0.5,
        "played_s": 1800,
        "lines": year["episodes"]["lines"],
    }
    assert len(year["episodes"]["lines"]) == 1
    assert [a["artist"] for a in year["top_artists"]] == [
        "Ola Nordmann",
        "Kari Nordmann",
    ], "by hours, not listens"
    ola, kari = year["top_artists"]
    assert ola == {
        "artist": "Ola Nordmann",
        "listens": 3,
        "hours": 0.3,
        "played_s": 1230,
        "lines": ola["lines"],
    }
    assert len(ola["lines"]) == 3, "the correction, not the line it supersedes; the retracted line is out"
    assert kari == {
        "artist": "Kari Nordmann",
        "listens": 4,
        "hours": 0.2,
        "played_s": 813,
        "lines": kari["lines"],
    }
    assert len(kari["lines"]) == 4
    assert [m["month"] for m in year["months"]] == ["2026-01", "2026-02", "2026-03"]
    january, february, march = year["months"]
    assert january == {
        "month": "2026-01",
        "first": "2026-01-01",
        "last": "2026-01-31",
        "listens": 1,
        "hours": 0.1,
        "played_s": 360,
        "skipped": 0,
        "lines": january["lines"],
    }
    assert february["listens"] == 1 and february["played_s"] == 1200 and len(february["lines"]) == 1
    assert march["listens"] == 6 and march["hours"] == 0.6 and march["skipped"] == 2
    assert march["first"] == "2026-03-01"
    assert march["last"] == "2026-03-07", "the retracted line's day bounds the window, as it does the index"
    assert len(march["lines"]) == 6
    for entry in (*year["top_artists"], *year["months"], year["episodes"]):
        assert all(len(id_) == 36 for id_ in entry["lines"])
    assert lb.meta["head"] == head, "a reader never writes"
    text = _run(capsys, "--year", "2026")
    assert text.startswith(f"listen 2026-01-01 {EN_DASH} 2026-03-07")
    assert (
        "  2026  8 listens · 1.1 h · 2 skipped · 1 without a playhead · 1 episode · spotify 7, shazam 1"
        in text
    )
    assert "top artists" in text and "by month" in text
    lines = text.splitlines()
    assert lines.index("        top artists") < lines.index("        by month")
    assert any(line.startswith("          Ola Nordmann") and "0.3 h · 3 listens" in line for line in lines)
    assert any(line.startswith("          Kari Nordmann") and "0.2 h · 4 listens" in line for line in lines)
    assert "          2026-01  0.1 h · 1 listen" in text
    assert "          2026-03  0.6 h · 6 listens · 2 skipped" in text


def test_the_whole_record_spans_two_years_and_an_empty_month_is_a_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch)
    data = _json(capsys)
    assert data["window"]["since"] == "2025-12-31" and data["window"]["until"] == "2026-03-07"
    assert [y["year"] for y in data["years"]] == ["2025", "2026"]
    old, new = data["years"]
    assert old["listens"] == 1 and old["hours"] == 0.2 and [m["month"] for m in old["months"]] == ["2025-12"]
    assert old["months"][0]["first"] == "2025-12-31" and old["months"][0]["last"] == "2025-12-31"
    assert new["listens"] == 8
    data = _json(capsys, "--since", "2026-04-01", "--until", "2026-06-30")
    assert data["years"] == [] and data["window"]["since"] is None
    text = _run(capsys, "--since", "2026-01-15", "--until", "2026-02-05")
    assert "  2026  0 listens" in text, "a window with days but no listen"
    assert f"          2026-01  {EM_DASH}" in text and f"          2026-02  {EM_DASH}" in text
    assert "top artists" not in text


def test_an_empty_record_and_the_refused_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _run(capsys).splitlines() == ["listen", "  nothing in the window"]
    assert _json(capsys) == {
        "kind": "listen",
        "window": {"since": None, "until": None, "days": []},
        "years": [],
    }
    for flags in (("--by", "week"), ("--with",)):
        with pytest.raises(SystemExit) as e:
            cli.main(["rollup", "listen", *flags])
        assert e.value.code == 2
