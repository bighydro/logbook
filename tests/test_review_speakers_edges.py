"""Edges of `review speakers` (RFC 0038 §3.2, §4.2, §4.4, §10) the main tests do not reach: the one
writer of a `speaker` resolution, the dedupe key when consent is absent, a ref nobody has given as a
name, the terminal's minting, and the confidence of a name typed with no proposal. Synthetic Oslo
persona (`speakers_record`); nothing real, nothing decoded, no socket."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import TZ
from speakers_record import DINNER, KARI, KARI_ID, attribution, dinner_record, resolution

from logbook import cli
from logbook.core.attribution import BASES, SPEAKER
from logbook.core.store import Logbook

OWNER_EMAIL = "ines@example.org"


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


def _terminal(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    said = iter(answers)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(said))


# -- the one writer (§3.2) ---------------------------------------------------------------------------------


def test_people_merge_writes_no_speaker_resolution_without_basis(lb: Logbook, capsys) -> None:
    """§3.2: `basis` is a MUST on a line with a `speaker` ref, and the review is the one writer. A
    merge aliases every ref of the secondary person; a voice bound to them is evidence of the
    person, not one of their refs (`people._people_of`), and must not come out as a `speaker` line
    with no `basis` and an `alias_of` that is not a voice."""
    twin = "019cadd3-6bc0-7dcd-9133-0000000004c2"
    lb.append_many(
        [
            resolution(("provider_id", "ios-contacts:42"), KARI_ID, KARI["name"]),  # Kari: 3 refs, primary
            resolution(("handle", "447700900102@s.whatsapp.net"), twin, "Kari"),  # her number, another id
        ]
    )
    _run(capsys, "--name", "2", twin)  # the owner binds S2 of the dinner to the twin
    cli.main(["people", "merge", "--json"])
    (proposal,) = json.loads(capsys.readouterr().out)["proposals"]
    assert {proposal["primary"]["id"], *(s["id"] for s in proposal["secondary"])} == {KARI_ID, twin}
    before = _seq(lb)
    cli.main(["people", "merge", "--apply", proposal["id"]])
    capsys.readouterr()
    for line in _written(lb, before):
        p = line["payload"]
        if line["kind"] != "resolution" or p["ref"]["kind"] != SPEAKER:
            continue
        assert p.get("basis") in BASES, f"a speaker line without basis: {p}"
        assert "entity" in p or p.get("alias_of", {}).get("kind") == SPEAKER, p


# -- the dedupe key (§10) with consent absent --------------------------------------------------------------


def test_a_standing_consent_unknown_and_an_answer_without_consent_write_nothing(lb: Logbook, capsys) -> None:
    """§3.2: consent absent reads as `unknown`; §10: the same entity, basis and consent as the standing
    line write nothing. The RFC's own examples (§11) write `consent: unknown` out, as the terminal's
    Enter does, so a record that followed them meets this on its first correction."""
    lb.append_many([attribution(DINNER, "S2", KARI_ID, name=KARI["name"], basis="voice", consent="unknown")])
    rows = _json(capsys, "--named", "--recording", DINNER)["rows"]
    n = next(str(r["number"]) for r in rows if r["voices"][0]["label"] == "S2")
    before = _seq(lb)
    out = _run(capsys, "--named", "--recording", DINNER, "--accept", n)
    assert _written(lb, before) == [], out


def test_a_standing_consent_absent_and_an_answer_of_unknown_write_nothing(lb: Logbook, capsys) -> None:
    """The other direction of the same key: `--consent N=unknown` says what the standing line, with
    no `consent`, already reads as."""
    lb.append_many([attribution(DINNER, "S2", KARI_ID, name=KARI["name"], basis="voice")])
    rows = _json(capsys, "--named", "--recording", DINNER)["rows"]
    n = next(str(r["number"]) for r in rows if r["voices"][0]["label"] == "S2")
    before = _seq(lb)
    out = _run(capsys, "--named", "--recording", DINNER, "--accept", n, "--consent", f"{n}=unknown")
    assert _written(lb, before) == [], out


# -- `--name` with a ref (§4.4) ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["phone:+447700900999", "+447700900999", "nobody@example.org", "email:nobody@example.org"],
)
def test_a_ref_the_record_does_not_resolve_is_refused_not_minted(lb: Logbook, capsys, text: str) -> None:
    """§4.4: `--name` names a person by a ref the record resolves; a name nobody has mints a person.
    A ref nobody has is neither: minting a person labelled `phone:+447700900999` is a mistake the
    record then keeps, as an unknown id is already refused (`is no person the record names`)."""
    before = _seq(lb)
    err = _refused(capsys, "--name", "3", text)
    assert _written(lb, before) == [], err


def test_the_owners_own_address_names_the_owner(lb: Logbook, capsys) -> None:
    """`owner_emails` of logbook.json is the owner's (present.Owner.refs) with no resolution line;
    `--name N <that address>` is the owner, not a person minted under their address as a label."""
    lb.set_owner_emails([OWNER_EMAIL])
    before = _seq(lb)
    out = _run(capsys, "--name", "1", OWNER_EMAIL)
    (line,) = _written(lb, before)
    p = line["payload"]
    assert p["entity"]["id"] == lb.meta["owner_id"] and "label" not in p, (out, p)


# -- the terminal (§4.2) -----------------------------------------------------------------------------------


def test_on_a_terminal_one_new_name_for_two_rows_is_one_person(lb: Logbook, capsys, monkeypatch) -> None:
    """One sitting, two rows answered with the same new name: one person, as two `--name` of one
    command mint one. The terminal answers row by row against the listing it read at the start, so
    the second answer must see what the first minted."""
    _terminal(monkeypatch, ["Per Hansen", "", "Per Hansen", "", "q"])
    before = _seq(lb)
    cli.main(["review", "speakers"])
    capsys.readouterr()
    written = _written(lb, before)
    assert [line["payload"].get("label") for line in written] == ["Per Hansen", "Per Hansen"]
    assert len({line["payload"]["entity"]["id"] for line in written}) == 1, "one Per Hansen, not two"


def test_on_a_terminal_y_on_a_row_proposing_nobody_mints_nobody(lb: Logbook, capsys, monkeypatch) -> None:
    """§4.2: `y` accepts. A row with no candidate has nothing to accept: the sitting says so and asks
    again, as the flags do (`row N proposes nobody`); it never mints a person called `y`."""
    _run(capsys, "--reject", "3")  # S3 was never Kari: the row now proposes nobody, `____`
    _terminal(monkeypatch, ["", "", "y", "", "q"])
    before = _seq(lb)
    cli.main(["review", "speakers"])
    out = capsys.readouterr().out
    written = _written(lb, before)
    assert written == [], out
    assert "proposes nobody" in out


# -- a name typed with no proposal (§3.2, basis `text`) ----------------------------------------------------


def test_a_name_typed_with_no_proposal_does_not_read_as_no_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """§3.2: a text attribution's `confidence` is the proposal's score over 100, at most the cap, so a
    voice named from the words alone never reads as surer than one heard. The owner typing a name
    the record proposed nobody for has no score: the line must not say `confidence: 0`, which every
    reader (§3.4 `with`: the line's confidence becomes the reader's) takes as no confidence at all."""
    lb = Logbook.init(tmp_path / "quiet", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    dinner_record(lb, audio=False)
    before = _seq(lb)
    _run(capsys, "--name", "3", "Per Hansen")
    (line,) = _written(lb, before)
    p = line["payload"]
    assert p["basis"] == "text" and p["label"] == "Per Hansen"
    assert 0 < p["confidence"] <= 0.6, p


# -- from the independent review -----------------------------------------------------------------------------


def test_a_bound_voice_is_read_ahead_of_the_same_persons_participant_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.4 `with`: a voice bound to a person is company ahead of rule 2's participant match, and the
    line's confidence is the reader's: a text attribution's 0.4 reads as 0.4, not the participant's 0.9."""
    from persona import HOME, dwell, utc
    from speakers_record import DINNER_DAY, ROOM, people, transcript

    from logbook.core import day as day_reader

    lb = Logbook.init(tmp_path / "both", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            *people(),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            transcript(
                DINNER,
                utc(DINNER_DAY, "19:40"),
                utc(DINNER_DAY, "20:52"),
                "Middag",
                ROOM,
                participants=[{"name": KARI["name"], "email": KARI["email"]}],
            ),
            attribution(DINNER, "S2", KARI_ID, name=KARI["name"], basis="text", confidence=0.4),
        ]
    )
    stay = next(e for e in day_reader.read(lb, DINNER_DAY)["timeline"] if e["kind"] == "stay")
    (kari,) = stay["with"]["confirmed"]
    assert (kari["confidence"], kari["reasons"]) == (0.4, ["spoke in Middag"])


