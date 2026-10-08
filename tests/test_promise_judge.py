"""`logbook promises --judge`: a local model's reading of each rule-found candidate, through a fake
engine with deterministic answers; nothing here opens a socket or runs a model. Synthetic Oslo
persona; every address is at example.org."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest
from persona import OLA, OLA_ID, resolution
from test_promises import OWNER_EMAIL, OWNER_ID, _by_quote, _run, _transcript
from test_promises import lb as record

from logbook import cli
from logbook.contrib import promises
from logbook.core import attachments
from logbook.core.store import Logbook
from logbook.labs import judge

CRANE = "I will book the crane for next week."
PHOTOS = "I'll send you the mooring photos by Friday."
FORECAST = "Let me check the forecast first."
SEE = "We will see."
lb = record  # the promises tests' record, under the name its tests use


def _verdict(**fields: Any) -> str:
    base: dict[str, Any] = {
        "is_commitment": False,
        "by": "unknown",
        "to": "unknown",
        "what": "",
        "due": None,
        "confidence": 0.7,
    }
    return json.dumps({**base, **fields})


class FakeJudge:
    """Answers by the candidate's words: the photos and the crane are commitments, the forecast a
    weak one, `We will see` none; everything else is a non-commitment at 0.7."""

    name = "fake-judge"

    def __init__(self, model: str = "fake-instruct-4bit", ready: bool = True) -> None:
        self.model = model
        self.prompts: list[list[dict[str, str]]] = []
        self.fetched = 0
        self._ready = ready
        self.offline_seen: list[str | None] = []

    def ready(self) -> bool:
        return self._ready

    def fetch(self) -> None:
        self.fetched += 1
        self._ready = True

    def answer(self, messages: list[dict[str, str]]) -> str:
        self.prompts.append(list(messages))
        self.offline_seen.append(os.environ.get("HF_HUB_OFFLINE"))
        candidate = judge.candidate_of(messages)
        if "mooring photos" in candidate:
            return _verdict(
                is_commitment=True, by="Ola Nordmann", to="owner", what="send the mooring photos",
                due="2026-06-12", confidence=0.92,
            )  # fmt: skip
        if "crane" in candidate:
            return (
                "Sure, here is the JSON:\n```json\n"
                + _verdict(
                    is_commitment=True, by="owner", to="Ola Nordmann", what="book the crane", confidence=0.8
                )
                + "\n```"
            )
        if "forecast" in candidate:
            return _verdict(is_commitment=True, by="owner", what="check the forecast", confidence=0.4)
        if "We will see" in candidate:
            return _verdict(is_commitment=False, confidence=0.95)
        if "Rechnung" in candidate:
            return "I cannot tell."
        return _verdict()


def _cache(lb: Logbook) -> dict[str, Any]:
    path = lb.root / "policy" / "promises-cache.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# -- the prompt --------------------------------------------------------------------------------------


def test_the_prompt_marks_the_candidate_with_its_speaker_the_context_and_the_names(lb: Logbook) -> None:
    report = promises.extract(lb)
    crane = _by_quote(report)[CRANE]
    messages = judge.messages_of(crane, report.owner)
    assert [m["role"] for m in messages] == ["system", "user"]
    user = messages[1]["content"]
    assert judge.candidate_of(messages) == f"you: {CRANE}"
    lines = user.splitlines()
    marked = lines.index(f"> you: {CRANE}")
    assert lines[marked - 2 : marked] == [f"  Ola Nordmann: {PHOTOS}", "  you: Good."]
    assert lines[marked + 1 : marked + 3] == [
        "  Ola Nordmann: Will you be at the marina on Saturday?",
        f"  you: {FORECAST}",
    ]
    assert "Ines Nordmann" in user and "Ola Nordmann" in user and "2026-06-11" in user
    assert "Boat plans" in user
    assert "temperature" not in user  # the sampling is the engine's, not the prompt's
    system = messages[0]["content"]
    for key in ("is_commitment", "by", "to", "what", "due", "confidence"):
        assert f'"{key}"' in system


def test_the_prompt_attributes_a_diarizer_labelled_turn_to_that_speaker_never_to_the_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    segments = [
        {"speaker": {"attribution": "me"}, "text": "Speaker 2: I'll bring the chart."},
        {"speaker": {"attribution": "me"}, "text": "I'll check the tide tables."},
    ]
    blob = json.dumps(segments).encode("utf-8")
    fresh = Logbook.init(tmp_path / "fresh", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(fresh.root))
    meta = fresh.meta
    meta["owner_id"] = OWNER_ID
    meta["owner_emails"] = [OWNER_EMAIL]
    fresh._save_meta(meta)
    fresh.attach(blob)
    fresh.append_many(
        [
            resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
            resolution(("email", OWNER_EMAIL), OWNER_ID, "Ines Nordmann"),
            _transcript(
                "2026-06-16T17:00:00Z",
                "2026-06-16T17:40:00Z",
                "Chart",
                [{"name": "Ola Nordmann", "email": OLA["email"]}],
                attachments.reference(blob, "application/json"),
            ),
        ]
    )
    report = promises.extract(fresh)
    found = _by_quote(report)
    chart = judge.messages_of(found["I'll bring the chart."], report.owner)
    assert judge.candidate_of(chart) == "Speaker 2: I'll bring the chart."
    tide = judge.messages_of(found["I'll check the tide tables."], report.owner)
    assert judge.candidate_of(tide) == "you: I'll check the tide tables."


# -- the answer --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"is_commitment": true, "by": "owner", "to": "Ola Nordmann", "what": "w", "due": null,'
        ' "confidence": 0.8}',
        'Here:\n```json\n{"is_commitment": true, "by": "owner", "to": "Ola Nordmann", "what": "w",'
        ' "due": null, "confidence": 0.8}\n```\nDone.',
        '{"is_commitment": "true", "by": "owner", "to": "Ola Nordmann", "what": "w", "due": "",'
        ' "confidence": "0.8"}',
    ],
)
def test_an_answer_is_read_as_the_first_json_object_in_it_with_lenient_types(text: str) -> None:
    found = judge.judgement_of(text, "m", "2026-06-20T10:00:00Z")
    assert found is not None
    assert (found.is_commitment, found.by, found.to, found.what, found.due, found.confidence) == (
        True, "owner", "Ola Nordmann", "w", None, 0.8,
    )  # fmt: skip
    assert found.model == "m" and found.judged_at == "2026-06-20T10:00:00Z"


@pytest.mark.parametrize(
    "text",
    [
        "I cannot tell.",
        "{not json",
        '{"is_commitment": true}',
        '{"is_commitment": true, "by": "owner", "to": "x", "what": "w", "due": "soon", "confidence": 2}',
        '{"is_commitment": true, "by": "owner", "to": "x", "what": "w", "due": "2026-13-01",'
        ' "confidence": 0.5}',
    ],
)
def test_an_answer_without_a_whole_verdict_is_no_judgement(text: str) -> None:
    assert judge.judgement_of(text, "m", "2026-06-20T10:00:00Z") is None


def test_a_judgement_shows_when_it_is_a_commitment_at_the_threshold_or_above() -> None:
    def verdict(is_commitment: bool, confidence: float) -> promises.Judgement:
        return promises.Judgement(is_commitment, "owner", "unknown", "w", None, confidence, "m", "t")

    assert verdict(True, 0.6).shows() and verdict(True, 0.95).shows()
    assert not verdict(True, 0.59).shows() and not verdict(False, 0.99).shows()
    assert verdict(True, 0.5).shows(0.5)


# -- the run and the cache ---------------------------------------------------------------------------


def test_run_judges_every_unjudged_candidate_once_and_keeps_the_verdicts_in_the_record(
    lb: Logbook,
) -> None:
    report = promises.extract(lb)
    engine = FakeJudge()
    lines = list(lb.lines())
    seen: list[str] = []
    done = judge.run(lb.root, report, engine, progress=seen.append)
    assert done.candidates == 10 and done.judged == 9 and done.unparsed == 1
    assert len(engine.prompts) == 10 and len(seen) == 10
    assert any("1/10" in s for s in seen) and any("10/10" in s for s in seen)
    cache = _cache(lb)
    assert cache["version"] == judge.CACHE_VERSION and len(cache["judgements"]) == 9
    photos = _by_quote(report)[PHOTOS]
    kept = cache["judgements"][photos.id]
    assert kept["model"] == "fake-instruct-4bit" and kept["engine"] == "fake-judge"
    assert kept["is_commitment"] is True and kept["by"] == "Ola Nordmann" and kept["to"] == "owner"
    assert kept["what"] == "send the mooring photos" and kept["due"] == "2026-06-12"
    assert kept["confidence"] == 0.92 and kept["judged_at"].endswith("Z")
    assert list(lb.lines()) == lines  # nothing reached the chain
    again = judge.run(lb.root, promises.extract(lb), FakeJudge(model="another-model"), progress=seen.append)
    assert again.candidates == 1 and again.judged == 0 and again.unparsed == 1  # only the unparsed one
    assert _cache(lb)["judgements"][photos.id]["model"] == "fake-instruct-4bit"  # never re-judged


def test_run_judges_at_most_limit_candidates_oldest_first_and_the_cache_survives_each(lb: Logbook) -> None:
    report = promises.extract(lb)
    engine = FakeJudge()
    done = judge.run(lb.root, report, engine, limit=3)
    assert (done.candidates, done.judged, len(engine.prompts)) == (10, 3, 3)
    assert set(_cache(lb)["judgements"]) == {p.id for p in report.proposals[:3]}
    more = judge.run(lb.root, report, engine, limit=3)  # the sixth candidate gets no verdict
    assert (more.candidates, more.judged, more.unparsed) == (7, 2, 1)
    assert len(_cache(lb)["judgements"]) == 5


def test_no_socket_is_opened_while_judging(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a socket was opened while judging")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    engine = FakeJudge()
    done = judge.run(lb.root, promises.extract(lb), engine)
    assert done.judged == 9
    assert set(engine.offline_seen) == {"1"}  # the hub is told so too, for the real engine's sake
    assert os.environ.get("HF_HUB_OFFLINE") != "1"  # and only for the run


def test_a_model_not_on_this_machine_stops_with_the_flag_that_fetches_it_unless_asked(lb: Logbook) -> None:
    engine = FakeJudge(ready=False)
    report = promises.extract(lb)
    with pytest.raises(judge.ModelMissing, match="--fetch-model"):
        judge.run(lb.root, report, engine)
    assert engine.fetched == 0 and _cache(lb) == {}
    done = judge.run(lb.root, report, engine, fetch_model=True)
    assert engine.fetched == 1 and done.judged == 9


def test_a_cache_that_is_not_json_is_one_clear_error_naming_the_file(lb: Logbook) -> None:
    path = lb.root / "policy" / "promises-cache.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(judge.CacheError, match=r"promises-cache\.json"):
        judge.read_cache(lb.root)


# -- the engine --------------------------------------------------------------------------------------


def _importer(*present: str) -> Any:
    def import_module(name: str) -> Any:
        if name in present:
            return object()
        raise ImportError(name)

    return import_module


def test_without_mlx_lm_the_message_names_the_extra_and_apple_silicon() -> None:
    with pytest.raises(judge.EngineMissing, match=r"openlogbook\[judge\].*Apple silicon"):
        judge.detect(importer=_importer())


def test_with_mlx_lm_the_engine_is_mlx_lm_on_the_default_model_or_the_one_named() -> None:
    engine = judge.detect(importer=_importer("mlx_lm"))
    assert engine.name == "mlx-lm" and engine.model == judge.DEFAULT_MODEL
    assert "4bit" in judge.DEFAULT_MODEL and "Instruct" in judge.DEFAULT_MODEL
    assert judge.detect("example/other-instruct-4bit", importer=_importer("mlx_lm")).model == (
        "example/other-instruct-4bit"
    )


# -- through the CLI ---------------------------------------------------------------------------------


def test_promises_shows_the_rules_by_default_and_the_judge_sets_candidates_aside(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "promises")  # the rules alone: the owner's six, nothing judged yet
    assert out.startswith("6 promises proposed: 6 you made, 0 asked of you") and "judged" not in out
    assert "crane" in out and "forecast" in out and "mooring photos" not in out and "We will see" not in out
    engine = FakeJudge()
    monkeypatch.setattr(judge, "detect", lambda model, **_k: engine)
    lines = list(lb.lines())
    cli.main(["promises", "--judge"])
    captured = capsys.readouterr()
    assert "10/10" in captured.err and "mooring photos" in captured.err  # the progress line
    assert list(lb.lines()) == lines
    first, head, *rows = captured.out.splitlines()
    assert first.startswith("judged 9 candidates with fake-judge (fake-instruct-4bit)")
    assert head.startswith("2 promises proposed: 2 you made, 0 asked of you") and "9 judged" in head
    assert "0.6" in head and "1 unjudged" in head
    assert "1 candidate could not be judged" in captured.out
    assert [r for r in rows if "“" in r] == [r for r in rows if "crane" in r or "Rechnung" in r]
    crane = next(r for r in rows if "crane" in r)
    assert "0.8" in crane and "to Ola Nordmann" in crane
    assert "forecast" not in captured.out and "We will see" not in captured.out
    assert "mooring photos" not in captured.out  # Ola's commitment, judged or not, is not the owner's
    out = _run(capsys, "promises", "--all")
    assert out.startswith("6 promises proposed") and "forecast" in out and "We will see" in out
    assert "0.4" in out and "no 0.95" in out
    photos = next(r for r in out.splitlines() if "mooring photos" in r)
    assert (
        "Ola Nordmann" in photos and "0.92" in photos and "to you" in photos and "due 2026-06-12?" in photos
    )
    out = _run(capsys, "promises", "--since", "2026-06-12")
    assert out.startswith("1 promise proposed since 2026-06-12: 1 you made") and "1 unjudged" in out


def test_promises_json_carries_the_judgement_or_null(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(judge, "detect", lambda model, **_k: FakeJudge())
    cli.main(["promises", "--judge", "--limit", "2", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["all"] is False and out["threshold"] == 0.6 and out["judge"] == {
        "engine": "fake-judge", "model": "fake-instruct-4bit", "candidates": 10, "judged": 2, "unparsed": 0,
    }  # fmt: skip
    assert [p["role"] for p in out["proposals"]] == ["promise"] * 6 and out["unjudged"] == 8
    crane = next(p for p in out["proposals"] if p["quote"] == CRANE)
    assert crane["judgement"]["confidence"] == 0.8
    assert PHOTOS not in {p["quote"] for p in out["proposals"]}
    everything = json.loads(_run(capsys, "promises", "--all", "--json"))
    assert everything["all"] is True and len(everything["proposals"]) == 10
    photos = next(p for p in everything["proposals"] if p["quote"] == PHOTOS)
    assert photos["judgement"]["confidence"] == 0.92 and photos["role"] == "theirs"
    crane = next(p for p in everything["proposals"] if p["quote"] == CRANE)
    assert crane["judgement"]["to"] == "Ola Nordmann" and crane["judgement"]["model"] == "fake-instruct-4bit"
    assert next(p for p in everything["proposals"] if p["quote"] == SEE)["judgement"] is None


def test_done_still_closes_a_candidate_and_is_the_only_write(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(judge, "detect", lambda model, **_k: FakeJudge())
    cli.main(["promises", "--judge"])
    capsys.readouterr()
    before = list(lb.lines())
    photos = _by_quote(promises.extract(lb))[PHOTOS]
    out = _run(capsys, "promises", "done", photos.id)
    assert "done:" in out and "mooring photos" in out
    after = list(lb.lines())
    assert len(after) == len(before) + 1 and after[-1]["kind"] == "task"
    assert after[-1]["payload"]["extra"]["promise"] == photos.id
    assert "done" in next(r for r in _run(capsys, "promises", "--all").splitlines() if "mooring photos" in r)
    assert "mooring photos" not in _run(capsys, "promises", "--all", "--open")


def test_judge_without_an_engine_fails_with_the_message_and_status_2(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(model: str, **_k: Any) -> Any:
        raise judge.EngineMissing(f"no judge engine is installed; install {judge.EXTRA}")

    monkeypatch.setattr(judge, "detect", missing)
    with pytest.raises(SystemExit) as stop:
        cli.main(["promises", "--judge"])
    assert stop.value.code == 2
    assert "openlogbook[judge]" in capsys.readouterr().err
