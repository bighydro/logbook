"""The owner's own bots in the Beeper adapters: the machine mark (docs/adapters/agents.md), driven by
the sender ids `policy/agents.json` names (`logbook setup agents`), never by a list in the code; and
the `agents` line of `logbook doctor`, the lines marked machine per source.

On the persona record: the Oslo owner, who does not exist, with a Telegram bot of their own bridged
through Beeper. Every id, number and name here is synthetic."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_beeper import OWNER, PER, ROOM_B, T0, _blob, _store
from test_beeper_live import TOKEN, TOKEN_ENV, URL_ENV, FakeBeeper, _chat, _message, _user

from logbook import cli
from logbook.contrib import doctor
from logbook.contrib.adapters import beeper, beeper_live
from logbook.core import machine, policy
from logbook.core.store import Logbook

BOT = "@telegram_900000001:beeper.local"  # the owner's own bot, as Beeper names its sender
ROOM_BOT = "!fyr:beeper.local"
LIVE_BOT = "@telegram_900000002:beeper.local"
LIVE_ME = "@telegram_kari:beeper.local"
TG_BOT = "!tg-fyr:beeper.local"
TG_ACCOUNT = "local-telegram"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _cli(*args: str) -> int:
    try:
        cli.main(list(args))
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    return 0


def _with_bot(folder: Path) -> Path:
    """The test_beeper store, and one more room: a direct chat with the owner's bot, which also sits
    in the sailing crew's group and speaks there once."""
    path = _store(folder)
    con = sqlite3.connect(path)
    try:
        con.execute(
            "INSERT INTO ZROOMITEMMO VALUES (4,1,1,1,?,?,?,?,?)", (T0, "Fyr", "telegram", ROOM_BOT, "other")
        )
        con.executemany(
            "INSERT INTO ZROOMMEMBERMO VALUES (NULL,1,1,?,?,?,?,?,?,?,?)",
            [
                ("join", "Kari", ROOM_BOT, OWNER, None, None, None, 0),
                ("join", "Fyr", ROOM_BOT, BOT, None, None, None, 0),
                ("join", "Fyr", ROOM_B, BOT, None, None, None, 0),
            ],
        )
        text = {"msgtype": "m.text"}
        con.executemany(
            "INSERT INTO ZBSEVENT VALUES (?,1,1,?,?,700000000,?,?,?)",
            [
                (
                    20,
                    0,
                    0,
                    "$bot1",
                    ROOM_BOT,
                    _blob(20, ROOM_BOT, OWNER, 30000, {**text, "body": "ferry times?"}),
                ),
                (
                    21,
                    0,
                    0,
                    "$bot2",
                    ROOM_BOT,
                    _blob(21, ROOM_BOT, BOT, 31000, {**text, "body": "07:30, 09:10"}),
                ),
                (22, 0, 0, "$bot3", ROOM_B, _blob(22, ROOM_B, BOT, 32000, {**text, "body": "wind 6 m/s"})),
            ],
        )
        con.commit()
    finally:
        con.close()
    return path


def _by_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


def _marked(line: dict[str, Any]) -> bool:
    return machine.is_machine(line["payload"]) or machine.with_agent(line["payload"])