def test_a_merge_says_which_voices_stay_with_the_person_merged_away(lb: Logbook, capsys) -> None:
    twin = "019cadd3-6bc0-7dcd-9133-0000000004c2"
    lb.append_many(
        [
            resolution(("provider_id", "ios-contacts:42"), KARI_ID, KARI["name"]),
            resolution(("handle", "447700900102@s.whatsapp.net"), twin, "Kari"),
        ]
    )
    _run(capsys, "--name", "2", twin)
    cli.main(["people", "merge", "--json"])
    (proposal,) = json.loads(capsys.readouterr().out)["proposals"]
    cli.main(["people", "merge", "--apply", proposal["id"]])
    out = capsys.readouterr().out
    assert "1 voice stays bound to Kari: `review speakers --named`" in out, out


def test_an_entry_already_scored_is_not_seen_that_day_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """§4.3: on the entry is 15; the same entry is not also `seen that day`."""
    from persona import HOME, dwell, utc
    from speakers_record import DINNER_DAY, ROOM, event, people, transcript

    lb = Logbook.init(tmp_path / "entry", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            *people(),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            event(
                utc(DINNER_DAY, "19:30"),
                utc(DINNER_DAY, "22:00"),
                "Middag med Kari",
                [{"ref": {"kind": "email", "value": KARI["email"]}, "response": "accepted"}],
            ),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
        ]
    )
    (kari,) = _json(capsys)["rows"][0]["candidates"]
    assert (kari["score"], kari["matched"]) == (15, ['on the entry "Middag med Kari"'])


