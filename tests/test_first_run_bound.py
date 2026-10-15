"""A source's first scheduled run reads two weeks, not its whole history. `sync --scheduled` (what the
installed schedule runs) bounds a live source that has no watermark yet to the last 14 local days, keeps
its watermark as any run does, says so in one line and leaves a mark `doctor` names until the history is
read with `--since`; a run by hand starts where it always did and `--since` always wins. A dry run that
meets the source's quota or rate limit stops at once and writes nothing. Fake live sources whose pull
honours `since`, nothing real; synthetic notes only; no connection is opened."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.commands.common import _takes
from logbook.contrib import adapters, doctor, first_run, last_run, notify
from logbook.core.store import Logbook

NOW = datetime(2026, 10, 8, 17, 0, 12, tzinfo=UTC)  # a Thursday, 19:00 in Oslo
DAY = "2026-09-25"  # 14 local days ending on the 8th: the 25th to the 8th
BOUND = "2026-09-24T22:00:00Z"  # local midnight of DAY in Oslo (summer time), in UTC
FIRST = datetime(2025, 10, 1, 10, 0, tzinfo=UTC)  # the fake's history: one item a day from here
LINE = (
    f"history: first scheduled run read from {DAY}; for the history run `logbook sync history --since <date>`"
)
QUOTA = "HTTP 429: Quota exceeded for quota metric 'Queries' and limit 'Queries per day'"


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class History:
    """A live adapter as `adapters.LiveAdapter` describes one, with a long history: one item a day from
    `FIRST` to `last`, each item's source clock its own time. A pull yields the items at or after `since`
    (every one without it), oldest first, and notes the `since` it was given. With `limit_at` it answers
    a quota after that many items: at once when told not to wait (`wait_on_limits=False`), else it waits
    the limit out and carries on, as a real source does."""

    NAME = "history"
    ENV = ("LOGBOOK_HISTORY_KEY",)

    def __init__(self, last: datetime, limit_at: int | None = None, fail_at: int | None = None) -> None:
        self.last = last
        self.limit_at = limit_at
        self.fail_at = fail_at
        self.sinces: list[str | None] = []
        self.waits: list[bool] = []
        self.waited = 0

    def configure(self, env: Any) -> object | None:
        return {"key": "k"} if env.get(self.ENV[0], "").strip() else None

    def pull(
        self,
        config: Any,
        since: str | None = None,
        progress: Any = None,
        counts: Any = None,
        wait_on_limits: bool = True,
    ) -> Iterator[dict[str, Any]]:
        self.sinces.append(since)
        self.waits.append(wait_on_limits)
        for n, draft in enumerate(self.items(since)):
            if self.limit_at is not None and n == self.limit_at:
                if not wait_on_limits:
                    raise adapters.LimitReached(QUOTA)
                self.waited += 1
            if self.fail_at is not None and n == self.fail_at:
                raise OSError("the service went away")
            yield draft

    def items(self, since: str | None) -> Iterator[dict[str, Any]]:
        when = FIRST
        while when <= self.last:
            at = _stamp(when)
            when += timedelta(days=1)
            if since is None or at >= since:
                payload = {"schema": "note/v1", "raw_id": f"{self.NAME}:{at}", "text": "a synthetic note"}
                yield {"at": at, "source": self.NAME, "kind": "note", "tier": 3, "payload": payload}

    def watermark(self, draft: dict[str, Any]) -> str | None:
        return str(draft["at"])


class Resuming(History):
    """A source whose lasting state is its own (`RESUMES`, as `mail` and `gmail`): the watermark is None,
    and what it reached is told to the walk keeper `sync` drives, written once the lines are in."""

    NAME = "resuming"
    ENV = ("LOGBOOK_RESUMING_KEY",)
    RESUMES = True

    def pull(  # type: ignore[override]
        self,
        config: Any,
        since: str | None = None,
        progress: Any = None,
        counts: Any = None,
        walk: Any = None,
    ) -> Iterator[dict[str, Any]]:
        saved = walk.start() if walk is not None else None
        after = saved.get("newest") if isinstance(saved, dict) else None
        self.sinces.append(since)
        n = 0
        for draft in self.items(since):
            if since is None and after is not None and draft["at"] <= after:
                continue
            n += 1
            yield draft
            if walk is not None:
                walk.reached(n, {"newest": draft["at"]})

    def watermark(self, draft: dict[str, Any]) -> str | None:
        return None


class Stream(History):
    """A source with no history to read (`HISTORY = False`, as `ais`): what it hears is the present."""

    NAME = "stream"
    ENV = ("LOGBOOK_STREAM_KEY",)
    HISTORY = False


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name in notify.ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(doctor, "EXTRAS", ())  # what this machine has installed is not the test's
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 0)
    return lb


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """`last_run.now()`, the scheduled run's clock, reads the first stamp of this list; a test moves it."""
    stamps = [NOW]
    monkeypatch.setattr(last_run, "now", lambda: stamps[0])
    return stamps


