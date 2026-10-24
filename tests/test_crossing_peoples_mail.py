"""The crossing sends people's mail only (RFC 0045 §6): a mail no person the record names is on stays
home and is counted as `mail_held_back`; `--all-mail` sends every mail as before and the manifest says
so; every other kind's bundle is byte for byte what it was. Every string here is synthetic; the people
live in Oslo and do not exist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import crossing, signing
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
SINCE, UNTIL = "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"
OWNER_EMAIL, KARI_EMAIL, PER_EMAIL = "ines@example.org", "kari@example.org", "per@example.org"
HARBOUR_EMAIL, NO_REPLY_EMAIL = "harbour@example.org", "no-reply@harbour.example.org"
KARI, PER, HARBOUR = (
    "019cadd3-6bc0-7dcd-9133-043f5aabf2b1",
    "019cadd3-6bc0-7dcd-9133-043f5aabf2b2",
    "019cadd3-6bc0-7dcd-9133-043f5aabf2b3",
)
KARI_PHONE = "+447700900101"


def _resolution(
    value: str, label: str, entity: str, type_: str = "person", kind: str = "email"
) -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:00:00Z",
        "source": "ios-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": kind, "value": value},
            "entity": {"type": type_, "id": entity, "registry": "logbook"},
            "label": label,
            "method": "exact",
        },
    }


def _mail(at: str, sender: str, to: str, direction: str = "received") -> dict[str, Any]:
    return {
        "at": at,
        "source": "mail",
        "kind": "mail",
        "tier": 2,
        "payload": {
            "schema": "mail/v1",
            "raw_id": f"m-{at}@mail.example.org",
            "thread": f"m-{at}@mail.example.org",
            "subject": "Berth 14",
            "direction": direction,
            "from": {"email": sender},
            "to": [{"email": to}],
            "size": 1024,
        },
    }


def _note(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


def _message(at: str) -> dict[str, Any]:
    payload = {
        "schema": "message/v1",
        "raw_id": f"wa:{at}",
        "chat": {"id": "kari-chat", "type": "direct", "name": "Kari"},
        "from_me": False,
        "sender": {"kind": "phone", "value": KARI_PHONE},
        "text": "see you at the boat",
    }
    return {"at": at, "source": "whatsapp", "kind": "message", "tier": 2, "payload": payload}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """One signed day, 2026-03-01: a note, a message from Kari, and five mails: from Kari, sent to
    Per, from a no-reply address, from the harbour (a company), sent to the harbour."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([OWNER_EMAIL])
    lb.append_many(
        [
            _resolution(KARI_EMAIL, "Kari Nordmann", KARI),
            _resolution(KARI_PHONE, "Kari Nordmann", KARI, kind="phone"),
            _resolution(PER_EMAIL, "Per Hansen", PER),
            _resolution(HARBOUR_EMAIL, "Oslo Harbour", HARBOUR, type_="company"),
            _note("2026-03-01T08:00:00Z", "the mooring lines are frayed"),
            _message("2026-03-01T08:30:00Z"),
            _mail("2026-03-01T09:00:00Z", KARI_EMAIL, OWNER_EMAIL),
            _mail("2026-03-01T10:00:00Z", OWNER_EMAIL, PER_EMAIL, "sent"),
            _mail("2026-03-01T11:00:00Z", NO_REPLY_EMAIL, OWNER_EMAIL),
            _mail("2026-03-01T12:00:00Z", HARBOUR_EMAIL, OWNER_EMAIL),
            _mail("2026-03-01T13:00:00Z", OWNER_EMAIL, HARBOUR_EMAIL, "sent"),
        ]
    )
    signing.sign(lb, "2026-03-01", at="2026-03-03T08:00:00Z")
    policy = lb.root / "policy" / "crossing.json"
    policy.parent.mkdir(exist_ok=True)
    policy.write_text(json.dumps({"hermes": {"max_tier": 2}}), encoding="utf-8")
    return lb


def _run(out: Path, *args: str) -> dict[str, Any]:
    cli.main(
        [
            "export",
            "crossing",
            "--to",
            "hermes",
            "--since",
            SINCE,
            "--until",
            UNTIL,
            "--tier",
            "1,2",
            "--out",
            str(out),
            *args,
        ]
    )
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def _entries(out: Path) -> list[dict[str, Any]]:
    text = (out / "entries.jsonl").read_text(encoding="utf-8")
    return [json.loads(s) for s in text.splitlines() if s.strip()]


def _subjects(out: Path) -> list[tuple[str, str]]:
    return [(e["payload"]["direction"], e["at"]) for e in _entries(out) if e["kind"] == "mail"]


