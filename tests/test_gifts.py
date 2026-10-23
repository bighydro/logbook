"""The gift act (RFC 0043 §11, §12): `logbook add gift DAY NAME "what" [--received]` writes one note/v1
labelled `gift` through the notes path, the person under `extra.recipient` (given) or `extra.giver`
(received), the thing in the owner's words, tier 2; `gifts` reads them back both ways. Synthetic:
the orgs record's people, who do not exist."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from orgs_record import OLA, PER, evidence_record

from logbook import cli
from logbook.core import gifts
from logbook.core.store import Logbook

DAY, LATER = "2026-10-10", "2026-10-11"
BOOK = "a book on knots, the one with the bowline on the cover"
JAM = "  cloudberry jam  "  # the owner's words, spaces and all


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        return evidence_record(tmp_path_factory.mktemp("gifts")).root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    return Logbook(root)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    try:
        cli.main(list(argv))
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


def _after(lb: Logbook, seq: int) -> list[dict]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > seq]


def test_a_gift_given_is_one_note_labelled_gift_naming_the_recipient(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    code, out, err = _run(capsys, "add", "gift", DAY, "Per Hansen", BOOK)
    assert code == 0, err
    [line] = _after(lb, seq)
    assert (line["kind"], line["source"], line["tier"]) == ("note", "manual", 2)
    payload = line["payload"]
    assert payload == {
        "schema": "note/v1",
        "text": BOOK,
        "labels": ["gift"],
        "extra": {"recipient": PER["id"]},
    }
    assert line["at"] == "2026-10-10T21:59:00Z", "a past day's note: its last minute, as every note"
    assert "Per Hansen" in out and BOOK in out and f"#{line['seq']}" in out


def test_a_gift_received_names_the_giver_under_giver_and_keeps_the_words_as_given(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    code, _out, err = _run(
        capsys, "add", "gift", LATER, "ola.nordmann@nordmann-verft.example.org", JAM, "--received"
    )
    assert code == 0, err
    [line] = _after(lb, seq)
    assert line["payload"]["extra"] == {"giver": OLA["id"]}
    assert line["payload"]["text"] == JAM, "the owner's words, never filtered"


def test_the_command_and_the_function_write_the_same_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    written = gifts.give(lb, DAY, "Per", BOOK)
    code, _out, err = _run(capsys, "add", "gift", DAY, "Per", BOOK, "--received")
    assert code == 0, err
    [cli_line] = _after(lb, int(written.line["seq"]))
    assert written.line["payload"]["labels"] == cli_line["payload"]["labels"] == ["gift"]
    assert written.line["payload"]["extra"] == {"recipient": PER["id"]}
    assert cli_line["payload"]["extra"] == {"giver": PER["id"]}
    assert written.line["at"] == cli_line["at"]


def test_the_reader_lists_gifts_both_ways_for_a_person_and_a_window(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    gifts.give(lb, DAY, "Per Hansen", BOOK)
    gifts.give(lb, LATER, "Ola Nordmann", JAM, received=True)
    gifts.give(lb, LATER, "Per Hansen", "a jar of honey", received=True)
    every = gifts.gifts(lb)
    assert [(g.day, g.direction, g.name, g.what) for g in every] == [
        (DAY, "given", "Per Hansen", BOOK),
        (LATER, "received", "Ola Nordmann", JAM),
        (LATER, "received", "Per Hansen", "a jar of honey"),
    ]
    per = gifts.gifts(lb, person="Per")
    assert [(g.direction, g.person) for g in per] == [("given", PER["id"]), ("received", PER["id"])]
    assert gifts.counts(per) == "1 given, 1 received"
    assert [g.day for g in gifts.gifts(lb, window=(LATER, LATER))] == [LATER, LATER]
    code, out, err = _run(capsys, "people", "gifts", "Per Hansen")
    assert code == 0, err
    assert out.splitlines()[:2] == ["gifts with Per Hansen", "1 given, 1 received"], "no number beside a name"
    assert BOOK in out and "a jar of honey" in out and JAM not in out
    code, out, err = _run(capsys, "people", "gifts", "--json")
    assert code == 0, err
    data = json.loads(out)
    assert (data["given"], data["received"], len(data["gifts"])) == (1, 2, 3)
    assert data["gifts"][0] == {
        "day": DAY,
        "direction": "given",
        "person": PER["id"],
        "name": "Per Hansen",
        "what": BOOK,
        "line": every[0].line["id"],
    }


def test_a_retracted_gift_is_not_listed(lb: Logbook) -> None:
    written = gifts.give(lb, DAY, "Per Hansen", BOOK)
    lb.retract(int(written.line["seq"]), "a slip")
    assert gifts.gifts(lb) == []


@pytest.mark.parametrize(
    ("name", "said"),
    [
        ("Nobody Atall", "'Nobody Atall' is nobody the record's resolution lines name"),
        ("Nordmann", "'Nordmann' names several people"),
        ("Ines Nordmann", "'Ines Nordmann' is you"),
    ],
)
def test_a_name_that_is_nobody_or_several_or_the_owner_is_refused_in_one_sentence_and_nothing_is_written(
    lb: Logbook, capsys: pytest.CaptureFixture[str], name: str, said: str
) -> None:
    seq = int(lb.meta["seq"])
    code, out, err = _run(capsys, "add", "gift", DAY, name, BOOK)
    assert code == 2 and out == ""
    assert said in err and "nothing was written" in err
    assert len(err.strip().splitlines()) == 1 and err.strip().count(". ") == 0, "one sentence"
    assert _after(lb, seq) == []
    with pytest.raises(gifts.GiftError):
        gifts.gifts(lb, person=name)


def test_a_day_still_to_come_and_an_empty_gift_are_refused(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    code, _out, err = _run(capsys, "add", "gift", "2099-01-01", "Per Hansen", BOOK)
    assert code == 2 and "has not begun" in err
    code, _out, err = _run(capsys, "add", "gift", DAY, "Per Hansen", "   ")
    assert code == 2 and "what the gift was" in err
    assert _after(lb, seq) == []


def test_the_same_gift_said_twice_on_a_day_is_written_once(lb: Logbook) -> None:
    first = gifts.give(lb, DAY, "Per Hansen", BOOK)
    again = gifts.give(lb, DAY, "Per", BOOK)
    assert first.written and not again.written
    assert again.line["id"] == first.line["id"]
    assert len(gifts.gifts(lb)) == 1


def test_a_record_with_no_gifts_says_so(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, "people", "gifts")
    assert code == 0, err
    assert out.strip() == "no gifts in the record; `logbook add gift DAY NAME WHAT` writes one"
    code, out, _err = _run(capsys, "people", "gifts", "Per Hansen", "--json")
    assert json.loads(out) == {
        "person": PER["id"],
        "name": "Per Hansen",
        "given": 0,
        "received": 0,
        "gifts": [],
    }


def test_a_name_is_compared_with_its_whitespace_normalised(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """`  per   HANSEN ` is Per Hansen: runs of whitespace one space, none at either end, case aside."""
    seq = int(lb.meta["seq"])
    code, out, err = _run(capsys, "add", "gift", DAY, "  per \t  HANSEN ", BOOK)
    assert code == 0, err
    [line] = _after(lb, seq)
    assert line["payload"]["extra"] == {"recipient": PER["id"]}
    assert "given to Per Hansen" in out
    assert [g.person for g in gifts.gifts(lb, person=" Per  Hansen\n")] == [PER["id"]]
    code, out, err = _run(capsys, "people", "gifts", "  Per   Hansen  ")
    assert code == 0, err
    assert out.splitlines()[0] == "gifts with Per Hansen"


def test_the_same_words_with_other_whitespace_are_the_same_gift(lb: Logbook) -> None:
    first = gifts.give(lb, DAY, "Per Hansen", "a book  on knots")
    again = gifts.give(lb, DAY, "Per Hansen", "  a book on\tknots ")
    assert first.written and not again.written
    assert first.line["payload"]["text"] == "a book  on knots", "the words written as given"


def test_a_malformed_gift_is_refused_and_received_goes_with_a_gift_only(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    code, _out, err = _run(capsys, "add", "gift", DAY, "Per Hansen")
    assert code == 2 and "add gift DAY NAME" in err
    code, _out, err = _run(capsys, "add", "a jar of honey from Per", "--received")
    assert code == 2 and "--received goes with" in err
    assert _after(lb, seq) == []


@pytest.mark.parametrize("flag", ["--since", "--until"])
def test_people_gifts_refuses_the_mail_window_as_people_refuses_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    """`--since` and `--until` are `people mail`'s window (and `--until` who was there's too): `people
    gifts` refuses them before it reads anything, in the words every other `people` form gets from
    main, here `people drift`'s, and writes nothing."""
    gifts.give(lb, DAY, "Per Hansen", BOOK)
    seq = int(lb.meta["seq"])
    code, out, said = _run(capsys, "people", "drift", flag, DAY)
    assert (code, out) == (2, "") and said.strip()
    for argv in (("people", "gifts", flag, DAY), ("people", "gifts", "Per Hansen", flag, DAY)):
        code, out, err = _run(capsys, *argv)
        assert (code, out) == (2, ""), argv
        assert err == said, argv
    assert _after(lb, seq) == []
    if flag == "--since":
        assert said.strip() == "people: --since and --until go with `people mail`"
