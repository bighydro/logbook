"""dream-day/4, the dream learns (RFC 0043 slice B): the goodnight story with the reader's closing line,
one answer per lens, what was learned and decided, the ideas the day moved, the photo of the day, one
question, the proposed links (`draft/v1` amendment 2), `dream day TODAY --evening`, and the re-dream
rules of RFC 0043 §6 (kept lines never re-dream a day; after a signature only a later line does; a signed
day with none never). The model is an in-process fake of an OpenAI-compatible server (`model_client.send`
replaced); no test opens a connection (`no_network`). Synthetic Oslo persona, who does not exist: Kari
Nordmann, the yacht Solvind, the idea "Boat-share log", the chapter "The Fjord Summer"."""

from __future__ import annotations

import contextlib
import html
import io
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, KARI, KARI_ID, dwell, event, note, photo, resolution, utc
from test_day_rhythm import _seen, beside

from logbook import cli
from logbook.contrib import day_rhythm, dream, entities, model_client, questions, serve
from logbook.core import chapter, drafts, goals, policy, signing, stars
from logbook.core.store import Logbook

DAY, NEXT, AFTER = "2026-06-10", "2026-06-11", "2026-06-12"
MODEL = "qwen2.5-7b-instruct"
ENV = {model_client.ENDPOINT_ENV: "http://127.0.0.1:8080/v1", model_client.MODEL_ENV: MODEL}
IDEA_ID = "019cadd3-6bc0-7dcd-9133-0000000000a1"
ORG_ID = "019cadd3-6bc0-7dcd-9133-0000000000a2"
TALLY_ID = "019cadd3-6bc0-7dcd-9133-0000000000a3"  # an idea the record never named
LENSES = [
    {"id": "boat", "text": "What did the boat teach you?", "ask": "day"},
    {"id": "money", "text": "Where did the money go?", "ask": "day"},
]
NOTE_TEXT = "Wrote the crew list for the boat-share log; Kari Nordmann will sail on Saturday."
Answer = Callable[[dict[str, Any]], dict[str, Any]]


def _record() -> list[dict[str, Any]]:
    """A day at home with a note, two photos (one received, one from the owner's camera), and the
    next day with two timed calendar entries and a note."""
    found: list[dict[str, Any]] = [resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann")]
    found += dwell(DAY, "08:00", "20:00", HOME, every_min=20)
    found.append(note(utc(DAY, "12:30"), NOTE_TEXT))
    received = photo(utc(DAY, "10:00"), HOME)
    received["payload"]["provenance"] = "received"
    found += [received, photo(utc(DAY, "15:00"), HOME), photo(utc(DAY, "17:00"), HOME)]
    found += dwell(NEXT, "08:00", "18:00", HOME, every_min=30)
    found.append(note(utc(NEXT, "19:00"), "A quiet evening at home."))
    found += [
        event(utc(AFTER, "09:00"), utc(AFTER, "10:00"), "Harbour office"),
        event(utc(AFTER, "13:00"), utc(AFTER, "14:00"), "Sail repair"),
        event(utc(NEXT, "09:00"), utc(NEXT, "09:30"), "Dentist"),
        event(utc(NEXT, "11:00"), utc(NEXT, "12:00"), "Harbour office"),
    ]
    return found


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    lb.append_many(_record())
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    _policy(lb, 2)
    for kind, entity_id, label in (
        (entities.IDEA, IDEA_ID, "Boat-share log"),
        (entities.ORG, ORG_ID, "Solvind Club"),
    ):
        lb.append(
            "2026-06-01T08:00:00Z",
            "manual",
            entities.ENTITY,
            2,
            entities.entity_payload(kind, entity_id, label),
        )
    monkeypatch.setattr(goals, "now", lambda: datetime(2026, 6, 1, 8, tzinfo=UTC))
    goals.add(lb, "Sail to Lofoten and back", "year", start="2026-01-01")
    chapter.open_chapter(lb, "The Fjord Summer", start="2026-06-01", rules="Sail when the wind allows.")
    path = questions.questions_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"questions": LENSES}), encoding="utf-8")
    return lb


def _policy(lb: Logbook, max_tier: int) -> None:
    data = {policy.DREAM_DESTINATION: {"max_tier": max_tier, "until": "2026-12-31"}, "mcp": {"max_tier": 1}}
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")


