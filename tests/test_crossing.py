"""`logbook export crossing`: the crossing-package/v1 bundle (RFC 0005) under the tier policy of
ADR 0016, recorded in the chain as a crossing/v1 line (RFC 0011) with a watermark per destination.
Every string here is synthetic; the person lives in Oslo and does not exist."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import crossing, signing
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
PERSON_A = "019cadd3-6bc0-7dcd-9133-043f5aabf2a9"
PERSON_B = "019cadd3-6bc0-7dcd-9133-043f5aabf2aa"
PHONE_A, PHONE_B = "+4790000001", "+4790000002"
LID = "236000000000001@lid"
EMAIL_B = "kari@example.org"
SHA_PRESENT = hashlib.sha256(b"three").hexdigest()
SHA_MISSING = "b" * 64
SINCE, UNTIL = "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"
SIGNED_AT = "2026-03-03T08:00:00Z"  # the two signatures (seq 13 and 14), written on the 3rd


def _location(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"trk:{at}"},
    }


def _note(at: str, text: str, tier: int = 2) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": tier,
        "payload": {"schema": "note/v1", "text": text},
    }


def _message(at: str, sender: dict[str, str], media: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"wa:{at}",
        "chat": {"id": "group@g.us", "type": "group", "name": "Boat club"},
        "from_me": False,
        "sender": sender,
        "text": "mooring photos sent",
    }
    if media is not None:
        payload["media"] = media
    return {"at": at, "source": "whatsapp", "kind": "message", "tier": 2, "payload": payload}


def _resolution(kind: str, value: str, label: str, entity: str) -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:00:00Z",  # before the window: the overlay is what carries it across
        "source": "ios-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": kind, "value": value},
            "entity": {"type": "person", "id": entity, "registry": "logbook"},
            "label": label,
            "method": "exact",
        },
    }


def _alias(kind: str, value: str, target: tuple[str, str]) -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:05:00Z",
        "source": "whatsapp-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": kind, "value": value},
            "alias_of": {"kind": target[0], "value": target[1]},
            "method": "exact",
        },
    }


def _ref(sha256: str) -> dict[str, Any]:
    return {"sha256": sha256, "path": f"attachments/{sha256}", "bytes": 5, "media_type": "text/plain"}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """One local day, 2026-03-01, in the window [SINCE, UNTIL): two tier-1 locations, a tier-2 note,
    a tier-3 note, a tier-2 message from a lid whose alias resolves through a phone to Ola, a tier-2
    message with a present attachment and one with a missing attachment. Before the window: the
    resolutions (Ola's phone, the lid alias, and Kari, whom nothing in the window mentions) and a
    location. At exactly UNTIL: a location that must not cross. Both days are signed (RFC 0034), on
    the 3rd, so the crossing's default gate lets them through."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    store = lb.root / "attachments"
    store.mkdir()
    (store / SHA_PRESENT).write_bytes(b"three")
    lb.append_many(
        [
            _resolution("phone", PHONE_A, "Ola Nordmann", PERSON_A),  # seq 1
            _alias("handle", LID, ("phone", PHONE_A)),  # seq 2
            _resolution("email", EMAIL_B, "Kari Nordmann", PERSON_B),  # seq 3
            _location("2026-02-28T23:59:59Z"),  # seq 4: before the window
            _location(SINCE),  # seq 5: the window is closed at the start
            _note("2026-03-01T08:00:00Z", "coffee by the harbour"),  # seq 6: tier 2
            _note("2026-03-01T09:00:00Z", "paid the boat insurance", tier=3),  # seq 7: tier 3
            _message("2026-03-01T10:00:00Z", {"kind": "handle", "value": LID}),  # seq 8: names Ola via alias
            _message("2026-03-01T11:00:00Z", {"kind": "phone", "value": PHONE_B}, _ref(SHA_PRESENT)),  # seq 9
            _message(
                "2026-03-01T12:00:00Z", {"kind": "phone", "value": PHONE_B}, _ref(SHA_MISSING)
            ),  # seq 10
            _location("2026-03-01T13:00:00Z"),  # seq 11
            _location(UNTIL),  # seq 12: open at the end
        ]
    )
    signing.sign(lb, "2026-03-01", at=SIGNED_AT)  # seq 13
    signing.sign(lb, "2026-03-02", at=SIGNED_AT)  # seq 14
    return lb


def _run(*args: str) -> None:
    cli.main(["export", "crossing", *args])


def _fails(*args: str) -> int:
    with pytest.raises(SystemExit) as e:
        _run(*args)
    return int(e.value.code or 0)


def _manifest(out: Path) -> dict[str, Any]:
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def _policy(lb: Logbook, max_tier: int, destination: str = "hermes") -> Path:
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({destination: {"max_tier": max_tier}}), encoding="utf-8")
    return path


