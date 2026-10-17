"""`review speakers` with voiceprints (RFC 0038 §4.1 rule 2, §4.3, §5): the same voice scores up to 70
against the registry, the owner's voiceprint included, beside the context build 2 scores; voices that
sound alike are one row; `forget` is never proposed, an unnamed person only with `enrol_unnamed`; each
answer updates the registry without a model; a record without recipients is heard for the run, in
memory. Synthetic Oslo persona (`voiceprints_record`); the embedder is a fake, no model is loaded, no
socket opened, and no vector is ever printed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, utc
from speakers_record import CALL, DINNER, KARI, KARI_ID, attribution, message, transcript
from voiceprints_record import FakeEmbedder, as_text, audio_bytes, seal, store_text, stored, voiced_record

from logbook import cli
from logbook.commands import speakers as speakers_command
from logbook.contrib import speakers_review
from logbook.core import attachments, voiceprints
from logbook.core.store import Logbook

LUNCH = "019cadd3-6bc0-7dcd-9133-0000000004b1"  # Thursday: Kari and Ines, and the neighbour again
WALK = "019cadd3-6bc0-7dcd-9133-0000000004b2"  # Friday: the neighbour on the stairs, and Ines
LUNCH_TEXT = [
    ("S1", "Skal vi spise ute?"),
    ("S2", "Ja, det er fint vær."),
    ("S1", "Jeg tar med kaffe."),
    ("S2", "Takk."),
    ("S3", "Hei igjen, det var meg med pakken."),
    ("S3", "Ha en fin dag."),
]
WALK_TEXT = [
    ("S1", "God morgen."),
    ("S2", "Hei, er pakken kommet fram?"),
    ("S1", "Ja, tusen takk."),
    ("S2", "Bra, vi ses."),
]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The dinner and the call, sealed, and the registry as `derive transcripts` leaves it."""
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = seal(Logbook.init(root, TZ), monkeypatch, tmp_path)
    voiced_record(lb)
    voiceprints.update(Logbook(root), FakeEmbedder())
    return Logbook(root)


def _recording(lb: Logbook, id_: str, day: str, title: str, said: list, voices: dict[str, str]) -> None:
    content, spans = store_text(lb, said)
    sound = audio_bytes(said, voices)
    lb.attach(sound)
    labels = list(dict.fromkeys(label for label, _t in said))
    room = [
        {"label": label, "seconds": 8.0, "turns": sum(1 for x, _t in said if x == label)} for label in labels
    ]
    lb.append_many(
        [
            transcript(
                id_,
                utc(day, "12:00"),
                utc(day, "12:30"),
                title,
                room,
                content=content,
                spans=spans,
                audio=attachments.digest(sound),
            )
        ]
    )


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    cli.main(["review", "speakers", *args, "--json"])
    return json.loads(capsys.readouterr().out)


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["review", "speakers", *args])
    return capsys.readouterr().out


def _row(data: dict[str, Any], ref: str) -> dict[str, Any]:
    return next(row for row in data["rows"] if ref in [v["ref"] for v in row["voices"]])


def _written(lb: Logbook, since: int) -> list[dict[str, Any]]:
    """The lines after `since`, opened: the record is sealed."""
    fresh = Logbook(lb.root)
    return [fresh.opened(line) for line in fresh.lines() if int(line["seq"]) > since]


def _no_vector(text: str) -> None:
    assert not any(t in text for who in ("ines", "kari", "ola", "neighbour") for t in as_text(stored(who)))


# -- the score ---------------------------------------------------------------------------------------------


def test_the_owner_is_proposed_by_their_voice_first_and_context_still_scores_the_guests(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys)
    first = data["rows"][0]
    assert [v["ref"] for v in first["voices"]] == [f"{DINNER}#S1"], "the owner's row comes first"
    you = first["candidates"][0]
    assert (you["owner"], you["score"], you["matched"], you["evidence"]) == (
        True,
        70,
        ["same voice 1.00"],
        [],
    )
    assert you["person"] == Logbook(lb.root).meta["owner_id"]
    kari = _row(data, f"{DINNER}#S2")["candidates"][0]
    assert (kari["name"], kari["score"]) == ("Kari Nordmann", 20), "no voiceprint of Kari yet: context alone"
    assert _row(data, f"{CALL}#system")["candidates"][0]["score"] == 40
    text = _run(capsys)
    assert text.splitlines()[2].strip() == "→ you: same voice 1.00"
    _no_vector(text)
    _no_vector(json.dumps(data))


