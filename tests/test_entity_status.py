"""`logbook status KIND ENTITY DISPOSITION` and `status list KIND` (RFC 0037 §9; decisions 5, 6, 9, 10,
11): one `status/v1` line for an org, an idea, a place or an asset, at the kind's tier (3 for an org,
RFC 0037 §8; 2 for the rest, never citing a tier-3 line), under the writer lock with the head read
again; the reason on the line, and for an idea, a place or an asset also as a `note/v1` at tier 2
(RFC 0010's MUST), written first and named by the status line's `note` (RFC 0037 §10.5), a pair
written the other way before still read the same, while an org's reason stays on its tier-3 line and
no note is written; a place let go or an asset sold closes its registry entry with `until`, never
deleted; a person and a goal take no status; the 365-day mute and the stale rule are a reader's. On
the synthetic record of `entities_record`, the clock pinned (`clock`)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from entities_record import YARD, record

from logbook import cli
from logbook.commands import export as export_command
from logbook.contrib import entities, entity_review, entity_status
from logbook.core import assets, day_start, notes, places, store
from logbook.core.store import HeadMoved, Logbook

ZONE = ZoneInfo("Europe/Oslo")
NOW = "2026-10-14T22:30:00Z"  # the clock every test reads (`clock`): 00:30 in Oslo, still the 14th in UTC
# the record's today, 2026-10-15: its day starts at midnight (`entities_record` sets no `day_start`)
TODAY = datetime.fromisoformat(NOW).astimezone(ZONE).date().isoformat()
MUTED_TO = (date.fromisoformat(TODAY) + timedelta(days=364)).isoformat()  # the 365th day, today counted
A_YEAR_ON = (date.fromisoformat(TODAY) + timedelta(days=365)).isoformat()


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every clock these tests reach reads NOW, whatever the wall clock says: the writer's and the
    list's today (`notes.today_in`, under the record's zone and day start), the moment of a status
    given today (`notes.moment`'s now) and the stamps the store, the review writer and `export` take
    (each module that imported `now_utc` keeps its own name for it). Read from
    the wall clock, a run that straddled midnight in Oslo wrote `until` a day after TODAY and found
    nothing muted."""
    instant = datetime.fromisoformat(NOW)
    for module in (store, notes, entity_review, export_command):
        monkeypatch.setattr(module, "now_utc", lambda: NOW)
    monkeypatch.setattr(notes, "today_in", lambda days: days.today(instant).isoformat())


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