# -- policy (ADR 0016) -------------------------------------------------------------------------


def test_init_writes_the_default_policy(tmp_path: Path):
    lb = Logbook.init(tmp_path / "fresh", TZ)
    policy = json.loads((lb.root / "policy" / "crossing.json").read_text(encoding="utf-8"))
    assert policy == {"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}}


def test_first_export_writes_the_default_policy_when_missing(lb: Logbook, tmp_path: Path):
    (lb.root / "policy" / "crossing.json").unlink()  # a record made before ADR 0016
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(tmp_path / "out"))
    policy = json.loads((lb.root / "policy" / "crossing.json").read_text(encoding="utf-8"))
    assert policy == {"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}}


def test_request_above_the_ceiling_is_refused_naming_the_file(lb: Logbook, tmp_path: Path, capsys):
    path = _policy(lb, 1)
    assert _fails("--to", "hermes", "--since", SINCE, "--tier", "1,2", "--out", str(tmp_path / "out")) == 2
    err = capsys.readouterr().err
    assert str(path) in err and "max_tier" in err
    assert not (tmp_path / "out").exists()
    assert lb.meta["seq"] == 14


def test_unknown_destination_is_refused_naming_the_file(lb: Logbook, tmp_path: Path, capsys):
    path = _policy(lb, 2)
    assert _fails("--to", "athena", "--since", SINCE, "--out", str(tmp_path / "out")) == 2
    assert str(path) in capsys.readouterr().err


def test_tier_3_is_refused_without_the_explicit_flag_even_when_policy_allows(lb: Logbook, tmp_path: Path):
    _policy(lb, 3)
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(tmp_path / "a"))
    tiers = {e["tier"] for e in _jsonl(tmp_path / "a" / "entries.jsonl")}
    assert tiers == {1, 2}
    assert _manifest(tmp_path / "a")["policy"]["tiers"]["3"] == "never"


def test_tier_3_needs_both_the_policy_and_the_flag(lb: Logbook, tmp_path: Path, capsys):
    _policy(lb, 2)
    code = _fails("--to", "hermes", "--since", SINCE, "--tier", "1,2,3", "--out", str(tmp_path / "out"))
    assert code == 2
    assert "policy" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_tier_3_crosses_only_with_policy_and_flag_and_says_so_loudly(lb: Logbook, tmp_path: Path, capsys):
    _policy(lb, 3)
    _run(
        "--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2,3", "--out", str(tmp_path / "a")
    )
    entries = _jsonl(tmp_path / "a" / "entries.jsonl")
    assert [e["seq"] for e in entries if e["tier"] == 3] == [7]
    m = _manifest(tmp_path / "a")
    assert m["tier3"]["lines"] == 1 and "TIER-3" in m["tier3"]["warning"]
    assert m["policy"]["tiers"]["3"] == "explicit"
    assert "TIER-3" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["2", "3", "1,3", "2,3", "0", "x", ""])
def test_tier_must_be_1_or_1_2_or_1_2_3(lb: Logbook, tmp_path: Path, bad: str, capsys):
    assert _fails("--to", "hermes", "--since", SINCE, "--tier", bad, "--out", str(tmp_path / "out")) == 2
    assert "--tier must be 1, 1,2 or 1,2,3" in capsys.readouterr().err


# -- the window and the bundle (RFC 0005) ------------------------------------------------------


def test_tier_1_crosses_by_default_and_the_window_is_half_open(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out))
    entries = _jsonl(out / "entries.jsonl")
    assert [e["seq"] for e in entries] == [5, 11]  # tier 1 only; seq 4 is before, seq 12 is at UNTIL
    lines = {line["seq"]: line for line in lb.lines()}
    assert entries[0] == lines[5]  # verbatim: the standard envelope, hash included
    m = _manifest(out)
    assert m["schema"] == "crossing-package/v1"
    assert m["recipient"] == "hermes"
    assert m["owner"] == lb.meta["owner_id"]
    assert m["covers"] == {"from": SINCE, "to": UNTIL}
    assert m["tiers"] == [1]
    assert m["entries_file"] == "entries.jsonl"
    assert m["counts"]["logged"] == 7 and m["counts"]["crossed"] == 2 and m["counts"]["held_back"] == 5
    assert m["counts"]["held_back_unsigned"] == 0
    assert m["policy"]["signed_days"] == "only"
    assert m["counts"]["by_tier"] == {"1": 2, "2": 0, "3": 0}
    assert m["counts"]["by_kind"] == {"location": 2}
    assert m["tool"]["version"] == cli.__version__
    assert "review" not in m and "tier3" not in m
    assert "resolution_file" not in m  # a location names nobody
    assert sorted(p.name for p in out.iterdir()) == ["entries.jsonl", "manifest.json"]


