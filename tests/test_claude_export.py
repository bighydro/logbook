"""`logbook add claude-export DIR`: the Claude apps' data export → transcript/v1, one line per
conversation in the shape `claude-sessions` writes (#279): the owner's turns as speaker `owner`, the
assistant's as a machine participant, attachments and tool calls counted and never copied.
Synthetic: `claude_conversations` (the Oslo persona's export)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import claude_conversations as cc
import pytest

from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import claude_code, claude_export
from logbook.core import machine
from logbook.core.store import Logbook
from logbook.core.transcripts import turns_of


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return cc.export(tmp_path / "export")


def _run(
    path: Path, counts: dict[str, int] | None = None, **options: Any
) -> list[tuple[dict[str, Any], bytes]]:
    """The drafts with the bytes each stored."""
    stored: list[bytes] = []
    found = []
    for line in claude_export.run(
        path, counts=counts if counts is not None else {}, store=stored.append, **options
    ):
        found.append((line, stored[-1]))
    return found


def _by_conversation(path: Path, **options: Any) -> dict[str, tuple[dict[str, Any], bytes]]:
    return {line["payload"]["extra"]["conversation"]: (line, data) for line, data in _run(path, **options)}


def _passage(path: Path) -> tuple[dict[str, Any], bytes]:
    return _by_conversation(path)[cc.PASSAGE]


# -- sniff -------------------------------------------------------------------------------------------


def test_sniff_knows_the_folder_the_zip_and_the_file(folder: Path, tmp_path: Path):
    archive = cc.zipped(tmp_path / "data-2026-03-03.zip")
    assert claude_export.sniff(folder) and claude_export.sniff(archive)
    assert claude_export.sniff(folder / "conversations.json")
    assert adapters.find(folder) is claude_export and adapters.find(archive) is claude_export
    assert adapters.find(folder / "conversations.json") is claude_export
    assert adapters.named("claude-export") is claude_export


def test_sniff_says_no_to_another_apps_conversations_and_other_files(tmp_path: Path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "conversations.json").write_text(  # another app's export: no chat_messages
        json.dumps([{"title": "x", "create_time": 1.0, "mapping": {}, "current_node": "a"}]), encoding="utf-8"
    )
    assert not claude_export.sniff(other) and not claude_export.sniff(other / "conversations.json")
    (tmp_path / "garbage.zip").write_bytes(b"PK\x03\x04 not a zip")
    assert not claude_export.sniff(tmp_path / "garbage.zip")
    assert not claude_export.sniff(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    assert not claude_export.sniff(tmp_path / "empty")


# -- the line: the shape of #279's ---------------------------------------------------------------------


def test_one_transcript_line_per_conversation_in_claude_codes_shape_and_tier(folder: Path):
    counts: dict[str, int] = {}
    lines = _run(folder, counts)
    assert sorted(line["payload"]["extra"]["conversation"] for line, _d in lines) == [cc.PASSAGE, cc.PRESENT]
    for line, _data in lines:
        assert (line["kind"], line["source"], line["tier"]) == ("transcript", "claude", claude_code.TIER)
        payload = line["payload"]
        assert payload["schema"] == "transcript/v1" and payload["provider"] == "claude"
        assert payload["participants"] == [dict(p) for p in claude_code.PARTICIPANTS]
        assert payload["content"]["media_type"] == "application/json"
        assert {"words", "tool_calls", "tools", "counterpart", "turns", "speakers"} <= set(payload["extra"])
    assert counts["conversations"] == 3 and counts["skipped_empty"] == 1


def test_the_owner_speaks_as_owner_and_the_assistant_is_a_machine_participant(folder: Path):
    line, data = _passage(folder)
    participants = line["payload"]["participants"]
    assert participants == [{"name": "owner"}, {"name": "assistant", "machine": True}]
    assert machine.labels(participants) == frozenset({"assistant"})
    assert {t["speaker"] for t in json.loads(data)["turns"]} == {"owner", "assistant"}
    assert machine.agent_of(line["payload"]) == {
        "kind": "agent",
        "ref": {"kind": "provider_id", "value": "claude"},
        "name": "Claude",
    }


def test_the_text_is_the_turns_and_nothing_else(folder: Path):
    _line, data = _passage(folder)
    assert json.loads(data)["turns"] == [
        {"speaker": "owner", "text": cc.OWNER_FIRST},
        {"speaker": "assistant", "text": cc.MACHINE_FIRST},
        {"speaker": "owner", "text": cc.OWNER_SECOND},
        {"speaker": "assistant", "text": cc.MACHINE_SECOND},
    ]


def test_attachments_tool_outputs_thinking_and_the_account_never_reach_the_record(
    folder: Path, tmp_path: Path
):
    archive = cc.zipped(tmp_path / "export.zip")
    for path in (folder, archive):
        for line, data in _run(path):
            text = data.decode("utf-8") + json.dumps(line, ensure_ascii=False)
            for canary in cc.CANARIES:
                assert canary not in text, canary
            assert "not supported on your current device" not in text


def test_attachments_and_uploaded_files_are_counted_by_name_and_type(folder: Path):
    line, _data = _passage(folder)
    assert line["payload"]["extra"]["attachments"] == [
        {"name": "harbours.csv", "type": "text/csv", "bytes": 2048},
        {"name": "chart.png", "type": "png"},
    ]


def test_files_v2_are_counted_in_place_of_files_and_never_twice(tmp_path: Path):
    messages = cc.present_messages()
    messages[0]["files"] = [{"file_name": "gloves.jpg"}]
    messages[0]["files_v2"] = [
        {"file_kind": "image", "file_uuid": "u", "file_name": "gloves.jpg", "preview_url": "/api/x/preview"}
    ]
    messages[1]["files_v2"] = [{"file_kind": "document", "file_name": "sizes.pdf"}]
    ((line, _data),) = _run(cc.export(tmp_path / "v2", [cc.conversation(cc.PRESENT, "", messages, 0, 1)]))
    assert line["payload"]["extra"]["attachments"] == [
        {"name": "gloves.jpg", "type": "image"},
        {"name": "sizes.pdf", "type": "document"},
    ]
    assert "/api/x/preview" not in json.dumps(line)


def test_a_name_is_never_a_way_in_for_a_document(tmp_path: Path):
    long = "x" * 5000
    messages = cc.present_messages()
    messages[0]["attachments"] = [{"file_name": long, "file_type": long, "extracted_content": "y"}]
    messages[1]["content"].append({"type": "tool_use", "name": long, "input": {}})
    ((line, _data),) = _run(cc.export(tmp_path / "n", [cc.conversation(cc.PRESENT, long, messages, 0, 1)]))
    extra = line["payload"]["extra"]
    (named,) = extra["attachments"]
    assert len(named["name"]) <= 255 and len(named["type"]) <= 255
    assert all(len(tool) <= 255 for tool in extra["tools"]) and len(line["payload"]["title"]) <= 255


def test_tool_calls_are_a_count_by_name(folder: Path):
    line, _data = _passage(folder)
    extra = line["payload"]["extra"]
    assert extra["tool_calls"] == 2 and extra["tools"] == {"artifacts": 1, "web_search": 1}


def test_a_digest_and_the_words_of_each_side(folder: Path):
    line, data = _passage(folder)
    content = line["payload"]["content"]
    assert content["bytes"] == len(data) and content["sha256"] == hashlib.sha256(data).hexdigest()
    assert line["payload"]["extra"]["words"] == {
        "owner": len(cc.OWNER_FIRST.split()) + len(cc.OWNER_SECOND.split()),
        "machine": len(cc.MACHINE_FIRST.split()) + len(cc.MACHINE_SECOND.split()),
    }


def test_the_conversation_its_title_project_and_times(folder: Path):
    line, _data = _passage(folder)
    payload = line["payload"]
    assert payload["raw_id"] == f"claude:{cc.PASSAGE}" and payload["title"] == "Passage to Drøbak"
    extra = payload["extra"]
    assert extra["conversation"] == cc.PASSAGE and extra["project"] == cc.PROJECT_NAME
    assert extra["created_at"] == cc.at(0) and extra["updated_at"] == cc.at(700)
    assert line["at"] == cc.at(0) and line["end"] == cc.at(630)


def test_a_conversation_without_a_name_or_a_project_is_titled_by_the_owners_first_words(folder: Path):
    line, _data = _by_conversation(folder)[cc.PRESENT]
    assert line["payload"]["title"] == cc.PRESENT_OWNER
    assert "project" not in line["payload"]["extra"]


def test_the_zip_and_the_folder_give_the_same_lines(folder: Path, tmp_path: Path):
    archive = cc.zipped(tmp_path / "export.zip")
    assert _run(archive) == _run(folder) == _run(folder / "conversations.json")


def test_an_older_export_without_content_blocks_reads_the_text_without_placeholders(tmp_path: Path):
    older = cc.passage_messages()
    for m in older:
        del m["content"]
    chats = [cc.conversation(cc.PASSAGE, "Passage", older, 0, 700)]
    ((_line, data),) = _run(cc.export(tmp_path / "older", chats))
    turns = json.loads(data)["turns"]
    assert [t["speaker"] for t in turns] == ["owner", "assistant", "owner", "assistant"]
    assert turns[1]["text"] == cc.MACHINE_FIRST and turns[3]["text"] == cc.MACHINE_SECOND
    assert "not supported" not in data.decode("utf-8")


INLINE_ARTIFACT = "CANARY-inline-artifact-never-in-the-record"
INLINE_THINKING = "CANARY-inline-thinking-never-in-the-record"
INLINE = (
    f"<antThinking>{INLINE_THINKING}</antThinking>\n\nHere is the plan.\n\n"
    f'<antArtifact identifier="plan" type="text/markdown" title="Plan">\n{INLINE_ARTIFACT}\n'
    "</antArtifact>\n\n"
    "Tell me what to change."
)


@pytest.mark.parametrize("shape", ["blocks", "text"])
def test_an_artifact_and_thinking_written_inline_are_never_kept(tmp_path: Path, shape: str):
    """An export from before artifacts were tool calls carries them, and the thinking, in the text."""
    human = cc.message(1, 0, "human", [cc.text(cc.PRESENT_OWNER)], conversation=cc.PRESENT)
    assistant = cc.message(2, 30, "assistant", [cc.text(INLINE, 30)], conversation=cc.PRESENT)
    unclosed = cc.message(
        3,
        60,
        "assistant",
        [cc.text(f"Also:\n<antArtifact identifier='x'>{INLINE_ARTIFACT}")],
        conversation=cc.PRESENT,
    )
    if shape == "text":
        for m in (human, assistant, unclosed):
            del m["content"]
        assistant["text"], unclosed["text"] = INLINE, f"Also:\n<antArtifact identifier='x'>{INLINE_ARTIFACT}"
    chat = cc.conversation(cc.PRESENT, "", [human, assistant, unclosed], 0, 100)
    ((line, data),) = _run(cc.export(tmp_path / shape, [chat]))
    text = data.decode("utf-8") + json.dumps(line, ensure_ascii=False)
    assert INLINE_ARTIFACT not in text and INLINE_THINKING not in text and "<ant" not in text
    assert json.loads(data)["turns"][1]["text"] == "Here is the plan.\n\nTell me what to change.\n\nAlso:"
    assert line["payload"]["extra"]["tools"] == {"artifacts": 2}


def test_a_message_whose_blocks_are_empty_is_read_from_its_text(tmp_path: Path):
    first, answer = cc.present_messages()
    first["content"] = []
    ((_line, data),) = _run(
        cc.export(tmp_path / "e", [cc.conversation(cc.PRESENT, "", [first, answer], 0, 1)])
    )
    assert json.loads(data)["turns"][0] == {"speaker": "owner", "text": cc.PRESENT_OWNER}


def test_a_zip_whose_member_is_corrupt_is_not_sniffed_and_is_one_sentence(tmp_path: Path):
    archive = cc.zipped(tmp_path / "corrupt.zip")
    data = bytearray(archive.read_bytes())
    start = data.find(b"conversations.json") + len("conversations.json")
    for i in range(start + 5, start + 60):
        data[i] ^= 0xFF
    archive.write_bytes(bytes(data))
    assert zipfile.is_zipfile(archive) and claude_export.sniff(archive) is False
    assert adapters.find(archive) is not claude_export
    with pytest.raises(adapters.Unreadable, match=r"corrupt\.zip"):
        list(claude_export.run(archive))


def test_a_malformed_conversation_is_skipped_and_counted(tmp_path: Path):
    timeless = cc.conversation(
        "0193c1a0-0000-7000-8000-00000000c0f3",
        "x",
        [{**cc.present_messages()[0], "created_at": "yesterday"}],
        0,
        1,
    )
    timeless["created_at"] = timeless["updated_at"] = "never"
    chats: list[Any] = [
        "not a conversation",
        {"name": "no uuid", "chat_messages": cc.present_messages()},
        {
            **cc.conversation("0193c1a0-0000-7000-8000-00000000c0f1", "x", [], 0, 1),
            "chat_messages": "not a list",
        },
        cc.conversation("0193c1a0-0000-7000-8000-00000000c0f2", "x", [cc.present_messages()[0], 7], 0, 1),  # type: ignore[list-item]
        timeless,
        cc.conversation(cc.PRESENT, "", cc.present_messages(), 86400, 86420),
    ]
    counts: dict[str, int] = {}
    lines = _run(cc.export(tmp_path / "bad", chats), counts)
    assert [line["payload"]["extra"]["conversation"] for line, _d in lines] == [cc.PRESENT]
    assert counts["skipped_malformed"] == 5 and counts["conversations"] == 6


def test_only_the_branch_the_conversation_stands_on_is_read(tmp_path: Path):
    root = "00000000-0000-4000-8000-000000000000"
    first, answer = cc.present_messages()
    again = cc.message(3, 86460, "assistant", [cc.text("A waterproof logbook.")], conversation=cc.PRESENT)
    more = cc.message(
        4, 86500, "human", [cc.text("I'll order the logbook tonight.")], conversation=cc.PRESENT
    )
    first["parent_message_uuid"] = root
    answer["parent_message_uuid"] = again["parent_message_uuid"] = first["uuid"]
    more["parent_message_uuid"] = again["uuid"]
    chat = cc.conversation(cc.PRESENT, "", [first, answer, again, more], 0, 1)
    counts: dict[str, int] = {}
    ((_line, data),) = _run(
        cc.export(tmp_path / "b", [{**chat, "current_leaf_message_uuid": more["uuid"]}]), counts
    )
    assert [t["text"] for t in json.loads(data)["turns"]] == [
        cc.PRESENT_OWNER,
        "A waterproof logbook.",
        "I'll order the logbook tonight.",
    ]
    assert counts["skipped_branch"] == 1
    del more["parent_message_uuid"]  # a message without its parent: the export's order, every message
    counts = {}
    ((_line, data),) = _run(
        cc.export(tmp_path / "c", [{**chat, "current_leaf_message_uuid": more["uuid"]}]), counts
    )
    assert len(json.loads(data)["turns"]) == 3 and "skipped_branch" not in counts
    assert cc.PRESENT_MACHINE in json.loads(data)["turns"][1]["text"]


def test_a_message_from_neither_side_is_never_the_owners(tmp_path: Path):
    messages = [
        *cc.present_messages(),
        cc.message(
            3, 86500, "system", [cc.text("Nobody's words, never the owner's.")], conversation=cc.PRESENT
        ),
    ]
    counts: dict[str, int] = {}
    ((_line, data),) = _run(
        cc.export(tmp_path / "x", [cc.conversation(cc.PRESENT, "", messages, 0, 1)]), counts
    )
    assert "Nobody's words" not in data.decode("utf-8") and counts["skipped_unknown_sender"] == 1


def test_since_leaves_out_a_conversation_that_ended_before(folder: Path):
    counts: dict[str, int] = {}
    assert list(_by_conversation(folder, since=cc.at(3600), counts=counts)) == [cc.PRESENT]
    assert counts["skipped_before_since"] == 1


def test_an_export_that_does_not_parse_is_one_sentence(tmp_path: Path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "conversations.json").write_text('[{"uuid": "x", "chat_messages": [', encoding="utf-8")
    with pytest.raises(adapters.Unreadable, match=r"conversations\.json"):
        list(claude_export.run(broken))


def test_a_sealed_line_this_machine_cannot_open_is_never_written_again(folder: Path):
    sealed = {"id": "line-1", "payload": {"schema": "sealed/v1", "of": "transcript/v1", "digest": "0" * 64}}

    def existing(keys: Any) -> dict[tuple[str, str], dict[str, Any]]:
        return {key: sealed for key in keys if key == ("claude", f"claude:{cc.PASSAGE}")}

    counts: dict[str, int] = {}
    lines = {
        line["payload"]["extra"]["conversation"]: line
        for line in claude_export.run(folder, counts=counts, existing=existing)
    }
    assert lines[cc.PASSAGE]["payload"]["raw_id"] == f"claude:{cc.PASSAGE}"
    assert "supersedes" not in lines[cc.PASSAGE]["payload"]
    assert (
        counts["conversations_unchanged"] == 1 and counts["conversations_new"] == 1 and "grown" not in counts
    )


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


def _transcripts(lb: Logbook, conversation: str | None = None) -> list[dict[str, Any]]:
    with lb.index() as idx:
        found = [t for t in idx.by_kind("transcript") if t["source"] == "claude"]
    if conversation is not None:
        found = [t for t in found if t["payload"]["extra"]["conversation"] == conversation]
    return sorted(found, key=lambda t: t["seq"])


def test_add_claude_export_stores_the_turns_and_an_unchanged_export_writes_nothing(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    archive = cc.zipped(tmp_path / "data-2026-03-03.zip")
    code, out = _cli(capsys, "add", "claude-export", str(archive))
    assert code == 0 and "added 2 lines from claude" in out
    (passage,) = _transcripts(lb, cc.PASSAGE)
    turns = turns_of(lb, passage)
    assert turns is not None and [t.speaker for t in turns] == ["owner", "assistant", "owner", "assistant"]
    for blob in (lb.root / "attachments").iterdir():
        for canary in cc.CANARIES:
            assert canary.encode("utf-8") not in blob.read_bytes(), canary
    seq = int(lb.meta["seq"])
    code, out = _cli(capsys, "add", "claude-export", str(archive))
    assert code == 0 and "added 0 lines from claude" in out and "2 already in the record" in out
    assert "2 unchanged since the last import" in out
    assert int(Logbook.find().meta["seq"]) == seq


def test_a_conversation_that_grew_supersedes_the_line_before(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
):
    assert _cli(capsys, "add", "claude-export", str(folder))[0] == 0
    grown = cc.conversations()
    grown[0]["chat_messages"].append(
        cc.message(5, 4000, "human", [cc.text("I'll print the plan for the cockpit.")])
    )
    cc.export(folder, grown)
    code, out = _cli(capsys, "add", "claude-export", str(folder))
    assert code == 0 and "added 1 lines from claude" in out and "1 grown since the last import" in out
    old, new = _transcripts(lb, cc.PASSAGE)
    assert new["payload"]["raw_id"] == f"claude:{cc.PASSAGE}:v2"
    assert new["payload"]["supersedes"] == old["id"] and new["end"] == cc.at(4000)
    assert len(_transcripts(lb, cc.PRESENT)) == 1  # unchanged: nothing written for it
    grown[0]["chat_messages"].append(
        cc.message(6, 5000, "assistant", [cc.text("A copy for the chart table.")])
    )
    cc.export(folder, grown)
    assert _cli(capsys, "add", "claude-export", str(folder))[0] == 0
    newest = _transcripts(lb, cc.PASSAGE)[-1]
    assert newest["payload"]["raw_id"] == f"claude:{cc.PASSAGE}:v3"
    assert newest["payload"]["supersedes"] == new["id"]
    code, out = _cli(capsys, "add", "claude-export", str(folder))
    assert "added 0 lines from claude" in out and "2 unchanged since the last import" in out
    seq, _head, errors = lb.verify()
    assert not errors and seq == 4


def test_dry_run_counts_conversations_new_grown_and_unchanged_and_writes_nothing(
    lb: Logbook, folder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    first = [cc.conversations()[0]]
    assert _cli(capsys, "add", "claude-export", str(cc.export(tmp_path / "first", first)))[0] == 0
    grown = cc.conversations()
    grown[0]["chat_messages"].append(cc.message(5, 4000, "human", [cc.text("One more thing.")]))
    later = cc.export(tmp_path / "later", grown)
    seq = int(lb.meta["seq"])
    attachments = sorted(p.name for p in (lb.root / "attachments").iterdir())
    code, out = _cli(capsys, "add", "claude-export", str(later), "--dry-run")
    assert code == 0 and "claude: 2 lines would be added, 0 already in the record (dry run" in out
    assert "3 conversations in the export" in out and "1 new to the record" in out
    assert "1 grown since the last import" in out and "1 with nothing in them" in out
    assert int(Logbook.find().meta["seq"]) == seq
    assert sorted(p.name for p in (lb.root / "attachments").iterdir()) == attachments
    assert (
        _cli(capsys, "add", "claude-export", str(cc.export(tmp_path / "first", first)), "--dry-run")[1].count(
            "1 unchanged since the last import"
        )
        == 1
    )


def test_an_export_older_than_one_already_imported_writes_nothing(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    older = cc.zipped(tmp_path / "drop" / "data-2026-03-03.zip")
    grown = cc.conversations()
    grown[0]["chat_messages"].append(cc.message(5, 4000, "human", [cc.text("One more thing.")]))
    newer = cc.zipped(tmp_path / "drop" / "data-2026-04-03.zip", grown)
    assert _cli(capsys, "add", "claude-export", str(older), str(newer))[0] == 0
    assert [t["payload"]["raw_id"] for t in _transcripts(lb, cc.PASSAGE)] == [
        f"claude:{cc.PASSAGE}",
        f"claude:{cc.PASSAGE}:v2",
    ]
    seq = int(lb.meta["seq"])
    blobs = sorted(p.name for p in (lb.root / "attachments").iterdir())
    code, out = _cli(capsys, "add", "claude-export", str(older), str(newer))
    assert code == 0 and "grown" not in out and int(Logbook.find().meta["seq"]) == seq
    shorter = cc.conversations()
    shorter[0]["chat_messages"].pop()  # an export older still, never imported: nothing either
    code, out = _cli(capsys, "add", "claude-export", str(cc.export(tmp_path / "oldest", shorter)))
    assert code == 0 and "1 older than the line in the record" in out
    assert int(Logbook.find().meta["seq"]) == seq
    assert sorted(p.name for p in (lb.root / "attachments").iterdir()) == blobs  # its text never stored


def _branches(leaf: str, updated: float) -> list[Any]:
    """The present conversation with two answers to the owner's question: `leaf` names the one it
    stands on, the later answer going on with a second question."""
    root = "00000000-0000-4000-8000-000000000000"
    first, answer = cc.present_messages()
    again = cc.message(3, 86460, "assistant", [cc.text("A waterproof logbook.")], conversation=cc.PRESENT)
    more = cc.message(4, 86500, "human", [cc.text("Where can I buy one?")], conversation=cc.PRESENT)
    first["parent_message_uuid"] = root
    answer["parent_message_uuid"] = again["parent_message_uuid"] = first["uuid"]
    more["parent_message_uuid"] = again["uuid"]
    ids = {"answer": answer["uuid"], "more": more["uuid"]}
    chat = cc.conversation(cc.PRESENT, "", [first, answer, again, more], 86400, updated)
    return [{**chat, "current_leaf_message_uuid": ids[leaf]}]


def test_a_conversation_switched_back_to_an_earlier_branch_is_a_new_version(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    assert (
        _cli(capsys, "add", "claude-export", str(cc.export(tmp_path / "a", _branches("more", 86500))))[0] == 0
    )
    code, out = _cli(
        capsys, "add", "claude-export", str(cc.export(tmp_path / "b", _branches("answer", 90000)))
    )
    assert code == 0 and "1 grown since the last import" in out  # it ends earlier, yet it is later
    old, new = _transcripts(lb, cc.PRESENT)
    assert new["payload"]["supersedes"] == old["id"] and new["end"] < old["end"]
    assert [t.text for t in turns_of(lb, new) or []] == [cc.PRESENT_OWNER, cc.PRESENT_MACHINE]


def test_a_broken_branch_reads_every_message_in_the_exports_order(tmp_path: Path):
    chats = _branches("more", 86500)
    chats[0]["chat_messages"][2]["parent_message_uuid"] = "0193c1a0-0000-7000-8000-00000000dead"  # not there
    counts: dict[str, int] = {}
    ((_line, data),) = _run(cc.export(tmp_path / "x", chats), counts)
    assert len(json.loads(data)["turns"]) == 3 and "skipped_branch" not in counts


def test_a_project_named_by_an_object_or_an_unreadable_projects_file(tmp_path: Path):
    chats = cc.conversations()
    del chats[0]["project_uuid"]
    chats[0]["project"] = {"uuid": cc.PROJECT, "name": "not read from here"}
    folder = cc.export(tmp_path / "p", chats)
    assert _by_conversation(folder)[cc.PASSAGE][0]["payload"]["extra"]["project"] == cc.PROJECT_NAME
    (folder / "projects.json").write_text("[{", encoding="utf-8")
    assert "project" not in _by_conversation(folder)[cc.PASSAGE][0]["payload"]["extra"]


def test_tier_sets_another_for_the_run_and_an_unchanged_conversation_is_not_written_again(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
):
    assert _cli(capsys, "add", "claude-export", str(folder), "--tier", "3")[0] == 0
    assert {t["tier"] for t in _transcripts(lb)} == {3}
    code, out = _cli(capsys, "add", "claude-export", str(folder))
    assert code == 0 and "added 0 lines from claude" in out
