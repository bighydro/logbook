"""`day_start` (RFC 0036): where the owner's day begins, set once in `logbook.json` and applied by every
reader that puts a line on a day — the index's `day_local`, the Day and its nights, the signed day's page,
`days`, the trips, the gaps, the digest and the pages `serve` keeps, `/today` included. A line's `at`,
hash and month file never move; a reader that cannot parse the value refuses and names it.

The record is the Oslo persona's, who does not exist: on the 13th of October 2026 (CEST, UTC+2) one line
at 01:30 local and one at 07:00. With the day beginning at 06:00 the first is the 12th's and the second
the 13th's; at midnight both are the 13th's."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from logbook import cli
from logbook.core import day_start, index
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OSLO = ZoneInfo(TZ)
EARLY = "2026-10-12T23:30:00Z"  # 01:30 on the 13th, local
MORNING = "2026-10-13T05:00:00Z"  # 07:00 on the 13th, local


def _note(lb: Logbook, at: str, text: str) -> str:
    line = lb.append(at=at, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": text})
    return str(line["id"])


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    _note(lb, EARLY, "back from the late concert")
    _note(lb, MORNING, "coffee on the balcony")
    return lb


def _texts(lines: list[dict[str, object]]) -> list[str]:
    return [str(line["payload"]["text"]) for line in lines]  # type: ignore[index]


# -- the rule ------------------------------------------------------------------------------------------------


def test_a_line_before_the_boundary_belongs_to_the_date_before() -> None:
    six = day_start.DayStart(OSLO, time(6, 0))
    assert six.day_of(EARLY) == "2026-10-12"
    assert six.day_of(MORNING) == "2026-10-13"
    assert six.day_of("2026-10-13T04:00:00Z") == "2026-10-13", "06:00 itself begins the day"
    assert six.day_of("2026-10-13T03:59:59Z") == "2026-10-12"
    assert six.day_of("2026-10-13T21:30:00Z") == "2026-10-13", "23:30 is the day's as it always was"
    midnight = day_start.DayStart(OSLO)
    assert midnight.day_of(EARLY) == midnight.day_of(MORNING) == "2026-10-13"


def test_a_change_of_offset_in_the_night_moves_no_line() -> None:
    """Summer time ends in Oslo at 03:00 on 25 October 2026 (01:00Z): the clock goes back an hour. The
    day is what the wall clock said: 05:30 on the 25th is still the 24th's, 06:00 begins the 25th, and
    the 24th lasts twenty-five hours."""
    six = day_start.DayStart(OSLO, time(6, 0))
    assert six.day_of("2026-10-25T04:30:00Z") == "2026-10-24"  # 05:30 CET
    assert six.day_of("2026-10-25T05:00:00Z") == "2026-10-25"  # 06:00 CET
    assert six.day_of("2026-10-25T00:30:00Z") == "2026-10-24"  # 02:30 CEST, the first of two 02:30s
    assert six.day_of("2026-10-25T01:30:00Z") == "2026-10-24"  # 02:30 CET, the second
    start, end = six.span("2026-10-24")
    assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == 25 * 3600
    assert start.astimezone(UTC) == datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    assert end.astimezone(UTC) == datetime(2026, 10, 25, 5, 0, tzinfo=UTC)


def test_today_is_the_day_the_owner_is_in() -> None:
    six = day_start.DayStart(OSLO, time(6, 0))
    assert six.today(datetime(2026, 10, 13, 3, 59, tzinfo=UTC)) == date(2026, 10, 12)  # 05:59 local
    assert six.today(datetime(2026, 10, 13, 4, 1, tzinfo=UTC)) == date(2026, 10, 13)  # 06:01 local


@pytest.mark.parametrize("value", ["6:00", "24:00", "06:60", "06:00:00", "", "morning", 6, ["06:00"]])
def test_a_value_that_is_not_a_clock_is_refused_naming_the_key_and_the_value(value: object) -> None:
    with pytest.raises(day_start.DayStartError) as e:
        day_start.of({"timezone": TZ, "day_start": value})
    assert "day_start" in str(e.value) and repr(value) in str(e.value)
    assert day_start.lenient(value) == time(0), "the index reads midnight; no reader reads it"


@pytest.mark.parametrize("value", ["00:00", "05:30", "23:59"])
def test_every_clock_from_midnight_to_one_minute_before_it_is_a_boundary(value: str) -> None:
    found = day_start.of({"timezone": TZ, "day_start": value})
    assert found.text == value
    assert day_start.of({"timezone": TZ}).text == "00:00"


def test_the_night_after_is_the_one_whose_window_holds_the_days_end() -> None:
    """The night window (22:00 to 08:00) is unchanged; the boundary says which night is a day's. At
    06:00 the night after the 12th is the night of the 12th, the stay at 06:00 on the 13th; at 23:00 the
    12th ends inside the window of the 13th's night; at noon the night inside the day is its night after."""
    six = day_start.DayStart(OSLO, time(6, 0))
    assert (six.night_before("2026-10-12", "22:00"), six.night_after("2026-10-12", "22:00")) == (
        "2026-10-11",
        "2026-10-12",
    )
    late = day_start.DayStart(OSLO, time(23, 0))
    assert (late.night_before("2026-10-12", "22:00"), late.night_after("2026-10-12", "22:00")) == (
        "2026-10-12",
        "2026-10-13",
    )
    assert late.day_before_night("2026-10-13", "22:00") == "2026-10-12"
    noon = day_start.DayStart(OSLO, time(12, 0))
    assert noon.night_after("2026-10-12", "22:00") == "2026-10-12"
    assert day_start.DayStart(OSLO).night_after("2026-10-12", "22:00") == "2026-10-12"