def test_logbook_head_is_the_head_before_the_crossing_line(lb: Logbook, tmp_path: Path):
    before = lb.meta["head"]
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(tmp_path / "out"))
    assert _manifest(tmp_path / "out")["logbook_head"] == before


def test_tier_2_review_section_lists_the_tier_2_lines(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    m = _manifest(out)
    lines = {line["seq"]: line for line in lb.lines()}
    assert [e["seq"] for e in _jsonl(out / "entries.jsonl")] == [5, 6, 8, 9, 10, 11]
    assert m["review"] == [  # every tier-2 line in the package: the entries, then the overlay
        {"id": lines[s]["id"], "kind": lines[s]["kind"], "source": lines[s]["source"], "at": lines[s]["at"]}
        for s in (6, 8, 9, 10, 1, 2)
    ]
    assert m["policy"]["tiers"] == {"1": "auto", "2": "reviewed", "3": "never"}
    assert m["counts"]["by_tier"] == {"1": 2, "2": 4, "3": 0}


def test_kinds_filter(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run(
        "--to",
        "hermes",
        "--since",
        SINCE,
        "--until",
        UNTIL,
        "--tier",
        "1,2",
        "--kinds",
        "note",
        "--out",
        str(out),
    )
    assert [e["seq"] for e in _jsonl(out / "entries.jsonl")] == [6]
    assert _manifest(out)["counts"]["by_kind"] == {"note": 1}


def test_a_retracted_line_is_held_back(lb: Logbook, tmp_path: Path):
    lb.retract(6, "not for anyone")
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    assert 6 not in [e["seq"] for e in _jsonl(out / "entries.jsonl")]


# -- resolution overlay (RFC 0006) ------------------------------------------------------------


def test_resolutions_the_exported_refs_resolve_through_cross_including_alias_hops(
    lb: Logbook, tmp_path: Path
):
    out = tmp_path / "out"
    _run(
        "--to",
        "hermes",
        "--since",
        SINCE,
        "--until",
        UNTIL,
        "--tier",
        "1,2",
        "--kinds",
        "message",
        "--out",
        str(out),
    )
    m = _manifest(out)
    assert m["resolution_file"] == "resolution.jsonl"
    overlay = _jsonl(out / "resolution.jsonl")
    assert [r["seq"] for r in overlay] == [1, 2]  # Ola's phone and the lid alias; never Kari (seq 3)
    lines = {line["seq"]: line for line in lb.lines()}
    assert overlay[0] == lines[1]
    assert m["counts"]["resolutions"] == 2


def test_resolution_overlay_never_crosses_above_the_requested_tier(lb: Logbook, tmp_path: Path):
    """A resolution is tier 2 (RFC 0006); at --tier 1 it stays home, and the manifest says so."""
    lb.append(**_message("2026-03-01T14:00:00Z", {"kind": "phone", "value": PHONE_A}) | {"tier": 1})
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out))
    assert not (out / "resolution.jsonl").exists()
    m = _manifest(out)
    assert "resolution_file" not in m
    assert m["counts"]["resolutions"] == 0 and m["counts"]["resolutions_held_back"] == 1


# -- attachments (SPEC §1.1) -----------------------------------------------------------------


