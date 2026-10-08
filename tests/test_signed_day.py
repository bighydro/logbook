"""`logbook day sign YYYY-MM-DD [--note TEXT] [--confirm ID,ID]` (RFC 0034, `signed-day/v1`): the owner's
reading of a day's page, appended as one tier-1 line and rewriting nothing; `show` and `day` say in
their header whether a day is signed; a later signature supersedes; the page digest binds which lines
were on the page; and the Day's `readiness` block says per class of source whether the day is in.
Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from logbook import cli
from logbook.contrib import mcp_server
from logbook.core import readiness, signing
from logbook.core.chain import canonical_json
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-03-01"
SIGNED_AT = "2026-03-02T08:00:00Z"  # 09:00 on the 2nd, Oslo


def _location(at: str, source: str = "dawarich") -> dict[str, Any]:
    return {
        "at": at,
        "source": source,
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"{source}:{at}"},
    }


def _note(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """2026-03-01 (CET): four lines on the page, appended out of time order, and one just past
    midnight that is on the 2nd."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _location("2026-03-01T07:30:00Z"),  # seq 1: 08:30
            _note("2026-03-01T10:00:00Z", "coffee"),  # seq 2: 11:00
            _location("2026-03-01T22:59:00Z"),  # seq 3: 23:59
            _location("2026-03-01T23:30:00Z"),  # seq 4: 00:30 on the 2nd
            _note("2026-03-01T08:00:00Z", "breakfast"),  # seq 5: 09:00, appended last, second on the page
        ]
    )
    return lb


PAGE = (1, 5, 2, 3)  # the page of DAY in its order: by instant, then seq


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _fails(*args: str) -> int:
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    return int(e.value.code or 0)


def _by_seq(lb: Logbook) -> dict[int, dict[str, Any]]:
    return {int(line["seq"]): line for line in lb.lines()}


def _page_sha256(lb: Logbook, day: str, seqs: tuple[int, ...]) -> str:
    lines = _by_seq(lb)
    page = {"day": day, "tz": TZ, "lines": [lines[s]["hash"] for s in seqs]}
    return hashlib.sha256(canonical_json(page).encode("utf-8")).hexdigest()


