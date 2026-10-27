"""A signature never confirms pencil (R7): the dream's draft, a note a model derived (`derive
descriptions`, source `description`, `extra.derived`) and a note an agent wrote through the door
(source `mcp`) are proposals, and no way of signing a day names one in `confirmed`, nor carries a
disposition a standing signature gave one into the signature that supersedes it. The paths: `day
sign` (a first signature, and a re-sign through `sign_again.again`), `day reflect --sign` (through
`reflect.signature`, the code the Library's Sign form runs) and the door's `sign_day`.

Synthetic throughout: Ines Nordmann of Oslo, who does not exist."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, photo, utc

from logbook import cli
from logbook.contrib import mcp_server
from logbook.core import drafts, policy, signing
from logbook.core.store import Logbook

DAY = "2026-10-20"
MODEL = "model:qwen2.5-7b-instruct"


def _cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """DAY: the owner's note and a photo (ink), then a draft, a described photo and an agent's note
    (pencil). The door names sign_day; today is two days later."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 22))
    monkeypatch.setattr(mcp_server, "_today", lambda _lb: "2026-10-22")
    policy.policy_path(lb.root).write_text(
        json.dumps(
            {
                policy.DREAM_DESTINATION: {"max_tier": 2, "until": "2026-12-31"},
                "mcp": {"max_tier": 2, "write": ["sign_day"]},
            }
        ),
        encoding="utf-8",
    )
    lb.append_many(
        [
            {"at": utc(DAY, "12:30"), "source": "manual", "kind": "note", "tier": 2,
             "payload": {"schema": "note/v1", "text": "Wrote the crew list with Kari Nordmann."}},
            photo(utc(DAY, "17:00"), HOME),
        ]
    )  # fmt: skip
    note, picture = (next(line for line in lb.lines() if line["kind"] == kind) for kind in ("note", "photo"))
    lb.append(
        utc(DAY, "21:00"),
        MODEL,
        drafts.KIND,
        2,
        {
            "schema": drafts.SCHEMA,
            "unit": "day",
            "subject": DAY,
            "read_head": lb.meta["head"],
            "read_count": 2,
            "language": "en",
            "segments": [{"text": "You spent the day at home.", "evidence": [note["id"]]}],
            "proposals": [],
        },
    )
    lb.append_many(
        [
            {"at": utc(DAY, "17:00"), "source": "description", "kind": "note", "tier": 2,
             "payload": {"schema": "note/v1", "raw_id": picture["id"], "text": "A boat at a jetty.",
                         "extra": {"derived": True, "engine": "ollama", "model": "qwen2.5vl:7b",
                                   "photo": {"line": picture["id"], "asset_id": "a1", "library": "photos"},
                                   "keeper": picture["id"], "things": ["boat", "jetty"]}}},
            {"at": utc(DAY, "18:00"), "source": "mcp", "kind": "note", "tier": 2,
             "payload": {"schema": "note/v1", "text": "Proposed: book the crane for Friday."}},
        ]
    )  # fmt: skip
    return lb


def _of(lb: Logbook) -> tuple[set[str], set[str]]:
    """The ids of the day's ink and of its pencil, by what each line is."""
    lines = [line for line in Logbook(lb.root).lines() if line["kind"] != signing.KIND]
    pencil = {
        line["id"]
        for line in lines
        if line["kind"] == drafts.KIND
        or line["source"] in ("description", "mcp")
        or (line["payload"].get("extra") or {}).get("derived")
    }
    assert len(pencil) == 3
    return {line["id"] for line in lines} - pencil, pencil


def _signature(lb: Logbook) -> dict[str, Any]:
    return [line for line in Logbook(lb.root).lines() if line["kind"] == signing.KIND][-1]


def _standing_with_pencil_kept(lb: Logbook) -> None:
    """A standing signature made before the rule: every line of the page kept, the pencil among them,
    written through the frozen `signing.sign`, which takes a disposition on any line of the page."""
    ink, pencil = _of(lb)
    signing.sign(lb, DAY, confirm=None, dispositions={signing.KEPT: sorted(ink | pencil)})


def _assert_no_pencil(lb: Logbook) -> None:
    ink, pencil = _of(lb)
    p = _signature(lb)["payload"]
    assert not pencil & set(p["confirmed"]), "a signature never confirms pencil"
    assert not pencil & set(signing.dispositions_of(p)), "nor carries a disposition on it forward"
    assert ink <= set(p["confirmed"])


