"""The readers join a transcript's voices to who they are (RFC 0038 §3.4): `with` takes company from
a voice bound to a person in a recording that overlaps the stay (the far end of a call counts for
the person's transcripts and is never company; an unnamed voice is counted and never named; a voice
not yet named is nobody's company); `people` counts a bound voice on the transcripts channel with
the seconds it spoke, never lists the unnamed and says how many voices are not yet named; the Day
names who spoke; `promises` takes a sentence's speaker from its voice; the digest says who spoke and,
once, how many voices wait. Synthetic Oslo persona (`speakers_record`)."""

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
    KARI,
    KARI_ID,
    OLA,
    OLA_ID,
    ROOM,
    attribution,
    dinner_record,
    people,
    transcript,
)

from logbook import cli
from logbook.contrib import digest, promises
from logbook.core import day as day_reader
from logbook.core import people as people_reader
from logbook.core.store import Logbook

NEIGHBOUR = "019cadd3-6bc0-7dcd-9133-000000000403"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _named(lb: Logbook, *extra: dict[str, Any]) -> None:
    """The owner's answers of RFC 0038 §11: S1 is Ines, S2 Kari (consent yes), S3 the neighbour,
    unnamed; the call's far end Ola."""
    owner = str(lb.meta["owner_id"])
    lb.append_many(
        [
            attribution(DINNER, "S1", owner),
            attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann", consent="yes"),
            attribution(DINNER, "S3", NEIGHBOUR, unnamed=True),
            attribution(CALL, "system", OLA_ID, name="Ola Nordmann", basis="channel"),
            *extra,
        ]
    )


def _stay(data: dict[str, Any]) -> dict[str, Any]:
    stays = [e for e in data["timeline"] if e["kind"] == "stay"]
    assert len(stays) == 1, stays
    return stays[0]


# -- with --------------------------------------------------------------------------------------------------


def test_a_bound_voice_is_company_at_the_stay_its_recording_overlaps(lb: Logbook) -> None:
    lb.append_many(
        [
            *people(),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
        ]
    )
    stay = _stay(day_reader.read(lb, DINNER_DAY))
    assert stay["with"] == {"confirmed": [], "proposed": []}, "a voice not yet named is nobody's company"
    _named(lb)
    stay = _stay(day_reader.read(lb, DINNER_DAY))
    kari = stay["with"]["confirmed"]
    assert [(c["person"], c["name"], c["sources"], c["reasons"], c["confidence"]) for c in kari] == [
        (KARI_ID, "Kari Nordmann", ["transcript"], ["spoke in Middag"], 1.0)
    ], "asserted by the owner: the reader's confidence is the line's, absent read as asserted"
    assert stay["with"]["unnamed"] == 1, "the neighbour is counted, never named"
    assert all(c["person"] != NEIGHBOUR for c in [*kari, *stay["with"]["proposed"]])


def test_a_text_attribution_reads_with_its_own_confidence(lb: Logbook) -> None:
    lb.append_many(
        [
            *people(),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
            attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann", basis="text", confidence=0.4),
        ]
    )
    (kari,) = _stay(day_reader.read(lb, DINNER_DAY))["with"]["confirmed"]
    assert kari["confidence"] == 0.4


def test_the_far_end_of_a_call_is_never_company_not_even_as_a_participant(lb: Logbook) -> None:
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
                    {"label": "mic", "seconds": 201.7, "turns": 2, "channel": "mic", "from_me": True},
                    {"label": "system", "seconds": 188.3, "turns": 2, "channel": "system"},
                ],
                participants=[{"name": "Ola Nordmann", "phone": OLA["phone"]}],
            ),
        ]
    )
    before = _stay(day_reader.read(lb, CALL_DAY))["with"]["confirmed"]
    assert [c["person"] for c in before] == [OLA_ID], "a participant, as SPEC §3.2.5 rule 2 has it today"
    lb.append(**_draft(attribution(CALL, "system", OLA_ID, name="Ola Nordmann", basis="channel")))
    after = _stay(day_reader.read(lb, CALL_DAY))["with"]
    assert after["confirmed"] == [], "he spoke on the call and was not there"
    assert "unnamed" not in after


def test_a_voice_bound_to_the_owner_or_from_me_is_never_company(lb: Logbook) -> None:
    owner = str(lb.meta["owner_id"])
    lb.append_many(
        [
            *people(),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
            attribution(DINNER, "S1", owner),
        ]
    )
    assert _stay(day_reader.read(lb, DINNER_DAY))["with"] == {"confirmed": [], "proposed": []}


# -- people ------------------------------------------------------------------------------------------------


