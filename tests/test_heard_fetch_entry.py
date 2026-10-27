"""`sync heard`'s fetches need a `heard` entry (S9): each fetch tells the transcript's host which
episode the owner played, a tier-2 fact, so `LOGBOOK_HEARD=feed` alone fetches nothing. The entry in
`policy/crossing.json` says `"fetch": true` with a `max_tier` the listens are at or under, and it is
checked before any request or any lookup of a name; `doctor` names it. Synthetic: invented podcasts
and the Oslo persona, who does not exist."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_heard_sync import FEED, VTT, _heard, _listen, _resolve, _run, _web

from logbook.contrib import doctor
from logbook.contrib.adapters import heard as step
from logbook.core import policy
from logbook.core.store import Logbook

TZ = "Europe/Oslo"


@pytest.fixture
def lb(monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(Path(os.environ["LOGBOOK_HOME"]), TZ)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    monkeypatch.setattr(step, "sleep", lambda _s: None)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 20))
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Havnepodden", f"{FEED}/a.vtt")
    return lb


def _entry(lb: Logbook, entry: dict[str, Any] | None) -> None:
    data = policy.read(lb.root)
    data.pop("heard", None)
    if entry is not None:
        data["heard"] = entry
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize(
    "entry",
    [
        None,
        {"max_tier": 2},
        {"max_tier": 2, "fetch": False},
        {"max_tier": 2, "fetch": "yes"},
        {"max_tier": 1, "fetch": True},
        {"max_tier": 2, "fetch": True, "until": "2026-10-19"},
        {"fetch": True},
    ],
    ids=["none", "no-fetch", "fetch-false", "fetch-not-a-boolean", "under-the-listens", "expired", "no-tier"],
)
def test_without_an_entry_that_allows_it_nothing_is_fetched_or_resolved(
    lb: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: dict[str, Any] | None,
) -> None:
    _entry(lb, entry)
    web = _web(monkeypatch, {f"{FEED}/a.vtt": (VTT, {"Content-Type": "text/vtt"})})
    resolver = _resolve(monkeypatch)

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert web.requests == [] and resolver.asked == [], "checked before any request"
    assert "1 feed transcript not fetched" in out and not _heard(lb)
    assert "heard" in err and "fetch" in err and "crossing.json" in err, "one line saying what to write"


def test_a_dry_run_without_the_entry_would_fetch_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry(lb, None)
    _web(monkeypatch, {})
    status, out, _err = _run(capsys, "sync", "heard", "--dry-run")
    assert status == 0 and "would fetch" not in out and "1 feed transcript not fetched" in out


def test_with_the_entry_the_transcript_is_fetched(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry(lb, {"max_tier": 2, "fetch": True, "until": "2026-12-31"})
    web = _web(monkeypatch, {f"{FEED}/a.vtt": (VTT, {"Content-Type": "text/vtt"})})
    status, _out, err = _run(capsys, "sync", "heard")
    assert status == 0, err
    assert len(web.requests) == 1 and len(_heard(lb)) == 1


def test_doctor_names_the_entry(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _entry(lb, None)
    said = doctor.crossing_check(lb.root).detail
    assert "heard" in said and '"fetch": true' in said, said
    _entry(lb, {"max_tier": 2, "fetch": True})
    assert "heard 2 fetch" in doctor.crossing_check(lb.root).detail
    _entry(lb, {"max_tier": 2, "fetch": False})
    said = doctor.crossing_check(lb.root).detail
    assert "heard 2" in said and "heard 2 fetch" not in said and '"fetch": true' in said
