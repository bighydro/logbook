"""Edges of the readers' join (RFC 0038 §3.3 rules 4 and 5, §3.4): a superseded transcript's voices
name nobody in `rollup people`; a line the profile would reject (no `basis`) still counts an unnamed
person and never shows a label; several voices on the microphone channel; payloads a reader cannot
interpret; a voice bound by alias; the owner's microphone bound to someone else and given back;
voices of a recording at no stay. Synthetic Oslo persona (`speakers_record`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, TZ, dwell, utc
from speakers_record import (
    CALL,
    CALL_DAY,
    DINNER,
    DINNER_DAY,
    KARI_ID,
    ROOM,
    TWO_CHANNELS,
    attribution,
    dinner_record,
    people,
    transcript,
)

from logbook import cli
from logbook.contrib import digest
from logbook.core import day as day_reader
from logbook.core import people as people_reader
from logbook.core.store import Logbook

NEIGHBOUR = "019cadd3-6bc0-7dcd-9133-000000000403"
AGAIN = "019cadd3-6bc0-7dcd-9133-0000000004a9"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _stay(data: dict[str, Any]) -> dict[str, Any]:
    stays = [e for e in data["timeline"] if e["kind"] == "stay"]
    assert len(stays) == 1, stays
    return stays[0]


def _transcript_row(lb: Logbook, day: str, capsys: pytest.CaptureFixture[str]) -> str:
    cli.main(["day", day])
    return next(row for row in capsys.readouterr().out.splitlines() if row.lstrip().startswith("transcript"))


def _draft(line: dict[str, Any]) -> dict[str, Any]:
    return {k: line[k] for k in ("at", "source", "kind", "tier", "payload")}


# -- §3.3 rule 5: a voice of a transcript that is not standing names nobody ---------------------------------


def test_rollup_people_reads_no_voice_of_a_superseded_transcript(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The dinner is heard again (`derive speakers`, §2.8): the new line has new labels and no
    attribution yet, the old line is superseded. Its attributions are read by nothing (§3.3 rule
    5): Kari is nobody's company that day and the neighbour is not counted, as the Day already has
    it; `rollup people` must agree."""
    lb.append_many(
        [
            *people(),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
            attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann"),
            attribution(DINNER, "S3", NEIGHBOUR, unnamed=True),
        ]
    )
    cli.main(["rollup", "people", "--since", DINNER_DAY, "--until", DINNER_DAY, "--json"])
    (year,) = json.loads(capsys.readouterr().out)["years"]
    assert [p["id"] for p in year["people"]] == [KARI_ID] and year["unnamed"] == 1, "the standing line's"
    lb.append_many(
        [
            transcript(
                AGAIN,
                utc(DINNER_DAY, "19:40"),
                utc(DINNER_DAY, "20:52"),
                "Middag",
                ROOM,
                raw_id="memo-04a1#speakers@a9e2",
                supersedes=DINNER,
            )
        ]
    )
    assert _stay(day_reader.read(lb, DINNER_DAY))["with"] == {"confirmed": [], "proposed": []}
    cli.main(["rollup", "people", "--since", DINNER_DAY, "--until", DINNER_DAY, "--json"])
    years = json.loads(capsys.readouterr().out)["years"]
    assert all(year["people"] == [] and "unnamed" not in year for year in years), years


# -- a line the profile would reject: never a failure, never a name ------------------------------------------


