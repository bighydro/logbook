"""`logbook export notion OUT [--since DAY] [--include-unsigned] [--dry-run]`: the record's facts for the
owner's Notion, as a crossing (docs/export-notion.md). One folder, written fresh every run, under the
`notion` entry of `policy/crossing.json`; signed days only unless the entry and the flag both say
otherwise; one `crossing/v1` line; nothing created anywhere but the folder.

The record is synthetic: Ines Nordmann of Oslo, who does not exist, in September 2026. Ola writes from
the yard's domain, meets her at the office, promises drawings and is promised a call; Kari wrote only in
August; Per only on an unsigned day; Liv has no address the record can match on; a phone resolved by a
tier-3 line names nobody here. The yard is an org with a domain, a tier-3 status and a ledger line;
the board is an org with no domain. The fjord kiosk is an idea with a Notion page and three statuses,
the last on an unsigned day; the tide clock has no Notion page."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import OFFICE, attendee, dwell, event, utc

from logbook import cli
from logbook.contrib import notion_export
from logbook.core import policy, signing
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
OWNER = {"name": "Ines Nordmann", "email": "ines@example.org"}
YARD_DOMAIN = "nordmann-verft.example.org"
OLA = {
    "id": "019cadd3-6bc0-7dcd-9133-000000000411",
    "name": "Ola Nordmann",
    "email": f"ola@{YARD_DOMAIN}",
    "phone": "+447700900101",
    "handle": "ola-nordmann",
}
KARI = {
    "id": "019cadd3-6bc0-7dcd-9133-000000000412",
    "name": "Kari Nordmann",
    "email": "kari@nordmann.example.org",
}
PER = {"id": "019cadd3-6bc0-7dcd-9133-000000000413", "name": "Per Nordmann", "phone": "+447700900102"}
LIV = {"id": "019cadd3-6bc0-7dcd-9133-000000000414", "name": "Liv Berg", "provider_id": "beeper:liv-berg"}
SIGRID = {"id": "019cadd3-6bc0-7dcd-9133-000000000415", "name": "Sigrid Nordmann", "phone": "+447700900109"}
YARD = "019cadd3-6bc0-7dcd-9133-000000000421"
BOARD = "019cadd3-6bc0-7dcd-9133-000000000422"
KIOSK = "019cadd3-6bc0-7dcd-9133-000000000431"
TIDE = "019cadd3-6bc0-7dcd-9133-000000000432"
KIOSK_PAGE = "notion:1f2e3d4c-0000-0000-0000-000000000031"
REASON = "pricing page written; talk to the ferry company first"
UNSIGNED_REASON = "UNSIGNED-REASON first stand ordered"
TIDE_REASON = "TIDE-REASON every chartplotter already shows it"
ORG_REASON = "SENTINEL-ORG-REASON bought 4 % at 250 000 NOK"
TIER3_TEXT = "I will bring the SECRET-TIER3 papers tomorrow."
DRAWINGS = "I'll send you the drawings by Friday."
CALL = "I will call the yard tomorrow."
MONEY_PROMISE = "I'll pay you the 450 NOK on Monday."
SIGNED = ("2026-09-02", "2026-09-03", "2026-09-05", "2026-09-10", "2026-09-12", "2026-09-14", "2026-09-20")
UNSIGNED = "2026-09-25"
NEVER = (  # what no bundle may hold, whatever the run: tier 3, an org's status and reason, money
    "SECRET-TIER3",
    SIGRID["phone"],
    "SENTINEL-ORG-REASON",
    "250 000",
    "NOK",
    "1234.5",
    "1234,5",
    "FJORDKIOSK",
    '"hold"',
    TIDE_REASON,
)


def _at(day: str, clock: str = "10:00") -> str:
    return utc(day, clock)


def _resolution(
    ref: tuple[str, str], who: dict[str, str], kind: str = "person", tier: int = 2
) -> dict[str, Any]:
    return {
        "at": "2026-08-01T08:00:00Z", "source": "manual", "kind": "resolution", "tier": tier,
        "payload": {"schema": "resolution/v1", "ref": {"kind": ref[0], "value": ref[1]},
                    "entity": {"type": kind, "id": who["id"], "registry": "logbook"}, "label": who["name"],
                    "method": "owner"},
    }  # fmt: skip


def _entity(kind: str, entity: str, label: str, refs: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "at": "2026-08-01T09:00:00Z", "source": "manual", "kind": "entity", "tier": 2,
        "payload": {"schema": "entity/v1", "entity": {"type": kind, "id": entity, "registry": "logbook"},
                    "label": label, "refs": [{"kind": k, "value": v} for k, v in refs], "method": "owner"},
    }  # fmt: skip


def _mail(day: str, sender: dict[str, str], subject: str, clock: str = "09:00") -> dict[str, Any]:
    message_id = f"{day}.{clock}.{sender['email']}"
    return {
        "at": _at(day, clock), "source": "mail", "kind": "mail", "tier": 2,
        "payload": {"schema": "mail/v1", "raw_id": f"mail:{message_id}", "message_id": message_id,
                    "thread": message_id, "from": {"email": sender["email"], "name": sender["name"]},
                    "to": [{"email": OWNER["email"], "name": OWNER["name"]}], "subject": subject,
                    "direction": "received", "size": 900},
    }  # fmt: skip


def _message(
    day: str,
    text: str,
    chat: str,
    sender: tuple[str, str] | None = None,
    clock: str = "15:00",
    tier: int = 2,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"wa:{day}:{clock}:{chat}",
        "chat": {"id": chat, "type": "direct"},
        "from_me": sender is None,
        "text": text,
    }
    if sender is not None:
        payload["sender"] = {"kind": sender[0], "value": sender[1]}
    return {"at": _at(day, clock), "source": "whatsapp", "kind": "message", "tier": tier, "payload": payload}


def _status(
    entity: tuple[str, str], label: str, status: str, day: str, tier: int, **more: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "status/v1",
        "entity": {"type": entity[0], "id": entity[1], "registry": "logbook"},
        "label": label,
        "status": status,
        "proposed_by": "owner",
        **more,
    }
    return {"at": _at(day, "20:00"), "source": "manual", "kind": "status", "tier": tier, "payload": payload}


def _reason_note(status: dict[str, Any], entity: tuple[str, str], text: str) -> dict[str, Any]:
    """The note `logbook status` writes beside an idea's status line with a reason (RFC 0037 §10.5)."""
    return {
        "at": status["at"], "source": "manual", "kind": "note", "tier": 2,
        "payload": {"schema": "note/v1", "text": text, "labels": ["status"],
                    "extra": {"status": status["id"], "entity": {"type": entity[0], "id": entity[1],
                                                                  "registry": "logbook"}}},
    }  # fmt: skip