def test_an_org_status_is_one_tier_three_line_with_its_reason_on_it_and_no_note(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq, head = int(lb.meta["seq"]), str(lb.meta["head"])
    out = _status(capsys, "org", "Nordmann Verft", "hold", "--reason", "the yard is still compounding")
    assert out.splitlines()[0] == f"Nordmann Verft AS: hold (#{seq + 1})"
    [status] = _after(lb, seq)
    assert (status["kind"], status["source"], status["tier"]) == ("status", "manual", 3), (
        "an org's status is tier 3 (RFC 0037 §8): its dispositions describe a position in money"
    )
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
    assert "note" not in payload, (
        "no note: a note/v1 is tier 2 (RFC 0010), so an org's reason stays on its tier-3 line"
    )
    assert not {"amount", "currency"} & set(payload), "no money on the line"
    assert not [line for line in _after(lb, seq) if line["kind"] == "note"], "no note/v1 written"
    assert "the yard is still compounding" in out, "the reason shows to the owner, read from the line"
    assert "reason: the yard is still compounding" in _status(capsys, "list", "org")
    [row] = json.loads(_status(capsys, "list", "org", "--json"))["entities"]
    assert (row["line"], row["reason"], row["note"]) == (status["id"], "the yard is still compounding", None)
    assert Logbook(lb.root).verify()[2] == []


def test_one_status_a_day_and_a_reaffirmation_needs_a_new_reason(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    _status(capsys, "org", YARD["label"], "hold", "--at", "2026-10-01", "--reason", "first")
    [first] = _after(lb, seq)
    assert first["at"] == "2026-10-01T21:59:00Z", "a day before today: its last minute, Oslo time"
    assert "to reaffirm it, say why" in _refused(capsys, "org", YARD["label"], "hold")
    assert "to reaffirm it" in _refused(capsys, "org", YARD["label"], "hold", "--reason", "first")
    seq = int(Logbook(lb.root).meta["seq"])
    _status(capsys, "org", YARD["label"], "hold", "--reason", "still")
    [again] = _after(lb, seq)
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
    _note, status = _after(lb, seq)
    assert status["payload"]["entity"]["type"] == "idea" and status["payload"]["label"] == "the fjord kiosk"
    assert status["tier"] == 2


def test_an_idea_status_with_a_reason_is_a_tier_two_line_and_a_tier_two_note(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    out = _status(capsys, "idea", "kiosk", "exploring", "--reason", "pricing page written")
    note, status = _after(lb, seq)
    assert (status["kind"], status["tier"]) == ("status", 2)
    assert status["payload"]["reason"] == "pricing page written"
    assert (note["kind"], note["source"], note["tier"], note["at"]) == ("note", "manual", 2, status["at"])
    assert note["payload"]["schema"] == "note/v1" and note["payload"]["labels"] == ["status"]
    assert note["payload"]["text"] == "pricing page written"
    assert status["payload"]["note"] == note["id"], "the status line names its note (RFC 0037 §10.5)"
    assert note["payload"]["extra"]["entity"]["type"] == "idea"
    assert f"the reason as a note (#{note['seq']})" in out


def test_a_place_status_is_tier_two_and_never_cites_a_tier_three_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    _status(capsys, "place", "Hytta", "let-go", "--reason", "sold the cabin")
    note, status = _after(lb, seq)
    assert (status["kind"], status["tier"], status["payload"]["entity"]["type"]) == ("status", 2, "place")
    assert note["tier"] == 2, "the note at the status line's tier"
    payment = next(line for line in Logbook(lb.root).lines() if line["kind"] == "transaction")
    assert payment["tier"] == 3
    with pytest.raises(entity_status.StatusError, match="never cites a tier-3 line") as e:
        entity_status.write(lb, "asset", "Solvind", "sold", evidence=[str(payment["id"])], today=TODAY)
    assert "about an asset" in str(e.value) and payment["id"] in str(e.value)
    with pytest.raises(entity_status.StatusError, match="about an idea"):
        entity_status.write(lb, "idea", "kiosk", "spark", evidence=[str(payment["id"])], today=TODAY)
    assert int(Logbook(lb.root).meta["seq"]) == seq + 2, "nothing written"
    written = entity_status.write(
        lb, "org", YARD["label"], "hold", evidence=[str(payment["id"])], today=TODAY
    )
    assert written.status["tier"] == 3 and written.status["payload"]["evidence"] == [payment["id"]], (
        "an org's status may cite tier-3 evidence"
    )


def test_an_export_under_a_ceiling_of_two_carries_no_org_status_and_not_its_reason(
    lb: Logbook, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    policy = lb.root / "policy" / "crossing.json"
    policy.write_text(json.dumps({"hermes": {"max_tier": 2}}), encoding="utf-8")
    seq = int(lb.meta["seq"])
    org_reason, idea_reason = "orders through 2027 at the yard", "pricing page written"
    _status(capsys, "org", YARD["label"], "hold", "--reason", org_reason, "--at", "2026-10-01")
    _status(capsys, "idea", "kiosk", "exploring", "--reason", idea_reason, "--at", "2026-10-02")
    org_status, idea_note, idea_status = _after(lb, seq)
    assert [line["kind"] for line in (org_status, idea_note, idea_status)] == ["status", "note", "status"]
    assert [line["tier"] for line in (org_status, idea_note, idea_status)] == [3, 2, 2]
    out = tmp_path / "out"
    cli.main(["export", "crossing", "--to", "hermes", "--since", "2026-09-01T00:00:00Z", "--until",
              "2026-10-05T00:00:00Z", "--tier", "1,2", "--unsigned", "--out", str(out)])  # fmt: skip
    crossed = [json.loads(s) for s in (out / "entries.jsonl").read_text(encoding="utf-8").splitlines() if s]
    ids = {line["id"] for line in crossed}
    assert idea_status["id"] in ids and idea_note["id"] in ids, "an idea's status and its note cross at 2"
    assert org_status["id"] not in ids, "an org's status never under a ceiling of 2"
    assert not any(
        line["kind"] == "status" and line["payload"]["entity"]["type"] == "org" for line in crossed
    )
    assert not any(
        line["kind"] == "note"
        and "status" in line["payload"].get("labels", [])
        and line["payload"].get("extra", {}).get("entity", {}).get("type") == "org"
        for line in crossed
    )
    assert all(line["tier"] <= 2 for line in crossed)
    files = [path.read_bytes() for path in sorted(out.rglob("*")) if path.is_file()]
    assert any(idea_reason.encode("utf-8") in data for data in files), "the idea's reason crossed"
    assert not any(org_reason.encode("utf-8") in data for data in files), (
        "an org's reason is nowhere in what crossed: it is on the tier-3 line only"
    )


def test_no_status_of_any_kind_writes_a_note_above_tier_two(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0010 makes note/v1 tier 2, MUST, and SPEC §4 lets a producer raise only a SHOULD: every
    disposition of every kind, with a reason, writes no note/v1 above 2. An org's reason stays on its
    tier-3 line; an idea's, a place's and an asset's is also a note at 2."""
    seq = int(lb.meta["seq"])
    names = {"org": YARD["label"], "idea": "kiosk", "place": "Hytta", "asset": "Solvind"}
    for kind, dispositions in entities.DISPOSITIONS.items():
        for disposition in dispositions:
            _status(capsys, kind, names[kind], disposition, "--reason", f"why {kind} {disposition}")
    written = _after(lb, seq)
    statuses = [line for line in written if line["kind"] == "status"]
    notes = [line for line in written if line["kind"] == "note"]
    assert len(statuses) == sum(len(d) for d in entities.DISPOSITIONS.values())
    assert all(s["payload"]["reason"] == f"why {s['payload']['entity']['type']} {s['payload']['status']}"
               for s in statuses), "every reason is on its status line"  # fmt: skip
    assert [s["tier"] for s in statuses if s["payload"]["entity"]["type"] == "org"] == [3] * 6
    noted = [n["payload"]["extra"]["entity"]["type"] for n in notes]
    assert noted == ["idea"] * 5 + ["place"] + ["asset"] * 2, "an org's reason is never a note"
    assert all(n["tier"] == 2 for n in notes)
    assert not [n for n in Logbook(lb.root).lines() if n["kind"] == "note" and n["tier"] > 2], (
        "no note/v1 above tier 2 anywhere in the record"
    )


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
    _note, status = _after(lb, seq)
    Logbook(lb.root).retract(int(status["seq"]), "not killed after all")
    [row] = entity_status.listing(Logbook(lb.root), "idea", today=TODAY).rows
    assert row.current is not None and (row.current.status, row.since) == ("spark", "2026-09-20")


# -- the reason as a note: written first, named by the status line (RFC 0037 §10.5) ---------------------


@pytest.mark.parametrize(
    ("kind", "name", "disposition", "entity"),
    [
        ("idea", "kiosk", "exploring", None),
        ("place", "Hytta", "let-go", "Hytta"),
        ("asset", "Solvind", "let-go", "solvind"),
    ],
)
def test_a_reason_is_a_note_written_first_and_the_status_line_names_it(
    lb: Logbook,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    name: str,
    disposition: str,
    entity: str | None,
) -> None:
    seq, reason = int(lb.meta["seq"]), f"why the {kind} is {disposition}"
    out = _status(capsys, kind, name, disposition, "--reason", reason)
    note, status = _after(lb, seq)
    assert (int(note["seq"]), int(status["seq"])) == (seq + 1, seq + 2), "the note first, then the status"
    assert (note["kind"], note["source"], note["tier"], note["at"]) == ("note", "manual", 2, status["at"])
    entity_ref = status["payload"]["entity"]
    assert entity_ref["type"] == kind and (entity is None or entity_ref["id"] == entity)
    assert note["payload"] == {
        "schema": "note/v1",
        "text": reason,
        "labels": ["status"],
        "extra": {"entity": entity_ref},
    }, "the words and the entity, never the disposition, and no back link: the status names the note"
    assert (status["kind"], status["tier"]) == ("status", 2)
    assert (status["payload"]["reason"], status["payload"]["note"]) == (reason, note["id"])
    assert entities.validate_status(status["payload"]) == []
    assert out.splitlines() == [
        f"{status['payload']['label']}: {disposition} (#{status['seq']})",
        f"  the reason as a note (#{note['seq']})",
        *out.splitlines()[2:],
    ]
    [row] = [r for r in json.loads(_status(capsys, "list", kind, "--json"))["entities"] if r["status"]]
    assert (row["line"], row["reason"], row["note"]) == (status["id"], reason, note["id"])
    assert f"reason: {reason}" in _status(capsys, "list", kind)
    assert Logbook(lb.root).verify()[2] == []


def test_a_status_refused_with_a_reason_writes_no_note_either(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything is checked, and the head read again, before the first line, which is now the note."""
    payment = next(line for line in lb.lines() if line["kind"] == "transaction")
    seq = int(lb.meta["seq"])
    with pytest.raises(entity_status.StatusError, match="never cites a tier-3 line"):
        entity_status.write(lb, "idea", "kiosk", "exploring", "pricing", evidence=[str(payment["id"])])
    assert int(Logbook(lb.root).meta["seq"]) == seq, "refused inside the lock: no note, no line"
    _status(capsys, "idea", "kiosk", "exploring", "--reason", "pricing page written")
    seq = int(Logbook(lb.root).meta["seq"])
    assert "one status a day" in _refused(capsys, "idea", "kiosk", "exploring", "--reason", "again")
    real = entity_status._read

    def another_writer(lb2: Logbook) -> Any:
        found = real(lb2)
        lb2.append(at=NOW, source="manual", kind="note", tier=2,
                   payload={"schema": "note/v1", "text": "written under the reading"})  # fmt: skip
        return found

    monkeypatch.setattr(entity_status, "_read", another_writer)
    with pytest.raises(HeadMoved):
        entity_status.write(lb, "idea", "kiosk", "build", "the repo is busy")
    after = _after(lb, seq)
    assert [line["payload"].get("text") for line in after] == ["written under the reading"], (
        "no status note, no status line"
    )


def _old_order(
    lb: Logbook, kind: str, entity_id: str, label: str, status: str, reason: str, at: str
) -> tuple:
    """A pair as the writer wrote it before it kept RFC 0037 §10.5's order: the status line first, its
    reason on it and no `note` field, then the note naming it under `extra.status`, with the label
    and the disposition beside it."""
    line = Logbook(lb.root).append(
        at=at, source="manual", kind="status", tier=2,
        payload=entities.status_payload(kind, entity_id, label, status, reason),
    )  # fmt: skip
    note = Logbook(lb.root).append(
        at=at, source="manual", kind="note", tier=2,
        payload={"schema": "note/v1", "text": reason, "labels": ["status"],
                 "extra": {"status": line["id"], "entity": entities.entity_ref(kind, entity_id),
                           "label": label, "disposition": status}},
    )  # fmt: skip
    return line, note


def test_a_pair_written_the_old_way_reads_as_it_did(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """A status line written before the note came first has no `note`; its note names it under
    `extra.status`. The list reads the same status, day, reason and note from it as from a pair
    written now, and a status written after it supersedes it as before."""
    with lb.index() as idx:
        [idea] = [line for line in idx.by_kind("entity") if line["payload"]["entity"]["type"] == "idea"]
    idea_id = idea["payload"]["entity"]["id"]
    old_status, old_note = _old_order(
        lb, "idea", idea_id, "the fjord kiosk", "exploring", "pricing page written", "2026-10-02T18:00:00Z"
    )
    old_place, old_place_note = _old_order(
        lb, "place", "Hytta", "Hytta", "let-go", "sold the cabin", "2026-10-03T18:00:00Z"
    )
    assert "note" not in old_status["payload"] and entities.validate_status(old_status["payload"]) == []
    [row] = [r for r in entity_status.listing(Logbook(lb.root), "idea", today=TODAY).rows if r.current]
    assert row.current is not None
    assert (row.current.status, row.since, row.current.reason, row.current.line, row.current.note) == (
        "exploring",
        "2026-10-02",
        "pricing page written",
        old_status["id"],
        old_note["id"],
    ), "the old note found by its extra.status"
    [place] = json.loads(_status(capsys, "list", "place", "--json"))["entities"][:1]
    assert (place["status"], place["until"], place["reason"], place["note"]) == (
        "let-go",
        "2026-10-03",
        "sold the cabin",
        old_place_note["id"],
    )
    assert "reason: pricing page written" in _status(capsys, "list", "idea")
    # the same words written now, in the RFC's order, read the same but for the ids
    seq = int(Logbook(lb.root).meta["seq"])
    _status(capsys, "idea", "kiosk", "exploring", "--reason", "pricing page written, again")
    new_note, new_status = _after(lb, seq)
    assert new_status["payload"]["supersedes"] == old_status["id"], "the old line was the standing one"
    with Logbook(lb.root).index() as idx:
        lines = [*idx.retractions(), *idx.by_kind("status"), *idx.by_kind("note")]
    before = [line for line in lines if line["id"] != new_status["id"]]
    for found, pair in ((before, (old_status, old_note)), (lines, (new_status, new_note))):
        [current] = entities.statuses(found)[("idea", idea_id)]
        assert (current.line, current.note) == (pair[0]["id"], pair[1]["id"]), (
            "each status joined to its own note, whichever way the pair was written"
        )
    Logbook(lb.root).retract(int(old_place_note["seq"]), "the note taken back")
    [place] = json.loads(_status(capsys, "list", "place", "--json"))["entities"][:1]
    assert (place["reason"], place["note"]) == ("sold the cabin", None), (
        "a retracted note names nothing; the reason is still on the line"
    )
    assert old_place["id"] == place["line"]


IDEA_ID = "019cadd3-6bc0-7dcd-9133-000000000301"


def test_a_status_line_s_note_is_a_line_id_never_an_org_s_and_never_without_a_reason() -> None:
    idea = entities.status_payload(
        "idea",
        IDEA_ID,
        "the fjord kiosk",
        "exploring",
        "because",
        note="019cadd3-6bc0-7dcd-9133-0000000001d3",
    )
    assert entities.validate_status(idea) == []
    assert any("note" in p for p in entities.validate_status({**idea, "note": 7}))
    org = entities.status_payload(
        "org", YARD["id"], YARD["label"], "hold", "because", note="019cadd3-6bc0-7dcd-9133-0000000001d3"
    )
    assert any("an org's reason stays on its tier-3 line" in p for p in entities.validate_status(org))
    bare = {k: v for k, v in idea.items() if k != "reason"}
    assert any("a status without a reason has none" in p for p in entities.validate_status(bare))


def test_a_retracted_note_is_no_reason_note_and_an_org_is_never_joined_to_one(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whichever way the pair was written, a retracted note counts for nothing; and an org's line is
    never joined to a note, not by a `note` on it nor by a note naming it under `extra.status`."""
    seq = int(lb.meta["seq"])
    _status(capsys, "asset", "Solvind", "let-go", "--reason", "given to the sailing club")
    note, status = _after(lb, seq)
    Logbook(lb.root).retract(int(note["seq"]), "the note taken back")
    [row] = [r for r in json.loads(_status(capsys, "list", "asset", "--json"))["entities"] if r["status"]]
    assert (row["line"], row["reason"], row["note"]) == (status["id"], "given to the sailing club", None)
    # an org's line, written by hand with a `note` (the writer never does), and a stray note naming
    # another org line the old way; an old-order idea pair turns the old road on
    with lb.index() as idx:
        [idea] = [line for line in idx.by_kind("entity") if line["payload"]["entity"]["type"] == "idea"]
    _old_order(lb, "idea", idea["payload"]["entity"]["id"], "the fjord kiosk", "spark", "a sketch",
               "2026-10-02T18:00:00Z")  # fmt: skip
    org = Logbook(lb.root).append(
        at="2026-10-03T18:00:00Z", source="manual", kind="status", tier=3,
        payload={**entities.status_payload("org", YARD["id"], YARD["label"], "hold", "orders"),
                 "note": idea["id"]},
    )  # fmt: skip
    assert any("an org's reason stays" in p for p in entities.validate_status(org["payload"]))
    [row] = json.loads(_status(capsys, "list", "org", "--json"))["entities"]
    assert (row["line"], row["note"]) == (org["id"], None), "an org's `note` is never read"
    stray = Logbook(lb.root).append(
        at="2026-10-04T18:00:00Z", source="manual", kind="status", tier=3,
        payload=entities.status_payload("org", YARD["id"], YARD["label"], "add", "more orders"),
    )  # fmt: skip
    Logbook(lb.root).append(
        at="2026-10-04T18:00:00Z", source="manual", kind="note", tier=2,
        payload={"schema": "note/v1", "text": "more orders", "labels": ["status"],
                 "extra": {"status": stray["id"], "entity": entities.entity_ref("org", YARD["id"])}},
    )  # fmt: skip
    [row] = json.loads(_status(capsys, "list", "org", "--json"))["entities"]
    assert (row["line"], row["note"]) == (stray["id"], None), "an org is never joined to a note"


def test_notes_are_read_only_for_a_standing_line_written_the_old_way_and_only_around_its_day(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record the writer wrote note first reads no note to list or write a status; an old-order line
    makes the reader read the `manual` status notes of its day, a day either side, and nothing more."""
    from logbook.core import index

    asked: list[tuple[Any, ...]] = []
    real = index.Index.of_kind

    def spy(self: index.Index, kind: str, *args: Any, **kwargs: Any) -> Any:
        asked.append((kind, *args, *sorted(kwargs.items())))
        return real(self, kind, *args, **kwargs)

    monkeypatch.setattr(index.Index, "of_kind", spy)
    _status(capsys, "idea", "kiosk", "exploring", "--reason", "pricing page written")
    _status(capsys, "place", "Hytta", "let-go", "--reason", "sold the cabin")
    _status(capsys, "list", "idea")
    assert not [a for a in asked if a[0] == "note"], "no old-order line: no note read"
    _old_order(lb, "asset", "solvind", "Solvind", "let-go", "given away", "2026-10-02T18:00:00Z")
    asked.clear()
    [row] = [r for r in json.loads(_status(capsys, "list", "asset", "--json"))["entities"] if r["status"]]
    assert row["reason"] == "given away" and row["note"] is not None
    assert [a for a in asked if a[0] == "note"] == [
        ("note", "2026-10-01", "2026-10-03", ("source", "manual"))
    ]
    seq = int(Logbook(lb.root).meta["seq"])
    _status(capsys, "asset", "Solvind", "sold")  # supersedes the old-order line
    asked.clear()
    _status(capsys, "list", "asset")
    assert int(Logbook(lb.root).meta["seq"]) == seq + 1
    assert not [a for a in asked if a[0] == "note"], "the old-order line no longer stands: no note read"
