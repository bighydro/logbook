"""The digest's closing question, chosen from the record's own bank (`policy/questions.json`) by the
day's facts, weighted, never the same id two days running (`state/questions.json` remembers the
last ones); `logbook questions list|add|disable` manages the bank. RFC 0027. Synthetic Oslo persona,
who does not exist; the clock is pinned where today matters."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, OLA_ID, TZ, note, persona_record, resolution, utc

from logbook import cli, digest, gaps, questions
from logbook.core.policy import PolicyError
from logbook.core.store import Logbook

NOW = datetime(2026, 6, 22, 18, 0, tzinfo=UTC)  # the Monday evening after the persona's fortnight


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _bank(root: Path, *entries: dict[str, Any]) -> Path:
    """Write a bank of `entries`, each filled out with the defaults of a question."""
    path = questions.questions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    full = [{"kind": "open", "when": [], "weight": 1, "source": "", **e} for e in entries]
    path.write_text(json.dumps({"questions": full}, indent=2) + "\n", encoding="utf-8")
    return path


def _q(id_: str, **fields: Any) -> questions.Question:
    base: dict[str, Any] = {"id": id_, "text": f"{id_}?", "kind": "open", "when": ()}
    return questions.Question(**{**base, **fields})


def _facts(**flags: bool) -> questions.Facts:
    return questions.Facts(flags={**{name: False for name in questions.FACTS}, **flags}, values={})


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    return persona_record(tmp_path, monkeypatch)


# -- the bank ------------------------------------------------------------------------------------------------


def test_the_default_bank_is_written_on_first_read_and_never_overwritten(lb: Logbook) -> None:
    path = questions.questions_path(lb.root)
    assert not path.exists(), "init does not write it; the first run does"
    bank = questions.read(lb.root)
    assert path.exists() and path.parts[-2:] == ("policy", "questions.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"questions"} and len(data["questions"]) == len(bank) >= 3
    for entry in data["questions"]:
        assert set(entry) >= {"id", "text", "kind", "when", "weight", "source"}
        assert entry["kind"] in questions.KINDS and entry["weight"] > 0
        assert entry["source"] == "", "the defaults cite nothing: the bank is to be written (RFC 0027)"
        assert all(name.lstrip("!") in questions.FACTS for name in entry["when"])
    assert len({q.id for q in bank}) == len(bank), "ids are unique"
    assert sum(1 for q in bank if q.when == ("logged",)) >= 2, "a logged day always has candidates"
    assert any(q.when == ("!logged",) for q in bank), "and so has a day with nothing logged"
    data["questions"] = data["questions"][:1]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert [q.id for q in questions.read(lb.root)] == [data["questions"][0]["id"]], "an edit stands"


def test_a_question_carries_an_optional_german_text_and_a_citation(lb: Logbook) -> None:
    _bank(
        lb.root,
        {
            "id": "savour",
            "text": "What did you savour today?",
            "text_de": "Was hast du heute genossen?",
            "kind": "savouring",
            "source": "A. Author (2030), a placeholder citation",
        },
    )
    [q] = questions.read(lb.root)
    assert (q.text, q.text_de, q.kind, q.source) == (
        "What did you savour today?",
        "Was hast du heute genossen?",
        "savouring",
        "A. Author (2030), a placeholder citation",
    )
    assert q.enabled is True and q.weight == 1.0 and q.when == ()


@pytest.mark.parametrize(
    "broken",
    [
        {"id": "x", "text": "x?", "kind": "wondering"},
        {"id": "x", "text": "x?", "when": ["teleported"]},
        {"id": "x", "text": "x?", "when": "travelled"},
        {"id": "x", "text": "x?", "weight": 0},
        {"id": "x", "text": "x?", "weight": "heavy"},
        {"id": "", "text": "x?"},
        {"id": "x", "text": ""},
        {"id": "x", "text": "Was {someone} there?"},
    ],
    ids=[
        "kind",
        "unknown fact",
        "when not a list",
        "weight zero",
        "weight text",
        "no id",
        "no text",
        "placeholder",
    ],
)
def test_a_bank_that_is_not_the_shape_is_refused_naming_the_file(lb: Logbook, broken: dict[str, Any]) -> None:
    path = _bank(lb.root, broken)
    with pytest.raises(PolicyError) as e:
        questions.read(lb.root)
    assert str(path) in str(e.value)


def test_two_questions_with_one_id_are_refused(lb: Logbook) -> None:
    path = _bank(lb.root, {"id": "same", "text": "a?"}, {"id": "same", "text": "b?"})
    with pytest.raises(PolicyError) as e:
        questions.read(lb.root)
    assert str(path) in str(e.value) and "same" in str(e.value)


def test_a_file_that_is_not_json_or_not_the_object_is_refused(lb: Logbook) -> None:
    path = questions.questions_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[", encoding="utf-8")
    with pytest.raises(PolicyError, match="not JSON"):
        questions.read(lb.root)
    path.write_text(json.dumps([{"id": "x", "text": "x?"}]), encoding="utf-8")
    with pytest.raises(PolicyError) as e:
        questions.read(lb.root)
    assert str(path) in str(e.value)


# -- the conditions -----------------------------------------------------------------------------------------


def test_when_is_every_fact_named_true_and_every_negated_one_false() -> None:
    travelled = _facts(logged=True, travelled=True, flew=True, night_away=True)
    assert questions.matches(_q("a"), travelled), "no condition: always"
    assert questions.matches(_q("a", when=("travelled",)), travelled)
    assert questions.matches(_q("a", when=("travelled", "!photos")), travelled)
    assert not questions.matches(_q("a", when=("travelled", "photos")), travelled)
    assert not questions.matches(_q("a", when=("!travelled",)), travelled)
    assert not questions.matches(_q("a", when=("aboard",)), travelled)


def test_the_facts_of_the_persona_days(lb: Logbook) -> None:
    def facts_of(day: str) -> questions.Facts:
        data = digest.read(lb, day)
        return questions.Facts(
            flags={name: name in data["question"]["facts"] for name in questions.FACTS},
            values={},
        )

    office = facts_of("2026-06-10").flags
    assert office["logged"] and office["company"] and office["photos"] and office["night_home"]
    assert not office["travelled"] and not office["flew"] and not office["aboard"] and not office["weekend"]
    assert not office["reunion"], "Kari was at the office on Monday too"
    flight = facts_of("2026-06-15").flags
    assert flight["travelled"] and flight["flew"] and flight["night_away"] and not flight["night_home"]
    saturday = facts_of("2026-06-13").flags
    assert saturday["aboard"] and saturday["weekend"] and saturday["travelled"] and saturday["company"]


def test_the_facts_of_a_day_from_its_parts() -> None:
    """`flags` reads the digest's own parts: the Day, its shape, the promises due, the gaps."""
    data = {
        "weekday": "Sunday",
        "sources": [{"source": "dawarich"}],
        "flights": [],
        "timeline": [],
        "unplaced": [{"kind": "event", "title": "Lunch"}],
        "health": {"sleep_h": 9.4, "steps": 100, "resting_hr": None, "hrv": None},
    }
    shape = {
        "where": ["Home"],
        "night": {"where": "Home", "home": True, "aboard": None, "in_transit": False},
        "with": {"confirmed": [], "proposed": ["Per Hansen"]},
        "attached": [{"count": 1, "noun": "note"}],
        "unplaced": 1,
    }
    flags = questions.flags(data, shape, due_today=True, missing=["apple-health"], reunion=[], tomorrow=4)
    assert flags["logged"] and flags["weekend"] and flags["night_home"] and flags["long_sleep"]
    assert flags["notes"] and not flags["photos"] and not flags["company"] and flags["proposed"]
    assert flags["alone"] is False, "someone is proposed, so the owner was not plainly alone"
    assert flags["event_unplaced"] and flags["gap"] and flags["promise_due"] and flags["tomorrow_busy"]
    assert not flags["travelled"] and not flags["short_sleep"] and not flags["reunion"]
    data["health"] = {"sleep_h": 5.2, "steps": None, "resting_hr": None, "hrv": None}
    shape["with"] = {"confirmed": [], "proposed": []}
    flags = questions.flags(data, shape, due_today=False, missing=[], reunion=[], tomorrow=0)
    assert flags["short_sleep"] and flags["alone"] and not flags["long_sleep"]
    data["health"] = None
    data["sources"] = []
    flags = questions.flags(data, shape, due_today=False, missing=[], reunion=[], tomorrow=0)
    assert not flags["logged"] and not flags["alone"] and not flags["short_sleep"] and not flags["night_home"]
    assert set(flags) == set(questions.FACTS)


