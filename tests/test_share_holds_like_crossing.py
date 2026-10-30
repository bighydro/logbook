"""A shared page holds back what the crossing holds back, a destination name the policy keeps for its
own readers is never a person's, and an agent's reflection stays pencil (the privacy review of 26
October, R4, and the desk's reviews since).

- `export share day` sends one day to a person, as `export crossing` sends a window: only a day the
  owner has signed leaves (RFC 0034), and a mail crosses only when a person is on it (RFC 0045), both
  through the crossing's own rules, each counted in the page's manifest.
- The local exports (a folder, the vault, the site, the world) are the owner's own copies and take no
  signed-day gate.
- `mcp`, `dream`, `vault` and the other names of `policy.RESERVED` are refused as a destination by
  both commands, in one sentence, before anything is written.
- `note_day` writes a reflection only when the `mcp` entry names it, as source `mcp`: pencil, never
  confirmed by a plain `day sign`, never the reflection Sign signs with, and shown with its source.

Every name here is synthetic: Ines Nordmann of Oslo, her brother Ola, Kari Nordmann and Per Hansen,
`example.org` addresses; nobody here exists."""

from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import mcp_server, reflect
from logbook.core import drafts, policy, share, signing
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-03-01"
SIGNED_AT = "2026-03-02T08:00:00Z"  # 09:00 on the 2nd, Oslo: the signature is not on the page's day
OWNER_EMAIL, KARI_EMAIL, PER_EMAIL = "ines@example.org", "kari@example.org", "per@example.org"
HARBOUR_EMAIL = "harbour@example.org"
KARI, PER, HARBOUR = (
    "019cadd3-6bc0-7dcd-9133-043f5aabf3b1",
    "019cadd3-6bc0-7dcd-9133-043f5aabf3b2",
    "019cadd3-6bc0-7dcd-9133-043f5aabf3b3",
)


def _resolution(value: str, label: str, entity: str, type_: str = "person") -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:00:00Z",
        "source": "ios-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": "email", "value": value},
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


def _location(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"dawarich:{at}"},
    }