def test_the_crossing_sends_only_peoples_mail_and_counts_the_rest(lb: Logbook, tmp_path: Path) -> None:
    out = tmp_path / "out"
    manifest = _run(out, "--kinds", "mail")
    assert _subjects(out) == [("received", "2026-03-01T09:00:00Z"), ("sent", "2026-03-01T10:00:00Z")]
    counts = manifest["counts"]
    assert counts["mail_held_back"] == 3
    assert counts["crossed"] == 2 and counts["by_kind"] == {"mail": 2}
    assert "mail" not in manifest["policy"]
    line = list(lb.lines())[-1]
    assert line["kind"] == "crossing" and line["payload"]["counts"] == counts
    assert "mail" not in line["payload"]["policy"]


def test_mail_among_every_kind_is_people_s_mail_too(lb: Logbook, tmp_path: Path) -> None:
    out = tmp_path / "out"
    manifest = _run(out)
    assert manifest["counts"]["mail_held_back"] == 3
    assert manifest["counts"]["by_kind"] == {"mail": 2, "message": 1, "note": 1}
    held = {e["payload"].get("from", {}).get("email") for e in _entries(out) if e["kind"] == "mail"}
    assert NO_REPLY_EMAIL not in held and HARBOUR_EMAIL not in held


def test_all_mail_sends_every_mail_and_says_so(lb: Logbook, tmp_path: Path) -> None:
    out = tmp_path / "out"
    manifest = _run(out, "--kinds", "mail", "--all-mail")
    assert len(_subjects(out)) == 5
    assert "mail_held_back" not in manifest["counts"]
    assert manifest["policy"]["mail"] == "all"
    line = list(lb.lines())[-1]
    assert line["payload"]["policy"]["mail"] == "all"


def test_the_dry_run_says_how_many_mails_stay_home(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(
        [
            "export",
            "crossing",
            "--to",
            "hermes",
            "--since",
            SINCE,
            "--until",
            UNTIL,
            "--tier",
            "1,2",
            "--dry-run",
        ]
    )
    text = capsys.readouterr().out
    assert "3 mail(s) held back: no person the record names is on them (--all-mail sends them)" in text
    assert "@" not in text


def test_a_window_whose_mail_is_all_peoples_says_none_was_held_back(lb: Logbook) -> None:
    req = crossing.request(lb, "hermes", "2026-03-01T08:59:00Z", "2026-03-01T09:30:00Z", (1, 2))
    assert crossing.select(lb, req).counts()["mail_held_back"] == 0


def _bundle(lb: Logbook, out: Path, kinds: frozenset[str] | None, all_mail: bool) -> dict[str, bytes]:
    """The bundle of one request, with the bundle's id, time and head fixed, as files → bytes."""
    req = crossing.request(lb, "hermes", SINCE, UNTIL, (1, 2), kinds, all_mail=all_mail)
    sel = crossing.select(lb, req)
    head = str(lb.meta["head"])
    manifest = crossing.build_manifest(
        lb, req, sel, "2026-03-05T08:00:00Z", "019cadd3-0000-7000-8000-000000000001", head
    )
    crossing.write_bundle(lb, sel, manifest, out, req)
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


@pytest.mark.parametrize(
    "kinds", [frozenset({"note"}), frozenset({"message"}), frozenset({"note", "message", "signed-day"})]
)
def test_every_other_kinds_bundle_is_byte_for_byte_what_it_was(
    lb: Logbook, tmp_path: Path, kinds: frozenset[str]
) -> None:
    """`--all-mail` is the crossing as it was before RFC 0045; without mail among the kinds, the rule
    changes nothing: every file of the bundle, the manifest included, is the same bytes."""
    before = _bundle(lb, tmp_path / "before", kinds, all_mail=True)
    after = _bundle(lb, tmp_path / "after", kinds, all_mail=False)
    assert before == after
    assert b"mail" not in before["manifest.json"]


def test_a_record_with_no_mail_carries_no_mail_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "plain", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [_note("2026-03-01T08:00:00Z", "a quiet day on the boat"), _message("2026-03-01T08:30:00Z")]
    )
    signing.sign(lb, "2026-03-01", at="2026-03-03T08:00:00Z")
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "crossing.json").write_text(
        json.dumps({"hermes": {"max_tier": 2}}), encoding="utf-8"
    )
    bundle = _bundle(lb, tmp_path / "out", None, all_mail=False)
    assert b"mail" not in bundle["manifest.json"]  # no `mail_held_back`, no `policy.mail`
