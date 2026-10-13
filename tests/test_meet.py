"""`logbook sync meet`: the owner's Google Meet calls as `event/v1` (RFC 0009), one line per conference, and,
when Meet transcribed it, one `transcript/v1` line (RFC 0004) built as Granola's is: the same mapping
(`transcript.draft`), the same tier, the words in the attachment store and never in the line. Read from the
Meet REST API v2, read-only, with the service account the other Google sources use.

Against the in-process fake of `tests/google_fake.py`: Ines Nordmann's calls with Ola and Per. Nobody in
them exists, and nothing leaves the process (`no_network`)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from google_fake import DRIVE_SCOPE, MEET_SCOPE, USER, Fake, private_key, write_key

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import granola, meet, service_account, transcript
from logbook.core import transcripts
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
A, B, C, D = (f"conferenceRecords/conf-{x}" for x in "abcd")


def _participant(record: str, n: int, **who: Any) -> dict[str, Any]:
    return {"name": f"{record}/participants/p{n}", "earliestStartTime": "2026-09-14T08:00:05Z", **who}


def _signed_in(record: str, n: int, user: str, name: str) -> dict[str, Any]:
    return _participant(record, n, signedinUser={"user": user, "displayName": name})


def _entry(transcript_name: str, n: int, participant: str, text: str, start: str, end: str) -> dict[str, Any]:
    return {
        "name": f"{transcript_name}/entries/e{n}",
        "participant": participant,
        "text": text,
        "languageCode": "en-GB",
        "startTime": start,
        "endTime": end,
    }


def _server(key: Any) -> Fake:
    conferences = [
        {
            "name": A,
            "startTime": "2026-09-14T08:00:00.123Z",
            "endTime": "2026-09-14T08:45:00Z",
            "space": "spaces/s-a",
        },
        {
            "name": B,
            "startTime": "2026-09-15T10:00:00Z",
            "endTime": "2026-09-15T10:30:00Z",
            "space": "spaces/s-b",
        },
        {"name": C, "startTime": "2026-09-16T09:00:00Z", "space": "spaces/s-a"},  # still going on
        {
            "name": D,
            "startTime": "2026-09-15T14:00:00Z",
            "endTime": "2026-09-15T14:20:00Z",
            "space": "spaces/gone",
        },
    ]
    participants = {
        A: [
            _signed_in(A, 1, "users/1000", "Ines Nordmann"),
            _signed_in(A, 2, "users/1001", "Ola Nordmann"),
            _participant(A, 3, anonymousUser={"displayName": "Guest"}),
            _participant(A, 4, phoneUser={"displayName": "+44 7700 900•••"}),
        ],
        B: [_signed_in(B, 1, "users/1000", "Ines Nordmann"), _signed_in(B, 2, "users/1002", "Per Hansen")],
        D: [_signed_in(D, 1, "users/1000", "Ines Nordmann"), _signed_in(D, 2, "users/1001", "Ola Nordmann")],
    }
    ta, td = f"{A}/transcripts/t1", f"{D}/transcripts/t1"
    transcripts_by_record = {
        A: [
            {
                "name": ta,
                "state": "FILE_GENERATED",
                "startTime": "2026-09-14T08:01:00Z",
                "endTime": "2026-09-14T08:44:00Z",
                "docsDestination": {
                    "document": "doc-a",
                    "exportUri": "https://docs.google.com/document/d/doc-a",
                },
            }
        ],
        D: [
            {
                "name": td,
                "state": "ENDED",
                "startTime": "2026-09-15T14:01:00Z",
                "endTime": "2026-09-15T14:19:00Z",
            }
        ],
    }
    entries = {
        ta: [
            _entry(
                ta,
                1,
                f"{A}/participants/p1",
                "Morning. Shall we go over the mooring?",
                "2026-09-14T08:01:10Z",
                "2026-09-14T08:01:14Z",
            ),
            _entry(
                ta,
                2,
                f"{A}/participants/p2",
                "Yes, the long rope arrived.",
                "2026-09-14T08:01:15Z",
                "2026-09-14T08:01:18Z",
            ),
            _entry(
                ta,
                3,
                f"{A}/participants/p1",
                "Good. Saturday, then.",
                "2026-09-14T08:43:00Z",
                "2026-09-14T08:43:30Z",
            ),
        ],
        td: [
            _entry(
                td,
                1,
                f"{D}/participants/p2",
                "Quick one about the survey.",
                "2026-09-15T14:01:10Z",
                "2026-09-15T14:01:13Z",
            )
        ],
    }
    spaces = {
        "spaces/s-a": {
            "name": "spaces/s-a",
            "meetingCode": "abc-mnop-xyz",
            "meetingUri": "https://meet.google.com/abc-mnop-xyz",
        },
        "spaces/s-b": {
            "name": "spaces/s-b",
            "meetingCode": "def-ghij-klm",
            "meetingUri": "https://meet.google.com/def-ghij-klm",
        },
    }
    return Fake(
        key,
        conferences=conferences,
        participants=participants,
        transcripts=transcripts_by_record,
        entries=entries,
        spaces=spaces,
    )


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = _server(key)
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _config() -> service_account.Account:
    account = meet.configure(os.environ)
    assert account is not None
    return account


def _pull(**kw: Any) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, bytes]]:
    counts: dict[str, int] = {}
    stored: dict[str, bytes] = {}

    def store(data: bytes) -> None:
        stored[hashlib.sha256(data).hexdigest()] = data

    drafts = list(meet.pull(_config(), counts=counts, timezone="Europe/Oslo", store=store, **kw))
    return drafts, counts, stored


def _by(drafts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["payload"]["raw_id"]: d for d in drafts}


# -- registry and configuration -------------------------------------------------------------------


def test_registry_has_meet_as_a_live_adapter_on_the_one_key() -> None:
    assert adapters.live("meet") is meet
    assert meet.ENV == service_account.ENV and meet.configure is service_account.configure
    assert (meet.KIND, meet.TIER, meet.SCOPE) == ("event", 1, MEET_SCOPE)
    assert meet.TRANSCRIPT_TIER == transcript.TIER == granola.TIER, "built as Granola's, the same tier"
    assert "meet" in service_account.SOURCES and service_account.SCOPES["meet"] == MEET_SCOPE


# -- the conference: one event/v1 line ------------------------------------------------------------


def test_pull_writes_one_event_per_conference_that_has_ended_oldest_first(fake: Fake) -> None:
    drafts, counts, _ = _pull()
    events = [d for d in drafts if d["kind"] == "event"]
    assert [d["payload"]["raw_id"] for d in events] == ["meet:conf-a", "meet:conf-b", "meet:conf-d"]
    assert counts["held_ongoing"] == 1, "a call still going on waits for the run after it ends"
    assert all(d["source"] == "meet" and d["tier"] == 1 and d["tz"] == "Europe/Oslo" for d in events)


def test_an_event_has_the_span_a_title_and_the_participants_as_the_api_gives_them(fake: Fake) -> None:
    line = _by(_pull()[0])["meet:conf-a"]
    assert (line["at"], line["end"]) == ("2026-09-14T08:00:00.123Z", "2026-09-14T08:45:00Z")
    payload = line["payload"]
    assert payload["schema"] == "event/v1" and payload["all_day"] is False
    assert payload["title"] == "Meet abc-mnop-xyz", "the API keeps no title: the meeting code names it"
    assert payload["calendar"] == {"id": "google-meet", "name": "Google Meet"}
    assert payload["attendees"] == [
        {"ref": {"kind": "provider_id", "value": "users/1000"}, "name": "Ines Nordmann"},
        {"ref": {"kind": "provider_id", "value": "users/1001"}, "name": "Ola Nordmann"},
    ], "a signed-in participant is a Google account, as the API names it; never resolved here"
    extra = payload["extra"]
    assert extra["conference"] == A and extra["space"] == "spaces/s-a"
    assert extra["meeting_code"] == "abc-mnop-xyz"
    assert extra["participants"] == [
        {
            "kind": "signed-in",
            "user": "users/1000",
            "name": "Ines Nordmann",
            "joined": "2026-09-14T08:00:05Z",
        },
        {"kind": "signed-in", "user": "users/1001", "name": "Ola Nordmann", "joined": "2026-09-14T08:00:05Z"},
        {"kind": "anonymous", "name": "Guest", "joined": "2026-09-14T08:00:05Z"},
        {"kind": "phone", "name": "+44 7700 900•••", "joined": "2026-09-14T08:00:05Z"},
    ]


def test_a_space_the_owner_cannot_read_leaves_the_plain_title(fake: Fake) -> None:
    line = _by(_pull()[0])["meet:conf-d"]
    assert line["payload"]["title"] == "Meet call" and "meeting_code" not in line["payload"]["extra"]


# -- the transcript: one transcript/v1 line, as Granola's ------------------------------------------


def test_a_transcribed_call_is_one_transcript_line_built_as_granolas(fake: Fake) -> None:
    drafts, _counts, stored = _pull()
    line = _by(drafts)["meet:conf-a:transcript"]
    assert (line["source"], line["kind"], line["tier"]) == ("meet", "transcript", transcript.TIER)
    assert (line["at"], line["end"]) == ("2026-09-14T08:01:10Z", "2026-09-14T08:43:30Z")
    payload = line["payload"]
    assert payload["schema"] == "transcript/v1" and payload["provider"] == "meet"
    assert payload["title"] == "Meet abc-mnop-xyz" and payload["language"] == "en-GB"
    assert payload["participants"] == [
        {"name": "Ines Nordmann", "provider_id": "users/1000"},
        {"name": "Ola Nordmann", "provider_id": "users/1001"},
        {"name": "Guest"},
        {"name": "+44 7700 900•••"},
    ]
    assert payload["source_uri"] == "https://docs.google.com/document/d/doc-a"
    assert payload["extra"]["conference"] == A
    assert payload["extra"]["turns"] == 3 and payload["extra"]["speakers"] == 2
    content = payload["content"]
    assert (
        content["media_type"] == "application/json" and content["path"] == f"attachments/{content['sha256']}"
    )
    data = stored[content["sha256"]]
    assert content["bytes"] == len(data)
    assert "long rope" not in json.dumps(line), "the words are in the store, never in the line"
    turns = transcripts._json_turns(data.decode("utf-8"))
    assert [(t.speaker, t.text) for t in turns][1] == ("Ola Nordmann", "Yes, the long rope arrived.")


def test_the_transcript_line_is_the_mapping_granola_uses() -> None:
    """One mapping (`transcript.draft`, ADR 0017): the keys and their order are the file adapter's."""
    turns = [transcripts.Turn("Ines Nordmann", "Morning.")]
    made = transcript.draft(
        source="meet",
        at="2026-09-14T08:01:10Z",
        end="2026-09-14T08:01:14Z",
        raw_id="meet:x:transcript",
        content={
            "sha256": "0" * 64,
            "path": "attachments/" + "0" * 64,
            "bytes": 1,
            "media_type": "application/json",
        },
        turns=turns,
        tier=meet.TRANSCRIPT_TIER,
    )
    assert made["tier"] == granola.TIER and made["payload"]["provider"] == "meet"