def drafts() -> list[dict[str, Any]]:
    ola_chat = f"{OLA['phone'][1:]}@s.whatsapp.net"
    found = [
        _resolution(("email", OLA["email"]), OLA),
        _resolution(("phone", OLA["phone"]), OLA),
        _resolution(("handle", OLA["handle"]), OLA),
        _resolution(("email", KARI["email"]), KARI),
        _resolution(("phone", PER["phone"]), PER),
        _resolution(("provider_id", LIV["provider_id"]), LIV),
        _resolution(("phone", SIGRID["phone"]), SIGRID, tier=3),  # tier 3: names nobody under a ceiling of 2
        _entity("org", YARD, "Nordmann Verft AS", [("domain", YARD_DOMAIN)]),
        _entity("org", BOARD, "Nordmann Verft board", [("group", "nordmann verft board")]),
        _entity("idea", KIOSK, "the fjord kiosk", [("page", KIOSK_PAGE), ("title", "fjord kiosk")]),
        _entity("idea", TIDE, "the tide clock", [("repo", "git.example.org/nordmann-verft/tide")]),
        _mail("2026-08-20", KARI, "Before the summer ends"),  # Kari: before the window only
        _mail("2026-09-02", OLA, "Hull drawings"),
        _mail("2026-09-03", OLA, "Re: Hull drawings"),
        _mail(UNSIGNED, {"name": "Nordmann Verft", "email": f"post@{YARD_DOMAIN}"}, "Invoice"),
        _status(("org", YARD), "Nordmann Verft AS", "hold", "2026-09-05", 3, reason=ORG_REASON),
        {"at": _at("2026-09-05", "17:00"), "source": "copilot", "kind": "transaction", "tier": 3,
         "payload": {"schema": "transaction/v1", "raw_id": "copilot:1", "amount": -1234.5, "currency": "NOK",
                     "merchant": "FJORDKIOSK AS", "provider": "copilot"}},
        _status(("idea", KIOSK), "the fjord kiosk", "spark", "2026-09-05", 2),
        *dwell("2026-09-10", "09:00", "12:00", OFFICE),
        event(_at("2026-09-10", "10:00"), _at("2026-09-10", "11:30"), "Hull review",
              [attendee(OLA["email"], OLA["name"])]),
        _message("2026-09-12", DRAWINGS, ola_chat, ("phone", OLA["phone"])),
        _message("2026-09-12", CALL, ola_chat, clock="15:10"),
        _message("2026-09-12", MONEY_PROMISE, ola_chat, ("phone", OLA["phone"]), clock="15:20"),
        _message("2026-09-12", "See you", "beeper-liv", ("provider_id", LIV["provider_id"])),
        _message("2026-09-12", "Hei", f"{SIGRID['phone'][1:]}@s.whatsapp.net", ("phone", SIGRID["phone"])),
        _message("2026-09-14", TIER3_TEXT, ola_chat, ("phone", OLA["phone"]), tier=3),
        _message(UNSIGNED, "Tomorrow at the yard?", ola_chat, ("phone", OLA["phone"])),
        _message(UNSIGNED, "Kommer du?", f"{PER['phone'][1:]}@s.whatsapp.net", ("phone", PER["phone"])),
    ]  # fmt: skip
    return found


