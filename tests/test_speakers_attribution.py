"""Who a voice is (RFC 0038 §3): the `speaker` ref, one standing `resolution/v1` line per voice, and
the join every reader makes through the identities (`resolve.identities_from`,
`attribution.Voices`). The transcript line is never touched; the owner's `from_me` microphone is the
owner's without a line, and a standing line wins over it; a retracted line binds nothing; a
correction supersedes; an attribution of a transcript heard again names nothing on the new line,
whose labels are new refs. Synthetic Oslo persona (`speakers_record`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from persona import TZ
from speakers_record import (
    CALL,
    DINNER,
    DINNER_TEXT,
    KARI_ID,
    OLA_ID,
    ROOM,
    TWO_CHANNELS,
    attribution,
    dinner_record,
    transcript,
)

from logbook.core import attribution as voices_of
from logbook.core import resolve
from logbook.core.store import Logbook

AT = "2026-10-03T17:40:12Z"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return [*idx.retractions(), *idx.resolutions()]


def _heard(lb: Logbook, line_id: str) -> dict[str, voices_of.Heard]:
    identities = resolve.identities_from(_lines(lb))
    owner = str(lb.meta["owner_id"])
    line = next(line for line in lb.lines() if line.get("id") == line_id)
    return {h.label: h for h in voices_of.Voices(identities, (owner,), owner).of(line)}


def test_the_ref_is_the_line_id_and_the_label_split_at_the_first_hash() -> None:
    assert voices_of.ref_value(DINNER, "S2") == f"{DINNER}#S2"
    assert voices_of.split(f"{DINNER}#S2") == (DINNER, "S2")
    assert voices_of.split(f"{DINNER}#mic.2") == (DINNER, "mic.2")
    assert voices_of.split(DINNER) is None
    assert voices_of.split(f"{DINNER}#") is None
    assert voices_of.split(f"{DINNER}#a#b") is None  # a label never holds a `#`


def test_a_speaker_ref_carries_basis_consent_confidence_and_unnamed_and_other_refs_do_not() -> None:
    lines = [
        {"seq": 1, "id": "r1", **attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann", consent="yes")},
        {
            "seq": 2,
            "id": "r2",
            **attribution(DINNER, "S3", "019cadd3-6bc0-7dcd-9133-000000000403", unnamed=True),
        },
        {"seq": 3, "id": "r3", **attribution(DINNER, "S4", KARI_ID, basis="text", confidence=0.4)},
        {
            "seq": 4,
            "id": "r4",
            "kind": "resolution",
            "payload": {
                "schema": "resolution/v1",
                "ref": {"kind": "email", "value": "kari@example.org"},
                "entity": {"type": "person", "id": KARI_ID, "registry": "logbook"},
                "label": "Kari Nordmann",
                "basis": "voice",  # meaningless on any other ref: never read
            },
        },
    ]
    found = resolve.identities_from(lines)
    assert found[("speaker", f"{DINNER}#S2")] == resolve.Identity(
        KARI_ID, "person", "Kari Nordmann", False, "voice", "yes", None
    )
    assert found[("speaker", f"{DINNER}#S3")].unnamed is True
    assert found[("speaker", f"{DINNER}#S3")].label is None
    assert found[("speaker", f"{DINNER}#S4")].confidence == 0.4
    assert found[("speaker", f"{DINNER}#S4")].basis == "text"
    assert found[("email", "kari@example.org")] == resolve.Identity(KARI_ID, "person", "Kari Nordmann")
    assert found[("email", "kari@example.org")].basis is None


def test_values_the_profile_does_not_allow_are_read_as_absent() -> None:
    line = attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann")
    line["payload"].update({"basis": "guess", "consent": "maybe", "confidence": 7})
    found = resolve.identities_from([{"seq": 1, "id": "r1", **line}])[("speaker", f"{DINNER}#S2")]
    assert (found.basis, found.consent, found.confidence) == (None, None, None)


def test_each_voice_is_the_owners_a_persons_unnamed_or_not_yet_named(lb: Logbook) -> None:
    dinner_record(lb, with_text=False)
    owner = str(lb.meta["owner_id"])
    neighbour = "019cadd3-6bc0-7dcd-9133-000000000403"
    lb.append_many(
        [
            attribution(DINNER, "S1", owner),  # the owner bound by a line: no label (docs/people.md)
            attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann", consent="yes"),
            attribution(DINNER, "S3", neighbour, unnamed=True),
        ]
    )
    heard = _heard(lb, DINNER)
    assert [(h.label, h.state, h.shown) for h in heard.values()] == [
        ("S1", "owner", "you"),
        ("S2", "person", "Kari Nordmann"),
        ("S3", "unnamed", "unnamed"),
    ]
    assert heard["S2"].to_json() == {
        "label": "S2",
        "person": KARI_ID,
        "name": "Kari Nordmann",
        "seconds": 861.0,
        "basis": "voice",
        "consent": "yes",
        "owner": False,
    }
    assert heard["S3"].to_json()["person"] is None  # never named, not even by its id
    assert heard["S3"].to_json()["consent"] == "unknown"  # absent reads as unknown (§3.2)
    assert heard["S1"].to_json()["person"] == owner
    call = _heard(lb, CALL)
    assert call["mic"].state == "owner" and call["mic"].basis == "channel"  # from_me, no line
    assert call["system"].state == "not yet named" and call["system"].far_end
    assert call["system"].to_json() == {
        "label": "system",
        "person": None,
        "name": None,
        "seconds": 188.3,
        "basis": None,
        "consent": None,
        "owner": False,
    }


def test_a_standing_line_wins_over_from_me_and_a_retraction_gives_it_back(lb: Logbook) -> None:
    """§3.3 rule 4: someone else spoke into the owner's phone. Rule 2: a retracted line binds nothing."""
    dinner_record(lb, with_text=False)
    line = lb.append(**_draft(attribution(CALL, "mic", KARI_ID, name="Kari Nordmann")))
    assert _heard(lb, CALL)["mic"].state == "person"
    lb.retract(int(line["seq"]), "it was me after all")
    assert _heard(lb, CALL)["mic"].state == "owner"