def test_a_transcript_not_yet_generated_waits_and_the_call_without_one_has_none(fake: Fake) -> None:
    drafts, counts, _ = _pull()
    keys = set(_by(drafts))
    assert "meet:conf-d:transcript" not in keys and counts["transcript_pending"] == 1
    assert "meet:conf-b:transcript" not in keys
    assert [d["kind"] for d in drafts].count("transcript") == 1


# -- the API: what is asked, paging, backoff -------------------------------------------------------


def test_since_asks_for_the_conferences_started_from_then_on(fake: Fake) -> None:
    drafts, _, _ = _pull(since="2026-09-15T00:00:00Z")
    assert {d["payload"]["raw_id"] for d in drafts} == {"meet:conf-b", "meet:conf-d"}
    asked = fake.calls("meet.googleapis.com/v2/conferenceRecords")
    assert asked[0]["filter"] == 'start_time>="2026-09-15T00:00:00Z"'


def test_pull_pages_until_the_last_page_and_reports_each(fake: Fake) -> None:
    fake.page = 2
    reported: list[int] = []
    drafts, _, _ = _pull(progress=lambda n, _s: reported.append(n))
    assert len(drafts) == 4
    tokens = [c.get("pageToken") for c in fake.calls("meet.googleapis.com/v2/conferenceRecords")]
    assert tokens == [None, "2"] and reported == [2, 4]
    assert [c.get("pageToken") for c in fake.calls(f"meet.googleapis.com/v2/{A}/participants")] == [None, "2"]


