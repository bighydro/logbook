"""`logbook demo --years N --seed S --out DIR`: a synthetic life of the Oslo persona from birth to
today, whose phases change the shape of the data, deterministic from the seed, that every reader
of the record runs on. Forty years is the headline case; a one-year record is a baby's."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli, demo, demo_life
from logbook.core import people, reading
from logbook.core.index import local_date
from logbook.core.store import Logbook

YEARS = 40
SEED = 7
PHONE = re.compile(r"\+447700900\d{3}$")  # the UK reserved range, nothing else


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> Any:
    return json.loads(_run(capsys, *args, "--json"))


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """Forty years, generated once for the readers' tests of this module."""
    root = tmp_path_factory.mktemp("life") / "Life"
    cli.main(["demo", "--years", str(YEARS), "--seed", str(SEED), "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


@pytest.fixture(scope="module")
def years(record: Logbook) -> dict[int, Counter[str]]:
    """Lines per kind per local year, read once."""
    out: dict[int, Counter[str]] = {}
    for line in record.lines():
        year = int(local_date(line["at"], demo.TZ)[:4])
        out.setdefault(year, Counter())[line["kind"]] += 1
    return out


@pytest.fixture(scope="module")
def people_report(record: Logbook) -> people.Report:
    """`people` over the whole life, read once, from the channels alone: `people._together` asks
    `stays.night` for every day of the window and that scans every stay of the window each time,
    so a forty-year window takes minutes. The people this module asks about (who drifted out, when
    someone first appears) are decided by their messages, calls, calendar entries, mail and faces,
    which the channels carry; the owner's track is read for one day only, so it holds no stay."""
    real = reading.owner_track

    def one_day(lb: Logbook, first: str, last: str, airports: Any = None) -> reading.OwnerTrack:
        return real(lb, first, first, airports)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(reading, "owner_track", one_day)
        first, last = reading.record_days(record) or ("", "")
        return people.read(record, first, last)


# -- the record ------------------------------------------------------------------------------------------


def test_the_life_verifies_and_holds_every_profile(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "verify")
    assert out.startswith("valid")
    stats = _json(capsys, "stats")
    kinds = {k["kind"] for k in stats["kinds"]}
    assert kinds >= demo.KINDS, demo.KINDS - kinds
    schemas = {line["payload"]["schema"] for line in lb.lines()}
    assert schemas >= demo.SCHEMAS, demo.SCHEMAS - schemas
    birth = demo_life.birthday(YEARS)
    assert birth == date(1986, 7, 1)
    assert stats["first"].startswith("1986-06-30"), "the resolutions, written the day before the birth"
    assert stats["last"].startswith("2026-06-30"), "the life ends where the default month does"
    assert lb.meta["seq"] < 300_000, "forty years stay a reasonable record"
    assert (lb.root / "places.json").is_file() and (lb.root / "assets.json").is_file()


def test_nothing_in_it_is_real(lb: Logbook) -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in lb.files())
    for phone in re.findall(r"\+\d{8,}", text):
        assert PHONE.match(phone), phone
    for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text):  # a chat id is source-native
        assert email.endswith(("example.org", "@s.whatsapp.net", "@g.us")), email
    for mmsi in re.findall(r'"mmsi":\s*"(\d+)"', text):
        assert mmsi.startswith("970"), mmsi
    for registration in re.findall(r'"registration":\s*"([^"]+)"', text):
        assert registration.startswith("ZZ-"), registration
    for carrier in re.findall(r'"carrier":\s*"([^"]+)"', text):
        assert carrier == "XY", carrier


def test_the_same_seed_gives_the_same_head(tmp_path: Path) -> None:
    a = demo.generate(tmp_path / "a", years=2, seed=1)
    b = demo.generate(tmp_path / "b", years=2, seed=1)
    c = demo.generate(tmp_path / "c", years=2, seed=2)
    assert a.meta["head"] == b.meta["head"] and a.meta["seq"] == b.meta["seq"]
    assert c.meta["head"] != a.meta["head"]
    for f in a.files():
        assert f.read_bytes() == (b.root / f.relative_to(a.root)).read_bytes()


