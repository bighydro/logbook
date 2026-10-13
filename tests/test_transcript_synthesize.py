"""`logbook transcript synthesize ID|--day DAY` (RFC 0036, `draft/v1`, unit `event`): a model reads one
transcript under the `dream` entry of `policy/crossing.json` and writes one draft line about it, actions on
top, then the topics consolidated across the call, the decisions, the open threads and a short personal
part, every item pointing at the utterances it rests on or marked unsupported. The model endpoint is an
in-process fake of an OpenAI-compatible chat completions server (`model_client.send` replaced); no test
opens a connection (`no_network`). The transcript is a synthetic Granola call between Ines and Ola
Nordmann of Oslo, who do not exist, built by the granola adapter's own mapping; addresses at example.org."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import model_client, synthesis
from logbook.contrib.adapters import granola
from logbook.core import drafts, policy
from logbook.core.store import Logbook

DAY = "2026-06-10"  # a Wednesday; the call runs 10:00 to 10:48 in Oslo
MODEL = "qwen2.5-7b-instruct"
ENV = {
    model_client.ENDPOINT_ENV: "http://127.0.0.1:8080/v1",
    model_client.MODEL_ENV: MODEL,
}
PERSONAL = "My daughter starts school on Monday, so I leave early that day."


def _segment(name: str, text: str, minute: int, second: int = 0) -> dict[str, Any]:
    start = f"{DAY}T08:{minute:02d}:{second:02d}Z"
    end = f"{DAY}T08:{minute:02d}:{min(second + 20, 59):02d}Z"
    return {
        "speaker": {"source": "microphone", "name": name},
        "text": text,
        "start_time": start,
        "end_time": end,
    }


INES, OLA = "Ines Nordmann", "Ola Nordmann"
SEGMENTS = [
    _segment(INES, "Good morning Ola, shall we go through the yard plans?", 0),  # U1
    _segment(OLA, "Yes. First the hull survey: the yard in Vollen can do it in week 26.", 2),  # U2
    _segment(INES, PERSONAL, 3, 10),  # U3
    _segment(OLA, "The new mooring lines arrived at the marina.", 8, 30),  # U4
    _segment(INES, "Then we go with the yard in Vollen for the survey. Agreed?", 12),  # U5
    _segment(OLA, "Agreed.", 12, 20),  # U6
    _segment(OLA, "Back to the hull survey: they want the keel checked as well.", 20),  # U7
    _segment(INES, "Who pays for the haul-out? We have not settled that.", 31),  # U8
    _segment(OLA, "On the survey again: the report comes to me first.", 45),  # U9
    _segment(INES, "Then please send me the survey report by Friday.", 46, 30),  # U10
    _segment(OLA, "I will send it by Friday.", 47, 0),  # U11
]


def _note(note_id: str, title: str) -> dict[str, Any]:
    return {
        "id": note_id,
        "title": title,
        "created_at": f"{DAY}T07:58:00Z",
        "calendar_event": None,
        "attendees": [{"name": INES, "email": "ines@example.org"}, {"name": OLA, "email": "ola@example.org"}],
        "web_url": f"https://granola.example/notes/{note_id}",
    }


def _transcript(
    lb: Logbook,
    segments: list[dict[str, Any]] = SEGMENTS,
    note_id: str = "not_0synthetic0001",
    title: str = "Yard plans",
    tier: int | None = None,
    store: bool = True,
) -> dict[str, Any]:
    """One synthetic Granola call as `sync granola` writes it: the line through the adapter's mapping,
    the segments in the attachment store under their digest. Tier 3, as the adapter writes it, unless
    `tier` says otherwise."""
    line = granola.transcript_of(_note(note_id, title), segments)
    if tier is not None:
        line["tier"] = tier
    if store:
        lb.attach(granola._content(segments), line["tier"])
    return lb.append(
        at=line["at"],
        source=line["source"],
        kind=line["kind"],
        tier=line["tier"],
        payload=line["payload"],
        end=line["end"],
    )


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    _policy(lb, {"max_tier": 3, "until": "2026-12-31"})
    return lb


def _policy(lb: Logbook, entry: dict[str, Any] | None) -> None:
    data: dict[str, Any] = {"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}}
    if entry is not None:
        data[policy.DREAM_DESTINATION] = entry
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")


def _answer(_material: dict[str, Any], **parts: Any) -> dict[str, Any]:
    """A plausible answer for SEGMENTS, its keys in another order than the schema's: topics first,
    actions in the middle. `parts` override."""
    found: dict[str, Any] = {
        "topics": [
            {
                "topic": "Hull survey",
                "text": "The yard in Vollen surveys in week 26; the keel is to be checked too.",
                "evidence": ["U2", "U7", "U9"],
            },
            {"topic": "Mooring lines", "text": "The new mooring lines arrived.", "evidence": ["U4"]},
        ],
        "decisions": [{"text": "The survey goes to the yard in Vollen.", "evidence": ["U5", "U6"]}],
        "actions": [
            {
                "text": "Send the survey report to Ines.",
                "assignee": OLA,
                "due": "by Friday",
                "evidence": ["U10", "U11"],
            }
        ],
        "open_threads": [{"text": "Who pays for the haul-out is still open.", "evidence": ["U8"]}],
        "personal": [{"text": "A family matter of Ines's came up.", "evidence": ["U3"]}],
    }
    found.update(parts)
    return found


def _fake(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[dict[str, Any]], Any] | None = None
) -> dict[str, Any]:
    """`model_client.send` replaced by an in-process fake: what it was sent is in the returned dict
    (`calls`, each the request body; `prompt`, the last system text; `material`, the last material as
    the model got it). `answer` makes the completion from the material; a string is sent as is."""
    seen: dict[str, Any] = {"calls": []}

    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
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


def _drafts(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == drafts.KIND]


# -- the policy ----------------------------------------------------------------------------------------------


def test_no_dream_entry_refuses_and_sends_nothing(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    call = _transcript(lb)
    _policy(lb, None)
    seen = _fake(monkeypatch)
    seq = lb.meta["seq"]
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 2 and "'dream'" in err and "no day crosses" in err
    assert seen["calls"] == [] and lb.meta["seq"] == seq and no_network == []


def test_a_transcript_above_the_ceiling_stays_home(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    """The granola adapter writes tier 3; a dream entry of max_tier 2 lets no word of it cross."""
    call = _transcript(lb)
    _policy(lb, {"max_tier": 2, "until": "2026-12-31"})
    seen = _fake(monkeypatch)
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 2 and "tier 3" in err and "max_tier is 2" in err and "nothing was sent" in err
    assert seen["calls"] == [] and _drafts(lb) == [] and no_network == []
    _policy(lb, {"max_tier": 3})
    code, out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 0, err
    assert _drafts(lb)[-1]["tier"] == 3 and "tier 3" in out


# -- the draft -----------------------------------------------------------------------------------------------


def test_one_draft_per_transcript_its_evidence_the_transcript_line_and_the_utterances_kept(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    head, seq = lb.meta["head"], lb.meta["seq"]
    code, out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 0, err
    assert lb.meta["seq"] == seq + 1 and len(seen["calls"]) == 1 and no_network == []
    (line,) = _drafts(lb)
    p = line["payload"]
    assert line["kind"] == "draft" and line["source"] == f"model:{MODEL}" and line["tier"] == 3
    assert p["unit"] == "event" and p["subject"] == [call["id"]]
    assert p["read_head"] == head and p["read_count"] == 1 and p["language"] == "en"
    assert drafts.validate(p) == [] and "supersedes" not in p
    # utterances are not lines of their own: every segment's evidence is the transcript line ...
    assert all(s["evidence"] == [call["id"]] for s in p["segments"])
    # ... and which utterances it rests on, with where they are in the call, is kept beside it
    extra = p["extra"]
    assert extra["prompt"] == synthesis.PROMPT_NAME and extra["utterances"] == len(SEGMENTS)
    action, survey = extra["segments"][0], extra["segments"][1]
    assert action == {
        "part": "actions",
        "utterances": [{"n": 10, "offset": "46:30"}, {"n": 11, "offset": "47:00"}],
        "assignee": OLA,
        "due": {"phrase": "by Friday", "date": "2026-06-12"},
    }
    assert survey == {
        "part": "topics",
        "utterances": [{"n": 2, "offset": "02:00"}, {"n": 7, "offset": "20:00"}, {"n": 9, "offset": "45:00"}],
    }
    assert p["segments"][1]["text"].startswith("Hull survey: The yard in Vollen")
    assert f"synthesized as #{line['seq']} draft/v1" in out
    assert f"  action    Send the survey report to Ines.  → {OLA} · due by Friday (2026-06-12?)" in out
    assert "[46:30, 47:00]" in out and "[02:00, 20:00, 45:00]" in out


def test_actions_are_on_top_whatever_order_the_model_answers_in(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    _fake(monkeypatch)  # the fake answers topics first, actions third
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    parts = [d["part"] for d in _drafts(lb)[-1]["payload"]["extra"]["segments"]]
    assert parts == ["actions", "topics", "topics", "decisions", "open_threads", "personal"]


def test_a_theme_the_model_names_twice_is_one_topic(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    call = _transcript(lb)
    topics = [
        {"topic": "Hull survey", "text": "The yard surveys in week 26.", "evidence": ["U2"]},
        {"topic": "Mooring lines", "text": "The new lines arrived.", "evidence": ["U4"]},
        {"topic": "hull  survey", "text": "The keel is to be checked too.", "evidence": ["U7", "U9"]},
    ]
    _fake(monkeypatch, lambda m: _answer(m, topics=topics))
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    p = _drafts(lb)[-1]["payload"]
    texts = [
        s["text"] for s, d in zip(p["segments"], p["extra"]["segments"], strict=True) if d["part"] == "topics"
    ]
    assert texts == [
        "Hull survey: The yard surveys in week 26. The keel is to be checked too.",
        "Mooring lines: The new lines arrived.",
    ]
    merged = p["extra"]["segments"][1]["utterances"]
    assert [u["n"] for u in merged] == [2, 7, 9]


def test_every_reference_is_checked_against_the_transcript(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A reference the material did not give makes the item unsupported, whatever else it cites: an
    utterance past the end, another line's id, a day's `L1`. `T` is the transcript itself."""
    other = _transcript(lb, note_id="not_0synthetic0002", title="Another call")
    call = _transcript(lb)
    actions = [
        {"text": "Send the report.", "assignee": OLA, "due": None, "evidence": ["U10", "U99"]},
        {"text": "Book the haul-out.", "assignee": None, "due": None, "evidence": [other["id"]]},
    ]
    decisions = [
        {"text": "The yard in Vollen.", "evidence": ["U5"]},
        {"text": "A call about the yard.", "evidence": ["T"]},
        {"text": "Nothing.", "evidence": ["L1", "U0"]},
    ]
    open_threads = [
        {"text": "Who pays for the haul-out is still open.", "evidence": ["U8"]},
        {"text": "The keel check is not priced yet.", "evidence": ["U7"]},
    ]  # ten segments, three unsupported: 30 %, not more, so the answer stands
    _fake(monkeypatch, lambda m: _answer(m, actions=actions, decisions=decisions, open_threads=open_threads))
    code, out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 0, err
    p = _drafts(lb)[-1]["payload"]
    by = {s["text"]: (s, d) for s, d in zip(p["segments"], p["extra"]["segments"], strict=True)}
    for text in ("Send the report.", "Book the haul-out.", "Nothing."):
        assert by[text][0] == {"text": text, "unsupported": True} and by[text][1]["utterances"] == []
    assert by["The yard in Vollen."][0]["evidence"] == [call["id"]]
    assert by["A call about the yard."][0]["evidence"] == [call["id"]]
    assert by["A call about the yard."][1]["utterances"] == []
    assert "~ action    Send the report.  → Ola Nordmann  unsupported" in out
    assert "  decision  A call about the yard.  [the transcript]" in out


