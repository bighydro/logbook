"""`logbook export crossing`: the crossing-package/v1 bundle (RFC 0005) under the tier policy of
ADR 0016, recorded in the chain as a crossing/v1 line (RFC 0011) with a watermark per destination.
Every string here is synthetic; the person lives in Oslo and does not exist."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
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
    location. At exactly UNTIL: a location that must not cross."""
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
    assert lb.meta["seq"] == 12


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
    assert (line["kind"], line["tier"], line["source"], line["seq"]) == ("crossing", 1, "logbook", 13)
    m = _manifest(out)
    p = line["payload"]
    assert p["schema"] == "crossing/v1"
    assert p["destination"] == "hermes"
    assert p["bundle_id"] == m["bundle_id"]
    assert p["window"] == {"from": SINCE, "to": UNTIL}
    assert p["tiers"] == [1, 2]
    assert p["counts"] == m["counts"]
    assert p["policy"] == {"file": "policy/crossing.json", "max_tier": 2}
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
    ]  # seq 13, the crossing line, is at now
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
    assert [e["seq"] for e in _jsonl(tmp_path / "out" / "entries.jsonl")] == [5, 11, 12]


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
