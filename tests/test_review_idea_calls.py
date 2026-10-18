"""Ideas from calls (`synthesis.ideas_of`, `entity_review.call_ideas`): the call synthesis proposes new
ideas and refinements of the owner's named ones, by entity id, with the utterances as evidence; they
are proposals in the draft's `extra.ideas` and candidates in `review idea`, and nothing reaches the
Ideas shelf until the owner says yes there. A no is the `entity-review/v1` line review writes; a
home video's soundtrack never feeds it; a synthesis the `dream` entry withholds today proposes
nothing; and a tier-3 call's yes is a tier-2 `entity/v1` line with the name alone. The calls are the
synthetic Granola call of `test_transcript_synthesize` between Ines and Ola Nordmann of Oslo."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from ideas_record import task, transcript
from test_transcript_synthesize import ENV, _answer, _cli, _fake, _policy, _transcript

from logbook import cli
from logbook.contrib import entities, entity_review, serve, synthesis
from logbook.core import drafts, policy
from logbook.core.store import Logbook, uuid7

KIOSK = "Fjord Kiosk"
CALENDAR = "Shared haul-out calendar"
NEW_IDEA = {
    "name": CALENDAR,
    "idea": None,
    "text": "One calendar the yard and the owners share.",
    "evidence": ["U8"],
}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The record of `test_transcript_synthesize`: the persona's zone, the endpoint, a dream entry."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    _policy(lb, {"max_tier": 3, "until": "2026-12-31"})
    return lb


def kiosk(lb: Logbook) -> str:
    """The idea the owner named before the call."""
    entity_id = uuid7()
    payload = entities.entity_payload(
        entities.IDEA, entity_id, KIOSK, key=entities.key_of(entities.IDEA, [], entity_id, KIOSK)
    )
    entity_review.write_entity(lb, payload)
    return entity_id


def refining(material: dict[str, Any]) -> dict[str, Any]:
    (ref,) = [i["ref"] for i in material["ideas"] if i["name"] == KIOSK]
    return {"name": KIOSK, "idea": ref, "text": "The kiosk sells mooring lines too.", "evidence": ["U4"]}


def synthesize(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, *ideas: Any, tier: int | None = None
) -> dict[str, Any]:
    call = _transcript(lb, tier=tier)
    seen = _fake(
        monkeypatch,
        lambda material: _answer(material, ideas=[i(material) if callable(i) else i for i in ideas]),
    )
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 0, err
    seen["call"] = call
    return seen


def queue(lb: Logbook) -> list[dict[str, Any]]:
    code, out, err = _cli("review", "idea", "--json")
    assert code == 0, err
    return [p for p in json.loads(out)["proposals"] if p["call"] is not None]


def entity_lines(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if line["kind"] == entities.ENTITY]


def shelf(lb: Logbook) -> list[str]:
    code, out, err = _cli("show", "ideas", "--json")
    assert code == 0, err
    return [i["name"] for i in json.loads(out)["ideas"]]


def test_a_call_with_an_idea_becomes_one_candidate_and_nothing_on_the_shelf(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    seen = synthesize(lb, monkeypatch, NEW_IDEA)
    (draft,) = [line for line in Logbook(lb.root).lines() if line["kind"] == drafts.KIND]
    (kept,) = draft["payload"]["extra"]["ideas"]
    assert kept["name"] == CALENDAR and kept["idea"] is None and kept["evidence"] == [seen["call"]["id"]]
    assert [u["n"] for u in kept["utterances"]] == [8]
    assert all(CALENDAR not in s["text"] for s in draft["payload"]["segments"]), "never a segment"
    (candidate,) = queue(lb)
    assert candidate["new"] and candidate["call"]["name"] == CALENDAR
    assert candidate["call"]["transcript"] == seen["call"]["id"] and candidate["call"]["utterances"] == [8]
    assert candidate["observed"]["tier"] == 3, "a Granola call is tier 3, and so is what it proposes"
    assert entity_lines(lb) == [] and CALENDAR not in shelf(lb), (
        "nothing on the shelf until the owner says yes"
    )
    code, out, _err = _cli("review", "idea")
    assert code == 0 and f"[call]  “{CALENDAR}” (call “Yard plans” 2026-06-10; U8) → ____" in out


def test_a_refinement_names_the_idea_by_its_entity_id(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    idea = kiosk(lb)
    seen = synthesize(lb, monkeypatch, refining, NEW_IDEA)
    assert {"ref": "I1", "name": KIOSK} in seen["material"]["ideas"], "only the label goes to the model"
    found = queue(lb)
    assert [(p["call"]["name"], p["call"]["idea"]) for p in found] == [(KIOSK, idea), (CALENDAR, None)]
    assert found[0]["canonical"]["id"] == idea and not found[0]["new"]
    _code, out, _err = _cli("review", "idea")
    assert f"→ {KIOSK}, refines: The kiosk sells mooring lines too." in out


def test_yes_writes_one_entity_line_and_a_tier_3_call_gives_it_the_name_alone(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    idea = kiosk(lb)
    synthesize(lb, monkeypatch, refining, NEW_IDEA)
    numbers = {p["call"]["name"]: p["number"] for p in queue(lb)}
    before = len(entity_lines(lb))
    code, _out, err = _cli("review", "idea", "--name", str(numbers[CALENDAR]), "Haul-out calendar")
    assert code == 0, err
    code, _out, err = _cli("review", "idea", "--accept", str(numbers[KIOSK]))
    assert code == 0, err
    new, refined = entity_lines(lb)[before:]
    for line in (new, refined):
        assert line["tier"] == 2 and "evidence" not in line["payload"], "a tier-3 call is never cited"
        assert set(line["payload"]["extra"]) == {"review"}, "nothing of the call's words on a tier-2 line"
    assert new["payload"]["label"] == "Haul-out calendar" and new["payload"]["entity"]["id"] != idea
    assert refined["payload"]["entity"]["id"] == idea and refined["payload"]["label"] == KIOSK
    assert "Haul-out calendar" in shelf(lb)
    assert queue(lb) == [], "an answered candidate is not proposed again"


def test_a_tier_2_call_is_cited_and_its_words_kept(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    seen = synthesize(lb, monkeypatch, NEW_IDEA, tier=2)
    (candidate,) = queue(lb)
    code, _out, err = _cli("review", "idea", "--accept", str(candidate["number"]))
    assert code == 0, err
    (line,) = entity_lines(lb)
    assert line["tier"] == 2 and line["payload"]["evidence"] == [seen["call"]["id"]]
    assert line["payload"]["extra"]["pitch"] == NEW_IDEA["text"]
    assert line["payload"]["extra"]["call"]["transcript"] == seen["call"]["id"]


def test_no_writes_the_entity_review_line_as_review_does_and_is_never_asked_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    idea = kiosk(lb)
    seen = synthesize(lb, monkeypatch, refining, NEW_IDEA)
    numbers = [p["number"] for p in queue(lb)]
    code, _out, err = _cli("review", "idea", "--reject", ",".join(map(str, numbers)))
    assert code == 0, err
    noes = [line for line in Logbook(lb.root).lines() if line["kind"] == entities.ENTITY_REVIEW]
    assert len(noes) == 2 and all(line["tier"] == 3 for line in noes), "a no on a tier-3 call is tier 3"
    refinement, new = noes
    assert refinement["payload"]["ref"] == {"kind": "line", "value": seen["call"]["id"]}
    assert refinement["payload"]["entity"]["id"] == idea and refinement["payload"]["verdict"] == "different"
    assert new["payload"]["ref"] == {"kind": "title", "value": entities.title_key(CALENDAR)}
    assert new["payload"]["entity"] == {"type": "idea"} and new["payload"]["label"] == CALENDAR
    for line in noes:
        assert entities.validate_entity_review(line["payload"]) == []
        assert line["payload"]["raw_id"].startswith("review:different:")
    assert queue(lb) == [] and entity_lines(lb)[1:] == [], "never proposed again; nothing on the shelf"


def test_a_withheld_synthesis_and_a_video_soundtrack_propose_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    synthesize(lb, monkeypatch, NEW_IDEA)
    assert len(queue(lb)) == 1
    _policy(lb, {"max_tier": 2, "until": "2026-12-31"})  # the tier-3 synthesis is withheld today
    assert queue(lb) == []
    _policy(lb, {"max_tier": 3, "until": "2026-12-31"})
    (draft,) = [line for line in Logbook(lb.root).lines() if line["kind"] == drafts.KIND]
    video = lb.append(
        at="2026-06-11T08:00:00Z",
        source="video-transcription",
        kind="transcript",
        tier=2,
        payload={"schema": "transcript/v1", "title": "Summer 1994"},
    )
    payload = {**draft["payload"], "subject": [video["id"]]}
    payload.pop("supersedes", None)
    lb.append(at="2026-06-11T09:00:00Z", source=draft["source"], kind=drafts.KIND, tier=2, payload=payload)
    assert [p["call"]["transcript"] for p in queue(lb)] == [draft["payload"]["subject"][0]], (
        "a soundtrack is no call: its synthesis feeds no idea"
    )


def test_an_idea_that_rests_on_nothing_or_names_an_idea_not_given_is_dropped(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    kiosk(lb)
    synthesize(
        lb,
        monkeypatch,
        {"name": "Unsupported", "idea": None, "text": "No utterance.", "unsupported": True},
        {"name": "Only the header", "idea": None, "text": "The title alone.", "evidence": ["T"]},
        {"name": "Invented", "idea": "I9", "text": "A reference never given.", "evidence": ["U2"]},
        {"name": "Elsewhere", "idea": None, "text": "Cites another line.", "evidence": ["L4"]},
    )
    (draft,) = [line for line in Logbook(lb.root).lines() if line["kind"] == drafts.KIND]
    assert "ideas" not in draft["payload"]["extra"] and queue(lb) == []


def test_a_tier_1_call_is_given_no_labels(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    """An idea's label is a tier-2 line: a tier-1 call's synthesis never reads it, so its draft stays
    tier 1 and it can only propose a new idea."""
    kiosk(lb)
    seen = synthesize(lb, monkeypatch, NEW_IDEA, tier=1)
    assert seen["material"]["ideas"] == []
    (draft,) = [line for line in Logbook(lb.root).lines() if line["kind"] == drafts.KIND]
    assert draft["tier"] == 1 and draft["payload"]["extra"]["ideas"][0]["name"] == CALENDAR


# -- what the review found: nothing comes back, one candidate per idea, the terminal, the Library ----


def _synthesize(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, *ideas: Any, again: bool = False, **kw: Any
) -> dict[str, Any]:
    call = kw.pop("call", None) or _transcript(lb, **kw)
    seen = _fake(
        monkeypatch,
        lambda material: _answer(material, ideas=[i(material) if callable(i) else i for i in ideas]),
    )
    code, _out, err = _cli("transcript", "synthesize", call["id"], *(["--again"] if again else []))
    assert code == 0, err
    seen["call"] = call
    return seen


def _review_lines(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if line["kind"] == entities.ENTITY_REVIEW]


# -- (b) nothing comes back after a yes or a no ----------------------------------------------------------


def test_a_re_synthesis_after_a_yes_or_a_no_proposes_nothing_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    kiosk(lb)
    seen = _synthesize(lb, monkeypatch, refining, NEW_IDEA)
    numbers = {p["call"]["name"]: p["number"] for p in queue(lb)}
    assert _cli("review", "idea", "--name", str(numbers[CALENDAR]), "Yard calendar")[0] == 0
    assert _cli("review", "idea", "--reject", str(numbers[KIOSK]))[0] == 0
    assert queue(lb) == []
    _synthesize(lb, monkeypatch, refining, NEW_IDEA, call=seen["call"], again=True)
    assert len([line for line in Logbook(lb.root).lines() if line["kind"] == drafts.KIND]) == 2
    assert queue(lb) == [], "the same ideas from the same call, synthesized again, are answered"
    # a second call that puts the same new idea forward: answered by the first's yes
    _synthesize(lb, monkeypatch, NEW_IDEA, note_id="not_0synthetic0002", title="Second call")
    assert queue(lb) == []
    assert set(shelf(lb)) == {KIOSK, "Yard calendar"}


def test_a_no_on_a_tier_2_call_is_a_tier_2_line(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    _synthesize(lb, monkeypatch, NEW_IDEA, tier=2)
    (candidate,) = queue(lb)
    assert _cli("review", "idea", "--reject", str(candidate["number"]))[0] == 0
    (no,) = _review_lines(lb)
    assert no["tier"] == 2 and no["payload"]["evidence"] == [candidate["call"]["transcript"]]


# -- (e) the sitting's flags, two candidates of one idea, the terminal ------------------------------------


def test_all_above_never_takes_a_call_candidate(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    kiosk(lb)
    _synthesize(lb, monkeypatch, refining, NEW_IDEA)
    assert len(queue(lb)) == 2
    code, out, err = _cli("review", "idea", "--all-above", "0")
    assert code == 0, err
    assert entity_lines(lb)[1:] == [] and "nothing" in out


def test_two_calls_with_the_same_new_idea_are_one_candidate(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    _synthesize(lb, monkeypatch, NEW_IDEA)
    _synthesize(lb, monkeypatch, NEW_IDEA, note_id="not_0synthetic0002", title="Second call")
    found = queue(lb)
    assert len({p["id"] for p in found}) == len(found), "one proposal id, listed once"
    assert len(found) == 1
    assert _cli("review", "idea", "--accept", str(found[0]["number"]))[0] == 0
    assert len(entity_lines(lb)) == 1 and queue(lb) == []


def test_an_observed_title_and_a_call_s_new_idea_of_one_title_accepted_together_mint_one_id(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    """RFC 0037 §9: a key is looked up before minting, so a second yes on the same key reuses the id."""
    lb.append(**task("2026-06-08T09:00:00Z", CALENDAR))
    lb.append(**transcript("2026-06-09T09:00:00Z", CALENDAR, "2026-06-09T09:30:00Z"))
    _synthesize(lb, monkeypatch, NEW_IDEA)
    report = entity_review.read(lb, entities.IDEA)
    by_key = {(p.observed.key, p.call is None): p for p in report.proposals}
    key = ("title", entities.title_key(CALENDAR))
    observed, call = by_key[(key, True)], by_key[(key, False)]
    code, _out, err = _cli("review", "idea", "--accept", f"{observed.number},{call.number}")
    assert code == 0, err
    lines = entity_lines(lb)
    assert len({line["payload"]["entity"]["id"] for line in lines}) == 1, [
        (line["payload"]["entity"]["id"], line["payload"]["keys"]) for line in lines
    ]


def test_the_terminal_takes_y_n_and_a_name_on_a_call_candidate(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    kiosk(lb)
    _synthesize(lb, monkeypatch, refining, NEW_IDEA)
    answers = iter(["y", "Yard calendar"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    with contextlib.redirect_stdout(Terminal()):
        cli.main(["review", "idea"])
    refined, new = entity_lines(lb)[1:]
    assert refined["payload"]["label"] == KIOSK and new["payload"]["label"] == "Yard calendar"
    assert queue(lb) == []


# -- (d) a soundtrack's synthesis is given the labels ------------------------------------------------------


def test_a_video_s_synthesis_is_given_no_idea_labels(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    """A soundtrack never feeds the queue; the labels of the owner's ideas need not go out with it."""
    kiosk(lb)
    video = _transcript(lb, tier=2)
    line = dict(video)
    line["source"] = "video-transcription"
    found = synthesis.material(lb, line, synthesis.dream.ceiling(lb))
    assert found.data["ideas"] == [] and found.ideas == {}