def _files(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# -- signing ---------------------------------------------------------------------------------------------


def test_signing_appends_one_tier_1_line_and_rewrites_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    before = _files(lb.root)
    owner = lb.meta["owner_id"]
    out = _run(capsys, "day", "sign", DAY, "--note", "A quiet Sunday.")
    assert lb.meta["seq"] == 6
    line = _by_seq(lb)[6]
    assert (line["kind"], line["tier"], line["source"], line["end"]) == ("signed-day", 1, "manual", None)
    p = line["payload"]
    assert p["schema"] == "signed-day/v1" and p["day"] == DAY and p["subject"] == owner
    ids = {s: _by_seq(lb)[s]["id"] for s in PAGE}
    assert p["confirmed"] == [ids[s] for s in PAGE], "every line of the page, in the page's order"
    assert p["page"] == {"sha256": _page_sha256(lb, DAY, PAGE), "lines": 4}
    assert p["note"] == "A quiet Sunday." and "supersedes" not in p
    assert lb.verify()[2] == []
    after = _files(lb.root)
    changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
    [month_file] = sorted(changed - {Path("logbook.json")})  # the month of now, the signing moment
    assert month_file.parts[0] == "logbook" and month_file not in before, (
        "one line appended; nothing else touched"
    )
    march = Path("logbook", "2026", "03.jsonl")
    assert before[march] == after[march], "the day's own file is untouched"
    assert (
        f"{DAY}: signed" in out
        and "#6" in out
        and "4 lines confirmed" in out
        and p["page"]["sha256"][:12] in out
    )


def test_show_and_day_say_in_their_header_whether_the_day_is_signed(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    assert _run(capsys, "show", DAY).splitlines()[0] == f"{DAY}  unsigned"
    assert _run(capsys, "day", DAY).splitlines()[0] == f"{DAY}  Sunday · unsigned"
    assert json.loads(_run(capsys, "day", DAY, "--json"))["signed"] is None
    line = signing.sign(lb, DAY, at=SIGNED_AT)
    assert _run(capsys, "show", DAY).splitlines()[0] == f"{DAY}  signed 2026-03-02 09:00"
    assert _run(capsys, "day", DAY).splitlines()[0] == f"{DAY}  Sunday · signed 2026-03-02 09:00"
    signed = json.loads(_run(capsys, "day", DAY, "--json"))["signed"]
    assert signed == {
        "at": SIGNED_AT,
        "at_local": "2026-03-02T09:00:00+01:00",
        "line": line["id"],
        "seq": 6,
        "confirmed": 4,
        "lines": 4,
        "page_sha256": _page_sha256(lb, DAY, PAGE),
        "page_matches": True,
        "note": None,
        "supersedes": None,
    }
    assert _run(capsys, "show", "2026-03-02").splitlines()[0] == "2026-03-02  unsigned", (
        "the signing day itself"
    )


def test_a_signature_is_listed_on_the_day_it_was_written(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    signing.sign(lb, DAY, at=SIGNED_AT, note="Ines came for coffee.")
    rows = _run(capsys, "show", "2026-03-02").splitlines()
    assert (
        rows[-1]
        == f"  09:00  signed-day manual         signed {DAY}: 4 lines confirmed of 4 · Ines came for coffee."
    )


def test_re_signing_supersedes_and_a_retracted_signature_leaves_the_earlier_one_standing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    first = signing.sign(lb, DAY, at=SIGNED_AT)
    second = signing.sign(lb, DAY, at="2026-03-03T08:00:00Z", note="read again")
    assert second["payload"]["supersedes"] == first["id"]
    assert second["seq"] == 7 and first["seq"] == 6
    signed = json.loads(_run(capsys, "day", DAY, "--json"))["signed"]
    assert (
        signed["line"] == second["id"]
        and signed["supersedes"] == first["id"]
        and signed["note"] == "read again"
    )
    assert _run(capsys, "show", DAY).splitlines()[0] == f"{DAY}  signed 2026-03-03 09:00"
    lb.retract(7, "signed the wrong day")
    signed = json.loads(_run(capsys, "day", DAY, "--json"))["signed"]
    assert signed["line"] == first["id"], "the retracted later signature leaves the earlier one standing"
    lb.retract(6, "that one too")
    assert json.loads(_run(capsys, "day", DAY, "--json"))["signed"] is None
    assert _run(capsys, "show", DAY).splitlines()[0] == f"{DAY}  unsigned"
    assert lb.verify()[2] == []


def test_confirm_names_seqs_or_ids_on_the_page_and_refuses_anything_else(lb: Logbook, capsys):
    ids = {s: _by_seq(lb)[s]["id"] for s in range(1, 6)}
    _run(capsys, "day", "sign", DAY, "--confirm", f"5, 1,{ids[2]}")
    p = _by_seq(lb)[6]["payload"]
    assert p["confirmed"] == [ids[1], ids[5], ids[2]], "in the page's order, whatever the order typed"
    assert p["page"]["lines"] == 4
    seq = lb.meta["seq"]
    assert _fails("day", "sign", DAY, "--confirm", "4") == 2  # on the 2nd, not on this page
    assert "4" in capsys.readouterr().err
    assert _fails("day", "sign", DAY, "--confirm", "99") == 2
    assert _fails("day", "sign", DAY, "--confirm", "not-a-line") == 2
    assert _fails("day", "sign", DAY, "--confirm", "") == 2
    lb.retract(2, "not true")
    assert _fails("day", "sign", DAY, "--confirm", "2") == 2, "a retracted line is not a fact"
    assert "retracted" in capsys.readouterr().err
    assert lb.meta["seq"] == seq + 1, "the retraction; no signature was written"
    _run(capsys, "day", "sign", DAY)
    p = _by_seq(lb)[lb.meta["seq"]]["payload"]
    assert p["confirmed"] == [ids[1], ids[5], ids[3]], "by default every line of the page not retracted"
    assert p["page"]["lines"] == 4, "the retracted line is still on the page, marked"


def test_a_note_is_one_line_and_sign_needs_a_day(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    assert _fails("day", "sign", DAY, "--note", "two\nlines") == 2
    assert "one line" in capsys.readouterr().err
    assert _fails("day", "sign") == 2
    assert _fails("day", "sign", "2026-13-01") == 2
    assert _fails("day", DAY, "--note", "x") == 2, "--note belongs to sign"
    assert _fails("day", DAY, "--confirm", "1") == 2
    assert _fails("day", DAY, "extra") == 2
    assert lb.meta["seq"] == 5


def test_a_line_appended_after_signing_is_seen_as_a_page_that_no_longer_matches(lb: Logbook, capsys):
    signing.sign(lb, DAY, at=SIGNED_AT)
    lb.append(**_note("2026-03-01T12:00:00Z", "lunch, late"))
    signed = json.loads(_run(capsys, "day", DAY, "--json"))["signed"]
    assert signed["page_matches"] is False and signed["lines"] == 4
    text = _run(capsys, "day", DAY)
    assert text.splitlines()[0].endswith("signed 2026-03-02 09:00, the page has changed since")
    signing.sign(lb, DAY, at="2026-03-03T08:00:00Z")
    signed = json.loads(_run(capsys, "day", DAY, "--json"))["signed"]
    assert signed["page_matches"] is True and signed["lines"] == 5 and signed["confirmed"] == 5


def test_an_empty_day_can_be_signed(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _run(capsys, "day", "sign", "2026-03-20")
    p = _by_seq(lb)[6]["payload"]
    assert p["confirmed"] == [] and p["page"]["lines"] == 0
    assert p["page"]["sha256"] == _page_sha256(lb, "2026-03-20", ())
    assert _run(capsys, "show", "2026-03-20").splitlines()[0].startswith("2026-03-20: nothing logged")


def test_the_mcp_server_cannot_sign():
    """ARCHITECTURE: a confirmation stays with the human. No tool of the MCP server signs a day."""
    source = inspect.getsource(mcp_server)
    assert "signing" not in source and "sign_day" not in source and "signed-day" not in source


# -- property: re-signing never changes the chain head of earlier days -----------------------------------


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    signings=st.lists(
        st.tuples(st.sampled_from(["2026-03-01", "2026-03-02", "2026-03-03"]), st.booleans()), max_size=8
    )
)
def test_re_signing_never_changes_the_chain_head_of_earlier_days(signings: list[tuple[str, bool]]) -> None:
    """Three days of lines; any sequence of signings and re-signings, each written later than all
    three days: every line of those days keeps its hash, each day's last line (its head in the chain)
    stays what it was, every page digest stays what it was, and the record verifies after each."""
    with tempfile.TemporaryDirectory() as tmp:
        lb = Logbook.init(Path(tmp) / "lb", TZ)
        drafts = []
        for day in ("2026-03-01", "2026-03-02", "2026-03-03"):
            drafts += [_location(f"{day}T07:30:00Z"), _note(f"{day}T10:00:00Z", f"{day} note")]
        lb.append_many(drafts)
        before = _by_seq(lb)
        heads = {
            day: max(s for s, line in before.items() if line["at"].startswith(day))
            for day in ("2026-03-01", "2026-03-02", "2026-03-03")
        }
        with lb.index() as idx:
            pages = {day: signing.page_digest(day, TZ, signing.page(idx, day)) for day in heads}
        for n, (day, with_note) in enumerate(signings):
            line = signing.sign(
                lb, day, at=f"2026-03-10T{8 + n:02d}:00:00Z", note="again" if with_note else None
            )
            assert line["payload"]["day"] == day
            after = _by_seq(lb)
            for seq, old in before.items():
                assert after[seq]["hash"] == old["hash"] and after[seq]["prev"] == old["prev"]
            for d, seq in heads.items():
                assert after[seq]["hash"] == before[seq]["hash"], f"the head of {d} moved"
            with lb.index() as idx:
                for d, digest in pages.items():
                    assert signing.page_digest(d, TZ, signing.page(idx, d)) == digest
                standing = signing.standing(idx)
            assert standing[day]["id"] == line["id"]
            assert lb.verify()[2] == []


# -- readiness --------------------------------------------------------------------------------------------


def _ten_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Ten days with a point from the tracker, two messages and a note each; the eleventh with a
    note and a photo only: the tracker and the messages went quiet."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    drafts: list[dict[str, Any]] = []
    for n in range(1, 11):
        day = f"2026-03-{n:02d}"
        drafts.append(_location(f"{day}T07:30:00Z"))
        drafts.append(_note(f"{day}T10:00:00Z", "a note"))
        for clock in ("11:00", "12:00"):
            drafts.append(
                {
                    "at": f"{day}T{clock}:00Z",
                    "source": "whatsapp",
                    "kind": "message",
                    "tier": 2,
                    "payload": {
                        "schema": "message/v1",
                        "raw_id": f"wa:{day}:{clock}",
                        "chat": {"id": "g@g.us", "type": "group", "name": "Boat club"},
                        "from_me": False,
                        "sender": {"kind": "phone", "value": "+4790000001"},
                        "text": "hi",
                    },
                }
            )
    drafts.append(_note("2026-03-11T10:00:00Z", "quiet"))
    drafts.append(
        {
            "at": "2026-03-11T11:00:00Z",
            "source": "immich",
            "kind": "photo",
            "tier": 1,
            "payload": {"schema": "photo/v1", "raw_id": "p1", "asset_id": "p1", "library": "immich"},
        }
    )
    lb.append_many(drafts)
    return lb


def test_readiness_names_the_usual_sources_that_did_not_deliver(tmp_path: Path, monkeypatch, capsys):
    _ten_days(tmp_path, monkeypatch)
    data = json.loads(_run(capsys, "day", "2026-03-11", "--json"))
    r = data["readiness"]
    assert [c["name"] for c in r["classes"]] == [
        "mail",
        "message",
        "meeting",
        "location",
        "photo",
        "calendar",
    ]
    classes = {c["name"]: c for c in r["classes"]}
    assert classes["location"] == {
        "name": "location",
        "kinds": ["location"],
        "present": False,
        "lines": 0,
        "sources": [],
        "usual": ["dawarich"],
        "missing": ["dawarich"],
    }
    assert classes["message"]["missing"] == ["whatsapp"] and classes["message"]["present"] is False
    assert classes["photo"] == {
        "name": "photo",
        "kinds": ["photo"],
        "present": True,
        "lines": 1,
        "sources": ["immich"],
        "usual": [],
        "missing": [],
    }
    assert classes["mail"]["present"] is False and classes["mail"]["usual"] == []
    assert r["missing"] == ["message", "location"] and r["ready"] is False
    assert r["window"] == {"since": "2026-02-12", "until": "2026-03-11", "logged_days": 11}
    text = _run(capsys, "day", "2026-03-11")
    assert (
        "  readiness     mail none · message missing whatsapp · meeting none · location missing dawarich"
        " · photo present · calendar none"
    ) in text
    ready = json.loads(_run(capsys, "day", "2026-03-10", "--json"))["readiness"]
    assert ready["ready"] is True and ready["missing"] == []
    assert {c["name"]: c["present"] for c in ready["classes"]} == {
        "mail": False,
        "message": True,
        "meeting": False,
        "location": True,
        "photo": False,
        "calendar": False,
    }


def test_a_disabled_source_is_not_expected(tmp_path: Path, monkeypatch, capsys):
    lb = _ten_days(tmp_path, monkeypatch)
    policy = lb.root / "policy" / "import.json"
    policy.write_text(json.dumps({"disabled": [{"source": "whatsapp", "reason": "off"}]}), encoding="utf-8")
    r = json.loads(_run(capsys, "day", "2026-03-11", "--json"))["readiness"]
    classes = {c["name"]: c for c in r["classes"]}
    assert classes["message"]["usual"] == [] and classes["message"]["missing"] == []
    assert r["missing"] == ["location"]


def test_readiness_reads_the_record_and_the_policy_only(tmp_path: Path, monkeypatch, no_network: list[str]):
    lb = _ten_days(tmp_path, monkeypatch)
    (lb.root / "policy" / "import.json").unlink()  # a record made before the import policy
    before = _files(lb.root)
    block = readiness.read(lb, "2026-03-11")
    assert block["missing"] == ["message", "location"]
    assert no_network == []
    assert _files(lb.root) == before, "a reader writes nothing, not even the default policy"