def _agents(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(policy.agents_path(lb.root).read_text(encoding="utf-8"))
    return data


# -- the setting -------------------------------------------------------------------------------------


def test_a_record_without_the_file_names_no_agent_and_reading_writes_nothing(lb: Logbook) -> None:
    assert policy.agent_senders(lb.root) == {}
    assert not policy.agents_path(lb.root).exists()


def test_adding_naming_and_removing_a_sender(lb: Logbook) -> None:
    assert policy.agent_add(lb.root, BOT) is True
    assert policy.agent_add(lb.root, BOT) is False  # already there, as it is
    assert policy.agent_senders(lb.root) == {BOT: None}
    assert policy.agent_add(lb.root, f"  {BOT} ", "Fyr") is True  # the name is new
    assert policy.agent_senders(lb.root) == {BOT: "Fyr"}
    assert _agents(lb) == {"senders": [{"id": BOT, "name": "Fyr"}]}
    assert policy.agent_remove(lb.root, BOT) is True
    assert policy.agent_remove(lb.root, BOT) is False
    assert policy.agent_senders(lb.root) == {}


def test_a_file_that_is_not_the_shape_is_refused_naming_it(lb: Logbook) -> None:
    path = policy.agents_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    for broken in ("not json", '{"senders": "x"}', '{"senders": [{"name": "Fyr"}]}', "[]"):
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(policy.PolicyError, match=r"agents\.json"):
            policy.agent_senders(lb.root)


def test_a_blank_sender_is_refused(lb: Logbook) -> None:
    with pytest.raises(policy.PolicyError, match="sender id"):
        policy.agent_add(lb.root, "  ")


# -- the phone's cache (`beeper`) -----------------------------------------------------------------------


def test_without_agents_no_beeper_line_is_marked(tmp_path: Path) -> None:
    lines = list(beeper.run(_with_bot(tmp_path)))
    assert not any(
        machine.is_machine(line["payload"]) or machine.with_agent(line["payload"]) for line in lines
    )


def test_a_named_bot_in_a_direct_chat_marks_its_lines_and_the_conversation(tmp_path: Path) -> None:
    lines = _by_id(list(beeper.run(_with_bot(tmp_path), agents={BOT: "Fyr"})))
    counterpart = {"kind": "agent", "ref": {"kind": "handle", "value": BOT}, "name": "Fyr"}
    asked, answered = lines["$bot1"]["payload"], lines["$bot2"]["payload"]
    assert asked["from_me"] is True and not machine.is_machine(asked)
    assert asked["extra"]["counterpart"] == counterpart  # the owner's side of a chat with an agent
    assert answered["from_me"] is False and answered["extra"]["machine"] is True
    assert answered["extra"]["counterpart"] == counterpart
    assert answered["text"] == "07:30, 09:10"  # the words are kept, marked as the machine's


def test_a_named_bot_in_a_group_marks_its_own_lines_and_never_the_peoples(tmp_path: Path) -> None:
    lines = _by_id(list(beeper.run(_with_bot(tmp_path), agents={BOT: None})))
    bot = lines["$bot3"]["payload"]
    assert bot["extra"]["machine"] is True and not machine.with_agent(bot)  # a group is not a chat with it
    for raw_id in ("$ev2", "$last-b"):  # the owner and Per, in the same group
        assert not machine.is_machine(lines[raw_id]["payload"])
        assert not machine.with_agent(lines[raw_id]["payload"])
    assert lines["$last-b"]["payload"]["extra"]["matrix_user"] == PER


def test_a_named_bot_without_a_name_takes_the_one_the_member_row_gives(tmp_path: Path) -> None:
    lines = _by_id(list(beeper.run(_with_bot(tmp_path), agents={BOT: None})))
    assert lines["$bot2"]["payload"]["extra"]["counterpart"]["name"] == "Fyr"


def test_add_reads_the_agents_from_the_records_settings(lb: Logbook, tmp_path: Path) -> None:
    store = _with_bot(tmp_path / "backup")
    assert _cli("setup", "agents", "add", BOT, "--name", "Fyr") == 0
    assert _cli("add", "beeper", str(store)) == 0
    lines = _by_id([dict(line) for line in lb.lines_unsorted() if line.get("source") == "beeper"])
    assert lines["$bot2"]["payload"]["extra"]["machine"] is True
    assert lines["$bot1"]["payload"]["extra"]["counterpart"]["name"] == "Fyr"
    assert not machine.is_machine(lines["$ev1"]["payload"])


# -- the desktop's API (`sync beeper`) ----------------------------------------------------------------


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    server = FakeBeeper()
    server.accounts.append(
        {
            "accountID": TG_ACCOUNT,
            "network": "Telegram",
            "status": "connected",
            "user": {"id": LIVE_ME, "fullName": "Kari", "isSelf": True},
        }
    )
    server.chats.append(
        _chat(
            TG_BOT,
            TG_ACCOUNT,
            "Telegram",
            "single",
            "Fyr",
            _user(LIVE_ME, "Kari", isSelf=True),
            _user(LIVE_BOT, "Fyr bot", username="fyr_example_bot"),
        )
    )
    server.messages[TG_BOT] = [
        _message(TG_BOT, TG_ACCOUNT, "$tg1", LIVE_ME, 60, "tide tomorrow?", isSender=True),
        _message(TG_BOT, TG_ACCOUNT, "$tg2", LIVE_BOT, 61, "high water 06:12"),
    ]
    server.start()
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv(URL_ENV, server.url)
    try:
        yield server
    finally:
        server.stop()


def test_pull_marks_a_named_sender_and_the_direct_chat_with_it(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    lines = _by_id(list(beeper_live.pull(config, agents={LIVE_BOT: "Fyr"})))
    asked = lines[f"{TG_ACCOUNT}/{TG_BOT}/$tg1"]["payload"]
    answered = lines[f"{TG_ACCOUNT}/{TG_BOT}/$tg2"]["payload"]
    counterpart = {"kind": "agent", "ref": {"kind": "handle", "value": LIVE_BOT}, "name": "Fyr"}
    assert asked["extra"]["counterpart"] == counterpart and not machine.is_machine(asked)
    assert answered["extra"]["machine"] is True and answered["extra"]["counterpart"] == counterpart
    people = [
        p for raw_id, line in lines.items() if not raw_id.startswith(TG_ACCOUNT) for p in [line["payload"]]
    ]
    assert people and not any(machine.is_machine(p) or machine.with_agent(p) for p in people)


def test_pull_without_agents_marks_nothing(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    lines = list(beeper_live.pull(config))
    assert not any(
        machine.is_machine(line["payload"]) or machine.with_agent(line["payload"]) for line in lines
    )


def test_sync_reads_the_agents_from_the_records_settings(lb: Logbook, fake: FakeBeeper) -> None:
    policy.agent_add(lb.root, LIVE_BOT)
    assert _cli("sync", "beeper", "--networks", "telegram") == 0
    lines = _by_id([dict(line) for line in lb.lines_unsorted() if line.get("kind") == "message"])
    answered = lines[f"{TG_ACCOUNT}/{TG_BOT}/$tg2"]
    assert answered["source"] == "beeper-telegram" and answered["payload"]["extra"]["machine"] is True
    assert answered["payload"]["extra"]["counterpart"]["name"] == "Fyr bot"  # the app's, none in the setting


# -- `logbook setup agents` --------------------------------------------------------------------------


def test_setup_agents_lists_adds_and_removes(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli("setup", "agents", "list") == 0
    assert "no agent named" in capsys.readouterr().out
    assert _cli("setup", "agents", "add", BOT, "--name", "Fyr") == 0
    out = capsys.readouterr().out
    assert BOT in out and "Fyr" in out and "already in the record keep" in out
    assert _cli("setup", "agents", "add", BOT, "--name", "Fyr") == 0
    assert "already named" in capsys.readouterr().out
    assert _cli("setup", "agents", "list") == 0
    assert f"{BOT}  Fyr" in capsys.readouterr().out
    assert _cli("setup", "agents", "remove", BOT) == 0
    assert policy.agent_senders(lb.root) == {}
    assert _cli("setup", "agents", "remove", BOT) == 2
    assert "names no agent" in capsys.readouterr().err


def test_setup_agents_on_a_broken_file_is_one_sentence(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    path = policy.agents_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    assert _cli("setup", "agents", "list") == 2
    err = capsys.readouterr().err
    assert "agents.json" in err and "Traceback" not in err


# -- `logbook doctor`: the lines marked machine, per source ---------------------------------------------


def _agents_check(lb: Logbook) -> doctor.Check | None:
    return next((c for c in doctor.run(lb, {}) if c.name == "agents"), None)


def test_doctor_has_no_agents_line_on_a_record_without_agents(lb: Logbook) -> None:
    assert _agents_check(lb) is None


def test_doctor_counts_the_lines_marked_machine_per_source(lb: Logbook, tmp_path: Path) -> None:
    policy.agent_add(lb.root, BOT, "Fyr")
    assert _cli("add", "beeper", str(_with_bot(tmp_path / "backup"))) == 0
    lb.append(
        at="2026-03-01T10:00:00Z",
        source="claude-code",
        kind="transcript",
        tier=2,
        payload={
            "schema": "transcript/v1",
            "provider": "claude-code",
            "raw_id": "claude-code:session-1",
            "participants": [{"name": "owner"}, {"name": "assistant", "machine": True}],
        },
    )
    for state in ("current", "stale"):
        if state == "current":
            lb.index_rebuild()
        else:
            lb.index_path.unlink()
        check = _agents_check(lb)
        assert check is not None and check.status == "pass"
        assert check.detail.startswith("lines marked machine: beeper 2, claude-code 1")
        assert "1 sender named in policy/agents.json" in check.detail


def test_doctor_says_when_agents_are_named_and_no_line_is_marked(lb: Logbook) -> None:
    policy.agent_add(lb.root, BOT)
    check = _agents_check(lb)
    assert check is not None and check.status == "pass"
    assert check.detail.startswith("no line marked machine yet")


def test_doctor_fails_the_agents_line_on_a_broken_file(lb: Logbook) -> None:
    path = policy.agents_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")
    check = _agents_check(lb)
    assert check is not None and check.status == "fail" and "agents.json" in check.detail