def test_accepting_the_owner_writes_the_score_and_the_registry_follows_without_a_model(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    since = int(lb.meta["seq"])
    _run(capsys, "--all-above", "70")
    (line,) = _written(lb, since)
    payload = line["payload"]
    assert payload["entity"]["id"] == lb.meta["owner_id"] and payload["basis"] == "voice"
    assert payload["extra"]["score"] == 70 and payload["extra"]["matched"] == ["same voice 1.00"]
    assert "consent" not in payload and "label" not in payload
    found = voiceprints.read(Logbook(lb.root))
    assert found is not None and found.people[lb.meta["owner_id"]].refs == sorted(
        [f"{CALL}#mic", f"{DINNER}#S1"]
    )


def test_a_guest_named_once_is_recognised_the_next_time_above_the_context_cap(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "--name", "2", "Kari Nordmann", "--consent", "2=yes")
    _recording(lb, LUNCH, "2026-10-08", "Lunsj", LUNCH_TEXT, {"S1": "kari", "S2": "ines", "S3": "neighbour"})
    voiceprints.update(Logbook(lb.root), FakeEmbedder())  # as `derive transcripts` ends
    data = _json(capsys)
    kari = _row(data, f"{LUNCH}#S1")["candidates"][0]
    assert (kari["person"], kari["score"], kari["matched"][0]) == (KARI_ID, 70, "same voice 1.00")
    assert _row(data, f"{LUNCH}#S2")["candidates"][0]["owner"] is True
    since = int(Logbook(lb.root).meta["seq"])
    _run(capsys, "--all-above", "70")
    assert {line["payload"]["ref"]["value"] for line in _written(lb, since)} >= {f"{LUNCH}#S1", f"{LUNCH}#S2"}


def test_the_same_voice_and_the_context_add_up_past_seventy(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cap of 40 holds context alone; with the same voice the context is added to the 70."""
    _run(capsys, "--name", "2", "Kari Nordmann")
    _recording(lb, LUNCH, "2026-10-08", "Lunsj", LUNCH_TEXT, {"S1": "kari", "S2": "ines", "S3": "neighbour"})
    Logbook(lb.root).append(**_draft(message(utc("2026-10-08", "11:20"), KARI["phone"], "Kommer kl 12.")))
    voiceprints.update(Logbook(lb.root), FakeEmbedder())
    kari = _row(_json(capsys), f"{LUNCH}#S1")["candidates"][0]
    assert (kari["person"], kari["score"]) == (KARI_ID, 75)
    assert kari["matched"] == ["same voice 1.00", "seen that day (message 11:20)"]


def test_a_retracted_answer_counts_for_nothing_before_the_file_is_written_again(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lb.append(**_draft(attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann")))
    voiceprints.update(Logbook(lb.root))
    _recording(lb, LUNCH, "2026-10-08", "Lunsj", LUNCH_TEXT, {"S1": "kari", "S2": "ines", "S3": "neighbour"})
    voiceprints.update(Logbook(lb.root), FakeEmbedder())
    answer = next(
        line
        for line in _written(lb, 0)
        if line["kind"] == "resolution" and line["payload"]["ref"]["value"] == f"{DINNER}#S2"
    )
    Logbook(lb.root).retract(int(answer["seq"]), "not her")  # the file still says Kari: the queue does not
    data = _json(capsys)
    assert not any(
        c["person"] == KARI_ID and c["score"] >= 70 for c in _row(data, f"{LUNCH}#S1")["candidates"]
    )
    assert _row(data, f"{DINNER}#S2")["voices"][0]["ref"] == f"{DINNER}#S2", "back in the queue"


# -- the observed voice: one row for one voice heard twice -------------------------------------------------


def test_one_unknown_voice_in_two_recordings_is_one_row(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _recording(lb, LUNCH, "2026-10-08", "Lunsj", LUNCH_TEXT, {"S1": "kari", "S2": "ines", "S3": "neighbour"})
    _recording(lb, WALK, "2026-10-09", "Trappa", WALK_TEXT, {"S1": "ines", "S2": "neighbour"})
    voiceprints.update(Logbook(lb.root), FakeEmbedder())
    data = _json(capsys)
    row = _row(data, f"{LUNCH}#S3")
    assert sorted(v["ref"] for v in row["voices"]) == [f"{LUNCH}#S3", f"{WALK}#S2"]
    assert row["key"]["kind"] == "same voice" and row["candidates"] == []
    since = int(Logbook(lb.root).meta["seq"])
    _run(capsys, "--unnamed", str(row["number"]))
    lines = _written(lb, since)
    assert len(lines) == 2 and len({line["payload"]["entity"]["id"] for line in lines}) == 1
    assert all(line["payload"]["unnamed"] is True for line in lines)
    found = voiceprints.read(Logbook(lb.root))
    assert found is not None and not any(ref in found.pool() for ref in (f"{LUNCH}#S3", f"{WALK}#S2")), (
        "enrol_unnamed is false: a stranger the owner would not name is not kept"
    )


def test_two_voices_of_one_recording_are_never_one_row(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _recording(lb, WALK, "2026-10-09", "Trappa", WALK_TEXT, {"S1": "neighbour", "S2": "neighbour"})
    voiceprints.update(Logbook(lb.root), FakeEmbedder())
    data = _json(capsys)
    assert _row(data, f"{WALK}#S1")["number"] != _row(data, f"{WALK}#S2")["number"]


# -- forget, enrol_unnamed, a no ---------------------------------------------------------------------------


def _settings(lb: Logbook, **given: object) -> None:
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "speakers.json").write_text(json.dumps(given), encoding="utf-8")


def test_forget_is_never_proposed_by_voice_nor_held(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "--name", "2", "Kari Nordmann")
    _settings(lb, forget=[KARI_ID])
    _recording(lb, LUNCH, "2026-10-08", "Lunsj", LUNCH_TEXT, {"S1": "kari", "S2": "ines", "S3": "neighbour"})
    voiceprints.update(Logbook(lb.root), FakeEmbedder())
    data = _json(capsys)
    assert all(c["person"] != KARI_ID for row in data["rows"] for c in row["candidates"])
    found = voiceprints.read(Logbook(lb.root))
    assert found is not None and KARI_ID not in found.people and f"{DINNER}#S2" not in found.pool()


def test_an_unnamed_person_is_proposed_again_only_with_enrol_unnamed(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _recording(lb, LUNCH, "2026-10-08", "Lunsj", LUNCH_TEXT, {"S1": "kari", "S2": "ines", "S3": "neighbour"})
    voiceprints.update(Logbook(lb.root), FakeEmbedder())
    _run(capsys, "--unnamed", str(_row(_json(capsys), f"{LUNCH}#S3")["number"]))
    _recording(lb, WALK, "2026-10-09", "Trappa", WALK_TEXT, {"S1": "ines", "S2": "neighbour"})
    voiceprints.update(Logbook(lb.root), FakeEmbedder())
    assert _row(_json(capsys), f"{WALK}#S2")["candidates"] == [], "enrol_unnamed false: not recognised"
    _settings(lb, enrol_unnamed=True)
    voiceprints.update(Logbook(lb.root), FakeEmbedder())  # the voice the file let go, heard again
    row = _row(_json(capsys), f"{WALK}#S2")
    same = row["candidates"][0]
    assert (same["unnamed"], same["name"], same["score"]) == (True, None, 70)
    assert "→ the same unnamed person: same voice 1.00" in _run(capsys)
    since = int(Logbook(lb.root).meta["seq"])
    _run(capsys, "--accept", str(row["number"]))
    (line,) = _written(lb, since)
    assert line["payload"]["unnamed"] is True and line["payload"]["entity"]["id"] == same["person"]


def test_a_no_to_the_owner_is_never_proposed_again(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "--reject", "1")
    row = _row(_json(capsys), f"{DINNER}#S1")
    assert not any(c["owner"] for c in row["candidates"])


# -- a record without recipients: heard for the run ----------------------------------------------------------


def test_a_record_without_recipients_is_heard_for_the_run_and_nothing_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    root = tmp_path / "open"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    voiced_record(Logbook.init(root, TZ))
    report = speakers_review.read(Logbook(root))  # no model here: context alone
    assert not any(c.owner for row in report.rows for c in row.candidates)
    embedder = FakeEmbedder()
    monkeypatch.setattr(speakers_command, "hearing", lambda lb: lambda: embedder)
    data = _json(capsys)
    assert data["rows"][0]["candidates"][0]["owner"] is True and embedder.loaded
    _run(capsys, "--accept", "1")
    assert not (root / voiceprints.FILE).exists() and no_network == []


def test_a_registry_this_machine_cannot_open_is_no_voiceprint(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (lb.root / voiceprints.FILE).write_bytes(b"age-encryption.org/v1\nnot really")
    data = _json(capsys)
    assert not any(c["owner"] for row in data["rows"] for c in row["candidates"])


def _draft(line: dict) -> dict:
    return {k: line[k] for k in ("at", "source", "kind", "tier", "payload")}
