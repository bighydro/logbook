"""Google Takeout Google Chat/ → message/v1 (RFC 0008): one line per message, direct and group chats,
the owner from `Users/` or `owner_emails`. Everyone here is synthetic."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters.takeout import chat

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Google Chat"
GROUPS = FIX / "Groups"
DM = GROUPS / "DM 7f3a2b1c9d0e"
SPACE = GROUPS / "Space AAAAb2Cd3Ef"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
OWNER = "per.persona@example.org"


def _lines(path=FIX, **kw):
    return list(chat.run(path, timezone=TZ, **kw))


def test_registry_has_chat_as_a_file_adapter_under_both_names():
    assert adapters.named("google-takeout-chat") is chat and adapters.named("takeout-chat") is chat
    assert isinstance(chat, adapters.Adapter)
    assert adapters.find(FIX) is chat and adapters.find(GROUPS) is chat and adapters.find(DM) is chat
    assert adapters.find(DM / "messages.json") is chat


def test_sniff_recognises_the_folder_at_every_level_and_nothing_else(tmp_path):
    assert chat.sniff(FIX) and chat.sniff(GROUPS) and chat.sniff(SPACE) and chat.sniff(DM / "messages.json")
    assert not chat.sniff(DM / "group_info.json") and not chat.sniff(
        ROOT / "tests" / "fixtures" / "takeout" / "Keep"
    )
    assert not chat.sniff(tmp_path) and not chat.sniff(tmp_path / "messages.json")
    (tmp_path / "messages.json").write_text('{"messages": "nope"}', encoding="utf-8")
    assert not chat.sniff(tmp_path / "messages.json")


def test_every_message_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(chat.run(FIX, timezone=TZ, counts=counts))
    assert len(lines) == 6  # 3 in the DM (one with only a file), 3 in the space
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "message" and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "message/v1"
    assert counts == {
        "skipped_no_body": 1,
        "skipped_no_timestamp": 1,
        "no_chat_message_id": 1,
        "media_hashed": 1,
    }
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_the_owner_comes_from_users_and_from_me_is_set_accordingly():
    by = {line["payload"]["raw_id"]: line for line in _lines()}
    theirs = by["chat:kQ1xYz/kQ1xYz"]
    assert theirs["at"] == "2026-06-10T11:30:05Z"
    assert theirs["payload"] == {
        "schema": "message/v1",
        "raw_id": "chat:kQ1xYz/kQ1xYz",
        "chat": {"id": "DM 7f3a2b1c9d0e", "type": "direct", "name": "Kari Nordmann"},
        "from_me": False,
        "sender": {"kind": "email", "value": "kari.nordmann@example.org", "name": "Kari Nordmann"},
        "text": "Lunch at the cafe at 12?",
        "extra": {"topic_id": "kQ1xYz"},
    }
    mine = by["chat:kQ1xYz/Lm2Nop"]["payload"]
    assert mine["from_me"] is True and "sender" not in mine
    assert mine["extra"]["reactions"] == [{"emoji": "👍", "count": 1}]


def test_owner_emails_name_the_owner_when_the_export_has_no_users_folder(tmp_path):
    import shutil

    shutil.copytree(GROUPS, tmp_path / "Groups")
    lines = list(chat.run(tmp_path / "Groups", timezone=TZ, owner_emails=["Kari.Nordmann@example.org"]))
    by = {line["payload"]["raw_id"]: line["payload"] for line in lines}
    assert by["chat:kQ1xYz/kQ1xYz"]["from_me"] is True
    assert by["chat:kQ1xYz/Lm2Nop"]["from_me"] is False
    assert by["chat:kQ1xYz/Lm2Nop"]["sender"]["value"] == OWNER
    counts: dict[str, int] = {}
    list(chat.run(tmp_path / "Groups", timezone=TZ, counts=counts))  # nobody says who the owner is
    assert counts["no_owner"] == 1
    assert all(
        not p["from_me"] for p in (line["payload"] for line in chat.run(tmp_path / "Groups", timezone=TZ))
    )


def test_a_space_is_a_group_chat_named_by_group_info_and_a_link_is_kept():
    by = {line["payload"]["raw_id"]: line["payload"] for line in _lines(SPACE)}
    ola = by["chat:Aa1Bb2/Aa1Bb2"]
    assert ola["chat"] == {"id": "Space AAAAb2Cd3Ef", "type": "group", "name": "Solvind crew"}
    assert ola["extra"]["links"] == [
        {"url": "https://weather.example.org/oslofjord", "title": "Oslofjord forecast"}
    ]
    spelled = "Saturday, June 13, 2026 at 6:06:00 AM UTC"
    digest = hashlib.sha256(b"Bringing the coffee").hexdigest()[:16]
    no_id = by[f"chat:{spelled}:{digest}"]
    assert no_id["sender"]["name"] == "Kari Nordmann" and no_id["text"] == "Bringing the coffee"


def test_a_file_is_hashed_beside_the_message_and_stored_only_when_asked(tmp_path):
    stored: list[bytes] = []
    counts: dict[str, int] = {}
    by = {
        line["payload"]["raw_id"]: line["payload"] for line in _lines(DM, counts=counts, store=stored.append)
    }
    photo = by["chat:kQ1xYz/Qr3Stu"]
    data = (DM / "impeller.jpg").read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    assert photo["media"] == {"sha256": sha, "bytes": len(data), "media_type": "image/jpeg"}
    assert photo["media_kind"] == "image" and "text" not in photo
    assert photo["extra"]["attached_files"] == ["impeller.jpg"]
    assert stored == [] and counts["media_hashed"] == 1
    by = {
        line["payload"]["raw_id"]: line["payload"]
        for line in _lines(DM, attachments=True, store=stored.append)
    }
    assert by["chat:kQ1xYz/Qr3Stu"]["media"]["path"] == f"attachments/{sha}"
    assert stored == [data]


def test_since_cuts_on_at():
    assert [line["payload"]["text"] for line in _lines(since="2026-06-13T06:05:00Z")] == [
        "On my way",
        "Bringing the coffee",
    ]


def test_cli_add_sniffs_the_folder_dry_run_writes_nothing_and_a_re_add_appends_nothing(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", "takeout-chat", str(FIX), "--dry-run"])
    out = capsys.readouterr().out
    assert (
        "google-takeout-chat: 6 lines would be added, 0 already in the record (dry run, nothing written)"
        in out
    )
    assert "skipped 1 without a timestamp" in out and "skipped 1 without a body" in out
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 6 lines from google-takeout-chat" in out
    assert "1 without a message id, keyed by time and text" in out and "1 with media hashed" in out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-chat" in capsys.readouterr().out
