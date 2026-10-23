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
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, dwell, utc

from logbook import cli
from logbook.contrib import doctor, dream, mcp_server, model_client, serve, synthesis
from logbook.contrib.adapters import granola
from logbook.contrib.adapters import transcript as transcript_adapter
from logbook.core import attachments, drafts, policy
from logbook.core import day as day_reader
from logbook.core.store import Logbook
from logbook.labs import scenes

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


def _policy(lb: Logbook, entry: dict[str, Any] | None, mcp: int = 1) -> None:
    data: dict[str, Any] = {"hermes": {"max_tier": 2}, "mcp": {"max_tier": mcp}}
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


# -- a home video's soundtrack is no call -----------------------------------------------------------------

SOUNDTRACK = (
    "WEBVTT\n\n00:00:05.000 --> 00:00:09.000\nCan you send me the photos by Friday? I'll call you tomorrow.\n"
)


def _soundtrack(lb: Logbook) -> dict[str, Any]:
    """A home video's transcript as `videos infer` writes it (RFC 0040): source `video-transcription`,
    `at` the video line's, `end` null, the WebVTT in the attachment store, tier 2."""
    data = SOUNDTRACK.encode("utf-8")
    lb.attach(data)
    line = transcript_adapter.draft(
        source=scenes.TRANSCRIPT_SOURCE,
        at=f"{DAY}T16:00:00Z",
        end=None,
        raw_id="video:1HomeTape01SyntheticVideoId01@000000000000",
        content=attachments.reference(data, scenes.TRANSCRIPT_MEDIA),
        turns=[],
        tier=2,
        title="Home 01",
        participants=[],
        extra={"format": "vtt", "time_unknown": True},
    )
    return lb.append(line["at"], line["source"], line["kind"], line["tier"], line["payload"], end=None)


def _never(monkeypatch: pytest.MonkeyPatch) -> None:
    """`model_client.send` replaced by one that fails the test: nothing of a soundtrack is ever sent."""

    def send(*_a: Any, **_k: Any) -> dict[str, Any]:
        pytest.fail("a home video's soundtrack reached the model endpoint")

    monkeypatch.setattr(model_client, "send", send)


