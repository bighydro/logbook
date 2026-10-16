"""`logbook review speakers` (RFC 0038 §4): the voices not yet named, keyed by the strongest identifier
they carry, scored without a voiceprint, numbered; the owner's say, each answer one line per voice
through the review's own writer, every number checked before the first line; a wrong answer
corrected by a line that supersedes, a wrong yes by a retraction. Synthetic Oslo persona
(`speakers_record`): no model, no audio decoded, no socket."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from persona import HOME, TZ, dwell, utc
from speakers_record import (
    CALL,
    CALL_DAY,
    CALL_LINE,
    DINNER,
    DINNER_DAY,
    KARI,
    KARI_ID,
    OLA,
    OLA_ID,
    ROOM,
    attribution,
    dinner_record,
    message,
    people,
    resolution,
    transcript,
)

from logbook import cli
from logbook.contrib import speakers_review
from logbook.core import people as people_reader
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "resolution-v1-speaker.schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    dinner_record(lb)
    return lb


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["review", "speakers", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    return json.loads(_run(capsys, *args, "--json"))


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "speakers", *args])
    assert e.value.code == 2
    return capsys.readouterr().err


def _written(lb: Logbook, since: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > since]


def _seq(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


# -- the queue ---------------------------------------------------------------------------------------------


def test_the_queue_keys_scores_and_numbers_the_voices_not_yet_named(lb: Logbook, capsys) -> None:
    out = _run(capsys).splitlines()
    assert out[0] == "4 voices not yet named in 2 recordings, 4 rows · 0 named · tier 2"
    assert out[1].startswith("   1  [20]  Sat 2026-10-03 19:40")
    assert '"Middag" · S1 · 31 min · "Har du sett hvor høyt vannet står?"' in out[1]
    assert (
        out[2]
        .strip()
        .startswith('→ Kari Nordmann: on the entry "Middag med Kari" · seen that day (message 18:02)')
    )
    assert "as good for S2, S3 of the recording" in out[2], "context is the recording's, not the voice's"
    assert out[3].strip() == "that day: Kari Nordmann (message, calendar)"
    assert out[4].startswith("   2  [20]  same recording · S2 · 14 min")
    four = next(row for row in out if row.startswith("   4"))
    assert "[40]" in four and '"Samtale" · system · 3 min · "I\'ll call the yard tomorrow."' in four
    assert out[out.index(four) + 1].strip() == "→ Ola Nordmann: the far end of the call 09:15"
    assert out[-1].startswith("nothing written: `review speakers --accept N[,N]`")
    assert not any("you" in row.split("→")[-1] for row in out if "→" in row), (
        "the owner is proposed by nothing"
    )


def test_the_json_carries_stable_ids_the_evidence_and_the_counts(lb: Logbook, capsys) -> None:
    data = _json(capsys)
    assert (data["not_yet_named"], data["recordings"], data["named"], data["tier"]) == (4, 2, 0, 2)
    far = data["rows"][3]
    refs = [f"{CALL}#system"]
    assert far["id"] == hashlib.sha256("\n".join(sorted(refs)).encode()).hexdigest()[:16]
    assert far["key"] == {"kind": "phone", "value": OLA["phone"]}
    assert far["candidates"] == [
        {
            "id": OLA_ID,
            "person": OLA_ID,
            "name": "Ola Nordmann",
            "owner": False,
            "score": 40,
            "matched": ["the far end of the call 09:15"],
            "evidence": [CALL_LINE],
        }
    ]
    assert data["rows"][0]["shared"] == ["S2", "S3"]
    assert [v["ref"] for v in data["rows"][0]["voices"]] == [f"{DINNER}#S1"]
    assert _json(capsys)["rows"][3]["id"] == far["id"], "the same row, the same id"


def test_a_from_me_voice_is_the_owners_and_never_asked(lb: Logbook, capsys) -> None:
    refs = [v["ref"] for row in _json(capsys)["rows"] for v in row["voices"]]
    assert f"{CALL}#mic" not in refs


def test_the_far_end_of_calls_with_one_number_is_one_row(lb: Logbook, capsys) -> None:
    again = "019cadd3-6bc0-7dcd-9133-0000000004b9"
    from speakers_record import TWO_CHANNELS, call

    lb.append_many(
        [
            call(utc("2026-10-07", "12:00"), OLA["phone"], 300, id_="019cadd3-6bc0-7dcd-9133-0000000004e9"),
            transcript(
                again, utc("2026-10-07", "12:00"), utc("2026-10-07", "12:05"), "Samtale", TWO_CHANNELS
            ),
        ]
    )
    rows = _json(capsys)["rows"]
    far = [r for r in rows if r["key"] == {"kind": "phone", "value": OLA["phone"]}]
    assert len(far) == 1 and [v["number"] for v in far[0]["voices"]] == ["4.1", "4.2"]
    text = _run(capsys)
    assert "a voice in 2 recordings" in text and "      4.2  Wed 2026-10-07 12:00" in text
    before = _seq(lb)
    _run(capsys, "--accept", "4")
    assert len(_written(lb, before)) == 2, "an answer to a row is an answer for every voice in it"


# -- what each answer writes -------------------------------------------------------------------------------


def test_accept_writes_one_resolution_per_voice_as_the_rfc_has_it(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    row_id = _json(capsys)["rows"][3]["id"]
    assert _run(capsys, "--accept", "4").startswith("accepted 4 → Ola Nordmann: 1 line")
    (line,) = _written(lb, before)
    assert (line["kind"], line["source"], line["tier"]) == ("resolution", "manual", 2)
    payload = line["payload"]
    assert payload == {
        "schema": "resolution/v1",
        "ref": {"kind": "speaker", "value": f"{CALL}#system"},
        "entity": {"type": "person", "id": OLA_ID, "registry": "logbook"},
        "label": "Ola Nordmann",
        "method": "owner",
        "basis": "channel",
        "evidence": [CALL, CALL_LINE],
        "logbook_head": payload["logbook_head"],
        "extra": {"proposal": row_id, "score": 40, "matched": ["the far end of the call 09:15"]},
    }
    assert "confidence" not in payload, "asserted by the owner with the recording there"
    assert list(Draft202012Validator(SCHEMA).iter_errors(payload)) == []
    data = _json(capsys)
    assert (data["not_yet_named"], data["named"]) == (3, 1)
    assert Logbook(lb.root).verify()[2] == []


def test_accept_with_consent_and_a_voice_heard_is_basis_voice(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    _run(capsys, "--accept", "2", "--consent", "2=yes")
    (line,) = _written(lb, before)
    p = line["payload"]
    assert (p["entity"]["id"], p["basis"], p["consent"], p["label"]) == (
        KARI_ID,
        "voice",
        "yes",
        "Kari Nordmann",
    )
    assert p["extra"]["score"] == 20
    assert p["extra"]["matched"] == ['on the entry "Middag med Kari"', "seen that day (message 18:02)"]
    assert set(p["evidence"]) >= {DINNER}
    assert list(Draft202012Validator(SCHEMA).iter_errors(p)) == []


def test_the_owner_names_their_own_voice_with_no_label_and_no_consent(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    assert "→ you" in _run(capsys, "--name", "1", "me")
    (line,) = _written(lb, before)
    p = line["payload"]
    assert p["entity"]["id"] == lb.meta["owner_id"]
    assert "label" not in p and "consent" not in p and "unnamed" not in p
    err = _refused(capsys, "--name", "2", "me", "--consent", "2=yes")
    assert "your own voice is not asked for consent" in err


def test_a_name_nobody_has_mints_a_person_and_one_two_people_have_is_refused(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    _run(capsys, "--name", "3", "Per Hansen")
    (line,) = _written(lb, before)
    per = line["payload"]["entity"]["id"]
    assert per not in (KARI_ID, OLA_ID) and line["payload"]["label"] == "Per Hansen"
    report = people_reader.read(lb, DINNER_DAY, CALL_DAY)
    assert any(p.entity == per and p.name == "Per Hansen" for p in report.people)
    lb.append_many(
        [
            resolution(
                ("email", "per.a@example.org"), "019cadd3-6bc0-7dcd-9133-0000000004c1", "Ola Nordmann"
            ),
        ]
    )
    seq = _seq(lb)
    err = _refused(capsys, "--name", "1", "Ola Nordmann")
    assert "2 people are called Ola Nordmann" in err
    assert _seq(lb) == seq
    assert "→ Ola Nordmann" in _run(capsys, "--name", "1", f"email:{OLA['email']}")


def test_unnamed_mints_a_person_with_no_label_and_same_as_shares_it(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    _run(capsys, "--unnamed", "2,3", "--same-as", "2", "--consent", "3=unknown")
    two, three = _written(lb, before)
    for line in (two, three):
        assert line["payload"]["unnamed"] is True and "label" not in line["payload"]
        assert list(Draft202012Validator(SCHEMA).iter_errors(line["payload"])) == []
    assert two["payload"]["entity"]["id"] == three["payload"]["entity"]["id"], "one stranger, heard twice"
    assert three["payload"]["consent"] == "unknown" and "consent" not in two["payload"]
    report = people_reader.read(lb, DINNER_DAY, CALL_DAY)
    assert report.unnamed == 1
    assert all(p.entity != two["payload"]["entity"]["id"] for p in report.people)


def test_unnamed_rows_without_same_as_are_two_people(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    _run(capsys, "--unnamed", "2,3")
    two, three = _written(lb, before)
    assert two["payload"]["entity"]["id"] != three["payload"]["entity"]["id"]


def test_same_as_a_voice_already_unnamed(lb: Logbook, capsys) -> None:
    _run(capsys, "--unnamed", "3")
    neighbour = next(
        line["payload"]["entity"]["id"]
        for line in Logbook(lb.root).lines()
        if (line.get("payload") or {}).get("unnamed") is True
    )
    before = _seq(lb)
    _run(capsys, "--unnamed", "2", "--same-as", f"{DINNER}#S3")
    (line,) = _written(lb, before)
    assert line["payload"]["entity"]["id"] == neighbour
    err = _refused(capsys, "--unnamed", "1", "--same-as", "2")  # row 2 is Ola's far end now: not unnamed
    assert "not bound unnamed" in err


def test_reject_writes_one_no_and_the_pair_is_never_proposed_again(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    _run(capsys, "--reject", "2")
    (line,) = _written(lb, before)
    assert line["kind"] == "entity-review" and line["tier"] == 2
    p = line["payload"]
    assert (p["schema"], p["verdict"]) == ("entity-review/v1", "different")  # its kind is its entity's type
    assert p["ref"] == {"kind": "speaker", "value": f"{DINNER}#S2"}
    assert p["refs"] == [{"kind": "speaker", "value": f"{DINNER}#S2"}]
    assert p["entity"] == {"type": "person", "id": KARI_ID, "registry": "logbook"}
    rows = _json(capsys)["rows"]
    s2 = next(r for r in rows if r["voices"][0]["ref"] == f"{DINNER}#S2")
    assert all(c["id"] != KARI_ID for c in s2["candidates"]), (
        "the voice stays, with the next candidate or a blank"
    )
    Logbook(lb.root).retract(int(line["seq"]), "it was Kari after all")
    s2 = next(r for r in _json(capsys)["rows"] if r["voices"][0]["ref"] == f"{DINNER}#S2")
    assert s2["candidates"][0]["id"] == KARI_ID, "a wrong no is undone by retracting it"


def test_a_no_written_as_people_review_v1_is_read_too(lb: Logbook, capsys) -> None:
    lb.append_many(
        [
            {
                "at": "2026-10-11T08:14:00Z",
                "source": "manual",
                "kind": "people-review",
                "tier": 2,
                "payload": {
                    "schema": "people-review/v1",
                    "verdict": "different",
                    "ref": {"kind": "speaker", "value": f"{CALL}#system"},
                    "refs": [{"kind": "speaker", "value": f"{CALL}#system"}],
                    "entity": {"type": "person", "id": OLA_ID, "registry": "logbook"},
                    "label": "Ola Nordmann",
                    "method": "owner",
                },
            }
        ]
    )
    far = next(r for r in _json(capsys)["rows"] if r["voices"][0]["ref"] == f"{CALL}#system")
    assert far["candidates"] == []


def test_every_number_is_checked_before_the_first_line(lb: Logbook, capsys) -> None:
    seq = _seq(lb)
    for args, words in (
        (("--accept", "4", "--accept", "9"), "no row 9"),
        (("--accept", "4", "--reject", "4"), "both accepted and rejected"),
        (("--accept", "4", "--name", "4", "Ola Nordmann"), "answer the same voice twice"),
        (("--accept", "x"), "is not a row number"),
        (("--accept", "4", "--consent", "3=yes"), "answers no such row"),
        (("--consent", "4=maybe", "--accept", "4"), "say N=yes, N=no or N=unknown"),
        (("--all-above", "high"), "not a score"),
        (("--accept", "4.2"), "no voice 4.2"),
        (("--same-as", "2"), "--same-as goes with --unnamed"),
        (("--reject", "4", "--consent", "4=no"), "a no states nobody's consent"),
        (("--recording", DINNER), "go with --named"),
        (("--named",), "--named takes --recording ID or --day DAY"),
        (("--play", "4", "--accept", "4"), "--play writes nothing"),
    ):
        err = _refused(capsys, *args)
        assert words in err, (args, err)
        assert err.startswith("review speakers: "), err
    assert _seq(lb) == seq, "nothing written"


def test_the_speakers_options_go_with_review_speakers_only(lb: Logbook, capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["review", "org", "--unnamed", "1"])
    assert "--unnamed goes with `review speakers`" in capsys.readouterr().err


def test_all_above_takes_a_single_best_and_never_context_alone_over_forty(lb: Logbook, capsys) -> None:
    before = _seq(lb)
    out = _run(capsys, "--all-above", "15")
    assert out.splitlines() == [f"accepted 4 → Ola Nordmann: 1 line (#{before + 1})"], (
        "the dinner's three rows share Kari at 20: not taken"
    )
    assert _run(capsys, "--all-above", "41").strip() == "nothing to write: no proposal at or above that score"


def test_context_alone_scores_forty_at_most(lb: Logbook, capsys) -> None:
    """On the entry 15 + a participant 15 + the source's name 10 + seen that day 5 is 45: 40."""
    room = "019cadd3-6bc0-7dcd-9133-0000000004d7"
    lb.append_many(
        [
            transcript(
                room,
                utc(DINNER_DAY, "20:00"),
                utc(DINNER_DAY, "20:30"),
                "Kaffe",
                [{"label": "S1", "seconds": 600.0, "turns": 3, "name": "Kari Nordmann"}],
                participants=[{"name": "Kari Nordmann", "email": KARI["email"]}],
            )
        ]
    )
    row = next(r for r in _json(capsys)["rows"] if r["voices"][0]["ref"] == f"{room}#S1")
    (kari,) = row["candidates"]
    assert kari["score"] == 40
    assert len(kari["matched"]) == 4
    assert (
        _run(capsys, "--all-above", "41").strip() == "nothing to write: no proposal at or above that score"
    ), "above 40, context never takes a guest; without a voiceprint, neither does the far end alone"