def test_a_person_seen_after_ninety_days_is_a_reunion(lb: Logbook) -> None:
    """Per Hansen, resolved in January and with the owner on no day of the ninety before, is named
    in a note at home on Friday 19 June: a reunion. Kari, at the office all fortnight, is not."""
    per_id = OLA_ID[:-1] + "9"
    lb.append_many(
        [
            {**resolution(("email", "per@example.org"), per_id, "Per Hansen"), "at": "2026-01-05T08:00:00Z"},
            note(utc("2026-06-19", "19:00"), "Evening with Per, first time since the winter."),
        ]
    )
    data = digest.read(lb, "2026-06-19")
    assert "Per Hansen" in data["shape"]["with"]["confirmed"]
    assert "reunion" in data["question"]["facts"]
    assert questions.reunion(lb, "2026-06-19", ["Per Hansen", "Kari Nordmann"]) == ["Per Hansen"]
    assert questions.reunion(lb, "2026-06-10", ["Kari Nordmann"]) == []
    assert questions.reunion(lb, "2026-06-10", []) == [], "nobody confirmed: nothing is read"


def test_a_person_the_record_did_not_know_before_is_not_a_reunion(lb: Logbook) -> None:
    per_id = OLA_ID[:-1] + "9"
    lb.append_many(
        [
            {**resolution(("email", "per@example.org"), per_id, "Per Hansen"), "at": "2026-06-18T08:00:00Z"},
            note(utc("2026-06-19", "19:00"), "Evening with Per."),
        ]
    )
    assert questions.reunion(lb, "2026-06-19", ["Per Hansen"]) == [], "met for the first time, not again"