# -- (f) the Library page ---------------------------------------------------------------------------------


def _site(lb: Logbook) -> serve.Site:
    return serve.Site(lb, now=lambda: datetime(2026, 6, 20, 12, tzinfo=UTC), tiers=None)


def test_the_library_lists_a_call_candidate_with_its_words_and_takes_the_acts(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    idea = kiosk(lb)
    _synthesize(lb, monkeypatch, refining, NEW_IDEA)
    site = _site(lb)
    page = site.respond("/ideas", "")
    assert page.status == 200
    text = page.body.decode("utf-8")
    assert "Yard plans" in text and CALENDAR in text
    assert "The kiosk sells mooring lines too." in text, "the refinement's words are what the owner answers"
    report = entity_review.read(lb, entities.IDEA)
    refinement, new = [p for p in report.proposals if p.call is not None]
    done = site.write(serve.IDEAS_REVIEW, {"id": refinement.id, "act": "accept"}, "127.0.0.1", None)
    assert done.status == 303, done.body
    done = site.write(
        serve.IDEAS_REVIEW, {"id": new.id, "act": "name", "name": "Yard calendar"}, "127.0.0.1", None
    )
    assert done.status == 303, done.body
    refined, named = entity_lines(lb)[1:]
    assert refined["payload"]["entity"]["id"] == idea and named["payload"]["label"] == "Yard calendar"
    assert site.respond(f"/idea/{idea}", "").status == 200


def test_a_library_act_on_a_call_candidate_while_another_command_writes_is_a_409(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    """Main's `_busy`: one sentence, 409, nothing written; and once the record is free, written."""
    import subprocess
    import sys

    _synthesize(lb, monkeypatch, NEW_IDEA)
    report = entity_review.read(lb, entities.IDEA)
    (candidate,) = [p for p in report.proposals if p.call is not None]
    site = _site(lb)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = lb._lock_path()
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        holder = {"pid": other.pid, "command": "sync granola", "since": "2026-06-20T06:00:00Z"}
        lock.write_text(json.dumps(holder), encoding="utf-8")
        seq = int(Logbook(lb.root).meta["seq"])
        for act in ({"act": "name", "name": "Yard calendar"}, {"act": "reject"}):
            response = site.write(serve.IDEAS_REVIEW, {"id": candidate.id, **act}, "127.0.0.1", None)
            body = response.body.decode("utf-8")
            assert response.status == 409 and "sync granola" in body and "nothing was written" in body
            assert int(Logbook(lb.root).meta["seq"]) == seq
    finally:
        other.kill()
        other.wait()
        lock.unlink(missing_ok=True)
    done = site.write(
        serve.IDEAS_REVIEW, {"id": candidate.id, "act": "name", "name": "Yard calendar"}, "127.0.0.1", None
    )
    assert done.status == 303 and [line["payload"]["label"] for line in entity_lines(lb)] == ["Yard calendar"]