def _sources(monkeypatch: pytest.MonkeyPatch, *fakes: History) -> None:
    monkeypatch.setattr(adapters, "live_adapters", lambda: list(fakes))
    for fake in fakes:
        monkeypatch.setenv(fake.ENV[0], "k")


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(list(args))
    except SystemExit as e:
        status = int(e.code or 0)
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


def _state(lb: Logbook, name: str = "history") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / f"{name}.json").read_text(encoding="utf-8"))
    return data


def _ats(lb: Logbook, source: str = "history") -> list[str]:
    return [line["at"] for line in lb.lines() if line["source"] == source]


def _doctor_line(lb: Logbook, name: str = "history") -> doctor.Check:
    import os

    found = {c.name: c for c in doctor.run(Logbook.find(), os.environ)}
    return found[f"sync:{name}"]


# -- the first scheduled run ---------------------------------------------------------------------------------


def test_the_first_scheduled_run_of_a_source_reads_the_last_14_days_and_says_so(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    status, out, _err = _run(capsys, "sync", "--scheduled")
    assert status == 0
    assert source.sinces == [BOUND], "from local midnight 13 days before today, never from the beginning"
    ats = _ats(lb)
    assert len(ats) == 14 and ats[0] == "2026-09-25T10:00:00Z" and ats[-1] == "2026-10-08T10:00:00Z"
    assert out.count(LINE) == 1
    assert _state(lb)["since"] == "2026-10-08T10:00:00Z", "the watermark is the newest item's, as always"
    assert _state(lb)["first_run"]["from"] == BOUND


def test_the_second_scheduled_run_carries_on_from_the_watermark(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    source.last = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)  # a new item since
    clock[0] = datetime(2026, 10, 9, 16, 0, tzinfo=UTC)
    status, out, _err = _run(capsys, "sync", "--scheduled")
    assert status == 0
    assert source.sinces == [BOUND, "2026-10-08T10:00:00Z"], "from the watermark, not a new window"
    assert "first scheduled run" not in out
    ats = _ats(lb)
    assert ats[-1] == "2026-10-09T10:00:00Z"
    assert len(ats) == len(set(ats)) == 15, "nothing lost, nothing twice"


def test_a_bounded_run_that_saw_nothing_still_counts_and_the_next_starts_from_the_same_day(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 9, 1, 10, 0, tzinfo=UTC))  # nothing in the last two weeks
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    assert _ats(lb) == [] and "since" not in _state(lb)
    clock[0] = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)  # four days on: a fresh window would start later
    source.last = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
    status, out, _err = _run(capsys, "sync", "--scheduled")
    assert status == 0
    assert source.sinces == [BOUND, BOUND], "the window never slides: nothing after its start is skipped"
    assert "first scheduled run" not in out, "said once, on the run that bounded it"
    assert sorted(_ats(lb))[0] == "2026-09-25T10:00:00Z"
    assert _state(lb)["since"] == "2026-10-12T10:00:00Z"