# -- the choice ----------------------------------------------------------------------------------------------


def test_the_choice_is_weighted_and_reproducible_for_a_day() -> None:
    bank = [_q("heavy", weight=8), _q("light-a"), _q("light-b")]
    facts = _facts(logged=True)
    counts = Counter(
        questions.choose(bank, facts, exclude=set(), seed=f"2026-{i:05d}").id for i in range(2000)
    )
    assert 0.7 < counts["heavy"] / 2000 < 0.9, counts
    assert counts["light-a"] and counts["light-b"]
    assert questions.choose(bank, facts, set(), "2026-06-10") == questions.choose(
        bank, facts, set(), "2026-06-10"
    )


def test_only_a_question_whose_conditions_hold_is_a_candidate() -> None:
    bank = [_q("away", when=("night_away",), weight=100), _q("home", when=("night_home",))]
    chosen = questions.choose(bank, _facts(logged=True, night_home=True), exclude=set(), seed="x")
    assert chosen is not None and chosen.id == "home"
    assert questions.choose(bank, _facts(logged=True), exclude=set(), seed="x") is None
    disabled = [_q("home", when=("night_home",), enabled=False)]
    assert questions.choose(disabled, _facts(night_home=True), exclude=set(), seed="x") is None


def test_a_placeholder_is_filled_from_the_day_or_the_question_is_not_asked() -> None:
    bank = [_q("gap", text="Was {missing} switched off?", when=("gap",), weight=100), _q("open")]
    facts = questions.Facts(flags={**_facts(logged=True, gap=True).flags}, values={"missing": "dawarich"})
    chosen = questions.choose(bank, facts, exclude=set(), seed="x")
    assert chosen is not None and chosen.id == "gap"
    assert questions.fill(chosen.text, facts.values) == "Was dawarich switched off?"
    unfilled = questions.Facts(flags=facts.flags, values={})
    chosen = questions.choose(bank, unfilled, exclude=set(), seed="x")
    assert chosen is not None and chosen.id == "open", "a text the day cannot fill is not a candidate"
    assert questions.placeholders("Did {event} happen with {person}?") == ["event", "person"]
    assert questions.placeholders("Anything to add?") == []


def test_never_the_same_id_two_days_running(lb: Logbook) -> None:
    _bank(lb.root, {"id": "a", "text": "a?"}, {"id": "b", "text": "b?"}, {"id": "c", "text": "c?"})
    facts = _facts(logged=True)
    days = [f"2026-06-{d:02d}" for d in range(1, 29)]
    asked = [questions.pick(lb.root, facts, day) for day in days]
    ids = [q["id"] for q in asked]
    assert set(ids) <= {"a", "b", "c"} and len(set(ids)) == 3
    for before, after in pairwise(ids):
        assert before != after, ids
    state = json.loads(questions.state_path(lb.root).read_text(encoding="utf-8"))
    assert (
        state["asked"] == [{"day": d, "id": i} for d, i in zip(days, ids, strict=True)][-questions.REMEMBER :]
    )
    assert questions.state_path(lb.root).parts[-2:] == ("state", "questions.json")