def test_the_default_month_is_untouched(tmp_path: Path) -> None:
    """`--years` is another record; the month `--days` writes keeps its head."""
    a = demo.generate(tmp_path / "a", days=3, seed=1)
    b = demo.generate(tmp_path / "b", days=3, seed=1)
    assert a.meta["head"] == b.meta["head"]
    assert (demo.START - demo_life.birthday(1)).days > 300, "the one-year life ends on the month's last day"


def test_years_and_days_are_one_or_the_other(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["demo", "--years", "2", "--days", "3", "--out", str(tmp_path / "a")])
    assert e.value.code == 2 and "--years" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["demo", "--years", "0", "--out", str(tmp_path / "b")])
    assert e.value.code == 2 and "at least 1" in capsys.readouterr().err
    cli.main(["demo", "--years", "1", "--seed", "3", "--out", str(tmp_path / "c")])
    out = capsys.readouterr().out
    assert "1 year" in out and "2025-07-01 to 2026-06-30" in out
    baby = Logbook(tmp_path / "c")
    seq, _head, errors = baby.verify()
    assert not errors and seq > 0
    kinds = {line["kind"] for line in baby.lines()}
    assert "photo" in kinds and "event" in kinds and "location" not in kinds, "a baby has no phone"


# -- the phases ------------------------------------------------------------------------------------------


def test_childhood_is_sparse_and_told_by_others(lb: Logbook, years: dict[int, Counter[str]]) -> None:
    child = years[1990]  # age three to four
    assert child["location"] == 0 and child["health"] == 0 and child["message"] == 0
    assert 0 < sum(child.values()) < 60, child
    assert child["photo"] >= 4 and child["event"] >= 2
    tellers = Counter()
    for line in lb.lines():
        if line["kind"] == "note" and local_date(line["at"], demo.TZ) < "1993-01-01":
            teller = line["payload"]["text"].split(":")[0]
            tellers[teller] += 1
    assert tellers[demo.KARI.name] >= 1 and tellers[demo.OLA.name] >= 1, tellers
    assert set(tellers) <= {demo.KARI.name, demo.OLA.name}, "a childhood is told by others"


def test_school_and_university_bring_the_calendar_and_the_friends(
    years: dict[int, Counter[str]], people_report: people.Report
) -> None:
    assert years[1998]["event"] > 3 * years[1990]["event"], "school fills the calendar"
    assert years[2008]["event"] > years[1998]["event"], "lectures fill it more"
    assert years[2008]["message"] > 0 and years[2008]["mail"] > 0
    assert years[1998]["transcript"] == 0 and years[2008]["transcript"] == 0, "no meetings before work"
    known = {p.name: p for p in people_report.people}
    assert known[demo_life.MIA.name].first_contact < "1995-01-01"
    assert known[demo_life.HANNA.name].first_contact[:4] == "2005", "a friend from the first term"
    assert known[demo_life.BJORN.name].first_contact[:4] == "2010", "the first boss, the first job"


def test_people_shows_someone_a_decade_gone(people_report: people.Report) -> None:
    cutoff = date(2016, 6, 30).isoformat()  # ten years before the record's last day
    gone = [p for p in people_report.people if p.last_contact is not None and p.last_contact < cutoff]
    assert gone, "someone drifted out"
    names = {p.name for p in gone}
    assert demo_life.JENS.name in names and demo_life.MIA.name in names, names
    assert demo_life.SOLVEIG.name in names, "the grandmother, in the photos until Ines is 27"
    assert demo.OLA.name not in names, "Ola drifted out of school and back in"
    text = "\n".join(people.rows(people_report))
    jens = next(line for line in text.splitlines() if demo_life.JENS.name in line)
    assert "2005" in jens, jens
    ola = next(p for p in people_report.people if p.name == demo.OLA.name)
    assert ola.first_contact is not None and ola.first_contact < "1992-01-01"
    assert ola.last_contact is not None and ola.last_contact >= "2026-06-01"
    tore = next(p for p in people_report.people if p.name == demo.TORE.name)
    assert tore.first_contact is not None and tore.first_contact[:4] == "2020", "the runs of the watch years"


