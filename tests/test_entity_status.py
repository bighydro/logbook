"""`logbook status KIND ENTITY DISPOSITION` and `status list KIND` (RFC 0037 §9; decisions 5, 6, 9, 10,
11): one `status/v1` line for an org, an idea, a place or an asset, tier 2, under the writer lock with
the head read again; the reason as a `note/v1` beside it; a place let go or an asset sold closes its
registry entry with `until`, never deleted; a person and a goal take no status; the 365-day mute and
the stale rule are a reader's. On the synthetic record of `entities_record`."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from entities_record import YARD, record

from logbook import cli
from logbook.contrib import entities, entity_review, entity_status
from logbook.core import assets, day_start, places
from logbook.core.store import HeadMoved, Logbook

ZONE = ZoneInfo("Europe/Oslo")
TODAY = datetime.now(ZONE).date().isoformat()  # the writer's today is the clock's, in the record's zone
MUTED_TO = (date.fromisoformat(TODAY) + timedelta(days=364)).isoformat()  # the 365th day, today counted
A_YEAR_ON = (date.fromisoformat(TODAY) + timedelta(days=365)).isoformat()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = record(tmp_path, monkeypatch)
    places.add(lb.root, places.Place("Hytta", 59.9, 10.75, 120, "other", ("family",)))
    places.add(lb.root, places.Place("Båtplassen", 59.91, 10.73, 80, "asset-berth"))
    idea = entities.entity_payload(
        "idea", entity_review.uuid7(), "the fjord kiosk", refs=[("title", "fjord kiosk")]
    )
    entity_review.write_entity(lb, idea)
    return lb


def _status(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["status", *args])
    return capsys.readouterr().out


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main(["status", *args])
    assert e.value.code == 2, args
    return capsys.readouterr().err


def _after(lb: Logbook, seq: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > seq]


def test_an_org_status_is_one_tier_two_line_and_its_reason_a_note_beside_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq, head = int(lb.meta["seq"]), str(lb.meta["head"])
    out = _status(capsys, "org", "Nordmann Verft", "hold", "--reason", "the yard is still compounding")
    assert out.splitlines()[0] == f"Nordmann Verft AS: hold (#{seq + 1})"
    status, note = _after(lb, seq)
    assert (status["kind"], status["source"], status["tier"]) == ("status", "manual", 2)
    payload = status["payload"]
    assert entities.validate_status(payload) == []
    assert payload["entity"] == {"type": "org", "id": YARD["id"], "registry": "logbook"}, (
        "a company read as org"
    )
    assert (payload["status"], payload["label"], payload["proposed_by"]) == (
        "hold",
        "Nordmann Verft AS",
        "owner",
    )
    assert payload["reason"] == "the yard is still compounding" and payload["logbook_head"] == head
    assert not {"amount", "currency"} & set(payload), "no money on the line"
    assert (note["kind"], note["tier"], note["at"]) == ("note", 2, status["at"])
    assert (
        note["payload"]["labels"] == ["status"] and note["payload"]["text"] == "the yard is still compounding"
    )
    assert note["payload"]["extra"]["status"] == status["id"]
    assert Logbook(lb.root).verify()[2] == []


def test_one_status_a_day_and_a_reaffirmation_needs_a_new_reason(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    _status(capsys, "org", YARD["label"], "hold", "--at", "2026-10-01", "--reason", "first")
    [first, _note] = _after(lb, seq)
    assert first["at"] == "2026-10-01T21:59:00Z", "a day before today: its last minute, Oslo time"
    assert "to reaffirm it, say why" in _refused(capsys, "org", YARD["label"], "hold")
    assert "to reaffirm it" in _refused(capsys, "org", YARD["label"], "hold", "--reason", "first")
    seq = int(Logbook(lb.root).meta["seq"])
    _status(capsys, "org", YARD["label"], "hold", "--reason", "still")
    [again, _] = _after(lb, seq)
    assert again["payload"]["supersedes"] == first["id"]
    assert "one status a day" in _refused(capsys, "org", YARD["label"], "hold", "--reason", "third")
    seq = int(Logbook(lb.root).meta["seq"])
    _status(capsys, "org", YARD["label"], "sell")
    [sell] = _after(lb, seq)
    assert sell["payload"]["supersedes"] == again["id"] and "reason" not in sell["payload"], (
        "no reason: no note"
    )


def test_status_refuses_a_person_a_goal_and_what_a_kind_does_not_take(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    for args, words in (
        (("person", "Ola Nordmann", "hold"), "a person has no status"),
        (("goal", "sail more", "kept"), "review/v1"),
        (("org", YARD["label"], "sold"), "not an org's status"),
        (("org", YARD["label"], "passed"), "must say why"),
        (("idea", "kiosk", "killed"), "must say why"),
        (("asset", "solvind", "exited"), "not an asset's status"),
        (("org", "Fjordkiosk", "hold"), "no org is 'Fjordkiosk'"),
        (("org", YARD["label"], "hold", "--at", "2099-01-01"), "after today"),
        (("org", YARD["label"], "hold", "--at", "1 October"), "not a day"),
        (("org", YARD["label"]), "say KIND ENTITY DISPOSITION"),
        (("list", "org", "--reason", "x"), "takes a kind and nothing else"),
        (("list", "person"), "a person has no status"),
    ):
        err = _refused(capsys, *args)
        assert err.startswith("status: ") and words in err, (args, err)
    assert int(Logbook(lb.root).meta["seq"]) == seq, "nothing written"


def test_an_idea_status_names_the_idea_by_a_word_of_its_label(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    _status(capsys, "idea", "kiosk", "exploring", "--reason", "pricing page written")
    status, _note = _after(lb, seq)
    assert status["payload"]["entity"]["type"] == "idea" and status["payload"]["label"] == "the fjord kiosk"
    assert status["tier"] == 2


def test_a_place_let_go_and_an_asset_sold_close_their_entries_with_until(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    before = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    out = _status(
        capsys, "place", "Båtplassen", "let-go", "--reason", "gave the berth up", "--at", "2026-10-02"
    )
    assert "closed in places.json with until 2026-10-02" in out
    after = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    assert after["Båtplassen"] == {**before["Båtplassen"], "until": "2026-10-02"}, "every other key kept"
    assert after["Hytta"] == before["Hytta"] and list(after) == list(before), "never deleted"
    assert [p.name for p in places.read(lb.root)] == ["Hytta", "Båtplassen"], "the readers read it on"
    seq = int(Logbook(lb.root).meta["seq"])
    _status(capsys, "asset", "Solvind", "sold")
    [sold] = _after(lb, seq)
    assert sold["payload"]["entity"] == {"type": "asset", "id": "solvind", "registry": "logbook"}
    registry = json.loads((lb.root / "assets.json").read_text(encoding="utf-8"))["assets"]
    assert registry[0] == {
        "id": "solvind",
        "kind": "yacht",
        "name": "Solvind",
        "mmsi": "970000001",
        "until": TODAY,
    }
    assert registry[1].get("until") is None and [a.id for a in assets.read(lb.root)] == ["solvind", "lerka"]
    listing = entity_status.listing(Logbook(lb.root), "asset", today=TODAY).to_json()
    assert [(e["id"], e["status"], e["until"]) for e in listing["entities"]] == [
        ("solvind", "sold", TODAY),
        ("lerka", None, None),
    ]
    Logbook(lb.root).retract(int(sold["seq"]), "not sold after all")
    listing = entity_status.listing(Logbook(lb.root), "asset", today=TODAY).to_json()
    assert listing["entities"][0]["until"] is None, "the standing line closes, never the file's copy"


def test_the_writer_holds_the_lock_and_reads_the_head_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = lb.root / "state" / "writer.lock"
    real = entity_status._read
    held = []

    def another_writer(lb2: Logbook) -> Any:
        held.append(lock.exists())
        found = real(lb2)
        lb2.append(at="2026-10-13T08:00:00Z", source="manual", kind="note", tier=2,
                   payload={"schema": "note/v1", "text": "written under the reading"})  # fmt: skip
        return found

    monkeypatch.setattr(entity_status, "_read", another_writer)
    seq = int(lb.meta["seq"])
    with pytest.raises(HeadMoved, match="nothing was written"):
        entity_status.write(lb, "org", YARD["label"], "hold", today=TODAY)
    assert held == [True], "read under the writer lock"
    assert [line["kind"] for line in _after(lb, seq)] == ["note"], "the status line never written"


def test_status_list_says_the_current_status_the_stale_and_the_muted(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    entity_status.write(lb, "org", YARD["label"], "hold", "early", at="2023-01-02", today=TODAY)
    found = entity_status.listing(Logbook(lb.root), "org", today=TODAY)
    [yard] = found.rows
    assert (yard.current is not None and yard.current.status, yard.since, yard.stale) == (
        "hold",
        "2023-01-02",
        True,
    )
    out = _status(capsys, "list", "org")
    assert "hold since 2023-01-02 (owner)" in out and "stale" in out and "reason: early" in out
    # the dream proposed let-go; the owner held, and said why: let-go is muted for 365 days
    entity_status.write(
        lb, "org", YARD["label"], "hold", "orders through 2027", at=TODAY, today=TODAY,
        proposal={"status": "let-go", "score": 30, "because": ["no touch for 365 days"]},
    )  # fmt: skip
    rows = entity_status.listing(Logbook(lb.root), "org", today=TODAY).to_json()["entities"]
    assert rows[0]["muted"] == [{"status": "let-go", "until": MUTED_TO}] and rows[0]["stale"] is False
    assert rows[0]["proposed_by"] == "dream"
    later = entity_status.listing(Logbook(lb.root), "org", today=A_YEAR_ON).to_json()["entities"]
    assert later[0]["muted"] == [], "after 365 days the dream may propose it again"
    with Logbook(lb.root).index() as idx:
        history = entities.statuses([*idx.retractions(), *idx.by_kind("status")])[("org", YARD["id"])]
    local = entity_status._local(day_start.of(Logbook(lb.root).meta))  # a line's day, Oslo time
    assert entities.muted(history, "let-go", date.fromisoformat(MUTED_TO), local) is not None
    assert entities.muted(history, "exited", date.fromisoformat(TODAY), local) is None, "only let-go"
    assert json.loads(_status(capsys, "list", "org", "--json"))["entities"][0]["status"] == "hold"


def test_a_retracted_status_counts_for_nothing_and_the_one_before_stands(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _status(capsys, "idea", "kiosk", "spark", "--at", "2026-09-20")
    seq = int(Logbook(lb.root).meta["seq"])
    _status(capsys, "idea", "kiosk", "killed", "--reason", "a ferry kiosk exists already")
    status, _note = _after(lb, seq)
    Logbook(lb.root).retract(int(status["seq"]), "not killed after all")
    [row] = entity_status.listing(Logbook(lb.root), "idea", today=TODAY).rows
    assert row.current is not None and (row.current.status, row.since) == ("spark", "2026-09-20")