def test_two_close_candidates_are_shown_and_neither_is_taken(lb: Logbook, capsys) -> None:
    room = "019cadd3-6bc0-7dcd-9133-0000000004d8"
    lb.append_many(
        [
            message(utc("2026-10-08", "09:00"), OLA["phone"], "Kommer!"),
            message(utc("2026-10-08", "09:05"), KARI["phone"], "Jeg også"),
            *dwell("2026-10-08", "08:00", "12:00", HOME),
            transcript(room, utc("2026-10-08", "10:00"), utc("2026-10-08", "10:30"), "Møte", ROOM[:1]),
        ]
    )
    row = next(r for r in _json(capsys)["rows"] if r["voices"][0]["ref"] == f"{room}#S1")
    assert row["close"] is True and [c["score"] for c in row["candidates"]] == [5, 5]
    n = str(row["number"])
    text = _run(capsys)
    assert "Kari Nordmann: seen that day (message 09:05) | or Ola Nordmann: seen that day" in text
    assert "two candidates within 5 points" in _refused(capsys, "--accept", n)
    assert f"accepted {n}" not in _run(capsys, "--all-above", "0")


def test_a_voice_with_no_audio_is_basis_text_with_a_capped_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    lb = Logbook.init(tmp_path / "quiet", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    dinner_record(lb, audio=False)
    before = _seq(lb)
    _run(capsys, "--accept", "2")
    (line,) = _written(lb, before)
    assert (line["payload"]["basis"], line["payload"]["confidence"]) == ("text", 0.2)
    assert list(Draft202012Validator(SCHEMA).iter_errors(line["payload"])) == []
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "speakers.json").write_text('{"text_confidence_cap": 0.1}', encoding="utf-8")
    assert "proposes nobody" in _refused(capsys, "--accept", "2"), "S3: Kari is S2's voice of the recording"
    before = _seq(lb)
    _run(capsys, "--name", "2", "Kari Nordmann")
    (line,) = _written(lb, before)
    assert (line["payload"]["basis"], line["payload"]["confidence"]) == ("text", 0.1)


