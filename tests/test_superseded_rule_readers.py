"""Issue #321 through the two readers it named: `review speakers` and the voiceprint registry's
`standing_voices` read a transcript heard again by the index's one rule — a line is superseded while
at least one line of its kind that is not retracted supersedes it. Plus the index's edges: a superseder
of another kind counts for nothing, a superseder written before the line it names counts, and a sealed
record (RFC 0029) read with the identity says the same kept current and rebuilt. Ines Nordmann of Oslo,
who does not exist (`speakers_record`): A is the dinner transcript, B and C are heard again."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, utc
from speakers_record import CALL, DINNER, DINNER_DAY, ROOM, dinner_record, transcript
from voiceprints_record import seal

from logbook import cli
from logbook.core import voiceprints
from logbook.core.store import Logbook

B = "019cadd3-6bc0-7dcd-9133-0000000004b1"
C = "019cadd3-6bc0-7dcd-9133-0000000004c1"
IDS = {"A": DINNER, "B": B, "C": C}

# (shape, retracted) → the transcripts of the dinner that stand: every case of the issue
CASES = [
    ("twice", "", "BC"),
    ("twice", "C", "B"),  # #321: C retracted, B still supersedes A; A must not come back
    ("twice", "B", "C"),
    ("twice", "BC", "A"),  # no superseder stands: A stands again
    ("chain", "", "C"),  # A←B←C
    ("chain", "C", "B"),  # C retracted: B stands and still supersedes A
    ("chain", "B", "AC"),  # B retracted: it supersedes nothing, so A stands beside C
    ("chain", "BC", "A"),
]


def _heard_again(id_: str, supersedes: str) -> dict[str, Any]:
    return transcript(
        id_,
        utc(DINNER_DAY, "19:40"),
        utc(DINNER_DAY, "20:52"),
        "Middag",
        ROOM,
        raw_id=f"memo-04a1#speakers@{id_[-4:]}",
        supersedes=supersedes,
    )


def _seqs(lb: Logbook) -> dict[str, int]:
    return {
        name: int(line["seq"]) for line in Logbook(lb.root).lines() for name in IDS if line["id"] == IDS[name]
    }


def _shape(lb: Logbook, shape: str, retracted: str) -> None:
    """B and C heard again, both of A (`twice`) or C of B (`chain`); then the retractions."""
    lb.append_many([_heard_again(B, DINNER), _heard_again(C, DINNER if shape == "twice" else B)])
    seqs = _seqs(lb)
    for name in retracted:
        lb.retract(seqs[name], "heard wrong")


def _dinner_lines(refs: list[str]) -> set[str]:
    return {name for ref in refs for name in IDS if ref.startswith(IDS[name])}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    dinner_record(lb)
    return lb


@pytest.mark.parametrize(("shape", "retracted", "standing"), CASES)
def test_review_speakers_asks_the_voices_of_the_transcripts_that_stand(
    lb: Logbook, capsys: pytest.CaptureFixture[str], shape: str, retracted: str, standing: str
) -> None:
    _shape(lb, shape, retracted)
    cli.main(["review", "speakers", "--json"])
    report = json.loads(capsys.readouterr().out)
    refs = [v["ref"] for row in report["rows"] for v in row["voices"]]
    assert _dinner_lines(refs) == set(standing), refs
    assert any(ref.startswith(CALL) for ref in refs)  # the call is untouched


@pytest.mark.parametrize(("shape", "retracted", "standing"), CASES)
def test_standing_voices_are_those_of_the_transcripts_that_stand(
    lb: Logbook, shape: str, retracted: str, standing: str
) -> None:
    _shape(lb, shape, retracted)
    heard, owner = voiceprints.standing_voices(Logbook(lb.root))
    assert owner == str(lb.meta["owner_id"])
    assert _dinner_lines([h.ref for _line, h in heard]) == set(standing)
    assert {str(line["id"]) for line, _h in heard} == {IDS[n] for n in standing} | {CALL}


def test_the_index_agrees_with_itself_rebuilt_after_a_retraction_appended_later(lb: Logbook) -> None:
    """The incremental index and a rebuild answer alike at every step: after the heard-again lines,
    after a retraction that changes the answer for lines appended earlier, and after the second."""
    lb.append_many([_heard_again(B, DINNER), _heard_again(C, DINNER)])
    seqs = _seqs(lb)
    want = [{DINNER: seqs["C"]}, {DINNER: seqs["B"]}, {}]
    for step, expected in enumerate(want):
        if step:
            lb.retract(seqs["CB"[step - 1]], "heard wrong")
        with lb.index() as idx:
            assert idx.superseded("transcript") == expected, step
        lb.index_rebuild()
        with lb.index() as idx:
            assert idx.superseded("transcript") == expected, (step, "rebuilt")


def test_a_superseder_of_another_kind_counts_for_nothing(lb: Logbook) -> None:
    """Only a line of the same kind supersedes (SPEC §3): a note that says `supersedes` A is not a
    transcript heard again, and a retraction of it changes nothing for transcripts."""
    note = lb.append(
        at=utc(DINNER_DAY, "21:00"),
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "raw_id": "n-1", "text": "not a transcript", "supersedes": DINNER},
    )
    with lb.index() as idx:
        assert idx.superseded("transcript") == {}
        assert idx.superseded("note") == {DINNER: int(note["seq"])}
    lb.retract(int(note["seq"]), "a note is not a hearing")
    with lb.index() as idx:
        assert idx.superseded("transcript") == {} and idx.superseded("note") == {}


def test_a_superseder_written_before_the_line_it_names_still_counts(lb: Logbook) -> None:
    """`supersedes` is read as written, whatever the order in the chain: B at a lower seq naming A
    appended after it supersedes A, until B is retracted."""
    early = "019cadd3-6bc0-7dcd-9133-0000000004d1"
    late = "019cadd3-6bc0-7dcd-9133-0000000004d2"
    lb.append_many([_heard_again(early, late)])
    lb.append_many([_heard_again(late, CALL)])  # `late` itself names a line of its kind (the call)
    lines = {str(line["id"]): int(line["seq"]) for line in Logbook(lb.root).lines()}
    assert lines[early] < lines[late]
    with lb.index() as idx:
        assert idx.superseded("transcript") == {late: lines[early], CALL: lines[late]}
    lb.retract(lines[early], "heard wrong")
    with lb.index() as idx:
        assert idx.superseded("transcript") == {CALL: lines[late]}
    lb.index_rebuild()
    with lb.index() as idx:
        assert idx.superseded("transcript") == {CALL: lines[late]}


@pytest.mark.parametrize(("shape", "retracted", "standing"), CASES)
def test_a_sealed_record_read_with_the_identity_says_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str, retracted: str, standing: str
) -> None:
    """RFC 0029: the transcripts and the retractions are tier 2 and so sealed; with the identity the
    index reads `supersedes` from the opened payloads, kept current and rebuilt alike, and the
    `review speakers` queue says what the open record's does."""
    lb = seal(Logbook.init(tmp_path / "lb", TZ), monkeypatch, tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    dinner_record(lb)
    _shape(lb, shape, retracted)
    seqs = _seqs(lb)
    gone = {IDS[n] for n in "ABC" if n not in standing and n not in retracted}
    with lb.index() as idx:
        found = idx.superseded("transcript")
        assert set(found) - {IDS[n] for n in retracted} == gone
        assert all(seq in seqs.values() and seq != seqs.get("A") for seq in found.values())
    lb.index_rebuild()
    with lb.index() as idx:
        assert set(idx.superseded("transcript")) - {IDS[n] for n in retracted} == gone
    heard, _owner = voiceprints.standing_voices(Logbook(lb.root))
    assert _dinner_lines([h.ref for _line, h in heard]) == set(standing)