def test_a_correction_supersedes_and_the_last_standing_line_decides(lb: Logbook) -> None:
    """§3.3 rule 3, RFC 0038 §11: the call's far end was Kari, not Ola; the wrong line stays."""
    dinner_record(lb, with_text=False)
    wrong = lb.append(**_draft(attribution(CALL, "system", OLA_ID, name="Ola Nordmann", basis="channel")))
    assert _heard(lb, CALL)["system"].name == "Ola Nordmann"
    lb.append(
        **_draft(attribution(CALL, "system", KARI_ID, name="Kari Nordmann", supersedes=str(wrong["id"])))
    )
    heard = _heard(lb, CALL)["system"]
    assert (heard.entity, heard.basis) == (KARI_ID, "voice")
    assert any(line.get("id") == wrong["id"] for line in lb.lines()), "the wrong line stays in the record"


def test_a_voice_said_to_be_another_voice_resolves_to_whatever_that_one_does(lb: Logbook) -> None:
    dinner_record(lb, with_text=False)
    neighbour = "019cadd3-6bc0-7dcd-9133-000000000403"
    lb.append_many(
        [
            attribution(DINNER, "S3", neighbour, unnamed=True, consent="no"),
            attribution(CALL, "system", "", alias_of=f"{DINNER}#S3", consent="yes"),
        ]
    )
    heard = _heard(lb, CALL)["system"]
    assert (heard.state, heard.entity) == ("unnamed", neighbour)
    assert heard.consent == "yes", "consent is the voice's own line's, not the voice it is the same as"


def test_a_transcript_heard_again_is_a_new_line_whose_voices_are_new_refs(lb: Logbook) -> None:
    """§3.1: the old line's attribution names nothing on the line that supersedes it."""
    dinner_record(lb, with_text=False)
    lb.append(**_draft(attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann")))
    again = "019cadd3-6bc0-7dcd-9133-0000000004a9"
    lb.append_many(
        [transcript(again, AT, None, "Middag", ROOM, raw_id="memo-04a1#speakers@a9e2", supersedes=DINNER)]
    )
    assert _heard(lb, again)["S2"].state == "not yet named"
    assert _heard(lb, DINNER)["S2"].state == "person"  # the old line's, read by a reader of it alone


def test_a_line_naming_nobody_leaves_the_voice_as_the_source_put_it(lb: Logbook) -> None:
    """An alias to a voice no line binds names nothing (RFC 0006 rule 6); `from_me` stands."""
    dinner_record(lb, with_text=False)
    lb.append(**_draft(attribution(CALL, "mic", "", alias_of=f"{DINNER}#S2")))
    assert _heard(lb, CALL)["mic"].state == "owner"
    assert _heard(lb, CALL)["system"].state == "not yet named"


def test_voiced_turns_cut_the_text_by_voice_and_refuse_a_spans_file_that_does_not_fit(lb: Logbook) -> None:
    dinner_record(lb)
    line = next(line for line in lb.lines() if line.get("id") == DINNER)
    turns = voices_of.voiced_turns(lb, line)
    assert turns is not None
    assert [(t.speaker, t.text) for t in turns] == [(label, text) for label, text in DINNER_TEXT]
    bad = {**line, "payload": {**line["payload"], "diarization": {**line["payload"]["diarization"]}}}
    bad["payload"]["diarization"]["spans"] = line["payload"]["content"]  # the text itself: not a spans file
    assert voices_of.voiced_turns(lb, bad) is None
    plain = {
        **line,
        "payload": {k: v for k, v in line["payload"].items() if k not in ("speakers", "diarization")},
    }
    assert voices_of.voiced_turns(lb, plain) is None


def test_two_channels_and_a_room_are_read_as_the_rfc_has_them() -> None:
    line = transcript(CALL, AT, None, "Samtale", TWO_CHANNELS)
    voices = voices_of.Voices({}, (), "019cadd3-6bc0-7dcd-9133-000000000400").of(line)
    assert [(h.label, h.state, h.far_end) for h in voices] == [
        ("mic", "owner", False),
        ("system", "not yet named", True),
    ]
    room = voices_of.Voices({}, (), None).of(transcript(DINNER, AT, None, "Middag", ROOM))
    assert [h.state for h in room] == ["not yet named"] * 3  # a room's first voice is nobody's yet


def _draft(line: dict[str, Any]) -> dict[str, Any]:
    return {k: line[k] for k in ("at", "source", "kind", "tier", "payload")}