def test_people_count_a_bound_voice_with_the_seconds_and_never_list_the_unnamed(lb: Logbook) -> None:
    dinner_record(lb, with_text=False)
    report = people_reader.read(lb, DINNER_DAY, CALL_DAY)
    assert (report.unnamed, report.not_yet_named) == (0, 4), (
        "S1, S2, S3 and the far end; from_me is the owner"
    )
    head = next(people_reader.rows(report))
    assert "4 voices not yet named · review speakers" in head
    _named(lb)
    report = people_reader.read(lb, DINNER_DAY, CALL_DAY)
    by_id = {p.entity: p.to_json() for p in report.people}
    assert NEIGHBOUR not in by_id and NEIGHBOUR not in report.known, "an unnamed person is never a row"
    assert by_id[KARI_ID]["channels"]["transcripts"]["lines"] == 1
    assert by_id[KARI_ID]["channels"]["transcripts"]["spoke_s"] == 861.0
    assert by_id[OLA_ID]["channels"]["transcripts"] == {
        "lines": 1,
        "first": CALL_DAY,
        "last": CALL_DAY,
        "tier": 2,
        "last_line": CALL,
        "spoke_s": 188.3,
    }, "the far end counts for his transcripts"
    assert by_id[KARI_ID]["days"] == 1  # the dinner (her calendar entry, and her voice)
    assert by_id[OLA_ID]["days"] == 0, "the far end of a call is no day together"
    assert all(r["kind"] != "speaker" for r in by_id[KARI_ID]["refs"]), "a voice is no ref of a person"
    assert (report.unnamed, report.not_yet_named) == (1, 0)
    head = next(people_reader.rows(report))
    assert head.endswith("and 1 unnamed"), head
    data = report.to_json()
    assert (data["unnamed"], data["not_yet_named"]) == (1, 0)


def test_people_json_is_unchanged_for_a_record_without_voices(lb: Logbook) -> None:
    lb.append_many([*people(), *dwell(DINNER_DAY, "16:00", "23:30", HOME)])
    data = people_reader.read(lb, DINNER_DAY, DINNER_DAY).to_json()
    assert set(data) == {"window", "tier", "people"}


def test_a_person_minted_for_a_voice_alone_is_a_person_heard(lb: Logbook) -> None:
    """`review speakers --name 3 "Per Hansen"` mints Per: a person of the record with no address."""
    dinner_record(lb, with_text=False)
    per = "019cadd3-6bc0-7dcd-9133-000000000405"
    lb.append(**_draft(attribution(DINNER, "S3", per, name="Per Hansen")))
    report = people_reader.read(lb, DINNER_DAY, DINNER_DAY)
    row = next(p for p in report.people if p.entity == per)
    assert row.name == "Per Hansen"
    assert row.channels["transcripts"].lines == 1