def test_the_day_before_is_never_repeated_even_when_it_is_the_only_match(lb: Logbook) -> None:
    _bank(lb.root, {"id": "only", "text": "only?"}, {"id": "away", "text": "away?", "when": ["night_away"]})
    facts = _facts(logged=True)
    assert questions.pick(lb.root, facts, "2026-06-10")["id"] == "only"
    fallback = questions.pick(lb.root, facts, "2026-06-11")
    assert fallback == {"id": None, "kind": "open", "text": questions.FALLBACK, "facts": ["logged"]}
    state = json.loads(questions.state_path(lb.root).read_text(encoding="utf-8"))
    assert state["asked"] == [{"day": "2026-06-10", "id": "only"}], "the fallback is not remembered"
    assert questions.pick(lb.root, facts, "2026-06-12")["id"] == "only"


def test_a_question_asked_for_a_day_stands_when_the_day_is_read_again(lb: Logbook) -> None:
    _bank(lb.root, {"id": "a", "text": "a?"}, {"id": "b", "text": "b?"})
    facts = _facts(logged=True)
    first = questions.pick(lb.root, facts, "2026-06-10")
    questions.pick(lb.root, facts, "2026-06-11")
    questions.pick(lb.root, facts, "2026-06-09")
    assert questions.pick(lb.root, facts, "2026-06-10") == first
    cli.main(["questions", "disable", str(first["id"])])
    again = questions.pick(lb.root, facts, "2026-06-10")
    assert again["id"] != first["id"], "a question disabled since is chosen anew"


def test_a_recently_asked_question_yields_to_one_that_was_not(lb: Logbook) -> None:
    """Beyond the two-days rule, a question asked within the remembered days steps back when another
    candidate was not; it returns only when every candidate was."""
    _bank(lb.root, {"id": "a", "text": "a?"}, {"id": "b", "text": "b?"}, {"id": "c", "text": "c?"})
    facts = _facts(logged=True)
    first_three = {questions.pick(lb.root, facts, f"2026-06-{d:02d}")["id"] for d in (10, 11, 12)}
    assert first_three == {"a", "b", "c"}


# -- the digest ----------------------------------------------------------------------------------------------