def test_a_tier_three_transcript_makes_a_tier_three_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    lb = Logbook.init(tmp_path / "three", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            *people(),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM, tier=3),
        ]
    )
    before = _seq(lb)
    _run(capsys, "--name", "2", "Kari Nordmann")
    (line,) = _written(lb, before)
    assert line["tier"] == 3


def test_policy_forget_is_never_proposed_and_a_bad_file_is_one_sentence(lb: Logbook, capsys) -> None:
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "speakers.json").write_text(json.dumps({"forget": [OLA_ID]}), encoding="utf-8")
    far = next(r for r in _json(capsys)["rows"] if r["voices"][0]["ref"] == f"{CALL}#system")
    assert far["candidates"] == []
    (lb.root / "policy" / "speakers.json").write_text('{"text_confidence_cap": 2}', encoding="utf-8")
    assert "text_confidence_cap must be a number from 0 to 1" in _refused(capsys)


# -- a wrong answer ----------------------------------------------------------------------------------------


def test_named_lists_a_recordings_voices_and_an_answer_supersedes(lb: Logbook, capsys) -> None:
    _run(capsys, "--accept", "4")  # Ola, the far end
    wrong = _written(lb, _seq(lb) - 1)[0]
    out = _run(capsys, "--named", "--recording", CALL).splitlines()
    assert out[0] == "2 voices named · tier 2"
    assert any("= you: channel · from_me, no line" in row for row in out)
    assert any(f"= Ola Nordmann: channel, consent unknown · line #{wrong['seq']}" in row for row in out)
    rows = _json(capsys, "--named", "--recording", CALL)["rows"]
    n = next(str(r["number"]) for r in rows if r["voices"][0]["label"] == "system")
    before = _seq(lb)
    _run(capsys, "--named", "--recording", CALL, "--name", n, "Kari Nordmann")
    (line,) = _written(lb, before)
    assert line["payload"]["supersedes"] == wrong["id"]
    assert line["payload"]["entity"]["id"] == KARI_ID and line["payload"]["basis"] == "voice"
    assert any(x["id"] == wrong["id"] for x in Logbook(lb.root).lines()), "the wrong line stays"
    before = _seq(lb)
    _run(capsys, "--named", "--recording", CALL, "--accept", n)
    assert _written(lb, before) == [], "the same entity, basis and consent write nothing"
    _run(capsys, "--named", "--recording", CALL, "--accept", n, "--consent", f"{n}=yes")
    (restated,) = _written(lb, before)
    assert restated["payload"]["consent"] == "yes" and restated["payload"]["supersedes"] == line["id"]
    assert "a wrong yes is undone by `repair retract SEQ`" in _refused(
        capsys, "--named", "--recording", CALL, "--reject", n
    )


