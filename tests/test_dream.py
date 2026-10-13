"""`logbook dream day DAY`, `logbook dream --catch-up` (RFC 0036, `draft/v1`): a model reads one day
under the `dream` entry of `policy/crossing.json` and writes one draft line, every segment with its
evidence or marked unsupported. The model endpoint is an in-process fake of an OpenAI-compatible
chat completions server (`model_client.send` replaced); no test opens a connection (`no_network`).
Synthetic Oslo persona, who does not exist; the example.org addresses and the reserved +47 9000
000x numbers of the project's fixtures."""

from __future__ import annotations

import contextlib
import io
import json
import urllib.error
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, KARI, KARI_ID, dwell, note, resolution, utc

from logbook import cli
from logbook.contrib import doctor, dream, model_client, serve
from logbook.core import day as day_reader
from logbook.core import drafts, policy
from logbook.core.store import Logbook

DAY, NEXT = "2026-06-10", "2026-06-11"
MODEL = "qwen2.5-7b-instruct"
ENV = {
    model_client.ENDPOINT_ENV: "http://127.0.0.1:8080/v1",
    model_client.MODEL_ENV: MODEL,
}
NOTE_TEXT = "Lunch with Kari Nordmann at the cafe; she promised to send the boat plans."
HEALTH_TEXT = "Resting heart rate 52 bpm this morning."
MESSAGE_TEXT = "Ses i morgen ved marinaen?"
Fake = Callable[..., dict[str, Any]]


def _message(at: str, text: str, from_me: bool = False) -> dict[str, Any]:
    return {
        "at": at,
        "source": "imessage",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "chat": {"type": "direct", "id": "chat-1", "name": "Kari"},
            "sender": {"kind": "phone", "value": KARI["phone"]},
            "from_me": from_me,
            "text": text,
            "raw_id": f"msg:{at}",
        },
    }


def _drafts() -> list[dict[str, Any]]:
    """Two days at home: the first with a tier-2 note and message, a tier-3 line and a
    commitment; the second with a note only."""
    found: list[dict[str, Any]] = [
        resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
    ]
    found += dwell(DAY, "08:00", "18:00", HOME, every_min=20)
    found.append(note(utc(DAY, "12:30"), NOTE_TEXT))
    found.append({**note(utc(DAY, "07:30"), HEALTH_TEXT), "tier": 3})
    found.append(_message(utc(DAY, "16:00"), MESSAGE_TEXT))
    found.append(_message(utc(DAY, "16:05"), "Ja, klokka ti.", from_me=True))
    found.append(
        {
            "at": utc(DAY, "12:45"),
            "source": "manual",
            "kind": "commitment",
            "tier": 2,
            "payload": {
                "schema": "commitment/v1",
                "text": "send the boat plans",
                "direction": "owed_to_owner",
                "counterparty": {"kind": "email", "value": KARI["email"]},
            },
        }
    )
    found += dwell(NEXT, "08:00", "18:00", HOME, every_min=20)
    found.append(note(utc(NEXT, "19:00"), "A quiet evening at home."))
    return found


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    lb.append_many(_drafts())
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    _policy(lb, {"max_tier": 2, "until": "2026-12-31"})
    return lb


def _policy(lb: Logbook, entry: dict[str, Any] | None) -> None:
    data: dict[str, Any] = {"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}}
    if entry is not None:
        data[policy.DREAM_DESTINATION] = entry
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")


def _answer(material: dict[str, Any], **parts: list[dict[str, Any]]) -> dict[str, Any]:
    """A plausible answer from the material: the day's stays and notes cited; `parts` override."""
    stays = [r for e in material["timeline"] for r in e["ref"]]
    notes = [n["ref"] for n in material["notes"]]
    found: dict[str, Any] = {
        "day": [
            {"text": "A day at home.", "evidence": stays[:1]},
            {"text": "You wrote about lunch.", "evidence": notes[:1] or stays[:1]},
        ],
        "threads": [],
        "questions": [
            {"text": "What came of the lunch?", "evidence": notes[:1] or stays[:1]},
            {"text": "Was the evening what you wanted?", "unsupported": True},
        ],
        "people": [],
        "promises": [],
    }
    found.update(parts)
    return found


def _fake(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[dict[str, Any]], Any] | None = None
) -> dict[str, Any]:
    """`model_client.send` replaced by an in-process fake: what it was sent is in the returned
    dict (`calls`, each the request body; `prompt`, the last system text; `material`, the last
    material as the model got it). `answer` makes the completion from the material; the default
    is `_answer`. A string answer is sent as is."""
    seen: dict[str, Any] = {"calls": [], "statuses": []}

    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        seen["url"], seen["headers"], seen["timeout"] = url, headers, timeout
        seen["calls"].append(body)
        seen["prompt"] = body["messages"][0]["content"]
        seen["material"] = json.loads(body["messages"][1]["content"])
        made = (answer or _answer)(seen["material"])
        text = made if isinstance(made, str) else json.dumps(made)
        return {"choices": [{"message": {"content": text}}]}

    monkeypatch.setattr(model_client, "send", send)
    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)
    return seen


