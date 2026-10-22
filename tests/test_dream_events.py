"""The dream proposes events, and the owner confirms them (`logbook dream day`, `day sign --accept`,
`day reflect --sign --accept`). A stay at a restaurant with two photos and a transcript is a dinner with
the people in it: the dream proposes it inside its `draft/v1` line (`proposals`, kind `event`), never as
an event line; the Day shows it greyed; `--accept` writes it as the `event/v1` line the calendar adapter
would write for the same fields, source `owner`, `extra.from` the draft's id, through the writer lock the
signature takes. Nothing is written without `--accept`. The model is an in-process fake; no test opens a
connection. Synthetic Oslo persona, who does not exist; example.org addresses; a place invented here."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from persona import CAFE, HOME, KARI, KARI_ID, OLA, OLA_ID, dwell, photo, resolution, transcript, travel, utc

from logbook import cli
from logbook.commands import day as day_command
from logbook.contrib import dream, model_client, serve
from logbook.contrib.adapters import ics
from logbook.core import day as day_reader
from logbook.core import drafts, policy
from logbook.core.chain import canonical_json
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-06-10"  # a Wednesday, CEST
MODEL = "qwen2.5-7b-instruct"
ENV = {model_client.ENDPOINT_ENV: "http://127.0.0.1:8080/v1", model_client.MODEL_ENV: MODEL}
BISTRO = "Bistro Eksempel"  # invented: a restaurant at the persona's cafe coordinates
TITLE = "Dinner with Kari Nordmann"
SIGNED_AT = "2026-06-10T23:30:00+02:00"
CONTENT = ("at", "end", "tz", "source", "kind", "tier", "payload")


def _drafts() -> list[dict[str, Any]]:
    """A day at home, then the evening at the bistro: two photos there and a recording Kari spoke in."""
    found: list[dict[str, Any]] = [
        resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
    ]
    found += dwell(DAY, "07:00", "18:30", HOME, every_min=20)
    found += travel(DAY, "18:30", "19:25", HOME, CAFE)
    found += dwell(DAY, "19:30", "22:10", CAFE, every_min=5, noise_m=15)
    found += travel(DAY, "22:10", "22:40", CAFE, HOME)
    found += dwell(DAY, "22:40", "23:55", HOME, every_min=20)
    found.append(photo(utc(DAY, "20:05"), CAFE))
    found.append(photo(utc(DAY, "21:15"), CAFE))
    found.append(
        transcript(
            utc(DAY, "19:40"),
            utc(DAY, "22:00"),
            "Dinner",
            [{"name": "Kari Nordmann", "email": KARI["email"]}],
        )
    )
    return found


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: False)
    lb.append_many(_drafts())
    (lb.root / "places.json").write_text(
        json.dumps(
            {
                "Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"},
                BISTRO: {"lat": CAFE[0], "lon": CAFE[1], "radius_m": 80},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    policy.policy_path(lb.root).write_text(
        json.dumps(
            {"mcp": {"max_tier": 1}, policy.DREAM_DESTINATION: {"max_tier": 2, "until": "2026-12-31"}}
        ),
        encoding="utf-8",
    )
    return lb


def _answer(
    material: dict[str, Any], people: Callable[[list[str]], list[str]] | None = None
) -> dict[str, Any]:
    """A plausible answer read from the material alone: a day segment and two questions, and one event
    for each stay with photos and a recording, at the stay's place and span, with the people confirmed
    there, resting on the stay, the photos and the recording."""
    refs = [r for e in material["timeline"] for r in e["ref"]]
    events = []
    for entry in material["timeline"]:
        if not (entry.get("photos") and entry.get("transcripts")):
            continue
        who = [c["person"] for c in entry["with"]["confirmed"] if c.get("person")]
        events.append(
            {
                "title": TITLE,
                "start": entry["start"],
                "end": entry["end"],
                "place": entry["place"],
                "people": people(who) if people else who,
                "evidence": [
                    *entry["ref"],
                    *entry["photos"]["ref"],
                    *(r for t in entry["transcripts"] for r in t["ref"]),
                ],
            }
        )
    return {
        "story": [{"text": "A day at home, then dinner out.", "evidence": refs[:2]}],
        "threads": [{"text": "The dinner plans came to the table.", "evidence": refs[:1]}],
        "questions": [{"text": "What did you talk about at dinner?", "evidence": refs[:1]}],
        "people": [],
        "promises": [],
        "events": events,
    }


def _fake(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[dict[str, Any]], Any] | None = None
) -> dict[str, Any]:
    seen: dict[str, Any] = {"calls": []}

    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        seen["calls"].append(body)
        seen["prompt"] = body["messages"][0]["content"]
        seen["material"] = json.loads(body["messages"][1]["content"])
        return {"choices": [{"message": {"content": json.dumps((answer or _answer)(seen["material"]))}}]}

    monkeypatch.setattr(model_client, "send", send)
    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)
    return seen


def _cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()


def _of_kind(lb: Logbook, kind: str) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == kind]


def _files(root: Path) -> dict[Path, bytes]:
    return {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file() and "state" not in p.parts
    }


def _dreamed(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _fake(monkeypatch)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    return _of_kind(lb, drafts.KIND)[-1]


def _bistro(data: dict[str, Any]) -> dict[str, Any]:
    return next(e for e in data["timeline"] if e.get("place") == BISTRO)


# -- the dream proposes ----------------------------------------------------------------------------------


def test_a_stay_with_photos_and_a_transcript_yields_one_proposed_event(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = _fake(monkeypatch)
    seq = lb.meta["seq"]
    code, out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    # the material names the places and the people by id, the only ids a proposal may hold
    material = seen["material"]
    assert {"id": KARI_ID, "name": "Kari Nordmann"} in material["people"]
    places = [e.get("place") for e in material["timeline"] if e["kind"] == "stay"]
    assert BISTRO in places and "Home" in places
    assert '"events"' in seen["prompt"] and "never a name" in seen["prompt"]
    (line,) = _of_kind(lb, drafts.KIND)
    assert lb.meta["seq"] == seq + 1 and _of_kind(lb, "event") == []  # a proposal, never an event line
    p = line["payload"]
    assert p["extra"]["prompt"] == dream.PROMPT_NAME and drafts.validate(p) == []
    (proposal,) = p["proposals"]
    stay = _bistro(day_reader.read(lb, DAY))
    with lb.index() as idx:
        on_day = {str(x["id"]): x for x in idx.day(DAY)}
    photos = [i for i, x in on_day.items() if x["kind"] == "photo"]
    (recording,) = [i for i, x in on_day.items() if x["kind"] == "transcript"]
    assert proposal == {
        "kind": "event",
        "title": TITLE,
        "start": stay["start"],
        "end": stay["end"],
        "place": BISTRO,
        "people": [KARI_ID],
        "evidence": proposal["evidence"],
    }
    assert set(photos) | {recording} <= set(proposal["evidence"]) <= set(on_day)
    assert "dropped" not in p["extra"]
    assert "1 proposed event" in out and f"event 1   {stay['start_local'][11:16]}" in out
    assert TITLE in out and "with Kari Nordmann" in out


def test_a_proposal_with_an_unresolved_person_is_dropped_and_counted(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(material: dict[str, Any]) -> dict[str, Any]:
        found = _answer(material, people=lambda _who: ["Kari Nordmann"])  # a name, not an id
        owner = _answer(material, people=lambda _who: [lb.meta["owner_id"]])  # the owner is no one's company
        found["events"] += owner["events"]
        return found

    _fake(monkeypatch, answer)
    code, out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    (line,) = _of_kind(lb, drafts.KIND)
    p = line["payload"]
    assert "proposals" not in p and p["extra"]["dropped"] == {dream.DROP_PERSON: 2}
    assert len(p["segments"]) == 3  # the draft itself is written
    assert f"2 proposed events dropped: {dream.DROP_PERSON} 2" in out
    assert _of_kind(lb, "event") == []


def test_a_proposal_must_rest_on_the_day_and_be_at_a_place_of_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(material: dict[str, Any]) -> dict[str, Any]:
        found = _answer(material)
        (event,) = found["events"]
        found["events"] = [
            {**event, "evidence": ["L999"]},
            {**event, "place": "place:48.8566,2.3522"},
            {**event, "start": "2026-06-11T19:30:00+02:00"},
            {**event, "title": " "},
            event,
        ]
        return found

    _fake(monkeypatch, answer)
    assert _cli("dream", "day", DAY)[0] == 0
    p = _of_kind(lb, drafts.KIND)[-1]["payload"]
    assert len(p["proposals"]) == 1
    assert p["extra"]["dropped"] == {
        dream.DROP_EVIDENCE: 1,
        dream.DROP_PLACE: 1,
        dream.DROP_TIME: 1,
        dream.DROP_TITLE: 1,
    }


def test_a_malformed_proposal_makes_the_draft_invalid() -> None:
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": "0" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": "A day.", "unsupported": True}],
        "proposals": [{"kind": "event", "title": "Dinner", "start": "19:30", "end": None, "evidence": []}],
    }
    assert drafts.validate(payload) == ["proposal 1 is malformed: " + drafts.NOT_A_PROPOSAL]


# -- forward compatibility (draft/v1, 19 Oct 2026) -------------------------------------------------------

# a kind of later: `link` was the example until draft/v1 amendment 2 made it known (dream-day/4)
LATER = {"kind": "reminder", "from": "idea:boat-share-log", "to": KARI_ID, "evidence": ["x"]}


def _with_proposals(lb: Logbook, *proposals: dict[str, Any]) -> dict[str, Any]:
    """A note on the day and a draft whose proposals rest on it: an event, then whatever is given."""
    at = utc(DAY, "20:00")
    note = lb.append(at, "manual", "note", 1, {"schema": "note/v1", "text": "Dinner at the bistro."})
    dinner = {
        "kind": "event",
        "title": "Dinner",
        "start": utc(DAY, "19:30"),
        "end": utc(DAY, "22:00"),
        "place": None,
        "people": [],
        "evidence": [str(note["id"])],
    }
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": lb.meta["head"],
        "read_count": 1,
        "language": "en",
        "segments": [{"text": "Dinner at the bistro.", "evidence": [str(note["id"])]}],
        "proposals": [dinner, *proposals],
    }
    return payload


def test_a_reader_counts_a_proposal_of_an_unknown_kind_and_shows_the_event(lb: Logbook) -> None:
    payload = _with_proposals(lb, LATER)
    assert drafts.validate(payload, reader=True) == []  # a reader: not malformed
    lb.append(utc(DAY, "23:00"), "model:x", "draft", 1, payload)  # written by a writer that knows `reminder`
    draft = day_reader.read(lb, DAY)["draft"]
    (shown,) = draft["proposals"]
    assert shown["number"] == 1 and shown["kind"] == "event" and shown["title"] == "Dinner"
    assert draft["proposals_unknown"] == 1 and draft["malformed"] == []
    _code, out, _err = _cli("day", DAY, "--no-anniversaries")
    assert "? event 1" in out and "malformed" not in out


def test_a_writer_still_refuses_a_proposal_of_a_kind_it_does_not_know(lb: Logbook) -> None:
    payload = _with_proposals(lb, LATER)
    refused = f"proposal 2 is of a kind this writer does not know: {LATER['kind']!r}"
    assert drafts.validate(payload) == [refused]
    with pytest.raises(dream.AnswerError, match="nothing was written"):
        dream.valid(payload)


def test_a_malformed_event_beside_an_unknown_kind_is_still_malformed(lb: Logbook) -> None:
    broken = {"kind": "event", "title": "Dinner", "start": "19:30", "end": None, "evidence": []}
    payload = _with_proposals(lb, LATER, broken)
    assert drafts.validate(payload, reader=True) == ["proposal 3 is malformed: " + drafts.NOT_A_PROPOSAL]
    lb.append(utc(DAY, "23:00"), "model:x", "draft", 1, payload)
    draft = day_reader.read(lb, DAY)["draft"]
    assert [p["number"] for p in draft["proposals"]] == [1] and draft["proposals_unknown"] == 1
    assert draft["malformed"] == ["proposal 3 is malformed: " + drafts.NOT_A_PROPOSAL]
    assert "malformed" in _cli("day", DAY, "--no-anniversaries")[1]


def test_a_proposal_with_no_kind_is_malformed_not_unknown(lb: Logbook) -> None:
    payload = _with_proposals(lb, {"title": "Dinner"})
    assert drafts.validate(payload, reader=True) == ["proposal 2 is malformed: " + drafts.NOT_A_PROPOSAL]
    lb.append(utc(DAY, "23:00"), "model:x", "draft", 1, payload)
    draft = day_reader.read(lb, DAY)["draft"]
    assert draft["proposals_unknown"] == 0 and draft["malformed"]


# -- nothing written without --accept --------------------------------------------------------------------


def test_nothing_is_written_without_accept(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    _dreamed(lb, monkeypatch)
    before = _files(lb.root)
    for args in (
        ("day", DAY, "--no-anniversaries"),
        ("day", DAY, "--json"),
        ("day", "reflect", DAY, "--text", "A good dinner.", "--dry-run"),
        ("day", "reflect", DAY, "--text", "A good dinner.", "--sign", "--accept", "1", "--dry-run"),
    ):
        code, _out, err = _cli(*args)
        assert code == 0, err
    assert _files(lb.root) == before
    code, out, err = _cli("day", "reflect", DAY, "--text", "A good dinner.", "--sign", "--at", SIGNED_AT)
    assert code == 2 and "--accept" in err and "nothing was written" in err
    assert "proposed events, from the dream" in out and "    1  event      " in out
    assert _files(lb.root) == before
    serve.Site(lb).page_day(DAY)
    assert _files(lb.root) == before
    code, out, err = _cli("day", "sign", DAY, "--at", SIGNED_AT)
    assert code == 0, err
    assert [line["kind"] for line in lb.lines()][-1] == "signed-day" and _of_kind(lb, "event") == []
    assert TITLE in out and f"logbook day sign {DAY} --accept N" in out


def test_an_unknown_number_and_confirm_none_are_refused_before_anything_is_written(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _dreamed(lb, monkeypatch)
    before = _files(lb.root)
    code, _out, err = _cli("day", "sign", DAY, "--accept", "2")
    assert code == 2 and "no proposed event 2" in err
    code, _out, err = _cli("day", "sign", DAY, "--accept", "1", "--confirm", "none")
    assert code == 2 and "--confirm none" in err
    code, _out, err = _cli("day", "sign", DAY, "--accept", "one")
    assert code == 2 and "'one'" in err
    assert _files(lb.root) == before


def test_a_day_without_a_dream_has_nothing_to_accept(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    before = _files(lb.root)
    code, _out, err = _cli("day", "sign", DAY, "--accept", "1")
    assert code == 2 and "no proposed event 1" in err and _files(lb.root) == before


# -- --accept writes the line ----------------------------------------------------------------------------


def _ics_line(draft_id: str, start: str, end: str) -> dict[str, Any]:
    """What the calendar adapter writes for the proposal's fields, a calendar named `logbook`."""
    zone = ZoneInfo(TZ)

    def local(stamp: str) -> str:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(zone).strftime("%Y%m%dT%H%M%S")

    text = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "X-WR-CALNAME:logbook",
            "BEGIN:VEVENT",
            f"UID:{draft_id}/1",
            f"DTSTART;TZID={TZ}:{local(start)}",
            f"DTEND;TZID={TZ}:{local(end)}",
            f"SUMMARY:{TITLE}",
            f"LOCATION:{BISTRO}",
            f"GEO:{CAFE[0]};{CAFE[1]}",
            f"ATTENDEE;CN=Kari Nordmann;PARTSTAT=ACCEPTED:mailto:{KARI['email']}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    (line,) = ics.lines(text, "logbook", timezone=TZ)
    return line