def test_named_by_day_and_by_seq(lb: Logbook, capsys) -> None:
    _run(capsys, "--name", "1", "me")
    seq = next(int(line["seq"]) for line in Logbook(lb.root).lines() if line.get("id") == DINNER)
    by_seq = _json(capsys, "--named", "--recording", str(seq))
    by_day = _json(capsys, "--named", "--day", DINNER_DAY)
    assert [r["voices"][0]["ref"] for r in by_seq["rows"]] == [f"{DINNER}#S1"]
    assert by_seq["rows"] == by_day["rows"]
    assert "no standing transcript" in _refused(capsys, "--named", "--recording", "999")


def test_a_wrong_yes_retracted_returns_the_voice_to_the_queue(lb: Logbook, capsys) -> None:
    _run(capsys, "--accept", "4")
    (line,) = _written(lb, _seq(lb) - 1)
    assert _json(capsys)["not_yet_named"] == 3
    cli.main(["repair", "retract", str(line["seq"]), "it was Kari on his phone"])
    capsys.readouterr()
    assert _json(capsys)["not_yet_named"] == 4


def test_a_transcript_heard_again_brings_its_voices_back_as_new_refs(lb: Logbook, capsys) -> None:
    _run(capsys, "--name", "1", "me")
    again = "019cadd3-6bc0-7dcd-9133-0000000004aa"
    lb.append_many(
        [
            transcript(
                again,
                utc(DINNER_DAY, "19:40"),
                utc(DINNER_DAY, "20:52"),
                "Middag",
                ROOM,
                raw_id="memo-04a1#speakers@a9e2c41d0000",
                supersedes=DINNER,
            )
        ]
    )
    refs = [v["ref"] for row in _json(capsys)["rows"] for v in row["voices"]]
    assert f"{again}#S1" in refs and not any(r.startswith(DINNER) for r in refs)