def test_an_unnamed_line_without_a_basis_is_still_counted_and_never_shown_as_its_label(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """`basis` is MUST on a `speaker` ref (§3.2); a reader that meets a line without one reads it
    as absent (SPEC §5) and still knows the voice is bound: the person is unnamed, counted and
    never named (§3.4), not shown as `S3` and not one of the voices not yet named."""
    dinner_record(lb, with_text=False)
    line = attribution(DINNER, "S3", NEIGHBOUR, unnamed=True)
    del line["payload"]["basis"]
    lb.append_many([line])
    stay = _stay(day_reader.read(lb, DINNER_DAY))
    assert stay["with"]["unnamed"] == 1
    row = _transcript_row(lb, DINNER_DAY, capsys)
    assert "1 unnamed" in row and "S3" not in row, row
    shape = digest.read(lb, DINNER_DAY)["shape"]
    assert shape["not_yet_named"] == 2, "S1 and S2; the neighbour is bound"


# -- what the RFC's examples imply, locked in --------------------------------------------------------------


def test_several_voices_on_the_microphone_channel_are_nobodys_until_bound(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2.5: a speakerphone in the room gives `mic.1`, `mic.2`, none `from_me`; the owner is then
    proposed by voice like anyone. Neither is the far end: one bound to Kari is company."""
    lb.append_many(
        [
            *people(),
            *dwell(CALL_DAY, "08:00", "10:30", HOME),
            transcript(
                CALL,
                utc(CALL_DAY, "09:15"),
                utc(CALL_DAY, "09:22"),
                "Samtale",
                [
                    {"label": "mic.1", "seconds": 100.0, "turns": 2, "channel": "mic"},
                    {"label": "mic.2", "seconds": 50.0, "turns": 2, "channel": "mic"},
                    {"label": "system", "seconds": 188.3, "turns": 2, "channel": "system"},
                ],
            ),
        ]
    )
    stay = _stay(day_reader.read(lb, CALL_DAY))
    (call,) = stay["attached"]["transcripts"]
    assert [(v["label"], v["owner"], v["person"]) for v in call["speakers"]] == [
        ("mic.1", False, None),
        ("mic.2", False, None),
        ("system", False, None),
    ]
    assert people_reader.read(lb, CALL_DAY, CALL_DAY).not_yet_named == 3
    lb.append_many([attribution(CALL, "mic.2", KARI_ID, name="Kari Nordmann")])
    stay = _stay(day_reader.read(lb, CALL_DAY))
    assert [(c["person"], c["reasons"]) for c in stay["with"]["confirmed"]] == [
        (KARI_ID, ["spoke in Samtale"])
    ]
    assert "mic.1 2 min · Kari Nordmann 50 s · system 3 min" in _transcript_row(lb, CALL_DAY, capsys)


def test_readers_never_fail_on_payloads_they_cannot_interpret(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """SPEC §5: `speakers` that is not a list, an entry whose label holds `#`, a `speaker` ref with
    no `#`, a line naming a company, a consent outside the enum. Every reader reads; a voice such
    a line names is not yet named, a consent it cannot read is unknown."""
    room = [*ROOM, {"label": "S#4", "seconds": 1.0, "turns": 1}]
    dinner = transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", room)
    no_hash = attribution(DINNER, "S1", KARI_ID, name="Kari Nordmann")
    no_hash["payload"]["ref"]["value"] = DINNER
    company = attribution(DINNER, "S3", "019cadd3-6bc0-7dcd-9133-000000000777", name="Acme AS")
    company["payload"]["entity"]["type"] = "company"
    maybe = attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann", consent="maybe")
    lb.append_many([*people(), *dwell(DINNER_DAY, "16:00", "23:30", HOME), dinner, no_hash, company, maybe])
    stay = _stay(day_reader.read(lb, DINNER_DAY))
    (middag,) = stay["attached"]["transcripts"]
    assert [(v["label"], v["person"], v["consent"]) for v in middag["speakers"]] == [
        ("S1", None, None),
        ("S2", KARI_ID, "unknown"),
        ("S3", None, None),
    ]
    assert [c["person"] for c in stay["with"]["confirmed"]] == [KARI_ID]
    report = people_reader.read(lb, DINNER_DAY, DINNER_DAY)
    assert (report.unnamed, report.not_yet_named) == (0, 2)
    assert [p.entity for p in report.people] == [KARI_ID]
    assert digest.read(lb, DINNER_DAY)["shape"]["spoke"] == ["Kari Nordmann"]
    cli.main(["day", DINNER_DAY])
    assert "recorded with consent: unknown" in capsys.readouterr().out
    unreadable = transcript(CALL, utc(CALL_DAY, "09:15"), utc(CALL_DAY, "09:22"), "Samtale", TWO_CHANNELS)
    unreadable["payload"]["speakers"] = {"label": "mic"}
    lb.append_many([*dwell(CALL_DAY, "08:00", "10:30", HOME), unreadable])
    (call,) = _stay(day_reader.read(lb, CALL_DAY))["attached"]["transcripts"]
    assert "speakers" not in call
    assert people_reader.read(lb, CALL_DAY, CALL_DAY).not_yet_named == 0


def test_a_voice_said_to_be_another_voice_counts_for_that_person_everywhere(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """`alias_of` between `speaker` refs (§3.2): the call's far end is the same voice as the
    dinner's `S2`, Kari; `people` counts both recordings and the seconds of both, the Day names her
    on the call, and she is still not company on the call (the far end)."""
    dinner_record(lb, with_text=False)
    lb.append_many(
        [
            attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann", consent="yes"),
            attribution(CALL, "system", "", alias_of=f"{DINNER}#S2", basis="channel"),
        ]
    )
    report = people_reader.read(lb, DINNER_DAY, CALL_DAY)
    kari = next(p for p in report.people if p.entity == KARI_ID)
    assert kari.channels["transcripts"].lines == 2
    assert kari.channels["transcripts"].spoke_s == pytest.approx(861.0 + 188.3)
    assert "Kari Nordmann 3 min" in _transcript_row(lb, CALL_DAY, capsys)
    assert _stay(day_reader.read(lb, CALL_DAY))["with"]["confirmed"] == []


def test_the_owners_microphone_bound_to_someone_else_counts_for_them_and_is_given_back(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.3 rule 4 in the readers: Kari spoke into the owner's phone. `people` counts the call and
    the minutes for her, the Day names her and she is company (she was there); once the line is
    retracted the microphone is the owner's again and nothing counts for her."""
    dinner_record(lb, with_text=False)
    line = lb.append(**_draft(attribution(CALL, "mic", KARI_ID, name="Kari Nordmann", consent="yes")))
    report = people_reader.read(lb, CALL_DAY, CALL_DAY)
    kari = next(p for p in report.people if p.entity == KARI_ID)
    assert (kari.channels["transcripts"].lines, kari.channels["transcripts"].spoke_s) == (1, 201.7)
    assert [c["person"] for c in _stay(day_reader.read(lb, CALL_DAY))["with"]["confirmed"]] == [KARI_ID]
    assert "Kari Nordmann 3 min" in _transcript_row(lb, CALL_DAY, capsys)
    lb.retract(int(line["seq"]), "it was me after all")
    report = people_reader.read(lb, CALL_DAY, CALL_DAY)
    assert KARI_ID not in {p.entity for p in report.people}
    assert str(lb.meta["owner_id"]) not in report.known, "the owner is never a row"
    stay = _stay(day_reader.read(lb, CALL_DAY))
    assert stay["with"] == {"confirmed": [], "proposed": []}
    (call,) = stay["attached"]["transcripts"]
    assert call["speakers"][0]["owner"] is True and call["speakers"][0]["basis"] == "channel"
    assert "you 3 min" in _transcript_row(lb, CALL_DAY, capsys)


def test_voices_of_a_recording_at_no_stay_count_for_the_person_and_are_no_day_together(
    lb: Logbook,
) -> None:
    """No track that evening: the recording is unplaced. `people` still counts the transcript and
    the minutes for Kari; days together need a stay (`with`), so she has none."""
    lb.append_many(
        [
            *people(),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
            attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann"),
            attribution(DINNER, "S3", NEIGHBOUR, unnamed=True),
        ]
    )
    report = people_reader.read(lb, DINNER_DAY, DINNER_DAY)
    kari = next(p for p in report.people if p.entity == KARI_ID)
    assert (kari.channels["transcripts"].lines, kari.channels["transcripts"].spoke_s) == (1, 861.0)
    assert not kari.days
    assert (report.unnamed, report.not_yet_named) == (1, 1)
    data = day_reader.read(lb, DINNER_DAY)
    assert data["timeline"] == []
    (middag,) = data["unplaced"]
    assert [v["person"] for v in middag["speakers"]] == [None, KARI_ID, None]
    assert digest.read(lb, DINNER_DAY)["shape"]["spoke"] == ["Kari Nordmann"]