def build(root: Path) -> Logbook:
    lb = Logbook.init(root, TZ)
    lb.set_owner_emails([OWNER["email"]])
    lb.append_many(drafts())
    spark = next(line for line in lb.lines() if line["kind"] == "status" and line["tier"] == 2)
    exploring = lb.append(**_line(_status(("idea", KIOSK), "the fjord kiosk", "exploring", "2026-09-20", 2,
                                          reason=REASON, supersedes=spark["id"])))  # fmt: skip
    lb.append(**_line(_reason_note(exploring, ("idea", KIOSK), REASON)))
    tide = lb.append(
        **_line(_status(("idea", TIDE), "the tide clock", "killed", "2026-09-20", 2, reason=TIDE_REASON))
    )
    lb.append(**_line(_reason_note(tide, ("idea", TIDE), TIDE_REASON)))
    build_ = lb.append(**_line(_status(("idea", KIOSK), "the fjord kiosk", "build", UNSIGNED, 2,
                                       reason=UNSIGNED_REASON, supersedes=exploring["id"])))  # fmt: skip
    lb.append(**_line(_reason_note(build_, ("idea", KIOSK), UNSIGNED_REASON)))
    for day in SIGNED:
        signing.sign(lb, day, at="2026-10-01T08:00:00Z")
    return lb


def _line(draft: dict[str, Any]) -> dict[str, Any]:
    return {k: draft[k] for k in ("at", "source", "kind", "tier", "payload")}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    record = build(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    monkeypatch.setattr(notion_export, "now", lambda: NOW)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 15))
    _entry(record)
    return record


