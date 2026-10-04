"""`logbook doctor`: one line per check, pass, warn or fail, on a synthetic record; exit 1 on a fail.
Nothing here is real: the record is built in the test, the owner is the Oslo persona, who does not
exist, and every value an environment variable holds is a sentinel the output must never show."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from logbook import adapters, cli, doctor
from logbook.store import Logbook

GIB = 1024**3
HOME = {"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}}
OWNER = {"names": ["Ines Nordmann"], "emails": ["ines.nordmann@example.org"], "phones": []}
ASSETS = {"assets": [{"id": "nordlys", "kind": "yacht", "name": "Nordlys", "mmsi": "970000001"}]}


def _usage(free: int) -> doctor.Usage:
    def usage(_path: Path) -> tuple[int, int, int]:
        return (300 * GIB, 300 * GIB - free, free)

    return usage


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _make(root: Path) -> Logbook:
    """A healthy record: two lines, one from `dawarich`, every settings file filled, the index current."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(
        "2026-06-08T06:00:00Z",
        "dawarich",
        "location",
        1,
        {"schema": "location/v1", "lat": 59.9139, "lon": 10.7522, "raw_id": "dawarich:1"},
    )
    lb.append("2026-06-08T07:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "a synthetic note"})
    _write(root / "policy" / "owner.json", OWNER)
    _write(root / "places.json", HOME)
    _write(root / "assets.json", ASSETS)
    lb.index_rebuild()
    return lb


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "Records" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    for adapter in adapters.live_adapters():  # the shell's own keys never reach a test
        for name in adapter.ENV:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    return _make(root)


def _run(lb: Logbook | None, env: dict[str, str] | None = None) -> dict[str, doctor.Check]:
    checks = doctor.run(lb, env or {}, installed=lambda _module: True, usage=_usage(200 * GIB))
    return {c.name: c for c in checks}


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    try:
        cli.main(["doctor", *args])
    except SystemExit as e:
        return int(e.code or 0), capsys.readouterr().out
    return 0, capsys.readouterr().out


# -- the record -----------------------------------------------------------------------------------------


def test_a_healthy_record_passes_every_check(lb: Logbook) -> None:
    checks = _run(lb, {"LOGBOOK_DAWARICH_URL": "https://dawarich.example.org", "LOGBOOK_DAWARICH_KEY": "k"})
    assert {c.status for c in checks.values()} == {"pass"}, [c for c in checks.values() if c.status != "pass"]
    assert checks["record"].detail.startswith("2 lines, head ")
    assert "verified" in checks["record"].detail


def test_no_record_is_one_failure_and_the_extras(tmp_path: Path) -> None:
    checks = _run(None)
    assert checks["record"].status == "fail"
    assert "logbook init" in checks["record"].detail
    assert "index" not in checks and "disk" not in checks
    assert {n for n in checks if n.startswith("extra:")} == {
        "extra:ais",
        "extra:crypto",
        "extra:sealed",
        "extra:transcribe",
    }


def test_a_changed_line_fails_the_record_check(lb: Logbook) -> None:
    month = lb.files()[0]
    month.write_bytes(month.read_bytes().replace(b"a synthetic note", b"another note"))  # tampering
    check = _run(lb)["record"]
    assert check.status == "fail"
    assert "logbook verify" in check.detail


def test_a_stale_head_fails_the_record_check(lb: Logbook) -> None:
    meta = lb.meta
    meta["seq"] = 1  # logbook.json behind the files: the write order after a crash (SPEC §3)
    lb.meta_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    check = _run(lb)["record"]
    assert check.status == "fail"
    assert "logbook.json" in check.detail


def test_a_record_of_another_format_fails_naming_migrate(lb: Logbook) -> None:
    meta = lb.meta
    meta["format"] = "logbook/0.1"
    lb.meta_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    check = _run(lb)["record"]
    assert check.status == "fail"
    assert "logbook migrate" in check.detail


# -- the index ------------------------------------------------------------------------------------------


def test_the_index_is_current_missing_or_stale(lb: Logbook) -> None:
    assert _run(lb)["index"].status == "pass"
    lb.append("2026-06-08T08:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "later"})
    (lb.index_path).unlink()
    missing = _run(lb)["index"]
    assert missing.status == "warn"
    assert "logbook index" in missing.detail
    lb.index_rebuild()
    meta = lb.meta
    lb.append("2026-06-08T09:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "latest"})
    lb.index_rebuild()
    (lb.index_path).unlink()
    with Logbook(lb.root).index() as idx:  # built at the head before the last line
        idx.rebuild()
        idx._set_meta(meta)
    stale = _run(lb)["index"]
    assert stale.status == "warn"
    assert "behind" in stale.detail


def test_an_unreadable_index_is_a_warning_not_a_traceback(lb: Logbook) -> None:
    (lb.index_path).write_bytes(b"not a database")
    check = _run(lb)["index"]
    assert check.status == "warn"
    assert "logbook index" in check.detail


# -- the settings files ---------------------------------------------------------------------------------


def test_owner_json_present_empty_missing_and_broken(lb: Logbook) -> None:
    path = lb.root / "policy" / "owner.json"
    assert _run(lb)["owner"].status == "pass"
    _write(path, {"names": [], "emails": [], "phones": []})
    empty = _run(lb)["owner"]
    assert empty.status == "warn"
    assert "names, emails and phones" in empty.detail
    path.unlink()
    assert _run(lb)["owner"].status == "warn"
    assert not path.exists(), "doctor writes nothing"
    path.write_text("{", encoding="utf-8")
    broken = _run(lb)["owner"]
    assert broken.status == "fail"
    assert "owner.json" in broken.detail


def test_places_json_needs_one_home(lb: Logbook) -> None:
    path = lb.root / "places.json"
    assert _run(lb)["places"].status == "pass"
    assert "Home" in _run(lb)["places"].detail
    _write(path, {"Office": {"lat": 59.91, "lon": 10.75, "radius_m": 100, "kind": "other"}})
    no_home = _run(lb)["places"]
    assert no_home.status == "warn"
    assert "--kind home" in no_home.detail
    path.unlink()
    assert _run(lb)["places"].status == "warn"
    path.write_text("[]", encoding="utf-8")
    assert _run(lb)["places"].status == "fail"


def test_assets_json_valid_absent_and_broken(lb: Logbook) -> None:
    path = lb.root / "assets.json"
    assert _run(lb)["assets"].status == "pass"
    assert "1 asset" in _run(lb)["assets"].detail
    path.unlink()
    assert _run(lb)["assets"].status == "pass"
    _write(path, {"assets": [{"id": "Nordlys", "kind": "yacht", "name": "Nordlys"}]})
    broken = _run(lb)["assets"]
    assert broken.status == "fail"
    assert "id must be" in broken.detail


# -- the extras -----------------------------------------------------------------------------------------


def test_a_missing_extra_names_its_install_line(lb: Logbook) -> None:
    checks = {
        c.name: c
        for c in doctor.run(lb, {}, installed=lambda m: m == "cryptography", usage=_usage(200 * GIB))
    }
    assert checks["extra:crypto"].status == "pass"
    assert checks["extra:ais"].status == "warn"
    assert 'pip install "openlogbook[ais]"' in checks["extra:ais"].detail
    assert checks["extra:transcribe"].status == "warn"
    assert 'pip install "openlogbook[transcribe]"' in checks["extra:transcribe"].detail


def test_transcribe_is_satisfied_by_either_engine() -> None:
    for engine in ("mlx_whisper", "faster_whisper"):
        checks = {c.name: c for c in doctor.run(None, {}, installed=lambda m, e=engine: m == e)}
        assert checks["extra:transcribe"].status == "pass", engine
        assert engine.replace("_", "-") in checks["extra:transcribe"].detail


def test_installed_never_raises_on_an_odd_name() -> None:
    assert doctor.module_installed("json") is True
    assert doctor.module_installed("no_such_module_anywhere") is False
    assert doctor.module_installed("no_such_parent.child") is False


# -- the environment ------------------------------------------------------------------------------------


def test_a_sync_the_record_uses_needs_its_variables_by_name_only(lb: Logbook) -> None:
    sentinel = "https://sentinel.example.org"
    check = _run(lb, {"LOGBOOK_DAWARICH_URL": sentinel})["sync:dawarich"]
    assert check.status == "warn"
    assert "LOGBOOK_DAWARICH_KEY" in check.detail
    assert "LOGBOOK_DAWARICH_URL" not in check.detail, "the one that is set is not asked for"
    assert sentinel not in check.detail
    assert "sync:immich" not in _run(lb), "a source the record has no line of and never synced"


def test_a_sync_with_a_state_file_counts_as_used(lb: Logbook) -> None:
    _write(lb.root / "state" / "granola.json", {"since": "2026-06-08T00:00:00Z"})
    check = _run(lb)["sync:granola"]
    assert check.status == "warn"
    assert "LOGBOOK_GRANOLA_KEY" in check.detail


def test_a_missing_import_policy_is_not_written(lb: Logbook) -> None:
    path = lb.root / "policy" / "import.json"
    path.unlink()
    assert _run(lb)["sync:dawarich"].status == "warn"
    assert not path.exists(), "doctor writes nothing"


def test_a_disabled_sync_needs_nothing(lb: Logbook) -> None:
    _write(
        lb.root / "policy" / "import.json", {"disabled": [{"source": "dawarich", "reason": "sold the phone"}]}
    )
    assert "sync:dawarich" not in _run(lb)


def test_a_variable_that_is_set_but_refused_names_the_sync_not_the_value(lb: Logbook) -> None:
    _write(lb.root / "state" / "gcal.json", {"since": "2026-06-08T00:00:00Z"})
    check = _run(lb, {"LOGBOOK_GCAL_URLS": "ftp://secret.example.org/calendar"})["sync:gcal"]
    assert check.status == "warn"
    assert "secret" not in check.detail
    assert "logbook sync gcal" in check.detail


def test_sources_are_read_from_the_index_only_when_it_is_current(lb: Logbook) -> None:
    (lb.index_path).unlink()
    assert "sync:dawarich" not in _run(lb), "no index: only the state files say which syncs ran"


# -- disk and folder ------------------------------------------------------------------------------------


def test_disk_space_thresholds(lb: Logbook) -> None:
    def check(free: int) -> doctor.Check:
        return {c.name: c for c in doctor.run(lb, {}, installed=lambda _m: True, usage=_usage(free))}["disk"]

    assert check(200 * GIB).status == "pass"
    assert check(2 * GIB).status == "warn"
    assert check(100 * 1024**2).status == "fail"
    assert "GiB free" in check(200 * GIB).detail


def test_disk_usage_that_cannot_be_read_is_a_warning(lb: Logbook) -> None:
    def refuse(_path: Path) -> tuple[int, int, int]:
        raise OSError("no such device")

    check = {c.name: c for c in doctor.run(lb, {}, installed=lambda _m: True, usage=refuse)}["disk"]
    assert check.status == "warn"


@pytest.mark.parametrize(
    ("parts", "service"),
    [
        (("Dropbox", "Logbook"), "Dropbox"),
        (("Dropbox (Personal)", "Logbook"), "Dropbox"),
        (("OneDrive", "Logbook"), "OneDrive"),
        (("OneDrive - Example Org", "Logbook"), "OneDrive"),
        (("Library", "Mobile Documents", "com~apple~CloudDocs", "Logbook"), "iCloud Drive"),
        (("iCloud Drive", "Logbook"), "iCloud Drive"),
        (("Google Drive", "My Drive", "Logbook"), "Google Drive"),
    ],
)
def test_a_record_under_a_cloud_sync_folder_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parts: tuple[str, ...], service: str
) -> None:
    root = tmp_path.joinpath(*parts)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.delenv("OneDrive", raising=False)
    lb = _make(root)
    check = _run(lb)["folder"]
    assert check.status == "fail"
    assert service in check.detail
    assert "LOGBOOK_HOME" in check.detail


def test_a_folder_that_only_resembles_a_cloud_name_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Dropboxes" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.delenv("OneDrive", raising=False)
    assert _run(_make(root))["folder"].status == "pass"


def test_the_onedrive_variable_names_the_folder_on_windows(lb: Logbook) -> None:
    assert _run(lb)["folder"].status == "pass"
    check = _run(lb, {"OneDrive": str(lb.root.parent)})["folder"]
    assert check.status == "fail"
    assert "OneDrive" in check.detail


def test_a_symlink_into_a_cloud_folder_is_seen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "Dropbox" / "Logbook"
    _make(real)
    link = tmp_path / "Records"
    try:
        link.symlink_to(real.parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    monkeypatch.setenv("LOGBOOK_HOME", str(link / "Logbook"))
    assert _run(Logbook(link / "Logbook"))["folder"].status == "fail"


# -- the command ----------------------------------------------------------------------------------------


def test_the_command_prints_one_line_per_check_and_exits_0_when_nothing_fails(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "disk_usage", _usage(200 * GIB))
    status, out = _cli(capsys)
    assert status == 0, out
    lines = out.splitlines()
    assert lines[0].startswith("pass  record")
    assert all(line.split()[0] in {"pass", "warn", "fail"} for line in lines[:-1])
    assert "0 fail" in lines[-1]
    assert "fail" not in {line.split()[0] for line in lines[:-1]}


def test_the_command_exits_1_on_a_failure(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    (lb.root / "assets.json").write_text("{", encoding="utf-8")
    status, out = _cli(capsys)
    assert status == 1
    assert "fail  assets" in out


def test_the_command_without_a_record_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "nowhere"))
    status, out = _cli(capsys)
    assert status == 1
    assert out.startswith("fail  record")


def test_the_report_never_prints_an_environment_value(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_DAWARICH_KEY", "sentinel-key-value")
    _status, out = _cli(capsys)
    assert "sentinel-key-value" not in out
    assert "LOGBOOK_DAWARICH_URL" in out