def test_the_digest_asks_from_the_bank_and_remembers_what_it_asked(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    head = lb.meta["head"]
    data = json.loads(_run(capsys, "digest", "2026-06-10", "--json"))
    q = data["question"]
    assert set(q) == {"id", "kind", "text", "facts"} and q["text"].endswith("?")
    assert q["id"] in {entry.id for entry in questions.read(lb.root)} and q["kind"] in questions.KINDS
    assert "logged" in q["facts"] and "company" in q["facts"]
    text = _run(capsys, "digest", "2026-06-10")
    assert text.splitlines()[-1] == q["text"] and text.splitlines()[-2] == ""
    state = json.loads(questions.state_path(lb.root).read_text(encoding="utf-8"))
    assert state["asked"] == [{"day": "2026-06-10", "id": q["id"]}]
    next_day = json.loads(_run(capsys, "digest", "2026-06-11", "--json"))["question"]
    assert next_day["id"] != q["id"]
    assert lb.meta["head"] == head, "the record is untouched: the bank and the state are beside it"
    written = {
        str(p.relative_to(lb.root))
        for p in lb.root.rglob("*.json")
        if "policy" in p.parts or "state" in p.parts
    }
    assert written == {
        str(Path("policy") / "crossing.json"),
        str(Path("policy") / "import.json"),
        str(Path("policy") / "owner.json"),
        str(Path("policy") / "questions.json"),
        str(Path("state") / "questions.json"),
    }


def test_the_former_rules_live_on_as_default_questions(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """A face confirmed nowhere asks whether they were with you, as the code once did; the bank's
    `proposed` question carries the rule, and the digest fills the name."""
    lb.append_many(
        [
            resolution(("provider_id", "immich:p_99"), OLA_ID[:-1] + "9", "Per Hansen"),
            {
                "at": utc("2026-06-19", "19:00"),
                "source": "immich",
                "kind": "photo",
                "tier": 1,
                "payload": {
                    "schema": "photo/v1",
                    "asset_id": "p-per",
                    "library": "immich",
                    "file_name": "IMG_1900.HEIC",
                    "media": "image",
                    "provenance": "camera",
                    "faces": 1,
                    "people": ["p_99"],
                    "lat": HOME[0],
                    "lon": HOME[1],
                    "raw_id": "p-per",
                },
            },
        ]
    )
    bank = {q.id: q for q in questions.read(lb.root)}
    proposed = [q for q in bank.values() if "proposed" in q.when]
    assert proposed and all("{proposed}" in q.text for q in proposed)
    for q in bank.values():  # only the proposed-face question is in play on the Friday
        if "proposed" not in q.when:
            cli.main(["questions", "disable", q.id])
    capsys.readouterr()
    friday = json.loads(_run(capsys, "digest", "2026-06-19", "--json"))
    assert friday["shape"]["with"] == {"confirmed": [], "proposed": ["Per Hansen"]}
    assert friday["question"]["text"] == "Was Per Hansen with you?"


def test_an_empty_record_asks_where_you_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    data = json.loads(_run(capsys, "digest", "2026-06-10", "--json"))
    assert data["question"]["facts"] == [] and data["question"]["text"] == "Where were you?"


def test_a_broken_bank_stops_the_digest_naming_the_file(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _bank(lb.root, {"id": "x", "text": "x?", "kind": "wondering"})
    with pytest.raises(SystemExit) as e:
        cli.main(["digest", "2026-06-10"])
    assert e.value.code == 2 and str(path) in capsys.readouterr().err


# -- the command ---------------------------------------------------------------------------------------------


def test_questions_list_add_disable(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    listed = _run(capsys, "questions", "list")
    bank = questions.read(lb.root)
    assert len(listed.splitlines()) == len(bank)
    for q in bank:
        assert any(line.startswith(f"  {q.id}") and q.text in line for line in listed.splitlines())
    as_json = json.loads(_run(capsys, "questions", "list", "--json"))
    assert [q["id"] for q in as_json["questions"]] == [q.id for q in bank]
    added = _run(
        capsys,
        "questions",
        "add",
        "sea-air",
        "--text",
        "What did the sea smell of?",
        "--kind",
        "savouring",
        "--when",
        "aboard",
        "--when",
        "!night_in_transit",
        "--weight",
        "2.5",
        "--source",
        "a placeholder citation",
        "--de",
        "Wonach roch das Meer?",
    )
    assert added.startswith("  sea-air") and "What did the sea smell of?" in added
    [new] = [q for q in questions.read(lb.root) if q.id == "sea-air"]
    assert new.when == ("aboard", "!night_in_transit") and new.weight == 2.5 and new.kind == "savouring"
    assert new.source == "a placeholder citation" and new.text_de == "Wonach roch das Meer?"
    assert (
        json.loads(questions.questions_path(lb.root).read_text(encoding="utf-8"))["questions"][-1]["id"]
        == "sea-air"
    )
    disabled = _run(capsys, "questions", "disable", "sea-air")
    assert "sea-air" in disabled and "disabled" in disabled
    [new] = [q for q in questions.read(lb.root) if q.id == "sea-air"]
    assert new.enabled is False
    assert "(disabled)" in _run(capsys, "questions", "list")


def test_questions_add_refuses_a_duplicate_id_an_unknown_fact_and_a_bad_kind(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    before = [q.id for q in questions.read(lb.root)]
    for args in (
        ["add", before[0], "--text", "again?", "--kind", "open"],
        ["add", "new", "--text", "new?", "--kind", "open", "--when", "teleported"],
        ["add", "new", "--text", "Was {someone} there?", "--kind", "open"],
        ["disable", "nobody-has-this-id"],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(["questions", *args])
        assert e.value.code == 2 and capsys.readouterr().err.startswith("questions: ")
    with pytest.raises(SystemExit):
        cli.main(["questions", "add", "new", "--text", "new?", "--kind", "wondering"])
    assert [q.id for q in questions.read(lb.root)] == before, "nothing written"


def test_questions_list_on_a_record_with_an_edited_bank_prints_it_as_is(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _bank(
        lb.root,
        {"id": "one", "text": "One two?", "kind": "gratitude", "when": ["travelled", "!photos"], "weight": 3},
    )
    [line] = _run(capsys, "questions", "list").splitlines()
    assert line.startswith("  one ") and line.endswith("  One two?")
    assert line.split()[:5] == ["one", "gratitude", "3", "travelled", "!photos"]
