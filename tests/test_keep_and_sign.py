"""Keep and sign on the command line (RFC 0043 §5, slices C and E, part 1): `day sign DAY --keep N,N`
and `day reflect DAY --sign --keep N,N` keep the numbered sentences, links and photo of the day's
standing draft, `--revisit N=YYYY-MM-DD` dates a kept decision, `--mend N="…"` keeps a sentence in the
owner's own words, `--word WORD` is the day in a word, and `--done T,T --tomorrow T --let-go T` answer
the plan's tasks of the day. Every item is checked before the first line is written, and all of it is
written under one hold of the writer lock, before the signature, which never confirms a draft line
(RFC 0043 §6 rule 3).

Synthetic throughout: Ines Nordmann of Oslo, who does not exist, her boat-share log, a repository under
`nordmann-verft`, and two tasks in a Notion database that is made up."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from ideas_record import notion
from persona import HOME, photo, utc

from logbook import cli
from logbook.contrib import entities, mcp_server, plan
from logbook.core import crossing, drafts, policy, store
from logbook.core.store import Logbook

DAY, NEXT = "2026-10-20", "2026-10-21"
IDEA_ID = "019cadd3-6bc0-7dcd-9133-0000000000a1"
REPO_URL = "https://github.com/nordmann-verft/boat-share-log"
MODEL = "model:qwen2.5-7b-instruct"
TASKS_DB = "00000100-0000-4000-8000-000000000100"
ROPE, BILGE, LATER = (f"00000{n}-0000-4000-8000-000000000{n}" for n in (801, 802, 803))
LEARNED = "A crew list helps the boat-share log."
DECIDED = "Kari Nordmann sails on Saturday."
IDEA = "The boat-share log moved on."
PHOTO_TEXT = "The afternoon light on the water."
MENDED = "A crew list makes Saturday easy."
HERMES = "hermes"


def _cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()


def _task(at: str, page: str, title: str, properties: dict[str, Any]) -> dict[str, Any]:
    return notion(
        at, page, title, parent={"type": "database", "id": TASKS_DB}, path=["Plan", "Tasks"],
        properties={"Status": "To do", **properties},
    )  # fmt: skip


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 22))
    policy.policy_path(lb.root).write_text(
        json.dumps(
            {policy.DREAM_DESTINATION: {"max_tier": 2, "until": "2026-12-31"}, "hermes": {"max_tier": 2}}
        ),
        encoding="utf-8",
    )
    lb.append(
        "2026-06-01T08:00:00Z", "manual", entities.ENTITY, 2,
        entities.entity_payload(entities.IDEA, IDEA_ID, "Boat-share log"),
    )  # fmt: skip
    lb.append_many(
        [
            # the bilge pump's only line is of an earlier day: planned for DAY, due later
            _task("2026-10-12T07:00:00Z", BILGE, "Fix the bilge pump",
                  {"Planned": {"start": DAY, "end": None}, "Due": {"start": "2026-10-25", "end": None}}),
            _task(utc(DAY, "07:00"), ROPE, "Buy rope", {"Due": {"start": DAY, "end": None}}),
            _task(utc(DAY, "07:05"), LATER, "Paint the hull", {"Due": {"start": "2026-11-02", "end": None}}),
            {"at": utc(DAY, "12:30"), "source": "manual", "kind": "note", "tier": 2,
             "payload": {"schema": "note/v1", "text": "Wrote the crew list for the boat-share log."}},
            {"at": utc(DAY, "14:00"), "source": "chrome", "kind": "browse", "tier": 2,
             "payload": {"schema": "browse/v1", "raw_id": "chrome:1:abc", "url": REPO_URL, "action": "visit",
                         "browser": "chrome"}},
            photo(utc(DAY, "17:00"), HOME),
        ]
    )  # fmt: skip
    plan_file = plan.plan_path(lb.root)
    plan_file.write_text(json.dumps({"plan": {"tasks": TASKS_DB}}), encoding="utf-8")
    _draft(lb)
    return lb


def _draft(lb: Logbook) -> dict[str, Any]:
    """The evening's draft of DAY: a story, one sentence learned, one decided, one idea, the photo of
    the day and one learned sentence with nothing under it; a proposed event, then a proposed link."""
    by_kind = {line["kind"]: line["id"] for line in lb.lines() if line["at"].startswith(DAY)}
    note_id, browse_id, photo_id = by_kind["note"], by_kind["browse"], by_kind["photo"]
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "day",
        "subject": DAY,
        "read_head": lb.meta["head"],
        "read_count": 3,
        "language": "en",
        "segments": [
            {"text": "You spent the day at home.", "evidence": [note_id]},
            {"text": LEARNED, "evidence": [note_id]},
            {"text": DECIDED, "evidence": [note_id]},
            {"text": IDEA, "evidence": [note_id]},
            {"text": PHOTO_TEXT, "evidence": [photo_id]},
            {"text": "Something nothing shows.", "unsupported": True},
        ],
        "proposals": [
            {"kind": "event", "title": "Crew meeting", "start": utc(DAY, "18:00"), "end": utc(DAY, "19:00"),
             "place": None, "people": [], "evidence": [note_id]},
            {"kind": "link", "entity": IDEA_ID, "text": "The repository is the boat-share log's",
             "evidence": [browse_id]},
        ],
        "extra": {"parts": ["story", "learned", "decision", "ideas", "photo", "learned"],
                  "ideas": [{"segment": 4, "entity": IDEA_ID}]},
    }  # fmt: skip
    return lb.append(utc(DAY, "21:00"), MODEL, drafts.KIND, 2, payload)


# the draft numbers: event 1, link 2, then the keepable sentences after the proposals
EVENT, LINK, KEEP_LEARNED, KEEP_DECIDED, KEEP_IDEA, KEEP_PHOTO, KEEP_UNSUPPORTED = 1, 2, 3, 4, 5, 6, 7


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    return list(Logbook(lb.root).lines())


def _after(lb: Logbook, seq: int) -> list[dict[str, Any]]:
    return [line for line in _lines(lb) if int(line["seq"]) > seq]


def _kept(lb: Logbook) -> list[dict[str, Any]]:
    """The lines the close kept: notes and entity lines that name the draft they came from."""
    return [line for line in _lines(lb) if ((line.get("payload") or {}).get("extra") or {}).get("from")] + [
        line for line in _lines(lb) if "task" in _labels(line)
    ]


def _labels(line: dict[str, Any]) -> list[str]:
    return list((line.get("payload") or {}).get("labels") or [])


# -- the numbers --------------------------------------------------------------------------------------------


def test_the_pencil_numbers_every_keepable_sentence_after_the_proposals(lb: Logbook) -> None:
    code, out, err = _cli("day", DAY, "--json", "--no-anniversaries")
    assert code == 0, err
    draft = json.loads(out)["draft"]
    keep = {s["text"]: s.get("keep") for s in draft["segments"]}
    assert keep == {
        "You spent the day at home.": None,
        LEARNED: KEEP_LEARNED,
        DECIDED: KEEP_DECIDED,
        IDEA: KEEP_IDEA,
        PHOTO_TEXT: KEEP_PHOTO,
        "Something nothing shows.": KEEP_UNSUPPORTED,
    }
    assert [link["keep"] for link in draft["links"]] == [LINK]
    code, out, err = _cli("day", DAY, "--no-anniversaries")
    assert code == 0, err
    rows = {line.split("  ")[-1]: line for line in out.splitlines() if "  keep " in line}
    # an unsupported sentence keeps its number in the JSON and is offered nothing on the row
    assert sorted(rows) == [f"keep {n}" for n in (KEEP_LEARNED, KEEP_DECIDED, KEEP_IDEA, KEEP_PHOTO)]
    assert DECIDED in rows[f"keep {KEEP_DECIDED}"] and f"link {LINK}" in out
    assert f"keep {KEEP_DECIDED} {DECIDED}" not in out  # no number beside the name the sentence opens with


# -- the acceptance: keep one of each and sign ---------------------------------------------------------------


def test_keep_one_learned_one_idea_one_link_and_a_word_then_sign_in_that_order_under_one_lock(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    holds: list[int] = []
    real = Logbook.writer

    def counted(self: Logbook, *args: Any, **kwargs: Any) -> Any:
        holds.append(store._held.get(self._lock_path(), 0))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Logbook, "writer", counted)
    seq = int(lb.meta["seq"])
    code, out, err = _cli(
        "day", "sign", DAY, "--keep", f"{KEEP_LEARNED},{KEEP_IDEA},{LINK}", "--word", "calm"
    )
    assert code == 0, err
    assert no_network == []
    written = _after(lb, seq)
    kinds = [(line["kind"], _labels(line)) for line in written]
    assert kinds == [
        ("note", ["learned"]),
        ("note", ["idea"]),
        ("entity", []),
        ("note", ["word"]),
        ("signed-day", []),
    ]
    learned, idea, link, word, signature = written
    draft_id = next(line["id"] for line in _lines(lb) if line["kind"] == "draft")
    assert learned["payload"]["text"] == LEARNED and idea["payload"]["text"] == IDEA
    assert learned["payload"]["extra"]["from"] == draft_id
    assert learned["payload"]["extra"]["segment"] == {"part": "learned", "n": 2}
    assert idea["payload"]["extra"]["segment"] == {"part": "ideas", "n": 4}
    assert idea["payload"]["extra"]["entity"] == IDEA_ID
    assert link["payload"]["entity"]["id"] == IDEA_ID
    assert link["payload"]["extra"]["from"] == draft_id
    assert word["payload"]["text"] == "calm"
    confirmed = set(signature["payload"]["confirmed"])
    assert {learned["id"], idea["id"], link["id"], word["id"]} <= confirmed
    assert draft_id not in confirmed  # rule 3
    # the first hold of the command is the outer one; every later writer() call re-enters it
    assert holds and holds[0] == 0 and all(h >= 1 for h in holds[1:])
    # the Day shows them kept, and the "since you signed" reading keys them by content
    code, out, err = _cli("day", DAY, "--json", "--no-anniversaries")
    draft = json.loads(out)["draft"]
    kept = {s["text"]: s.get("kept") for s in draft["segments"] if s.get("keep")}
    assert kept[LEARNED] == {"line": learned["id"], "seq": learned["seq"]}
    assert kept[DECIDED] is None
    assert draft["links"][0]["kept"] == {"line": link["id"], "seq": link["seq"]}


def test_a_kept_decision_with_a_revisit_day_and_a_mended_sentence(lb: Logbook) -> None:
    seq = int(lb.meta["seq"])
    code, _out, err = _cli(
        "day", "sign", DAY, "--keep", f"{KEEP_LEARNED},{KEEP_DECIDED}",
        "--revisit", f"{KEEP_DECIDED}=2026-11-20", "--mend", f"{KEEP_LEARNED}={MENDED}",
    )  # fmt: skip
    assert code == 0, err
    learned, decided, _signature = _after(lb, seq)
    assert learned["payload"]["text"] == MENDED
    assert learned["payload"]["extra"]["from"] == decided["payload"]["extra"]["from"]
    assert learned["payload"]["extra"]["proposal"] == {"kind": "learned", "text": LEARNED}
    assert decided["payload"]["labels"] == ["decision"]
    assert decided["payload"]["extra"]["revisit"] == "2026-11-20"


def test_kept_lines_take_the_moment_you_signed_when_it_is_on_the_day(lb: Logbook) -> None:
    seq = int(lb.meta["seq"])
    at = f"{DAY}T19:00:00+02:00"
    flags = ["--keep", f"{KEEP_LEARNED},{LINK}", "--word", "calm", "--at", at]
    code, _out, err = _cli("day", "sign", DAY, *flags)
    assert code == 0, err
    *kept, signature = _after(lb, seq)
    assert [line["at"] for line in kept] == [f"{DAY}T17:00:00Z"] * 3 == [signature["at"]] * 3


def test_a_word_with_a_digit_in_it_is_a_word(lb: Logbook) -> None:
    code, _out, err = _cli("day", "sign", DAY, "--word", "covid19")
    assert code == 0, err
    for number in ("3.5", "7/10", "-2"):
        assert _cli("day", "sign", DAY, "--word", number)[0] == 2


def test_the_photo_of_the_day_is_kept_as_a_star_with_its_note(lb: Logbook) -> None:
    seq = int(lb.meta["seq"])
    code, _out, err = _cli("day", "sign", DAY, "--keep", str(KEEP_PHOTO))
    assert code == 0, err
    keeper, signature = _after(lb, seq)
    assert keeper["kind"] == "keeper" and keeper["payload"]["lane"] == "memory"
    assert keeper["payload"]["note"] == PHOTO_TEXT and keeper["source"] == "manual"
    assert keeper["id"] in signature["payload"]["confirmed"]


@pytest.mark.parametrize(
    ("flags", "said"),
    [
        (["--keep", "99"], "no keepable sentence or link 99"),
        (["--keep", str(EVENT)], "--accept"),
        (["--keep", str(KEEP_UNSUPPORTED)], "rests on no line"),
        (["--keep", "x"], "--keep takes"),
        (["--revisit", f"{KEEP_LEARNED}=2026-11-20", "--keep", str(KEEP_LEARNED)], "a decision"),
        (["--revisit", f"{KEEP_DECIDED}=2026-11-20"], "not kept"),
        (["--revisit", f"{KEEP_DECIDED}=20 Nov", "--keep", str(KEEP_DECIDED)], "YYYY-MM-DD"),
        (["--revisit", f"{KEEP_DECIDED}={DAY}", "--keep", str(KEEP_DECIDED)], "after"),
        (["--mend", f"{LINK}=Mine", "--keep", str(LINK)], "a link"),
        (["--mend", f"{KEEP_LEARNED}=  ", "--keep", str(KEEP_LEARNED)], "empty"),
        (["--keep", f"{KEEP_LEARNED}", "--word", "two words"], "one word"),
        (["--keep", f"{KEEP_LEARNED}", "--word", "42"], "not a number"),
        (["--keep", f"{KEEP_LEARNED}", "--done", "1", "--let-go", "1"], "two answers"),
        (["--keep", f"{KEEP_LEARNED}", "--done", "9"], "no task 9"),
        (["--keep", f"{KEEP_LEARNED}", "--confirm", "999"], "not a line on the page"),
    ],
)
def test_any_refusal_writes_nothing_and_says_why_in_one_sentence(
    lb: Logbook, flags: list[str], said: str
) -> None:
    seq = int(lb.meta["seq"])
    code, out, err = _cli("day", "sign", DAY, *flags)
    assert code == 2, out
    assert said in err and err.count("\n") == 1
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_a_link_whose_line_names_nothing_the_entity_is_known_by_is_refused_and_nothing_written(
    lb: Logbook,
) -> None:
    """The link is checked before the first sentence is written, so a refusal of the last item leaves
    the first unwritten."""
    browse = next(line for line in lb.lines() if line["kind"] == "browse")
    lb.retract(int(browse["seq"]), "not mine")
    seq = int(lb.meta["seq"])
    code, _out, err = _cli("day", "sign", DAY, "--keep", f"{KEEP_LEARNED},{LINK}")
    assert code == 2 and f"link {LINK}" in err
    assert int(Logbook(lb.root).meta["seq"]) == seq


# -- the word ----------------------------------------------------------------------------------------------


def test_the_day_in_a_word_is_one_word_once(lb: Logbook) -> None:
    assert _cli("day", "sign", DAY, "--word", "calm")[0] == 0
    seq = int(lb.meta["seq"])
    code, _out, err = _cli("day", "sign", DAY, "--word", "busy")
    assert code == 2 and "calm" in err and "repair retract" in err
    assert int(Logbook(lb.root).meta["seq"]) == seq
    code, _out, err = _cli("day", "sign", DAY)  # a re-sign keeps the word
    assert code == 0, err
    words = [line for line in _lines(lb) if "word" in _labels(line)]
    assert [w["payload"]["text"] for w in words] == ["calm"]
    signature = [line for line in _lines(lb) if line["kind"] == "signed-day"][-1]
    assert words[0]["id"] in signature["payload"]["confirmed"]


# -- a re-sign ---------------------------------------------------------------------------------------------


def test_a_re_sign_keeps_the_kept_notes_and_never_writes_them_twice(lb: Logbook) -> None:
    assert _cli("day", "sign", DAY, "--keep", f"{KEEP_LEARNED},{LINK}", "--done", "1")[0] == 0
    kept = _kept(lb)
    assert len(kept) == 3
    code, _out, err = _cli("day", "sign", DAY)
    assert code == 0, err
    signature = [line for line in _lines(lb) if line["kind"] == "signed-day"][-1]
    ids = {line["id"] for line in _lines(lb) if "learned" in _labels(line) or "task" in _labels(line)}
    assert ids <= set(signature["payload"]["confirmed"])
    seq = int(lb.meta["seq"])
    code, _out, err = _cli("day", "sign", DAY, "--keep", str(KEEP_LEARNED))
    assert code == 2 and "kept already" in err
    code, _out, err = _cli("day", "sign", DAY, "--done", "1")
    assert code == 2 and "answered" in err
    assert int(Logbook(lb.root).meta["seq"]) == seq
    assert kept == _kept(lb)


# -- rule 3 ------------------------------------------------------------------------------------------------


def test_a_signature_never_confirms_the_draft_line(lb: Logbook) -> None:
    draft = next(line for line in lb.lines() if line["kind"] == "draft")
    seq = int(lb.meta["seq"])
    code, _out, err = _cli("day", "sign", DAY, "--confirm", str(draft["seq"]))
    assert code == 2 and "draft" in err and err.count("\n") == 1
    assert int(Logbook(lb.root).meta["seq"]) == seq
    for flags in ([], ["--confirm", "all"]):
        code, _out, err = _cli("day", "sign", DAY, *flags)
        assert code == 0, err
        signature = [line for line in _lines(lb) if line["kind"] == "signed-day"][-1]
        assert draft["id"] not in signature["payload"]["confirmed"]
        assert signature["payload"]["page"]["lines"] == 6  # the digest still covers the draft


def test_the_door_s_sign_day_never_confirms_the_draft_and_takes_nothing_new(lb: Logbook) -> None:
    data = json.loads(policy.policy_path(lb.root).read_text(encoding="utf-8"))
    data["mcp"] = {"max_tier": 2, "write": ["sign_day"]}
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")
    draft = next(line for line in lb.lines() if line["kind"] == "draft")
    seq = int(lb.meta["seq"])
    with pytest.raises(ValueError, match="draft"):  # a SignError, as the door says every refusal
        mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": [str(draft["seq"])]})
    assert int(Logbook(lb.root).meta["seq"]) == seq
    with pytest.raises(mcp_server.ToolError, match="no argument 'keep'"):  # agents propose; the owner keeps
        mcp_server.call(lb.root, "sign_day", {"day": DAY, "keep": "3"})
    answer = mcp_server.call(lb.root, "sign_day", {"day": DAY})
    assert answer["data"]["above_ceiling"] == 0
    signature = [line for line in _lines(lb) if line["kind"] == "signed-day"][-1]
    assert draft["id"] not in signature["payload"]["confirmed"]
    assert len(signature["payload"]["confirmed"]) == signature["payload"]["page"]["lines"] - 1


def test_reflect_sign_keeps_and_never_confirms_the_draft(lb: Logbook) -> None:
    seq = int(lb.meta["seq"])
    code, _out, err = _cli(
        "day", "reflect", DAY, "--text", "A good day for the crew list.", "--sign", "--accept", "none",
        "--keep", str(KEEP_DECIDED), "--revisit", f"{KEEP_DECIDED}=2026-11-20", "--word", "steady",
        "--tomorrow", "2",
    )  # fmt: skip
    assert code == 0, err
    written = _after(lb, seq)
    assert [(line["kind"], _labels(line)) for line in written] == [
        ("note", ["reflection"]),
        ("note", ["decision"]),
        ("note", ["word"]),
        ("note", ["task"]),
        ("signed-day", []),
    ]
    draft = next(line for line in lb.lines() if line["kind"] == "draft")
    assert draft["id"] not in written[-1]["payload"]["confirmed"]
    assert {line["id"] for line in written[:-1]} <= set(written[-1]["payload"]["confirmed"])


def test_kept_flags_belong_to_sign_and_reflect_with_sign(lb: Logbook) -> None:
    code, _out, err = _cli("day", DAY, "--keep", "3")
    assert code == 2 and "day sign" in err
    code, _out, err = _cli("day", "reflect", DAY, "--text", "A day.", "--keep", "3")
    assert code == 2 and "--sign" in err


# -- the plan answered -------------------------------------------------------------------------------------


def test_the_plan_numbers_today_s_tasks_planned_before_due(lb: Logbook) -> None:
    code, out, err = _cli("show", "plan", DAY, "--json")
    assert code == 0, err
    rows = json.loads(out)["tasks"]["rows"]
    assert [(r["number"], r["title"]) for r in rows] == [(1, "Buy rope"), (2, "Fix the bilge pump")]
    code, out, err = _cli("show", "plan", DAY)
    assert code == 0, err
    assert "  1  " in out and "Buy rope" in out and "Paint the hull" not in out


def test_a_task_with_neither_planned_nor_due_is_not_dated(lb: Logbook) -> None:
    tiller = "00000804-0000-4000-8000-000000000804"
    lb.append_many(
        [_task(utc(DAY, "07:10"), tiller, "Varnish the tiller", {"Started": {"start": DAY, "end": None}})]
    )
    rows = plan.read(lb, DAY).to_json()["tasks"]["rows"]
    assert [r["title"] for r in rows] == ["Buy rope", "Fix the bilge pump"]


def test_done_tomorrow_and_let_go_each_write_one_task_note_before_the_signature(lb: Logbook) -> None:
    rows = plan.read(lb, DAY).to_json()["tasks"]["rows"]
    seq = int(lb.meta["seq"])
    code, _out, err = _cli("day", "sign", DAY, "--done", "1", "--let-go", "2")
    assert code == 0, err
    rope, bilge, signature = _after(lb, seq)
    assert signature["kind"] == "signed-day"
    for line, row, outcome in ((rope, rows[0], "done"), (bilge, rows[1], "let-go")):
        assert line["kind"] == "note" and line["payload"]["labels"] == ["task"]
        assert line["payload"]["text"] == row["title"]
        assert line["payload"]["extra"] == {"task": row["id"], "line": row["line"], "outcome": outcome}
        assert line["id"] in signature["payload"]["confirmed"]
    bilge_line = next(x for x in lb.lines() if x["id"] == rows[1]["line"])
    assert bilge_line["at"].startswith("2026-10-12")  # its latest line is from an earlier day
    assert "dispositions" not in signature["payload"]  # never a disposition of a line off the page
    code, out, err = _cli("show", "plan", DAY)
    assert code == 0, err
    assert "done today" in out and "let go" in out and "  1  " not in out
    rows_after = json.loads(_cli("show", "plan", DAY, "--json")[1])["tasks"]["rows"]
    assert [r.get("number") for r in rows_after] == [None, None]
    assert [r["answered"]["outcome"] for r in rows_after] == ["done", "let-go"]


def test_a_task_answered_already_or_given_two_answers_is_refused(lb: Logbook) -> None:
    assert _cli("day", "sign", DAY, "--tomorrow", "1")[0] == 0
    seq = int(lb.meta["seq"])
    for flags, said in (
        (["--done", "1"], "answered"),
        (["--done", "2", "--tomorrow", "2"], "two answers"),
        (["--let-go", "3"], "no task 3"),
    ):
        code, _out, err = _cli("day", "sign", DAY, *flags)
        assert code == 2 and said in err, err
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_the_task_notes_cross_to_hermes_at_tier_2_with_the_signed_day(lb: Logbook) -> None:
    assert _cli("day", "sign", DAY, "--done", "1", "--tomorrow", "2")[0] == 0
    answers = [line["id"] for line in lb.lines() if "task" in _labels(line)]
    assert len(answers) == 2
    req = crossing.request(lb, HERMES, utc(DAY, "00:00"), utc(NEXT, "06:00"), (1, 2))
    sel = crossing.select(lb, req)
    assert set(answers) <= {str(line["id"]) for line in sel.lines}
    code, out, err = _cli(
        "export", "crossing", "--to", HERMES, "--since", utc(DAY, "00:00"), "--until", utc(NEXT, "06:00"),
        "--tier", "1,2", "--dry-run",
    )  # fmt: skip
    assert code == 0, err
    assert "note: 3" in out  # the owner's note of the day and the two answers


# -- the busy record ---------------------------------------------------------------------------------------


def test_a_busy_record_answers_the_one_way_and_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "WAIT", True)  # `--no-wait` sets it; put back after the test
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = lb._lock_path()
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(
            json.dumps({"pid": other.pid, "command": "sync granola", "since": "2026-10-20T06:00:00Z"}),
            encoding="utf-8",
        )
        seq = int(Logbook(lb.root).meta["seq"])
        code, _out, err = _cli(
            "--no-wait",
            "day",
            "sign",
            DAY,
            "--keep",
            f"{KEEP_LEARNED},{LINK}",
            "--word",
            "calm",
            "--done",
            "1",
        )
        assert code == 2 and "sync granola" in err
        assert int(Logbook(lb.root).meta["seq"]) == seq
    finally:
        other.kill()
        other.wait()