def test_work_years_bring_mail_transcripts_travel_and_the_boat(
    lb: Logbook, years: dict[int, Counter[str]]
) -> None:
    for year in (2012, 2016, 2020, 2024):
        assert years[year]["mail"] >= 50 and years[year]["transcript"] >= 6, (year, years[year])
        assert years[year]["flight"] >= 4, (year, years[year]["flight"])
    first_ais = min(
        local_date(line["at"], demo.TZ) for line in lb.lines() if line["payload"].get("subject") == demo.BOAT
    )
    assert first_ais[:4] == "2021", "the boat appears the summer she turns thirty-five"
    assert years[2015]["location"] < years[2025]["location"], "old years are thin"


def test_health_only_from_the_year_the_watch_appears(
    lb: Logbook, years: dict[int, Counter[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    first = min(local_date(line["at"], demo.TZ) for line in lb.lines() if line["kind"] == "health")
    assert first == demo_life.birthday(YEARS, demo_life.WATCH_AGE).isoformat()
    assert years[2019]["health"] == 0 and years[2021]["health"] > 300
    days = _json(capsys, "stats", "--health")["days"]
    assert days[0]["day"] >= first
    for d in days[1:30]:
        assert d["sleep_h"] is not None and 5.5 <= d["sleep_h"] <= 9.5, d
        assert d["steps"] is not None and 2000 <= d["steps"] <= 20000, d


def test_the_move_between_cities(lb: Logbook) -> None:
    before: list[tuple[float, float]] = []
    after: list[tuple[float, float]] = []
    for line in lb.lines():
        if line["kind"] != "location" or "subject" in line["payload"]:
            continue
        day = local_date(line["at"], demo.TZ)
        if "2018-03-01" <= day < "2018-03-08":
            before.append((line["payload"]["lat"], line["payload"]["lon"]))
        elif "2019-03-01" <= day < "2019-03-08":
            after.append((line["payload"]["lat"], line["payload"]["lon"]))
    in_copenhagen = sum(1 for lat, _ in before if 55.5 < lat < 55.8)
    in_oslo = sum(1 for lat, _ in after if 59.8 < lat < 60.0)
    assert before and in_copenhagen > 0.7 * len(before), "Copenhagen before the move"
    assert after and in_oslo > 0.7 * len(after), "Oslo after it (a cabin weekend aside)"
    homes = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    assert {name for name, p in homes.items() if p.get("kind") == "home"} >= {
        demo_life.BG_HOME.name,
        demo_life.CPH_FLAT.name,
        demo.HOME.name,
    }


# -- the readers -----------------------------------------------------------------------------------------


def test_trips_in_an_early_and_a_late_year(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    early = _json(capsys, "trips", "--year", "2001")["trips"]
    assert early, "the summer at the family cabin, the first year with a phone"
    assert any(demo_life.BG_CABIN.name in t["route"] for t in early), [t["route"] for t in early]
    assert all(t["nights"] < 60 for t in early), "a year without a track is not one long trip"
    late = _json(capsys, "trips", "--year", "2025")["trips"]
    assert late
    assert any(t["flights_in"] for t in late), "a flight in"
    assert any(demo.CABIN.name in t["route"] for t in late)
    for year in ("2001", "2025"):
        text = _run(capsys, "trips", "--year", year)
        assert "night" in text, text
    assert _json(capsys, "trips", "--year", "1990")["trips"] == [], "no phone, no track, no trips"


def test_the_long_trips(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    term = max(_json(capsys, "trips", "--year", "2008")["trips"], key=lambda t: t["nights"])
    assert term["nights"] >= 100 and "Barcelona" in " ".join(term["route"]), term["route"]
    flights = _json(capsys, "rollup", "flights")
    by_year = {y["year"]: y for y in flights["years"]}
    assert min(by_year) == "2000", "the first flights, the summer she gets a phone"
    assert by_year["2000"]["by_evidence"] == {"declared": 2}, "the first flights are declared"
    assert by_year["2025"]["by_evidence"].get("tracked", 0) >= 4


def test_a_day_of_every_phase_reads(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    for day in ("1988-07-01", "1998-10-07", "2007-02-14", "2014-09-16", "2023-07-26", "2026-06-17"):
        text = _run(capsys, "day", day)
        assert text.startswith(day), text[:40]
    text = _run(capsys, "day", "2023-07-26")
    assert demo.BOAT_NAME in text
