"""No number beside a person's name (RFC 0043 §2.5, VISION: no metrics near people), in ink or pencil:
a week draft's people are printed by name only, in the draft's order, by every reader that renders them
(`dream week`, `logbook day`, `show`, the Day page, `export site`, letters), and the week holds a
sentence of its own that puts a figure beside a person, as the day, the month and the chapter do. A
call's length and a recording's talk time are never set beside a name either. On the dream's synthetic
fortnight: Ines, Kari and Ola Nordmann of Oslo, who do not exist."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import letter_record
import pytest
from dream_fortnight import DAYS, ENV, KARI, OLA, W25, fake, fortnight, run_cli, week_answer
from persona import utc

from logbook.contrib import digest, dream, dream_week, letter, serve, week_paper
from logbook.core import day as day_reader
from logbook.core import drafts, policy, speakers
from logbook.core.store import Logbook

NAMES = ("Kari Nordmann", "Ola Nordmann", "Per Hansen", "Kari", "Ola")
MONDAY_AFTER = "2026-06-22"  # the close of Sunday 21 June: both weeks are over
SUNDAY = "2026-06-21"
CALL_DAY, RECORDING_DAY = "2026-06-17", "2026-06-19"
_ALT = "|".join(re.escape(n) for n in NAMES)
# the guard: a digit, then nothing but a separator, then a name; or a name, then a separator, then a digit
GUARD = re.compile(rf"(\d[\s(:×x#·,]*(?:{_ALT})\b)|(\b(?:{_ALT})\??[\s(:×x#·,]*\d)")


RAW = re.compile(r'<a class="raw"[^>]*>#\d+</a>')  # a row's link to its line as written: an address


def beside(texts: str | Iterable[str]) -> list[str]:
    """Every place in `texts` where a number stands beside a person's name (`GUARD`), the markup taken
    out first; dates and clock times are not numbers, as `dream.figures` reads them (`dream.CALENDAR`),
    nor is a page's link from a row to its line as written (`#SEQ`, `RAW`), the line's address."""
    found: list[str] = []
    for text in [texts] if isinstance(texts, str) else texts:
        for row in html.unescape(re.sub(r"<[^>]*>", " ", RAW.sub(" ", text))).splitlines():
            if GUARD.search(dream.CALENDAR.sub(" ", row)):
                found.append(row.strip())
    return found


def test_the_guard_finds_a_count_on_either_side_and_lets_dates_and_clocks_be() -> None:
    assert beside("contacts  Kari Nordmann 12 · Ola Nordmann 3") == [
        "contacts  Kari Nordmann 12 · Ola Nordmann 3"
    ]
    assert beside("12 × Kari Nordmann") and beside("you 3 min · Ola Nordmann 3 min") and beside("Ola: 4")
    assert beside(["<li>Kari Nordmann <span>3</span></li>"]), "markup is no separator"
    assert beside("with  Kari Nordmann · Ola Nordmann") == []
    assert beside("due  “Comments by Friday.”  Kari Nordmann, 2026-06-05 (by Friday)") == []
    assert beside("19:30  call  19 min ← Ola Nordmann, cellular") == []


# -- the readers, on rows a week before this rule wrote ------------------------------------------------------

WEEK_BEFORE = {  # a week's `extra.numbers.people` as `dream-week/1` kept it: a count beside each name
    "people": [
        {"name": "Kari Nordmann", "id": "e-kari", "messages": 9, "calendar": 3, "calls": 0, "transcripts": 0,
         "contacts": 12, "days_together": 2, "lines": ["l1", "l2"]},
        {"name": "Ola Nordmann", "id": "e-ola", "messages": 1, "calendar": 1, "calls": 1, "transcripts": 0,
         "contacts": 3, "lines": ["l3"]},
    ],
    "places": [{"place": "Office", "hours": 41.5, "days": 5, "lines": ["l4"]}],
}  # fmt: skip


def test_a_week_s_people_are_names_only_in_the_draft_s_order_wherever_a_draft_is_printed() -> None:
    rows = list(drafts.number_rows(WEEK_BEFORE, ""))
    assert rows == ["  hours     Office 41.5 h", "  with      Kari Nordmann · Ola Nordmann"], rows
    payload = {"extra": {"numbers": WEEK_BEFORE}}  # as a writer has it, and as a reader carries it
    for found in (drafts.extra_rows(payload, ""), drafts.extra_rows(drafts.unit_json(payload), "")):
        rows = list(found)
        assert "  with      Kari Nordmann · Ola Nordmann" in rows and beside(rows) == [], rows
    carried = drafts.unit_json(payload)["numbers"]
    assert carried["people"][0]["contacts"] == 12, "the week page computes who moved from it, unprinted"
    assert drafts.names_only(carried)["people"] == [
        {"name": "Kari Nordmann", "id": "e-kari", "lines": ["l1", "l2"]},
        {"name": "Ola Nordmann", "id": "e-ola", "lines": ["l3"]},
    ], "what a reader prints, in text or JSON: no count beside a person, in the draft's order"
    assert WEEK_BEFORE["people"][0]["contacts"] == 12, "the line is never rewritten"


def test_a_call_s_length_and_a_recording_s_talk_time_stand_apart_from_the_name() -> None:
    call = {"who": "Ola Nordmann", "direction": "incoming", "answered": True, "duration_s": 1140}
    assert day_reader.call_text(call) == "19 min ← Ola Nordmann"
    assert day_reader.call_text({**call, "answered": False}) == "← Ola Nordmann, missed"
    assert day_reader.call_text({**call, "duration_s": 45, "direction": "outgoing"}) == "45 s → Ola Nordmann"
    voices = [
        {"label": "S2", "name": "Kari Nordmann", "seconds": 840.0, "person": "e-kari", "basis": "voice"},
        {"label": "mic", "seconds": 1860.0, "owner": True, "basis": "channel"},
        {"label": "S3", "seconds": 60.0, "person": None, "basis": "voice", "consent": "unknown"},
    ]
    text = speakers.json_text(voices)
    assert text == "you · Kari Nordmann and 1 unnamed · recorded with consent: unknown", text
    payload = {
        "speakers": [
            {"label": "S2", "seconds": 40.0, "name": "Ola Nordmann"},
            {"label": "S1", "seconds": 90.0},
        ]
    }
    assert speakers.row_text(payload) == "S1 · Ola Nordmann", "the one who spoke most first, no minutes"


def test_the_digest_s_with_and_the_week_s_paper_say_how_many_away_from_a_name() -> None:
    assert digest._with_text({"confirmed": ["Kari Nordmann"], "proposed": ["Ola Nordmann"]}) == (
        "Kari Nordmann and 1 proposed"
    )
    assert (
        digest._with_text({"confirmed": [], "proposed": ["Ola Nordmann"]}) == "nobody confirmed (1 proposed)"
    )
    page = "\n".join(week_paper._with_page({
        "people": [{"name": "Kari Nordmann"}, {"name": "Ola Nordmann"}], "keepers": [], "week": W25,
        "first": DAYS[7], "last": DAYS[13], "name": "Ines Nordmann", "head": "",
    }))  # fmt: skip
    assert "Kari Nordmann" in page and beside(page) == [], beside(page)


# -- the week, dreamed: its pencil and every reader of it ----------------------------------------------------


def counting(material: dict[str, Any]) -> dict[str, Any]:
    """The week's answer as `dream-week/1`'s example taught: a sentence that puts the count beside the
    person, beside the plausible answer's own sentences."""
    found = week_answer(material)
    person = material["time"]["people"][0]
    found["time"].append(
        {"text": f"{person['contacts']} contacts with {person['name']}.", "evidence": person["ref"][:1]}
    )
    return found


