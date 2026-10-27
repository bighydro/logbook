"""No number beside a person's name in any draft (R6, VISION: no metrics near people): the journey and
the person dreams hold a sentence that sets one, as the day, the week, the month and the chapter do
(`dream.hold_numbers`, then `dream.hold_names`), and every reader holds one in a draft already stored,
whatever wrote it and whenever (`drafts.hold_beside`): `day`, the Day page, `show trip`, the journey's
page and `export letter` print its words nowhere. On the dream's synthetic fortnight: Kari and Ola
Nordmann of Oslo, who do not exist."""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import JOURNEY, fake, fortnight, journey_answer, run_cli
from test_dream_journey import THURSDAY_06
from test_dream_person import _dream as dream_person_cli
from test_relationship_model import _env, _fake
from test_relationship_reader import _record

from logbook.contrib import dream, dream_person, serve
from logbook.core import drafts, policy
from logbook.core.store import Logbook

NAMES = ("Ola Nordmann", "Ola", "Kari Nordmann", "Kari")
_ALT = "|".join(re.escape(n) for n in NAMES)
SEP = "[\\s(:×x#·,\\-\u2013\u2014/|;=•.']*"  # with the en and em dash
# the strong guard: a digit, then nothing but separators, then a name; or a name, then separators, a digit
GUARD = re.compile(rf"(\d{SEP}(?:{_ALT})\b)|(\b(?:{_ALT})\??{SEP}\d)")
OLD = "Ola Nordmann: 4 messages before lunch."  # a sentence a draft stored before the rule
NIGHTS = "3 nights with Ola Nordmann."  # a model's journey sentence
CALLS = "Ola Nordmann (3 calls)."  # a model's person sentence
DAY = "2026-06-16"  # a day of the journey


def beside(text: str) -> list[str]:
    """Every row of `text` where a number stands beside a name (`GUARD`), the markup taken out first: a
    date, a clock time or a line's number is a number like any other (the owner, 27 October)."""
    rows = html.unescape(re.sub(r"<[^>]*>", " ", text)).splitlines()
    return [row.strip() for row in rows if GUARD.search(row)]


def test_the_guard_finds_the_sentences() -> None:
    assert beside(OLD) and beside(CALLS) and beside("Ola Nordmann — 4") and beside("4 · Ola")
    assert beside("A day with Ola Nordmann at 12:30 on 2026-06-16.") == [], "words between are fine"
    assert beside("Ola Nordmann, 2026-06-05") and beside("14:00 · Kari") and beside("#41 Ola Nordmann")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = fortnight(tmp_path / "lb", until=THURSDAY_06)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 18))
    return lb


def _with_numbers(material: dict[str, Any]) -> dict[str, Any]:
    """The fortnight's journey answer and a sentence that sets a count beside Ola, on a reference given."""
    found = journey_answer(material)
    found["journey"].append({"text": NIGHTS, "evidence": material["journey"]["ref"][:1]})
    return found


def test_the_journey_holds_a_number_beside_a_name(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    from dream_fortnight import ENV, rest

    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    rest(lb, THURSDAY_06)
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 19))
    fake(monkeypatch, journey=_with_numbers)
    code, out, err = run_cli("dream", "journey", JOURNEY)
    assert code == 0, out + err
    assert NIGHTS not in out and beside(out) == [], beside(out)
    (line,) = [
        x for x in Logbook(lb.root).lines() if x["kind"] == drafts.KIND and x["payload"]["unit"] == "journey"
    ]
    texts = [s["text"] for s in line["payload"]["segments"]]
    assert NIGHTS not in texts and dream.HELD in texts
    assert line["payload"]["extra"]["marked"][dream.BESIDE_A_NAME] == 1