def test_rollup_people_takes_the_voice_and_counts_the_unnamed(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    dinner_record(lb, with_text=False)
    cli.main(["rollup", "people", "--since", DINNER_DAY, "--until", CALL_DAY, "--json"])
    (year,) = json.loads(capsys.readouterr().out)["years"]
    assert "unnamed" not in year, "nobody bound unnamed: the year as it was"
    _named(lb)
    cli.main(["rollup", "people", "--since", DINNER_DAY, "--until", CALL_DAY, "--json"])
    (year,) = json.loads(capsys.readouterr().out)["years"]
    assert [p["id"] for p in year["people"]] == [KARI_ID], "Ola was the far end of a call: no day together"
    assert year["unnamed"] == 1
    cli.main(["rollup", "people", "--since", DINNER_DAY, "--until", CALL_DAY])
    assert "  2026 · and 1 unnamed" in capsys.readouterr().out.splitlines()


def test_the_person_page_says_how_long_they_spoke(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    dinner_record(lb, with_text=False)
    _named(lb)
    cli.main(["people", "Kari Nordmann", "--year", "2026"])
    assert "transcripts 1 (2026-10-03, spoke 14 min)" in capsys.readouterr().out


# -- the Day -----------------------------------------------------------------------------------------------


def test_the_day_names_who_spoke_and_says_the_consent(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    dinner_record(lb, with_text=False)
    _named(lb)
    cli.main(["day", DINNER_DAY])
    text = capsys.readouterr().out
    assert "Middag · you 31 min · Kari Nordmann 14 min · 1 unnamed · recorded with consent: unknown" in text
    with_row = next(row for row in text.splitlines() if row.lstrip().startswith("with "))
    assert with_row.split(None, 1)[1] == "Kari Nordmann (calendar, transcript) · 1 unnamed"
    cli.main(["day", DINNER_DAY, "--json"])
    data = json.loads(capsys.readouterr().out)
    (middag,) = _stay(data)["attached"]["transcripts"]
    owner = str(lb.meta["owner_id"])
    voice = ("label", "person", "name", "seconds", "basis", "consent", "owner")
    assert middag["speakers"] == [
        dict(zip(voice, ("S1", owner, None, 1862.4, "voice", None, True), strict=True)),
        dict(zip(voice, ("S2", KARI_ID, "Kari Nordmann", 861.0, "voice", "yes", False), strict=True)),
        dict(zip(voice, ("S3", None, None, 41.5, "voice", "unknown", False), strict=True)),
    ]
    cli.main(["day", CALL_DAY])
    assert (
        "Samtale · you 3 min · Ola Nordmann 3 min · recorded with consent: unknown" in capsys.readouterr().out
    )


def test_every_guest_consenting_shows_no_consent(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    dinner_record(lb, with_text=False)
    lb.append(
        **_draft(attribution(CALL, "system", OLA_ID, name="Ola Nordmann", basis="channel", consent="yes"))
    )
    cli.main(["day", CALL_DAY])
    out = capsys.readouterr().out
    assert "Samtale · you 3 min · Ola Nordmann 3 min" in out and "consent" not in out


# -- promises ----------------------------------------------------------------------------------------------


def _said(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {p.match.quote: p.to_json() for p in promises.extract(lb).proposals}


def test_a_sentences_speaker_is_its_voice_bound(lb: Logbook) -> None:
    dinner_record(lb)
    before = _said(lb)
    cake = before["I will bring the cake on Friday."]
    assert (cake["speaker"]["spoken"], cake["speaker"]["person"], cake["direction"]) == ("S2", None, None)
    yard = before["I'll call the yard tomorrow."]
    assert yard["speaker"]["spoken"] == "system" and yard["direction"] is None, "not yet named: as spoken"
    ferry = before["I will book the ferry on Monday."]
    assert ferry["speaker"]["owner"] is True, "the owner's microphone (from_me) is the owner's"
    _named(lb)
    after = _said(lb)
    cake = after["I will bring the cake on Friday."]
    assert cake["speaker"] == {"label": "Kari Nordmann", "spoken": "S2", "person": KARI_ID, "owner": False}
    assert cake["direction"] == "owed_to_owner"
    photos = after["I'll send you the photos tomorrow."]
    assert photos["speaker"]["owner"] is True and photos["direction"] == "owed_by_owner"
    yard = after["I'll call the yard tomorrow."]
    assert (yard["speaker"]["person"], yard["direction"]) == (OLA_ID, "owed_to_owner")
    assert cake["id"] == before["I will bring the cake on Friday."]["id"], (
        "the id is the line's and the words'"
    )


def test_an_unnamed_guests_promise_is_owed_to_the_owner_and_names_nobody(lb: Logbook) -> None:
    dinner_record(lb)
    lb.append(**_draft(attribution(DINNER, "S2", NEIGHBOUR, unnamed=True)))
    cake = _said(lb)["I will bring the cake on Friday."]
    assert cake["speaker"]["label"] is None and cake["speaker"]["owner"] is False
    assert cake["direction"] == "owed_to_owner"


# -- the digest --------------------------------------------------------------------------------------------


def test_the_digest_says_who_spoke_and_once_how_many_voices_wait(lb: Logbook) -> None:
    dinner_record(lb, with_text=False)
    lb.append(**_draft(attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann")))
    data = digest.read(lb, DINNER_DAY)
    assert data["shape"]["spoke"] == ["Kari Nordmann"]
    assert data["shape"]["not_yet_named"] == 2
    rows = list(digest.rows(data))
    spoke = [row for row in rows if row.lstrip().startswith("spoke")]
    assert len(spoke) == 1, rows
    assert "Kari Nordmann" in spoke[0] and "2 voices not yet named · logbook review speakers" in spoke[0]


def test_the_digest_of_a_day_without_voices_is_as_it_was(lb: Logbook) -> None:
    lb.append_many([*people(), *dwell(DINNER_DAY, "16:00", "23:30", HOME)])
    data = digest.read(lb, DINNER_DAY)
    assert "spoke" not in data["shape"] and "not_yet_named" not in data["shape"]
    assert not any(row.lstrip().startswith("spoke") for row in digest.rows(data))


def _draft(line: dict[str, Any]) -> dict[str, Any]:
    return {k: line[k] for k in ("at", "source", "kind", "tier", "payload")}


assert KARI["email"] and OLA["email"]  # the persona's addresses are example.org's
