"""`logbook review KIND` (RFC 0037 §5): one sitting for a person, an org, an idea, an asset and a
place. The org, idea and asset queues on a synthetic record (`entities_record`); the refusals, every
number checked before the first line; `people review` and `setup places review` the same sitting as
`review person` and `review place`, their output byte for byte; and `--migrate-rejects`, one line per
no of the old state file, once. Nothing is looked up; every name is synthetic."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
from entities_record import (
    CHILD_PAGE,
    HULL,
    HULL_MMSI,
    KIOSK_DOMAIN,
    ROOT_PAGE,
    YARD,
    record,
)
from places_record import record as places_record
from review_people import review_record

from logbook import cli
from logbook.contrib import entities, entity_review, places_review
from logbook.core.store import Logbook


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main([*args])
    assert e.value.code == 2, args
    return capsys.readouterr().err


def _new_lines(lb: Logbook, seq: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > seq]


def _number(proposals: list[dict[str, Any]], key: str) -> int:
    return next(int(p["number"]) for p in proposals if p["observed"]["key"]["value"] == key)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return record(tmp_path, monkeypatch)


# -- org ------------------------------------------------------------------------------------------------


def test_the_org_queue_proposes_by_the_evidence_then_the_new_ones(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "review", "org").splitlines()
    assert out[0] == "4 proposals · 5 observed orgs not yet placed, 1 placed · tier 2"
    assert out[1] == (
        '  1  [34]  group "nordmann verft" (Nordmann Verft; message 3) → Nordmann Verft AS:'
        " same name Nordmann Verft ~ Nordmann Verft AS · 1 person on both · together on 2 days"
    ), "a company resolution is an org: the yard is canonical, its domain placed"
    assert out[3] == f"  3  [new]  {KIOSK_DOMAIN} (Fjordkiosk; mail 2) → ____"
    assert out[-1].startswith("nothing written: `review org --accept N[,N]`")
    data = _json(capsys, "review", "org")
    hints = {o["key"]["value"]: o["hint"] for o in data["observed"]["unplaced"]}
    assert hints == {
        "nordmann verft": "community",
        "git.example.org/nordmann-verft": "community",
        KIOSK_DOMAIN: "company",
        "nordmann.example.org": "personal",
        "fjordkiosk as": "brand",
    }, "the hint ranks; the family's domain last"
    assert [p["new"] for p in data["proposals"]] == [False, False, True, True]
    assert "example.org" not in hints and "liv.berg@example.org" not in json.dumps(data), "a public provider"
    assert not any(line["kind"] == "entity" for line in Logbook(lb.root).lines()), "nothing written"


def test_accept_binds_through_entity_v1_and_mints_a_new_org_once(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq, head = int(lb.meta["seq"]), str(lb.meta["head"])
    out = _run(capsys, "review", "org", "--accept", "1", "--name", "3", "Fjordkiosk AS")
    assert "accepted 1 nordmann verft → Nordmann Verft AS: 1 line" in out
    assert f"accepted 3 {KIOSK_DOMAIN} → Fjordkiosk AS: 1 line" in out
    yard, kiosk = _new_lines(lb, seq)
    for line in (yard, kiosk):
        assert (line["kind"], line["source"], line["tier"]) == ("entity", "manual", 2)
        assert entities.validate_entity(line["payload"]) == [] and line["payload"]["logbook_head"] == head
    assert yard["payload"]["entity"] == {"type": "org", "id": YARD["id"], "registry": "logbook"}
    assert yard["payload"]["refs"] == [{"kind": "group", "value": "nordmann verft"}]
    assert yard["payload"]["keys"] == {"org": f"domain:{YARD['domain']}"}, "the yard's own key, its domain"
    minted = kiosk["payload"]["entity"]["id"]
    assert uuid.UUID(minted).version == 7 and kiosk["payload"]["label"] == "Fjordkiosk AS"
    assert kiosk["payload"]["refs"] == [{"kind": "domain", "value": KIOSK_DOMAIN}]
    assert kiosk["payload"]["keys"] == {"org": f"domain:{KIOSK_DOMAIN}"}
    data = _json(capsys, "review", "org")
    assert data["observed"]["placed"] == 3, "the group and the kiosk's domain are placed now"
    merchant = next(p for p in data["proposals"] if p["observed"]["key"]["value"] == "fjordkiosk as")
    assert merchant["canonical"]["id"] == minted and merchant["evidence"] == [
        "same name FJORDKIOSK AS ~ Fjordkiosk AS"
    ]
    seq = int(Logbook(lb.root).meta["seq"])
    _run(capsys, "review", "org", "--accept", str(merchant["number"]))
    [bound] = _new_lines(lb, seq)
    assert bound["tier"] == 2 and bound["payload"]["refs"] == [{"kind": "merchant", "value": "fjordkiosk as"}]
    assert "evidence" not in bound["payload"], "the payments are tier 3: a merchant is a ref, never cited"
    assert bound["payload"]["entity"]["id"] == minted, "the key resolves: the id is reused"
    assert Logbook(lb.root).verify()[2] == []


def test_reject_writes_one_entity_review_line_and_a_no_citing_the_ledger_is_tier_three(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "review", "org", "--name", "3", "Fjordkiosk AS")
    proposals = _json(capsys, "review", "org")["proposals"]
    n = _number(proposals, "fjordkiosk as")
    seq = int(Logbook(lb.root).meta["seq"])
    out = _run(capsys, "review", "org", "--reject", str(n))
    assert f"rejected {n} fjordkiosk as ≠ Fjordkiosk AS: 1 line" in out
    [no] = _new_lines(lb, seq)
    assert (no["kind"], no["tier"]) == ("entity-review", 3), "it cites the payments"
    payload = no["payload"]
    assert entities.validate_entity_review(payload) == [] and payload["verdict"] == "different"
    assert (
        payload["ref"] == {"kind": "merchant", "value": "fjordkiosk as"}
        and payload["entity"]["type"] == "org"
    )
    again = _json(capsys, "review", "org")
    assert not any(p["observed"]["key"]["value"] == "fjordkiosk as" for p in again["proposals"])
    assert again["rejected"] == 1
    Logbook(lb.root).retract(int(no["seq"]), "the kiosk after all")
    assert any(
        p["observed"]["key"]["value"] == "fjordkiosk as" for p in _json(capsys, "review", "org")["proposals"]
    )
    n_new = _number(_json(capsys, "review", "org")["proposals"], "nordmann.example.org")
    seq = int(Logbook(lb.root).meta["seq"])
    _run(capsys, "review", "org", "--reject", str(n_new))
    [family] = _new_lines(lb, seq)
    assert family["tier"] == 2 and family["payload"]["entity"] == {"type": "org"}, (
        "a new one rejected: type alone"
    )
    assert not any(
        p["observed"]["key"]["value"] == "nordmann.example.org"
        for p in _json(capsys, "review", "org")["proposals"]
    )


def test_an_entity_line_never_cites_a_tier_three_line(lb: Logbook) -> None:
    payment = next(line for line in lb.lines() if line["kind"] == "transaction")
    payload = entities.entity_payload(
        "org",
        entity_review.uuid7(),
        "Fjordkiosk AS",
        refs=[("merchant", "fjordkiosk as")],
        evidence=[str(payment["id"])],
    )
    seq = int(lb.meta["seq"])
    with pytest.raises(entities.EntityError, match="never cites a tier-3 line"):
        entity_review.write_entity(lb, payload)
    assert int(Logbook(lb.root).meta["seq"]) == seq, "nothing written"


# -- idea -----------------------------------------------------------------------------------------------


def test_an_idea_is_named_by_the_owner_and_its_title_binds_to_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "review", "idea")
    assert [p["observed"]["key"]["value"] for p in data["proposals"]] == [
        f"notion:{ROOT_PAGE}",
        "git.example.org/nordmann-verft/kiosk",
        "fjord kiosk",
    ], "every observed idea new: the dream never mints one"
    seq = int(lb.meta["seq"])
    _run(capsys, "review", "idea", "--name", "1", "the fjord kiosk")
    [idea] = _new_lines(lb, seq)
    payload = idea["payload"]
    assert payload["label"] == "the fjord kiosk" and payload["keys"] == {"idea": f"page:notion:{ROOT_PAGE}"}
    assert payload["refs"] == [
        {"kind": "page", "value": f"notion:{ROOT_PAGE}"},
        {"kind": "page", "value": f"notion:{CHILD_PAGE}"},
    ], "a page under the root is the root's idea"
    [title] = [
        p
        for p in _json(capsys, "review", "idea")["proposals"]
        if p["observed"]["key"]["value"] == "fjord kiosk"
    ]
    assert title["canonical"]["name"] == "the fjord kiosk" and title["score"] >= 35
    assert title["evidence"][0].startswith("same name") and "1 person on both" in title["evidence"]
    seq = int(Logbook(lb.root).meta["seq"])
    _run(capsys, "review", "idea", "--accept", str(title["number"]))
    [bound] = _new_lines(lb, seq)
    assert bound["payload"]["entity"]["id"] == payload["entity"]["id"]
    assert bound["payload"]["refs"] == [{"kind": "title", "value": "fjord kiosk"}]


# -- asset ----------------------------------------------------------------------------------------------


def test_an_asset_is_matched_by_its_registration_or_registered_new(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "review", "asset")
    first, second = data["proposals"]
    assert (first["score"], first["canonical"]["id"], first["evidence"]) == (
        50,
        "lerka",
        ["same registration ZZ-ABC ~ ZZABC"],
    )
    assert second["new"] and second["observed"]["key"] == {"kind": "mmsi", "value": HULL_MMSI}
    seq = int(lb.meta["seq"])
    _run(capsys, "review", "asset", "--accept", "1", "--name", "2", "Gamle Solvind")
    lerka, hull = _new_lines(lb, seq)
    assert lerka["payload"]["entity"]["id"] == "lerka"
    assert lerka["payload"]["refs"] == [{"kind": "registration", "value": "ZZ-ABC"}]
    assert hull["payload"]["entity"]["id"] == HULL and hull["payload"]["refs"] == [
        {"kind": "mmsi", "value": HULL_MMSI}
    ]
    registry = json.loads((lb.root / "assets.json").read_text(encoding="utf-8"))["assets"]
    assert registry[-1] == {"id": HULL, "kind": "yacht", "name": "Gamle Solvind", "mmsi": HULL_MMSI}, (
        "registered as `assets add` writes it, under the id its lines carry"
    )
    assert _json(capsys, "review", "asset")["proposals"] == []


# -- the refusals ---------------------------------------------------------------------------------------


def test_the_sitting_refuses_what_it_cannot_act_on_and_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    for args, words in (
        (("review", "org", "--accept", "9"), "no proposal 9"),
        (("review", "org", "--accept", "1", "--reject", "1"), "both accepted and rejected"),
        (("review", "org", "--accept", "1,x"), "not a proposal number"),
        (("review", "org", "--all-above", "high"), "not a score"),
        (("review", "org", "--name", "1", "The Yard"), "Nordmann Verft AS already"),
        (("review", "org", "--accept", "3", "--reject", "9"), "no proposal 9"),
        (("review", "idea", "--top", "2"), "--top goes with `review place`"),
        (("review", "person", "--name", "1", "Ola"), "--name goes with a new org"),
        (("review", "place", "--all-above", "3"), "no score"),
        (("review", "--accept", "1"), "say which kind"),
    ):
        err = _refused(capsys, *args)
        assert words in err, (args, err)
        assert err.startswith("review"), err
    assert int(Logbook(lb.root).meta["seq"]) == seq, "every number checked before the first line"


def test_review_with_no_kind_lists_every_queue_and_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    out = _run(capsys, "review").splitlines()
    assert [line for line in out if not line.startswith(" ")] == ["person", "org", "idea", "asset", "place"]
    assert "  4 proposals · 5 observed orgs not yet placed, 1 placed · tier 2" in out
    assert set(_json(capsys, "review")) == {"person", "org", "idea", "asset", "place"}
    assert int(Logbook(lb.root).meta["seq"]) == seq, "nothing written"


# -- people review and places review: the same sitting -------------------------------------------------


@pytest.mark.parametrize("extra", [(), ("--json",)], ids=["text", "json"])
def test_review_person_is_people_review_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: tuple[str, ...],
) -> None:
    review_record(tmp_path, monkeypatch)
    assert _run(capsys, "review", "person", *extra) == _run(capsys, "people", "review", *extra)


@pytest.mark.parametrize("extra", [(), ("--json",), ("--top", "3", "--verbose")], ids=["text", "json", "top"])
def test_review_place_is_places_review_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: tuple[str, ...],
) -> None:
    root = tmp_path / "lb"
    places_record(root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    assert _run(capsys, "review", "place", *extra) == _run(capsys, "setup", "places", "review", *extra)


def test_migrate_rejects_writes_one_line_per_old_no_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "lb"
    places_record(root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook(root)
    report = places_review.read(lb)
    fourth, sixth = report.proposals[3], report.proposals[5]
    old = [  # the file as 0.6 wrote it: the pairs beside the record, never lines
        {"lat": round(fourth.lat, 6), "lon": round(fourth.lon, 6), "name": fourth.name, "id": fourth.id,
         "rejected_at": "2026-10-01T18:00:00Z"},
        {"lat": round(sixth.lat, 6), "lon": round(sixth.lon, 6), "name": None, "id": sixth.id,
         "rejected_at": "2026-10-02T18:00:00Z"},
    ]  # fmt: skip
    state = places_review.state_path(root)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"rejected": old}, indent=2) + "\n", encoding="utf-8")
    cli.main(["setup", "places", "review", "--json"])
    captured = capsys.readouterr()
    before = json.loads(captured.out)
    assert "2 noes in state/places-review.json are not a line yet" in captured.err
    seq = int(lb.meta["seq"])
    cli.main(["setup", "places", "review", "--migrate-rejects", "--json"])
    captured = capsys.readouterr()
    assert "migrate-rejects: wrote 2 lines" in captured.err
    after = json.loads(captured.out)
    assert after.pop("head") != before.pop("head")
    assert after == before, "the queue is what it was: the same noes, now lines"
    lines = _new_lines(lb, seq)
    assert len(lines) == 2 and [line["at"] for line in lines] == [
        "2026-10-01T18:00:00Z",
        "2026-10-02T18:00:00Z",
    ]
    for line, row in zip(lines, old, strict=True):
        payload = line["payload"]
        assert line["kind"] == "entity-review" and entities.validate_entity_review(payload) == []
        assert payload["entity"] == {"type": "place"} and payload.get("label") == row["name"]
        assert payload["ref"] == {"kind": "centre", "value": places_review.centre(row["lat"], row["lon"])}
        assert payload["extra"]["migrated_from"] == "state/places-review.json"
    cache = json.loads(state.read_text(encoding="utf-8"))
    assert [row["line"] for row in cache["rejected"]] == [line["id"] for line in lines], (
        "a cache of the lines"
    )
    seq = int(Logbook(root).meta["seq"])
    cli.main(["setup", "places", "review", "--migrate-rejects"])
    assert "migrate-rejects: wrote 0 lines" in capsys.readouterr().err
    assert int(Logbook(root).meta["seq"]) == seq, "idempotent: a second run writes nothing"
    shutil.copy(state, tmp_path / "cache.json")
    state.write_text(
        json.dumps({"rejected": old}, indent=2) + "\n", encoding="utf-8"
    )  # an old backup restored
    cli.main(["setup", "places", "review", "--migrate-rejects"])
    assert "wrote 0 lines, 2 already lines" in capsys.readouterr().err
    assert int(Logbook(root).meta["seq"]) == seq
    Logbook(root).retract(int(lines[0]["seq"]), "the boathouse after all")
    after = _json(capsys, "setup", "places", "review")
    assert after["proposals"][3]["name"] == fourth.name, "the line retracted: the pair returns"