def _cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()


def _draft_lines(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == drafts.KIND]


# -- the policy ----------------------------------------------------------------------------------------------


def test_no_dream_entry_refuses_and_sends_nothing(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    _policy(lb, None)
    seen = _fake(monkeypatch)
    seq = lb.meta["seq"]
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 2 and "policy/crossing.json" in err and "'dream'" in err and "no day crosses" in err
    assert seen["calls"] == [] and lb.meta["seq"] == seq and no_network == []


def test_an_expired_entry_refuses(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    _policy(lb, {"max_tier": 2, "until": "2026-06-01"})
    seen = _fake(monkeypatch)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 2 and "expired on 2026-06-01" in err and "max_tier 0" in err
    assert seen["calls"] == [] and _draft_lines(lb) == []


def test_the_policy_model_wins_and_a_different_variable_is_refused(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _policy(lb, {"max_tier": 2, "model": "local-3b"})
    seen = _fake(monkeypatch)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 2 and "local-3b" in err and MODEL in err and seen["calls"] == []
    monkeypatch.delenv(model_client.MODEL_ENV)
    code, out, _err = _cli("dream", "day", DAY)
    assert code == 0, out
    assert seen["calls"][-1]["model"] == "local-3b" and _draft_lines(lb)[-1]["source"] == "model:local-3b"


def test_a_missing_endpoint_variable_is_said(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    monkeypatch.delenv(model_client.ENDPOINT_ENV)
    seen = _fake(monkeypatch)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 2 and model_client.ENDPOINT_ENV in err and seen["calls"] == []


def test_doctor_lists_the_dream_entry_with_its_model(lb: Logbook) -> None:
    _policy(lb, {"max_tier": 2, "until": "2026-12-31", "model": MODEL})
    checks = {c.name: c for c in doctor.run(lb, {}, installed=lambda _m: True)}
    assert checks["crossing"].status == "pass"
    assert f"dream 2 until 2026-12-31 model {MODEL}" in checks["crossing"].detail


# -- the ceiling ---------------------------------------------------------------------------------------------


def test_a_tier_3_line_never_reaches_the_prompt_under_max_tier_2(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = _fake(monkeypatch)
    code, out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    sent = json.dumps(seen["calls"][-1])
    assert HEALTH_TEXT not in sent and "52" not in sent
    assert NOTE_TEXT in sent and MESSAGE_TEXT in sent  # tier 2 is under the ceiling: text allowed
    assert seen["material"]["max_tier"] == 2
    by = {m["counterpart"]: m for m in seen["material"]["messages"]}
    assert by["Kari Nordmann"]["count"] == 2 and by["Kari Nordmann"]["texts"][0]["text"] == MESSAGE_TEXT
    line = _draft_lines(lb)[-1]
    assert line["tier"] == 2 and "tier 2" in out


def test_under_max_tier_1_no_message_and_no_note_reaches_the_prompt(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _policy(lb, {"max_tier": 1})
    seen = _fake(monkeypatch)
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    sent = json.dumps(seen["calls"][-1])
    assert NOTE_TEXT not in sent and MESSAGE_TEXT not in sent and HEALTH_TEXT not in sent
    assert "Kari" not in sent and seen["material"]["messages"] == [] and seen["material"]["notes"] == []
    line = _draft_lines(lb)[-1]
    assert line["tier"] == 1  # the highest tier it read, not the ceiling
    assert line["payload"]["read_count"] == sum(
        1 for found in lb.lines() if found["tier"] == 1 and found["at"].startswith("2026-06-10")
    )


# -- the answer ----------------------------------------------------------------------------------------------


def test_a_valid_answer_writes_one_draft_with_what_it_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = _fake(monkeypatch)
    head, seq = lb.meta["head"], lb.meta["seq"]
    code, out, err = _cli("dream", "day", DAY)
    assert code == 0, err
    assert lb.meta["seq"] == seq + 1 and no_network == []
    (line,) = _draft_lines(lb)
    p = line["payload"]
    assert line["kind"] == "draft" and line["source"] == f"model:{MODEL}" and line["tier"] == 2
    assert p["schema"] == "draft/v1" and p["unit"] == "day" and p["subject"] == DAY
    assert p["read_head"] == head
    on_day = [
        found
        for found in lb.lines()
        if found["at"].startswith("2026-06-10") and found["tier"] <= 2 and found["kind"] != "draft"
    ]
    assert p["read_count"] == len(on_day)
    assert p["language"] == "en" and "supersedes" not in p
    assert p["extra"]["prompt"] == dream.PROMPT_NAME and p["extra"]["parts"] == [
        "day",
        "day",
        "questions",
        "questions",
    ]
    assert drafts.validate(p) == []
    supported = [s for s in p["segments"] if "evidence" in s]
    ids = {found["id"] for found in on_day}
    assert supported and all(set(s["evidence"]) <= ids for s in supported)
    assert p["segments"][-1] == {"text": "Was the evening what you wanted?", "unsupported": True}
    assert f"dreamed as #{line['seq']} draft/v1" in out and "1 unsupported" in out
    assert "~ question  Was the evening what you wanted?  unsupported" in out
    assert seen["headers"].get("Authorization") is None  # no key, no header
    assert seen["url"] == "http://127.0.0.1:8080/v1/chat/completions"


def test_the_prompt_says_the_language_of_the_day(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    seen = _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    assert "Write in English (BCP 47 `en`)" in seen["prompt"]
    lb.append(
        utc(NEXT, "20:00"),
        "manual",
        "note",
        2,
        {"schema": "note/v1", "text": "Det var en rolig kveld hjemme."},
    )
    lb.append(utc(NEXT, "20:10"), "manual", "note", 2, {"schema": "note/v1", "text": "Jeg er glad for det."})
    assert _cli("dream", "day", NEXT)[0] == 0
    assert "Write in Norwegian (BCP 47 `nb`)" in seen["prompt"]
    assert _draft_lines(lb)[-1]["payload"]["language"] == "nb"


def test_an_evidence_id_the_day_does_not_have_makes_the_segment_unsupported(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(material: dict[str, Any]) -> dict[str, Any]:
        stays = material["timeline"][0]["ref"][:1]
        return _answer(
            material,
            questions=[{"text": "Why?", "evidence": stays}, {"text": "How?", "evidence": stays}],
            people=[{"text": "Ola Nordmann was there.", "evidence": ["L999"]}],
        )

    _fake(monkeypatch, answer)
    code, out, _err = _cli("dream", "day", DAY)
    assert code == 0
    p = _draft_lines(lb)[-1]["payload"]
    assert p["segments"][-1] == {"text": "Ola Nordmann was there.", "unsupported": True}
    assert "~ people    Ola Nordmann was there.  unsupported" in out


def test_too_many_unsupported_segments_refuse_and_write_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(material: dict[str, Any]) -> dict[str, Any]:
        return {
            "day": [{"text": "A day.", "evidence": material["timeline"][0]["ref"][:1]}],
            "questions": [{"text": "Why?", "unsupported": True}, {"text": "How?", "evidence": ["nope"]}],
        }

    _fake(monkeypatch, answer)
    seq = lb.meta["seq"]
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 1 and "2 of 3 segments rest on no line" in err and "nothing was written" in err
    assert lb.meta["seq"] == seq and _draft_lines(lb) == []


def test_an_answer_that_is_not_json_is_refused(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    _fake(monkeypatch, lambda _m: "I cannot do that.")
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 1 and "not one JSON object" in err and _draft_lines(lb) == []


def test_a_fenced_answer_is_read(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    _fake(monkeypatch, lambda m: "Here you go:\n```json\n" + json.dumps(_answer(m)) + "\n```\n")
    assert _cli("dream", "day", DAY)[0] == 0 and len(_draft_lines(lb)) == 1


def test_dry_run_asks_the_model_and_writes_nothing(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    seen = _fake(monkeypatch)
    seq = lb.meta["seq"]
    code, out, _err = _cli("dream", "day", DAY, "--dry-run", "--show-prompt")
    assert code == 0 and "dry run, nothing written" in out
    assert len(seen["calls"]) == 1 and lb.meta["seq"] == seq
    assert "Rules, each of them strict" in out and NOTE_TEXT in out  # the prompt and the material shown


def test_the_log_never_holds_the_material(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    """The draft line carries the model's segments and ids, never the prompt, the material or
    the day's text the model was shown."""
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    (line,) = _draft_lines(lb)
    text = json.dumps(line)
    assert "Kari Nordmann" not in text and NOTE_TEXT not in text and MESSAGE_TEXT not in text
    assert "L1" not in json.dumps(line["payload"]["segments"])  # ids, never references


def test_the_same_model_at_the_same_head_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    (line,) = _draft_lines(lb)
    head = lb.meta["head"]
    # the draft moved the head; put the standing draft's read_head where the head is now
    monkeypatch.setattr(
        drafts,
        "standing",
        lambda found: {**line, "payload": {**line["payload"], "read_head": head}} if found else None,
    )
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 2 and "already" in err and f"#{line['seq']}" in err and len(_draft_lines(lb)) == 1


# -- dreaming again ------------------------------------------------------------------------------------------


def test_dreaming_a_day_again_supersedes_the_standing_draft(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    first = _draft_lines(lb)[-1]
    code, out, _err = _cli("dream", "day", DAY)
    assert code == 0 and f"supersedes {first['id']}" in out
    first, second = _draft_lines(lb)
    assert second["payload"]["supersedes"] == first["id"] and second["payload"]["read_head"] == first["hash"]
    data = day_reader.read(lb, DAY)
    assert data["draft"]["line"] == second["id"] and data["draft"]["supersedes"] == first["id"]
    assert data["draft"]["earlier"] == [first["id"]] and data["draft"]["dreamed"] == 2
    # the earlier draft is still in the record, reachable by id, never deleted
    with lb.index() as idx:
        assert idx.by_id(first["id"]) is not None
    assert "dreamed 2×" in _cli("day", DAY, "--no-anniversaries")[1]


# -- the head ------------------------------------------------------------------------------------------------


def test_a_head_that_moved_under_the_reading_is_head_moved_and_nothing_is_written(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def answer(material: dict[str, Any]) -> dict[str, Any]:
        other = Logbook(lb.root)  # a writer that ignored the lock, in this process: the lock re-enters
        other.append(utc(DAY, "17:00"), "manual", "note", 2, {"schema": "note/v1", "text": "Late note."})
        return _answer(material)

    _fake(monkeypatch, answer)
    seq = lb.meta["seq"]
    code, _out, err = _cli("dream", "day", DAY)
    assert code == 2 and "head moved" in err and "nothing was written" in err
    assert lb.meta["seq"] == seq + 1 and _draft_lines(lb) == []  # the other writer's note, no draft
    assert not (lb.root / "state" / "writer.lock").exists()


# -- catch-up ------------------------------------------------------------------------------------------------


def test_catch_up_dreams_a_changed_day_and_skips_an_unchanged_one(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = _fake(monkeypatch)
    monkeypatch.setattr(dream, "date", type("D", (), {"today": staticmethod(lambda: date(2026, 6, 12))}))
    code, out, _err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0, out
    rows = out.splitlines()
    assert rows[0].startswith("2026-06-09  empty     nothing logged")
    assert rows[1].startswith(f"{DAY}  dreamed   #") and "no draft yet" in rows[1]
    assert rows[2].startswith(f"{NEXT}  dreamed   #") and "no draft yet" in rows[2]
    assert rows[3] == "2 dreamed · 1 empty" and len(seen["calls"]) == 2
    code, out, _err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0
    assert "unchanged since #" in out.splitlines()[1] and "unchanged since #" in out.splitlines()[2]
    assert len(seen["calls"]) == 2  # nothing sent for an unchanged day
    lb.append(utc(NEXT, "21:00"), "manual", "note", 2, {"schema": "note/v1", "text": "One more line."})
    code, out, _err = _cli("dream", "--catch-up", "--days", "3")
    rows = out.splitlines()
    assert "unchanged" in rows[1] and rows[2].startswith(f"{NEXT}  dreamed") and "lines now" in rows[2]
    assert len(seen["calls"]) == 3
    assert [line["payload"]["subject"] for line in _draft_lines(lb)] == [DAY, NEXT, NEXT]
    assert _draft_lines(lb)[-1]["payload"]["supersedes"] == _draft_lines(lb)[1]["id"]


def test_catch_up_refuses_once_without_a_policy_entry(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _policy(lb, None)
    seen = _fake(monkeypatch)
    code, _out, err = _cli("dream", "--catch-up")
    assert code == 2 and "no 'dream' entry" in err and seen["calls"] == []


def test_a_refused_day_is_one_row_and_exit_1(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    def answer(material: dict[str, Any]) -> Any:
        return "nonsense" if material["day"] == NEXT else _answer(material)

    _fake(monkeypatch, answer)
    monkeypatch.setattr(dream, "date", type("D", (), {"today": staticmethod(lambda: date(2026, 6, 12))}))
    code, out, _err = _cli("dream", "--catch-up", "--days", "2")
    assert code == 1
    rows = out.splitlines()
    assert rows[0].startswith(f"{DAY}  dreamed") and rows[1].startswith(
        f"{NEXT}  refused   the model's answer"
    )
    assert rows[2] == "1 dreamed · 1 refused"


# -- the Day -----------------------------------------------------------------------------------------------


def test_the_day_shows_the_draft_above_the_timeline_and_hides_it_under_no_dream(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    (line,) = _draft_lines(lb)
    code, out, _err = _cli("day", DAY, "--no-anniversaries")
    assert code == 0
    rows = out.splitlines()
    head = next(i for i, row in enumerate(rows) if row.startswith("  draft "))
    assert f"model:{MODEL}" in rows[head] and f"read at {line['payload']['read_head'][:8]}" in rows[head]
    assert "dreamed 1×, last on" in rows[head] and "1 unsupported" in rows[head]
    assert rows[head + 1].startswith("      day       A day at home.  […")
    assert rows[head + 4] == "    ~ question  Was the evening what you wanted?  unsupported"
    timeline = next(i for i, row in enumerate(rows) if "stay   Home" in row)
    assert head < timeline  # above every note of the day
    code, out, _err = _cli("day", DAY, "--no-anniversaries", "--no-dream")
    assert code == 0 and "draft" not in out
    data = json.loads(_cli("day", DAY, "--json", "--no-anniversaries")[1])
    assert data["draft"]["line"] == line["id"] and data["draft"]["unsupported"] == 1
    assert data["draft"]["segments"][0]["supported"] is True and data["draft"]["segments"][0]["part"] == "day"
    assert "draft" not in json.loads(_cli("day", DAY, "--json", "--no-dream")[1])
    assert "draft" not in json.loads(_cli("day", NEXT, "--json", "--no-anniversaries")[1])


def test_an_evidence_id_not_on_the_day_is_shown_unsupported_and_said_why(lb: Logbook) -> None:
    """A draft that cites a line of another day (rule 6): the reader marks the segment and says."""
    with lb.index() as idx:
        elsewhere = idx.day(NEXT)[0]["id"]
        here = idx.day(DAY)[0]["id"]
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": lb.meta["head"],
        "read_count": 3,
        "language": "en",
        "segments": [
            {"text": "At home.", "evidence": [here]},
            {"text": "Elsewhere.", "evidence": [elsewhere]},
        ],
    }
    lb.append("2026-06-11T04:00:00Z", "model:x", "draft", 1, payload)
    data = day_reader.read(lb, DAY)
    assert data["draft"]["segments"][1]["supported"] is False
    assert data["draft"]["segments"][1]["why"] == drafts.NOT_ON_DAY
    _code, out, _err = _cli("day", DAY, "--no-anniversaries")
    assert "~           Elsewhere.  unsupported: evidence names a line that is not on the day" in out


def test_a_malformed_segment_is_unsupported_and_the_line_said_malformed(lb: Logbook) -> None:
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": lb.meta["head"],
        "read_count": 1,
        "language": "en",
        "segments": [{"text": "Both.", "evidence": [], "unsupported": False}],
    }
    assert drafts.validate(payload) == ["segment 1 is malformed: " + drafts.NOT_A_SEGMENT]
    lb.append("2026-06-11T04:00:00Z", "model:x", "draft", 1, payload)  # a reader meets one anyway
    data = day_reader.read(lb, DAY)
    assert data["draft"]["segments"][0]["supported"] is False and data["draft"]["malformed"]
    assert "malformed" in _cli("day", DAY, "--no-anniversaries")[1]


def test_show_lists_the_draft_line_on_the_day_it_was_written(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    (line,) = _draft_lines(lb)
    written = line["at"][:10]
    _code, out, _err = _cli("show", written)
    assert f"draft of day {DAY}" in out and "4 segments, 1 unsupported" in out


def test_serve_renders_the_draft_marked(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    site = serve.Site(lb)
    html = site.page_day(DAY)
    assert "<h2>Draft</h2>" in html and f"model:{MODEL}" in html
    assert 'class="segment unsupported mute"' in html and "~ Was the evening what you wanted?" in html
    assert html.index("<h2>Draft</h2>") < html.index("<h2>Timeline</h2>")


def test_a_draft_above_the_ceiling_is_not_on_a_gated_day(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0  # tier 2: it read the note
    assert "draft" not in day_reader.read(lb, DAY, tiers=(1,))
    assert day_reader.read(lb, DAY, tiers=(1, 2))["draft"] is not None


# -- the client ----------------------------------------------------------------------------------------------


def test_the_completions_url_is_formed_from_what_the_server_prints() -> None:
    assert (
        model_client.completions_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080/v1/chat/completions"
    )
    assert (
        model_client.completions_url("http://127.0.0.1:8080/v1/")
        == "http://127.0.0.1:8080/v1/chat/completions"
    )
    full = "https://api.example.org/v1/chat/completions"
    assert model_client.completions_url(full) == full
    assert (
        model_client.completions_url("https://api.example.org/openai")
        == "https://api.example.org/openai/chat/completions"
    )


def test_the_client_retries_once_on_a_server_error_and_not_on_a_client_error(no_network) -> None:
    calls: list[int] = []

    def flaky(url: str, body: dict[str, Any], headers: Any, timeout: float) -> dict[str, Any]:
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)  # type: ignore[arg-type]
        return {"choices": [{"message": {"content": "ok"}}]}

    ep = model_client.Endpoint("http://127.0.0.1:1/v1/chat/completions", "m", "secret-key")
    assert (
        model_client.complete(ep, [{"role": "user", "content": "x"}], transport=flaky, pause=lambda _s: None)
        == "ok"
    )
    assert len(calls) == 2

    def refused(url: str, body: dict[str, Any], headers: Any, timeout: float) -> dict[str, Any]:
        calls.append(1)
        raise urllib.error.HTTPError(url, 401, "unauthorized", {}, None)  # type: ignore[arg-type]

    calls.clear()
    with pytest.raises(model_client.ModelError, match="HTTP 401"):
        model_client.complete(
            ep, [{"role": "user", "content": "x"}], transport=refused, pause=lambda _s: None
        )
    assert len(calls) == 1

    def down(url: str, body: dict[str, Any], headers: Any, timeout: float) -> dict[str, Any]:
        calls.append(1)
        raise urllib.error.URLError("connection refused")

    calls.clear()
    with pytest.raises(model_client.ModelError, match="2 attempts"):
        model_client.complete(ep, [{"role": "user", "content": "x"}], transport=down, pause=lambda _s: None)
    assert len(calls) == 2 and no_network == []


def test_the_key_goes_in_the_bearer_header_when_set(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    monkeypatch.setenv(model_client.KEY_ENV, "sk-example-not-real")
    seen = _fake(monkeypatch)
    assert _cli("dream", "day", DAY)[0] == 0
    assert seen["headers"]["Authorization"] == "Bearer sk-example-not-real"
    assert "sk-example" not in json.dumps(_draft_lines(lb)[-1])