def _entry(lb: Logbook, **fields: Any) -> Path:
    """The policy with the owner's `notion` entry (max_tier 2, no `write`: the list stays empty), plus
    `fields`."""
    path = lb.root / "policy" / "crossing.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["notion"] = {"max_tier": 2, **fields}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _run(out: Path, *args: str) -> None:
    cli.main(["export", "notion", str(out), *args])


def _fails(out: Path, *args: str) -> int:
    with pytest.raises(SystemExit) as e:
        _run(out, *args)
    return int(e.value.code or 0)


def _read(out: Path, name: str) -> Any:
    return json.loads((out / name).read_bytes())


def _all_bytes(out: Path) -> str:
    return "\n".join(p.read_bytes().decode("utf-8") for p in sorted(out.rglob("*")) if p.is_file())


def _person(out: Path, entity: str) -> dict[str, Any] | None:
    return next((p for p in _read(out, "persons.json")["persons"] if p["id"] == entity), None)


# -- the policy entry ----------------------------------------------------------------------------------


def test_without_the_notion_entry_the_command_refuses_in_one_sentence(lb: Logbook, tmp_path: Path, capsys):
    path = lb.root / "policy" / "crossing.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["notion"]
    path.write_text(json.dumps(data), encoding="utf-8")
    seq = lb.meta["seq"]
    assert _fails(tmp_path / "out") == 2
    err = capsys.readouterr().err.strip()
    assert err.count("\n") == 0 and err.count(". ") == 0, "one line, one sentence"
    assert "notion" in err and str(path) in err
    assert not (tmp_path / "out").exists()
    assert lb.meta["seq"] == seq, "nothing appended"


def test_an_entry_without_write_is_read_as_one_with_the_empty_write_list(lb: Logbook):
    """`write` defaults to the empty list, and this destination writes nothing back, so the owner's entry
    leaves it out (docs/export-notion.md, `policy.notion_entry`'s own message): spelled out empty, the
    entry is read the same."""
    path = lb.root / "policy" / "crossing.json"
    assert json.loads(path.read_text(encoding="utf-8"))["notion"] == {"max_tier": 2}
    left_out = policy.notion_entry(lb.root)
    _entry(lb, write=[])
    spelled_out = policy.notion_entry(lb.root)
    assert left_out == spelled_out
    assert left_out.write == () and left_out.writes == () and left_out.max_tier == 2


def test_an_expired_entry_lets_nothing_leave(lb: Logbook, tmp_path: Path, capsys):
    _entry(lb, until="2026-10-01")
    seq = lb.meta["seq"]
    assert _fails(tmp_path / "out") == 2
    err = capsys.readouterr().err
    assert "2026-10-01" in err and "notion" in err
    assert not (tmp_path / "out").exists() and lb.meta["seq"] == seq


# -- the envelope --------------------------------------------------------------------------------------


def test_the_envelope(lb: Logbook, tmp_path: Path):
    head = str(lb.meta["head"])
    _run(tmp_path / "out", "--since", "2026-09-01")
    manifest = _read(tmp_path / "out", "manifest.json")
    entry = next(c for c in policy.ceilings(lb.root) if c.destination == "notion")
    assert manifest["schema"] == notion_export.SCHEMA
    assert manifest["as_of"] == "2026-10-15T08:00:00Z"
    assert manifest["read_head"] == head
    assert manifest["policy"] == {"name": "notion", "version": policy.version(entry)}
    assert manifest["signed_only"] is True
    assert manifest["window"] == {"since": "2026-09-01", "until": "2026-10-15"}
    assert sorted(f["path"] for f in manifest["files"]) == ["ideas.json", "orgs.json", "persons.json"]
    for listed in manifest["files"]:
        raw = (tmp_path / "out" / listed["path"]).read_bytes()
        assert listed["sha256"] == hashlib.sha256(raw).hexdigest() and listed["bytes"] == len(raw)
    first = manifest["export_id"]
    _run(tmp_path / "out", "--since", "2026-09-01")
    again = _read(tmp_path / "out", "manifest.json")
    assert again["export_id"] != first, "unique per run"
    assert again["read_head"] != head, "the first run's crossing line moved the head"