def test_a_source_with_lines_from_an_export_within_the_window_starts_from_them(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    class Resumes(History):
        KIND = "note"

        def resume(self, config: Any, mark: str) -> str:
            return mark

    source = Resumes(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    lb.append(
        "2026-10-05T10:00:00Z",
        "history",
        "note",
        3,
        {"schema": "note/v1", "raw_id": "history:2026-10-05T10:00:00Z", "text": "a synthetic note"},
    )
    _run(capsys, "sync", "--scheduled")
    assert source.sinces == ["2026-10-05T10:00:00Z"], "already inside the window: nothing to bound"
    assert "first_run" not in _state(lb)


def test_an_export_line_early_in_the_window_keeps_the_sources_lookback_and_leaves_no_mark(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    class LooksBack(History):
        KIND = "note"

        def resume(self, config: Any, mark: str) -> str:
            return _stamp(datetime.fromisoformat(mark.replace("Z", "+00:00")) - timedelta(hours=24))

    source = LooksBack(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    lb.append(
        "2026-09-25T06:00:00Z",  # inside the window; a day before it is outside
        "history",
        "note",
        3,
        {"schema": "note/v1", "raw_id": "history:2026-09-25T06:00:00Z", "text": "a synthetic note"},
    )
    _status, out, _err = _run(capsys, "sync", "--scheduled")
    assert source.sinces == ["2026-09-24T06:00:00Z"], "on from the record's line, less the lookback"
    assert "first scheduled run" not in out and "first_run" not in _state(lb), "nothing left unread"


def test_a_source_with_lines_from_an_old_export_is_bounded_too(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    class Resumes(History):
        KIND = "note"

        def resume(self, config: Any, mark: str) -> str:
            return mark

    source = Resumes(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    lb.append(
        "2026-01-05T10:00:00Z",
        "history",
        "note",
        3,
        {"schema": "note/v1", "raw_id": "history:2026-01-05T10:00:00Z", "text": "a synthetic note"},
    )
    _status, out, _err = _run(capsys, "sync", "--scheduled")
    assert source.sinces == [BOUND]
    assert LINE in out


def test_a_source_with_no_history_is_never_bounded(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = Stream(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _status, out, _err = _run(capsys, "sync", "--scheduled")
    assert source.sinces == [None]
    assert "first scheduled run" not in out
    assert "first_run" not in _state(lb, "stream")


def test_a_source_that_keeps_its_own_state_is_bounded_once_then_resumes_from_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = Resuming(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _status, out, _err = _run(capsys, "sync", "--scheduled")
    assert source.sinces == [BOUND]
    assert "resuming: first scheduled run read from 2026-09-25" in out
    assert len(_ats(lb, "resuming")) == 14
    source.last = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    clock[0] = datetime(2026, 10, 9, 16, 0, tzinfo=UTC)
    _status, out, _err = _run(capsys, "sync", "--scheduled")
    assert source.sinces == [BOUND, None], "its own state carries it on, as by hand"
    assert _ats(lb, "resuming")[-1] == "2026-10-09T10:00:00Z" and len(_ats(lb, "resuming")) == 15


# -- by hand, and --since ------------------------------------------------------------------------------------


def test_a_run_by_hand_without_since_reads_from_the_beginning_as_before(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    status, out, _err = _run(capsys, "sync", "history")
    assert status == 0 and source.sinces == [None]
    assert len(_ats(lb)) == 373 and "first scheduled run" not in out
    assert "first_run" not in _state(lb)
    _run(capsys, "sync", "--all")
    assert source.sinces == [None, "2026-10-08T10:00:00Z"], "sync --all by hand: from the watermark"


def test_since_wins_and_reading_back_past_the_bound_clears_the_mark(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    _run(capsys, "sync", "history", "--since", "2026-09-30T00:00:00Z")  # inside the window: history unread
    assert source.sinces[-1] == "2026-09-30T00:00:00Z"
    assert "first_run" in _state(lb)
    status, _out, _err = _run(capsys, "sync", "history", "--since", "2026-01-01T00:00:00Z")
    assert status == 0 and source.sinces[-1] == "2026-01-01T00:00:00Z"
    ats = sorted(_ats(lb))
    assert ats[0] == "2026-01-01T10:00:00Z" and len(ats) == len(set(ats)), "the history, each line once"
    assert "first_run" not in _state(lb), "the history is read"
    assert _state(lb)["since"] == "2026-10-08T10:00:00Z", "the watermark never moves back"
    assert "history not read" not in _doctor_line(lb).detail


def test_restart_reads_the_whole_library_and_clears_the_mark(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = Resuming(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    assert _state(lb, "resuming")["first_run"]["complete"] is True
    status, _out, _err = _run(capsys, "sync", "resuming", "--restart")
    assert status == 0 and source.sinces == [BOUND, None]
    assert len(_ats(lb, "resuming")) == 373, "the history, the two weeks refused"
    assert "first_run" not in _state(lb, "resuming")
    assert "history not read" not in _doctor_line(lb, "resuming").detail


def test_since_at_the_bound_itself_reads_no_history_and_keeps_the_mark(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    _sources(monkeypatch, History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC)))
    _run(capsys, "sync", "--scheduled")
    _run(capsys, "sync", "history", "--since", BOUND)
    assert "first_run" in _state(lb), "nothing before the bound was read"
    _run(capsys, "sync", "history", "--since", "2026-09-24T21:59:59Z")
    assert "first_run" not in _state(lb)


def test_a_source_that_keeps_its_own_state_and_left_none_starts_from_the_mark_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = Resuming(last=datetime(2026, 9, 1, 10, 0, tzinfo=UTC))  # nothing in the window: no state
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    state = _state(lb, "resuming")
    assert "resume" not in state and state["first_run"]["complete"] is True
    clock[0] = datetime(2026, 10, 9, 16, 0, tzinfo=UTC)
    source.last = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    _run(capsys, "sync", "--scheduled")
    assert source.sinces == [BOUND, BOUND], "from the mark, never from the beginning"
    assert len(_ats(lb, "resuming")) == 15


def test_a_dry_run_by_hand_writes_no_mark(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    before = (lb.root / "state" / "history.json").read_bytes()
    _run(capsys, "sync", "history", "--since", "2026-01-01T00:00:00Z", "--dry-run")
    assert (lb.root / "state" / "history.json").read_bytes() == before, "a dry run reads no history"


# -- doctor --------------------------------------------------------------------------------------------------


def test_doctor_names_a_scheduled_source_whose_history_was_never_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    check = _doctor_line(lb)
    assert check.status == "pass", "a choice the schedule made, not a fault: no alert every run"
    assert "first run bounded to 14 days; history not read" in check.detail
    assert f"before {DAY}" in check.detail and "logbook sync history --since" in check.detail
    _status, out, _err = _run(capsys, "doctor")
    assert "first run bounded to 14 days; history not read" in out


def test_doctor_says_nothing_of_a_source_synced_by_hand(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    _sources(monkeypatch, History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC)))
    _run(capsys, "sync", "history")
    assert "history not read" not in _doctor_line(lb).detail


# -- a dry run and the source's limit ------------------------------------------------------------------------


def test_a_dry_run_stops_at_once_on_a_quota_answer_and_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, source)
    _run(capsys, "sync", "--scheduled")
    state = lb.root / "state"
    before = {p.name: p.read_bytes() for p in state.iterdir()}
    seq = lb.meta["seq"]
    source.limit_at = 3
    status, out, err = _run(capsys, "sync", "history", "--since", "2026-01-01T00:00:00Z", "--dry-run")
    assert status == 1
    assert source.waits[-1] is False and source.waited == 0, "told not to wait, and did not"
    lines = [line for line in err.splitlines() if line.strip()]
    assert lines == [f"sync: history: dry run stopped at the source's limit after 3 lines: {QUOTA}"]
    assert "dry run, nothing written" not in out
    assert {p.name: p.read_bytes() for p in state.iterdir()} == before, "no watermark, no mark, no cache"
    assert Logbook.find().meta["seq"] == seq


def test_a_run_that_writes_waits_the_limit_out_as_before(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC), limit_at=3)
    _sources(monkeypatch, source)
    status, _out, _err = _run(capsys, "sync", "history", "--since", "2026-09-01T00:00:00Z")
    assert status == 0 and source.waits == [True] and source.waited == 1
    assert len(_ats(lb)) == 38


def test_a_dry_run_of_every_source_goes_on_past_one_that_hit_its_limit(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    limited = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC), limit_at=0)
    other = Stream(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC))
    _sources(monkeypatch, limited, other)
    status, out, err = _run(capsys, "sync", "--all", "--dry-run")
    assert status == 1
    assert f"sync: history: dry run stopped at the source's limit after 0 lines: {QUOTA}" in err
    assert "stream: 373 lines from the beginning (dry run, nothing written)" in out
    assert not (lb.root / "state").exists() or not any((lb.root / "state").iterdir())


# -- the pieces -------------------------------------------------------------------------------------------


def test_a_bounded_run_that_fails_leaves_the_mark_and_the_next_starts_from_the_same_instant(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = History(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC), fail_at=5)
    _sources(monkeypatch, source)
    status, out, _err = _run(capsys, "sync", "--scheduled")
    assert status == 1 and LINE in out
    assert "since" not in _state(lb) and _state(lb)["first_run"] == {"from": BOUND, "day": DAY}
    source.fail_at = None
    clock[0] = datetime(2026, 10, 9, 16, 0, tzinfo=UTC)  # a day on: a fresh window would start a day later
    source.last = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    status, out, _err = _run(capsys, "sync", "--scheduled")
    assert status == 0 and source.sinces == [BOUND, BOUND] and "first scheduled run" not in out
    ats = _ats(lb)
    assert len(ats) == len(set(ats)) == 15, "the five the failed run wrote are refused, not written twice"
    assert _state(lb)["first_run"]["complete"] is True


class Walking(History):
    """A source that walks a library (`walk`, as `immich`): a checkpoint after every item, the count it
    resumes from; `resumed` notes the checkpoint each pull started from."""

    NAME = "walking"
    ENV = ("LOGBOOK_WALKING_KEY",)

    def __init__(self, last: datetime, fail_at: int | None = None) -> None:
        super().__init__(last, fail_at=fail_at)
        self.resumed: list[Any] = []

    def pull(  # type: ignore[override]
        self,
        config: Any,
        since: str | None = None,
        progress: Any = None,
        counts: Any = None,
        walk: Any = None,
    ) -> Iterator[dict[str, Any]]:
        saved = walk.start() if walk is not None else None
        self.resumed.append(saved)
        self.sinces.append(since)
        skip = int(saved["fetched"]) if saved else 0
        for i, draft in enumerate(self.items(since)):
            if i < skip:
                continue
            if self.fail_at is not None and i == self.fail_at:
                raise OSError("the server went away")
            yield draft
            if walk is not None:
                walk.reached(i - skip + 1, {"fetched": i + 1})


def test_a_bounded_walk_that_fails_resumes_its_checkpoint_on_the_next_scheduled_run(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    source = Walking(last=datetime(2026, 10, 8, 10, 0, tzinfo=UTC), fail_at=5)
    _sources(monkeypatch, source)
    status, _out, _err = _run(capsys, "sync", "--scheduled")
    state = _state(lb, "walking")
    assert status == 1 and state["walk"]["since"] == BOUND and state["walk"]["checkpoint"] == {"fetched": 5}
    source.fail_at = None
    clock[0] = datetime(2026, 10, 9, 16, 0, tzinfo=UTC)
    source.last = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    status, _out, _err = _run(capsys, "sync", "--scheduled")
    assert status == 0 and source.sinces == [BOUND, BOUND] and source.resumed == [None, {"fetched": 5}]
    ats = _ats(lb, "walking")
    assert len(ats) == len(set(ats)) == 15, "carried on where it stopped: nothing lost, nothing twice"
    state = _state(lb, "walking")
    assert "walk" not in state and state["first_run"]["complete"] is True
    assert state["since"] == "2026-10-09T10:00:00Z"


@pytest.mark.parametrize(
    "name", ["gmail", "gcal", "drive", "gtasks", "meet", "gaudit", "notion", "github", "granola"]
)
def test_every_source_that_waits_out_a_limit_is_told_not_to_on_a_dry_run(name: str) -> None:
    adapter = adapters.live(name)
    assert adapter is not None and _takes(adapter, "wait_on_limits", live=True)


def test_the_sources_with_no_history_to_read_say_so() -> None:
    names = {a.NAME for a in adapters.live_adapters() if not getattr(a, "HISTORY", True)}
    assert names == {"ais", "adsb", "telegram"}


def test_the_window_is_fourteen_local_days_on_the_records_clock() -> None:
    oslo = {"timezone": "Europe/Oslo"}
    assert first_run.window(oslo, NOW) == first_run.Window(DAY, BOUND)
    winter = datetime(2026, 12, 10, 4, 0, tzinfo=UTC)  # 05:00 in Oslo: before a 06:00 day start
    assert first_run.window({**oslo, "day_start": "06:00"}, winter) == first_run.Window(
        "2026-11-26", "2026-11-26T05:00:00Z"
    ), "the day is still the 9th; the window begins at 06:00 local, an hour ahead of UTC in winter"
    assert first_run.window({**oslo, "day_start": "6 am"}, winter) == first_run.Window(
        "2026-11-27", "2026-11-26T23:00:00Z"
    ), "a day start no reader accepts is read as midnight: a sync never refuses for it"
