"""`logbook people review`: the observed people of the record, keyed by their strongest identifier,
proposed against the people the owner has confirmed, accepted or rejected only when the owner says
so; and `people --priority`. The review fixture (`review_people.py`): 25 people who do not exist,
seen as 60-odd identities across mail, messages, a calendar and one transcript."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from circle import circle_record
from review_people import (
    PEOPLE,
    SPELLED,
    THREE_NAMES,
    TRANSCRIPT_SPEAKER,
    A,
    D,
    identities_seen,
    jid,
    review_drafts,
    review_record,
)

from logbook import cli
from logbook.contrib import people_review
from logbook.core import resolve
from logbook.core.store import Logbook


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _proposals(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = _json(capsys, "people", "review")["proposals"]
    return found


def _number_of(proposals: list[dict[str, Any]], key: tuple[str, str], canonical: str) -> int:
    for p in proposals:
        if (p["observed"]["key"]["kind"], p["observed"]["key"]["value"]) == key and p["canonical"][
            "id"
        ] == canonical:
            return int(p["number"])
    raise AssertionError(f"no proposal {key} → {canonical}")


def _resolutions(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return [*idx.retractions(), *idx.resolutions()]


def _people_rows(capsys: pytest.CaptureFixture[str], names: set[str]) -> dict[str, str]:
    rows = {}
    for text in _run(capsys, "people").splitlines()[1:]:
        name = text.strip().split("  ")[0]
        if name in names:
            rows[name] = text
    return rows


# -- observed people -----------------------------------------------------------------------------------------


def test_the_fixture_has_sixty_observed_identities_for_twenty_five_people() -> None:
    drafts = review_drafts("019cadd3-6bc0-7dcd-9133-000000000000")
    assert len(PEOPLE) == 25
    assert len(identities_seen(drafts)) >= 60


def test_an_observed_person_is_keyed_by_the_strongest_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    rows = {row.key: row for row in people_review.observed(lb)}
    maren = PEOPLE[THREE_NAMES[0]]
    by_mail = rows[("email", maren["email"])]
    assert sorted(by_mail.labels) == ["Eide, Maren", "Maren Eide", "maren eide"], "three names, one person"
    assert by_mail.name == "Maren Eide", "the name shown most, the first written when tied"
    assert by_mail.sources == {"mail": 3} and by_mail.kinds == {"mail": 3} and by_mail.lines == 3
    assert by_mail.first < by_mail.last and len(by_mail.days) == 3
    assert by_mail.entity is None, "the address book knows her number only: the address is not placed"
    assert rows[("phone", maren["phone"])].entity == maren["id"], "her number is"
    kari = PEOPLE[1]
    assert rows[("email", kari["email"])].entity == kari["id"]
    by_phone = rows[("phone", kari["phone"])]
    assert by_phone.entity == kari["id"] and by_phone.kinds == {"message": 3}, (
        "her line and the owner's two replies"
    )
    assert by_phone.identifiers == {("phone", kari["phone"]): 3}, (
        "the chat the owner wrote in is the number it spells"
    )
    eva = PEOPLE[11]
    assert rows[("phone", eva["phone"])].identifiers == {("handle", jid(eva)): 2}, (
        "a JID is the number it spells"
    )
    spelled = rows[("email", SPELLED[11].casefold())]
    assert spelled.entity is None, "spelled with capitals, which no line resolves as written"
    assert spelled.identifiers == {("email", SPELLED[11]): 1} and spelled.kinds == {"event": 1}
    assert ("name", "eide m") in rows and rows[("name", "eide m")].identifiers == {
        ("provider_id", TRANSCRIPT_SPEAKER): 1
    }
    simen = rows[("name", "ronning thea")]
    assert simen.identifiers == {} and simen.entity is None, "a spoken name alone"
    assert len(rows) < len(identities_seen(review_drafts(str(lb.meta["owner_id"]))))
    assert all(row.key[0] in ("email", "phone", "name") for row in rows.values()), (
        "never a per-observation id"
    )
    assert spelled.tier == 1 and by_mail.tier == 2, "the tier of the evidence: a calendar entry is tier 1"


def test_the_observed_table_lives_in_the_index_and_follows_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    before = people_review.observed(lb)
    db = sqlite3.connect(lb.index_path)
    try:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({people_review.TABLE})")}
        assert set(people_review.COLUMNS) <= columns
        assert db.execute(f"SELECT count(*) FROM {people_review.TABLE}").fetchone()[0] == len(before)
        head = dict(db.execute(f"SELECT key, value FROM {people_review.TABLE_META}"))["head"]
        assert head == lb.meta["head"]
    finally:
        db.close()
    assert people_review.observed(lb) == before, "served from the table while the head stands"
    from circle import mail
    from review_people import OWNER

    lb.append_many(
        [mail("2026-06-28T09:00:00Z", {"name": "Nora Aas", "email": "n.aas@example.org"}, OWNER, "Hi")]
    )
    after = people_review.observed(lb)
    assert len(after) == len(before) + 1, "rebuilt from the lines once the head moved"
    db = sqlite3.connect(lb.index_path)
    try:
        db.execute(f"ALTER TABLE {people_review.TABLE} DROP COLUMN days")
        db.commit()
    finally:
        db.close()
    assert people_review.observed(lb) == after, "a table of another shape is built again, not read"
    assert lb.verify()[2] == [], "nothing in the record changed"


# -- the queue -----------------------------------------------------------------------------------------------


def test_review_proposes_observed_to_canonical_ranked_by_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    data = _json(capsys, "people", "review")
    proposals = data["proposals"]
    assert [p["number"] for p in proposals] == list(range(1, len(proposals) + 1))
    scores = [p["score"] for p in proposals]
    assert scores == sorted(scores, reverse=True), "ranked by evidence"
    assert len(proposals) == 15
    spelled = {(p["observed"]["key"]["value"], p["canonical"]["id"]) for p in proposals[:2]}
    assert spelled == {(SPELLED[n].casefold(), PEOPLE[n]["id"]) for n in SPELLED}, (
        "the same address ranks first"
    )
    for p in proposals[:2]:
        address, name = p["observed"]["key"]["value"], p["canonical"]["name"]
        assert p["score"] == 80 and p["evidence"] == [f"same email {address}", f"same name {name}"]
    by_key = {(p["observed"]["key"]["kind"], p["observed"]["key"]["value"]): p for p in proposals}
    astrid = PEOPLE[15]
    p = by_key[("phone", astrid["phone"])]
    assert p["canonical"] == {"id": astrid["id"], "name": "Astrid Bakke"}
    assert p["score"] == 22 and p["evidence"] == ["same name Astrid Bakke", "together on 1 day"]
    eva = PEOPLE[11]
    assert by_key[("phone", eva["phone"])]["evidence"][0] == "same name Eva Nordmann"
    maren = PEOPLE[19]
    assert by_key[("email", maren["email"])]["evidence"] == ["same name Maren Eide", "together on 1 day"]
    assert by_key[("name", "eide m")]["evidence"] == ["same name M. Eide ~ Maren Eide"]
    assert by_key[("name", "eide m")]["canonical"]["id"] == maren["id"]
    targets = {p["canonical"]["id"] for p in proposals}
    assert not targets & {PEOPLE[n]["id"] for n in A}, "a person seen only as resolved is proposed nothing"
    assert not any(p["observed"]["key"]["value"] == PEOPLE[n]["email"] for p in proposals for n in D)
    unplaced = {(o["key"]["kind"], o["key"]["value"]) for o in data["observed"]["unplaced"]}
    assert ("name", "ronning thea") in unplaced and ("email", PEOPLE[23]["email"]) in unplaced
    assert ("name", "ronning thea") not in by_key, "a spoken name alone has no identifier to write"
    assert data["observed"]["placed"] > 0 and data["tier"] == 2
    assert all(len(p["id"]) == 16 for p in proposals)
    assert lb.meta["seq"] == seq, "proposing writes nothing"
    assert _json(capsys, "people", "review") == data, "stable until the record changes"


def test_review_prints_numbered_proposals_with_the_evidence_on_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    review_record(tmp_path, monkeypatch)
    text = _run(capsys, "people", "review")
    lines = text.splitlines()
    assert lines[0].startswith("15 proposals · ") and "not yet placed" in lines[0] and "tier 2" in lines[0]
    assert lines[1].startswith("   1  [80]  ") and "→" in lines[1] and "same email" in lines[1]
    numbered = [line for line in lines if line.startswith("  ") and "  [" in line]
    assert len(numbered) == 15 and all(line.count("\n") == 0 for line in numbered)
    astrid = next(line for line in numbered if "+447700900115" in line)
    assert "Astrid Bakke" in astrid and "same name Astrid Bakke · together on 1 day" in astrid
    assert "nothing written" in lines[-1] and "--accept" in lines[-1] and "--reject" in lines[-1]


def test_accept_writes_the_line_people_merge_writes_and_the_readers_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    proposals = _proposals(capsys)
    astrid, eva, maren = PEOPLE[15], PEOPLE[11], PEOPLE[19]
    numbers = (
        _number_of(proposals, ("phone", astrid["phone"]), astrid["id"]),
        _number_of(proposals, ("phone", eva["phone"]), eva["id"]),
        _number_of(proposals, ("name", "eide m"), maren["id"]),
    )
    before = {p["id"]: p for p in _json(capsys, "people")["people"]}
    assert before[astrid["id"]]["channels"] == {"mail": before[astrid["id"]]["channels"]["mail"]}
    head, seq = lb.meta["head"], lb.meta["seq"]
    out = _run(
        capsys, "people", "review", "--accept", f"{numbers[0]},{numbers[1]}", "--accept", str(numbers[2])
    )
    assert "accepted +447700900115 → Astrid Bakke: 1 line" in out
    assert "accepted +447700900111 → Eva Nordmann: 1 line" in out, "the number the JID spells"
    assert "accepted M. Eide → Maren Eide: 1 line" in out
    assert lb.meta["seq"] == seq + 3 and lb.verify()[2] == []
    new = [line for line in lb.lines() if int(line["seq"]) > seq]
    by_ref = {(line["payload"]["ref"]["kind"], line["payload"]["ref"]["value"]): line for line in new}
    for line in new:
        payload = line["payload"]
        assert line["kind"] == "resolution" and line["source"] == "manual" and line["tier"] == 2
        assert (
            payload["schema"] == "resolution/v1" and "entity" not in payload and "supersedes" not in payload
        )
        assert payload["method"] == "owner" and payload["logbook_head"] == head
        assert payload["evidence"][0] and len(payload["evidence"]) >= 2, (
            "the target's line, then what was seen"
        )
        assert set(payload["extra"]) == {"review", "into", "score", "matched"}
    assert by_ref[("phone", astrid["phone"])]["payload"]["alias_of"] == {
        "kind": "email",
        "value": astrid["email"],
    }
    assert by_ref[("phone", astrid["phone"])]["payload"]["label"] == "Astrid Bakke"
    assert by_ref[("handle", jid(eva))]["payload"]["alias_of"] == {"kind": "email", "value": eva["email"]}
    assert by_ref[("provider_id", TRANSCRIPT_SPEAKER)]["payload"]["alias_of"] == {
        "kind": "phone",
        "value": maren["phone"],
    }
    identities = resolve.identities_from(_resolutions(lb))
    assert identities[("phone", astrid["phone"])].entity == astrid["id"]
    assert identities[("handle", jid(eva))].entity == eva["id"]
    assert identities[("provider_id", TRANSCRIPT_SPEAKER)] == resolve.Identity(
        maren["id"], "person", "Maren Eide"
    )
    after = {p["id"]: p for p in _json(capsys, "people")["people"]}
    assert after[astrid["id"]]["channels"]["messages"]["lines"] == 3, "her two and the owner's reply"
    assert after[eva["id"]]["channels"]["messages"]["lines"] == 2
    assert after[maren["id"]]["channels"]["transcripts"]["lines"] == 1
    again = _proposals(capsys)
    assert len(again) == len(proposals) - 3, "a second review is shorter by what was accepted"
    assert [p["number"] for p in again] == list(range(1, len(again) + 1)), "numbered afresh"
    keys = {(p["observed"]["key"]["kind"], p["observed"]["key"]["value"]) for p in again}
    assert not keys & {("phone", astrid["phone"]), ("phone", eva["phone"]), ("name", "eide m")}
    rows = {row.key: row for row in people_review.observed(lb)}
    assert rows[("phone", astrid["phone"])].entity == astrid["id"], "placed now"


def test_reject_writes_a_line_and_the_pair_never_comes_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    proposals = _proposals(capsys)
    hanna = PEOPLE[21]
    n = _number_of(proposals, ("email", hanna["email"]), hanna["id"])
    head, seq = lb.meta["head"], lb.meta["seq"]
    out = _run(capsys, "people", "review", "--reject", str(n))
    assert f"rejected {hanna['email']} ≠ Hanna Foss: 1 line" in out
    assert lb.meta["seq"] == seq + 1 and lb.verify()[2] == []
    (line,) = [line for line in lb.lines() if int(line["seq"]) > seq]
    assert line["kind"] == people_review.KIND and line["source"] == "manual" and line["tier"] == 2
    payload = line["payload"]
    assert payload["schema"] == people_review.SCHEMA and payload["verdict"] == "different"
    assert payload["ref"] == {"kind": "email", "value": hanna["email"]}
    assert payload["refs"] == [{"kind": "email", "value": hanna["email"]}]
    assert payload["entity"] == {"type": "person", "id": hanna["id"], "registry": "logbook"}
    assert payload["label"] == "Hanna Foss" and payload["observed"] == ["Hanna Foss"]
    assert payload["method"] == "owner" and payload["logbook_head"] == head and payload["evidence"]
    again = _proposals(capsys)
    assert len(again) == len(proposals) - 1
    assert not any(
        p["observed"]["key"]["value"] == hanna["email"] and p["canonical"]["id"] == hanna["id"] for p in again
    ), "a rejected pair is never proposed again"
    data = _json(capsys, "people", "review")
    assert ("email", hanna["email"]) in {
        (o["key"]["kind"], o["key"]["value"]) for o in data["observed"]["unplaced"]
    }
    assert data["rejected"] == 1
    identities = resolve.identities_from(_resolutions(lb))
    assert ("email", hanna["email"]) not in identities, "nothing resolved; the address stays observed"
    # the owner changes their mind: the review line retracted, the proposal is back
    lb.retract(int(line["seq"]), "same person after all")
    assert len(_proposals(capsys)) == len(proposals)


def test_all_above_accepts_every_proposal_at_or_above_the_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    out = _run(capsys, "people", "review", "--all-above", "60")
    assert out.count("accepted ") == 2 and lb.meta["seq"] == seq + 2, "the two addresses at 80; nothing at 22"
    identities = resolve.identities_from(_resolutions(lb))
    for n, spelled in SPELLED.items():
        assert identities[("email", spelled.casefold())].entity == PEOPLE[n]["id"]
    assert len(_proposals(capsys)) == 13
    out = _run(capsys, "people", "review", "--all-above", "90")
    assert "nothing" in out and lb.meta["seq"] == seq + 2


def test_review_refuses_what_it_cannot_act_on_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    for args in (
        ("--accept", "1,99"),
        ("--reject", "0"),
        ("--accept", "two"),
        ("--accept", "1", "--reject", "1"),
        ("--all-above", "x"),
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(["people", "review", *args])
        assert e.value.code == 2, args
        err = capsys.readouterr().err
        assert "people review" in err, args
    assert lb.meta["seq"] == seq
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "--accept", "1"])
    assert e.value.code == 2 and "people review" in capsys.readouterr().err


def test_people_rows_of_placed_people_do_not_change_under_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    review_record(tmp_path, monkeypatch)
    names = {PEOPLE[n]["name"] for n in A}
    before = _people_rows(capsys, names)
    assert set(before) == names
    proposals = _proposals(capsys)
    _run(capsys, "people", "review", "--accept", ",".join(str(p["number"]) for p in proposals[:5]))
    _run(capsys, "people", "review", "--reject", "1,2")
    assert _people_rows(capsys, names) == before
    assert _run(capsys, "people", "review").splitlines()[0].startswith("8 proposals")


def test_an_empty_record_and_a_record_with_nothing_to_review_say_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _run(capsys, "people", "review").strip() == "no proposals: nobody observed is unplaced"
    data = _json(capsys, "people", "review")
    assert data["proposals"] == [] and data["observed"] == {"placed": 0, "unplaced": []}
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "review", "--accept", "1"])
    assert e.value.code == 2


# -- priority ------------------------------------------------------------------------------------------------


def test_the_priority_score_is_the_documented_sum() -> None:
    score = people_review.score
    assert score(days=3, them=2, me=3, meetings=2, since=5) == 9 + 2 + 4 + 10
    assert score(days=0, them=80, me=70, meetings=0, since=60) == 50 + 5, "messages cap at 50; 90 days is 5"
    assert score(days=0, them=10, me=0, meetings=0, since=200) == 0, "one way is no conversation"
    assert score(days=1, them=0, me=0, meetings=1, since=None) == 5, "no real contact, no recency"


def test_people_priority_ranks_the_canonical_people_with_the_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    data = _json(capsys, "people", "--priority")
    assert data["window"] == {"since": "2026-06-01", "until": "2026-06-27"}, (
        "the last year, clipped to the record"
    )
    ranked = data["people"]
    assert ranked[0]["name"] == "Kari Nordmann" and ranked[0]["score"] == 15
    assert (
        ranked[0]["messages"] == {"them": 1, "me": 2}
        and ranked[0]["meetings"] == 2
        and ranked[0]["days"] == 0
    )
    assert ranked[0]["recency"] == 10 and ranked[0]["last_real_contact"] == "2026-06-07"
    assert [p["score"] for p in ranked] == sorted((p["score"] for p in ranked), reverse=True)
    scores = {p["name"]: p["score"] for p in ranked}
    assert {scores[PEOPLE[n]["name"]] for n in A if n != 1} == {10}, (
        "a recent message their way; one way is 0"
    )
    assert {scores[PEOPLE[n]["name"]] for n in range(13, 19)} == {0}, (
        "mail is a channel, never a real contact"
    )
    assert len(ranked) == 20, "every canonical person heard in the window; nobody observed only"
    assert lb.meta["seq"] == seq
    text = _run(capsys, "people", "--priority")
    lines = text.splitlines()
    assert lines[0].startswith("priority · 2026-06-01 \u2013 2026-06-27 · 20 people")
    assert lines[1].startswith("  15  Kari Nordmann") and "messages 1 from them, 2 from you" in lines[1]
    assert "meetings 2" in lines[1] and "last real contact 2026-06-07" in lines[1]


def test_people_priority_counts_days_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    circle_record(tmp_path, monkeypatch)
    ranked = _json(capsys, "people", "--priority")["people"]
    ola = ranked[0]
    assert ola["name"] == "Ola Nordmann" and ola["days"] == 3 and ola["messages"] == {"them": 2, "me": 3}
    assert ola["score"] == 9 + 2 + ola["meetings"] * 2 + ola["recency"]
    year = _json(capsys, "people", "--priority", "--year", "2026")["people"]
    assert year[0]["name"] == "Ola Nordmann"
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "Ola Nordmann", "--priority"])
    assert e.value.code == 2