def test_a_home_videos_soundtrack_named_by_id_is_refused_before_any_request(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The catch-up and `--day` leave a soundtrack out (`NOT_CALLS`); naming it by its id, its #seq or
    the end of its id refuses it the same way, in one sentence, exit 2, nothing sent, nothing written,
    with `--dry-run` and `--again` as without, and with no `dream` entry at all."""
    video = _soundtrack(lb)
    _never(monkeypatch)
    seq = lb.meta["seq"]
    for name in (video["id"], f"#{video['seq']}", video["id"][-8:], f"…{video['id'][-8:]}"):
        for extra in ((), ("--dry-run",), ("--again",)):
            code, out, err = _cli("transcript", "synthesize", name, *extra)
            assert code == 2, (name, extra, err)
            assert out == "" and len(err.strip().splitlines()) == 1, err
            assert "home video's soundtrack, not a call" in err and "nothing was sent" in err
    _policy(lb, None)
    code, _out, err = _cli("transcript", "synthesize", video["id"])
    assert code == 2 and "home video's soundtrack, not a call" in err
    assert lb.meta["seq"] == seq and _drafts(lb) == [] and no_network == []


def test_synthesize_itself_refuses_a_soundtrack_whatever_line_it_is_handed(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The guard is in `synthesize`, the one path to the model every caller passes, not only in `find`:
    the line as the record holds it, or the bare id of one, is refused before the policy is read."""
    video = _soundtrack(lb)
    _never(monkeypatch)
    seq = lb.meta["seq"]
    for line in (video, {"id": video["id"]}):
        with pytest.raises(synthesis.NotACall, match="home video's soundtrack, not a call"):
            synthesis.synthesize(lb, line, env=ENV)
        with pytest.raises(synthesis.NotACall):
            synthesis.synthesize(lb, line, env=ENV, dry_run=True, again=True)
    assert issubclass(synthesis.NotACall, dream.DreamError)
    assert lb.meta["seq"] == seq and _drafts(lb) == [] and no_network == []


def test_a_call_beside_a_soundtrack_is_still_synthesized_by_id(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    video = _soundtrack(lb)
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 0, err
    assert len(seen["calls"]) == 1 and _drafts(lb)[-1]["payload"]["subject"] == [call["id"]]
    assert "Can you send me the photos" not in json.dumps(seen["calls"])
    tried = synthesis.synthesize_day(lb, DAY, env=ENV, again=True)
    assert [row.transcript["id"] for row in tried] == [call["id"]]
    assert video["id"] not in json.dumps(seen["calls"]) and no_network == []


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
    """The answer to whichever the model is asked: a call (it has utterances), a week (the close dreams
    the week whose seven days it looks at, `dream_week`) or a day."""
    if "utterances" in material:
        return _answer(material)
    if "week" in material:
        return {
            "time": [
                {"text": "A week with a call.", "evidence": re.findall(r'"(L\d+)"', json.dumps(material))[:1]}
            ]
        }
    return {"story": [{"text": "A call about the yard.", "evidence": material["unplaced"][0]["ref"]}]}


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


# -- the Day -------------------------------------------------------------------------------------------------

SUMMARY = f"synthesis · 1 action, 2 topics, 1 decision, 1 open thread, 1 personal · model:{MODEL}"


def test_the_day_shows_the_synthesis_collapsed_under_the_transcripts_row(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A call the track does not place is unplaced; its synthesis is one row under it, collapsed: the
    counts and the model, never the items, which `--json`, `serve` and `transcript synthesize` give."""
    call = _transcript(lb)
    _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    (line,) = _drafts(lb)
    code, out, _err = _cli("day", DAY, "--no-anniversaries")
    assert code == 0
    rows = out.splitlines()
    at = next(i for i, row in enumerate(rows) if row.startswith("  unplaced") and "Yard plans" in row)
    assert rows[at + 1].strip() == SUMMARY
    assert rows[at + 1].index("synthesis") == rows[at].index("Yard plans")  # under the title
    assert "Send the survey report" not in out
    data = json.loads(_cli("day", DAY, "--json", "--no-anniversaries")[1])
    (block,) = data["syntheses"]
    assert block["transcript"] == call["id"] and block["line"] == line["id"] and block["unsupported"] == 0
    assert block["counts"] == {"actions": 1, "topics": 2, "decisions": 1, "open_threads": 1, "personal": 1}
    first = block["segments"][0]
    assert first["part"] == "actions" and first["assignee"] == OLA and first["supported"] is True
    assert first["due"] == {"phrase": "by Friday", "date": "2026-06-12"}
    assert [u["offset"] for u in first["utterances"]] == ["46:30", "47:00"]
    assert "syntheses" not in json.loads(_cli("day", DAY, "--json", "--no-dream")[1])
    assert "synthesis" not in _cli("day", DAY, "--no-anniversaries", "--no-dream")[1]
    assert "syntheses" not in json.loads(_cli("day", "2026-06-11", "--json", "--no-anniversaries")[1])


def test_a_placed_call_carries_its_synthesis_under_its_row_in_the_stay(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    lb.append_many(dwell(DAY, "09:00", "12:00", HOME, every_min=20))
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    call = _transcript(lb)
    _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    rows = _cli("day", DAY, "--no-anniversaries")[1].splitlines()
    at = next(i for i, row in enumerate(rows) if row.strip().startswith("transcript") and "Yard plans" in row)
    assert rows[at + 1].strip() == SUMMARY
    assert rows[at + 1].index("synthesis") == rows[at].index("Yard plans")


def test_serve_shows_the_synthesis_behind_a_toggle_under_the_call(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    _fake(monkeypatch, lambda m: _answer(m, personal=[{"text": "Something personal.", "unsupported": True}]))
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    site = serve.Site(lb)
    html = site.page_day(DAY)
    toggle = html.index('<details class="synthesis">')
    assert html.index("Yard plans") < toggle and "<summary>synthesis · 1 action" in html
    body = html[toggle : html.index("</details>", toggle)]
    assert body.index("Send the survey report to Ines.") < body.index("Hull survey:")  # actions on top
    assert "→ Ola Nordmann · due by Friday (2026-06-12?)" in body and "02:00, 20:00, 45:00" in body
    assert 'class="segment unsupported mute"' in body and "~ Something personal." in body
    assert '<details class="synthesis" open>' in site.page_day(DAY, expanded=True)


def test_a_synthesis_above_the_gate_is_not_on_a_gated_day(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb, tier=2)
    _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0  # tier 2: what it read
    assert "syntheses" not in day_reader.read(lb, DAY, tiers=(1,))
    assert day_reader.read(lb, DAY, tiers=(1, 2))["syntheses"][0]["transcript"] == call["id"]


def test_evidence_that_is_not_the_transcript_is_shown_unsupported_and_said_why(lb: Logbook) -> None:
    """A synthesis some other writer made, citing a line that is not its call (rule 6): the reader marks
    the segment and says."""
    call = _transcript(lb)
    other = lb.append(utc(DAY, "09:00"), "manual", "note", 2, {"schema": "note/v1", "text": "A note."})
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "event",
        "subject": [call["id"]],
        "read_head": lb.meta["head"],
        "read_count": 1,
        "language": "en",
        "segments": [
            {"text": "Send the report.", "evidence": [call["id"]]},
            {"text": "Elsewhere.", "evidence": [other["id"]]},
        ],
        "extra": {"segments": [{"part": "actions", "utterances": [{"n": 10}]}, {"part": "topics"}]},
    }
    lb.append("2026-06-11T04:00:00Z", "model:x", "draft", 3, payload)
    (block,) = day_reader.read(lb, DAY)["syntheses"]
    assert block["segments"][0]["supported"] is True and block["segments"][0]["utterances"] == [
        {"n": 10, "offset": None}
    ]
    assert block["segments"][1] | {"utterances": []} == {
        "text": "Elsewhere.",
        "evidence": [other["id"]],
        "supported": False,
        "why": drafts.NOT_THE_TRANSCRIPT,
        "part": "topics",
        "utterances": [],
        "assignee": None,
        "due": None,
    }
    assert (
        "synthesis · 1 action, 1 topic · 1 unsupported · model:x" in _cli("day", DAY, "--no-anniversaries")[1]
    )


# -- the policy that authorised it: a synthesis is a draft, and follows the policy like any draft ----------


def _today(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    monkeypatch.setattr(dream, "date", type("D", (), {"today": staticmethod(lambda: day)}))


def _day_text(*args: str) -> str:
    code, out, err = _cli("day", DAY, *args, "--no-anniversaries")
    assert code == 0, err
    return out


def _under_the_call(out: str) -> str:
    """The row under the unplaced call's own row, checked to sit under its title."""
    rows = out.splitlines()
    at = next(i for i, row in enumerate(rows) if row.startswith("  unplaced") and "Yard plans" in row)
    below = rows[at + 1]
    assert len(below) - len(below.lstrip()) == rows[at].index("Yard plans"), (rows[at], below)
    return below.strip()


def test_a_synthesis_records_the_version_of_the_entry_it_was_made_under(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    _fake(monkeypatch)
    _policy(lb, {"max_tier": 3, "until": "2026-12-31", "model": MODEL})
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    (line,) = _drafts(lb)
    found = policy.version(policy.dream_entry(lb.root))
    assert line["payload"]["extra"]["policy_version"] == found and len(found) == 64
    assert drafts.validate(line["payload"]) == []


def test_the_same_model_under_another_entry_synthesizes_the_call_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """Rule 1 as the dream has it: a call is unchanged for the same model under the same prompt and the
    same entry; an entry lent for longer is another entry, and the new synthesis supersedes."""
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    (first,) = _drafts(lb)
    _policy(lb, {"max_tier": 3, "until": "2027-03-31"})  # the same ceiling, lent for longer
    code, out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 0, err
    assert len(seen["calls"]) == 2 and f"supersedes {first['id']}" in out
    second = _drafts(lb)[-1]
    assert second["payload"]["supersedes"] == first["id"]
    assert second["payload"]["extra"]["policy_version"] == policy.version(policy.dream_entry(lb.root))
    code, out, _err = _cli("transcript", "synthesize", call["id"])
    assert code == 0 and len(seen["calls"]) == 2
    assert f"unchanged: synthesized by model:{MODEL} as #{second['seq']}; nothing sent" in out


def test_a_synthesis_made_at_3_is_withheld_when_the_ceiling_drops_to_2(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The Day of a reader that holds the whole record says so under the call's row, and nothing of the
    synthesis; a gated reader hides it without a word; the call itself stays home from then on."""
    call = _transcript(lb)  # tier 3, as the granola adapter writes it
    seen = _fake(monkeypatch, _either)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    (line,) = _drafts(lb)
    assert _under_the_call(_day_text()) == SUMMARY

    _policy(lb, {"max_tier": 2, "until": "2026-12-31"})  # no line appended: the head did not move
    out = _day_text()
    below = _under_the_call(out)
    assert below.startswith(f"{drafts.SUPERSEDED_BY_POLICY}: tier 3, above max_tier 2")
    assert "synthesis ·" not in out and "Send the survey report" not in out and f"model:{MODEL}" not in out
    data = json.loads(_day_text("--json"))
    assert "syntheses" not in data and "draft_withheld" not in data
    (row,) = data["syntheses_withheld"]
    assert row["transcript"] == call["id"] and row["line"] == line["id"] and row["seq"] == line["seq"]
    assert row["tier"] == 3 and row["max_tier"] == 2 and set(row) == {
        "transcript", "line", "seq", "tier", "max_tier", "why",
    }  # fmt: skip
    assert "Send the survey report" not in json.dumps(data)
    gated = day_reader.read(lb, DAY, tiers=(1, 2, 3))
    assert "syntheses" not in gated and "syntheses_withheld" not in gated
    html = serve.Site(lb).page_day(DAY)
    assert '<details class="synthesis"' not in html and "Send the survey report" not in html
    assert html.index("Yard plans") < html.index(drafts.SUPERSEDED_BY_POLICY)
    assert "syntheses_withheld" not in json.loads(_day_text("--json", "--no-dream"))
    assert drafts.SUPERSEDED_BY_POLICY not in _day_text("--no-dream")

    _today(monkeypatch, date(2026, 6, 12))
    code, out, _err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0 and len(seen["calls"]) == 1 and _drafts(lb) == [line]
    assert out.splitlines()[-1] == "3 empty · 1 transcript held back above max_tier 2"

    _policy(lb, {"max_tier": 3, "until": "2026-12-31"})  # the entry it was made under, again
    assert _under_the_call(_day_text()) == SUMMARY
    assert "syntheses_withheld" not in json.loads(_day_text("--json"))


def test_an_expired_entry_shows_nothing_of_a_synthesis(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    _policy(lb, {"max_tier": 3, "until": "2026-06-15"})  # today is 2026-06-20 in the fixture
    below = _under_the_call(_day_text())
    assert below.startswith(drafts.SUPERSEDED_BY_POLICY) and "expired on 2026-06-15" in below
    (row,) = json.loads(_day_text("--json"))["syntheses_withheld"]
    assert row["max_tier"] == 0 and row["transcript"] == call["id"]
    assert "Send the survey report" not in serve.Site(lb).page_day(DAY)
    code, _out, err = _cli("transcript", "synthesize", call["id"])
    assert code == 2 and "expired on 2026-06-15" in err and len(seen["calls"]) == 1


def test_catch_up_synthesizes_again_a_call_made_under_another_entry(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _transcript(lb)
    seen = _fake(monkeypatch, _either)
    _today(monkeypatch, date(2026, 6, 12))
    assert _cli("dream", "--catch-up", "--days", "3")[0] == 0
    (first,) = [d for d in _drafts(lb) if d["payload"]["unit"] == drafts.UNIT_EVENT]
    assert len(seen["calls"]) == 2
    _policy(lb, {"max_tier": 3, "until": "2027-03-31"})  # the same ceiling, lent for longer
    assert _under_the_call(_day_text()) == SUMMARY  # its tier is allowed: shown until made again
    code, out, err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0, out + err
    rows = out.splitlines()
    assert rows[1].startswith(f"{DAY}  dreamed   #") and "dreamed under another dream entry" in rows[1]
    assert rows[3].startswith(f"{DAY}  synthesized #") and "“Yard plans” · 6 segments" in rows[3]
    assert rows[3].endswith("synthesized under another dream entry")
    assert rows[4] == "1 dreamed · 2 empty · 1 synthesized" and len(seen["calls"]) == 4
    second = _drafts(lb)[-1]
    assert second["payload"]["supersedes"] == first["id"]
    assert second["payload"]["extra"]["policy_version"] == policy.version(policy.dream_entry(lb.root))
    code, out, _err = _cli("dream", "--catch-up", "--days", "3")
    assert code == 0 and len(seen["calls"]) == 4 and out.splitlines()[-1] == "1 unchanged · 2 empty"


def test_a_synthesis_that_names_no_policy_version_is_held_to_its_model_and_its_tier(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A synthesis written before syntheses named their entry: no version to compare, so a new entry
    alone synthesizes nothing again, and its tier still decides what a reader shows."""
    call = _transcript(lb)
    seen = _fake(monkeypatch)
    made = synthesis.synthesize(lb, call, dry_run=True)
    payload = made.payload
    del payload["extra"]["policy_version"]
    lb.append("2026-06-20T04:00:00Z", f"model:{MODEL}", drafts.KIND, made.tier, payload)
    _policy(lb, {"max_tier": 3, "until": "2027-03-31"})
    code, out, _err = _cli("transcript", "synthesize", call["id"])
    assert code == 0 and "unchanged" in out and len(seen["calls"]) == 1
    _today(monkeypatch, date(2026, 6, 12))
    _fake(monkeypatch, _either)
    assert _cli("dream", "--catch-up", "--days", "3")[1].splitlines()[-1] == "1 dreamed · 2 empty"
    assert len([d for d in _drafts(lb) if d["payload"]["unit"] == drafts.UNIT_EVENT]) == 1
    assert _under_the_call(_day_text()) == SUMMARY
    _policy(lb, {"max_tier": 2, "until": "2027-03-31"})
    assert _under_the_call(_day_text()).startswith(drafts.SUPERSEDED_BY_POLICY)


def test_the_door_never_serves_a_synthesis_above_the_dream_ceiling(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    _fake(monkeypatch)
    _policy(lb, {"max_tier": 3, "until": "2026-12-31"}, mcp=3)
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    (line,) = _drafts(lb)

    def ask(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return mcp_server.call(lb.root, name, arguments, allow_tier_3=True)

    assert ask("day", {"date": DAY})["data"]["syntheses"][0]["line"] == line["id"]
    _policy(lb, {"max_tier": 2, "until": "2026-12-31"}, mcp=3)
    out = ask("day", {"date": DAY})
    assert "syntheses" not in out["data"] and "syntheses_withheld" not in out["data"]
    assert "Send the survey report" not in json.dumps(out)
    with pytest.raises(mcp_server.ToolError, match="dream"):
        ask("line", {"id": line["id"]})


# -- one draft per unit: the call's synthesis is the call's, never the day's (RFC 0036 amendment 1) ---------


def _day_draft(lb: Logbook) -> tuple[Any, ...]:
    """What `drafts.for_day` returns for DAY under the `dream` entry today: the Day's `draft` and
    `draft_withheld`, the day's alone."""
    with lb.index() as idx:
        return drafts.for_day(idx, DAY, None, drafts.allowed(lb.root))


def _on_the_note(material: dict[str, Any]) -> dict[str, Any]:
    """The answer to a call, or to a day whose one line under the ceiling is the owner's note."""
    if "utterances" in material:
        return _answer(material)
    return {"story": [{"text": "A note about the yard.", "evidence": [material["notes"][0]["ref"]]}]}


def test_a_calls_synthesis_leaves_the_days_draft_as_it_was(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The day and the call are two units with a standing draft each: a synthesis written after the
    day's draft is not the day's latest draft, does not count as a dream of the day, and `for_day`
    returns what it returned before; the synthesis is beside it, under the call."""
    call = _transcript(lb)
    _fake(monkeypatch, _either)
    assert _cli("dream", "day", DAY)[0] == 0
    before, data_before = _day_draft(lb), json.loads(_day_text("--json"))
    assert before[0] is not None and before[1] is None and before[0]["dreamed"] == 1
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    (synthesized,) = [d for d in _drafts(lb) if d["payload"]["unit"] == drafts.UNIT_EVENT]
    assert _day_draft(lb) == before
    data = json.loads(_day_text("--json"))
    assert data["draft"] == data_before["draft"] and "draft_withheld" not in data
    assert data["draft"]["line"] != synthesized["id"] and synthesized["id"] not in data["draft"]["earlier"]
    (block,) = data["syntheses"]
    assert block["transcript"] == call["id"] and block["line"] == synthesized["id"]
    out = _day_text()
    assert out.index("dreamed 1×") < out.index("Yard plans") and _under_the_call(out) == SUMMARY


def test_a_withheld_synthesis_leaves_the_days_draft_shown(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The day's draft read a tier-2 note under max_tier 2; the call (tier 3) was synthesized while the
    entry allowed 3. With the entry back at 2 the synthesis is withheld under the call, and the day's
    draft is shown as it was: no `draft_withheld`, nothing of the call's row in the day's."""
    call = _transcript(lb)  # tier 3: outside the day's reading at max_tier 2
    lb.append(utc(DAY, "09:00"), "manual", "note", 2, {"schema": "note/v1", "text": "The yard called."})
    _fake(monkeypatch, _on_the_note)
    _policy(lb, {"max_tier": 2, "until": "2026-12-31"})
    assert _cli("dream", "day", DAY)[0] == 0
    before = _day_draft(lb)
    assert before[0] is not None and before[0]["tier"] == 2 and before[1] is None
    _policy(lb, {"max_tier": 3, "until": "2026-12-31"})
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    _policy(lb, {"max_tier": 2, "until": "2026-12-31"})
    assert _day_draft(lb) == before
    data = json.loads(_day_text("--json"))
    assert data["draft"]["line"] == before[0]["line"] and "draft_withheld" not in data
    (row,) = data["syntheses_withheld"]
    assert row["transcript"] == call["id"] and row["tier"] == 3 and "syntheses" not in data
    out = _day_text()
    assert "A note about the yard." in out
    assert _under_the_call(out).startswith(f"{drafts.SUPERSEDED_BY_POLICY}: tier 3, above max_tier 2")
    assert out.count(drafts.SUPERSEDED_BY_POLICY) == 1  # under the call; the day's draft is shown


# -- the catch-up's window: a week of calls, never the whole backlog ---------------------------------------

TODAY = date(2026, 6, 20)  # the fixture's policy day too
WEEK_AGO = "2026-06-13"  # the first day of the catch-up's window: 7 days before TODAY
OLD_DAY = "2026-05-11"  # 40 days before TODAY
BEFORE_THE_WEEK = (
    f"1 call before {WEEK_AGO} not synthesized; run `logbook transcript synthesize --day {OLD_DAY}`"
    f" or `dream --catch-up --since {OLD_DAY}`"
)


def _call_days_ago(lb: Logbook, days: int, title: str, tier: int | None = None) -> dict[str, Any]:
    """The call of SEGMENTS held `days` days before TODAY, under its own note id and title."""
    day = (TODAY - timedelta(days=days)).isoformat()
    segments = json.loads(json.dumps(SEGMENTS).replace(DAY, day))
    return _transcript(lb, segments, note_id=f"not_0synthetic{days:04d}", title=title, tier=tier)


def _three_calls(lb: Logbook) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Calls 40, 6 and 2 days old, none synthesized."""
    return (
        _call_days_ago(lb, 40, "Spring fitting-out"),
        _call_days_ago(lb, 6, "Hull survey"),
        _call_days_ago(lb, 2, "Mooring lines"),
    )


def _calls_sent(seen: dict[str, Any]) -> list[str]:
    """The day of each call the model was sent, in order; the days' own requests left out."""
    found = [json.loads(body["messages"][1]["content"]) for body in seen["calls"]]
    return [material["transcript"]["day"] for material in found if "utterances" in material]


def _synthesized(lb: Logbook) -> list[str]:
    return [d["payload"]["subject"][0] for d in _drafts(lb) if d["payload"]["unit"] == drafts.UNIT_EVENT]


def test_the_catch_up_synthesizes_the_last_week_of_calls_and_names_the_older_ones(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The close runs `dream --catch-up` with nothing else: a call is sent only when its day is one of
    the last 7; an older one without a synthesis is counted and named in one line, never sent, so the
    first close after an upgrade does not send a record's whole backlog of calls."""
    old, six, two = _three_calls(lb)
    seen = _fake(monkeypatch, _either)
    _today(monkeypatch, TODAY)
    code, out, err = _cli("dream", "--catch-up")
    assert code == 0, out + err
    assert _calls_sent(seen) == ["2026-06-14", "2026-06-18"] and _synthesized(lb) == [six["id"], two["id"]]
    assert old["id"] not in _synthesized(lb) and no_network == []
    rows = out.splitlines()
    assert rows[-2] == "3 dreamed · 12 empty · 2 synthesized", "the days, then the week of 8 June"
    assert rows[-1] == BEFORE_THE_WEEK


def test_a_call_the_catch_up_synthesized_is_never_sent_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _three_calls(lb)
    seen = _fake(monkeypatch, _either)
    _today(monkeypatch, TODAY)
    assert _cli("dream", "--catch-up")[0] == 0
    sent = len(seen["calls"])
    code, out, _err = _cli("dream", "--catch-up")
    assert code == 0 and len(seen["calls"]) == sent
    assert out.splitlines()[-2:] == ["3 unchanged · 12 empty", BEFORE_THE_WEEK]


def test_since_reaches_back_to_an_older_call_and_resends_none(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """`dream --catch-up --since DAY` is the explicit ask that reaches past the week: the old call is
    sent, the two synthesized already are not, and the days dreamed are still the last `--days`."""
    old, six, two = _three_calls(lb)
    seen = _fake(monkeypatch, _either)
    _today(monkeypatch, TODAY)
    assert _cli("dream", "--catch-up")[0] == 0
    code, out, err = _cli("dream", "--catch-up", "--since", "2026-05-12")  # a day after the old call
    assert code == 0, out + err
    assert _calls_sent(seen) == ["2026-06-14", "2026-06-18"]
    assert out.splitlines()[-1] == (
        "1 call before 2026-05-12 not synthesized; run `logbook transcript synthesize --day 2026-05-11`"
        " or `dream --catch-up --since 2026-05-11`"
    )
    code, out, err = _cli("dream", "--catch-up", "--since", OLD_DAY)
    assert code == 0, out + err
    assert _calls_sent(seen) == ["2026-06-14", "2026-06-18", OLD_DAY]
    assert _synthesized(lb) == [six["id"], two["id"], old["id"]]
    rows = out.splitlines()
    assert rows[-1] == "3 unchanged · 12 empty · 1 synthesized"
    assert rows[-2].startswith(f"{OLD_DAY}  synthesized #") and "“Spring fitting-out”" in rows[-2]
    code, out, _err = _cli("dream", "--catch-up", "--since", OLD_DAY)
    assert code == 0 and len(_calls_sent(seen)) == 3 and out.splitlines()[-1] == "3 unchanged · 12 empty"


def test_a_call_synthesized_by_hand_is_not_sent_by_the_catch_up_nor_named(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """`transcript synthesize --day DAY` is unchanged and is the other way to an old call; once it
    has a synthesis under this model, prompt and entry, no catch-up sends it, however far it reaches."""
    old, _six, _two = _three_calls(lb)
    seen = _fake(monkeypatch, _either)
    _today(monkeypatch, TODAY)
    code, out, err = _cli("transcript", "synthesize", "--day", OLD_DAY)
    assert code == 0, out + err
    assert _calls_sent(seen) == [OLD_DAY] and _synthesized(lb) == [old["id"]]
    code, out, _err = _cli("dream", "--catch-up", "--since", "2026-05-01")
    assert code == 0 and _calls_sent(seen) == [OLD_DAY, "2026-06-14", "2026-06-18"]
    assert "not synthesized" not in out
    code, out, _err = _cli("dream", "--catch-up")
    assert code == 0 and len(_calls_sent(seen)) == 3 and "not synthesized" not in out


def test_the_window_is_the_calls_own_day_under_the_records_day_start(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A call at 05:30 on the first day of the window belongs, under a day that begins at 06:00, to
    the day before: outside the week, so it is named and not sent."""
    meta = json.loads(lb.meta_path.read_text(encoding="utf-8"))
    meta["day_start"] = "06:00"
    lb.meta_path.write_text(json.dumps(meta), encoding="utf-8")
    early = [
        {**s, "start_time": f"{WEEK_AGO}T03:30:00Z", "end_time": f"{WEEK_AGO}T03:40:00Z"}
        for s in SEGMENTS[:2]
    ]  # 05:30 to 05:40 in Oslo
    _transcript(lb, early, note_id="not_0synthetic0007", title="Early call")
    seen = _fake(monkeypatch, _either)
    _today(monkeypatch, TODAY)
    code, out, err = _cli("dream", "--catch-up")
    assert code == 0, out + err
    assert _calls_sent(seen) == [] and out.splitlines()[-1] == (
        "1 call before 2026-06-13 not synthesized; run `logbook transcript synthesize --day 2026-06-12`"
        " or `dream --catch-up --since 2026-06-12`"
    )


def test_since_goes_with_catch_up_and_is_a_day(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    seen = _fake(monkeypatch, _either)
    code, _out, err = _cli("dream", "day", DAY, "--since", "2026-05-01")
    assert code == 2 and "--since goes with --catch-up" in err
    code, _out, err = _cli("dream", "--catch-up", "--since", "2026-5-1")
    assert code == 2 and "--since" in err and "2026-5-1" in err
    assert seen["calls"] == [] and _drafts(lb) == []


def _synthesis_check(lb: Logbook) -> doctor.Check | None:
    now = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)  # TODAY, noon in Oslo
    return {c.name: c for c in doctor.run(lb, {}, now=now)}.get("synthesis")


def test_doctor_counts_the_calls_without_a_synthesis_inside_and_outside_the_window(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """One `synthesis` line: the calls with no synthesis in the close's window (today's among them,
    for the next close), those before it, which the close leaves, and those above the ceiling."""
    _old, six, _two = _three_calls(lb)
    _call_days_ago(lb, 0, "Today's call")
    _call_days_ago(lb, 50, "Keel bolts", tier=2)
    _fake(monkeypatch)
    assert _cli("transcript", "synthesize", six["id"])[0] == 0
    found = _synthesis_check(lb)
    assert found is not None and found.status == "pass"
    assert found.detail == (
        "4 calls without a synthesis: 2 since 2026-06-13, which the 06:00 close synthesizes (`dream"
        " --catch-up`); 2 before 2026-06-13, which the close leaves: `logbook dream --catch-up --since"
        " 2026-05-01`"
    )
    _policy(lb, {"max_tier": 2, "until": "2026-12-31"})  # every call but Keel bolts is tier 3
    found = _synthesis_check(lb)
    assert found is not None and found.detail == (
        "4 calls without a synthesis: 1 before 2026-06-13, which the close leaves: `logbook dream"
        " --catch-up --since 2026-05-01`; 3 above the dream entry's max_tier 2, which stay on this machine"
    )
    _policy(lb, None)
    assert _synthesis_check(lb) is None, "no dream entry: nothing is ever synthesized, nothing to count"


def test_doctor_has_no_synthesis_line_when_every_call_has_one(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    call = _transcript(lb)
    _fake(monkeypatch)
    assert _synthesis_check(lb) is not None
    assert _cli("transcript", "synthesize", call["id"])[0] == 0
    assert _synthesis_check(lb) is None
