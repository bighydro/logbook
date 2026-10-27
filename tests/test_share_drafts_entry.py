"""`share day` holds a draft to the entry it was written under (R4), as every other crossing does
(`drafts.held_by_entry`): a tier-2 draft of the day whose `dream` entry is missing, lowered under its
tier or expired stays home, whatever the destination's own ceiling, and is counted in the manifest's
`held_back` and in the crossing line's `held_back_by_entry`. Synthetic: Ines and Ola Nordmann of
Oslo, who do not exist (`shared_day.py`)."""

from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from persona import utc
from shared_day import DAY, both

from logbook import cli
from logbook.core import crossing, drafts, policy
from logbook.core.store import Logbook

MODEL = "model:qwen2.5-7b-instruct"


def _with_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dream: dict[str, Any] | None) -> Logbook:
    ines, _ola = both(tmp_path, monkeypatch)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    path = policy.policy_path(ines.root)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop(policy.DREAM_DESTINATION, None)
    if dream is not None:
        data[policy.DREAM_DESTINATION] = dream
    path.write_text(json.dumps(data), encoding="utf-8")
    note = next(line for line in ines.lines() if line["kind"] == "note")
    ines.append(
        utc(DAY, "23:00"),
        MODEL,
        drafts.KIND,
        2,
        {
            "schema": drafts.SCHEMA,
            "unit": "day",
            "subject": DAY,
            "read_head": ines.meta["head"],
            "read_count": 1,
            "language": "en",
            "segments": [{"text": "You anchored off Hovedøya.", "evidence": [note["id"]]}],
            "proposals": [],
        },
    )
    return ines


def _share(ines: Logbook, out: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cli.main(["export", "share", "day", DAY, "--to", "ola", "--tier", "2", "--out", str(out)])
    with zipfile.ZipFile(out) as zf:
        lines = [json.loads(s) for s in zf.read("lines.jsonl").decode("utf-8").splitlines() if s.strip()]
        manifest = json.loads(zf.read("manifest.json"))
    return lines, manifest


def _crossing(ines: Logbook) -> dict[str, Any]:
    return [line for line in Logbook(ines.root).lines() if line["kind"] == crossing.KIND][-1]["payload"]


def test_a_draft_its_entry_allows_is_shipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ines = _with_draft(tmp_path, monkeypatch, {"max_tier": 2, "until": "2026-12-31"})
    lines, _manifest = _share(ines, tmp_path / "page.zip")
    assert [line["kind"] for line in lines].count(drafts.KIND) == 1


@pytest.mark.parametrize(
    "dream",
    [None, {"max_tier": 1, "until": "2026-12-31"}, {"max_tier": 2, "until": "2026-06-14"}],
    ids=["missing", "lowered", "expired"],
)
def test_a_draft_its_entry_no_longer_allows_is_never_shipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dream: dict[str, Any] | None
) -> None:
    allowed = _with_draft(tmp_path / "allowed", monkeypatch, {"max_tier": 2, "until": "2026-12-31"})
    _lines, before = _share(allowed, tmp_path / "allowed.zip")
    ines = _with_draft(tmp_path / "held", monkeypatch, dream)
    lines, manifest = _share(ines, tmp_path / "page.zip")
    assert drafts.KIND not in {line["kind"] for line in lines}
    assert manifest["lines"] == before["lines"] - 1
    assert manifest["held_back"] == before["held_back"] + 1, "counted in what stayed home"
    assert _crossing(ines)["counts"]["held_back_by_entry"] == 1