# -- the index -----------------------------------------------------------------------------------------------


def test_the_index_puts_each_line_on_the_day_the_boundary_says(lb: Logbook) -> None:
    assert _texts(lb.day_lines("2026-10-13")) == ["back from the late concert", "coffee on the balcony"]
    lb.set_meta(day_start="06:00")
    assert _texts(lb.day_lines("2026-10-12")) == ["back from the late concert"]
    assert _texts(lb.day_lines("2026-10-13")) == ["coffee on the balcony"]


def test_the_index_records_the_boundary_it_was_built_with_and_is_rebuilt_when_it_differs(lb: Logbook) -> None:
    with lb.index() as idx:
        stored = dict(idx.db.execute("SELECT key, value FROM meta"))
    assert "day_start" not in stored, "the default is no key: an index built before the setting still matches"
    lb.set_meta(day_start="06:00")
    with lb.index() as idx:
        stored = dict(idx.db.execute("SELECT key, value FROM meta"))
        assert idx.db.execute("SELECT day_local FROM lines ORDER BY seq").fetchall() == [
            ("2026-10-12",),
            ("2026-10-13",),
        ]
    assert stored["day_start"] == "06:00"


def test_add_after_the_boundary_is_set_extends_the_index_on_the_same_rule(lb: Logbook) -> None:
    lb.set_meta(day_start="06:00")
    with lb.index():
        pass
    _note(lb, "2026-10-14T02:00:00Z", "night shift")  # 04:00 on the 14th, local
    with lb.index() as idx:
        assert _texts(idx.day("2026-10-13")) == ["coffee on the balcony", "night shift"]


def test_add_never_refuses_a_boundary_no_reader_accepts(lb: Logbook) -> None:
    """`add` never groups by day (RFC 0036): a value no reader can parse leaves writing as it was."""
    lb.set_meta(day_start="6 in the morning")
    with lb.index():
        pass
    line = lb.append(
        at="2026-10-14T08:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "x"},
    )
    assert line["seq"] == 3
    assert index.local_date(EARLY, TZ, "6 in the morning") == "2026-10-13"


def test_nothing_in_a_line_or_its_month_file_moves(lb: Logbook) -> None:
    before = {p.relative_to(lb.root): p.read_bytes() for p in lb.files()}
    head = lb.meta["head"]
    lb.set_meta(day_start="06:00")
    with lb.index():
        pass
    assert {p.relative_to(lb.root): p.read_bytes() for p in lb.files()} == before
    assert lb.meta["head"] == head


# -- the setting ---------------------------------------------------------------------------------------------


def test_init_leaves_the_default(tmp_path: Path) -> None:
    cli.main(["init", str(tmp_path / "Fresh"), "--timezone", TZ])
    meta = json.loads((tmp_path / "Fresh" / "logbook.json").read_text(encoding="utf-8"))
    assert "day_start" not in meta


