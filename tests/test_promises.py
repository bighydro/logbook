"""`logbook promises`: commitments proposed from transcript/v1 and note/v1 text by rules alone, never
stated as facts; `promises done <id>` closes one with a task/v1 line (RFC 0016). Synthetic Oslo
persona; every address is at example.org."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from persona import KARI, KARI_ID, OLA, OLA_ID, resolution

from logbook import attachments, cli, promises
from logbook.store import Logbook

OWNER_ID = "019cadd3-6bc0-7dcd-9133-000000000099"
OWNER_EMAIL = "ines@example.org"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _transcript(
    at: str, end: str, title: str, participants: list[dict[str, str]], content: dict[str, Any]
) -> dict[str, Any]:
    return {
        "at": at,
        "end": end,
        "source": "granola",
        "kind": "transcript",
        "tier": 2,
        "payload": {
            "schema": "transcript/v1",
            "provider": "granola",
            "raw_id": f"t-{at}",
            "title": title,
            "participants": participants,
            "content": content,
        },
    }


def _note(at: str, text: str, **payload: Any) -> dict[str, Any]:
    return {
        "at": at,
        "source": payload.pop("source", "manual"),
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text, **payload},
    }


BOAT_PLANS = (
    "# Boat plans\n\n"
    "Ola Nordmann: The mooring lines are fine. I'll send you the mooring photos by Friday.\n"
    "Ines: Good. I will book the crane for next week.\n"
    "Ola Nordmann: Will you be at the marina on Saturday?\n"
    "Ines: Let me check the forecast first.\n"
)
TROMSO = [
    {"speaker": {"name": "Kari Nordmann"}, "text": "Ich melde mich bis Montag wegen Tromsø."},
    {"speaker": {"attribution": "me"}, "text": "Ich schicke dir die Liste morgen."},
    {"speaker": {"diarization_label": "Speaker A"}, "text": "We will see."},
]
YARD = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Ola Nordmann>I'll call the yard tomorrow.\n"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    meta = lb.meta
    meta["owner_id"] = OWNER_ID
    meta["owner_emails"] = [OWNER_EMAIL]
    lb._save_meta(meta)
    boat = BOAT_PLANS.encode("utf-8")
    tromso = json.dumps(TROMSO, ensure_ascii=False).encode("utf-8")
    yard = YARD.encode("utf-8")
    for blob in (boat, tromso, yard):
        lb.attach(blob)
    missing = attachments.reference(b"never stored", "text/plain")
    drafts = [
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        resolution(("email", OWNER_EMAIL), OWNER_ID, "Ines Nordmann"),
        _transcript(
            "2026-06-11T12:00:00Z",
            "2026-06-11T12:30:00Z",
            "Boat plans",
            [{"name": "Ola Nordmann", "email": OLA["email"]}, {"name": "Ines", "email": OWNER_EMAIL}],
            attachments.reference(boat, "text/markdown"),
        ),
        _transcript(
            "2026-06-12T07:00:00Z",
            "2026-06-12T07:10:00Z",
            "Yard",
            [{"name": "Ola Nordmann", "email": OLA["email"]}],
            attachments.reference(yard, "text/vtt"),
        ),
        _note("2026-06-13T17:00:00Z", "Anchored in the bay. I need to order the new bilge pump next week."),
        _note("2026-06-14T09:00:00Z", "Ich muss die Rechnung bis 20. Juni bezahlen."),
        _note("2026-06-14T10:00:00Z", "I will not forget the chart again. I'll bring the chart, right?"),
        _note(
            "2026-06-15T06:00:00Z",
            "I'll paint the hull.",
            source="ios-notes",
            raw_id="h@2026-06-15T06:00:00Z",
        ),
        _transcript(
            "2026-06-16T17:00:00Z",
            "2026-06-16T17:40:00Z",
            "Tromsø",
            [{"name": "Kari Nordmann", "email": KARI["email"]}],
            attachments.reference(tromso, "application/json"),
        ),
        _transcript("2026-06-17T08:00:00Z", "2026-06-17T08:20:00Z", "Lost", [], missing),
        _note("2026-06-18T06:00:00Z", "I'll retract this one."),
    ]
    lb.append_many(drafts)
    hull = next(line for line in lb.lines() if line["payload"].get("raw_id") == "h@2026-06-15T06:00:00Z")
    retracted = next(line for line in lb.lines() if line["payload"].get("text") == "I'll retract this one.")
    lb.append_many(
        [
            _note(
                "2026-06-15T06:00:00Z",
                "I'll paint the hull in August.",
                source="ios-notes",
                raw_id="h@2026-06-15T09:00:00Z",
                supersedes=hull["id"],
            )
        ]
    )
    lb.retract(int(retracted["seq"]), "not a promise")
    return lb


# -- the rules ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "cue", "phrase_class"),
    [
        ("I'll send the photos.", "I'll", "future"),
        ("I will book the crane.", "I will", "future"),
        ("I'm going to write it up.", "I'm going to", "future"),
        ("We'll get back to you on the price.", "We'll", "future"),
        ("We will send the invoice.", "We will", "future"),
        ("I need to order the pump.", "I need to", "obligation"),
        ("I have to call the yard.", "I have to", "obligation"),
        ("I must renew the insurance.", "I must", "obligation"),
        ("We need to fix the pump.", "We need to", "obligation"),
        ("Let me check the forecast.", "Let me", "offer"),
        ("I promise to bring the chart.", "I promise", "future"),
    ],
)
def test_english_phrase_classes(sentence: str, cue: str, phrase_class: str) -> None:
    found = promises.find(sentence)
    assert [(m.cue, m.phrase_class, m.language) for m in found] == [(cue, phrase_class, "en")]
    assert found[0].quote == sentence


@pytest.mark.parametrize(
    ("sentence", "cue", "phrase_class"),
    [
        ("Ich schicke dir die Liste.", "Ich schicke", "future"),
        ("Ich melde mich wegen Tromsø.", "Ich melde mich", "future"),
        ("Ich werde das Boot streichen.", "Ich werde", "future"),
        ("Wir werden die Rechnung schicken.", "Wir werden", "future"),
        ("Ich kümmere mich um den Kran.", "Ich kümmere mich", "future"),
        ("Ich muss die Rechnung bezahlen.", "Ich muss", "obligation"),
        ("Wir müssen das Segel flicken.", "Wir müssen", "obligation"),
        ("Ich rufe die Werft an.", "Ich rufe", "future"),
    ],
)
def test_german_phrase_classes(sentence: str, cue: str, phrase_class: str) -> None:
    found = promises.find(sentence)
    assert [(m.cue, m.phrase_class, m.language) for m in found] == [(cue, phrase_class, "de")]


@pytest.mark.parametrize(
    "text",
    [
        "I will not forget the chart again.",
        "I'll never do that again.",
        "Ich werde nicht kommen.",
        "I'll bring the chart, right?",
        "Will I ever learn?",
        "He will send the photos.",
        "They'll get back to us.",
        "The forecast is fine.",
    ],
)
def test_negations_questions_and_third_persons_are_not_promises(text: str) -> None:
    assert promises.find(text) == []


def test_one_proposal_per_sentence_and_the_quote_is_the_sentence() -> None:
    found = promises.find("The lines are fine. I'll send the photos by Friday. I'll call tomorrow.")
    assert [m.quote for m in found] == ["I'll send the photos by Friday.", "I'll call tomorrow."]
    assert [m.due_phrase for m in found] == ["by Friday", "tomorrow"]


@pytest.mark.parametrize(
    ("sentence", "phrase", "day", "due"),
    [
        ("I'll send it by Friday.", "by Friday", "2026-06-11", "2026-06-12"),
        ("I'll send it by Friday.", "by Friday", "2026-06-12", "2026-06-19"),
        ("I'll send it on Monday.", "on Monday", "2026-06-13", "2026-06-15"),
        ("I'll send it next Tuesday.", "next Tuesday", "2026-06-16", "2026-06-23"),
        ("I'll send it tomorrow.", "tomorrow", "2026-06-12", "2026-06-13"),
        ("I'll send it tonight.", "tonight", "2026-06-12", "2026-06-12"),
        ("I'll send it next week.", "next week", "2026-06-11", "2026-06-15"),
        ("I'll send it this week.", "this week", "2026-06-10", "2026-06-12"),
        ("I'll send it by the end of the week.", "by the end of the week", "2026-06-13", "2026-06-19"),
        ("I'll send it in two weeks.", "in two weeks", "2026-06-11", "2026-06-25"),
        ("I'll send it in 3 days.", "in 3 days", "2026-06-11", "2026-06-14"),
        ("I'll send it next month.", "next month", "2026-06-11", "2026-07-01"),
        ("I'll send it by June 20.", "by June 20", "2026-06-11", "2026-06-20"),
        ("I'll send it by 20 June.", "by 20 June", "2026-06-11", "2026-06-20"),
        ("I'll send it by January 5.", "by January 5", "2026-06-11", "2027-01-05"),
        ("I'll send it on the 5th.", "on the 5th", "2026-06-11", "2026-07-05"),
        ("Ich melde mich bis Montag.", "bis Montag", "2026-06-16", "2026-06-22"),
        ("Ich schicke es morgen.", "morgen", "2026-06-16", "2026-06-17"),
        ("Ich schicke es heute Abend.", "heute Abend", "2026-06-16", "2026-06-16"),
        ("Ich melde mich nächste Woche.", "nächste Woche", "2026-06-16", "2026-06-22"),
        ("Ich melde mich in zwei Wochen.", "in zwei Wochen", "2026-06-16", "2026-06-30"),
        ("Ich muss bis 20. Juni bezahlen.", "bis 20. Juni", "2026-06-14", "2026-06-20"),
        ("Ich muss bis zum 20.6. bezahlen.", "bis zum 20.6.", "2026-06-14", "2026-06-20"),
        ("Ich muss bis Ende der Woche bezahlen.", "bis Ende der Woche", "2026-06-14", "2026-06-19"),
        ("Ich melde mich am Dienstag.", "am Dienstag", "2026-06-16", "2026-06-23"),
    ],
)
def test_due_hints_resolve_against_the_day_they_were_said(
    sentence: str, phrase: str, day: str, due: str
) -> None:
    (found,) = promises.find(sentence)
    assert found.due_phrase == phrase
    assert promises.due_of(phrase, date.fromisoformat(day)) == date.fromisoformat(due)


def test_a_sentence_with_no_date_phrase_has_no_due() -> None:
    (found,) = promises.find("I'll send the photos.")
    assert found.due_phrase is None


# -- the command -------------------------------------------------------------------------------------


def _by_quote(report: promises.Report) -> dict[str, promises.Proposal]:
    return {p.match.quote: p for p in report.proposals}


def test_extract_reads_transcripts_and_notes_with_speaker_day_line_and_due(lb: Logbook) -> None:
    report = promises.extract(lb)
    found = _by_quote(report)
    assert set(found) == {
        "I'll send you the mooring photos by Friday.",
        "I will book the crane for next week.",
        "Let me check the forecast first.",
        "I'll call the yard tomorrow.",
        "I need to order the new bilge pump next week.",
        "Ich muss die Rechnung bis 20. Juni bezahlen.",
        "I'll paint the hull in August.",
        "Ich melde mich bis Montag wegen Tromsø.",
        "Ich schicke dir die Liste morgen.",
        "We will see.",
    }
    lines = {line["id"]: line for line in lb.lines()}
    ola = found["I'll send you the mooring photos by Friday."]
    assert (
        ola.day == "2026-06-11"
        and ola.kind == "transcript"
        and lines[ola.line]["payload"]["title"] == "Boat plans"
    )
    assert ola.speaker is not None
    assert (ola.speaker.label, ola.speaker.person, ola.speaker.spoken) == (
        "Ola Nordmann",
        OLA_ID,
        "Ola Nordmann",
    )
    assert ola.direction == "owed_to_owner" and ola.due == "2026-06-12" and ola.status == "open"
    ines = found["I will book the crane for next week."]
    assert ines.speaker is not None and ines.speaker.person == OWNER_ID and ines.speaker.owner
    assert ines.direction == "owed_by_owner" and ines.due == "2026-06-15"
    assert found["Let me check the forecast first."].match.phrase_class == "offer"
    yard = found["I'll call the yard tomorrow."]
    assert yard.speaker is not None and yard.speaker.label == "Ola Nordmann" and yard.due == "2026-06-13"
    pump = found["I need to order the new bilge pump next week."]
    assert (
        pump.kind == "note" and pump.speaker is not None and pump.speaker.owner and pump.day == "2026-06-13"
    )
    assert pump.direction == "owed_by_owner" and pump.due == "2026-06-15"
    rechnung = found["Ich muss die Rechnung bis 20. Juni bezahlen."]
    assert rechnung.match.language == "de" and rechnung.due == "2026-06-20"
    kari = found["Ich melde mich bis Montag wegen Tromsø."]
    assert kari.speaker is not None and kari.speaker.person == KARI_ID and kari.due == "2026-06-22"
    me = found["Ich schicke dir die Liste morgen."]
    assert (
        me.speaker is not None and me.speaker.owner and me.speaker.spoken == "me" and me.due == "2026-06-17"
    )
    unknown = found["We will see."]
    assert (
        unknown.speaker is not None
        and unknown.speaker.person is None
        and unknown.speaker.spoken == "Speaker A"
    )
    assert unknown.direction is None
    assert report.skipped == {"transcripts_without_text": 1}
    assert report.extractor == {"name": "rules", "version": promises.RULES.version, "languages": ["en", "de"]}
    assert [p.day for p in report.proposals] == sorted(p.day for p in report.proposals)
    assert len({p.id for p in report.proposals}) == len(report.proposals)
    assert all(len(p.id) == 16 for p in report.proposals)


def test_ids_are_stable_across_extractors_that_quote_the_same_sentence(lb: Logbook) -> None:
    found = _by_quote(promises.extract(lb))
    ola = found["I'll send you the mooring photos by Friday."]
    assert ola.id == promises.proposal_id(ola.line, "  i'll send you the  mooring photos by friday.  ")
    assert ola.id != promises.proposal_id(ola.line, "another sentence")


def test_promises_prints_proposals_never_facts(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "promises")
    head = out.splitlines()[0]
    assert head.startswith("10 proposed promises") and "rules" in head and "not facts" in head
    row = next(line for line in out.splitlines() if "mooring photos" in line)
    assert "2026-06-11" in row and "14:00" in row and "Ola Nordmann" in row and "due 2026-06-12?" in row
    found = _by_quote(promises.extract(lb))
    assert found["I'll send you the mooring photos by Friday."].id in row
    row = next(line for line in out.splitlines() if "bilge pump" in line)
    assert "you" in row and "2026-06-13" in row
    row = next(line for line in out.splitlines() if "We will see" in line)
    assert "Speaker A" in row
    assert "1 transcript" in out and "not in the attachment store" in out
    assert "I'll retract this one" not in out and "I'll paint the hull." not in out
    assert "logbook promises done <id>" in out


def test_promises_json_is_the_report(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = json.loads(_run(capsys, "promises", "--json"))
    assert set(out) == {"since", "open_only", "extractor", "proposals", "skipped"}
    assert out["since"] is None and out["open_only"] is False
    assert out["extractor"]["name"] == "rules" and out["skipped"] == {"transcripts_without_text": 1}
    row = next(p for p in out["proposals"] if "mooring" in p["quote"])
    assert set(row) == {
        "id",
        "status",
        "closed_by",
        "day",
        "at",
        "line",
        "seq",
        "kind",
        "source",
        "title",
        "speaker",
        "direction",
        "certainty",
        "language",
        "cue",
        "class",
        "quote",
        "due",
    }
    assert row["speaker"] == {
        "label": "Ola Nordmann",
        "spoken": "Ola Nordmann",
        "person": OLA_ID,
        "owner": False,
    }
    assert row["due"] == {"phrase": "by Friday", "date": "2026-06-12"}
    assert row["certainty"] == "inferred" and row["status"] == "open" and row["closed_by"] is None
    assert row["title"] == "Boat plans" and row["source"] == "granola" and row["cue"] == "I'll"
    note = next(p for p in out["proposals"] if "bilge" in p["quote"])
    assert note["speaker"]["owner"] is True and note["title"] is None and note["due"]["phrase"] == "next week"
    assert (
        next(p for p in out["proposals"] if "photos." in p["quote"] or "forecast" in p["quote"])["due"]
        is None
    )


def test_since_limits_to_lines_from_that_local_day(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = json.loads(_run(capsys, "promises", "--since", "2026-06-14", "--json"))
    assert out["since"] == "2026-06-14"
    assert all(p["day"] >= "2026-06-14" for p in out["proposals"]) and len(out["proposals"]) == 5
    assert out["skipped"] == {"transcripts_without_text": 1}
    with pytest.raises(SystemExit) as e:
        cli.main(["promises", "--since", "yesterday"])
    assert e.value.code == 2


def test_done_writes_a_task_line_and_open_hides_it(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    found = _by_quote(promises.extract(lb))
    ola = found["I'll send you the mooring photos by Friday."]
    seq = lb.meta["seq"]
    out = _run(capsys, "promises", "done", ola.id, "--note", "photos came Thursday")
    assert f"#{seq + 1}" in out and "done" in out and "mooring photos" in out
    task = lb.line_by_seq(seq + 1)
    assert task is not None
    assert (task["source"], task["kind"], task["tier"], task["end"]) == ("manual", "task", 2, None)
    payload = task["payload"]
    assert payload["schema"] == "task/v1" and payload["status"] == "done"
    assert payload["raw_id"] == f"promise:{ola.id}@{task['at']}"
    assert payload["title"] == "I'll send you the mooring photos by Friday."
    assert payload["completed_at"] == task["at"] and payload["list"] == "promises"
    assert payload["notes"] == "photos came Thursday" and payload["due"] == "2026-06-12"
    assert payload["extra"] == {
        "promise": ola.id,
        "origin": ola.line,
        "speaker": "Ola Nordmann",
        "extractor": {"name": "rules", "version": promises.RULES.version, "languages": ["en", "de"]},
    }
    assert lb.verify()[2] == []
    listed = json.loads(_run(capsys, "promises", "--json"))
    row = next(p for p in listed["proposals"] if p["id"] == ola.id)
    assert row["status"] == "done" and row["closed_by"] == task["id"]
    assert len(listed["proposals"]) == 10
    open_only = json.loads(_run(capsys, "promises", "--open", "--json"))
    assert open_only["open_only"] is True
    assert ola.id not in {p["id"] for p in open_only["proposals"]} and len(open_only["proposals"]) == 9
    text = _run(capsys, "promises", "--open")
    assert text.startswith("9 proposed promises") and "mooring photos" not in text
    text = _run(capsys, "promises")
    assert "done" in next(line for line in text.splitlines() if "mooring photos" in line)


def test_done_twice_appends_nothing_and_an_unknown_id_is_refused(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    found = _by_quote(promises.extract(lb))
    pump = found["I need to order the new bilge pump next week."]
    _run(capsys, "promises", "done", pump.id)
    seq = lb.meta["seq"]
    out = _run(capsys, "promises", "done", pump.id)
    assert "already done" in out and lb.meta["seq"] == seq
    with pytest.raises(SystemExit) as e:
        cli.main(["promises", "done", "0123456789abcdef"])
    assert e.value.code == 2
    assert "no proposal 0123456789abcdef" in capsys.readouterr().err
    assert lb.meta["seq"] == seq


def test_a_record_with_nothing_to_propose_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append("2026-06-01T10:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Calm day."})
    assert _run(capsys, "promises").startswith("no promises proposed")
    assert json.loads(_run(capsys, "promises", "--json"))["proposals"] == []


class _Fake:
    """A stand-in for a later local-model extractor: the same contract, another reading."""

    name = "fake-model"
    version = "0"

    def __call__(self, text: str) -> list[promises.Match]:
        if "crane" not in text:
            return []
        return [promises.Match("book the crane", "crane", "future", "en", None, "2026-06-20")]


def test_the_extractor_is_replaceable_without_changing_the_report(lb: Logbook) -> None:
    report = promises.extract(lb, extractor=_Fake())
    assert report.extractor == {"name": "fake-model", "version": "0"}
    (only,) = report.proposals
    assert only.match.quote == "book the crane" and only.due == "2026-06-20"
    assert only.speaker is not None and only.speaker.owner and only.kind == "transcript"
    assert only.id == promises.proposal_id(only.line, "book the crane")