def test_the_person_dream_holds_a_number_beside_a_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_network
):
    lb, _ids = _record(tmp_path, monkeypatch)
    _env(monkeypatch)
    monkeypatch.setattr(dream_person, "today", lambda: date(2026, 7, 1))

    def answer(material: dict[str, Any]) -> dict[str, Any]:
        by_text = {line["text"]: line["ref"] for line in material["lines"]}
        return {
            "person": [
                {"text": "June with Ola was the boat.", "evidence": [by_text["Yes! Saturday."]]},
                {"text": CALLS, "evidence": [by_text["Yes! Saturday."]]},
                {
                    "text": "He thanked you for the weekend.",
                    "evidence": [by_text["Thanks for a great weekend."]],
                },
                {"text": "The charts came up.", "evidence": [by_text["Charts for Saturday"]]},
            ],
        }

    _fake(monkeypatch, answer)
    code, out, err = dream_person_cli(capsys)
    assert code == 0, out + err
    assert CALLS not in out and beside(out) == [], beside(out)
    (line,) = [x for x in Logbook(lb.root).lines() if x["kind"] == drafts.KIND]
    texts = [s["text"] for s in line["payload"]["segments"]]
    assert CALLS not in texts and dream.HELD in texts
    assert line["payload"]["extra"]["marked"][dream.BESIDE_A_NAME] == 1


def _stored(lb: Logbook, unit: str, source: str) -> dict[str, Any]:
    """The standing draft of `unit` written again as one stored before the rule: its first segment
    `OLD`, its source `source` (a demo's, a trip bundle's own words: any writer), superseding it."""
    line = [x for x in Logbook(lb.root).lines() if x["kind"] == drafts.KIND and x["payload"]["unit"] == unit][
        -1
    ]
    payload = json.loads(json.dumps(line["payload"]))
    payload["segments"][0]["text"] = OLD
    payload["supersedes"] = str(line["id"])
    return dict(lb.append(line["at"], source, drafts.KIND, int(line["tier"]), payload, tz=line.get("tz")))


def test_no_reader_prints_a_number_beside_a_name_in_a_stored_draft(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network
):
    from dream_fortnight import ENV, rest

    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    rest(lb, THURSDAY_06)
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 19))
    fake(monkeypatch)
    assert run_cli("dream", "day", DAY)[0] == 0 and run_cli("dream", "journey", JOURNEY)[0] == 0
    day_draft = _stored(lb, "day", "model:demo")  # the demo record's, say
    journey_draft = _stored(lb, "journey", "model:qwen2.5-7b-instruct")
    for line in (day_draft, journey_draft):
        assert OLD in json.dumps(line)

    crossing = policy.policy_path(lb.root)  # the letter's entry, beside the dream's
    entries = json.loads(crossing.read_text(encoding="utf-8"))
    crossing.write_text(json.dumps({**entries, "letter": {"max_tier": 2}}), encoding="utf-8")
    texts: dict[str, str] = {}
    code, texts["day"], err = run_cli("day", DAY)
    assert code == 0, err
    texts["day --json"] = run_cli("day", DAY, "--json")[1]
    texts["/day"] = serve.Site(lb).respond(f"/day/{DAY}", "").body.decode("utf-8")
    code, texts["show trip"], err = run_cli("show", "trip", DAY)
    assert code == 0, err
    texts["show trip --json"] = run_cli("show", "trip", JOURNEY, "--json")[1]
    _trip, first, last = JOURNEY.split(":")
    page = serve.Site(lb).respond(f"/journeys/{first}/{last}", "")
    texts["/journeys"] = page.body.decode("utf-8")
    assert page.status == 200, texts["/journeys"][:400]
    for unit in ("day", "journey"):
        out = tmp_path / f"letter-{unit}"
        code, _out, err = run_cli(
            "export", "letter", "2026-06-15", "2026-06-18", "--out", str(out), "--unit", unit, "--unsigned"
        )
        assert code == 0, err
        texts[f"letter {unit}"] = "\n".join(p.read_text(encoding="utf-8") for p in sorted(out.iterdir()))
    printed = {reader: beside(text) for reader, text in texts.items() if "4 messages" in text or beside(text)}
    assert printed == {}, printed
    assert "Ola Nordmann" in texts["show trip"], "the people are still named, with no number"


def test_a_reader_holds_only_beside_a_person_s_name(tmp_path: Path) -> None:
    """A label that names no person (a phone the record calls "Bank") is not one of `people_of`."""
    from persona import resolution

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    bank = resolution(("phone", "+447700900456"), "x", "Bank")
    bank["payload"].pop("entity")
    lb.append_many([bank, resolution(("phone", "+447700900457"), "e-ola", "Ola Nordmann")])
    with lb.index() as idx:
        assert drafts.people_of(idx) == frozenset({"Ola Nordmann"})