def test_pull_backs_off_on_429_and_5xx_and_carries_on(fake: Fake) -> None:
    fake.fail(503)
    fake.fail(429, retry_after="5")
    drafts, _, _ = _pull()
    assert len(drafts) == 4 and fake.waits == [1.0, 5.0]  # type: ignore[attr-defined]


def test_the_client_only_reads(fake: Fake) -> None:
    _pull()
    assert fake.methods() == {("POST", "oauth2.googleapis.com"), ("GET", "meet.googleapis.com")}
    assert {c["scope"] for c in fake.assertions} == {MEET_SCOPE}


def test_a_conference_the_record_holds_is_not_asked_about_again(fake: Fake) -> None:
    def existing(keys: Any) -> set[tuple[str, str]]:
        return {k for k in keys if k[1] in ("meet:conf-a", "meet:conf-a:transcript")}

    drafts, counts, _ = _pull(existing=existing)
    assert "meet:conf-a" not in _by(drafts) and counts["conference_in_record"] == 1
    assert fake.calls(f"meet.googleapis.com/v2/{A}/participants") == []
    assert fake.calls(f"meet.googleapis.com/v2/{A}/transcripts") == []


def test_watermark_is_the_conference_start_and_resume_looks_back_a_day(fake: Fake) -> None:
    by = _by(_pull()[0])
    assert meet.watermark(by["meet:conf-a"]) == "2026-09-14T08:00:00Z", "whole seconds: marks compare as text"
    assert meet.watermark(by["meet:conf-a:transcript"]) is None, "the event carries the conference's start"
    assert meet.resume(_config(), "2026-09-15T14:00:00Z") == "2026-09-14T14:00:00Z"