def test_too_many_unsupported_items_refuse_and_write_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    shaky = {
        "actions": [{"text": "Do it.", "unsupported": True}],
        "topics": [{"topic": "Yard", "text": "The yard.", "evidence": ["U2"]}],
        "decisions": [{"text": "Settled.", "evidence": ["U404"]}],
    }
    _fake(monkeypatch, lambda _m: shaky)
    seq = lb.meta["seq"]
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 1 and "2 of 3 segments rest on no line" in err and "nothing was written" in err
    assert lb.meta["seq"] == seq and _drafts(lb) == []


def test_the_prompt_fixes_the_schema_and_the_work_only_rule(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The schema and the work-only filter are the prompt's rules, not a filter in the code: the whole
    call reaches the model, the personal sentence too, and its answer decides what goes where."""
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    prompt = seen["prompt"]
    for rule in (
        "Work only.",
        "Actions on top.",
        "consolidated across the whole call",
        "settled, not discussed",
    ):
        assert rule in prompt
    for key in ("`actions`", "`topics`", "`decisions`", "`open_threads`", "`personal`"):
        assert key in prompt
    assert '"Yard plans", Wednesday 2026-06-10, in the zone Europe/Oslo: 11 utterances' in prompt
    m = seen["material"]
    assert m["transcript"]["ref"] == "T" and m["transcript"]["participants"] == [INES, OLA]
    assert m["transcript"]["start"] == "10:00" and m["transcript"]["minutes"] == 47
    assert m["utterances"][2] == {"ref": "U3", "at": "03:10", "speaker": INES, "text": PERSONAL}
    assert len(m["utterances"]) == len(SEGMENTS)
    assert "example.org" not in json.dumps(seen["calls"][-1])  # names cross, addresses never


def test_the_log_never_holds_the_call(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    call = _transcript(lb)
    _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    text = json.dumps(_drafts(lb)[-1])
    assert PERSONAL not in text and "U3" not in text and "example.org" not in text


def test_dry_run_asks_the_model_and_writes_nothing(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    seq = lb.meta["seq"]
    code, out, _err = _cli("transcript", "synthesize", call["id"], "--dry-run", "--show-prompt")
    assert code == 0 and "dry run, nothing written" in out and "Work only." in out
    assert len(seen["calls"]) == 1 and lb.meta["seq"] == seq


# -- again ---------------------------------------------------------------------------------------------------


def test_a_rerun_on_an_unchanged_transcript_sends_nothing_and_shows_the_standing_draft(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    (first,) = _drafts(lb)
    seq = lb.meta["seq"]
    code, out, _err = _cli("transcript", "synthesize", call["id"])
    assert code == 0 and len(seen["calls"]) == 1 and lb.meta["seq"] == seq
    assert f"unchanged: synthesized by model:{MODEL} as #{first['seq']}; nothing sent" in out
    assert "  action    Send the survey report to Ines." in out
    # --again asks once more, and the new draft supersedes the standing one
    code, out, _err = _cli("transcript", "synthesize", call["id"], "--again")
    assert code == 0 and len(seen["calls"]) == 2 and f"supersedes {first['id']}" in out
    assert _drafts(lb)[-1]["payload"]["supersedes"] == first["id"]
    # another model is another reading: it synthesizes without --again and supersedes too
    monkeypatch.setenv(model_client.MODEL_ENV, "local-3b")
    second = _drafts(lb)[-1]
    assert _cli("transcript", "synthesize", call["id"])[0] == 0 and len(seen["calls"]) == 3
    assert _drafts(lb)[-1]["source"] == "model:local-3b"
    assert _drafts(lb)[-1]["payload"]["supersedes"] == second["id"]


# -- naming the transcript -----------------------------------------------------------------------------------


def test_a_transcript_is_named_by_its_id_its_seq_or_the_end_of_its_id(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    note = lb.append(f"{DAY}T06:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Early."})
    call = _transcript(lb)
    _fake(monkeypatch, lambda _m: "not json")
    for name in (f"#{call['seq']}", call["id"][-8:], f"…{call['id'][-8:]}"):
        code, _out, err = _cli("transcript", "synthesize", name, "--dry-run")
        assert code == 1 and "not one JSON object" in err, name  # found, sent, refused
    code, _out, err = _cli("transcript", "synthesize", f"#{note['seq']}")
    assert code == 2 and "not a transcript" in err
    code, _out, err = _cli("transcript", "synthesize", "0000000000000000")
    assert code == 2 and "no line 0000000000000000" in err
    code, _out, err = _cli("transcript", "synthesize")
    assert code == 2 and "--day" in err


def test_a_transcript_whose_text_is_not_in_the_store_is_said(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb, store=False)
    seen = _fake(monkeypatch)
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 2 and "not in the attachment store" in err and seen["calls"] == []


# -- a day ---------------------------------------------------------------------------------------------------


def test_day_synthesizes_each_transcript_and_holds_back_one_above_the_ceiling(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    kept = _transcript(lb, note_id="not_0synthetic0003", title="Yard plans, tier 2", tier=2)
    held = _transcript(lb, title="Yard plans, tier 3")
    _policy(lb, {"max_tier": 2})
    seen = _fake(monkeypatch)
    code, out, err = _cli("transcript", "synthesize", "--day", DAY)
    assert code == 0, err
    assert len(seen["calls"]) == 1 and [d["payload"]["subject"] for d in _drafts(lb)] == [[kept["id"]]]
    assert "“Yard plans, tier 2”" in out and "held back" in out and "tier 3" in out
    assert out.rstrip().splitlines()[-1] == "1 synthesized · 1 held back"
    assert held["id"] not in json.dumps(seen["calls"])
    code, out, _err = _cli("transcript", "synthesize", "--day", DAY)
    assert code == 0 and len(seen["calls"]) == 1
    assert out.rstrip().splitlines()[-1] == "1 unchanged · 1 held back"
    code, out, _err = _cli("transcript", "synthesize", "--day", "2026-06-11")
    assert code == 0 and "no transcript on 2026-06-11" in out


def test_a_refused_answer_on_a_day_is_one_row_and_exit_1(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _transcript(lb)
    _fake(monkeypatch, lambda _m: "I cannot.")
    code, out, _err = _cli("transcript", "synthesize", "--day", DAY)
    assert code == 1 and "refused" in out and "not one JSON object" in out
    assert out.rstrip().splitlines()[-1] == "1 refused"


def test_a_head_that_moved_under_the_reading_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)

    def answer(material: dict[str, Any]) -> dict[str, Any]:
        other = Logbook(lb.root)  # a writer that ignored the lock, in this process: the lock re-enters
        other.append(f"{DAY}T15:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Late note."})
        return _answer(material)

    _fake(monkeypatch, answer)
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 2 and "head moved" in err and "nothing was written" in err and _drafts(lb) == []


# -- catch-up ------------------------------------------------------------------------------------------------


def _either(material: dict[str, Any]) -> dict[str, Any]:
    """The answer to whichever the model is asked: a call (it has utterances) or a day."""
    if "utterances" in material:
        return _answer(material)
    return {"day": [{"text": "A call about the yard.", "evidence": material["unplaced"][0]["ref"]}]}


def test_dream_catch_up_synthesizes_the_transcripts_that_have_no_draft(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """`dream --catch-up` is what the 06:00 close runs: after the days, each transcript of those days
    that no model has synthesized yet; one already synthesized is left alone, by any model."""
    from logbook.contrib import dream

    _transcript(lb)
    seen = _fake(monkeypatch, _either)
    monkeypatch.setattr(dream, "date", type("D", (), {"today": staticmethod(lambda: date(2026, 6, 12))}))
    code, out, err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0, out + err
    rows = out.splitlines()
    assert rows[1].startswith(f"{DAY}  dreamed   #")
    assert rows[3].startswith(f"{DAY}  synthesized #") and "“Yard plans” · 6 segments" in rows[3]
    assert rows[4] == "1 dreamed · 2 empty · 1 synthesized" and len(seen["calls"]) == 2
    code, out, _err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0 and len(seen["calls"]) == 2  # the day unchanged, the call synthesized already
    assert out.splitlines()[-1] == "1 unchanged · 2 empty"


def test_dream_catch_up_counts_a_transcript_above_the_ceiling_and_sends_nothing_of_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    from logbook.contrib import dream

    _transcript(lb)  # tier 3
    _policy(lb, {"max_tier": 2})
    seen = _fake(monkeypatch, _either)
    monkeypatch.setattr(dream, "date", type("D", (), {"today": staticmethod(lambda: date(2026, 6, 12))}))
    code, out, _err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0 and seen["calls"] == [] and _drafts(lb) == []
    assert out.splitlines()[-1] == "3 empty · 1 transcript held back above max_tier 2"