def test_present_attachments_are_copied_and_missing_ones_stay_references(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    assert (out / "attachments" / SHA_PRESENT).read_bytes() == b"three"
    assert not (out / "attachments" / SHA_MISSING).exists()
    m = _manifest(out)
    assert m["blobs"] == [
        {"sha256": SHA_PRESENT, "path": f"attachments/{SHA_PRESENT}", "bytes": 5, "media_type": "text/plain"}
    ]
    assert m["counts"]["attachments"] == {"included": 1, "bytes": 5, "missing": 1}
    entries = {e["seq"]: e for e in _jsonl(out / "entries.jsonl")}
    assert entries[10]["payload"]["media"]["sha256"] == SHA_MISSING  # the reference is kept verbatim


# -- dry run ---------------------------------------------------------------------------------


def test_dry_run_prints_counts_and_writes_nothing(lb: Logbook, tmp_path: Path, capsys):
    (
        lb.root / "policy" / "crossing.json"
    ).unlink()  # a record made before ADR 0016: a dry run writes no default
    head, seq = lb.meta["head"], lb.meta["seq"]
    out = tmp_path / "out"
    _run(
        "--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out), "--dry-run"
    )
    text = capsys.readouterr().out
    assert "dry run" in text and "nothing written" in text
    assert "location" in text and "note" in text and "message" in text
    assert "tier 1" in text and "tier 2" in text
    assert "5 bytes" in text  # attachments that would be copied
    assert "max_tier" in text and "hermes" in text  # the policy that would apply
    assert not out.exists()
    assert (lb.meta["head"], lb.meta["seq"]) == (head, seq)
    assert not (lb.root / "exports").exists()
    assert not (lb.root / "policy" / "crossing.json").exists()


# -- the crossing line (RFC 0011) and the watermark ----------------------------------------------


def test_a_real_export_appends_one_crossing_line_and_the_chain_stays_valid(lb: Logbook, tmp_path: Path):
    head = lb.meta["head"]
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    _seq, _head, errors = lb.verify()
    assert errors == []
    line = list(lb.lines())[-1]
    assert (line["kind"], line["tier"], line["source"], line["seq"]) == ("crossing", 1, "logbook", 15)
    m = _manifest(out)
    p = line["payload"]
    assert p["schema"] == "crossing/v1"
    assert p["destination"] == "hermes"
    assert p["bundle_id"] == m["bundle_id"]
    assert p["window"] == {"from": SINCE, "to": UNTIL}
    assert p["tiers"] == [1, 2]
    assert p["counts"] == m["counts"]
    assert p["policy"] == {"file": "policy/crossing.json", "max_tier": 2, "signed_only": True}
    assert p["logbook_head"] == head
    assert p["package_sha256"] == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()
    assert line["at"] == m["generated_at"]


def test_every_digest_is_of_the_bytes_on_disk_even_where_text_mode_writes_crlf(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Windows text mode turns every written newline into CRLF; a digest taken from the string
    instead of the bytes then names a manifest that does not exist. Simulated on every OS."""
    real_open = Path.open

    def crlf_open(self: Path, mode: str = "r", buffering: int = -1, encoding=None, errors=None, newline=None):  # type: ignore[no-untyped-def]
        if "b" not in mode and newline is None and any(c in mode for c in "wax"):
            newline = "\r\n"
        return real_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", crlf_open)
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    m = _manifest(out)
    p = list(lb.lines())[-1]["payload"]
    assert p["package_sha256"] == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()
    assert m["entries_sha256"] == hashlib.sha256((out / "entries.jsonl").read_bytes()).hexdigest()
    assert m["resolution_sha256"] == hashlib.sha256((out / "resolution.jsonl").read_bytes()).hexdigest()


def test_watermark_round_trip(lb: Logbook, tmp_path: Path):
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(tmp_path / "a"))
    mark = json.loads((lb.root / "exports" / "crossing.json").read_text(encoding="utf-8"))
    assert mark["hermes"]["until"] == UNTIL
    _run("--to", "hermes", "--since", "last", "--until", "2026-03-03T00:00:00Z", "--out", str(tmp_path / "b"))
    m = _manifest(tmp_path / "b")
    assert m["covers"] == {"from": UNTIL, "to": "2026-03-03T00:00:00Z"}
    assert [e["seq"] for e in _jsonl(tmp_path / "b" / "entries.jsonl")] == [
        12
    ]  # the signatures are on the 3rd; seq 15, the crossing line, is at now
    mark = json.loads((lb.root / "exports" / "crossing.json").read_text(encoding="utf-8"))
    assert mark["hermes"]["until"] == "2026-03-03T00:00:00Z"


def test_since_last_without_a_watermark_is_a_clear_error(lb: Logbook, tmp_path: Path, capsys):
    assert _fails("--to", "hermes", "--since", "last", "--out", str(tmp_path / "out")) == 2
    err = capsys.readouterr().err
    assert "exports" in err and "--since" in err


def test_until_defaults_to_now_and_a_backwards_window_is_refused(lb: Logbook, tmp_path: Path):
    assert _fails("--to", "hermes", "--since", UNTIL, "--until", SINCE, "--out", str(tmp_path / "out")) == 2
    _run("--to", "hermes", "--since", SINCE, "--out", str(tmp_path / "out"))
    m = _manifest(tmp_path / "out")
    assert m["covers"]["to"] == m["generated_at"]
    assert [e["seq"] for e in _jsonl(tmp_path / "out" / "entries.jsonl")] == [5, 11, 12, 13, 14]


def test_out_defaults_under_the_record(lb: Logbook):
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL)
    base = lb.root / "export" / "crossing" / "hermes"
    made = list(base.iterdir())
    assert len(made) == 1 and (made[0] / "manifest.json").exists()


def test_an_empty_window_is_a_quiet_no_op(lb: Logbook, tmp_path: Path, capsys):
    """`--since last` twice in one second: nothing to cross, nothing written, exit 0 (for a nightly job)."""
    seq = lb.meta["seq"]
    _run("--to", "hermes", "--since", SINCE, "--until", SINCE, "--out", str(tmp_path / "out"))
    assert "nothing to cross" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()
    assert lb.meta["seq"] == seq
    assert not (lb.root / "exports").exists()


# -- the signed-day gate (RFC 0034 rule 5) -----------------------------------------------------------


def _quiet_day(lb: Logbook) -> None:
    """2026-03-05, unsigned: a location and a note; and a location on the 3rd, the signing day,
    which is unsigned too."""
    lb.append_many(
        [
            _location("2026-03-03T10:00:00Z"),  # seq 15
            _location("2026-03-05T10:00:00Z"),  # seq 16
            _note("2026-03-05T11:00:00Z", "an unread day"),  # seq 17
        ]
    )


def test_only_the_lines_of_signed_days_cross_by_default(lb: Logbook, tmp_path: Path, capsys):
    _quiet_day(lb)
    out = tmp_path / "out"
    _run(
        "--to",
        "hermes",
        "--since",
        SINCE,
        "--until",
        "2026-03-06T00:00:00Z",
        "--tier",
        "1,2",
        "--out",
        str(out),
    )
    seqs = [e["seq"] for e in _jsonl(out / "entries.jsonl")]
    assert seqs == [5, 6, 8, 9, 10, 11, 12, 13, 14], (
        "the 1st and the 2nd, and their signatures; never the 3rd or the 5th"
    )
    m = _manifest(out)
    assert m["policy"]["signed_days"] == "only"
    assert m["counts"]["logged"] == 13 and m["counts"]["crossed"] == 9 and m["counts"]["held_back"] == 4
    assert m["counts"]["held_back_unsigned"] == 3, "seq 15, 16 and 17; seq 7 is tier 3"
    text = capsys.readouterr().out
    assert "3 held back on unsigned days" in text and "--unsigned" in text
    line = list(lb.lines())[-1]
    assert line["payload"]["policy"]["signed_only"] is True
    assert line["payload"]["counts"]["held_back_unsigned"] == 3


def test_unsigned_lifts_the_gate(lb: Logbook, tmp_path: Path, capsys):
    _quiet_day(lb)
    out = tmp_path / "out"
    _run(
        "--to",
        "hermes",
        "--since",
        SINCE,
        "--until",
        "2026-03-06T00:00:00Z",
        "--tier",
        "1,2",
        "--unsigned",
        "--out",
        str(out),
    )
    seqs = [e["seq"] for e in _jsonl(out / "entries.jsonl")]
    assert seqs == [5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    m = _manifest(out)
    assert m["policy"]["signed_days"] == "any" and m["counts"]["held_back_unsigned"] == 0
    assert list(lb.lines())[-1]["payload"]["policy"]["signed_only"] is False
    assert "unsigned days" not in capsys.readouterr().out


def test_a_retracted_signature_closes_the_gate_again(lb: Logbook, tmp_path: Path):
    lb.retract(14, "not read after all")  # the 2nd is unsigned again
    out = tmp_path / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", "2026-03-04T00:00:00Z", "--out", str(out))
    seqs = [e["seq"] for e in _jsonl(out / "entries.jsonl")]
    assert seqs == [5, 11, 13], "seq 12 is on the 2nd; seq 14 is retracted"
    assert _manifest(out)["counts"]["held_back_unsigned"] == 1, (
        "seq 12; the retracted signature is held as retracted"
    )


def test_dry_run_counts_the_unsigned_days(lb: Logbook, tmp_path: Path, capsys):
    _quiet_day(lb)
    _run("--to", "hermes", "--since", SINCE, "--until", "2026-03-06T00:00:00Z", "--dry-run")
    text = capsys.readouterr().out
    assert "2 held back on unsigned days" in text and "--unsigned" in text
    assert not (lb.root / "export").exists()


def test_dispositions_cross_with_the_signature_unchanged(lb: Logbook, tmp_path: Path):
    """RFC 0034 amendment 1: a signature's `dispositions` cross as written, with the day they sign."""
    by_seq = {int(line["seq"]): line for line in lb.lines()}
    again = signing.sign(
        lb,
        "2026-03-01",
        at="2026-03-03T09:00:00Z",
        dispositions={"kept": [by_seq[6]["id"]], "missed": [by_seq[8]["id"]], "carried": ["11"]},
    )  # seq 15: supersedes seq 13
    expected = {by_seq[6]["id"]: "kept", by_seq[8]["id"]: "missed", by_seq[11]["id"]: "carried"}
    assert again["payload"]["dispositions"] == expected
    out = tmp_path / "out"
    until = "2026-03-04T00:00:00Z"  # the signing day inside the window
    _run("--to", "hermes", "--since", SINCE, "--until", until, "--tier", "1,2", "--out", str(out))
    entries = {int(e["seq"]): e for e in _jsonl(out / "entries.jsonl")}
    assert 15 in entries and 13 in entries, "both signatures of the day cross with it"
    assert entries[15] == again, "the line crosses byte for byte: the dispositions untouched"
    assert entries[15]["payload"]["dispositions"] == again["payload"]["dispositions"]
    assert signing.validate(entries[15]["payload"]) == []


def test_a_signature_that_confirms_nothing_still_opens_the_gate_and_crosses(lb: Logbook, tmp_path: Path):
    """RFC 0034 amendment 2: `--confirm none` signs the day with an empty `confirmed`; the day is
    signed, so its lines cross, and the signature crosses with them, the empty list as written."""
    again = signing.sign(lb, "2026-03-01", at="2026-03-03T09:00:00Z", confirm=[])  # seq 15: supersedes 13
    assert again["payload"]["confirmed"] == []
    out = tmp_path / "out"
    until = "2026-03-04T00:00:00Z"  # the signing day inside the window
    _run("--to", "hermes", "--since", SINCE, "--until", until, "--tier", "1,2", "--out", str(out))
    entries = {int(e["seq"]): e for e in _jsonl(out / "entries.jsonl")}
    assert [s for s in entries if s < 13] == [5, 6, 8, 9, 10, 11, 12], "the day's lines cross: it is signed"
    assert 15 in entries and entries[15] == again, "the signature crosses byte for byte"
    assert entries[15]["payload"]["confirmed"] == []
    assert signing.validate(entries[15]["payload"]) == []
    assert _manifest(out)["counts"]["held_back_unsigned"] == 0


# -- the output directory: every bundle is built fresh, and only what the selection names is in it -----


def _on_disk(folder: Path) -> dict[str, bytes]:
    """Every file under `folder` by its path relative to it, `/`-separated whatever the platform."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _matches_its_manifest(out: Path) -> dict[str, Any]:
    """The folder holds exactly the files its manifest lists, each with the digest and size it names,
    and the manifest itself; nothing else."""
    m = _manifest(out)
    files = _on_disk(out)
    listed = {f["path"]: f for f in m["files"]}
    assert set(files) == {"manifest.json", *listed}, "a file the manifest does not list, or one missing"
    assert [f["path"] for f in m["files"]] == sorted(listed), "listed once each, in path order"
    for path, entry in listed.items():
        assert entry["bytes"] == len(files[path])
        assert entry["sha256"] == hashlib.sha256(files[path]).hexdigest()
    return m


def test_the_manifest_lists_every_file_in_the_package(lb: Logbook, tmp_path: Path):
    out = tmp_path / "given" / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    m = _matches_its_manifest(out)
    paths = [f["path"] for f in m["files"]]
    assert paths == [f"attachments/{SHA_PRESENT}", "entries.jsonl", "resolution.jsonl"]
    by_path = {f["path"]: f for f in m["files"]}
    assert by_path["entries.jsonl"]["sha256"] == m["entries_sha256"]
    assert by_path["resolution.jsonl"]["sha256"] == m["resolution_sha256"]
    assert by_path[f"attachments/{SHA_PRESENT}"]["sha256"] == SHA_PRESENT


def test_a_narrower_export_into_the_same_folder_leaves_nothing_of_the_broader_one(
    lb: Logbook, tmp_path: Path
):
    """The reviewer's finding: a broad unsigned crossing into a folder, then a tier-1 crossing into the
    same folder, left the first one's resolution.jsonl and tier-2 attachment beside a manifest that
    said there were none. Handing the folder over would have disclosed what the second one excluded."""
    out = tmp_path / "given" / "out"
    broad = ("--tier", "1,2", "--unsigned")
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, *broad, "--out", str(out))
    assert (out / "resolution.jsonl").exists() and (out / "attachments" / SHA_PRESENT).exists()
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out))
    m = _matches_its_manifest(out)
    assert sorted(_on_disk(out)) == ["entries.jsonl", "manifest.json"]
    assert not (out / "attachments").exists(), "not even the empty folder"
    assert m["counts"]["attachments"] == {"included": 0, "bytes": 0, "missing": 0}
    assert [e["seq"] for e in _jsonl(out / "entries.jsonl")] == [5, 11]
    assert sorted(p.name for p in out.parent.iterdir()) == ["out"], "no staging folder left beside it"
    payload = list(lb.lines())[-1]["payload"]
    assert payload["package_sha256"] == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()


def test_an_earlier_bundle_with_files_of_its_own_added_is_still_replaced_whole(lb: Logbook, tmp_path: Path):
    """A folder with a crossing manifest is ours to replace, whatever else was put in it since."""
    out = tmp_path / "given" / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    (out / "attachments" / "notes.txt").write_bytes(b"Ola's list for the boat\n")
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out))
    assert sorted(_on_disk(out)) == ["entries.jsonl", "manifest.json"]
    _matches_its_manifest(out)


def _foreign(out: Path, what: str) -> dict[str, bytes]:
    """A target that holds something other than a bundle of ours; what was there, to compare after."""
    out.parent.mkdir()
    if what == "a file":
        out.write_bytes(b"Ines' packing list\n")
        return {".": out.read_bytes()}
    out.mkdir()
    if what == "a folder of notes":
        (out / "notes").mkdir()
        (out / "notes" / "harbour.md").write_bytes(b"# Aker brygge\n")
    elif what == "another manifest":
        (out / "manifest.json").write_bytes(b'{"name": "a web app"}\n')
    elif what == "a manifest that is not JSON":
        (out / "manifest.json").write_bytes(b"not json\n")
    return _on_disk(out)


FOREIGN = ["a file", "a folder of notes", "another manifest", "a manifest that is not JSON"]


@pytest.mark.parametrize("what", FOREIGN)
def test_a_target_that_is_not_a_bundle_of_ours_is_refused(lb: Logbook, tmp_path: Path, what: str, capsys):
    out = tmp_path / "given" / "out"
    before = _foreign(out, what)
    code = _fails("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out))
    assert code == 2
    err = capsys.readouterr().err
    assert str(out) in err and "--force" in err
    after = {".": out.read_bytes()} if out.is_file() else _on_disk(out)
    assert after == before, "untouched"
    assert lb.meta["seq"] == 14, "no crossing line"
    assert not (lb.root / "exports").exists(), "no watermark"
    assert sorted(p.name for p in out.parent.iterdir()) == ["out"]


@pytest.mark.parametrize("what", FOREIGN)
def test_force_replaces_a_target_that_is_not_a_bundle_of_ours(lb: Logbook, tmp_path: Path, what: str):
    out = tmp_path / "given" / "out"
    _foreign(out, what)
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out), "--force")
    assert sorted(_on_disk(out)) == ["entries.jsonl", "manifest.json"]
    _matches_its_manifest(out)
    assert lb.meta["seq"] == 15
    assert sorted(p.name for p in out.parent.iterdir()) == ["out"]


def test_an_empty_folder_and_a_missing_one_are_written_as_before(lb: Logbook, tmp_path: Path):
    empty = tmp_path / "given" / "empty"
    empty.mkdir(parents=True)
    deep = tmp_path / "given" / "a" / "b" / "out"  # its parents are made, as they always were
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(empty))
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(deep))
    for out in (empty, deep):
        assert sorted(_on_disk(out)) == ["entries.jsonl", "manifest.json"]
        _matches_its_manifest(out)
    assert sorted(p.name for p in empty.parent.iterdir()) == ["a", "empty"]
    assert sorted(p.name for p in deep.parent.iterdir()) == ["out"]


def test_a_failed_export_leaves_the_earlier_bundle_as_it_was(lb: Logbook, tmp_path: Path, capsys):
    """A store file that no longer hashes to its name stops the second export while it copies; the
    first bundle is still there byte for byte, nothing half-written beside it, no line appended."""
    out = tmp_path / "given" / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    before, seq = _on_disk(out), lb.meta["seq"]
    (lb.root / "attachments" / SHA_PRESENT).write_bytes(b"thrEE")
    again = ("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    assert _fails(*again) == 1
    assert "does not hash to its name" in capsys.readouterr().err
    assert _on_disk(out) == before
    assert lb.meta["seq"] == seq
    assert sorted(p.name for p in out.parent.iterdir()) == ["out"]


def test_a_package_that_does_not_match_its_manifest_is_never_put_in_place(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    """The staged folder is checked against its manifest before the rename: a list that leaves a file
    out (here, by a fault put in on purpose) stops the export with the earlier bundle untouched."""
    out = tmp_path / "given" / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out))
    before, seq = _on_disk(out), lb.meta["seq"]
    listing = crossing._listing
    monkeypatch.setattr(crossing, "_listing", lambda folder, paths: listing(folder, list(paths)[1:]))
    assert _fails("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out)) == 1
    assert "entries.jsonl is in the package and not in its manifest" in capsys.readouterr().err
    assert _on_disk(out) == before and lb.meta["seq"] == seq
    assert sorted(p.name for p in out.parent.iterdir()) == ["out"]


def test_verify_package_names_a_file_missing_or_added(lb: Logbook, tmp_path: Path):
    out = tmp_path / "given" / "out"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    assert crossing.verify_package(out) == _manifest(out)
    (out / "attachments" / "extra.bin").write_bytes(b"\x00")
    with pytest.raises(crossing.CrossingError) as e:
        crossing.verify_package(out)
    assert str(out / "attachments" / "extra.bin") in str(e.value) and "not in its manifest" in str(e.value)
    (out / "attachments" / "extra.bin").unlink()
    (out / "resolution.jsonl").unlink()
    with pytest.raises(crossing.CrossingError) as e:
        crossing.verify_package(out)
    assert str(out / "resolution.jsonl") in str(e.value) and "not in the package" in str(e.value)


@pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs a privilege on Windows")
def test_a_link_to_an_earlier_bundle_still_names_the_new_one(lb: Logbook, tmp_path: Path):
    """`--out` a symbolic link: the folder it names is replaced, beside that folder, and the link kept."""
    real = tmp_path / "given" / "real"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(real))
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(link))
    assert link.is_symlink() and link.resolve() == real.resolve()
    assert sorted(_on_disk(real)) == ["entries.jsonl", "manifest.json"]
    _matches_its_manifest(real)
    assert sorted(p.name for p in real.parent.iterdir()) == ["real"]


WHERE = ["the record", "its attachment store", "its log", "a new folder in it", "a folder that holds it"]


@pytest.mark.parametrize("where", WHERE)
def test_the_record_is_never_replaced_even_under_force(lb: Logbook, tmp_path: Path, where: str, capsys):
    """Replacing a target removes what was there, so the record, a folder of it outside `export/` (one
    not there yet too, so that a second run is not the first to be refused), and a folder that holds it
    are refused whatever the flags; nothing of the record is touched."""
    out = {
        "the record": lb.root,
        "its attachment store": lb.root / "attachments",
        "its log": lb.root / "logbook",
        "a new folder in it": lb.root / "handover",
        "a folder that holds it": tmp_path,
    }[where]
    (lb.root / "manifest.json").write_bytes(  # an export into the root before this fix left one there
        json.dumps({"schema": "crossing-package/v1"}).encode("utf-8")
    )
    before = _on_disk(lb.root)
    assert _fails("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out), "--force") == 2
    err = capsys.readouterr().err
    assert str(out) in err and "record" in err
    assert _on_disk(lb.root) == before
    assert lb.verify()[2] == [] and lb.meta["seq"] == 14
    assert not any(p.name.startswith(f".{out.name}.") for p in out.parent.iterdir()), "no staging folder"


def test_a_bundle_under_the_records_export_folder_is_replaced_as_anywhere(lb: Logbook):
    out = lb.root / "export" / "for-hermes"
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--tier", "1,2", "--out", str(out))
    _run("--to", "hermes", "--since", SINCE, "--until", UNTIL, "--out", str(out))
    assert sorted(_on_disk(out)) == ["entries.jsonl", "manifest.json"]
    _matches_its_manifest(out)
