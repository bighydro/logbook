"""`logbook add claude-sessions DIR`: Claude Code's session transcripts → transcript/v1, one line per
session: the owner's turns as speaker `owner`, the assistant's as a machine participant, tool calls
counted and their output never kept. Synthetic: `claude_sessions` (the Oslo persona's coding)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import claude_sessions as cs
import pytest

from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import claude_code
from logbook.core import machine
from logbook.core.store import Logbook
from logbook.core.transcripts import turns_of

CANARIES = (
    cs.TOOL_OUTPUT,
    cs.SIDECHAIN,
    cs.THINKING,
    cs.COMPACT,
    "Caveat:",
    "/model",
    "interrupted",
    "API Error",
)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return cs.projects(tmp_path / "projects")


def _run(
    path: Path, counts: dict[str, int] | None = None, **options: Any
) -> list[tuple[dict[str, Any], bytes]]:
    """The drafts with the bytes each stored."""
    stored: list[bytes] = []
    found = []
    for line in claude_code.run(
        path, counts=counts if counts is not None else {}, store=stored.append, **options
    ):
        found.append((line, stored[-1]))
    return found


def _first(folder: Path) -> tuple[dict[str, Any], bytes]:
    by_session = {line["payload"]["extra"]["session"]: (line, data) for line, data in _run(folder)}
    return by_session[cs.SESSION]


# -- sniff -------------------------------------------------------------------------------------------


def test_sniff_knows_the_projects_folder_a_project_and_a_session(folder: Path):
    project = folder / cs.PROJECT
    assert claude_code.sniff(folder) and claude_code.sniff(project)
    assert claude_code.sniff(project / f"{cs.SESSION}.jsonl")
    assert adapters.find(folder) is claude_code


def test_sniff_says_no_to_observations_and_other_files(tmp_path: Path):
    observations = tmp_path / "lines.jsonl"
    observations.write_text(
        json.dumps({"at": "2026-03-01T10:00:00Z", "source": "manual", "payload": {}}) + "\n"
    )
    assert not claude_code.sniff(observations)
    (tmp_path / "garbage.jsonl").write_bytes(b"\x00\xff")
    assert not claude_code.sniff(tmp_path / "garbage.jsonl")
    assert not claude_code.sniff(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    assert not claude_code.sniff(tmp_path / "empty")


# -- the line ----------------------------------------------------------------------------------------


def test_one_transcript_line_per_session_and_a_subagents_file_is_not_one(folder: Path):
    counts: dict[str, int] = {}
    lines = _run(folder, counts)
    assert sorted(line["payload"]["extra"]["session"] for line, _data in lines) == [cs.SESSION, cs.SECOND]
    assert counts["skipped_subagent"] == 1
    for line, _data in lines:
        assert (line["kind"], line["source"], line["tier"]) == ("transcript", "claude-code", 2)
        assert line["payload"]["schema"] == "transcript/v1" and line["payload"]["provider"] == "claude-code"


def test_the_session_spans_its_first_and_last_entry(folder: Path):
    line, _data = _first(folder)
    assert line["at"] == cs.at(0) and line["end"] == cs.at(74)


def test_the_owner_speaks_as_owner_and_the_assistant_is_a_machine_participant(folder: Path):
    line, _data = _first(folder)
    participants = line["payload"]["participants"]
    assert participants == [{"name": "owner"}, {"name": "assistant", "machine": True}]
    assert machine.labels(participants) == frozenset({"assistant"})


def test_the_text_is_the_turns_and_nothing_else(folder: Path):
    line, data = _first(folder)
    turns = json.loads(data)["turns"]
    assert turns == [
        {"speaker": "owner", "text": cs.OWNER_FIRST},
        {"speaker": "assistant", "text": cs.MACHINE_FIRST},
        {"speaker": "owner", "text": cs.OWNER_SECOND},
        {"speaker": "assistant", "text": cs.MACHINE_SECOND},
    ]
    text = data.decode("utf-8") + json.dumps(line, ensure_ascii=False)
    for canary in CANARIES:
        assert canary not in text, canary


def test_tool_calls_are_a_count_and_their_output_is_never_kept(folder: Path):
    line, _data = _first(folder)
    extra = line["payload"]["extra"]
    assert extra["tool_calls"] == 2 and extra["tools"] == {"Bash": 1, "Edit": 1}
    assert extra["images"] == 1


def test_a_digest_and_the_words_of_each_side(folder: Path):
    line, data = _first(folder)
    content = line["payload"]["content"]
    assert content["media_type"] == "application/json" and content["bytes"] == len(data)
    assert content["sha256"] == hashlib.sha256(data).hexdigest()
    words = line["payload"]["extra"]["words"]
    assert words == {
        "owner": len(cs.OWNER_FIRST.split()) + len(cs.OWNER_SECOND.split()),
        "machine": len(cs.MACHINE_FIRST.split()) + len(cs.MACHINE_SECOND.split()),
    }


def test_the_session_and_the_project_are_references(folder: Path):
    line, _data = _first(folder)
    payload = line["payload"]
    assert payload["raw_id"] == f"claude-code:{cs.SESSION}"
    extra = payload["extra"]
    assert extra["session"] == cs.SESSION and extra["project"] == "solvind-log" and extra["cwd"] == cs.CWD
    assert extra["models"] == [cs.MODEL] and extra["git_branch"] == "main"
    assert machine.agent_of(payload) == {
        "kind": "agent",
        "ref": {"kind": "provider_id", "value": "claude-code"},
        "name": "Claude Code",
    }
    assert payload["title"] == "Passage planner for Solvind"


def test_skips_are_counted(folder: Path):
    counts: dict[str, int] = {}
    _run(folder, counts)
    assert counts["skipped_sidechain"] == 2 and counts["skipped_unreadable_row"] == 1


def test_a_session_with_no_turns_is_skipped(tmp_path: Path):
    cs.write(tmp_path / "p" / "s.jsonl", [{"type": "summary", "summary": "nothing", "leafUuid": "x"}])
    counts: dict[str, int] = {}
    assert _run(tmp_path / "p", counts) == [] and counts["skipped_empty"] == 1


def test_since_leaves_out_a_session_that_ended_before(folder: Path):
    lines = _run(folder, since=cs.at(3600))
    assert [line["payload"]["extra"]["session"] for line, _d in lines] == [cs.SECOND]


def test_a_session_without_a_summary_is_titled_by_the_owners_first_words(folder: Path):
    by_session = {line["payload"]["extra"]["session"]: line for line, _d in _run(folder)}
    assert by_session[cs.SECOND]["payload"]["title"] == "Add the moon phase to the planner, please."


def test_a_sealed_line_this_machine_cannot_open_is_never_written_again(folder: Path):
    sealed = {"id": "line-1", "payload": {"schema": "sealed/v1", "of": "transcript/v1", "digest": "0" * 64}}

    def existing(keys: Any) -> dict[tuple[str, str], dict[str, Any]]:
        return {key: sealed for key in keys if key == ("claude-code", f"claude-code:{cs.SESSION}")}

    counts: dict[str, int] = {}
    lines = list(claude_code.run(folder, counts=counts, existing=existing))
    first = next(line for line in lines if line["payload"]["extra"]["session"] == cs.SESSION)
    assert first["payload"]["raw_id"] == f"claude-code:{cs.SESSION}" and "supersedes" not in first["payload"]
    assert "grown" not in counts


def test_a_stray_file_in_the_projects_folder_hides_no_project(folder: Path):
    (folder / "notes.jsonl").write_text('{"anything": 1}\n', encoding="utf-8")
    sessions = sorted(line["payload"]["extra"]["session"] for line, _data in _run(folder))
    assert sessions == [cs.SESSION, cs.SECOND]


def test_a_session_file_alone_is_read(folder: Path):
    ((line, _data),) = _run(folder / cs.PROJECT / f"{cs.SECOND}.jsonl")
    assert line["payload"]["extra"]["session"] == cs.SECOND


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


def _transcripts(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return list(idx.by_kind("transcript"))


def test_add_claude_sessions_stores_the_turns_and_reads_them_back(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
):
    code, out = _cli(capsys, "add", "claude-sessions", str(folder))
    assert code == 0 and "added 2 lines from claude-code" in out
    first = next(t for t in _transcripts(lb) if t["payload"]["extra"]["session"] == cs.SESSION)
    turns = turns_of(lb, first)
    assert turns is not None and [t.speaker for t in turns] == ["owner", "assistant", "owner", "assistant"]
    code, out = _cli(capsys, "add", "claude-sessions", str(folder))
    assert "added 0 lines from claude-code" in out and "2 already in the record" in out


def test_a_session_that_grew_supersedes_the_line_before(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
):
    assert _cli(capsys, "add", "claude-sessions", str(folder))[0] == 0
    session = folder / cs.PROJECT / f"{cs.SESSION}.jsonl"
    grown = [*cs.entries(), cs.user(200, 30, "One more thing: I'll print the plan for the cockpit.")]
    cs.write(session, grown)
    code, out = _cli(capsys, "add", "claude-sessions", str(folder))
    assert code == 0 and "added 1 lines from claude-code" in out and "1 grown since the last import" in out
    lines = [t for t in _transcripts(lb) if t["payload"]["extra"]["session"] == cs.SESSION]
    old, new = sorted(lines, key=lambda t: t["seq"])
    assert new["payload"]["raw_id"] == f"claude-code:{cs.SESSION}:v2"
    assert new["payload"]["supersedes"] == old["id"] and new["end"] == cs.at(200)
    cs.write(session, [*grown, cs.user(300, 31, "And a copy for the chart table.")])
    assert _cli(capsys, "add", "claude-sessions", str(folder))[0] == 0
    newest = max(
        (t for t in _transcripts(lb) if t["payload"]["extra"]["session"] == cs.SESSION),
        key=lambda t: t["seq"],
    )
    assert (
        newest["payload"]["raw_id"] == f"claude-code:{cs.SESSION}:v3"
        and newest["payload"]["supersedes"] == new["id"]
    )
    seq, _head, errors = lb.verify()
    assert not errors and seq == 4