def test_naming_one_person_for_two_voices_of_a_recording_says_so(lb: Logbook, capsys) -> None:
    """§13.1: two labels may be one person, so it is allowed; the owner is told."""
    out = _run(capsys, "--name", "2", KARI["name"], "--name", "3", KARI["name"])
    assert "also S2 of the recording" in out or "also S3 of the recording" in out, out


def test_a_named_voice_answered_unnamed_supersedes_its_line(lb: Logbook, capsys) -> None:
    lb.append_many([attribution(DINNER, "S2", KARI_ID, name=KARI["name"])])
    standing = next(
        line
        for line in Logbook(lb.root).lines()
        if (line.get("payload") or {}).get("ref", {}).get("kind") == SPEAKER
    )
    rows = _json(capsys, "--named", "--recording", DINNER)["rows"]
    n = next(str(r["number"]) for r in rows if r["voices"][0]["label"] == "S2")
    before = _seq(lb)
    _run(capsys, "--named", "--recording", DINNER, "--unnamed", n)
    (line,) = _written(lb, before)
    assert line["payload"]["unnamed"] is True and line["payload"]["supersedes"] == standing["id"]
    assert line["payload"]["entity"]["id"] != KARI_ID and "label" not in line["payload"]


def test_on_a_terminal_y_on_two_close_candidates_is_refused(lb: Logbook, capsys, monkeypatch) -> None:
    from persona import HOME, dwell, utc
    from speakers_record import OLA, ROOM, message, transcript

    room = "019cadd3-6bc0-7dcd-9133-0000000004d8"
    lb.append_many(
        [
            message(utc("2026-10-08", "09:00"), OLA["phone"], "Kommer!"),
            message(utc("2026-10-08", "09:05"), KARI["phone"], "Jeg også"),
            *dwell("2026-10-08", "08:00", "12:00", HOME),
            transcript(room, utc("2026-10-08", "10:00"), utc("2026-10-08", "10:30"), "Møte", ROOM[:1]),
        ]
    )
    rows = _json(capsys)["rows"]
    close = next(r["number"] for r in rows if r["close"])
    _terminal(monkeypatch, [*([""] * (close - 1)), "y", "q"])
    before = _seq(lb)
    cli.main(["review", "speakers"])
    out = capsys.readouterr().out
    assert _written(lb, before) == [] and "proposes two, neither taken" in out


def test_a_row_names_its_place_as_the_day_does(lb: Logbook, capsys) -> None:
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 150, "kind": "home"}}),
        encoding="utf-8",
    )
    first = _json(capsys)["rows"][0]["voices"][0]
    assert first["where"] == "Home"