def test_an_answer_the_record_holds_writes_nothing(lb: Logbook, capsys) -> None:
    lb.append_many([attribution(DINNER, "S3", "019cadd3-6bc0-7dcd-9133-000000000403", unnamed=True)])
    before = _seq(lb)
    rows = _json(capsys, "--named", "--recording", DINNER)["rows"]
    n = next(str(r["number"]) for r in rows if r["voices"][0]["label"] == "S3")
    assert "held already" in _run(capsys, "--named", "--recording", DINNER, "--unnamed", n)
    assert _written(lb, before) == []


# -- the sitting -------------------------------------------------------------------------------------------


def test_review_with_no_kind_lists_the_speakers_too(lb: Logbook, capsys) -> None:
    cli.main(["review"])
    out = capsys.readouterr().out.splitlines()
    assert [row for row in out if not row.startswith(" ")][-1] == "speakers"
    assert "  4 voices not yet named in 2 recordings, 4 rows · 0 named · tier 2" in out


def test_on_a_terminal_each_answer_is_written_at_once(lb: Logbook, capsys, monkeypatch) -> None:
    answers = iter(["", "Kari Nordmann", "y", "u", "", "y", "n"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    before = _seq(lb)
    cli.main(["review", "speakers"])
    out = capsys.readouterr().out
    written = _written(lb, before)
    assert [line["payload"].get("label") for line in written] == ["Kari Nordmann", None, "Ola Nordmann"]
    assert written[0]["payload"]["consent"] == "yes", "asked after a name for a guest"
    assert written[1]["payload"]["unnamed"] is True and written[1]["payload"]["consent"] == "unknown"
    assert written[2]["payload"]["consent"] == "no", "a guest accepted is asked too"
    assert "named 2 → Kari Nordmann · consent yes: 1 line" in out


def test_play_cuts_the_voice_alone_and_writes_nothing(lb: Logbook, capsys) -> None:
    report = speakers_review.read(lb)
    played: list[Path] = []
    seen: list[bytes] = []

    def player(path: Path) -> None:
        played.append(path)
        seen.append(path.read_bytes())

    before = _seq(lb)
    said = speakers_review.play(
        lb, report, "2", decode=lambda path: ([0.25] * 16_000 * 40, 16_000), player=player
    )
    assert said.startswith('played S2 of "Middag":')
    assert len(played) == 1 and seen[0][:4] == b"RIFF"
    assert not played[0].exists(), "the WAV file is gone after"
    assert _seq(lb) == before


def test_clips_are_the_voice_alone_cut_at_twenty_seconds() -> None:
    document = {
        "turns": [
            {"from": 0.0, "to": 10.0, "speaker": "S2"},
            {"from": 8.0, "to": 12.0, "speaker": "S1"},
            {"from": 20.0, "to": 40.0, "speaker": "S2"},
            {"from": 25.0, "to": 26.0, "speaker": "S3"},
        ]
    }
    assert speakers_review.clips(document, "S2") == [(0.0, 8.0), (20.0, 25.0), (26.0, 33.0)]
    assert speakers_review.clips(document, "S9") == []


def test_review_speakers_opens_no_connection(lb: Logbook, capsys, no_network: list[str]) -> None:
    _run(capsys)
    _json(capsys)
    _run(capsys, "--named", "--day", DINNER_DAY)
    assert no_network == []


def test_the_text_road_and_the_voiceprint_are_not_this_build(lb: Logbook, capsys) -> None:
    """No row says `same voice`: there is no registry to compare against yet (RFC 0038 §5)."""
    assert "same voice" not in _run(capsys)
    assert not (lb.root / "voiceprints.age").exists()


def test_people_reads_what_the_review_wrote(lb: Logbook, capsys) -> None:
    _run(capsys, "--accept", "4", "--name", "2", "Kari Nordmann", "--unnamed", "3", "--name", "1", "me")
    report = people_reader.read(lb, DINNER_DAY, CALL_DAY)
    assert (report.unnamed, report.not_yet_named) == (1, 0)
    assert {p.entity for p in report.people} >= {KARI_ID, OLA_ID}
