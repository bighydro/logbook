"""`logbook add telegram-export DIR`: Telegram Desktop's JSON export → message/v1, the owner's own
bots only. The owner's words are theirs; the bot's are marked machine text; the counterpart of every
line is the bot, an observed entity of kind `agent`, never a person. Synthetic: `telegram_persona`."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import telegram_persona as tp

from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import telegram
from logbook.core import machine
from logbook.core.store import Logbook


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tp.export(tmp_path / "DataExport_2026-03-02")


def _lines(folder: Path, counts: dict[str, int] | None = None, **options: Any) -> list[dict[str, Any]]:
    return list(
        telegram.run(folder, counts=counts if counts is not None else {}, timezone="Europe/Oslo", **options)
    )


def _by_id(lines: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {line["payload"]["extra"]["message_id"]: line for line in lines}


# -- sniff -------------------------------------------------------------------------------------------


def test_sniff_knows_the_export_folder_and_its_result_json(folder: Path):
    assert telegram.sniff(folder)
    assert telegram.sniff(folder / "result.json")
    assert adapters.find(folder) is telegram


def test_sniff_knows_a_single_chat_export(tmp_path: Path):
    chat = {"name": "Nordlys", "type": "bot_chat", "id": tp.NORDLYS_ID, "messages": tp.NORDLYS_MESSAGES}
    (tmp_path / "result.json").write_text(json.dumps(chat), encoding="utf-8")
    assert telegram.sniff(tmp_path / "result.json")


@pytest.mark.parametrize(
    "content",
    [b"", b"\x00\xff garbage", b'{"messages": []}', b'[{"type": "bot_chat"}]', b'{"chats": {"list": []}}'],
)
def test_sniff_says_no_to_other_files_and_never_raises(tmp_path: Path, content: bytes):
    (tmp_path / "result.json").write_bytes(content)
    assert not telegram.sniff(tmp_path / "result.json")
    assert not telegram.sniff(tmp_path / "missing")
    assert not telegram.sniff(tmp_path / "empty-folder")


# -- the lines ---------------------------------------------------------------------------------------


def test_only_the_bot_chats_are_read_and_the_rest_is_counted(folder: Path):
    counts: dict[str, int] = {}
    lines = _lines(folder, counts)
    assert {line["payload"]["chat"]["id"] for line in lines} == {str(tp.NORDLYS_ID), str(tp.FJORDVAKT_ID)}
    assert len(lines) == 12  # ten in Nordlys's chat (one is a service message), two in Fjordvakt's
    assert counts["skipped_not_a_bot_chat"] == 2  # Ola's chat and the saved messages, never read
    assert counts["skipped_service"] == 1
    assert all(line["payload"]["text"] != "Great" for line in lines if "text" in line["payload"])


def test_every_line_is_a_tier_2_message_of_the_telegram_source(folder: Path):
    for line in _lines(folder):
        assert (line["kind"], line["tier"], line["source"], line["end"]) == ("message", 2, "telegram", None)
        assert line["payload"]["schema"] == "message/v1"
        assert line["payload"]["chat"]["type"] == "direct"


def test_the_owners_words_are_theirs_and_the_bots_are_marked_machine(folder: Path):
    by_id = _by_id(_lines(folder))
    own, bot = by_id[401]["payload"], by_id[402]["payload"]
    assert own["from_me"] is True and "sender" not in own and not machine.is_machine(own)
    assert bot["from_me"] is False and machine.is_machine(bot)
    assert bot["sender"] == {"kind": "provider_id", "value": f"telegram:{tp.NORDLYS_ID}", "name": "Nordlys"}
    assert own["text"] == "Plan the passage to Drøbak for Saturday, and remind me to call Ola"


def test_the_counterpart_of_every_line_is_the_bot_an_agent(folder: Path):
    for line in _lines(folder):
        agent = machine.agent_of(line["payload"])
        assert agent is not None and agent["kind"] == "agent"
        bot_id = line["payload"]["chat"]["id"]
        assert agent["ref"] == {"kind": "provider_id", "value": f"telegram:{bot_id}"}
    by_id = _by_id(_lines(folder))
    assert machine.agent_of(by_id[401]["payload"])["name"] == "Nordlys"
    assert machine.agent_of(by_id[501]["payload"])["name"] == "Fjordvakt"


def test_rich_text_is_read_as_the_words_it_shows(folder: Path):
    bot = _by_id(_lines(folder))[402]["payload"]
    assert bot["text"] == "I'll have the passage plan ready by Friday. Can you send me the tide table?"


def test_at_is_the_messages_own_instant_in_utc(folder: Path):
    by_id = _by_id(_lines(folder))
    assert by_id[401]["at"] == tp.at(15) and by_id[501]["at"] == tp.at(60)


def test_a_reply_points_at_the_raw_id_of_the_message_it_answers(folder: Path):
    by_id = _by_id(_lines(folder))
    assert by_id[402]["payload"]["reply_to"] == by_id[401]["payload"]["raw_id"]


def test_the_raw_id_is_the_key_both_views_of_the_chat_share(folder: Path):
    by_id = _by_id(_lines(folder))
    own = by_id[401]["payload"]
    text = "Plan the passage to Drøbak for Saturday, and remind me to call Ola"
    assert own["raw_id"] == telegram.key(str(tp.NORDLYS_ID), tp.unix(15), True, text, False)
    assert own["raw_id"].startswith(f"{tp.NORDLYS_ID}/{tp.unix(15)}/me/")
    assert by_id[402]["payload"]["raw_id"].startswith(f"{tp.NORDLYS_ID}/{tp.unix(16)}/bot/")
    assert own["extra"]["view"] == "export"


def test_two_messages_of_one_second_and_one_shape_get_two_keys(folder: Path):
    by_id = _by_id(_lines(folder))
    first, second = by_id[408]["payload"]["raw_id"], by_id[409]["payload"]["raw_id"]
    assert first != second and second == f"{first}~2"


def test_media_is_referenced_by_its_path_and_digest_never_copied(folder: Path):
    by_id = _by_id(_lines(folder))
    photo = by_id[403]["payload"]
    assert photo["media_kind"] == "image" and photo["text"] == "the anchorage" and "media" not in photo
    assert photo["extra"]["media"] == {
        "local_path": "photos/photo_1@01-03-2026_11-20-00.jpg",
        "sha256": hashlib.sha256(tp.PHOTO_BYTES).hexdigest(),
        "bytes": len(tp.PHOTO_BYTES),
    }
    voice = by_id[404]["payload"]
    assert voice["media_kind"] == "voice" and "text" not in voice
    assert voice["extra"]["media"]["media_type"] == "audio/ogg"
    assert voice["extra"]["media"]["sha256"] == hashlib.sha256(tp.VOICE_BYTES).hexdigest()


def test_a_file_the_export_left_out_is_missing_not_an_error(folder: Path):
    counts: dict[str, int] = {}
    doc = _by_id(_lines(folder, counts))[405]["payload"]
    assert doc["media_kind"] == "document" and doc["extra"]["media_missing"] is True
    assert doc["extra"]["media"] == {"filename": "passage-plan.pdf", "media_type": "application/pdf"}
    assert counts["media_missing"] == 2  # the PDF and the path that leaves the export


def test_a_media_path_outside_the_export_is_never_read(folder: Path):
    outside = _by_id(_lines(folder))[410]["payload"]
    assert outside["extra"]["media_missing"] is True and "sha256" not in outside["extra"].get("media", {})


def test_an_edited_message_says_so(folder: Path):
    edited = _by_id(_lines(folder))[406]["payload"]
    assert edited["edited"] is True and edited["extra"]["edited_at"] == tp.at(31)


def test_a_forwarded_message_keeps_who_it_came_from(folder: Path):
    forwarded = _by_id(_lines(folder))[407]["payload"]
    assert forwarded["extra"]["forwarded_from"] == "Ola Nordmann" and forwarded["from_me"] is True


def test_an_old_export_without_unix_times_is_read_in_the_records_zone(tmp_path: Path):
    old = tp.mine(401, 15, "Hei")
    del old["date_unixtime"]
    doc = tp.document([{"name": "Nordlys", "type": "bot_chat", "id": tp.NORDLYS_ID, "messages": [old]}])
    (line,) = _lines(tp.export(tmp_path / "old", doc))
    assert line["at"] == tp.at(15)  # 11:15 in Oslo is 10:15 UTC


def test_an_old_export_with_numeric_sender_ids_still_tells_the_bot_from_the_owner(tmp_path: Path):
    old = [dict(m) for m in tp.NORDLYS_MESSAGES[1:3]]
    for message in old:
        message["from_id"] = int(str(message["from_id"]).removeprefix("user"))
    doc = tp.document([{"name": "Nordlys", "type": "bot_chat", "id": tp.NORDLYS_ID, "messages": old}])
    own, bot = _lines(tp.export(tmp_path / "numeric", doc))
    assert own["payload"]["from_me"] is True and not machine.is_machine(own["payload"])
    assert bot["payload"]["from_me"] is False and machine.is_machine(bot["payload"])


def test_a_message_with_neither_text_nor_media_is_counted_not_written(tmp_path: Path):
    dice = tp.mine(411, 50, "")
    doc = tp.document([{"name": "Nordlys", "type": "bot_chat", "id": tp.NORDLYS_ID, "messages": [dice]}])
    counts: dict[str, int] = {}
    assert _lines(tp.export(tmp_path / "dice", doc), counts) == [] and counts["skipped_empty"] == 1


def test_since_leaves_out_what_came_before(folder: Path):
    lines = _lines(folder, since=tp.at(60))
    assert {line["payload"]["extra"]["message_id"] for line in lines} == {501, 502}


def test_a_single_chat_export_is_read_as_one_chat(tmp_path: Path):
    chat = {"name": "Fjordvakt", "type": "bot_chat", "id": tp.FJORDVAKT_ID, "messages": tp.FJORDVAKT_MESSAGES}
    lines = _lines(tp.export(tmp_path / "single", chat))
    assert [line["payload"]["extra"]["message_id"] for line in lines] == [501, 502]


def test_a_bot_chat_is_a_bot_chat_whatever_the_owner_id(tmp_path: Path):
    """The owner is everyone in a bot chat who is not the bot: a private chat with a bot has two sides."""
    doc = tp.document(
        [{"name": "Nordlys", "type": "bot_chat", "id": tp.NORDLYS_ID, "messages": tp.NORDLYS_MESSAGES}]
    )
    del doc["personal_information"]
    lines = _lines(tp.export(tmp_path / "anonymous", doc))
    assert [line["payload"]["from_me"] for line in lines][:2] == [True, False]


# -- through the command -----------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    try:
        cli.main(list(args))
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    return code, capsys.readouterr().out


def test_add_telegram_export_writes_once_and_re_adding_writes_nothing(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
):
    code, out = _cli(capsys, "add", "telegram-export", str(folder))
    assert code == 0 and "added 12 lines from telegram" in out
    code, out = _cli(capsys, "add", str(folder))
    assert code == 0 and "added 0 lines from telegram" in out and "12 already in the record" in out
    seq, _head, errors = lb.verify()
    assert seq == 12 and not errors