# -- a date, a clock time, any number: never beside a name, in any reader (the owner, 27 October) ----------

CLOCK = "Ola Nordmann, 14:00 at the berth."  # a model's sentence: a clock beside the name, nothing between
DATE = "Kari Nordmann · 2026-06-10."


def test_a_date_or_a_clock_beside_a_name_is_held_and_words_between_are_kept() -> None:
    from logbook.core import figures

    names = ["Ola Nordmann", "Kari Nordmann"]
    assert figures.beside_a_name(CLOCK, names) and figures.beside_a_name(DATE, names)
    assert not figures.beside_a_name("Dinner with Ola at 14:00.", names), "a word between: kept"
    assert not figures.beside_a_name("Ola Nordmann promised you · since 8 June", names)


def test_no_reader_of_the_dreamed_fortnight_sets_a_number_beside_a_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network
):
    """Every reader on the fortnight with its days, weeks and journey dreamed, a stored draft carrying
    `CLOCK` and `DATE` among them: the strong guard finds nothing, a date's and a clock's number
    included, and no row is let off."""
    from dream_fortnight import DAYS, ENV, W24, W25

    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 22))
    fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] in (0, 1)
    line = [
        x for x in Logbook(lb.root).lines() if x["kind"] == drafts.KIND and x["payload"]["unit"] == "day"
    ][-1]
    payload = json.loads(json.dumps(line["payload"]))
    evidence = payload["segments"][0].get("evidence") or []
    payload["segments"] = [{"text": CLOCK, "evidence": evidence}, {"text": DATE, "evidence": evidence}]
    payload["extra"]["parts"] = ["story", "story"]
    payload["supersedes"] = str(line["id"])
    lb.append(line["at"], line["source"], drafts.KIND, int(line["tier"]), payload, tz=line.get("tz"))
    crossing = policy.policy_path(lb.root)
    entries = json.loads(crossing.read_text(encoding="utf-8"))
    crossing.write_text(
        json.dumps({**entries, "letter": {"max_tier": 2}, "site": {"max_tier": 2}}), encoding="utf-8"
    )
    texts: dict[str, str] = {}
    site = serve.Site(lb)
    for day in DAYS:
        texts[f"day {day}"] = run_cli("day", day)[1]
        texts[f"show {day}"] = run_cli("show", day)[1]
        texts[f"/day/{day}"] = site.respond(f"/day/{day}", "").body.decode("utf-8")
    for args in (
        ("show", "trips"),
        ("show", "trip", JOURNEY),
        ("show", "year", "2026"),
        ("promises",),
        ("people",),
        ("digest", "--paper", "--week", W25),
    ):
        code, texts[" ".join(args)], err = run_cli(*args)
        assert code == 0, (args, err)
    _trip, first, last = JOURNEY.split(":")
    for path in ("/journeys", f"/journeys/{first}/{last}", f"/week/{W24}", f"/week/{W25}", "/people"):
        page = site.respond(path, "")
        assert page.status == 200, path
        texts[path] = page.body.decode("utf-8")
    for unit in ("day", "week", "journey"):
        out = tmp_path / f"letter-{unit}"
        code, _out, err = run_cli(
            "export", "letter", DAYS[0], DAYS[-1], "--out", str(out), "--unit", unit, "--unsigned"
        )
        assert code == 0, err
        texts[f"letter {unit}"] = "\n".join(p.read_text(encoding="utf-8") for p in sorted(out.iterdir()))
    folder = tmp_path / "site"
    code, _out, err = run_cli("export", "site", str(folder), "--tier", "1,2", "--with-drafts")
    assert code == 0, err
    texts |= {
        f"site {p.relative_to(folder).as_posix()}": p.read_text(encoding="utf-8")
        for p in folder.rglob("*.html")
    }
    assert any("Ola Nordmann" in t for t in texts.values()), (
        "the people are named, with no number beside them"
    )
    printed = {reader: beside(text) for reader, text in texts.items() if beside(text)}
    assert printed == {}, printed
    assert not any(CLOCK in t or DATE in t for t in texts.values()), "the stored sentences are held"
