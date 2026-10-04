"""`logbook sync --all`: every configured live source in sequence — configured: at least one of its
`ENV` variables set and its `configure` accepting the environment — one after the other, a failure
in one never stopping the next, each source's own summary as it runs and one summary line per source
at the end; exit 1 when any failed. A disabled source (`policy/import.json`) is skipped either way.
Fake live adapters, nothing real; synthetic notes only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import adapters
from logbook.core.store import Logbook


class Fake:
    """A live adapter as `adapters.LiveAdapter` describes one, with a scripted pull."""

    def __init__(self, name: str, env: tuple[str, ...], drafts: int = 0, fail: Exception | None = None):
        self.NAME = name
        self.ENV = env
        self.drafts = drafts
        self.fail = fail
        self.pulls = 0

    def configure(self, env: Any) -> object | None:
        missing = [v for v in self.ENV if not env.get(v, "").strip()]
        return None if missing else {"key": env[self.ENV[0]]}

    def pull(
        self, config: Any, since: str | None = None, progress: Any = None, counts: Any = None
    ) -> Iterator[dict[str, Any]]:
        self.pulls += 1
        if self.fail is not None:
            raise self.fail
        for i in range(self.drafts):
            at = f"2026-03-01T10:0{i}:00Z"
            yield {
                "at": at,
                "source": self.NAME,
                "kind": "note",
                "tier": 3,
                "payload": {"schema": "note/v1", "raw_id": f"{self.NAME}:{i}", "text": f"note {i}"},
            }

    def watermark(self, draft: dict[str, Any]) -> str | None:
        return str(draft["at"])


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name in ("LOGBOOK_ALPHA_KEY", "LOGBOOK_BETA_KEY", "LOGBOOK_GAMMA_KEY", "LOGBOOK_DELTA_KEY"):
        monkeypatch.delenv(name, raising=False)
    return lb


def _fakes(monkeypatch: pytest.MonkeyPatch, *fakes: Fake) -> None:
    monkeypatch.setattr(adapters, "live_adapters", lambda: list(fakes))


def _disable(lb: Logbook, name: str, reason: str) -> None:
    path = lb.root / "policy" / "import.json"
    path.write_text(json.dumps({"disabled": [{"source": name, "reason": reason}]}), encoding="utf-8")


def _all(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["sync", "--all", *args])
    except SystemExit as e:
        status = int(e.code or 0)
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


def test_all_runs_each_configured_source_continues_past_a_failure_and_sums_up(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=2)
    beta = Fake("beta", ("LOGBOOK_BETA_KEY",), drafts=1)  # not configured: its variable is not set
    gamma = Fake("gamma", ("LOGBOOK_GAMMA_KEY",), fail=OSError("the service is down"))
    delta = Fake("delta", ("LOGBOOK_DELTA_KEY",), drafts=1)  # disabled by the owner
    epsilon = Fake("epsilon", ("LOGBOOK_ALPHA_KEY", "LOGBOOK_EPSILON_URL"), drafts=1)  # one of two set
    _fakes(monkeypatch, alpha, beta, gamma, delta, epsilon)
    for name in ("LOGBOOK_ALPHA_KEY", "LOGBOOK_DELTA_KEY", "LOGBOOK_GAMMA_KEY"):
        monkeypatch.setenv(name, "k")
    monkeypatch.delenv("LOGBOOK_EPSILON_URL", raising=False)
    _disable(lb, "delta", "someone else's account")

    status, out, err = _all(capsys)
    assert status == 1, "one source failed"
    assert (alpha.pulls, beta.pulls, gamma.pulls, delta.pulls, epsilon.pulls) == (1, 0, 1, 0, 0)
    assert "alpha: 2 new lines of 2 seen from the beginning; watermark 2026-03-01T10:01:00Z" in out
    assert "sync: gamma: the service is down" in err
    assert "delta: disabled (someone else's account); skipped" in out
    assert [line["payload"]["raw_id"] for line in lb.lines()] == ["alpha:0", "alpha:1"]
    assert (lb.root / "state" / "alpha.json").exists() and not (lb.root / "state" / "gamma.json").exists()
    summary = out[out.index("sync --all:") :].splitlines()
    assert summary[0] == "sync --all: 5 sources: 1 ok, 1 failed, 3 skipped"
    assert [line.split() for line in summary[1:]] == [
        ["alpha", "ok"],
        ["beta", "skipped", "(LOGBOOK_BETA_KEY", "not", "set)"],
        ["gamma", "failed", "(status", "1)"],
        ["delta", "skipped", "(disabled)"],
        ["epsilon", "skipped", "(set", "LOGBOOK_EPSILON_URL)"],
    ]


def test_all_continues_past_an_unexpected_error_and_says_which_source(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), fail=RuntimeError("a bug in the adapter"))
    beta = Fake("beta", ("LOGBOOK_BETA_KEY",), drafts=1)
    _fakes(monkeypatch, alpha, beta)
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    monkeypatch.setenv("LOGBOOK_BETA_KEY", "k")
    status, out, err = _all(capsys)
    assert status == 1 and beta.pulls == 1
    assert "sync: alpha: RuntimeError: a bug in the adapter" in err
    assert "beta: 1 new lines of 1 seen" in out
    assert "alpha  failed (status 1)" in out.replace("  ", " ").replace("alpha failed", "alpha  failed")
    assert "beta   ok" in out or "beta  ok" in out


def test_all_with_nothing_configured_skips_every_source_and_exits_0(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=1)
    _fakes(monkeypatch, alpha)
    status, out, _err = _all(capsys)
    assert status == 0 and alpha.pulls == 0
    assert "sync --all: 1 source: 0 ok, 0 failed, 1 skipped" in out
    assert "alpha  skipped (LOGBOOK_ALPHA_KEY not set)" in out


def test_all_dry_run_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=2)
    _fakes(monkeypatch, alpha)
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    status, out, _err = _all(capsys, "--dry-run")
    assert status == 0 and "alpha: 2 lines from the beginning (dry run, nothing written)" in out
    assert list(lb.lines()) == [] and not (lb.root / "state").exists()


def test_all_takes_no_source_name_since_listen_or_until(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fakes(monkeypatch, Fake("alpha", ("LOGBOOK_ALPHA_KEY",)))
    for args in (["sync", "alpha", "--all"], ["sync", "--all", "--since", "2026-03-01T00:00:00Z"]):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2
        assert "--all" in capsys.readouterr().err
    for args in (["sync", "--all", "--listen", "10"], ["sync", "--all", "--until", "07:00"]):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2 and "--all" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["sync"])
    assert e.value.code == 2
    assert "a source or --all" in capsys.readouterr().err


def test_all_over_the_real_adapters_with_no_variable_set_skips_them_all(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No LOGBOOK_* variable set: every built-in live source is skipped and nothing is asked of any
    service; the exit status is 0 and the summary names each."""
    live = adapters.live_adapters()
    for adapter in live:
        for name in adapter.ENV:
            monkeypatch.delenv(name, raising=False)
    status, out, _err = _all(capsys)
    assert status == 0
    for adapter in live:
        assert f"{adapter.NAME}" in out and "skipped" in out
    assert f"{len(live)} sources: 0 ok, 0 failed, {len(live)} skipped" in out