# -- what leaves -----------------------------------------------------------------------------------------


def test_the_body_shape(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    ola = _person(out, OLA["id"])
    assert ola is not None and set(ola) == {"id", "identities", "facts", "page"}
    assert ola["identities"] == [
        {"kind": "email", "value": OLA["email"]},
        {"kind": "handle", "value": OLA["handle"]},
        {"kind": "phone", "value": OLA["phone"]},
    ]
    facts = ola["facts"]
    assert set(facts) == {
        "last_contact",
        "days_together",
        "first_together",
        "last_together",
        "promises",
        "promises_more",
    }
    assert facts["last_contact"] == {"date": "2026-09-12", "kind": "message"}
    assert facts["days_together"] == 1
    assert facts["first_together"] == facts["last_together"] == "2026-09-10"
    assert facts["promises_more"] == {"owed_by_owner": 0, "owed_to_owner": 0}
    owed_by, owed_to = facts["promises"]["owed_by_owner"], facts["promises"]["owed_to_owner"]
    assert [p["sentence"] for p in owed_by] == [CALL]
    assert [p["sentence"] for p in owed_to] == [DRAWINGS], "the one naming money is left out"
    assert all(
        set(p) == {"sentence", "date", "line"} and p["date"] == "2026-09-12" for p in owed_by + owed_to
    )
    assert all(isinstance(text, str) for text in ola["page"])
    page = "\n".join(ola["page"])
    assert "Letzter Kontakt: 12.09.2026 (Nachricht)" in page
    assert "Tage zusammen: 1 (zuerst 10.09.2026, zuletzt 10.09.2026)" in page
    assert f"„{CALL}“" in page and f"„{DRAWINGS}“" in page, "the sentence quoted as written"

    [kiosk] = _read(out, "ideas.json")["ideas"]
    assert set(kiosk) == {"page", "status", "reason", "entries"}
    assert kiosk["page"] == KIOSK_PAGE
    assert kiosk["status"]["status"] == "exploring" and kiosk["status"]["since"] == "2026-09-20"
    assert kiosk["reason"]["text"] == REASON, "the owner's words, verbatim"
    assert [e["date"] for e in kiosk["entries"]] == ["2026-09-05", "2026-09-20"]
    assert all(set(e) == {"id", "date", "text", "lines"} for e in kiosk["entries"])
    assert (
        kiosk["entries"][1]["text"]
        == f"20.09.2026 — Status: in Erkundung (exploring). Begründung: „{REASON}“"
    )
    assert kiosk["entries"][0]["text"] == "05.09.2026 — Status: Funke (spark)."

    [yard] = _read(out, "orgs.json")["orgs"]
    assert set(yard) == {"domain", "touched", "last_touch", "entries"}
    assert yard["domain"] == YARD_DOMAIN
    assert yard["touched"] == ["2026-09-02", "2026-09-03", "2026-09-10"], "two mails and the meeting"
    assert yard["last_touch"] == "2026-09-10"
    assert [e["text"] for e in yard["entries"]] == [
        "02.09.2026 — Kontakt.",
        "03.09.2026 — Kontakt.",
        "10.09.2026 — Kontakt.",
    ]

    left = _read(out, "manifest.json")["left_out"]
    assert left["persons_without_identity"] == 1, "Liv: only a provider id, nothing to match on"
    assert left["ideas_without_page"] == 1, "the tide clock: no Notion page"
    assert left["orgs_without_domain"] == 1, "the board: no domain"
    assert left["sentences_with_money"] == 1


def test_signed_days_only_by_default(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _person(out, PER["id"]) is None, "Per wrote only on an unsigned day"
    ola = _person(out, OLA["id"])
    assert ola is not None and ola["facts"]["last_contact"]["date"] == "2026-09-12"
    [yard] = _read(out, "orgs.json")["orgs"]
    assert UNSIGNED not in yard["touched"]
    [kiosk] = _read(out, "ideas.json")["ideas"]
    assert kiosk["status"]["status"] == "exploring"
    assert UNSIGNED_REASON not in _all_bytes(out)

    _entry(lb, include_unsigned=True)
    _run(out, "--since", "2026-09-01", "--include-unsigned")
    assert _read(out, "manifest.json")["signed_only"] is False
    per = _person(out, PER["id"])
    assert per is not None and per["facts"]["last_contact"] == {"date": UNSIGNED, "kind": "message"}
    ola = _person(out, OLA["id"])
    assert ola is not None and ola["facts"]["last_contact"]["date"] == UNSIGNED
    [yard] = _read(out, "orgs.json")["orgs"]
    assert yard["touched"][-1] == UNSIGNED
    [kiosk] = _read(out, "ideas.json")["ideas"]
    assert kiosk["status"]["status"] == "build" and kiosk["reason"]["text"] == UNSIGNED_REASON


def test_include_unsigned_needs_the_entry_to_allow_it(lb: Logbook, tmp_path: Path, capsys):
    seq = lb.meta["seq"]
    assert _fails(tmp_path / "out", "--include-unsigned") == 2
    err = capsys.readouterr().err
    assert "include_unsigned" in err and "notion" in err
    assert not (tmp_path / "out").exists() and lb.meta["seq"] == seq


def test_no_tier_3_line_no_org_status_and_no_money_ever_appear(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    [yard] = _read(out, "orgs.json")["orgs"]
    assert yard["touched"], "the yard is there, and only as touched"
    assert _person(out, OLA["id"]) is not None
    assert _person(out, SIGRID["id"]) is None, "her phone resolves through a tier-3 line only"
    whole = _all_bytes(out)
    for text in NEVER:
        assert text not in whole, text
    ola = _person(out, OLA["id"])
    assert ola is not None and ola["facts"]["last_contact"]["date"] != "2026-09-14", "not the tier-3 message"
    _entry(lb, include_unsigned=True, max_tier=3)
    _run(out, "--since", "2026-08-01", "--include-unsigned")
    whole = _all_bytes(out)
    for text in NEVER:
        assert text not in whole, f"{text} under a ceiling of 3"
    assert _read(out, "manifest.json")["tiers"] == [1, 2], "tier 3 never, whatever the entry"


def test_a_ceiling_of_1_lets_no_tier_2_fact_leave(lb: Logbook, tmp_path: Path):
    _entry(lb, max_tier=1)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _read(out, "persons.json")["persons"] == [], "every identity is on a tier-2 resolution line"
    assert _read(out, "ideas.json")["ideas"] == [], "an idea and its status are tier 2"
    assert _read(out, "orgs.json")["orgs"] == [], "an org is bound by a tier-2 entity line"
    assert REASON not in _all_bytes(out)


def test_a_person_without_contact_in_the_window_is_absent(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _person(out, OLA["id"]) is not None
    assert _person(out, KARI["id"]) is None, "Kari wrote in August"
    _entry(lb, include_unsigned=True)
    _run(out, "--since", "2026-08-01", "--include-unsigned")
    kari = _person(out, KARI["id"])
    assert kari is not None and kari["facts"]["last_contact"] == {"date": "2026-08-20", "kind": "mail"}


# -- the folder and the line -----------------------------------------------------------------------------


def test_the_output_folder_is_fresh_on_a_second_run(lb: Logbook, tmp_path: Path, capsys):
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    (out / "stray.json").write_text("{}", encoding="utf-8")
    (out / "old").mkdir()
    (out / "old" / "persons.json").write_text("[]", encoding="utf-8")
    _run(out, "--since", "2026-09-01")
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*")) == [
        "ideas.json",
        "manifest.json",
        "orgs.json",
        "persons.json",
    ]
    assert not list(tmp_path.glob(".out.*")), "no staging or old folder left beside it"
    other = tmp_path / "notes"
    other.mkdir()
    (other / "mine.md").write_text("my own notes", encoding="utf-8")
    seq = lb.meta["seq"]
    assert _fails(other, "--since", "2026-09-01") == 2, "a folder that is not an earlier export"
    assert (other / "mine.md").read_text(encoding="utf-8") == "my own notes" and lb.meta["seq"] == seq
    capsys.readouterr()


def test_a_crossing_line_is_written(lb: Logbook, tmp_path: Path):
    head, seq = str(lb.meta["head"]), lb.meta["seq"]
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert lb.meta["seq"] == seq + 1, "one line, and only one"
    line = lb.line_by_seq(seq + 1)
    manifest = _read(out, "manifest.json")
    assert (
        line is not None and line["kind"] == "crossing" and line["tier"] == 1 and line["source"] == "logbook"
    )
    payload = line["payload"]
    assert payload["schema"] == "crossing/v1" and payload["destination"] == "notion"
    assert payload["bundle_id"] == manifest["export_id"]
    assert payload["logbook_head"] == head == manifest["read_head"]
    assert payload["package_sha256"] == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()
    assert payload["policy"] == {
        "file": "policy/crossing.json",
        "max_tier": 2,
        "signed_only": True,
        "version": manifest["policy"]["version"],
    }
    assert payload["tiers"] == [1, 2]
    assert payload["window"]["to"] == "2026-10-15T08:00:00Z"
    assert payload["extra"]["notion"]["counts"] == manifest["counts"]
    assert line["at"] == manifest["as_of"]


def test_the_dry_run_counts_and_writes_nothing(lb: Logbook, tmp_path: Path, capsys):
    seq = lb.meta["seq"]
    _run(tmp_path / "out", "--since", "2026-09-01", "--dry-run")
    text = capsys.readouterr().out
    assert not (tmp_path / "out").exists() and lb.meta["seq"] == seq
    assert "nothing written" in text
    assert "persons: 1" in text and "ideas: 1 (2 entries)" in text and "orgs: 1 (3 entries)" in text
    assert "left out:" in text and "1 person without an email, phone or handle" in text
    assert "1 idea without a Notion page" in text and "1 org without a domain" in text
    assert "1 sentence naming money" in text
    assert "would be refused" not in text
    mine = tmp_path / "notes"
    mine.mkdir()
    (mine / "mine.md").write_text("my own notes", encoding="utf-8")
    _run(mine, "--since", "2026-09-01", "--dry-run")
    assert "a real run would be refused" in capsys.readouterr().out
    assert (mine / "mine.md").read_text(encoding="utf-8") == "my own notes" and lb.meta["seq"] == seq


def test_it_asks_nothing_of_the_network(lb: Logbook, tmp_path: Path, no_network: list[str]):
    _run(tmp_path / "out", "--since", "2026-09-01")
    assert no_network == []


@pytest.mark.parametrize("flag", [("--until", "2026-10-01"), ("--tier", "1,2"), ("--unsigned",)])
def test_a_crossing_flag_is_refused_never_ignored(lb: Logbook, tmp_path: Path, flag: tuple[str, ...], capsys):
    seq = lb.meta["seq"]
    assert _fails(tmp_path / "out", *flag) == 2
    assert flag[0] in capsys.readouterr().err
    assert not (tmp_path / "out").exists() and lb.meta["seq"] == seq


# -- the independent review's findings -------------------------------------------------------------------


def test_the_day_of_an_export_still_shows(lb: Logbook, tmp_path: Path, capsys):
    """The crossing line's `counts` are RFC 0011's, so `show` names it like any crossing; the
    sections' counts ride under `extra.notion`."""
    _run(tmp_path / "out", "--since", "2026-09-01")
    capsys.readouterr()
    cli.main(["show", "2026-10-15"])
    assert "crossed to notion:" in capsys.readouterr().out
    line = lb.line_by_seq(int(lb.meta["seq"]))
    assert line is not None
    counts = line["payload"]["counts"]
    assert {"logged", "crossed", "held_back", "by_tier", "by_kind"} <= set(counts)
    assert counts["by_tier"]["3"] == 0 and counts["crossed"] > 0
    assert line["payload"]["extra"]["notion"]["counts"] == _read(tmp_path / "out", "manifest.json")["counts"]


@pytest.mark.parametrize(
    "sentence",
    [
        "I'll pay 500kr tomorrow.",
        "I'll send NOK5000 on Monday.",
        "I'll send 5000NOK on Monday.",
        "I'll wire EUR500 by Friday.",
        "I'll pay you the 450 NOK on Monday.",
        "I'll put in 2 MNOK.",
        "The stand is 300,- a day.",
        "We need 5 mill for it.",
        "I'll bring 20 € tomorrow.",
        "It costs a few kroner.",
    ],
)
def test_a_sentence_naming_money_is_caught(sentence: str):
    assert notion_export.names_money(sentence), sentence


@pytest.mark.parametrize(
    "sentence",
    [DRAWINGS, CALL, REASON, "I'll run 5km on Sunday.", "Kronborg is lovely in May.", "We meet at 10:30."],
)
def test_a_sentence_without_money_is_kept(sentence: str):
    assert not notion_export.names_money(sentence), sentence


def test_an_idea_s_status_is_its_state_whatever_the_window(lb: Logbook, tmp_path: Path):
    """The current status is read from every status line the gate lets through, whatever its day, so a
    narrow window never blanks it; the entries are the window's."""
    out = tmp_path / "out"
    _run(out, "--since", "2026-10-01")
    [kiosk] = _read(out, "ideas.json")["ideas"]
    assert kiosk["status"]["status"] == "exploring" and kiosk["status"]["since"] == "2026-09-20"
    assert kiosk["reason"]["text"] == REASON
    assert kiosk["entries"] == [], "no status line was written in the window"


@pytest.mark.parametrize(
    "flag", [("--out", "elsewhere"), ("--kinds", "note"), ("--to", "hermes"), ("--open",)]
)
def test_every_flag_notion_does_not_take_is_refused(
    lb: Logbook, tmp_path: Path, flag: tuple[str, ...], capsys
):
    seq = lb.meta["seq"]
    assert _fails(tmp_path / "out", *flag) == 2
    assert flag[0] in capsys.readouterr().err
    assert not (tmp_path / "out").exists() and lb.meta["seq"] == seq


def test_nothing_after_the_read_time_is_a_fact(lb: Logbook, tmp_path: Path):
    """The line's window ends at `as_of` (RFC 0011: `from` <= `at` < `to`): a calendar entry later today
    is no contact yet, even with the gate lifted."""
    lb.append(**_line(event("2026-10-15T12:00:00Z", "2026-10-15T13:00:00Z", "Lunch",
                            [attendee(OLA["email"], OLA["name"])])))  # fmt: skip
    _entry(lb, include_unsigned=True)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01", "--include-unsigned")
    ola = _person(out, OLA["id"])
    assert ola is not None and ola["facts"]["last_contact"]["date"] == UNSIGNED


def test_the_window_opens_on_the_record_s_first_day_by_default(lb: Logbook, tmp_path: Path):
    _run(tmp_path / "out")
    assert _read(tmp_path / "out", "manifest.json")["window"] == {
        "since": "2026-08-01",
        "until": "2026-10-15",
    }


def test_a_policy_file_the_readers_refuse_is_one_sentence(lb: Logbook, tmp_path: Path, capsys):
    (lb.root / "policy" / "owner.json").write_text('{"emails": "not a list"}', encoding="utf-8")
    seq = lb.meta["seq"]
    assert _fails(tmp_path / "out", "--since", "2026-09-01") == 2
    err = capsys.readouterr().err.strip()
    assert err.startswith("export notion:") and err.count("\n") == 0
    assert not (tmp_path / "out").exists() and lb.meta["seq"] == seq