def test_setup_day_start_sets_it_and_rebuilds_an_index_that_exists(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    with lb.index():
        pass
    cli.main(["setup", "day_start", "06:00"])
    out = capsys.readouterr().out
    assert lb.meta["day_start"] == "06:00"
    assert "06:00" in out and "index" in out
    with lb.index() as idx:  # current already: no rebuild needed to read the 12th
        assert dict(idx.db.execute("SELECT key, value FROM meta"))["day_start"] == "06:00"
        assert idx.matches(lb.meta)
    assert _texts(lb.day_lines("2026-10-12")) == ["back from the late concert"]


def test_setup_day_start_without_an_index_says_the_next_reader_builds_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lb.index_path.unlink(missing_ok=True)
    cli.main(["setup", "day_start", "05:30"])
    out = capsys.readouterr().out
    assert lb.meta["day_start"] == "05:30"
    assert not lb.index_path.exists()
    assert "logbook repair index" in out


def test_setup_day_start_alone_says_where_the_day_begins(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["setup", "day_start"])
    assert "00:00" in capsys.readouterr().out
    lb.set_meta(day_start="06:00")
    cli.main(["setup", "day_start"])
    assert "06:00" in capsys.readouterr().out


def test_setup_day_start_refuses_a_value_that_is_not_a_clock(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "day_start", "6am"])
    assert e.value.code == 2
    assert "6am" in capsys.readouterr().err
    assert "day_start" not in lb.meta


