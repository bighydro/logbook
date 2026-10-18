"""One rule for a line superseded twice (issue #321, the owner's v1 choice): a line is superseded while
at least one line of its kind that is not retracted supersedes it. A retracted superseder supersedes
nothing; a superseder superseded in turn still does. The readers read alike: `show` marks the line
superseded, the Day and the Library's Day page leave it out, the MCP door marks it as `show` does,
`search` still finds it (as `show` still lists it) and never a retracted line, and an index rebuilt
from the files says the same as one kept current. Ines Nordmann records a dinner on Saturday 3 October
2026 in Oslo, a person who does not exist: A is the transcript, B and C are heard again."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import mcp_server, serve
from logbook.core import policy
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-10-03"
AT = "2026-10-03T17:40:00Z"  # 19:40 in Oslo; `derive speakers` writes at the instant it hears again
TITLES = {"A": "Middag Alfa", "B": "Middag Bravo", "C": "Middag Charlie"}

# (shape, retracted) → the lines superseded and not retracted; every case of the issue
CASES = [
    ("twice", "", "A"),  # B and C both supersede A
    ("twice", "C", "A"),  # #321: C retracted, B still supersedes A; `review speakers` used to read A again
    ("twice", "B", "A"),
    ("twice", "BC", ""),  # no superseder stands: A stands again
    ("chain", "", "AB"),  # A←B←C: B superseded by C still supersedes A
    ("chain", "C", "A"),  # C retracted: B stands, A stays superseded
    ("chain", "B", ""),  # B retracted: it supersedes nothing, so A and C stand
    ("chain", "BC", ""),
]


def _transcript(name: str, supersedes: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "transcript/v1",
        "provider": "mlx-whisper",
        "raw_id": f"dinner-{name}",
        "title": TITLES[name],
        "participants": [],
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return {
        "at": AT,
        "end": None,
        "tz": TZ,
        "source": "transcription",
        "kind": "transcript",
        "tier": 2,
        "payload": payload,
    }


def _record(root: Path, shape: str, retracted: str) -> dict[str, dict[str, Any]]:
    lb = Logbook(root)
    a = lb.append(**_transcript("A", None))
    b = lb.append(**_transcript("B", a["id"]))
    c = lb.append(**_transcript("C", a["id"] if shape == "twice" else b["id"]))
    lines = {"A": a, "B": b, "C": c}
    for name in retracted:
        lb.retract(int(lines[name]["seq"]), "heard wrong")
    return lines


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(mcp_server, "_today", lambda _lb: DAY)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 3))
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcp": {"max_tier": 2}}), encoding="utf-8")
    return lb.root


def _out(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


@pytest.mark.parametrize(("shape", "retracted", "superseded"), CASES)
def test_every_reader_reads_a_line_superseded_twice_alike(
    root: Path, capsys: pytest.CaptureFixture[str], shape: str, retracted: str, superseded: str
):
    lines = _record(root, shape, retracted)
    gone = set(retracted) | set(superseded)
    standing = [name for name in "ABC" if name not in gone]
    listed = [name for name in "ABC" if name not in retracted]  # what `show` and `search` list
    by_id = {str(line["id"]): name for name, line in lines.items()}
    superseders = {"A": "BC"} if shape == "twice" else {"A": "B", "B": "C"}
    # the mark names the last superseder that stands, never a retracted one
    mark = {
        old: f"superseded by #{lines[[n for n in new if n not in retracted][-1]]['seq']}"
        for old, new in superseders.items()
        if old in superseded
    }

    # show: a retracted line is its marker; a superseded one says so; a standing one is its title
    rows = [
        row for row in _out(capsys, "show", DAY).splitlines() if "transcript" in row or "retracted #" in row
    ]
    assert len(rows) == 3, rows  # one instant: A, B, C in chain order
    for name, row in zip("ABC", rows, strict=True):
        if name in retracted:
            assert "retracted" in row, (name, row)
        elif name in superseded:
            assert row.endswith(mark[name]), (name, row)
        else:
            assert row.endswith(TITLES[name]), (name, row)

    # the Day, and the Library's Day page: the standing transcripts only
    day = json.loads(_out(capsys, "day", DAY, "--json", "--no-anniversaries", "--no-dream"))
    assert [item["title"] for item in day["unplaced"]] == [TITLES[n] for n in standing]
    page = serve.Site(Logbook(root)).respond(f"/day/{DAY}", "")
    assert page.status == 200
    body = page.body.decode("utf-8") if isinstance(page.body, bytes) else page.body
    assert [n for n in "ABC" if TITLES[n] in body] == standing

    # the MCP door: `show` through the gate, the retracted counted, the superseded marked
    data = mcp_server.call(root, "day_lines", {"day": DAY})["data"]
    assert [by_id[row["id"]] for row in data["lines"]] == listed and data["retracted"] == len(retracted)
    marked = {
        by_id[row["id"]]: row["text"] for row in data["lines"] if row["text"].startswith("superseded by #")
    }
    assert marked == mark
    for name in listed:
        one = mcp_server.call(root, "line", {"id": lines[name]["id"]})["data"]
        assert one["row"] == mark[name] if name in superseded else not one["row"].startswith("superseded"), (
            name
        )

    # search: a superseded line is still a hit, as `show` still lists it; a retracted one never is
    hits = json.loads(_out(capsys, "search", "Middag", "--json"))
    assert sorted(by_id[h["id"]] for d in hits["days"] for h in d["lines"]) == listed

    # the index, kept current and rebuilt from the files
    want = {str(lines[n]["id"]) for n in superseded}
    lb = Logbook(root)
    with lb.index() as idx:
        assert set(idx.superseded("transcript")) - {str(lines[n]["id"]) for n in retracted} == want
    lb.index_rebuild()
    with lb.index() as idx:
        assert set(idx.superseded("transcript")) - {str(lines[n]["id"]) for n in retracted} == want