def _extra(lb: Logbook) -> list[dict[str, Any]]:
    """A call with Kari (19 min) and a recording where Kari and the owner speak, in the second week."""
    call = {
        "at": utc(CALL_DAY, "18:00"), "source": "ios-calls", "kind": "call", "tier": 1,
        "payload": {
            "schema": "call/v1", "raw_id": "c-guard", "direction": "incoming", "answered": True,
            "duration_s": 1140, "counterparty": {"kind": "phone", "value": KARI["phone"]},
            "service": "cellular",
        },
    }  # fmt: skip
    recording = {
        "at": utc(RECORDING_DAY, "20:00"), "end": utc(RECORDING_DAY, "20:40"), "source": "granola",
        "kind": "transcript", "tier": 2,
        "payload": {
            "schema": "transcript/v1", "provider": "granola", "raw_id": "t-guard", "title": "Middag",
            "participants": [{"email": OLA["email"], "name": "Ola Nordmann"}],
            "speakers": [
                {"label": "S1", "seconds": 1860.0, "turns": 40, "from_me": True},
                {"label": "S2", "seconds": 840.0, "turns": 22, "name": "Kari Nordmann"},
            ],
        },
    }  # fmt: skip
    return [call, recording]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = fortnight(tmp_path / "lb")
    lb.append_many(_extra(lb))
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date.fromisoformat(MONDAY_AFTER))
    return Logbook(lb.root)