def test_a_reader_refuses_a_boundary_it_cannot_parse(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lb.set_meta(day_start="25:00")
    for args in (["show", "2026-10-13"], ["day", "2026-10-13"], ["show", "days", "--from", "2026-10-12"]):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2, args
        err = capsys.readouterr().err
        assert "day_start" in err and "'25:00'" in err, args


def test_show_lists_the_page_of_the_day_so_defined(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lb.set_meta(day_start="06:00")
    cli.main(["show", "2026-10-12"])
    out = capsys.readouterr().out
    assert "back from the late concert" in out and "coffee" not in out
    assert "06:00" in out.splitlines()[0], "the header says where the day begins when it is not midnight"
    cli.main(["show", "2026-10-13"])
    out = capsys.readouterr().out
    assert "coffee on the balcony" in out and "concert" not in out


# -- the Day and its nights ----------------------------------------------------------------------------------


def test_the_day_reads_the_lines_of_the_day_so_defined(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.core import day as day_reader

    lb.set_meta(day_start="06:00")
    twelfth = day_reader.read(lb, "2026-10-12")
    assert [u["title"] for u in twelfth["unplaced"]] == ["back from the late concert"]
    assert twelfth["day_start"] == "06:00"
    thirteenth = day_reader.read(lb, "2026-10-13")
    assert [u["title"] for u in thirteenth["unplaced"]] == ["coffee on the balcony"]
    cli.main(["day", "2026-10-12"])
    head = capsys.readouterr().out.splitlines()[0]
    assert head == "2026-10-12  Monday · unsigned · 06:00 to 06:00 the next day"
    lb.set_meta(day_start="00:00")
    assert "day_start" not in day_reader.read(lb, "2026-10-12"), "the Day's object is as it was at midnight"
    cli.main(["day", "2026-10-13"])
    assert capsys.readouterr().out.splitlines()[0] == "2026-10-13  Tuesday · unsigned", (
        "midnight says nothing"
    )


def test_the_timeline_runs_from_the_boundary_to_the_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from persona import persona_record

    from logbook.core import day as day_reader

    lb = persona_record(tmp_path, monkeypatch)
    lb.set_meta(day_start="06:00")
    data = day_reader.read(lb, "2026-06-09")
    first, last = data["timeline"][0], data["timeline"][-1]
    assert first["within_day"]["start"] == "2026-06-09T04:00:00Z", "06:00 CEST"
    assert last["within_day"]["end"] == "2026-06-10T04:00:00Z", "06:00 the next morning"


def test_night_before_and_night_after_follow_the_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monday 15 June the persona flies to Zürich; the nights of the 15th, 16th and 17th are at the
    hotel. At 06:00 the night after the 15th is the stay at 06:00 on the 16th, the hotel, as at midnight.
    At 23:00 the 14th ends inside the night of the 15th: its night after is the hotel, and the 15th's
    night before is that same night."""
    from persona import persona_record

    from logbook.core import day as day_reader

    lb = persona_record(tmp_path, monkeypatch)
    lb.set_meta(day_start="06:00")
    data = day_reader.read(lb, "2026-06-15")
    assert (data["nights"]["before"]["where"], data["nights"]["before"]["home"]) == ("Home", True)
    after = data["nights"]["after"]
    assert after["day"] == "2026-06-15" and after["home"] is False and not after["in_transit"]
    lb.set_meta(day_start="23:00")
    fourteenth = day_reader.read(lb, "2026-06-14")
    assert fourteenth["nights"]["after"]["day"] == "2026-06-15"
    assert fourteenth["nights"]["after"]["home"] is False, "the 14th ends at 23:00 on the 15th, in Zürich"
    fifteenth = day_reader.read(lb, "2026-06-15")
    assert (
        fifteenth["nights"]["before"]["day"] == "2026-06-15"
        and fifteenth["nights"]["before"]["home"] is False
    )
    assert fifteenth["nights"]["after"]["day"] == "2026-06-16"


def test_days_and_trips_follow_the_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from persona import persona_record

    from logbook.core import days as days_reader
    from logbook.core import reading, trips

    lb = persona_record(tmp_path, monkeypatch)
    lb.set_meta(day_start="06:00")
    rows = {r["day"]: r for r in days_reader.read(lb, "2026-06-14", "2026-06-18")}
    assert [d for d, r in rows.items() if not r["night"]["home"]] == [
        "2026-06-15",
        "2026-06-16",
        "2026-06-17",
    ]
    found = trips.trips(reading.read(lb, "2026-06-08", "2026-06-21"))[0]
    assert [(t.start, t.end, t.until) for t in found] == [
        ("2026-06-13", "2026-06-13", "2026-06-14"),  # the night aboard Solvind
        ("2026-06-15", "2026-06-17", "2026-06-18"),  # Zürich, as at midnight
    ]
    lb.set_meta(day_start="23:00")
    found = trips.trips(reading.read(lb, "2026-06-08", "2026-06-21"))[0]
    assert [(t.start, t.end, t.until, t.nights) for t in found] == [
        ("2026-06-12", "2026-06-12", "2026-06-13", 1),
        ("2026-06-14", "2026-06-16", "2026-06-17", 3),
    ], "a day that ends at 23:00 ends in the night of the next date: each trip is a day earlier"


# -- the signed day ------------------------------------------------------------------------------------------


def test_a_signed_day_covers_the_day_so_defined(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    from logbook.core import crossing, policy, signing

    lb.set_meta(day_start="06:00")
    early = str(lb.day_lines("2026-10-12")[0]["id"])
    line = signing.sign(lb, "2026-10-12")
    assert line["payload"]["confirmed"] == [early]
    assert line["payload"]["page"]["lines"] == 1
    req = crossing.request(
        lb, policy.DEFAULT_DESTINATION, "2026-10-12T00:00:00Z", "2026-10-14T00:00:00Z", (1, 2)
    )
    crossed = [str(x["id"]) for x in crossing.select(lb, req).lines if x["kind"] == "note"]
    assert crossed == [early], "the 01:30 line is the signed 12th's; the 07:00 line is the unsigned 13th's"
    cli.main(["day", "2026-10-12", "--json"])
    assert json.loads(capsys.readouterr().out)["signed"]["page_matches"] is True
    lb.set_meta(day_start="00:00")  # the boundary moved: the 12th's page is empty now
    cli.main(["day", "2026-10-12", "--json"])
    assert json.loads(capsys.readouterr().out)["signed"]["page_matches"] is False
    cli.main(["setup", "day_start", "06:00"])
    assert "still match" in capsys.readouterr().out, "set back, the signature matches again"


def test_setting_the_boundary_says_how_many_signed_pages_moved(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.core import signing

    signing.sign(lb, "2026-10-13")
    cli.main(["setup", "day_start", "06:00"])
    out = capsys.readouterr().out
    assert "1 of 1 no longer match their page" in out


# -- gaps, the digest, /today -------------------------------------------------------------------------------


def test_gaps_count_days_by_the_boundary(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    from logbook.contrib import gaps

    lb.set_meta(day_start="06:00")
    monkeypatch.setattr(gaps, "now", lambda: datetime(2026, 10, 14, 3, 0, tzinfo=UTC))  # 05:00 on the 14th
    report = gaps.report(lb, since="2026-10-12")
    assert report["today"] == "2026-10-13", "at 05:00 the owner is still in the 13th"
    [manual] = report["sources"]
    assert manual["missing_days"] == []
    monkeypatch.setattr(gaps, "now", lambda: datetime(2026, 10, 14, 5, 0, tzinfo=UTC))  # 07:00 on the 14th
    assert gaps.report(lb, since="2026-10-12")["today"] == "2026-10-14"


def test_the_digest_closes_only_a_day_that_has_ended_by_the_boundary(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logbook.contrib import digest, gaps

    lb.set_meta(day_start="06:00")
    monkeypatch.setattr(gaps, "now", lambda: datetime(2026, 10, 13, 3, 59, tzinfo=UTC))  # 05:59 on the 13th
    with pytest.raises(ValueError, match="after today"):
        digest.read(lb, "2026-10-13")
    assert digest.read(lb, "2026-10-12")["day"] == "2026-10-12"


@pytest.mark.parametrize(
    ("now", "day"),
    [
        (datetime(2026, 10, 13, 3, 59, tzinfo=UTC), "2026-10-12"),  # 05:59 local: still the 12th
        (datetime(2026, 10, 13, 4, 1, tzinfo=UTC), "2026-10-13"),  # 06:01 local: the 13th has begun
    ],
)
def test_today_redirects_to_the_day_under_the_boundary(lb: Logbook, now: datetime, day: str) -> None:
    from logbook.contrib import serve

    lb.set_meta(day_start="06:00")
    response = serve.Site(lb, now=lambda: now).respond("/today")
    assert response.status == 302 and response.location == f"/day/{day}"


def test_the_day_page_says_where_the_day_begins_when_it_is_not_midnight(lb: Logbook) -> None:
    from logbook.contrib import serve

    page = serve.Site(lb).respond("/day/2026-10-13").body.decode("utf-8")
    assert "the next day" not in page
    lb.set_meta(day_start="06:00")
    page = serve.Site(lb).respond("/day/2026-10-12").body.decode("utf-8")
    assert "06:00 to 06:00 the next day" in page and "back from the late concert" in page


def test_a_page_of_a_record_whose_boundary_is_not_a_clock_is_refused_naming_it(lb: Logbook) -> None:
    from logbook.contrib import serve

    lb.set_meta(day_start="six")
    response = serve.Site(lb).respond("/day/2026-10-13")
    assert response.status == 500 and "day_start" in response.body.decode("utf-8")


# -- the conformance samples ---------------------------------------------------------------------------------

CONFORMANCE = Path(__file__).resolve().parents[1] / "conformance"
HEADS = {
    "sample-logbook": ("expected.json", "58bfa9e704e3388d44d74e63f1d84765d24df79e92fce3b522fbef53b765d3df"),
    "sample-logbook-sealed": (
        "expected-sealed.json",
        "0ab4c3e79bacc9a7c19d074094e81d1674fdf6967ceaf0d1711679e3c11481db",
    ),
}


@pytest.mark.parametrize("sample", sorted(HEADS))
def test_the_conformance_samples_keep_the_default_boundary_and_their_heads(
    sample: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The samples carry no `day_start` (RFC 0036: a reader that has not implemented it passes as
    before), and every line and head is what it was."""
    expected, head = HEADS[sample]
    meta = json.loads((CONFORMANCE / sample / "logbook.json").read_text(encoding="utf-8"))
    assert "day_start" not in meta and meta["head"] == head
    assert json.loads((CONFORMANCE / expected).read_text(encoding="utf-8"))["head"] == head
    cli.main(["verify", "--root", str(CONFORMANCE / sample), "--expect", str(CONFORMANCE / expected)])
    assert f"head {head}" in capsys.readouterr().out