def test_accept_writes_the_line_byte_for_byte_as_the_calendar_adapter_would(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    draft = _dreamed(lb, monkeypatch)
    proposal = draft["payload"]["proposals"][0]
    seq = lb.meta["seq"]
    code, out, err = _cli("day", "sign", DAY, "--accept", "1", "--at", SIGNED_AT)
    assert code == 0, err
    event, signature = lb.line_by_seq(seq + 1), lb.line_by_seq(seq + 2)
    assert event is not None and signature is not None and lb.meta["seq"] == seq + 2
    expected = _ics_line(str(draft["id"]), proposal["start"], proposal["end"])
    expected["source"] = "owner"
    expected["payload"]["extra"]["from"] = draft["id"]
    assert canonical_json({k: event[k] for k in CONTENT}) == canonical_json({k: expected[k] for k in CONTENT})
    assert (event["kind"], event["tier"], event["source"]) == ("event", 1, "owner")
    assert event["payload"]["raw_id"] == f"{draft['id']}/1"
    assert signature["kind"] == "signed-day" and event["id"] in signature["payload"]["confirmed"]
    assert f"wrote proposed event 1 as #{seq + 1} event/v1 (source owner, tier 1)" in out
    assert lb.verify()[2] == []
    # once is enough: the same proposal again is refused, and nothing is written
    before = _files(lb.root)
    code, _out, err = _cli("day", "sign", DAY, "--accept", "1")
    assert code == 2 and f"confirmed already as #{seq + 1}" in err and _files(lb.root) == before


def test_reflect_numbers_the_events_after_its_own_proposals_and_accepts_one(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _dreamed(lb, monkeypatch)
    seq = lb.meta["seq"]
    text = "Ola should book the ferry for Sunday."  # proposal 1, a delegation; the dinner is 2
    code, out, err = _cli("day", "reflect", DAY, "--text", text, "--sign", "--accept", "2", "--at", SIGNED_AT)
    assert code == 0, err
    assert "    1  delegation" in out and "    2  event      " in out
    kinds = [line["kind"] for line in lb.lines()][seq:]
    assert kinds == ["note", "event", "signed-day"]  # the reflection, the dinner, the signature
    event = _of_kind(lb, "event")[-1]
    assert event["source"] == "owner" and event["payload"]["title"] == TITLE
    assert event["id"] in _of_kind(lb, "signed-day")[-1]["payload"]["confirmed"]


def test_accept_refuses_a_proposal_whose_evidence_left_the_page(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    draft = _dreamed(lb, monkeypatch)
    recording = next(
        line
        for line in lb.lines()
        if line["kind"] == "transcript" and line["id"] in draft["payload"]["proposals"][0]["evidence"]
    )
    lb.retract(int(recording["seq"]), "not that evening")
    before = _files(lb.root)
    code, _out, err = _cli("day", "sign", DAY, "--accept", "1")
    assert code == 2 and "no longer on the page" in err and _files(lb.root) == before


# -- the Day ---------------------------------------------------------------------------------------------


def test_the_day_shows_a_proposed_event_greyed_and_a_confirmed_one_as_an_event(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    draft = _dreamed(lb, monkeypatch)
    data = day_reader.read(lb, DAY)
    (proposed,) = data["draft"]["proposals"]
    assert proposed["number"] == 1 and proposed["confirmed"] is None and proposed["supported"] is True
    assert proposed["people"] == [{"id": KARI_ID, "name": "Kari Nordmann"}] and proposed["where"] == BISTRO
    assert all(e["title"] != TITLE for e in _bistro(data)["attached"]["events"])
    _code, out, _err = _cli("day", DAY, "--no-anniversaries")
    row = next(r for r in out.splitlines() if TITLE in r)
    assert row.lstrip().startswith("? event 1") and row.endswith("]") and "proposed" in row
    html = serve.Site(lb).page_day(DAY)
    assert 'class="proposal proposed mute"' in html and TITLE in html
    assert html.index(TITLE) < html.index("<h2>Timeline</h2>")

    seq = lb.meta["seq"]
    assert _cli("day", "sign", DAY, "--accept", "1", "--at", SIGNED_AT)[0] == 0
    event = lb.line_by_seq(seq + 1)
    assert event is not None
    data = day_reader.read(lb, DAY)
    (confirmed,) = data["draft"]["proposals"]
    assert confirmed["confirmed"] == {"line": event["id"], "seq": seq + 1}
    bistro = _bistro(data)
    assert [e["title"] for e in bistro["attached"]["events"]] == [TITLE]  # an event of the record now
    kari = next(c for c in bistro["with"]["confirmed"] if c["person"] == KARI_ID)
    assert "calendar" in kari["sources"]  # the confirmed event places her, as a calendar entry would
    _code, out, _err = _cli("day", DAY, "--no-anniversaries")
    assert f"confirmed as #{seq + 1}" in out and "? event 1" not in out
    assert any(r.strip().startswith("event") and TITLE in r and "19:" in r for r in out.splitlines())
    html = serve.Site(lb).page_day(DAY)
    assert 'class="proposal proposed mute"' not in html and 'class="proposal confirmed"' in html
    assert f'<span class="kind">event</span> {TITLE}' in html
    assert str(draft["id"]) == event["payload"]["extra"]["from"]


# -- the policy ------------------------------------------------------------------------------------------

EVENING = "Evening at the bistro"


def _entry(lb: Logbook, max_tier: int) -> None:
    """The `dream` entry of the crossing policy as the owner edits it: no line is appended, the head
    does not move, and the readers hold every draft against the entry as it is now."""
    policy.policy_path(lb.root).write_text(
        json.dumps(
            {"mcp": {"max_tier": 1}, policy.DREAM_DESTINATION: {"max_tier": max_tier, "until": "2026-12-31"}}
        ),
        encoding="utf-8",
    )


def _photos_only(material: dict[str, Any]) -> dict[str, Any]:
    """The answer of a dream that read no recording (a tier-2 line, above an entry at 1): the evening
    proposed from the bistro stay and its photos alone, naming no one."""
    answer = _answer(material)
    entry = next(e for e in material["timeline"] if e.get("place") == BISTRO)
    answer["events"] = [
        {
            "title": EVENING,
            "start": entry["start"],
            "end": entry["end"],
            "place": BISTRO,
            "people": [],
            "evidence": [*entry["ref"], *entry["photos"]["ref"]],
        }
    ]
    return answer


def test_a_draft_the_policy_withholds_withholds_its_proposed_events_with_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    draft = _dreamed(lb, monkeypatch)
    assert draft["tier"] == 2 and draft["payload"]["proposals"]  # it read the recording, a tier-2 line
    _entry(lb, 1)
    out = _cli("day", DAY, "--no-anniversaries")[1]
    assert TITLE not in out and "? event" not in out
    (row,) = [r for r in out.splitlines() if r.startswith("  draft ")]
    assert "superseded by policy" in row
    raw = _cli("day", DAY, "--json", "--no-anniversaries")[1]
    data = json.loads(raw)
    assert "draft" not in data and data["draft_withheld"]["line"] == draft["id"] and TITLE not in raw
    assert "draft" not in day_reader.read(lb, DAY, tiers=(1, 2, 3))  # a gated reader: not a word
    html = serve.Site(lb).page_day(DAY)
    assert TITLE not in html and 'class="proposal' not in html and "superseded by policy" in html

    # not listed, so not to be accepted: refused with the reason, and nothing is written
    before = _files(lb.root)
    code, out, err = _cli("day", "sign", DAY, "--accept", "1")
    assert code == 2 and "no proposed event 1" in err and "superseded by policy" in err
    assert TITLE not in out and _files(lb.root) == before
    code, out, _err = _cli("day", "reflect", DAY, "--text", "A quiet evening.", "--dry-run")
    assert code == 0 and TITLE not in out and "proposed events" not in out
    code, _out, err = _cli("day", "reflect", DAY, "--text", "A quiet evening.", "--sign", "--accept", "1")
    assert code == 2 and "no proposal 1" in err and "superseded by policy" in err
    assert _files(lb.root) == before and _of_kind(lb, "event") == []
    code, out, err = _cli("day", "sign", DAY, "--at", SIGNED_AT)  # the day signs; nothing is offered
    assert code == 0, err
    assert TITLE not in out and "proposed event" not in out and _of_kind(lb, "event") == []


def test_the_draft_the_policy_still_allows_stands_in_with_its_own_proposed_events(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _entry(lb, 1)
    _fake(monkeypatch, _photos_only)
    assert _cli("dream", "day", DAY)[0] == 0
    _entry(lb, 2)
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    first, second = _of_kind(lb, drafts.KIND)
    assert (first["tier"], second["tier"]) == (1, 2) and second["payload"]["supersedes"] == first["id"]
    assert [p["title"] for p in day_reader.read(lb, DAY)["draft"]["proposals"]] == [TITLE]

    _entry(lb, 1)  # the standing draft is withheld; the earlier one, which the entry allows, is shown
    data = day_reader.read(lb, DAY)
    assert data["draft"]["line"] == first["id"] and data["draft_withheld"]["line"] == second["id"]
    assert [p["title"] for p in data["draft"]["proposals"]] == [EVENING]
    out = _cli("day", DAY, "--no-anniversaries")[1]
    assert TITLE not in out
    assert any(r.lstrip().startswith("? event 1") and EVENING in r for r in out.splitlines())
    html = serve.Site(lb).page_day(DAY)
    assert TITLE not in html and 'class="proposal proposed mute"' in html and EVENING in html

    seq = lb.meta["seq"]
    code, out, err = _cli("day", "sign", DAY, "--accept", "1", "--at", SIGNED_AT)
    assert code == 0, err
    assert TITLE not in out and f"wrote proposed event 1 as #{seq + 1} event/v1" in out
    event = lb.line_by_seq(seq + 1)
    assert event is not None and event["kind"] == "event" and event["payload"]["title"] == EVENING
    assert event["payload"]["extra"]["from"] == first["id"]  # the draft that was shown, not the withheld one
    (confirmed,) = day_reader.read(lb, DAY)["draft"]["proposals"]
    assert confirmed["confirmed"] == {"line": event["id"], "seq": seq + 1}


def test_an_event_confirmed_from_a_draft_the_policy_later_withholds_stays_in_the_record(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    draft = _dreamed(lb, monkeypatch)
    seq = lb.meta["seq"]
    assert _cli("day", "sign", DAY, "--accept", "1", "--at", SIGNED_AT)[0] == 0
    event = lb.line_by_seq(seq + 1)
    assert event is not None and event["tier"] == 1 and event["source"] == "owner"
    _entry(lb, 1)
    data = day_reader.read(lb, DAY)
    assert "draft" not in data and data["draft_withheld"]["line"] == draft["id"]
    # the proposal and its `confirmed as` row go with the draft; the event is the owner's line and stays
    assert [e["title"] for e in _bistro(data)["attached"]["events"]] == [TITLE]
    out = _cli("day", DAY, "--no-anniversaries")[1]
    assert f"confirmed as #{seq + 1}" not in out and "? event" not in out
    assert any(r.strip().startswith("event") and TITLE in r for r in out.splitlines())