def _week(lb: Logbook) -> dict[str, Any]:
    (line,) = [
        line
        for line in Logbook(lb.root).lines()
        if line["kind"] == drafts.KIND
        and line["payload"]["unit"] == drafts.UNIT_WEEK
        and line["payload"]["subject"] == W25
    ]
    return line


def test_a_week_holds_a_figure_beside_a_person_and_keeps_its_people_by_name_only(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    seen = fake(monkeypatch, week=counting)
    code, out, err = run_cli("dream", "--catch-up")
    assert code in (0, 1) and f"{W25}  dreamed" in out, out + err
    material = seen["weeks"][1]
    assert material["time"]["people"][0]["contacts"], "the model reads the counts, to know who came first"
    payload = _week(lb)["payload"]
    assert payload["extra"]["prompt"] == dream_week.PROMPT_NAME == "dream-week/2"
    assert payload["extra"]["marked"][dream.BESIDE_A_NAME] == 1, payload["extra"]
    texts = [s["text"] for s in payload["segments"]]
    assert dream.HELD in texts and not any("contacts with" in t for t in texts), "its words are dropped"
    people = payload["extra"]["numbers"]["people"]
    assert [p["name"] for p in people] == [p["name"] for p in material["time"]["people"]], "the draft's order"
    assert all(set(p) == set(dream_week.KEPT_PERSON) for p in people), "no count by channel, no days"
    assert people[0]["contacts"] == material["time"]["people"][0]["contacts"], "for the week page's movers"
    chats = [t for t in payload["extra"]["numbers"]["threads"] if t["kind"] == drafts.CHAT]
    assert chats and all("count" not in t for t in chats), "a chat is a person: named without its count"
    prompt = next(p for p in seen["prompts"] if "one week of a personal record" in p)
    assert "Never a number beside a person" in prompt and "4 contacts" not in prompt


def test_no_reader_of_the_week_prints_a_number_beside_a_name(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: list[str]
) -> None:
    fake(monkeypatch, week=counting)
    assert run_cli("dream", "--catch-up")[0] in (0, 1)
    line = _week(lb)
    assert line["payload"]["extra"]["numbers"]["people"], (
        "a week with people, so the readers have some to print"
    )

    code, out, err = run_cli("dream", "week", W25, "--dry-run")  # `dream week`'s text, as it writes one
    assert code == 0 and "  with      " in out and "Kari Nordmann" in out, out + err
    assert beside(out) == [], beside(out)

    days = {}
    for day in DAYS:
        code, out, err = run_cli("day", day)
        assert code == 0, err
        days[day] = out
        assert beside(out) == [], (day, beside(out))
        # `show`'s call row, `← who, 7 min, cellular`, is the conformance fixture's own
        # (conformance/profiles/call/show.txt): the only one left, and only a call's
        pinned = [
            row for row in beside(run_cli("show", day)[1]) if " call " not in row or "ios-calls" not in row
        ]
        assert pinned == [], day
    assert "19 min ← Kari Nordmann" in days[CALL_DAY]
    assert "you · Kari Nordmann" in days[RECORDING_DAY]
    sunday = days[SUNDAY]
    assert f"week {W25}" in sunday and "  with      " in sunday and "contacts" not in sunday, sunday
    data = json.loads(run_cli("day", SUNDAY, "--json")[1])
    people = data["week_draft"]["numbers"]["people"]
    assert people and all(set(p) <= set(drafts.PERSON_KEYS) for p in people), people

    code, out, err = run_cli("show", "trip", "2026-06-16")
    assert code == 0 and "Ola Nordmann" in out, out + err
    assert beside(out) == [], beside(out)

    week = serve.Site(lb).respond(f"/week/{W25}", "")  # the week page: who moved, computed, by name only
    assert week.status == 200
    body = week.body.decode("utf-8")
    assert "against the week before, names only" in body and "Kari Nordmann" in body, "the movers"
    assert beside(body) == [], beside(body)

    page = serve.Site(lb).respond(f"/day/{SUNDAY}", "")
    assert page.status == 200
    body = page.body.decode("utf-8")
    assert f'id="{serve.WEEK}"' in body and beside(body) == [], beside(body)
    for day in (CALL_DAY, RECORDING_DAY):
        assert beside(serve.Site(lb).respond(f"/day/{day}", "").body.decode("utf-8")) == [], day

    crossing = lb.root / "policy" / "crossing.json"  # the week's draft is tier 2: let tier 2 cross
    entries = json.loads(crossing.read_text(encoding="utf-8"))
    crossing.write_text(json.dumps({**entries, "site": {"max_tier": 2}}), encoding="utf-8")
    site = tmp_path / "site"
    code, _out, err = run_cli("export", "site", str(site), "--tier", "1,2", "--with-drafts")
    assert code == 0, err
    pages = [*site.glob("days/*.html"), *site.glob("trips/*.html")]  # the pages a draft's people are on
    assert any(W25 in p.read_text(encoding="utf-8") for p in pages), "the week's draft is on the site"
    for p in pages:
        assert beside(p.read_text(encoding="utf-8")) == [], (p.name, beside(p.read_text(encoding="utf-8")))

    vault = tmp_path / "vault"
    code, _out, err = run_cli("export", "vault", str(vault))
    assert code == 0, err
    notes = [p.read_text(encoding="utf-8") for p in vault.rglob("*.md")]
    assert any("- [[Ola Nordmann]]" in n for n in notes) and beside(notes) == [], beside(notes)

    code, out, err = run_cli("digest", "--paper", "--week", W25)
    assert code == 0 and "Kari Nordmann" in out and beside(out) == [], beside(out) or err
    for day in DAYS:
        assert beside(run_cli("digest", day)[1]) == [], day


def test_a_letter_of_weeks_names_its_people_with_no_number_beside_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = letter_record.record(tmp_path, monkeypatch)
    out = tmp_path / "letter"
    code, _out, err = run_cli("export", "letter", letter_record.FROM, letter_record.TO, "--out", str(out),
                              "--unit", "week")  # fmt: skip
    assert code == 0, err
    for name in (letter.HTML_FILE, letter.MARKDOWN_FILE):
        text = (out / name).read_text(encoding="utf-8")
        assert "Kari Nordmann" in text and beside(text) == [], (name, beside(text))
    assert lb.root.is_dir()
