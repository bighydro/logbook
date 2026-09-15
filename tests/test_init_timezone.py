"""`logbook init` detects the local timezone (issue #25: it picked UTC on macOS, where
datetime.now().astimezone() yields a fixed offset with no IANA key). Detection order:
/etc/localtime -> astimezone().tzinfo.key -> $TZ -> UTC, each candidate validated."""

from __future__ import annotations

import sys
from datetime import timedelta, timezone
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli

FALLBACK_HINT = "(could not detect; pass --timezone Europe/Zurich to change)"


class _Now:
    """Stand-in for datetime.now() exposing only what _tz_default uses."""

    def __init__(self, tz: object) -> None:
        self.tzinfo = tz

    def astimezone(self) -> _Now:
        return self


def _patch_clock(monkeypatch: pytest.MonkeyPatch, tz: object) -> None:
    monkeypatch.setattr(cli, "datetime", SimpleNamespace(now=lambda: _Now(tz)))


def _fake_localtime(tmp_path: Path, zone: str) -> Path:
    """A symlink like macOS's /etc/localtime -> /var/db/timezone/zoneinfo/<zone>."""
    target = tmp_path / "var" / "db" / "timezone" / "zoneinfo" / zone
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"TZif2")
    link = tmp_path / "etc" / "localtime"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return link


@pytest.fixture
def nothing_detectable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every detection path disabled; tests re-enable one at a time."""
    monkeypatch.setattr(cli, "_LOCALTIME", str(tmp_path / "etc" / "localtime"))  # does not exist
    _patch_clock(monkeypatch, timezone(timedelta(hours=1)))  # fixed offset, no .key (macOS)
    monkeypatch.delenv("TZ", raising=False)


def test_tz_from_etc_localtime_symlink(nothing_detectable, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_LOCALTIME", str(_fake_localtime(tmp_path, "Europe/Zurich")))
    assert cli._tz_default() == "Europe/Zurich"


def test_tz_from_localtime_with_backslash_path(nothing_detectable, monkeypatch):
    """Windows CI: realpath yields backslashes and PurePath is the Windows flavour."""
    monkeypatch.setattr(cli.os.path, "realpath", lambda _p: r"C:\tz\zoneinfo\Europe\Zurich")
    monkeypatch.setattr(cli, "PurePath", PureWindowsPath, raising=False)
    assert cli._tz_default() == "Europe/Zurich"


def test_tz_uses_last_zoneinfo_part(nothing_detectable, monkeypatch, tmp_path):
    link = _fake_localtime(tmp_path / "zoneinfo", "Europe/Zurich")
    monkeypatch.setattr(cli, "_LOCALTIME", str(link))
    assert cli._tz_default() == "Europe/Zurich"


def test_tz_ignores_localtime_that_names_no_real_zone(nothing_detectable, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_LOCALTIME", str(_fake_localtime(tmp_path, "Not/AZone")))
    monkeypatch.setenv("TZ", "Europe/Oslo")
    assert cli._tz_default() == "Europe/Oslo"


def test_tz_from_astimezone_key(nothing_detectable, monkeypatch):
    _patch_clock(monkeypatch, ZoneInfo("Europe/Zurich"))
    monkeypatch.setenv("TZ", "Europe/Oslo")  # lower priority than the clock
    assert cli._tz_default() == "Europe/Zurich"


def test_tz_from_env(nothing_detectable, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Zurich")
    assert cli._tz_default() == "Europe/Zurich"


def test_tz_ignores_env_that_names_no_real_zone(nothing_detectable, monkeypatch):
    monkeypatch.setenv("TZ", "CET-1CEST,M3.5.0,M10.5.0/3")  # POSIX rule string, not an IANA zone
    assert cli._tz_default() == "UTC"


def test_tz_falls_back_to_utc(nothing_detectable):
    assert cli._tz_default() == "UTC"


def test_init_prints_detected_timezone(nothing_detectable, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "_LOCALTIME", str(_fake_localtime(tmp_path, "Europe/Zurich")))
    cli.main(["init", str(tmp_path / "lb")])
    out = capsys.readouterr().out
    assert "timezone: Europe/Zurich" in out
    assert FALLBACK_HINT not in out


def test_init_says_when_it_could_not_detect(nothing_detectable, tmp_path, capsys):
    cli.main(["init", str(tmp_path / "lb")])
    out = capsys.readouterr().out
    assert f"timezone: UTC {FALLBACK_HINT}" in out


def test_init_explicit_timezone_needs_no_detection(nothing_detectable, tmp_path, capsys):
    cli.main(["init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo"])
    out = capsys.readouterr().out
    assert "timezone: Europe/Oslo" in out
    assert FALLBACK_HINT not in out