# -- sync: the CLI --------------------------------------------------------------------------------


def _sync(*args: str, source: str = "meet") -> int:
    try:
        cli.main(["sync", source, *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _lines(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lb.lines() if line["source"] == "meet"}


def test_sync_first_run_writes_the_calls_and_the_transcript_and_the_second_none(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "meet: 4 new lines of 4 seen from the beginning" in out
    assert "1 still going on" in out and "1 with a transcript not generated yet" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 4
    lines = _lines(lb)
    assert {(x["kind"], x["tier"]) for x in lines.values()} == {("event", 1), ("transcript", transcript.TIER)}
    sha = lines["meet:conf-a:transcript"]["payload"]["content"]["sha256"]
    assert (lb.root / "attachments" / sha).is_file()
    state = json.loads((lb.root / "state" / "meet.json").read_text(encoding="utf-8"))
    assert state["since"] == "2026-09-15T14:00:00Z"
    assert _sync() == 0
    assert "meet: 0 new lines of" in capsys.readouterr().out
    assert lb.meta["seq"] == 4


def test_sync_a_transcript_generated_later_is_written_and_the_call_not_again(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    _sync()
    fake.transcripts[D][0]["state"] = "FILE_GENERATED"
    assert _sync() == 0
    assert "meet: 1 new lines of 1 seen" in capsys.readouterr().out
    late = _lines(lb)["meet:conf-d:transcript"]
    assert late["payload"]["participants"][0] == {"name": "Ines Nordmann", "provider_id": "users/1000"}
    assert sum(1 for x in lb.lines() if x["payload"]["raw_id"] == "meet:conf-d") == 1


def test_sync_since_is_used_as_given(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--since", "2026-09-15T12:00:00Z") == 0
    assert "meet: 1 new lines of 1 seen since 2026-09-15T12:00:00Z" in capsys.readouterr().out
    assert set(_lines(lb)) == {"meet:conf-d"}


def test_sync_dry_run_counts_and_writes_nothing(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--dry-run") == 0
    out = capsys.readouterr().out
    assert "meet: 4 lines from the beginning (dry run, nothing written)" in out
    assert "event: 3" in out and "transcript: 1" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()
    assert not (lb.root / "attachments").exists() or not any((lb.root / "attachments").iterdir())


def test_a_granola_transcript_of_the_same_call_is_a_line_of_its_own(lb: Logbook, fake: Fake) -> None:
    """Two providers, two transcripts: each is what its source produced (RFC 0004), with its own words,
    speakers and id; that they are one call is a reader's judgement, never the adapter's."""
    note = {"id": "not_1", "title": "Mooring", "created_at": "2026-09-14T08:00:00Z", "attendees": []}
    segments = [
        {
            "speaker": {"source": "microphone", "attribution": "me"},
            "text": "Morning.",
            "start_time": "2026-09-14T08:01:09Z",
            "end_time": "2026-09-14T08:01:12Z",
        },
    ]
    lb.append_many([granola.transcript_of(note, segments)])
    assert _sync() == 0
    kinds = sorted((x["source"], x["payload"]["raw_id"]) for x in lb.lines() if x["kind"] == "transcript")
    assert kinds == [("granola", "granola:not_1"), ("meet", "meet:conf-a:transcript")]


def test_sync_without_the_meet_scope_delegated_is_one_line_and_exit_1(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    fake.delegated = {DRIVE_SCOPE}
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: meet:") and MEET_SCOPE in err


def test_doctor_shows_sync_meet_and_asks_google_nothing(lb: Logbook, fake: Fake) -> None:
    checks = {c.name: c for c in doctor.run(lb, dict(os.environ), installed=lambda _m: True)}
    assert checks["sync:meet"].status == "pass"
    assert f"configured ({KEY_ENV}, {USER_ENV})" in checks["sync:meet"].detail
    assert "meet" in checks["google"].detail
    assert fake.requests == []


def test_people_review_sees_a_participant_by_the_account_the_api_names(lb: Logbook, fake: Fake) -> None:
    from logbook.contrib import people_review

    assert _sync() == 0
    rows = {row.key: row for row in people_review.observed(lb)}
    ola = rows[("name", "nordmann ola")]
    assert ("provider_id", "users/1001") in ola.identifiers and ola.entity is None
    assert set(ola.kinds) == {"event", "transcript"} and ola.writable == [("provider_id", "users/1001")]
    assert rows[("name", "guest")].writable == [], "a guest is a display name alone: listed, never proposed"
