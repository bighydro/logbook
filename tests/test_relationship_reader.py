"""The relationship reader, slice 0 (EXPERIMENTAL, `logbook/contrib/relationship/`): the acceptance
test, one test per item of the outside reading of the design, with a stubbed model and the folder
store standing in for a Honcho-like one. Nobody here exists: Ines Nordmann of Oslo is the owner, Ola
and Kari Nordmann are resolved from their addresses, Gunnar Berg is not resolved at all. Phone numbers
are in the UK reserved range 07700 900xxx, addresses at example.org.

The authorized input set for one canonical person (RFC 0036 amendment 1, the person unit) is the lines
on which they are a counterpart, an attendee or a speaker, in the window, not retracted, at or under
the `relationship` entry's ceiling; never a line that merely mentions them."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from circle import OWNER, mail, message
from persona import attendee, event, note, resolution, transcript, utc

from logbook import cli
from logbook.contrib.relationship import ask, reader
from logbook.core import policy, signing
from logbook.core.store import Logbook, uuid7

TZ = "Europe/Oslo"
OLA = {"id": "019cadd3-6bc0-7dcd-9133-000000000002", "name": "Ola Nordmann", "email": "ola@example.org"}
OLA["phone"] = "+447700900002"
KARI = {"id": "019cadd3-6bc0-7dcd-9133-000000000001", "name": "Kari Nordmann"}
KARI |= {"email": "kari.nordmann@example.org", "phone": "+447700900001"}
GUNNAR = {"name": "Gunnar Berg", "email": "gunnar.berg@example.org"}  # no resolution line names him
WINDOW = ("2026-06-01", "2026-06-30")
TODAY = date(2026, 7, 1)
SIGNED = tuple(f"2026-06-{d:02d}" for d in range(1, 30))  # the 30th, a day with no line, is not
DIRECT = (f"{OLA['phone'][1:]}@s.whatsapp.net", "direct", "Ola")
CREW = ("120363000000000002@g.us", "group", "Crew")
HIS = ("mine", "his", "thanks", "his_mail", "call", "meeting", "recorded")  # his set at tier 2
EN_DASH = "\u2013"
NOT_HIS = f"not one of Ola Nordmann's lines in 2026-06-01 {EN_DASH} 2026-06-30"


def _call(at: str, person: Mapping[str, str], seconds: int) -> dict[str, Any]:
    return {
        "at": at,
        "source": "ios-calls",
        "kind": "call",
        "tier": 1,
        "payload": {
            "schema": "call/v1",
            "raw_id": f"c-{at}",
            "direction": "incoming",
            "answered": seconds > 0,
            "duration_s": seconds,
            "counterparty": {"kind": "phone", "value": person["phone"]},
            "service": "cellular",
        },
    }


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, dict[str, str]]:
    """A June of the owner's with Ola: the lines of his set and the lines that only mention him,
    named so a test can find them; the `relationship` entry at tier 2 until the end of the year."""
    monkeypatch.setattr(policy, "today", lambda: TODAY)
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    owner_id = str(lb.meta["owner_id"])
    drafts: list[dict[str, Any]] = [
        resolution(("email", OWNER["email"]), owner_id, OWNER["name"]),
        resolution(("phone", OWNER["phone"]), owner_id, OWNER["name"]),
    ]
    for p in (OLA, KARI):
        drafts.append(resolution(("email", p["email"]), p["id"], p["name"]))
        drafts.append(resolution(("phone", p["phone"]), p["id"], p["name"]))
    for line in drafts:  # the names at tier 1, so a ceiling of 1 still knows whom a line is with
        line["tier"] = 1
    lb.append_many(drafts)
    named = {
        # his set: the direct chat both ways, his mail, an answered call, a meeting, a recorded call
        "mine": message(utc("2026-06-09", "08:15"), DIRECT, "Boat on Saturday? Ola, bring the charts."),
        "his": message(utc("2026-06-09", "08:20"), DIRECT, "Yes! Saturday.", OLA),
        "thanks": message(utc("2026-06-14", "18:00"), DIRECT, "Thanks for a great weekend.", OLA),
        "his_mail": mail(utc("2026-06-10", "07:00"), OLA, OWNER, "Charts for Saturday"),
        "call": _call(utc("2026-06-16", "20:00"), OLA, 25 * 60),
        "meeting": event(
            utc("2026-06-12", "17:00"),
            utc("2026-06-12", "18:00"),
            "Sail planning",
            [attendee(OLA["email"], OLA["name"]), attendee(KARI["email"], KARI["name"])],
        ),
        "recorded": transcript(
            utc("2026-06-17", "10:00"),
            utc("2026-06-17", "10:40"),
            "Crew call",
            [
                {"name": OLA["name"], "email": OLA["email"]},
                {"name": KARI["name"], "email": KARI["email"]},
                {"name": OWNER["name"], "email": OWNER["email"]},
                {"name": GUNNAR["name"], "email": GUNNAR["email"]},
            ],
        ),
        # his, but above the ceiling: tier 3
        "private": message(utc("2026-06-15", "21:00"), DIRECT, "The test results came back fine.", OLA),
        # mentions, never speech: someone else's word about him
        "group": message(utc("2026-06-11", "09:10"), CREW, "Ola says hi from the boat.", KARI),
        "note": note(utc("2026-06-12", "22:00"), "Dinner with Ola at the marina."),
        "about_him": mail(utc("2026-06-10", "09:00"), KARI, OWNER, "Ola's birthday present"),
        "declined": event(
            utc("2026-06-20", "19:00"),
            utc("2026-06-20", "22:00"),
            "Regatta dinner",
            [attendee(OLA["email"], OLA["name"], response="declined")],
        ),
        # his, outside the window
        "may": message(utc("2026-05-28", "12:00"), DIRECT, "See you in June.", OLA),
    }
    named["private"]["tier"] = 3
    for draft in named.values():
        draft["id"] = uuid7()
    assert lb.append_many(list(named.values())) == len(named)
    ids = {name: str(draft["id"]) for name, draft in named.items()}
    for day in SIGNED:  # the owner signed June, so its lines may cross (the signed-day gate, RFC 0034)
        signing.sign(lb, day, at=utc(day, "23:30"))
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "owner.json").write_text(
        json.dumps({"names": [OWNER["name"]], "emails": [OWNER["email"]], "phones": [OWNER["phone"]]}),
        encoding="utf-8",
    )
    _entry(lb, 2, "2026-12-31")
    ids["owner"] = owner_id
    return lb, ids


def _entry(lb: Logbook, max_tier: int, until: str) -> None:
    path = policy.policy_path(lb.root)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["relationship"] = {"max_tier": max_tier, "until": until}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class Stub:
    """The model: answers with the segments it was given, and keeps every question it was asked."""

    def __init__(self, segments: Sequence[Mapping[str, Any]]):
        self.segments = list(segments)
        self.asked: list[ask.Question] = []

    def __call__(self, question: ask.Question) -> list[dict[str, Any]]:
        self.asked.append(question)
        return [dict(s) for s in self.segments]

    @property
    def served(self) -> set[str]:
        return {line["id"] for line in self.asked[-1].lines}


def _store(lb: Logbook) -> Path:
    return lb.root.joinpath("state", "relationship", OLA["id"])


def _files(root: Path, leave_out: Path | None = None) -> dict[tuple[str, ...], bytes]:
    """Every file under `root` by its parts, with its bytes; `leave_out` and what is under it not."""
    return {
        p.relative_to(root).parts: p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and (leave_out is None or leave_out not in (p, *p.parents))
    }


def _messages(lb: Logbook) -> list[dict[str, Any]]:
    text = _store(lb).joinpath("messages.jsonl").read_text(encoding="utf-8")
    return [json.loads(row) for row in text.splitlines() if row.strip()]


def _id_map(lb: Logbook) -> dict[str, str]:
    data: dict[str, str] = json.loads(_store(lb).joinpath("lines.json").read_text(encoding="utf-8"))
    return data


def _peers(lb: Logbook) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(_store(lb).joinpath("peers.json").read_text(encoding="utf-8"))
    return data


def _by_line(lb: Logbook) -> dict[str, dict[str, Any]]:
    lines = _id_map(lb)
    return {lines[m["id"]]: m for m in _messages(lb)}


def _ask(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, stub: Stub, *args: str
) -> dict[str, Any]:
    monkeypatch.setattr(ask, "MODEL", stub)
    cli.main(["people", "ask", "Ola Nordmann", "What did we plan for the boat?", *args, "--json"])
    data: dict[str, Any] = json.loads(capsys.readouterr().out)
    return data


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main(["people", *args])
    assert e.value.code == 2
    return capsys.readouterr().err


def _ingest(lb: Logbook) -> None:
    reader.ingest(lb, "Ola Nordmann", *WINDOW)


# -- the collaborator's list ------------------------------------------------------------------------------


def test_a_shared_exchange_is_attributed_to_its_speakers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    by_line = _by_line(lb)
    assert set(by_line) == {ids[n] for n in HIS}
    assert by_line[ids["his"]]["speakers"] == [OLA["id"]], "his words are his"
    assert by_line[ids["thanks"]]["speakers"] == [OLA["id"]]
    assert by_line[ids["mine"]]["speakers"] == [ids["owner"]], "the owner's half of the chat is the owner's"
    assert by_line[ids["his_mail"]]["speakers"] == [OLA["id"]], "a mail is its sender's"
    assert by_line[ids["call"]]["speakers"] == [OLA["id"], ids["owner"]], "an answered call: both spoke"
    assert by_line[ids["recorded"]]["speakers"] == [OLA["id"], KARI["id"], ids["owner"]]
    assert by_line[ids["meeting"]]["speakers"] == [], "an attendee is there, which is not speech"
    roles = {line: m["role"] for line, m in by_line.items()}
    assert roles[ids["his"]] == "counterpart" and roles[ids["meeting"]] == "attendee"
    assert roles[ids["recorded"]] == "speaker"
    assert all(m["at"] and m["kind"] and m["text"] for m in by_line.values()), "ids, timestamps, the words"
    his = by_line[ids["his"]]
    assert his["text"] == "Yes! Saturday." and his["at"] == utc("2026-06-09", "08:20")


def test_a_mention_is_not_speech(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    by_line = _by_line(lb)
    for mention in ("group", "note", "about_him", "declined"):
        assert ids[mention] not in by_line, f"{mention}: a line that names Ola is not one of his"
    stored = _store(lb).joinpath("messages.jsonl").read_text(encoding="utf-8")
    assert "says hi" not in stored and "Dinner with" not in stored and "birthday" not in stored
    assert by_line[ids["mine"]]["speakers"] == [ids["owner"]], "naming Ola in my message is not Ola speaking"
    assert ids["may"] not in by_line, "outside the window"


def test_an_unresolved_identity_gets_no_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    peers = _peers(lb)
    assert [p["id"] for p in peers] == [OLA["id"], KARI["id"], ids["owner"]], "one peer per canonical person"
    assert [p["label"] for p in peers] == [OLA["name"], KARI["name"], "owner"]
    assert GUNNAR["name"] not in json.dumps(peers) and GUNNAR["email"] not in json.dumps(peers)
    recorded = _by_line(lb)[ids["recorded"]]
    assert recorded["unresolved"] == 1 and GUNNAR["email"] not in json.dumps(recorded)
    with pytest.raises(reader.RelationshipError, match="nobody the record's resolution lines name"):
        reader.ingest(lb, GUNNAR["name"], *WINDOW)
    assert "nobody" in _refused(capsys, "ingest", GUNNAR["name"], "--window", *WINDOW)
    assert sorted(p.name for p in _store(lb).parent.iterdir()) == [OLA["id"]], "no store for him either"


def test_a_line_above_the_ceiling_never_reaches_the_store_or_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    assert ids["private"] not in _by_line(lb) and "test results" not in json.dumps(_messages(lb))
    manifest = json.loads(_store(lb).joinpath("manifest.json").read_text(encoding="utf-8"))
    assert manifest["read_count"] == 7 and manifest["held_back"] == 1
    # the store is disposable and may be wrong: plant the line in it, as a stale or edited store
    # would hold it, and the serving side still leaves it out
    planted = {"id": "f" * 16, "speakers": [OLA["id"]], "role": "counterpart", "kind": "message"}
    planted |= {"at": utc("2026-06-15", "21:00"), "source": "whatsapp", "tier": 3}
    planted["text"] = "The test results came back fine."
    with _store(lb).joinpath("messages.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(planted) + "\n")
    lines = _id_map(lb) | {planted["id"]: ids["private"]}
    _store(lb).joinpath("lines.json").write_text(json.dumps(lines), encoding="utf-8")
    stub = Stub([{"text": "Ola's results came back fine.", "evidence": [ids["private"]]}])
    data = _ask(capsys, monkeypatch, stub)
    assert ids["private"] not in stub.served
    assert "test results" not in json.dumps([q.lines for q in stub.asked])
    assert data["withheld"] == 1
    [segment] = data["answer"]
    assert segment["supported"] is False
    assert segment["evidence"] == [{"id": ids["private"], "line": None, "why": NOT_HIS}]


def test_a_citation_outside_the_authorized_set_is_marked_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    invented = "019cadd3-0000-7000-8000-00000000dead"
    stub = Stub(
        [
            {"text": "Ola said yes to Saturday.", "evidence": [ids["his"]]},
            {"text": "Ola has dinner at the marina.", "evidence": [ids["note"]]},
            {"text": "Ola sails in a regatta.", "evidence": [invented]},
            {"text": "Ola likes the fjord.", "evidence": []},
        ]
    )
    data = _ask(capsys, monkeypatch, stub)
    assert stub.served == {ids[n] for n in HIS}
    asked = stub.asked[0]
    assert asked.person == OLA["name"] and asked.question == "What did we plan for the boat?"
    assert asked.window == WINDOW
    his = next(line for line in asked.lines if line["id"] == ids["his"])
    assert his == {
        "id": ids["his"],
        "at": utc("2026-06-09", "08:20"),
        "kind": "message",
        "speakers": [OLA["name"]],
        "text": "Yes! Saturday.",
    }
    said, noted, invented_one, uncited = data["answer"]
    assert said["supported"] is True
    [cited] = said["evidence"]
    assert cited["id"] == ids["his"] and cited["why"] is None
    assert cited["line"] == {
        "at": utc("2026-06-09", "08:20"),
        "kind": "message",
        "source": "whatsapp",
        "speakers": [OLA["name"]],
    }
    assert noted["supported"] is False and noted["evidence"][0]["line"] is None, "a real line, not his"
    assert invented_one["supported"] is False and invented_one["evidence"][0]["id"] == invented
    assert uncited["supported"] is False and uncited["why"] == "cites nothing"
    capsys.readouterr()
    monkeypatch.setattr(ask, "MODEL", stub)
    cli.main(["people", "ask", "Ola Nordmann", "What did we plan for the boat?"])
    text = capsys.readouterr().out
    assert "Ola said yes to Saturday." in text and ids["his"] in text and "whatsapp" in text
    rows = text.splitlines()
    heading = next(i for i, row in enumerate(rows) if row.startswith("unsupported:"))
    assert rows.index("  Ola said yes to Saturday.") < heading, "the supported claims first"
    unsupported = [row for row in rows[heading + 1 :] if "unsupported" in row]
    assert len(unsupported) == 3 and any(invented in row for row in unsupported)
    assert [row for row in rows[heading + 1 :] if row.startswith("  ~ ")] == [
        "  ~ Ola has dinner at the marina.",
        "  ~ Ola sails in a regatta.",
        "  ~ Ola likes the fjord.",
    ], "every claim that rests on no line of his sits under `unsupported`"
    assert any(ids["note"] in row for row in unsupported)
    assert any("cites nothing" in row for row in unsupported)


def test_the_canonical_record_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    head, before = lb.meta["head"], _files(lb.root)
    _ingest(lb)
    assert lb.meta["head"] == head and _files(lb.root, _store(lb).parent) == before, "only the store"
    store = _files(_store(lb))
    with_store = _files(lb.root)
    monkeypatch.setattr(ask, "MODEL", None)  # the endpoint, which no variable names here
    assert "LOGBOOK_DREAM_ENDPOINT is not set" in _refused(capsys, "ask", "Ola Nordmann", "What did we plan?")
    _ask(capsys, monkeypatch, Stub([{"text": "Ola said yes.", "evidence": [ids["his"]]}]))
    assert lb.meta["head"] == head and _files(lb.root) == with_store, "asking writes nothing"
    assert _files(_store(lb)) == store
    source = "\n".join(p.read_text(encoding="utf-8") for p in Path(reader.__file__).parent.glob("*.py"))
    for writer in ("lb.append", "append_many", ".retract(", "set_meta", ".writer(", "sign_day", "note_day"):
        assert writer not in source, f"the relationship reader never writes the record: {writer}"


def test_ingestion_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb, _ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    first = _files(_store(lb))
    _ingest(lb)
    _ingest(lb)
    assert _files(_store(lb)) == first, "the same input, the same store, byte for byte"
    assert sorted(first) == [("lines.json",), ("manifest.json",), ("messages.jsonl",), ("peers.json",)]


def test_a_retracted_line_drops_from_the_store_on_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    assert ids["thanks"] in _by_line(lb)
    stub = Stub([{"text": "Ola thanked us for the weekend.", "evidence": [ids["thanks"]]}])
    assert _ask(capsys, monkeypatch, stub)["answer"][0]["supported"] is True
    thanks = next(line for line in lb.lines() if str(line["id"]) == ids["thanks"])
    retraction = lb.retract(int(thanks["seq"]), "not his words", at=utc("2026-06-20", "09:00"))
    assert retraction["payload"]["supersedes"] == ids["thanks"]
    monkeypatch.setattr(ask, "MODEL", stub)
    assert "moved" in _refused(capsys, "ask", "Ola Nordmann", "Who thanked us?"), "the head moved: invalid"
    assert len(stub.asked) == 1, "nothing served from an invalid store"
    _ingest(lb)
    assert ids["thanks"] not in _by_line(lb) and ids["thanks"] not in _id_map(lb).values()
    data = _ask(capsys, monkeypatch, stub)
    assert ids["thanks"] not in stub.served and data["answer"][0]["supported"] is False


def test_lowering_the_ceiling_stops_serving_what_was_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    stub = Stub([{"text": "Ola said yes to Saturday.", "evidence": [ids["his"]]}])
    assert _ask(capsys, monkeypatch, stub)["answer"][0]["supported"] is True and ids["his"] in stub.served
    _entry(lb, 1, "2026-12-31")
    assert "changed" in _refused(capsys, "ask", "Ola Nordmann", "What did we plan?"), "the head never moved"
    assert len(stub.asked) == 1
    _ingest(lb)
    data = _ask(capsys, monkeypatch, stub)
    assert stub.served == {ids["call"], ids["meeting"]}, "only what tier 1 lets cross"
    assert data["answer"][0]["supported"] is False and ids["his"] not in _by_line(lb)
    _entry(lb, 1, "2027-01-31")
    assert "changed" in _refused(capsys, "ask", "Ola Nordmann", "What did we plan?"), "a new until too"


def test_an_expired_entry_makes_people_ask_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    _ingest(lb)
    stub = Stub([{"text": "Ola said yes.", "evidence": [ids["his"]]}])
    monkeypatch.setattr(ask, "MODEL", stub)
    monkeypatch.setattr(policy, "today", lambda: date(2027, 1, 1))
    err = _refused(capsys, "ask", "Ola Nordmann", "What did we plan?")
    assert "expired on 2026-12-31" in err and not stub.asked
    with pytest.raises(reader.RelationshipError, match="expired"):
        _ingest(lb)
    path = policy.policy_path(lb.root)
    path.write_text(json.dumps({"relationship": {"max_tier": 2}}), encoding="utf-8")
    assert "until" in _refused(capsys, "ask", "Ola Nordmann", "What did we plan?"), "a lend has a last day"
    path.write_text(json.dumps({}), encoding="utf-8")
    assert "names no 'relationship' entry" in _refused(capsys, "ask", "Ola Nordmann", "What did we plan?")


def test_wipe_and_rebuild_recovers_the_same_input_set_and_id_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = _record(tmp_path, monkeypatch)
    cli.main(["people", "ingest", "Ola Nordmann", "--window", *WINDOW])
    assert "7 lines" in capsys.readouterr().out
    lines, peers = _id_map(lb), _peers(lb)
    shutil.rmtree(_store(lb))
    stub = Stub([{"text": "Ola said yes to Saturday.", "evidence": [ids["his"]]}])
    monkeypatch.setattr(ask, "MODEL", stub)
    assert "no derived store" in _refused(capsys, "ask", "Ola Nordmann", "What did we plan?")
    assert not stub.asked
    _ingest(lb)
    assert _id_map(lb) == lines and _peers(lb) == peers
    assert _ask(capsys, monkeypatch, stub)["answer"][0]["supported"] is True
    assert sorted(lines.values()) == sorted(ids[n] for n in HIS)