def test_is_pencil_knows_the_draft_the_derived_note_and_the_agent_s_note(lb: Logbook) -> None:
    ink, pencil = _of(lb)
    by_id = {line["id"]: line for line in lb.lines()}
    assert all(drafts.is_pencil(by_id[i]) for i in pencil)
    assert not any(drafts.is_pencil(by_id[i]) for i in ink)


def test_a_first_day_sign_confirms_no_pencil(lb: Logbook) -> None:
    for flags in ([], ["--confirm", "all"]):
        code, _out, err = _cli("day", "sign", DAY, *flags)
        assert code == 0, err
        _assert_no_pencil(lb)


def test_day_sign_again_drops_a_kept_disposition_on_pencil(lb: Logbook) -> None:
    _standing_with_pencil_kept(lb)
    code, _out, err = _cli("day", "sign", DAY)
    assert code == 0, err
    _assert_no_pencil(lb)


def test_reflect_sign_drops_a_kept_disposition_on_pencil(lb: Logbook) -> None:
    _standing_with_pencil_kept(lb)
    code, _out, err = _cli("day", "reflect", DAY, "--text", "A good day.", "--sign", "--accept", "none")
    assert code == 0, err
    _assert_no_pencil(lb)


def test_the_door_s_sign_day_drops_a_kept_disposition_on_pencil(lb: Logbook) -> None:
    _standing_with_pencil_kept(lb)
    mcp_server.call(lb.root, "sign_day", {"day": DAY})
    _assert_no_pencil(lb)


def test_the_door_s_first_sign_day_confirms_no_pencil(lb: Logbook) -> None:
    mcp_server.call(lb.root, "sign_day", {"day": DAY, "confirm": "all"})
    _assert_no_pencil(lb)


def test_a_disposition_typed_on_pencil_is_refused_and_nothing_is_written(lb: Logbook) -> None:
    _ink, pencil = _of(lb)
    seq = int(lb.meta["seq"])
    for line_id in sorted(pencil):
        code, _out, err = _cli("day", "sign", DAY, "--kept", line_id)
        assert code == 2 and "never confirms" in err
    assert int(Logbook(lb.root).meta["seq"]) == seq


def _spellings(seq: int) -> list[str]:
    """Every way `signing.sign` reads `seq` from an entry: as written, with a leading zero and a space,
    and in Arabic-Indic digits, which `str.isdigit` and `int` take as well."""
    arabic = "".join(chr(0x0660 + int(d)) for d in str(seq))
    return [str(seq), f" 0{seq}", f"00{seq}", arabic]


@pytest.mark.parametrize("flag", ["--confirm", "--kept"])
def test_pencil_named_by_any_spelling_of_its_seq_is_refused_on_day_sign(lb: Logbook, flag: str) -> None:
    seq = int(lb.meta["seq"])
    by_id = {line["id"]: line for line in lb.lines()}
    for line_id in sorted(_of(lb)[1]):
        for entry in _spellings(int(by_id[line_id]["seq"])):
            code, _out, err = _cli("day", "sign", DAY, flag, entry)
            assert code == 2 and "never confirms" in err, (entry, err)
    assert int(Logbook(lb.root).meta["seq"]) == seq


@pytest.mark.parametrize("key", ["confirm", "kept"])
def test_pencil_named_by_any_spelling_of_its_seq_is_refused_through_the_door(lb: Logbook, key: str) -> None:
    seq = int(lb.meta["seq"])
    by_id = {line["id"]: line for line in lb.lines()}
    for line_id in sorted(_of(lb)[1]):
        for entry in _spellings(int(by_id[line_id]["seq"])):
            with pytest.raises(ValueError, match="never confirms"):
                mcp_server.call(lb.root, "sign_day", {"day": DAY, key: [entry]})
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_an_agent_s_reflection_note_is_not_the_owner_s_reflection(lb: Logbook) -> None:
    from logbook.contrib import reflect

    lb.append(
        utc(DAY, "20:00"),
        "mcp",
        "note",
        2,
        {"schema": "note/v1", "text": "A good day, I'll call Per Hansen.", "labels": ["reflection"]},
    )
    lines, retracted = reflect.day_lines(Logbook(lb.root), DAY)
    assert reflect.reflections(lines, retracted) == []
