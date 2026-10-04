"""`logbook people merge`: the same person named twice or more by the record's resolution lines,
proposed with the evidence and merged only when the owner says so, by alias lines that readers
follow (RFC 0006). The duplicates fixture (`duplicates.py`); nothing real."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from duplicates import (
    ANDERS_A,
    ANDERS_B,
    ANDERS_SPEAKER,
    ANNA,
    ANNE,
    EVA,
    KARI_A,
    KARI_B,
    KARI_EMAIL,
    KARI_JID,
    KARI_LID,
    KARI_PHONE,
    LIV_A,
    LIV_B,
    LIV_WORK,
    PER_A,
    PER_B,
    PER_C,
    PER_EMAIL_SPELLED,
    PER_ENTERED,
    PER_LID,
    PER_PHONE,
    duplicate_record,
)

from logbook import cli
from logbook.contrib import people_merge
from logbook.core import resolve
from logbook.core.store import Logbook


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _by_primary(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["primary"]["id"]: p for p in data["proposals"]}


def _resolutions(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return [*idx.retractions(), *idx.resolutions()]


# -- proposing ---------------------------------------------------------------------------------------------


def test_propose_finds_the_four_duplicates_and_keeps_the_near_misses_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = duplicate_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    data = _json(capsys, "people", "merge", "--propose")
    found = _by_primary(data)
    assert set(found) == {KARI_A, PER_A, LIV_A, ANDERS_A}, "the one with most refs is the primary"
    kari = found[KARI_A]
    assert [s["id"] for s in kari["secondary"]] == [KARI_B]
    assert kari["primary"]["name"] == "Kari Nordmann" and kari["secondary"][0]["name"] == "Kari"
    assert [(m["kind"], m["value"]) for m in kari["matches"]] == [("phone", KARI_PHONE)]
    assert kari["matches"][0]["refs"] == [
        {"kind": "phone", "value": KARI_PHONE},
        {"kind": "handle", "value": KARI_JID},
    ], "a WhatsApp JID is the number it spells"
    kinds = {r["kind"] for r in kari["primary"]["refs"]}
    assert kinds == {"phone", "email", "handle"}, "the lid alias is hers"
    assert sorted(kari["primary"]["sources"]) == ["ios-contacts", "whatsapp-contacts"]
    assert kari["secondary"][0]["sources"] == ["manual"]
    per = found[PER_A]
    assert {s["id"] for s in per["secondary"]} == {PER_B, PER_C}, "three entities, one proposal"
    kinds = sorted((m["kind"], m["value"]) for m in per["matches"])
    assert kinds == [("email", "per.hansen@example.org"), ("phone", PER_PHONE)]
    phone = next(m for m in per["matches"] if m["kind"] == "phone")
    assert phone["refs"][1] == {"kind": "phone", "value": PER_ENTERED}, "normalised with the dial prefix"
    liv = found[LIV_A]
    assert [s["id"] for s in liv["secondary"]] == [LIV_B]
    (match,) = liv["matches"]
    assert (
        match["kind"] == "name" and match["value"] == "Liv Berg ~ Berg, Liv" and match["channels"] == ["mail"]
    )
    anders = found[ANDERS_A]
    assert [s["id"] for s in anders["secondary"]] == [ANDERS_B]
    (match,) = anders["matches"]
    assert match["kind"] == "name" and match["channels"] == ["transcripts"], "an initial for the first name"
    everyone = {e["id"] for p in data["proposals"] for e in (p["primary"], *p["secondary"])}
    assert not everyone & {EVA, ANNA, ANNE}  # a surname shared, or a name one letter off, is nobody twice
    assert all(len(p["id"]) == 16 for p in data["proposals"])
    assert data["tier"] == 2 and all(p["tier"] == 2 for p in data["proposals"])
    again = _json(capsys, "people", "merge")
    assert again == data, "--propose is the default, and the ids are stable"
    assert lb.meta["seq"] == seq, "proposing writes nothing"


def test_propose_prints_each_proposal_with_its_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    duplicate_record(tmp_path, monkeypatch)
    text = _run(capsys, "people", "merge")
    lines = text.splitlines()
    assert lines[0] == "4 proposals · 9 people named twice or more · tier 2"
    assert any(line.startswith("  ") and "Kari Nordmann ← Kari" in line for line in lines)
    assert any(
        f"phone {KARI_PHONE}:" in line and "ios-contacts" in line and "manual" in line for line in lines
    )
    assert any("name Liv Berg ~ Berg, Liv · both on mail" in line for line in lines)
    assert "nothing merged" in lines[-1], "a proposal is never applied silently"


def test_a_record_with_nobody_twice_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = duplicate_record(tmp_path, monkeypatch)
    data = _json(capsys, "people", "merge")
    cli.main(["people", "merge", "--apply", *(p["id"] for p in data["proposals"])])
    capsys.readouterr()
    assert _run(capsys, "people", "merge").strip() == "no proposals: nobody is named twice"
    assert _json(capsys, "people", "merge") == {"tier": None, "proposals": []}
    assert lb.verify()[2] == []


def test_similar_names() -> None:
    similar = people_merge.similar_names
    assert similar("Kari Nordmann", "Nordmann, Kari")
    assert similar("K. Nordmann", "Kari Nordmann") and similar("Kari Nordmann", "K Nordmann")
    assert similar("Jørgen Åsen", "Jorgen Asen") and similar("  liv   BERG ", "Liv Berg")
    assert not similar("Anna Hansen", "Anne Hansen"), "one letter off is another person"
    assert not similar("Eva Nordmann", "Kari Nordmann"), "a surname is not a name"
    assert not similar("Kari", "Kari Nordmann"), "a first name alone names anyone"
    assert not similar("Kari Nordmann", "Kari Nordmann Berg")
    assert not similar("", "Kari Nordmann")


# -- applying ------------------------------------------------------------------------------------------------


def test_apply_appends_alias_lines_and_the_readers_follow_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = duplicate_record(tmp_path, monkeypatch)
    before = _json(capsys, "people")
    assert len(before["people"]) == 10, "every entity with evidence, the duplicates among them"
    proposals = _by_primary(_json(capsys, "people", "merge"))
    head, seq = lb.meta["head"], lb.meta["seq"]
    out = _run(capsys, "people", "merge", "--apply", proposals[KARI_A]["id"], proposals[PER_A]["id"])
    assert "merged Kari → Kari Nordmann: 1 line" in out
    assert "merged Per Hansen, Per Hansen → Per Hansen: 2 lines" in out
    assert lb.meta["seq"] == seq + 3, "one alias line per ref that named a secondary; the lid alias follows"
    assert lb.verify()[2] == []
    new = [line for line in lb.lines() if int(line["seq"]) > seq]
    for line in new:
        payload = line["payload"]
        assert line["kind"] == "resolution" and line["source"] == "manual" and line["tier"] == 2
        assert payload["schema"] == "resolution/v1" and "entity" not in payload
        assert payload["method"] == "owner" and payload["logbook_head"] == head
        assert len(payload["evidence"]) == 2 and payload["supersedes"] == payload["evidence"][0]
        assert payload["extra"]["merge"] in {proposals[KARI_A]["id"], proposals[PER_A]["id"]}
    by_ref = {
        (line["payload"]["ref"]["kind"], line["payload"]["ref"]["value"]): line["payload"] for line in new
    }
    assert by_ref[("handle", KARI_JID)]["alias_of"] == {"kind": "phone", "value": KARI_PHONE}
    assert by_ref[("handle", KARI_JID)]["label"] == "Kari Nordmann" and by_ref[("handle", KARI_JID)][
        "extra"
    ] == {
        "merge": proposals[KARI_A]["id"],
        "from": KARI_B,
        "into": KARI_A,
        "matched": [f"phone {KARI_PHONE}"],
    }
    assert by_ref[("email", PER_EMAIL_SPELLED)]["alias_of"] == {"kind": "phone", "value": PER_PHONE}
    assert by_ref[("phone", PER_ENTERED)]["alias_of"] == {"kind": "phone", "value": PER_PHONE}
    identities = resolve.identities_from(_resolutions(lb))
    assert identities[("handle", KARI_JID)].entity == KARI_A
    assert identities[("handle", KARI_LID)].entity == KARI_A
    # lid → number as entered → the number → Per: an alias of an alias, followed transitively
    assert identities[("handle", PER_LID)] == resolve.Identity(PER_A, "person", "Per Hansen")
    assert identities[("email", PER_EMAIL_SPELLED)].entity == PER_A
    after = _json(capsys, "people")
    people = {p["id"]: p for p in after["people"]}
    assert set(people) == set(p["id"] for p in before["people"]) - {KARI_B, PER_B, PER_C}
    kari = people[KARI_A]
    assert {(r["kind"], r["value"]) for r in kari["refs"]} == {
        ("phone", KARI_PHONE),
        ("email", KARI_EMAIL),
        ("handle", KARI_LID),
        ("handle", KARI_JID),
    }
    assert kari["channels"]["messages"]["lines"] == 3, "the JID's message is hers now"
    assert kari["channels"]["mail"]["lines"] == 1 and kari["name"] == "Kari Nordmann"
    page = _json(capsys, "person", f"handle:{KARI_JID}")
    assert page["id"] == KARI_A, "a secondary's ref finds the primary's page"
    page = _json(capsys, "person", f"phone:{PER_ENTERED}")
    assert page["id"] == PER_A and page["channels"]["calendar"]["lines"] == 1
    left = _by_primary(_json(capsys, "people", "merge"))
    assert set(left) == {LIV_A, ANDERS_A}, "a merge applied is proposed no more"


def test_apply_refuses_an_unknown_id_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = duplicate_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    proposals = _by_primary(_json(capsys, "people", "merge"))
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "merge", "--apply", proposals[LIV_A]["id"], "0123456789abcdef"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "no proposal 0123456789abcdef" in err and "--propose" in err
    assert lb.meta["seq"] == seq, "one unknown id and nothing is written, not even the known one"


def test_apply_json_names_the_lines_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = duplicate_record(tmp_path, monkeypatch)
    proposals = _by_primary(_json(capsys, "people", "merge"))
    data = _json(capsys, "people", "merge", "--apply", proposals[ANDERS_A]["id"])
    assert data == {
        "applied": [
            {
                "proposal": proposals[ANDERS_A]["id"],
                "into": {"id": ANDERS_A, "name": "Anders Vik"},
                "from": [{"id": ANDERS_B, "name": "A. Vik"}],
                "lines": data["applied"][0]["lines"],
            }
        ]
    }
    (line_id,) = data["applied"][0]["lines"]
    assert len(line_id) == 36
    identities = resolve.identities_from(_resolutions(lb))
    assert identities[("provider_id", ANDERS_SPEAKER)].entity == ANDERS_A
    people = {p["id"]: p for p in _json(capsys, "people")["people"]}
    assert people[ANDERS_A]["channels"]["transcripts"]["lines"] == 2 and ANDERS_B not in people


def test_merge_flags_are_one_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    duplicate_record(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "merge", "--propose", "--apply", "0123456789abcdef"])
    assert e.value.code == 2


# -- the review file -----------------------------------------------------------------------------------------


def test_export_review_writes_one_row_per_secondary_and_apply_review_takes_the_marked_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = duplicate_record(tmp_path, monkeypatch)
    proposals = _by_primary(_json(capsys, "people", "merge"))
    review = tmp_path / "review.csv"
    out = _run(capsys, "people", "merge", "--export-review", str(review))
    assert out.strip() == f"wrote 5 rows for 4 proposals to {review}; mark `apply` and run --apply-review"
    with review.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["secondary_id"] for r in rows] == [KARI_B, PER_B, PER_C, LIV_B, ANDERS_B]
    assert list(rows[0]) == [
        "proposal",
        "apply",
        "primary_id",
        "primary",
        "primary_refs",
        "secondary_id",
        "secondary",
        "secondary_refs",
        "matched",
    ]
    assert rows[0]["proposal"] == proposals[KARI_A]["id"] and rows[0]["apply"] == ""
    assert rows[0]["primary"] == "Kari Nordmann" and rows[0]["secondary"] == "Kari"
    assert rows[0]["secondary_refs"] == f"handle:{KARI_JID}" and rows[0]["matched"] == f"phone {KARI_PHONE}"
    assert rows[3]["matched"] == "name Liv Berg ~ Berg, Liv (mail)"
    for row, mark in zip(rows, ("yes", "", "x", "", "no"), strict=True):
        row["apply"] = mark
    with review.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    seq = lb.meta["seq"]
    out = _run(capsys, "people", "merge", "--apply-review", str(review))
    assert "merged Kari → Kari Nordmann: 1 line" in out and "merged Per Hansen → Per Hansen: 1 line" in out
    assert lb.meta["seq"] == seq + 2, "the two marked rows; `no` and blank are left alone"
    identities = resolve.identities_from(_resolutions(lb))
    assert identities[("handle", KARI_JID)].entity == KARI_A
    assert (
        identities[("phone", PER_ENTERED)].entity == PER_A and identities[("handle", PER_LID)].entity == PER_A
    )
    assert identities[("email", PER_EMAIL_SPELLED)].entity == PER_B, "unmarked, so untouched"
    assert identities[("email", LIV_WORK)].entity == LIV_B
    # the same file again: the rows applied are said and skipped, nothing written
    out = _run(capsys, "people", "merge", "--apply-review", str(review))
    assert "already merged" in out and lb.meta["seq"] == seq + 2
    assert lb.verify()[2] == []


def test_apply_review_refuses_a_row_it_cannot_place_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = duplicate_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    review = tmp_path / "review.csv"
    _run(capsys, "people", "merge", "--export-review", str(review))
    with review.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["apply"], rows[1]["apply"] = "yes", "yes"
    rows[1]["secondary_id"] = "019cadd3-6bc0-7dcd-9133-000000000fff"
    with review.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "merge", "--apply-review", str(review)])
    assert e.value.code == 2
    assert "row 3" in capsys.readouterr().err and lb.meta["seq"] == seq
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "merge", "--apply-review", str(bad)])
    assert e.value.code == 2 and "primary_id" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "merge", "--apply-review", str(tmp_path / "missing.csv")])
    assert e.value.code == 2