class Listener(Fake):
    """A source that listens to a stream (ais): `pull` takes the window and reports Ctrl-C through
    `status`, and a single run then exits 130."""

    def pull(  # type: ignore[override]
        self,
        config: Any,
        since: str | None = None,
        progress: Any = None,
        counts: Any = None,
        listen_s: float = 0.0,
        status: dict[str, Any] | None = None,
        notice: Any = None,
    ) -> Iterator[dict[str, Any]]:
        self.pulls += 1
        if status is not None:
            status["interrupted"] = True
        yield from ()


def test_all_stops_at_a_ctrl_c_and_exits_130(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner interrupting a source that listens wants out, not the next source: what the run
    did so far is summed up, the sources not reached are named, and the status is 130."""
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=1)
    ais = Listener("ais", ("LOGBOOK_AIS_KEY",))
    beta = Fake("beta", ("LOGBOOK_BETA_KEY",), drafts=1)
    _fakes(monkeypatch, alpha, ais, beta)
    for name in ("LOGBOOK_ALPHA_KEY", "LOGBOOK_AIS_KEY", "LOGBOOK_BETA_KEY"):
        monkeypatch.setenv(name, "k")
    status, out, _err = _all(capsys)
    assert status == 130 and (alpha.pulls, ais.pulls, beta.pulls) == (1, 1, 0)
    summary = out[out.index("sync --all:") :].splitlines()
    assert summary[0] == "sync --all: 3 sources: 1 ok, 0 failed, 0 skipped, interrupted"
    assert [line.split() for line in summary[1:]] == [
        ["alpha", "ok"],
        ["ais", "interrupted"],
        ["beta", "not", "run"],
    ]