def _refs(material: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    stays = [r for e in material["timeline"] for r in e["ref"]]
    notes_ = [n["ref"] for n in material["notes"]]
    photos = [p["ref"][0] for p in material["photos"]]
    return stays, notes_ or stays, photos


def _answer(material: dict[str, Any], **parts: Any) -> dict[str, Any]:
    """A dream-day/4 answer from the material; `parts` override."""
    stays, notes_, photos = _refs(material)
    found: dict[str, Any] = {
        "story": [
            {"text": "You spent the day at home.", "evidence": stays[:1]},
            {"text": "You wrote the crew list.", "evidence": notes_[:1]},
        ],
        "lens:boat": [
            {"text": "The crew list is ready for Saturday; this is an inference.", "evidence": notes_[:1]}
        ],
        "lens:money": [],
        "threads": [],
        "learned": [{"text": "A crew list helps the boat-share log.", "evidence": notes_[:1]}],
        "decision": [{"text": "Kari Nordmann sails on Saturday.", "evidence": notes_[:1]}],
        "ideas": [{"text": "The boat-share log moved on.", "evidence": notes_[:1], "entity": IDEA_ID}],
        "questions": [{"text": "Who else sails on Saturday?", "evidence": notes_[:1]}],
        "people": [],
        "promises": [],
        "photo": [{"text": "The only photo of the afternoon light.", "evidence": photos[:1]}]
        if photos
        else [],
        "events": [],
        "links": [{"entity": IDEA_ID, "text": "Crew list", "evidence": notes_[:1]}],
    }
    found.update(parts)
    return found


def _fake(monkeypatch: pytest.MonkeyPatch, answer: Answer | None = None) -> dict[str, Any]:
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


def _drafts(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == drafts.KIND]


def _day_json(day: str = DAY) -> dict[str, Any]:
    code, out, err = _cli("day", day, "--json", "--no-anniversaries")
    assert code == 0, err
    return json.loads(out)


def _today(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    monkeypatch.setattr(dream, "date", type("D", (), {"today": staticmethod(lambda: day)}))


# -- the material ------------------------------------------------------------------------------------------


def test_the_material_gives_the_chapter_the_open_goals_the_named_ideas_and_orgs_the_photos_and_the_lenses(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = _fake(monkeypatch)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 0, err and no_network == []
    m = seen["material"]
    assert set(m["for"]) == {"chapter", "goals"} and "chapter" not in m and "goals" not in m
    assert m["for"]["chapter"] == {
        "name": "The Fjord Summer",
        "rules": "Sail when the wind allows.",
        "from": "2026-06-01",
        "to": None,
    }
    (goal,) = m["for"]["goals"]
    assert goal["text"] == "Sail to Lofoten and back" and goal["id"] in {line["id"] for line in lb.lines()}
    assert m["named"] == [
        {"id": IDEA_ID, "kind": "idea", "name": "Boat-share log"},
        {"id": ORG_ID, "kind": "org", "name": "Solvind Club"},
    ]
    assert m["lenses"] == [
        {"id": "boat", "text": LENSES[0]["text"]},
        {"id": "money", "text": LENSES[1]["text"]},
    ]
    assert [(p["at"], p["provenance"], p["starred"]) for p in m["photos"]] == [
        ("15:00", "camera", False),
        ("17:00", "camera", False),
        ("10:00", "received", False),
    ], "the owner's own camera first"
    assert "- `lens:<id>`" in seen["prompt"] and "- `story`:" in seen["prompt"]


def test_a_starred_photo_comes_first_among_the_owners_own(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    late = next(line for line in lb.lines() if line["kind"] == "photo" and line["at"] == utc(DAY, "17:00"))
    stars.star(lb, str(late["id"]), "the light")
    seen = _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    assert [(p["at"], p["starred"]) for p in seen["material"]["photos"]] == [
        ("17:00", True),
        ("15:00", False),
        ("10:00", False),
    ]


def test_under_max_tier_1_no_chapter_goal_note_or_named_entity_reaches_the_prompt(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _policy(lb, 1)
    seen = _fake(monkeypatch, lambda m: {"story": [{"text": "A day at home.", "evidence": _refs(m)[0][:1]}]})
    assert _cli("dream", "day", DAY)[0] == 0
    m = seen["material"]
    assert m["for"] == {"chapter": None, "goals": []} and m["named"] == [] and m["notes"] == []
    text = json.dumps(m)
    for word in ("Fjord Summer", "Lofoten", "Boat-share", "Solvind Club", "crew list"):
        assert word not in text


# -- the parts ----------------------------------------------------------------------------------------------


def test_every_new_part_is_a_segment_with_evidence_and_the_day_json_carries_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _fake(monkeypatch)
    code, out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    (line,) = _drafts(lb)
    p = line["payload"]
    assert p["extra"]["prompt"] == "dream-day/4" and drafts.validate(p) == []
    assert p["extra"]["parts"] == [
        "story",
        "story",
        "lens:boat",
        "learned",
        "decision",
        "ideas",
        "questions",
        "photo",
    ]
    assert all("evidence" in s for s in p["segments"]), "every new part is evidenced as every segment is"
    assert p["extra"]["lenses"] == [
        {"id": "boat", "text": LENSES[0]["text"]},
        {"id": "money", "text": LENSES[1]["text"]},
    ]
    assert p["extra"]["ideas"] == [{"segment": 6, "entity": IDEA_ID}]
    draft = _day_json()["draft"]
    assert [s["part"] for s in draft["segments"]] == p["extra"]["parts"]
    assert draft["segments"][5]["entity"] == IDEA_ID
    assert draft["lenses"] == [
        {"id": "boat", "text": LENSES[0]["text"], "answered": True},
        {"id": "money", "text": LENSES[1]["text"], "answered": False},
    ]
    assert draft["evening"] is False and draft["read_until"] is None and draft["since_signed"] is False
    (link,) = draft["links"]
    assert (
        link["number"] == 1
        and link["entity"] == IDEA_ID
        and link["text"] == "Crew list"
        and link["kept"] is None
    )
    assert draft["proposals"] == [] and draft["proposals_unknown"] == 0
    assert "? link 1    Crew list  proposed" in out and f"lens:money {drafts.NO_ANSWER}" in out


def test_the_story_closing_line_is_the_readers_never_the_models(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The last line of the story is computed from tomorrow's timed entries by the reader; the model is
    told never to write it, and a seventh sentence is dropped and counted."""
    story = [{"text": f"Sentence {w}.", "evidence": ["L1"]} for w in ("A", "B", "C", "D", "E", "F", "G")]
    seen = _fake(monkeypatch, lambda m: _answer(m, story=[{**s, "evidence": _refs(m)[0][:1]} for s in story]))
    code, out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    p = _drafts(lb)[0]["payload"]
    assert p["extra"]["parts"].count("story") == 6
    assert p["extra"]["dropped_segments"][dream.DROP_STORY] == 1
    assert "Tomorrow" not in json.dumps(p) and "never a closing line about tomorrow" in seen["prompt"].lower()
    draft = _day_json()["draft"]
    assert draft["closing"]["text"] == "Tomorrow: two entries, the first at 09:00."
    assert draft["closing"]["entries"] == 2 and draft["closing"]["day"] == NEXT
    rows = _cli("day", DAY, "--no-anniversaries")[1].splitlines()
    six = next(i for i, r in enumerate(rows) if "Sentence F." in r)
    assert rows[six + 1].strip() == "Tomorrow: two entries, the first at 09:00."
    assert "Tomorrow: two entries" in out  # the dream's own output computes it too
    assert _day_json(NEXT).get("draft") is None


def test_a_lens_is_answered_once_and_an_unanswered_lens_is_the_readers_words(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(m: dict[str, Any]) -> dict[str, Any]:
        notes_ = _refs(m)[1]
        return _answer(
            m,
            **{
                "lens:boat": [
                    {"text": "Ready for Saturday.", "evidence": notes_[:1]},
                    {"text": "And again.", "evidence": notes_[:1]},
                ],
                "lens:money": [{"text": "The day doesn't answer this.", "unsupported": True}],
                "lens:unasked": [{"text": "Not a lens of the bank.", "evidence": notes_[:1]}],
            },
        )

    _fake(monkeypatch, answer)
    assert _cli("dream", "day", DAY)[0] == 0
    p = _drafts(lb)[0]["payload"]
    assert p["extra"]["parts"].count("lens:boat") == 1 and "lens:money" not in p["extra"]["parts"]
    assert "lens:unasked" not in p["extra"]["parts"]
    assert p["extra"]["dropped_segments"] == {dream.DROP_LENS: 1, dream.DROP_LENS_UNSUPPORTED: 1}
    assert drafts.NO_ANSWER not in json.dumps(p), "the model never writes it"
    text = _cli("day", DAY, "--no-anniversaries")[1]
    assert f"lens:money {drafts.NO_ANSWER}" in text and "Ready for Saturday." in text


def test_one_question_an_idea_the_material_named_and_one_photo_of_the_day(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(m: dict[str, Any]) -> dict[str, Any]:
        stays, notes_, photos = _refs(m)
        return _answer(
            m,
            questions=[
                {"text": "First?", "evidence": notes_[:1]},
                {"text": "Second?", "evidence": notes_[:1]},
            ],
            ideas=[
                {"text": "An idea never named.", "evidence": notes_[:1], "entity": TALLY_ID},
                {"text": "An org is not an idea.", "evidence": notes_[:1], "entity": ORG_ID},
                {"text": "No id at all.", "evidence": notes_[:1]},
                {"text": "The boat-share log moved on.", "evidence": notes_[:1], "entity": IDEA_ID},
            ],
            photo=[
                {"text": "Not a photo.", "evidence": stays[:1]},
                {"text": "Two photos.", "evidence": photos[:2]},
                {"text": "The afternoon light.", "evidence": photos[:1]},
                {"text": "Another.", "evidence": photos[1:2]},
            ],
        )

    _fake(monkeypatch, answer)
    assert _cli("dream", "day", DAY)[0] == 0
    p = _drafts(lb)[0]["payload"]
    parts = p["extra"]["parts"]
    assert parts.count("questions") == 1 and parts.count("ideas") == 1 and parts.count("photo") == 1
    assert p["segments"][parts.index("questions")]["text"] == "First?"
    assert p["extra"]["dropped_segments"] == {
        dream.DROP_QUESTION: 1,
        dream.DROP_IDEA: 3,
        dream.DROP_PHOTO: 2,
        dream.DROP_PHOTO_TWICE: 1,
    }
    photo_line = next(
        line for line in lb.lines() if line["kind"] == "photo" and line["at"] == utc(DAY, "15:00")
    )
    assert p["segments"][parts.index("photo")] == {
        "text": "The afternoon light.",
        "evidence": [photo_line["id"]],
    }
    assert p["extra"]["ideas"] == [{"segment": parts.index("ideas") + 1, "entity": IDEA_ID}]


def test_a_number_the_lines_do_not_give_marks_the_segment(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """Numbers come from code: a figure the cited lines do not give marks the sentence unsupported."""
    _fake(
        monkeypatch,
        lambda m: _answer(m, learned=[{"text": "You sailed 42 miles.", "evidence": _refs(m)[1][:1]}]),
    )
    assert _cli("dream", "day", DAY)[0] == 0
    p = _drafts(lb)[0]["payload"]
    assert p["segments"][p["extra"]["parts"].index("learned")] == {
        "text": "You sailed 42 miles.",
        "unsupported": True,
    }
    assert p["extra"]["marked"] == {dream.UNBACKED: 1}


def test_a_link_names_only_an_entity_the_material_gave_and_follows_the_events(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(m: dict[str, Any]) -> dict[str, Any]:
        stays, notes_, _photos = _refs(m)
        dinner = {
            "title": "Crew planning",
            "start": "12:00",
            "end": "13:00",
            "place": "Home",
            "people": [],
            "evidence": notes_[:1],
        }
        return _answer(
            m,
            events=[dinner],
            links=[
                {"entity": TALLY_ID, "text": "Made up", "evidence": notes_[:1]},
                {"entity": "Boat-share log", "text": "A name", "evidence": notes_[:1]},
                {"entity": IDEA_ID, "text": "", "evidence": notes_[:1]},
                {"entity": IDEA_ID, "text": "Nowhere", "evidence": ["L999"]},
                "not an object",
                {
                    "entity": IDEA_ID,
                    "text": "Crew list",
                    "evidence": notes_[:1],
                    "note": "the note of the day",
                },
                {"entity": ORG_ID, "text": "The club's day", "evidence": stays[:1]},
            ],
        )

    _fake(monkeypatch, answer)
    code, out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    p = _drafts(lb)[0]["payload"]
    kinds = [x["kind"] for x in p["proposals"]]
    assert kinds == ["event", "link", "link"]
    assert p["proposals"][1] == {
        "kind": "link",
        "entity": IDEA_ID,
        "text": "Crew list",
        "evidence": p["proposals"][0]["evidence"],
        "note": "the note of the day",
    }
    assert p["extra"]["dropped_links"] == {
        dream.DROP_LINK_ENTITY: 2,
        dream.DROP_LINK_TEXT: 1,
        dream.DROP_EVIDENCE: 1,
        dream.DROP_LINK_SHAPE: 1,
    }
    draft = _day_json()["draft"]
    assert [x["number"] for x in draft["proposals"]] == [1] and [x["number"] for x in draft["links"]] == [
        2,
        3,
    ]
    assert "1 proposed event" in drafts.head_text(draft) and "2 proposed links" in drafts.head_text(draft)
    assert "? link 2    Crew list · the note of the day  proposed" in out


def test_draft_v1_amendment_2_link_and_evening_shapes() -> None:
    base = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": "a" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": "A day.", "evidence": ["x"]}],
    }
    link = {"kind": "link", "entity": IDEA_ID, "text": "Crew list", "evidence": ["x"]}
    assert drafts.validate({**base, "proposals": [link]}) == []
    assert drafts.validate({**base, "proposals": [{**link, "note": "why"}]}) == []
    for broken in (
        {**link, "evidence": []},
        {**link, "text": " "},
        {**link, "ref": {"kind": "page"}},
        {**link, "note": 3},
    ):
        assert drafts.validate({**base, "proposals": [broken]}) == [
            "proposal 1 is malformed: " + drafts.NOT_A_LINK
        ]
    evening = {**base, "extra": {"evening": True, "read_until": "2026-06-10T19:30:00Z"}}
    assert drafts.validate(evening) == []
    assert drafts.validate({**base, "extra": {"evening": True}}) == [
        "an evening draft's extra.read_until is the moment it read up to, UTC with a Z"
    ]
    assert drafts.validate({**base, "extra": {"evening": False, "read_until": "2026-06-10T19:30:00Z"}}) == [
        "extra.evening is true when present"
    ]


def test_a_dream_day_3_draft_still_reads_with_its_parts(lb: Logbook) -> None:
    on_day = next(line for line in lb.lines() if line["kind"] == "note" and line["at"].startswith(DAY))
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": lb.meta["head"],
        "read_count": 1,
        "language": "en",
        "segments": [
            {"text": "A day.", "evidence": [on_day["id"]]},
            {"text": "Why?", "evidence": [on_day["id"]]},
        ],
        "extra": {"prompt": "dream-day/3", "parts": ["day", "questions"]},
    }
    lb.append(utc(NEXT, "06:00"), f"model:{MODEL}", drafts.KIND, 2, payload)
    draft = _day_json()["draft"]
    assert [s["part"] for s in draft["segments"]] == ["day", "questions"]
    assert draft["lenses"] == [] and draft["links"] == [] and draft["closing"] is None
    assert "      day       A day." in _cli("day", DAY, "--no-anniversaries")[1]


# -- the evening ------------------------------------------------------------------------------------------


def test_evening_dreams_today_so_far_and_refuses_another_day(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    monkeypatch.setattr(dream, "now_utc", lambda: "2026-06-11T17:30:00Z")  # 19:30 in Oslo, on NEXT
    _fake(monkeypatch)
    code, _out, err = _cli("dream", "day", DAY, "--evening")
    assert code == 2 and "is not today (2026-06-11)" in err and _drafts(lb) == []
    code, out, err = _cli("dream", "day", NEXT, "--evening")
    assert code == 0, err
    (line,) = _drafts(lb)
    assert line["payload"]["extra"]["evening"] is True
    assert line["payload"]["extra"]["read_until"] == "2026-06-11T17:30:00Z"
    assert "the day so far, read until 2026-06-11T17:30:00Z" in out
    draft = _day_json(NEXT)["draft"]
    assert draft["evening"] is True and draft["read_until"] == "2026-06-11T17:30:00Z"
    assert "the day so far" in drafts.head_text(draft)
    code, _out, err = _cli("dream", "--catch-up", "--evening")
    assert code == 2 and "--evening goes with `dream day DAY`" in err


def test_the_catch_up_never_dreams_today_and_supersedes_the_evening_draft_in_the_morning(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    monkeypatch.setattr(dream, "now_utc", lambda: "2026-06-11T17:30:00Z")
    seen = _fake(monkeypatch)
    assert _cli("dream", "day", NEXT, "--evening")[0] == 0
    evening = _drafts(lb)[0]
    _today(monkeypatch, date(2026, 6, 11))
    out = _cli("dream", "--catch-up", "--days", "1")[1]
    assert NEXT not in out and out.startswith(f"{DAY}  dreamed"), "today is still being written"
    lb.append(
        utc(NEXT, "22:00"), "manual", "note", 2, {"schema": "note/v1", "text": "Late tea with Kari Nordmann."}
    )
    _today(monkeypatch, date(2026, 6, 12))
    out = _cli("dream", "--catch-up", "--days", "1")[1]
    assert out.startswith(f"{NEXT}  dreamed") and len(seen["calls"]) == 3
    morning = _drafts(lb)[-1]
    assert morning["payload"]["supersedes"] == evening["id"] and "evening" not in morning["payload"]["extra"]


# -- the re-dream rules (RFC 0043 §6 rules 4, 5 and 6) -----------------------------------------------------


def _accept_dinner(m: dict[str, Any]) -> dict[str, Any]:
    notes_ = _refs(m)[1]
    dinner = {
        "title": "Crew planning",
        "start": "12:00",
        "end": "13:00",
        "place": "Home",
        "people": [],
        "evidence": notes_[:1],
    }
    return _answer(m, events=[dinner])


def test_kept_lines_never_re_dream_the_day(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    """The reflection and a sentence kept from the draft (`extra.from`, as the close of slice C writes
    it) are the close's, not the day's: none of them makes the catch-up dream the day again; a
    plain note does. (An accepted event is written at the signature, under rule 5, below.)"""
    seen = _fake(monkeypatch, _accept_dinner)
    _today(monkeypatch, date(2026, 6, 11))
    assert "dreamed" in _cli("dream", "--catch-up", "--days", "1")[1]
    draft = _drafts(lb)[0]
    code, _out, err = _cli("day", "reflect", DAY, "--text", "A good crew list.")
    assert code == 0, err
    kept = {
        "schema": "note/v1",
        "text": "A crew list helps.",
        "labels": ["learned"],
        "extra": {"from": draft["id"]},
    }
    lb.append(utc(DAY, "21:30"), "manual", "note", 2, kept)
    out = _cli("dream", "--catch-up", "--days", "1")[1]
    assert (
        out.splitlines()[0] == f"{DAY}  unchanged unchanged since #{draft['seq']}" and len(seen["calls"]) == 1
    )
    lb.append(utc(DAY, "21:00"), "manual", "note", 2, {"schema": "note/v1", "text": "One more line."})
    out = _cli("dream", "--catch-up", "--days", "1")[1]
    assert out.startswith(f"{DAY}  dreamed") and len(seen["calls"]) == 2


def test_after_a_signature_only_a_later_line_re_dreams_and_a_kept_proposal_is_not_shown_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = _fake(monkeypatch, _accept_dinner)
    _today(monkeypatch, date(2026, 6, 11))
    assert "dreamed" in _cli("dream", "--catch-up", "--days", "1")[1]
    first = _drafts(lb)[0]
    lb.append(utc(DAY, "19:00"), "manual", "note", 2, {"schema": "note/v1", "text": "Seen before signing."})
    code, _out, err = _cli("day", "sign", DAY, "--accept", "1")
    assert code == 0, err
    signature = next(line for line in lb.lines() if line["kind"] == signing.KIND)
    out = _cli("dream", "--catch-up", "--days", "1")[1]
    assert out.splitlines()[0] == (
        f"{DAY}  unchanged signed as #{signature['seq']}, no line since; unchanged since #{first['seq']}"
    ), "a line before the signature, the owner signed what they saw"
    assert len(seen["calls"]) == 1
    late = lb.append(utc(DAY, "20:30"), "manual", "note", 2, {"schema": "note/v1", "text": "Synced after."})
    out = _cli("dream", "--catch-up", "--days", "1")[1]
    assert out.startswith(f"{DAY}  dreamed") and "1 line since you signed" in out and len(seen["calls"]) == 2
    second = _drafts(lb)[-1]
    assert second["payload"]["supersedes"] == first["id"] and int(second["seq"]) > int(late["seq"])
    draft = _day_json()["draft"]
    assert draft["since_signed"] is True and draft["signed_seq"] == signature["seq"]
    (dinner,) = draft["proposals"]
    assert dinner["confirmed"] == dinner["kept"], (
        "kept by its fields, though its raw_id names the first draft"
    )
    accepted = next(line for line in lb.lines() if line["kind"] == "event" and line["source"] == "owner")
    assert dinner["kept"] == {"line": accepted["id"], "seq": accepted["seq"]}, "kept, matched by its fields"
    rows = _cli("day", DAY, "--no-anniversaries")[1]
    assert "since you signed" in rows and "? link 2" in rows and "event 1" not in rows
    assert "dreamed" not in _cli("dream", "--catch-up", "--days", "1")[1], "nothing since the new draft"


def test_a_signed_day_with_no_late_lines_is_never_dreamed_again_unless_the_entry_changed_or_asked(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = _fake(monkeypatch)
    _today(monkeypatch, date(2026, 6, 11))
    assert "dreamed" in _cli("dream", "--catch-up", "--days", "1")[1]
    assert _cli("day", "sign", DAY)[0] == 0
    assert "unchanged signed as" in _cli("dream", "--catch-up", "--days", "1")[1] and len(seen["calls"]) == 1
    lb.append(utc(NEXT, "21:00"), "manual", "note", 2, {"schema": "note/v1", "text": "Another day's line."})
    assert "unchanged" in _cli("dream", "--catch-up", "--days", "1")[1].splitlines()[0]
    data = json.loads(policy.policy_path(lb.root).read_text(encoding="utf-8"))
    data[policy.DREAM_DESTINATION]["until"] = "2026-12-30"
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")
    out = _cli("dream", "--catch-up", "--days", "1")[1]
    assert out.startswith(f"{DAY}  dreamed") and "another dream entry" in out and len(seen["calls"]) == 2
    assert "unchanged signed as" in _cli("dream", "--catch-up", "--days", "1")[1]
    assert _cli("dream", "day", DAY)[0] == 0 and len(seen["calls"]) == 3, "the owner asks: dreamed"


def test_the_voice_rules_of_rfc_0043_section_7_are_in_the_prompt_word_for_word() -> None:
    """RFC 0043 §7's list, each item as the RFC writes it, the RFC's own `[main]` mark aside."""
    rfc = (Path(__file__).resolve().parents[1] / "rfcs" / "0043-the-day-page.md").read_text(encoding="utf-8")
    section = rfc.split("## 7. The voice of dream-day/4")[1].split("\n## ")[0]
    items: list[str] = []
    for row in section.splitlines():
        if row.startswith("- "):
            items.append(row)
        elif row.startswith("  ") and items:
            items[-1] += " " + row.strip()
    assert len(items) == 7
    prompt = " ".join(dream.PROMPT_FILE.read_text(encoding="utf-8").split())
    for item in items:
        assert item.replace(" [main]", "") in prompt, item


# -- what the blind review found ---------------------------------------------------------------------------


def test_a_hand_written_draft_with_odd_fields_reads_without_a_traceback(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A reader never fails on a draft a writer did not make: a proposal that is not an object, lenses
    and ideas that are not lists, and a line whose `extra.from` is not a string."""
    on_day = next(line for line in lb.lines() if line["kind"] == "note" and line["at"].startswith(DAY))
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": lb.meta["head"],
        "read_count": 1,
        "language": "en",
        "segments": [{"text": "A day.", "evidence": [on_day["id"]]}],
        "proposals": ["x", None, 5],
        "extra": {"parts": ["story"], "lenses": 5, "ideas": 7},
    }
    lb.append(utc(NEXT, "06:00"), f"model:{MODEL}", drafts.KIND, 2, payload)
    odd = {"schema": "note/v1", "text": "Odd.", "extra": {"from": ["a", "b"]}}
    lb.append(utc(DAY, "21:00"), "manual", "note", 2, odd)
    draft = _day_json()["draft"]
    assert draft["malformed"] and draft["lenses"] == [] and draft["links"] == [] and draft["proposals"] == []
    code, _out, err = _cli("day", DAY, "--no-anniversaries")
    assert code == 0, err
    _fake(monkeypatch)
    _today(monkeypatch, date(2026, 6, 11))
    code, out, err = _cli("dream", "--catch-up", "--days", "1")
    assert code == 0, err and out.startswith(f"{DAY}  dreamed")


def test_a_proposal_kept_from_another_draft_is_not_accepted_twice(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _fake(monkeypatch, _accept_dinner)
    _today(monkeypatch, date(2026, 6, 11))
    assert "dreamed" in _cli("dream", "--catch-up", "--days", "1")[1]
    assert _cli("day", "sign", DAY, "--accept", "1")[0] == 0
    lb.append(utc(DAY, "20:30"), "manual", "note", 2, {"schema": "note/v1", "text": "Synced after."})
    assert "dreamed" in _cli("dream", "--catch-up", "--days", "1")[1]
    events = [line for line in lb.lines() if line["kind"] == "event" and line["source"] == "owner"]
    (dinner,) = _day_json()["draft"]["proposals"]
    assert dinner["confirmed"] == {"line": events[0]["id"], "seq": events[0]["seq"]} == dinner["kept"]
    code, _out, err = _cli("day", "sign", DAY, "--accept", "1")
    assert code != 0 and "confirmed already" in err
    assert [line for line in lb.lines() if line["kind"] == "event" and line["source"] == "owner"] == events


def test_a_figure_the_chapter_a_goal_a_named_thing_or_a_lens_gives_is_not_marked(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The number rule credits the figures of the material's own words: the chapter's rule, a goal, a
    name, a lens, as it credits a note's."""
    chapter.close(lb, "2026-06-05")
    chapter.open_chapter(lb, "The Fjord Summer", start="2026-06-06", rules="Three sails a week at most.")
    sentence = "You kept to three sails a week."
    _fake(monkeypatch, lambda m: _answer(m, learned=[{"text": sentence, "evidence": _refs(m)[1][:1]}]))
    assert _cli("dream", "day", DAY)[0] == 0
    p = _drafts(lb)[0]["payload"]
    assert {
        "text": sentence,
        "evidence": p["segments"][p["extra"]["parts"].index("learned")]["evidence"],
    } in p["segments"]
    assert "marked" not in p["extra"]


# -- the tier of what the draft draws on, and no number beside a person ------------------------------

PER_ID = "019cadd3-6bc0-7dcd-9133-0000000000b1"


def test_a_tier_3_goal_the_dream_draws_on_lifts_the_drafted_line_to_tier_3(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The draft's tier is the highest of every line it read (RFC 0036): the day's, and the chapter, goal
    and entity lines `enrich` gives the model. A goal written at tier 3 lifts the draft to tier 3 when the
    entry lets it cross, and under max_tier 2 it is not read and the draft stays at 2."""
    goal = next(line for line in lb.lines() if line["kind"] == goals.KIND)
    secret = {**goal["payload"], "text": "Pay off the boat loan"}
    lb.append(goal["at"], goal["source"], goals.KIND, 3, secret)
    seen = _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    assert "Pay off the boat loan" not in json.dumps(seen["material"])
    assert _drafts(lb)[-1]["tier"] == 2
    _policy(lb, 3)
    lb.append(utc(NEXT, "21:00"), "manual", "note", 1, {"schema": "note/v1", "text": "Moves the head."})
    assert _cli("dream", "day", DAY)[0] == 0
    assert "Pay off the boat loan" in [g["text"] for g in seen["material"]["for"]["goals"]]
    on_day = [line for line in lb.lines() if line["at"].startswith(DAY) and line["kind"] != drafts.KIND]
    assert max(int(line["tier"]) for line in on_day) == 2, "no line of the day is above tier 2"
    assert _drafts(lb)[-1]["tier"] == 3, "the goal it drew on lifts it"


def test_no_number_stands_beside_a_person_in_a_day_segment(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A figure the cited line gives (`hold_numbers` lets it stand) is still never written beside a
    person's name: the sentence's words are dropped, its slot held unsupported with the reason
    (`dream.HELD`), its evidence kept under `extra.held`, and it is counted (`dream.BESIDE_A_NAME`);
    the same figure without the name, or the name without a figure, stays."""
    lb.append_many(
        [
            resolution(("email", "per.hansen@example.org"), PER_ID, "Per Hansen"),
            note(utc(DAY, "14:00"), "Per Hansen brought 3 sails for Solvind."),
        ]
    )

    def answer(m: dict[str, Any]) -> dict[str, Any]:
        sails = next(n["ref"] for n in m["notes"] if "sails" in n["text"])
        return _answer(
            m,
            learned=[
                {"text": "Per Hansen brought 3 sails.", "evidence": [sails]},
                {"text": "Per brought 3 sails.", "evidence": [sails]},
                {"text": "3 sails came aboard.", "evidence": [sails]},
                {"text": "Per Hansen came aboard.", "evidence": [sails]},
            ],
        )

    _fake(monkeypatch, answer)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    p = _drafts(lb)[-1]["payload"]
    learned = [s for s, part in zip(p["segments"], p["extra"]["parts"], strict=True) if part == "learned"]
    assert learned[:2] == [{"text": dream.HELD, "unsupported": True}] * 2
    assert dream.HELD == "held: a number beside a name"
    assert "evidence" in learned[2] and "evidence" in learned[3]
    assert p["extra"]["marked"] == {dream.BESIDE_A_NAME: 2}
    sails_id = next(line["id"] for line in lb.lines() if "sails" in str(line["payload"].get("text")))
    slots = [n for n, s in enumerate(p["segments"], 1) if s["text"] == dream.HELD]
    assert p["extra"]["held"] == [{"segment": n, "evidence": [sails_id]} for n in slots]
    assert "brought 3 sails" not in json.dumps(p), "the held words are in no field of the line"
    for segment in p["segments"]:
        if "evidence" in segment:
            assert not ("Per" in segment["text"] and any(c.isdigit() for c in segment["text"])), segment


def test_a_segment_with_a_number_beside_a_name_is_written_without_its_words_and_no_reader_prints_them(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network
):
    """RFC 0043: no number beside a person anywhere, pencil included. "Per Hansen · 3 calls" rests on a
    line that gives the 3, and "Per Hansen · 5 calls" on one that does not (`hold_numbers` marks it
    first): both are written without their words, each slot kept with its evidence and the reason, and
    `day DAY`, `day --json`, the Day page in every shape and `export site --with-drafts` print none of it."""
    lb.append_many(
        [
            resolution(("email", "per.hansen@example.org"), PER_ID, "Per Hansen"),
            note(utc(DAY, "15:00"), "Rang about the berth for Solvind 3 times; Per Hansen answered."),
        ]
    )

    def answer(m: dict[str, Any]) -> dict[str, Any]:
        calls = next(n["ref"] for n in m["notes"] if "berth" in n["text"])
        return _answer(
            m,
            learned=[
                {"text": "Per Hansen · 3 calls", "evidence": [calls]},
                {"text": "Per Hansen · 5 calls", "evidence": [calls]},
                {"text": "The berth for Solvind is settled.", "evidence": [calls]},
                {"text": dream.HELD, "evidence": [calls]},  # the reason's own words, from the model
            ],
        )

    _fake(monkeypatch, answer)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    line = _drafts(lb)[-1]
    p = line["payload"]
    calls_id = next(x["id"] for x in lb.lines() if "berth" in str(x["payload"].get("text")))
    learned = [
        (n, s)
        for n, (s, part) in enumerate(zip(p["segments"], p["extra"]["parts"], strict=True), 1)
        if part == "learned"
    ]
    assert [s for _n, s in learned[:2]] == [{"text": dream.HELD, "unsupported": True}] * 2
    assert learned[2][1] == {"text": "The berth for Solvind is settled.", "evidence": [calls_id]}
    assert learned[3][1] == {"text": dream.HELD, "unsupported": True}, "never prose that reads as held"
    held = [learned[0], learned[1], learned[3]]
    assert p["extra"]["held"] == [{"segment": n, "evidence": [calls_id]} for n, _s in held]
    assert p["extra"]["marked"] == {dream.UNBACKED: 1, dream.BESIDE_A_NAME: 3}
    assert _words(json.dumps(line, ensure_ascii=False)) == [], "the held words are in no field of the line"

    code, out, err = _cli("day", DAY, "--no-anniversaries")
    assert code == 0, err
    assert dream.HELD in out and _words(out) == []
    assert _words(json.dumps(_day_json(), ensure_ascii=False)) == []
    site = serve.Site(lb)
    for shape in day_rhythm.SHAPES:
        page = site.page_day(DAY, expanded=True, shape=shape)
        assert _words(page) == [], shape
        assert beside(_seen(page), ["Per Hansen"]) == [], shape
    folder = tmp_path / "Site"
    assert _cli("export", "site", str(folder), "--with-drafts")[0] == 0
    pages = sorted((folder / "days").glob("*.html"))
    assert DAY in [x.stem for x in pages]
    for found in pages:
        text = found.read_text(encoding="utf-8")
        assert _words(text) == [] and beside(_seen(text), ["Per Hansen"]) == [], found.name


def _words(text: str) -> list[str]:
    """The held segments' own words wherever they show: `3 calls`, `5 calls`, `Per Hansen ·`."""
    return re.findall(r"[35] calls|Per Hansen \u00b7", html.unescape(text))


def test_a_proposal_or_a_link_with_a_number_beside_a_name_is_dropped_and_no_reader_prints_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network
):
    """The same rule for what a draft proposes beside its text: an event whose title, or a link whose
    text or note, puts a number beside a person's name is dropped, never kept, and counted under
    `dream.DROP_BESIDE_A_NAME`; the event or link without one stays."""
    lb.append_many([resolution(("email", "per.hansen@example.org"), PER_ID, "Per Hansen")])

    def answer(m: dict[str, Any]) -> dict[str, Any]:
        notes_ = _refs(m)[1]
        event_ = {"start": "12:00", "end": "13:00", "place": "Home", "people": [], "evidence": notes_[:1]}
        link = {"entity": IDEA_ID, "evidence": notes_[:1]}
        return _answer(
            m,
            events=[{**event_, "title": "Crew planning"}, {**event_, "title": "Per Hansen · 3 calls"}],
            links=[
                {**link, "text": "Crew list"},
                {**link, "text": "Per Hansen · 3 calls"},
                {**link, "text": "Crew list", "note": "Per Hansen · 5 calls"},
            ],
        )

    _fake(monkeypatch, answer)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    line = _drafts(lb)[-1]
    p = line["payload"]
    assert [(x["kind"], x.get("title") or x.get("text")) for x in p[drafts.PROPOSALS]] == [
        (drafts.EVENT, "Crew planning"),
        (drafts.LINK, "Crew list"),
    ]
    assert p["extra"]["dropped"] == {dream.DROP_BESIDE_A_NAME: 1}
    assert p["extra"]["dropped_links"] == {dream.DROP_BESIDE_A_NAME: 2}
    assert _words(json.dumps(line, ensure_ascii=False)) == []
    code, out, err = _cli("day", DAY, "--no-anniversaries")
    assert code == 0, err
    assert "Crew planning" in out and _words(out) == []
    assert _words(json.dumps(_day_json(), ensure_ascii=False)) == []
    site = serve.Site(lb)
    for shape in day_rhythm.SHAPES:
        page = site.page_day(DAY, expanded=True, shape=shape)
        assert _words(page) == [] and beside(_seen(page), ["Per Hansen"]) == [], shape
    folder = tmp_path / "Site"
    assert _cli("export", "site", str(folder), "--with-drafts")[0] == 0
    for found in sorted((folder / "days").glob("*.html")):
        text = found.read_text(encoding="utf-8")
        assert _words(text) == [] and beside(_seen(text), ["Per Hansen"]) == [], found.name