def _policy(lb: Logbook, entries: dict[str, Any]) -> None:
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """2026-03-01 in Oslo, not signed: a location, a mail from Kari (a person), one sent to Per (a
    person) and one from the harbour (a company). Ola may have tier 2."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([OWNER_EMAIL])
    lb.append_many(
        [
            _resolution(KARI_EMAIL, "Kari Nordmann", KARI),  # seq 1
            _resolution(PER_EMAIL, "Per Hansen", PER),  # seq 2
            _resolution(HARBOUR_EMAIL, "Oslo Harbour", HARBOUR, type_="company"),  # seq 3
            _location("2026-03-01T08:00:00Z"),  # seq 4
            _mail("2026-03-01T09:00:00Z", KARI_EMAIL, OWNER_EMAIL),  # seq 5: Kari's
            _mail("2026-03-01T10:00:00Z", OWNER_EMAIL, PER_EMAIL, "sent"),  # seq 6: Per's
            _mail("2026-03-01T11:00:00Z", HARBOUR_EMAIL, OWNER_EMAIL),  # seq 7: no person's
        ]
    )
    _policy(lb, {"mcp": {"max_tier": 1}, "ola": {"max_tier": 2}})
    return lb


def _share(*args: str) -> None:
    cli.main(["export", "share", "day", *args])


def _fails(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    return int(e.value.code or 0)


def _one_sentence(text: str) -> str:
    said = text.strip()
    assert said.count("\n") == 0, said
    body = said.split(": ", 1)[1]
    assert body.count(". ") == 0 and body.count("; ") <= 1, said  # one sentence, at most one clause after
    return said


def _members(bundle: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(bundle) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


# -- 1. a shared page holds what the crossing holds -------------------------------------------------------


def test_an_unsigned_day_is_refused_in_one_sentence_naming_day_sign(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    seq, head = lb.meta["seq"], lb.meta["head"]
    out = tmp_path / "page.zip"
    assert _fails(["export", "share", "day", DAY, "--to", "ola", "--tier", "2", "--out", str(out)]) == 2
    said = _one_sentence(capsys.readouterr().err)
    assert f"logbook day sign {DAY}" in said and "signed" in said
    assert not out.exists() and not out.with_name(out.name + ".tmp").exists()
    assert (lb.meta["seq"], lb.meta["head"]) == (seq, head), "no crossing line"
    assert "share_key" not in lb.meta, "no key made for a page that never left"


def test_a_signed_day_shares_and_its_manifest_counts_what_the_gate_held_back(lb: Logbook, tmp_path: Path):
    signing.sign(lb, DAY, at=SIGNED_AT)
    out = tmp_path / "page.zip"
    _share(DAY, "--to", "ola", "--tier", "2", "--out", str(out))
    manifest = json.loads(_members(out)["manifest.json"])
    assert manifest["held_back_unsigned"] == 0


def test_a_mail_no_person_is_on_is_held_back_and_counted(lb: Logbook, tmp_path: Path):
    signing.sign(lb, DAY, at=SIGNED_AT)
    out = tmp_path / "page.zip"
    _share(DAY, "--to", "ola", "--tier", "2", "--out", str(out))
    members = _members(out)
    lines = [json.loads(s) for s in members["lines.jsonl"].decode("utf-8").splitlines()]
    mails = [line["payload"]["from"]["email"] for line in lines if line["kind"] == "mail"]
    assert mails == [KARI_EMAIL, OWNER_EMAIL], "Kari's and the one sent to Per cross; the harbour's stays"
    assert HARBOUR_EMAIL.encode() not in members["lines.jsonl"]
    manifest = json.loads(members["manifest.json"])
    assert manifest["mail_held_back"] == 1 and manifest["held_back_unsigned"] == 0
    crossed = [line for line in lb.lines() if line["kind"] == "crossing"][-1]
    counts = crossed["payload"]["counts"]
    assert counts["mail_held_back"] == 1 and counts["held_back_unsigned"] == 0
    assert crossed["payload"]["policy"]["signed_only"] is True


def test_a_page_with_no_mail_writes_no_mail_count(lb: Logbook, tmp_path: Path):
    """As the crossing: `mail_held_back` is written whenever the rule read a mail, and only then."""
    signing.sign(lb, DAY, at=SIGNED_AT)
    out = tmp_path / "page.zip"
    _share(DAY, "--to", "ola", "--tier", "1", "--out", str(out))
    manifest = json.loads(_members(out)["manifest.json"])
    assert "mail_held_back" not in manifest and manifest["held_back_unsigned"] == 0


def test_the_receiver_reads_a_page_that_counts_what_each_rule_held_back(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    signing.sign(lb, DAY, at=SIGNED_AT)
    out = tmp_path / "page.zip"
    _share(DAY, "--to", "ola", "--tier", "2", "--out", str(out))
    key = str(lb.meta["share_key"])
    ola = Logbook.init(tmp_path / "ola", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    cli.main(["key", "circle", "add", "ines", key])
    cli.main(["import", "page", str(out)])
    assert "from ines" in capsys.readouterr().out


# -- 2. the owner's own copies take no signed-day gate ------------------------------------------------------


def test_a_day_to_a_folder_takes_no_signed_day_gate(lb: Logbook, tmp_path: Path):
    out = tmp_path / "folder"
    cli.main(["export", "--day", DAY, "--out", str(out)])
    package = json.loads((out / "package.json").read_text(encoding="utf-8"))
    assert package["entries"], "the owner's own copy of an unsigned day"


def test_the_export_page_says_the_local_exports_take_no_signed_day_gate():
    text = (Path(__file__).parent.parent / "docs" / "export.md").read_text(encoding="utf-8")
    section = text.split("## The line that says it left", 1)[1]
    assert "signed" in section and "share day" in section and "export crossing" in section


# -- 3. the names the policy keeps are no one's ---------------------------------------------------------


@pytest.mark.parametrize("name", policy.RESERVED)
def test_export_crossing_refuses_a_reserved_name(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
):
    signing.sign(lb, DAY, at=SIGNED_AT)
    _policy(lb, {"mcp": {"max_tier": 1}, name: {"max_tier": 1}})
    seq = lb.meta["seq"]
    out = tmp_path / "out"
    argv = ["export", "crossing", "--to", name, "--since", "2026-03-01T00:00:00Z"]
    assert _fails([*argv, "--until", "2026-03-02T00:00:00Z", "--out", str(out)]) == 2
    said = _one_sentence(capsys.readouterr().err)
    assert repr(name) in said and "reserved" in said
    assert not out.exists() and lb.meta["seq"] == seq
    assert not (lb.root / "exports" / "crossing.json").exists()


@pytest.mark.parametrize("name", policy.RESERVED)
def test_share_day_refuses_a_reserved_name(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
):
    signing.sign(lb, DAY, at=SIGNED_AT)
    _policy(lb, {"mcp": {"max_tier": 1}, name: {"max_tier": 1}})
    seq = lb.meta["seq"]
    out = tmp_path / "page.zip"
    assert _fails(["export", "share", "day", DAY, "--to", name, "--out", str(out)]) == 2
    said = _one_sentence(capsys.readouterr().err)
    assert repr(name) in said and "reserved" in said
    assert not out.exists() and lb.meta["seq"] == seq and "share_key" not in lb.meta


@pytest.mark.parametrize("name", ["MCP", "Vault"])
def test_a_reserved_name_is_reserved_in_any_case(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
):
    """`export/crossing/MCP` and `export/crossing/mcp` are one folder on a Mac or Windows disk."""
    signing.sign(lb, DAY, at=SIGNED_AT)
    _policy(lb, {name: {"max_tier": 1}})
    assert _fails(["export", "share", "day", DAY, "--to", name, "--out", str(tmp_path / "p.zip")]) == 2
    assert "reserved" in capsys.readouterr().err
    argv = ["export", "crossing", "--to", name, "--since", "2026-03-01T00:00:00Z"]
    assert _fails([*argv, "--until", "2026-03-02T00:00:00Z", "--out", str(tmp_path / "o")]) == 2
    assert "reserved" in capsys.readouterr().err


def test_the_reserved_names_are_the_policy_s_own():
    for name in ("mcp", "hermes", "dream", "site", "vault", "world", "folder", "heard", "chat", "phone"):
        assert name in policy.RESERVED
    for constant in (
        policy.MCP_DESTINATION,
        policy.VAULT_DESTINATION,
        policy.SITE_DESTINATION,
        policy.FOLDER_DESTINATION,
        policy.WORLD_DESTINATION,
        policy.DREAM_DESTINATION,
        policy.HEARD_DESTINATION,
        policy.NOTION_DESTINATION,
        drafts.PERSON_ENTRY,
    ):
        assert constant in policy.RESERVED


# -- 4. an agent's reflection stays pencil ----------------------------------------------------------------


@pytest.fixture
def door(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setattr(mcp_server, "_today", lambda _lb: "2026-03-02")
    monkeypatch.setattr(policy, "today", lambda: date(2026, 3, 2))
    return lb


@pytest.mark.parametrize("write", [[], ["sign_day"], ["add_note", "promise_done"]])
def test_a_reflection_through_the_door_is_refused_unless_the_entry_names_note_day(
    door: Logbook, write: list[str]
):
    _policy(door, {"mcp": {"max_tier": 2, "write": write}})
    seq = door.meta["seq"]
    with pytest.raises(ValueError) as e:
        mcp_server.call(door.root, "note_day", {"day": DAY, "text": "A calm day.", "kind": "reflection"})
    assert "note_day" in str(e.value) and door.meta["seq"] == seq


def test_a_reflection_through_the_door_is_pencil_and_never_the_owner_s(
    door: Logbook, capsys: pytest.CaptureFixture[str]
):
    _policy(door, {"mcp": {"max_tier": 2, "write": ["note_day"]}})
    text = "A calm day; the agent thinks so."
    data = mcp_server.call(door.root, "note_day", {"day": DAY, "text": text, "kind": "reflection"})["data"]
    line = next(line for line in door.lines() if line["id"] == data["id"])
    assert line["source"] == "mcp" and line["payload"]["labels"] == ["reflection"]
    assert drafts.is_pencil(line)
    cli.main(["day", "sign", DAY, "--at", SIGNED_AT])
    capsys.readouterr()
    signature = [line for line in door.lines() if line["kind"] == signing.KIND][-1]
    confirmed = signature["payload"].get("confirmed")
    assert confirmed is not None and line["id"] not in confirmed, "a plain sign never confirms pencil"
    lines = list(door.lines())
    assert reflect.reflections(lines, set()) == [], "never the reflection Sign signs with"
    cli.main(["day", DAY, "--json"])
    shown = json.loads(capsys.readouterr().out)
    days = shown if isinstance(shown, list) else [shown]
    said = [day["reflection"] for day in days if "reflection" in day]
    assert said and all(r["source"] == "mcp" for r in said), "shown, and shown as the agent's"


# -- the review's findings -----------------------------------------------------------------------------


def test_the_page_s_own_selection_holds_back_an_unsigned_day_line_by_line(lb: Logbook):
    """`share_day` refuses an unsigned day before it selects; the selection holds it too, line by line,
    so the gate is the crossing's in both places and each held line is counted."""
    sel = share.select(lb, DAY, 2, "ola")
    assert sel.lines == [] and sel.held_back_unsigned == 4 and sel.held_back == sel.logged == 4
    assert sel.mail_held_back is None, "nothing past the gate, so no mail was read"


@pytest.mark.parametrize("name", ["mcp.", "vault..", "Dream. "])
def test_a_reserved_name_with_trailing_dots_is_reserved(lb: Logbook, name: str):
    """Windows drops a trailing dot or space from a folder's name: `export/crossing/mcp.` is `mcp`."""
    with pytest.raises(policy.PolicyError):
        policy.check_destination(name)


def test_the_receiver_refuses_a_count_larger_than_held_back(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    signing.sign(lb, DAY, at=SIGNED_AT)
    out = tmp_path / "page.zip"
    _share(DAY, "--to", "ola", "--tier", "2", "--out", str(out))
    members = _members(out)
    manifest = json.loads(members["manifest.json"])
    manifest["mail_held_back"] = manifest["held_back"] + 1
    with pytest.raises(share.ReceiveError, match="mail_held_back"):
        share._check_counts(manifest)
