"""`logbook doctor`: one line per check, pass, warn or fail, on a synthetic record; exit 1 on a fail.
Nothing here is real: the record is built in the test, the owner is the Oslo persona, who does not
exist, and every value an environment variable holds is a sentinel the output must never show."""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import shlex
import shutil
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from logbook import cli
from logbook.contrib import adapters, backup, doctor, home, last_run, schedule, service
from logbook.core import policy
from logbook.core.store import Logbook

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
    _restore_test(lb, "passed", datetime.now(UTC) - timedelta(days=3))
    return lb


def _restore_test(lb: Logbook, status: str, at: datetime, reason: str | None = None) -> None:
    snapshot = lb.root.parent / "Backups" / "owner" / "2026-10-03T030000Z"
    backup.write_restore_test(lb.root, backup.RestoreTest(at, status, snapshot, 2, "a" * 64, reason))


def _ran(lb: Logbook, at: datetime, *, failed: bool = False, doctor_ran: bool = True) -> None:
    """A scheduled run at `at`: `alpha` appended two lines, `gamma` failed when `failed`."""
    sources = (last_run.Source("alpha", "ok", 2),)
    if failed:
        sources += (last_run.Source("gamma", "failed (status 1)", 0),)
    report = last_run.Doctor(12, (), ()) if doctor_ran else None
    first = "gamma  failed (status 1)" if failed else None
    last_run.write(lb.root, last_run.State(last_run.Run(at, sources, report, first), (), None))


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
    """The stranger test: before any record, the first words say what to do next, in a sentence."""
    checks = _run(None)
    assert checks["record"].status == "fail", "the exit code stays 1"
    assert checks["record"].detail == (
        "No record yet: run `logbook demo --out ~/Demo/Logbook` to try one,"
        " or `logbook setup` to start yours."
    )
    assert "index" not in checks and "disk" not in checks
    assert {n for n in checks if n.startswith("extra:")} == {
        "extra:ais",
        "extra:crypto",
        "extra:sealed",
        "extra:speakers",
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
    assert "logbook repair index" in missing.detail
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
    assert "logbook repair index" in check.detail


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


#: what doctor knows of the process it runs in, for the tests: a tool environment uv made on 3.12, with
#: openlogbook 0.7.0 from an index, pip importable, and two companions at the versions installed
VERSION = "0.7.0"
PYTHON = "/home/ines/.local/share/uv/tools/openlogbook/bin/python"
VENV_PYTHON = "/home/ines/venv/bin/python"
PIPX_HOME = "/home/ines/.local/share/pipx"
COMMIT = "4f1c0d2e9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d"  # synthetic: the commit a git install installed
HERE = doctor.Here(
    executable=PYTHON,
    base="/usr/bin/python3.12",
    python=(3, 12, 3),
    version=VERSION,
    pip=True,
    venv=True,
    version_of={"ijson": "3.5.1", "uvicorn": "0.38.0", "pytest": "9.1.1", "ruff": "0.14.0"}.get,
)
GIT = json.dumps(
    {
        "url": "https://example.org/ines/logbook.git",
        "vcs_info": {"vcs": "git", "commit_id": COMMIT, "requested_revision": "v0.7.0"},
    }
)
PIP = doctor.Install("pip", requirement=f"=={VERSION}", python=VENV_PYTHON)


def _here(**changes: object) -> doctor.Here:
    return dataclasses.replace(HERE, **changes)  # type: ignore[arg-type]


def test_a_missing_extra_names_its_install_line(lb: Logbook) -> None:
    """Since the third review: this interpreter's pip, at the version installed now, so the line can
    neither land on another Python nor move Logbook to a newer version."""
    checks = {
        c.name: c
        for c in doctor.run(
            lb, {}, installed=lambda m: m == "cryptography", usage=_usage(200 * GIB), install=PIP
        )
    }
    assert checks["extra:crypto"].status == "pass"
    assert checks["extra:ais"].status == "warn"
    assert checks["extra:ais"].detail == (
        f'websockets not installed: {VENV_PYTHON} -m pip install "openlogbook[ais]==0.7.0"'
    ), "pip adds and removes nothing else, so the line names the extra alone (third review, 7)"
    assert checks["extra:transcribe"].status == "warn"
    assert checks["extra:transcribe"].detail.endswith(
        f'{VENV_PYTHON} -m pip install "openlogbook[transcribe]==0.7.0"'
    )
    assert checks["extra:speakers"].status == "warn"
    assert checks["extra:speakers"].detail == (
        f'pyannote.audio not installed: {VENV_PYTHON} -m pip install "openlogbook[speakers]==0.7.0"'
    )


def test_under_pipx_the_hint_is_pipx_and_keeps_every_extra_already_there(lb: Logbook) -> None:
    """#334: on the pipx install the README gives, `pip install "openlogbook[ais]"` put a second Logbook in
    the system Python, and the extras pipx had added (sealed, speakers, transcribe) were gone from the
    command. The line names how this one was installed, and every extra it has: following it removes none.
    `judge` is in pipx's own spec but installs nothing on Linux, so only the spec says it is there. Since
    the third review it runs pip in pipx's venv, never `pipx install --force`, which made the venv again
    on pipx's own Python."""
    pipx = doctor.Install(
        "pipx", frozenset({"sealed", "judge"}), f"=={VERSION}", home=PIPX_HOME, venv="openlogbook"
    )
    checks = {
        c.name: c
        for c in doctor.run(
            lb,
            {},
            installed=lambda m: m in ("cryptography", "pyrage", "ijson"),
            usage=_usage(200 * GIB),
            install=pipx,
        )
    }
    assert checks["extra:ais"].detail == (
        f"websockets not installed: PIPX_HOME={PIPX_HOME} pipx inject openlogbook"
        ' "openlogbook[ais,judge,sealed]==0.7.0"'
    ), "what pipx's receipt names, which pipx writes back, and the extra; a module found is not named"


INSTALLS: dict[str, doctor.Install] = {
    "pipx": doctor.Install("pipx", requirement=f"=={VERSION}", home=PIPX_HOME, venv="openlogbook"),
    "uv-tool": doctor.Install("uv-tool", requirement=f"=={VERSION}"),
    "checkout": doctor.Install("checkout", folder="openlogbook", python=VENV_PYTHON),
    "pip": PIP,
    "homebrew": doctor.Install("homebrew", why=doctor.HOMEBREW),
}


@pytest.mark.parametrize(
    ("how", "line"),
    [
        ("pipx", f'PIPX_HOME={PIPX_HOME} pipx inject openlogbook "openlogbook[ais,crypto]==0.7.0"'),
        ("uv-tool", 'uv tool install --force "openlogbook[ais,crypto]==0.7.0"'),
        ("checkout", "uv sync --extra ais --extra crypto"),
        ("pip", f'{VENV_PYTHON} -m pip install "openlogbook[ais,crypto]==0.7.0"'),
        ("homebrew", None),
    ],
)
def test_the_install_line_for_each_way_of_installing(how: str, line: str | None) -> None:
    assert doctor.install_line(INSTALLS[how], {"crypto", "ais"}) == line


def test_how_this_logbook_was_installed_is_read_from_its_prefix(tmp_path: Path) -> None:
    """From the files the installer left in `sys.prefix`, the package's `direct_url.json` and version;
    never a command run."""
    pipx = tmp_path / "pipx" / "venvs" / "openlogbook"
    pipx.mkdir(parents=True)
    (pipx / "pipx_metadata.json").write_text(
        json.dumps(
            {"main_package": {"package": "openlogbook", "package_or_url": "openlogbook[sealed,crypto]"}}
        ),
        encoding="utf-8",
    )
    assert doctor.install_of(pipx, HERE) == doctor.Install(
        "pipx", frozenset({"sealed", "crypto"}), "==0.7.0", home=str(tmp_path / "pipx"), venv="openlogbook"
    )

    uv = tmp_path / "uv" / "tools" / "openlogbook"
    uv.mkdir(parents=True)
    (uv / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "openlogbook", extras = ["mcp"] }]\n', encoding="utf-8"
    )
    assert doctor.install_of(uv, HERE) == doctor.Install("uv-tool", frozenset({"mcp"}), "==0.7.0")

    checkout = tmp_path / "src" / "logbook"
    (checkout / ".venv").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname = 'openlogbook'\n", encoding="utf-8")
    editable = _here(direct_url=json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}}))
    assert doctor.install_of(checkout / ".venv", editable) == doctor.Install(
        "checkout", folder=str(checkout), python=PYTHON
    )
    elsewhere = doctor.install_of(tmp_path / "venv", editable)
    assert elsewhere.how == "pip" and "folder" in elsewhere.why, "pip install -e: no line, the why said"
    assert doctor.install_line(elsewhere, {"ais"}) is None

    wheel = _here(direct_url=json.dumps({"url": "https://example.org/openlogbook.whl", "archive_info": {}}))
    assert doctor.install_of(tmp_path / "venv", wheel) == doctor.Install(
        "pip", why="it was installed from a folder, a URL or a wheel, which may have changed since"
    )
    assert doctor.install_of(tmp_path / "venv", HERE) == doctor.Install(
        "pip", requirement="==0.7.0", python=PYTHON
    )


def test_an_editable_or_pinned_install_keeps_where_it_came_from(tmp_path: Path) -> None:
    """From review: `pipx install -e ./logbook` or `uv tool install -e .` must not be told a line that
    reinstalls from PyPI and drops the checkout; a pinned version stays pinned, and since the third review
    an unpinned or loosely pinned one is pinned to the version installed now, never moved past it."""
    for checkout in (tmp_path / "RUNNER~1" / "logbook", tmp_path / "ines@example.org" / "logbook"):
        # a Windows short name, and an `@` in a folder: neither is a version operator, neither splits it
        venv = tmp_path / "pipx" / "venvs" / "openlogbook"
        venv.mkdir(parents=True, exist_ok=True)
        (venv / "pipx_metadata.json").write_text(
            json.dumps(
                {"main_package": {"package_or_url": f"{checkout}[crypto]", "pip_args": ["--editable"]}}
            ),
            encoding="utf-8",
        )
        editable = _here(direct_url=json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}}))
        pipx = doctor.install_of(venv, editable)
        assert pipx == doctor.Install(
            "pipx",
            frozenset({"crypto"}),
            folder=str(checkout),
            home=str(tmp_path / "pipx"),
            venv="openlogbook",
        )
        assert doctor.install_line(pipx, {"ais", "crypto"}) == (
            f"PIPX_HOME={doctor._arg(str(tmp_path / 'pipx'))} pipx inject openlogbook"
            f' --editable "{checkout}[ais,crypto]"'
        )

    for spec, installed in (
        ("openlogbook==0.7.0", "0.7.0"),
        ("openlogbook~=0.7", "0.7.0"),
        ("openlogbook", "0.7.1"),
    ):
        (venv / "pipx_metadata.json").write_text(
            json.dumps({"main_package": {"package_or_url": spec}}), encoding="utf-8"
        )
        pinned = doctor.install_of(venv, _here(version=installed))
        assert doctor.install_line(pinned, {"ais"}) == (
            f"PIPX_HOME={doctor._arg(str(tmp_path / 'pipx'))} pipx inject openlogbook"
            f' "openlogbook[ais]=={installed}"'
        ), spec

    checkout = tmp_path / "RUNNER~1" / "logbook"
    (tmp_path / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "openlogbook", editable = {json.dumps(str(checkout))} }}]\n',
        encoding="utf-8",
    )
    editable = _here(direct_url=json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}}))
    uv = doctor.install_of(tmp_path, editable)
    assert uv == doctor.Install("uv-tool", folder=str(checkout))
    assert doctor.install_line(uv, {"ais"}) == f'uv tool install --force --editable "{checkout}[ais]"'
    assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None, (
        "receipt and package differ"
    )

    clone = doctor.Install("checkout", folder=str(checkout), python=VENV_PYTHON)
    assert doctor.install_line(clone, {"ais"}) == "uv sync --extra ais"
    assert _hint(clone).endswith(f"; in the clone, {checkout}: uv sync --extra ais")


def test_a_broken_receipt_is_still_the_installer_with_no_extras_named(tmp_path: Path) -> None:
    """And, since 20 October's review, no line: a receipt that will not read is named, never guessed at."""
    receipt = tmp_path / "pipx_metadata.json"
    receipt.write_text("not json", encoding="utf-8")
    assert doctor.install_of(tmp_path, HERE) == doctor.Install(
        "pipx", why=f"its receipt, {receipt}, is in a shape doctor does not read"
    )
    receipt.unlink()
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text("[tool\n", encoding="utf-8")
    assert doctor.install_of(tmp_path, HERE) == doctor.Install(
        "uv-tool", why=f"its receipt, {receipt}, is in a shape doctor does not read"
    )
    assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None


# The receipts uv and pipx wrote for real installs, trimmed and moved under /home/ines
# (tests/fixtures/doctor/receipts/README.md). From the 20 October reviews of #338: the line doctor prints
# adds the extra to exactly what is installed (Python, venv options, source, version, suffix, companions),
# or doctor prints no line and says why.
RECEIPTS = Path(__file__).parent / "fixtures" / "doctor" / "receipts"


def _receipt(tmp_path: Path, fixture: str, here: doctor.Here = HERE) -> doctor.Install:
    """The install a fixture's receipt describes: uv's in the prefix, pipx's in a venv of a pipx home's
    `venvs` folder, named as pipx names it (`openlogbook`, with the suffix)."""
    if fixture.startswith("uv-"):
        shutil.copyfile(RECEIPTS / fixture, tmp_path / "uv-receipt.toml")
        return doctor.install_of(tmp_path, here)
    venv = tmp_path / "pipx" / "venvs" / ("openlogbook-ola" if "suffix" in fixture else "openlogbook")
    venv.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RECEIPTS / fixture, venv / "pipx_metadata.json")
    return doctor.install_of(venv, here)


def _inject(tmp_path: Path, venv: str = "openlogbook", pip_args: str = "") -> str:
    """How a line for a pipx venv `_receipt` made begins: its home named, since it is not the one a bare
    `pipx` uses (the tests' home is a temporary folder), and the index options pip is given."""
    options = f'--pip-args="{pip_args}" ' if pip_args else ""
    return f"PIPX_HOME={doctor._arg(str(tmp_path / 'pipx'))} pipx inject {options}{venv} "


def _hint(install: doctor.Install, extra: str = "ais") -> str:
    """The `extra:<extra>` line doctor prints under `install` when that extra alone is missing."""
    checks = {c.name: c for c in doctor.extras_checks(lambda m: False, install)}
    assert checks[f"extra:{extra}"].status == "warn"
    return checks[f"extra:{extra}"].detail


def test_a_uv_pin_stays_pinned_on_its_python_and_index(tmp_path: Path) -> None:
    """The review's first finding: `specifier = "==0.7.0"` was dropped, and with it the Python the tool
    was made with (uv's `--force` alone rebuilt it on another) and the index it was installed from. Since
    the third review the line names the interpreter running now, which the receipt's `3.12` must be."""
    uv = _receipt(tmp_path, "uv-pinned.toml")
    assert uv.extras == {"mcp"}
    assert doctor.install_line(uv, {"ais", "mcp"}) == (
        "uv tool install --force --python 3.12 --no-index --find-links file:///home/ines/src/dist"
        ' "openlogbook[ais,mcp]==0.7.0"'
    )


def test_a_uv_install_from_git_stays_on_its_repository_and_revision(tmp_path: Path) -> None:
    """Since the third review: on the commit installed, read from the package's `direct_url.json`, never
    the receipt's tag or branch, which may have moved; and only when the receipt says git too."""
    uv = _receipt(tmp_path, "uv-git.toml", _here(direct_url=GIT))
    assert doctor.install_line(uv, {"ais", "mcp"}) == (
        "uv tool install --force --python 3.12"
        f' "openlogbook[ais,mcp] @ git+https://example.org/ines/logbook.git@{COMMIT}"'
    )
    assert doctor.install_line(_receipt(tmp_path, "uv-git.toml"), {"ais"}) is None, "installed from an index"


def test_a_uv_install_from_a_url_stays_on_that_url(tmp_path: Path) -> None:
    """Since the third review, no line: uv keeps no hash of what the URL gave (`archive_info` is empty),
    so a line could install whatever is there now. Doctor says why and where to read."""
    url = _here(
        direct_url=json.dumps(
            {"url": "https://example.org/ines/openlogbook-0.7.0-py3-none-any.whl", "archive_info": {}}
        )
    )
    uv = _receipt(tmp_path, "uv-url.toml", url)
    assert doctor.install_line(uv, {"ais", "mcp"}) is None
    assert "may have changed since" in _hint(uv) and "install --force" not in _hint(uv)


def test_a_uv_install_from_a_wheel_stays_on_that_wheel(tmp_path: Path) -> None:
    """The same for a wheel's path: the file may have been replaced since, and uv kept no hash of it."""
    wheel = "file:///home/ines/src/dist/openlogbook-0.7.0-py3-none-any.whl"
    uv = _receipt(tmp_path, "uv-path.toml", _here(direct_url=json.dumps({"url": wheel, "archive_info": {}})))
    assert uv.extras == frozenset()
    assert doctor.install_line(uv, {"ais"}) is None
    assert "may have changed since" in _hint(uv)


def test_a_uv_companion_installed_with_with_stays(tmp_path: Path) -> None:
    """At the version installed now: `--with ijson` alone moved it to a newer one (third review)."""
    uv = _receipt(tmp_path, "uv-with.toml")
    assert doctor.install_line(uv, {"ais", "mcp"}) == (
        'uv tool install --force --python 3.12 --with ijson==3.5.1 "openlogbook[ais,mcp]==0.7.0"'
    )
    unknown = _receipt(tmp_path, "uv-with.toml", _here(version_of=lambda name: None))
    assert doctor.install_line(unknown, {"ais"}) is None and "ijson" in unknown.why


def test_a_uv_receipt_in_a_shape_doctor_does_not_know_prints_no_line_and_names_it(tmp_path: Path) -> None:
    """Constraints came from a file no line can name; a source key uv may add later is not guessed at."""
    uv = _receipt(tmp_path, "uv-constraints.toml")
    receipt = str(tmp_path / "uv-receipt.toml")
    assert uv == doctor.Install("uv-tool", why=f"its receipt, {receipt}, is in a shape doctor does not read")
    assert doctor.install_line(uv, {"ais"}) is None
    detail = _hint(uv)
    assert receipt in detail and 'docs/install.md, "Optional extras", says how to add ais' in detail
    assert "install --force" not in detail and "pip install" not in detail
    (tmp_path / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "openlogbook", workspace = true }]\n', encoding="utf-8"
    )
    assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None


def test_a_pipx_install_from_a_bare_git_url_becomes_a_requirement_with_the_extras(tmp_path: Path) -> None:
    """`"git+https://…[ais]"` is not a requirement; `"openlogbook[ais] @ git+https://…@<commit>"` is, on the
    commit installed (third review: the bare URL moved to whatever the branch had become)."""
    pipx = _receipt(tmp_path, "pipx-git.json", _here(direct_url=GIT))
    line = f'{_inject(tmp_path)}"openlogbook[ais] @ git+https://example.org/ines/logbook.git@{COMMIT}"'
    assert doctor.install_line(pipx, {"ais"}) == line
    receipt = json.loads((RECEIPTS / "pipx-git.json").read_text(encoding="utf-8"))
    receipt["main_package"]["package_or_url"] += "@v0.7.0"
    (tmp_path / "pipx" / "venvs" / "openlogbook" / "pipx_metadata.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    tagged = doctor.install_of(tmp_path / "pipx" / "venvs" / "openlogbook", _here(direct_url=GIT))
    assert doctor.install_line(tagged, {"ais"}) == line, "the commit installed, never the tag"


def test_a_pipx_suffix_and_pip_args_stay(tmp_path: Path) -> None:
    """Without the suffix the line would reach another venv; the index pip was given goes with it, as pip's
    own options. pipx's own `--force-reinstall` is not pip's to carry."""
    pipx = _receipt(tmp_path, "pipx-suffix.json")
    assert doctor.install_line(pipx, {"ais", "mcp"}) == (
        f"{_inject(tmp_path, 'openlogbook-ola', '--no-index --find-links /home/ines/src/dist')}"
        '"openlogbook[ais,mcp]==0.7.0"'
    )
    receipt = json.loads((RECEIPTS / "pipx-suffix.json").read_text(encoding="utf-8"))
    receipt["main_package"]["pip_args"] = ["--pre"]
    (tmp_path / "pipx" / "venvs" / "openlogbook-ola" / "pipx_metadata.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    other = doctor.install_of(tmp_path / "pipx" / "venvs" / "openlogbook-ola", HERE)
    assert doctor.install_line(other, {"ais"}) is None and "--pre" in other.why, (
        "only index options are carried"
    )


def test_a_pipx_injected_package_is_named_never_lost(tmp_path: Path) -> None:
    """Since the third review the line adds to the venv pipx made and removes nothing from it, so an
    injected package stays where it is; no `--force` makes the venv again."""
    pipx = _receipt(tmp_path, "pipx-injected.json")
    assert pipx.extras == {"mcp"}
    assert _hint(pipx) == f'websockets not installed: {_inject(tmp_path)}"openlogbook[ais,mcp]==0.7.0"'
    assert "--force" not in _hint(pipx) and "ijson" not in _hint(pipx)


def test_a_pipx_venv_keeps_its_python_and_options(tmp_path: Path) -> None:
    """The third review's first finding: `pipx install --force` made a 3.12 venv again on pipx's own 3.14
    and dropped `--system-site-packages`, and pipx ignores `--python` under `--force`. `pipx inject` installs
    into the venv as it is; the line names no Python and no venv option, and needs none."""
    pipx = _receipt(tmp_path, "pipx-system-site.json")
    line = doctor.install_line(pipx, {"ais"})
    options = "--no-index --find-links /home/ines/src/dist"
    assert line == f'{_inject(tmp_path, pip_args=options)}"openlogbook[ais]==0.7.0"'
    assert "--python" not in line and "--force" not in line and "--system-site-packages" not in line


def test_a_pipx_line_in_powershell_sets_the_home_first(tmp_path: Path) -> None:
    """PowerShell (what Windows Terminal opens) has no `NAME=value command`; the home is set first, in
    quotes, since the right side of an assignment there is an expression (third review, 2)."""
    pipx = _receipt(tmp_path, "pipx-injected.json", _here(windows=True))
    assert doctor.install_line(pipx, {"ais", "mcp"}) == (
        f'$env:PIPX_HOME = "{tmp_path / "pipx"}"; pipx inject openlogbook "openlogbook[ais,mcp]==0.7.0"'
    )


def test_a_pipx_venv_in_the_home_pipx_uses_is_plain_pipx_inject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stranger test (26 October): the line is what pipx's own docs say, `pipx inject openlogbook …`,
    with no `PIPX_HOME=` when the venv is in the home a bare `pipx` uses: the one `PIPX_HOME` names, else
    pipx's default. pipx writes the extras back to its receipt, so `pipx reinstall` keeps them."""
    venv = tmp_path / "pipx" / "venvs" / "openlogbook"
    venv.mkdir(parents=True)
    shutil.copyfile(RECEIPTS / "pipx-injected.json", venv / "pipx_metadata.json")
    named = doctor.install_of(venv, _here(env={"PIPX_HOME": str(tmp_path / "pipx")}))
    assert (
        doctor.install_line(named, {"ais", "mcp"}) == 'pipx inject openlogbook "openlogbook[ais,mcp]==0.7.0"'
    )
    elsewhere = doctor.install_of(venv, _here(env={"PIPX_HOME": str(tmp_path / "other")}))
    line = doctor.install_line(elsewhere, {"ais", "mcp"})
    assert line == f'{_inject(tmp_path)}"openlogbook[ais,mcp]==0.7.0"'
    if sys.platform.startswith("linux"):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "ines")
        default = tmp_path / "ines" / ".local" / "share" / "pipx" / "venvs" / "openlogbook"
        default.mkdir(parents=True)
        shutil.copyfile(RECEIPTS / "pipx-injected.json", default / "pipx_metadata.json")
        found = doctor.install_of(default, HERE)
        assert doctor.install_line(found, {"ais"}) == 'pipx inject openlogbook "openlogbook[ais]==0.7.0"'
        (
            tmp_path / "ines" / ".local" / "pipx"
        ).mkdir()  # every pipx still prefers the old home when it is there
        assert doctor.install_line(doctor.install_of(default, HERE), {"ais"}).startswith("PIPX_HOME=")  # type: ignore[union-attr]


def test_a_uv_tool_line_names_the_python_the_receipt_asked_for_or_none(tmp_path: Path) -> None:
    """The stranger test: `--python <the tool's own bin/python>` was 60 characters of nothing a person chose,
    and named the interpreter `--force` replaces. The line names the receipt's request (`3.12`), and none
    when the receipt has none or names the tool environment's own interpreter (an older doctor's line)."""
    receipt = (RECEIPTS / "uv-pinned.toml").read_text(encoding="utf-8")
    own = tmp_path / "bin" / "python"
    own.parent.mkdir()
    own.write_bytes(b"")
    for request, python in (
        ('python = "3.12"', "--python 3.12 "),
        ("", ""),
        (f"python = {json.dumps(str(own))}", ""),
    ):
        (tmp_path / "uv-receipt.toml").write_text(
            receipt.replace('python = "3.12"', request), encoding="utf-8"
        )
        found = doctor.install_of(tmp_path, _here(executable=str(own)))
        assert doctor.install_line(found, {"ais", "mcp"}) == (
            f"uv tool install --force {python}--no-index --find-links file:///home/ines/src/dist"
            ' "openlogbook[ais,mcp]==0.7.0"'
        ), request


def test_under_homebrew_doctor_says_it_cannot_and_where_to_read_never_a_pip_line(tmp_path: Path) -> None:
    """#334's own fault: `pip install` under Homebrew installs into another Python. The formula installs the
    base package only (homebrew/README.md), so doctor says so and points to docs/install.md."""
    keg = tmp_path / "opt" / "homebrew" / "Cellar" / "logbook" / "0.7.0"
    (keg / "libexec").mkdir(parents=True)
    shutil.copyfile(RECEIPTS / "homebrew-INSTALL_RECEIPT.json", keg / "INSTALL_RECEIPT.json")
    built = json.dumps({"url": (tmp_path / "build" / "openlogbook-0.7.0").as_uri(), "dir_info": {}})
    brew = doctor.install_of(keg / "libexec", _here(direct_url=built))
    assert brew == doctor.Install("homebrew", why=doctor.HOMEBREW)
    assert doctor.install_line(brew, {"ais"}) is None
    assert _hint(brew) == (
        "websockets not installed: Homebrew installed this Logbook and its formula installs the base package"
        ' only; docs/install.md, "Optional extras", says how to add ais'
    )


def test_a_pip_line_names_the_python_this_logbook_runs_in(tmp_path: Path) -> None:
    """A bare `pip` is whichever comes first on PATH, often another Python's; the line names this one."""
    python = str(tmp_path / "venv" / "bin" / "python")
    pip = doctor.install_of(tmp_path / "venv", _here(executable=python))
    assert pip == doctor.Install("pip", requirement="==0.7.0", python=python)
    line = doctor.install_line(pip, {"ais"})
    assert line is not None and line.endswith(' -m pip install "openlogbook[ais]==0.7.0"')
    first = line.removesuffix(' -m pip install "openlogbook[ais]==0.7.0"')
    assert first in (python, f'"{python}"'), "the path itself, quoted only when it must be"
    assert doctor.detect_install().how != "pip" or doctor.detect_install().python == sys.executable
    for odd in ("/home/ines/My Tools/venv/bin/python", "/home/ines/o'brien/bin/python"):
        assert doctor._command(odd, windows=True) == f'& "{odd}"'
        assert doctor._command(odd, windows=False) == f'"{odd}"'


def test_no_interpreter_named_is_no_line_never_a_bare_pip(tmp_path: Path) -> None:
    """The third review's minor finding: an empty `sys.executable` fell back to a bare `pip install`."""
    pip = doctor.install_of(tmp_path / "venv", _here(executable=""))
    assert pip == doctor.Install("pip", why="the interpreter it runs in cannot be named")
    assert "pip install" not in _hint(pip) and "says how to add ais" in _hint(pip)
    uv = _receipt(tmp_path, "uv-with.toml", _here(executable=""))
    assert doctor.install_line(uv, {"ais"}) is None and uv.why == "the interpreter it runs in cannot be named"
    nopip = doctor.install_of(tmp_path / "venv", _here(pip=False, installer="pip\n"))
    assert (
        doctor.install_line(nopip, {"ais"}) is None and nopip.why == "the interpreter it runs in has no pip"
    )


def test_a_uv_receipt_on_another_python_than_the_one_running_is_no_line(tmp_path: Path) -> None:
    """The third review: a line naming the interpreter running now would move a tool the receipt says
    is on 3.12 to another; when the two disagree there is no line. A path in the receipt agrees only
    when it is the running interpreter, or the one its venv was made from."""
    assert (
        doctor.install_line(_receipt(tmp_path, "uv-pinned.toml", _here(python=(3, 13, 1))), {"ais"}) is None
    )
    assert "another Python" in _receipt(tmp_path, "uv-pinned.toml", _here(python=(3, 13, 1))).why
    assert doctor.install_line(_receipt(tmp_path, "uv-pinned.toml", _here(cpython=False)), {"ais"}) is None
    base, other = tmp_path / "python3.12", tmp_path / "python3.13"
    base.write_bytes(b"")
    other.write_bytes(b"")
    receipt = (RECEIPTS / "uv-pinned.toml").read_text(encoding="utf-8")
    for request, agrees in ((base, True), (other, False)):
        text = receipt.replace('python = "3.12"', f"python = {json.dumps(str(request))}")
        (tmp_path / "uv-receipt.toml").write_text(text, encoding="utf-8")
        found = doctor.install_of(tmp_path, _here(base=str(base)))
        assert (doctor.install_line(found, {"ais"}) is not None) is agrees, request
    for request in (">=3.12", "pypy3.12", "3.13t"):
        text = receipt.replace('python = "3.12"', f"python = {json.dumps(request)}")
        (tmp_path / "uv-receipt.toml").write_text(text, encoding="utf-8")
        assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None, request


def test_a_checkout_keeps_its_groups_as_they_are(tmp_path: Path) -> None:
    """The third review: `uv sync` removes what it is not given; the line removes nothing, since it names
    every extra installed beside the new one, so every extra and default group installed stays. Since the
    owner's desk's review of #429 it is the short line a contributor types in the clone, `uv sync --extra
    ais`, the clone named before it, never the 200 characters of `--project` and `--python`; and none when
    `UV_PROJECT_ENVIRONMENT` points `uv sync` at another environment."""
    checkout = tmp_path / "src" / "logbook"
    (checkout / ".venv").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        "[project]\nname = 'openlogbook'\n\n[dependency-groups]\n"
        "dev = ['pytest>=8', 'openlogbook[crypto]']\n",
        encoding="utf-8",
    )
    here = _here(direct_url=json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}}))
    found = doctor.install_of(checkout / ".venv", here)
    assert found == doctor.Install("checkout", folder=str(checkout), python=PYTHON)
    assert doctor.install_line(found, {"ais"}) == "uv sync --extra ais"
    [hint] = [c for c in doctor.extras_checks(lambda m: m != "websockets", found) if c.name == "extra:ais"]
    every = "".join(f" --extra {e}" for e in sorted(doctor.KNOWN_EXTRAS))  # all here but ais, and ais
    assert hint.detail == f"websockets not installed; in the clone, {checkout}: uv sync{every}"
    elsewhere = doctor.install_of(
        checkout / ".venv", dataclasses.replace(here, env={"UV_PROJECT_ENVIRONMENT": "/home/ines/env"})
    )
    assert doctor.install_line(elsewhere, {"ais"}) is None and "UV_PROJECT_ENVIRONMENT" in elsewhere.why
    nameless = doctor.install_of(checkout / ".venv", dataclasses.replace(here, executable=""))
    assert nameless == doctor.Install("checkout", why="the interpreter it runs in cannot be named")


def test_openlogbook_beside_another_tool_or_app_is_no_line(tmp_path: Path) -> None:
    """The third review, 1: `uv tool install --with-executables-from openlogbook pip` makes the tool `pip`;
    a line that installs `openlogbook` as a tool makes a second one and moves the executables. pipx's
    venv of another app with openlogbook injected is likewise not openlogbook's."""
    (tmp_path / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "pip" }, { name = "openlogbook" }]\nentrypoints = [\n'
        '    { name = "logbook", install-path = "/home/ines/.local/bin/logbook",'
        ' from = "openlogbook" },\n]\n',
        encoding="utf-8",
    )
    found = doctor.install_of(tmp_path, HERE)
    assert doctor.install_line(found, {"ais"}) is None and "another tool" in found.why
    receipt = json.loads((RECEIPTS / "pipx-injected.json").read_text(encoding="utf-8"))
    receipt["main_package"]["package"] = "pycowsay"
    venv = tmp_path / "pipx" / "venvs" / "pycowsay"
    venv.mkdir(parents=True)
    (venv / "pipx_metadata.json").write_text(json.dumps(receipt), encoding="utf-8")
    assert doctor.install_line(doctor.install_of(venv, HERE), {"ais"}) is None
    (tmp_path / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "openlogbook", extras = "mcp" }]\n', encoding="utf-8"
    )
    assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None, (
        "extras as a string: no line"
    )


def test_uvs_cache_and_a_python_that_is_no_venv_have_no_line(tmp_path: Path) -> None:
    """The third review, 3 and 6: under `uvx` or `uv run --with` the environment is uv's cache, which a
    line would change for nothing; outside a venv pip installs beside (`--user`) or refuses (PEP 668)."""
    for prefix in (tmp_path / "cache" / "archive-v0" / "Xy12", tmp_path / "cache" / "builds-v0" / ".tmpAb"):
        found = doctor.install_of(prefix, HERE)
        assert doctor.install_line(found, {"ais"}) is None and "uv's cache" in found.why
    relocatable = tmp_path / "env"
    relocatable.mkdir()
    (relocatable / "pyvenv.cfg").write_text("home = /usr/bin\nrelocatable = true\n", encoding="utf-8")
    assert doctor.install_line(doctor.install_of(relocatable, HERE), {"ais"}) is None
    system = doctor.install_of(tmp_path / "usr", _here(venv=False))
    assert doctor.install_line(system, {"ais"}) is None and "not a venv" in system.why


def test_what_cannot_be_read_is_no_line_never_a_traceback(tmp_path: Path) -> None:
    """The third review, 4: a receipt nested past Python's recursion limit raised, and a `direct_url.json`
    that does not decode must never read as "installed from an index"."""
    deep = "[" * 100_000 + "]" * 100_000
    (tmp_path / "pipx_metadata.json").write_text(
        f'{{"note": {deep}, "main_package": {{}}}}', encoding="utf-8"
    )
    assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None
    (tmp_path / "pipx_metadata.json").unlink()
    (tmp_path / "uv-receipt.toml").write_text(
        "[tool]\nx = " + "[" * 2000 + "]" * 2000 + "\n", encoding="utf-8"
    )
    assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None
    found = doctor.install_of(tmp_path / "venv", _here(direct_url="unreadable"))
    assert found.why == "its direct_url.json does not read"


@pytest.mark.skipif(sys.platform == "win32", reason="a backslash is a path separator there")
def test_a_backslash_off_windows_is_no_line(tmp_path: Path) -> None:
    """The third review, 5: bash drops a bare backslash and may read one in quotes as an escape."""
    found = doctor.install_of(tmp_path / "venv", _here(executable="/home/ines/odd\\dir/venv/bin/python"))
    assert doctor.install_line(found, {"ais"}) is None


def test_an_editable_folder_on_another_machine_is_no_line(tmp_path: Path) -> None:
    """The third review, 11: `file://server/share/x` would lose the server."""
    venv = tmp_path / "pipx" / "venvs" / "openlogbook"
    venv.mkdir(parents=True)
    shutil.copyfile(RECEIPTS / "pipx-injected.json", venv / "pipx_metadata.json")
    unc = json.dumps({"url": "file://fileserver/share/logbook", "dir_info": {"editable": True}})
    assert doctor.install_line(doctor.install_of(venv, _here(direct_url=unc)), {"ais"}) is None


def test_a_path_no_quotes_keep_literal_is_no_line(tmp_path: Path) -> None:
    """A `$` or a backtick in a path is expanded inside double quotes by every shell doctor's reader has,
    so the line would name another folder."""
    pipx = tmp_path / "$HOME" / "pipx" / "venvs" / "openlogbook"
    pipx.mkdir(parents=True)
    shutil.copyfile(RECEIPTS / "pipx-injected.json", pipx / "pipx_metadata.json")
    found = doctor.install_of(pipx, HERE)
    assert doctor.install_line(found, {"ais"}) is None and "quotes" in found.why
    with pytest.raises(doctor.NoLine):
        doctor._arg("/home/ines/`date`/python")


def test_a_pip_install_from_a_folder_or_a_repository_is_no_line(tmp_path: Path) -> None:
    """Rule 1 of the third review: pip's line is for an install from an index alone."""
    folder = json.dumps({"url": (tmp_path / "logbook").as_uri(), "dir_info": {"editable": True}})
    for here in (_here(direct_url=folder), _here(direct_url=GIT)):
        found = doctor.install_of(tmp_path / "venv", here)
        assert found.how == "pip" and doctor.install_line(found, {"ais"}) is None
    assert doctor.install_line(doctor.install_of(tmp_path / "venv", _here(version="")), {"ais"}) is None


def test_a_uv_companion_whose_executables_were_installed_keeps_them(tmp_path: Path) -> None:
    """From the second review: `--with-executables-from` leaves only an entrypoint `from` the companion,
    and a plain `--with` in its place removes those executables."""
    uv = _receipt(tmp_path, "uv-with-executables.toml")
    assert doctor.install_line(uv, {"ais", "mcp"}) == (
        "uv tool install --force --python 3.12 --with-executables-from uvicorn==0.38.0"
        ' "openlogbook[ais,mcp]==0.7.0"'
    )
    receipt = (RECEIPTS / "uv-with-executables.toml").read_text(encoding="utf-8")
    (tmp_path / "uv-receipt.toml").write_text(receipt.replace('from = "uvicorn"', 'from = "other"'), "utf-8")
    assert doctor.install_line(doctor.install_of(tmp_path, HERE), {"ais"}) is None, "from what it names not"


def test_under_uv_each_line_says_it_installs_exactly_its_extras(tmp_path: Path) -> None:
    """From the second review: `uv tool install --force` and `uv sync` install exactly the extras named,
    so running the speakers line and then the transcribe line removes speakers again; each says so."""
    uv = _receipt(tmp_path, "uv-with.toml")
    checks = {c.name: c for c in doctor.extras_checks(lambda m: m == "websockets", uv)}
    assert checks["extra:speakers"].detail == (
        "pyannote.audio not installed; the line installs exactly the extras it names, so add any other one"
        " wanted to it: uv tool install --force --python 3.12 --with ijson==3.5.1"
        ' "openlogbook[ais,mcp,speakers]==0.7.0"'
    )
    alone = {c.name: c for c in doctor.extras_checks(lambda m: m != "pyannote.audio", uv)}
    assert alone["extra:speakers"].detail.startswith("pyannote.audio not installed: uv tool install")


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("pipx_metadata.json", json.dumps({"main_package": {"package_or_url": "git+https://[bad/x"}})),
        ("pipx_metadata.json", json.dumps({"main_package": {"package_or_url": 5}})),
        ("pipx_metadata.json", json.dumps({"main_package": None})),
        ("pipx_metadata.json", "[]"),
        ("uv-receipt.toml", '[tool]\nrequirements = [{ name = "openlogbook", git = "https://[x/y" }]\n'),
        ("uv-receipt.toml", '[tool]\nrequirements = [{ name = "openlogbook" }, "ijson"]\n'),
        ("uv-receipt.toml", '[tool]\nrequirements = [{ name = "openlogbook" }, 5]\n'),
        ("uv-receipt.toml", '[tool]\nrequirements = [{ name = "openlogbook" }]\nentrypoints = ["logbook"]\n'),
        ("uv-receipt.toml", "tool = 5\n"),
    ],
)
def test_a_receipt_malformed_in_any_part_is_no_line_never_a_traceback(
    tmp_path: Path, name: str, text: str
) -> None:
    """From the second review: `detect_install` runs on every doctor, setup's doctor step and the end of
    `sync --scheduled`, so a receipt that raised took all three down."""
    (tmp_path / name).write_text(text, encoding="utf-8")
    install = doctor.install_of(tmp_path, HERE)
    assert str(tmp_path / name) in install.why, "the receipt is named"
    assert doctor.install_line(install, {"ais"}) is None


def test_a_pipx_file_url_becomes_a_requirement_too(tmp_path: Path) -> None:
    """A git repository on disk is installed at its commit; a folder installed whole may have changed
    since it was installed, so since the third review it has no line."""
    receipt = json.loads((RECEIPTS / "pipx-git.json").read_text(encoding="utf-8"))
    venv = tmp_path / "pipx" / "venvs" / "openlogbook"
    venv.mkdir(parents=True)
    for url, origin, line in (
        (
            "git+file:///home/ines/src/logbook",
            {"url": "file:///home/ines/src/logbook", "vcs_info": {"vcs": "git", "commit_id": COMMIT}},
            f'{_inject(tmp_path)}"openlogbook[ais] @ git+file:///home/ines/src/logbook@{COMMIT}"',
        ),
        ("file:///home/ines/src/logbook", {"url": "file:///home/ines/src/logbook", "dir_info": {}}, None),
    ):
        receipt["main_package"]["package_or_url"] = url
        (venv / "pipx_metadata.json").write_text(json.dumps(receipt), encoding="utf-8")
        assert (
            doctor.install_line(doctor.install_of(venv, _here(direct_url=json.dumps(origin))), {"ais"})
            == line
        )


def test_a_receipt_with_a_password_or_token_prints_no_line(tmp_path: Path) -> None:
    """From the second review: the line is printed and the first warn of a scheduled run is kept in
    `state/last-run.json`, so an index or a git address with a token in it is named, never printed."""
    token = "__token__:s3cret"
    receipt = json.loads((RECEIPTS / "pipx-suffix.json").read_text(encoding="utf-8"))
    receipt["main_package"]["pip_args"] = ["--index-url", f"https://{token}@example.org/simple"]
    venv = tmp_path / "pipx" / "venvs" / "openlogbook-ola"
    venv.mkdir(parents=True)
    (venv / "pipx_metadata.json").write_text(json.dumps(receipt), encoding="utf-8")
    pipx = doctor.install_of(venv, HERE)
    assert pipx.how == "pipx" and str(venv / "pipx_metadata.json") in pipx.why
    assert "s3cret" not in _hint(pipx) and "password or token" in _hint(pipx)
    for git in (
        f"https://{token}@example.org/ines/logbook.git",
        "https://ghp_x@example.org/ines/logbook.git",
    ):
        (tmp_path / "uv-receipt.toml").write_text(
            f'[tool]\nrequirements = [{{ name = "openlogbook", git = "{git}" }}]\n', encoding="utf-8"
        )
        assert "password or token" in doctor.install_of(tmp_path, HERE).why
        origin = json.dumps({"url": git, "vcs_info": {"vcs": "git", "commit_id": COMMIT}})
        found = doctor.install_of(tmp_path / "venv", _here(direct_url=origin))
        assert "password or token" in found.why and "s3cret" not in _hint(found), "nor from the package's own"
    ssh = "ssh://git@example.org/ines/logbook.git"  # a user name in an ssh address is no secret
    (tmp_path / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "openlogbook", git = "{ssh}" }}]\n', encoding="utf-8"
    )
    origin = json.dumps({"url": ssh, "vcs_info": {"vcs": "git", "commit_id": COMMIT}})
    assert doctor.install_line(doctor.install_of(tmp_path, _here(direct_url=origin)), {"ais"}) == (
        f'uv tool install --force "openlogbook[ais] @ git+{ssh}@{COMMIT}"'
    )


def test_a_global_pipx_install_is_reinstalled_globally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """From the second review: without `--global` the line built a second, per-user Logbook. Since the
    third it adds to the global venv itself, named by its home, whatever this shell's pipx would pick."""
    home = tmp_path / "opt" / "pipx"
    venv = home / "venvs" / "openlogbook"
    venv.mkdir(parents=True)
    shutil.copyfile(RECEIPTS / "pipx-injected.json", venv / "pipx_metadata.json")
    line = f'PIPX_HOME={doctor._arg(str(home))} pipx inject openlogbook "openlogbook[ais,mcp]==0.7.0"'
    monkeypatch.setenv("PIPX_GLOBAL_HOME", str(home))
    assert doctor.install_line(doctor.install_of(venv, HERE), {"ais", "mcp"}) == line
    monkeypatch.delenv("PIPX_GLOBAL_HOME")
    monkeypatch.setenv("PIPX_HOME", str(tmp_path / "elsewhere"))
    assert doctor.install_line(doctor.install_of(venv, HERE), {"ais", "mcp"}) == line
    outside = tmp_path / "loose" / "openlogbook"  # a venv in no pipx home's `venvs`: pipx cannot name it
    outside.mkdir(parents=True)
    shutil.copyfile(RECEIPTS / "pipx-injected.json", outside / "pipx_metadata.json")
    assert doctor.install_line(doctor.install_of(outside, HERE), {"ais"}) is None


def test_every_extra_pyproject_names_is_one_doctor_knows() -> None:
    """From the second review: `uv sync` and `uv tool install --force` install exactly the extras named,
    so an extra doctor did not know would be dropped from every line."""
    import tomllib

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    declared = set(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"])
    assert declared == {extra for extra, _ in (*doctor.EXTRAS, *doctor.UNCHECKED_EXTRAS)}


def test_transcribe_is_satisfied_by_either_engine() -> None:
    for engine in ("mlx_whisper", "faster_whisper"):
        checks = {c.name: c for c in doctor.run(None, {}, installed=lambda m, e=engine: m == e)}
        assert checks["extra:transcribe"].status == "pass", engine
        assert engine.replace("_", "-") in checks["extra:transcribe"].detail


def test_speakers_is_pyannote_audio_and_apart_from_transcribe() -> None:
    """`openlogbook[speakers]` (#307) is its own line, after `sealed` and before `transcribe`:
    pyannote.audio satisfies it and nothing else does, and it satisfies nothing else."""
    checks = {c.name: c for c in doctor.run(None, {}, installed=lambda m: m == "pyannote.audio")}
    assert checks["extra:speakers"] == doctor.Check("extra:speakers", "pass", "pyannote.audio is installed")
    assert checks["extra:transcribe"].status == "warn"
    names = [n for n in checks if n.startswith("extra:")]
    assert names == ["extra:ais", "extra:crypto", "extra:sealed", "extra:speakers", "extra:transcribe"]
    for engine in ("mlx_whisper", "faster_whisper"):
        checks = {c.name: c for c in doctor.run(None, {}, installed=lambda m, e=engine: m == e)}
        assert checks["extra:speakers"].status == "warn", engine


def test_installed_never_raises_on_an_odd_name() -> None:
    assert doctor.module_installed("json") is True
    assert doctor.module_installed("no_such_module_anywhere") is False
    assert doctor.module_installed("no_such_parent.child") is False


# -- the environment ------------------------------------------------------------------------------------


def test_no_live_source_variable_of_the_shell_reaches_a_test() -> None:
    """`tests/conftest.py` drops every `LOGBOOK_*` variable the shell exported before a test runs, so a
    developer's Immich key or IMAP password can never turn a `sync:<name>` line to `configured` and
    change doctor's output under a test; a test that needs one sets its own."""
    leaked = sorted(name for name in os.environ if name.startswith("LOGBOOK_") and name != "LOGBOOK_HOME")
    assert leaked in ([], ["LOGBOOK_SLOW"], ["LOGBOOK_STRESS"], ["LOGBOOK_SLOW", "LOGBOOK_STRESS"])
    assert os.environ["LOGBOOK_HOME"] != "", "the fixture's own"


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


# -- the last scheduled run ---------------------------------------------------------------------------


NOW = datetime(2026, 10, 8, 17, 0, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(last_run, "now", lambda: NOW)
    return NOW


def test_a_fresh_clean_run_passes_with_its_counts(lb: Logbook, clock: datetime) -> None:
    _ran(lb, NOW - timedelta(hours=2))
    check = _run(lb)["last-run"]
    assert check.status == "pass"
    assert check.detail.startswith(
        "2026-10-08 17:00 (2 h ago): alpha 2 lines; doctor 12 pass, 0 warn, 0 fail"
    )


def test_a_run_older_than_26_hours_is_stale(lb: Logbook, clock: datetime) -> None:
    _ran(lb, NOW - timedelta(hours=27))
    check = _run(lb)["last-run"]
    assert (
        check.status == "warn" and "more than 26 h ago" in check.detail and "1 days ago" not in check.detail
    )
    _ran(lb, NOW - timedelta(hours=25))
    assert _run(lb)["last-run"].status == "pass"


def test_a_run_in_which_a_source_failed_warns_with_the_first_failing_line(
    lb: Logbook, clock: datetime
) -> None:
    _ran(lb, NOW - timedelta(hours=1), failed=True)
    check = _run(lb)["last-run"]
    assert check.status == "warn"
    assert "gamma failed" in check.detail and "first failing line: gamma  failed (status 1)" in check.detail


def test_a_run_that_never_reached_doctor_warns_once_it_is_old(lb: Logbook, clock: datetime) -> None:
    _ran(lb, NOW - timedelta(minutes=20), doctor_ran=False)
    check = _run(lb)["last-run"]
    assert check.status == "pass" and "doctor not yet run" in check.detail, "a run in progress"
    _ran(lb, NOW - timedelta(hours=5), doctor_ran=False)
    check = _run(lb)["last-run"]
    assert check.status == "warn" and "did not finish" in check.detail


def test_no_run_and_no_schedule_passes_and_says_how_to_install_one(
    lb: Logbook, clock: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "linux")
    check = _run(lb)["last-run"]
    assert check.status == "pass" and "no schedule on this machine" in check.detail
    assert "logbook sync --install-schedule" in check.detail


def test_a_schedule_that_is_installed_but_has_not_run_warns(
    lb: Logbook, clock: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "linux")
    plan = schedule.plan("linux", Path.home(), "/opt/py")
    schedule.install(plan, lambda _text: None)
    check = _run(lb)["last-run"]
    assert check.status == "warn" and "has not run yet" in check.detail


def _installed_for_the_user(system: str) -> None:
    """The agents or user timers `sync --install-schedule` writes."""
    schedule.install(schedule.plan(system, Path.home(), "/opt/py"), lambda _text: None)


def _installed_for_the_system(system: str) -> None:
    """`sync --install-schedule --system`'s files, copied where the system's scheduler reads them, as
    the printed sudo commands do — under the empty root `tests/conftest.py` gives every test
    (`service.SYSTEM_ROOT`), never the machine's own."""
    plan = schedule.plan(system, Path.home(), "/opt/py", user="ines", system_root=service.SYSTEM_ROOT)
    for text, copy in zip(plan.files.values(), plan.copies, strict=True):
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("system", ["darwin", "linux"])
def test_the_last_run_is_read_whichever_install_wrote_it(
    system: str, lb: Logbook, clock: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`state/last-run.json` is the record's, written by whichever install ran `sync --scheduled`: the
    user's agents, the system's daemons, or one installed elsewhere; the line reads it the same way."""
    monkeypatch.setattr(schedule, "system", lambda: system)
    _ran(lb, NOW - timedelta(hours=2))
    expected = "2026-10-08 17:00 (2 h ago): alpha 2 lines; doctor 12 pass, 0 warn, 0 fail"
    check = _run(lb)["last-run"]
    assert (check.status, check.detail) == ("pass", expected), "no install on this machine"
    _installed_for_the_system(system)
    check = _run(lb)["last-run"]
    assert (check.status, check.detail) == ("pass", expected), "the system's daemons or units"
    for copy in schedule.plan(
        system, Path.home(), "/opt/py", user="ines", system_root=service.SYSTEM_ROOT
    ).copies:
        copy.unlink()
    _installed_for_the_user(system)
    check = _run(lb)["last-run"]
    assert (check.status, check.detail) == ("pass", expected), "the user's agents or timers"


@pytest.mark.parametrize(
    ("system", "user", "system_wide"),
    [
        ("darwin", "launchd agents", "launchd daemons"),
        ("linux", "systemd user timers", "systemd system timers"),
    ],
)
def test_the_user_and_the_system_install_both_present_warn_that_every_run_is_twice(
    system: str,
    user: str,
    system_wide: str,
    lb: Logbook,
    clock: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: system)
    _installed_for_the_user(system)
    _installed_for_the_system(system)
    twice = f"the schedule is installed twice, as {user} and as {system_wide}: every run happens twice"
    check = _run(lb)["last-run"]
    assert check.status == "warn" and "has not run yet" in check.detail and twice in check.detail
    _ran(lb, NOW - timedelta(hours=2))
    check = _run(lb)["last-run"]
    assert check.status == "warn", "a clean run, but every source ran twice"
    assert check.detail.startswith("2026-10-08 17:00 (2 h ago): alpha 2 lines") and twice in check.detail
    assert "`logbook sync --uninstall-schedule`" in check.detail
    _ran(lb, NOW - timedelta(hours=30))
    check = _run(lb)["last-run"]
    assert "more than 26 h ago" in check.detail and twice in check.detail
    assert doctor.schedule_installed({}), "installed, whichever"


def test_a_last_run_file_that_is_not_the_shape_is_a_warning_naming_it(lb: Logbook, clock: datetime) -> None:
    path = lb.root / "state" / "last-run.json"
    path.write_text("{", encoding="utf-8")
    check = _run(lb)["last-run"]
    assert check.status == "warn" and str(path) in check.detail


# -- the restore test ----------------------------------------------------------------------------------


def test_a_restore_test_that_passed_within_35_days_passes(lb: Logbook, clock: datetime) -> None:
    _restore_test(lb, "passed", NOW - timedelta(days=34))
    check = _run(lb)["restore-test"]
    assert check.status == "pass" and check.detail == "passed 2026-09-04 (2026-10-03T030000Z, 2 lines)"


def test_a_restore_test_older_than_35_days_warns(lb: Logbook, clock: datetime) -> None:
    _restore_test(lb, "passed", NOW - timedelta(days=36))
    check = _run(lb)["restore-test"]
    assert check.status == "warn" and "more than 35 days" in check.detail
    assert "logbook backup --restore-test" in check.detail and "first Sunday" in check.detail


def test_no_restore_test_yet_warns_and_says_what_to_run(lb: Logbook, clock: datetime) -> None:
    (lb.root / "state" / "last-restore-test.json").unlink()
    check = _run(lb)["restore-test"]
    assert check.status == "warn" and check.detail.startswith(
        "no restore test yet: run `logbook backup DEST` once, then `logbook backup --restore-test`, which"
        " restores the latest snapshot"
    ), "the stranger test: with no backup, `backup --restore-test` alone answers that there is no snapshot"
    snapshot = lb.root.parent / "Backups" / "owner" / "2026-10-03T030000Z"
    backup.record_backup(lb.root, snapshot.parent.parent, snapshot, 2, "a" * 64, clock)
    check = _run(lb)["restore-test"]
    assert check.status == "warn" and check.detail.startswith(
        "no restore test yet: `logbook backup --restore-test`"
    ), "a backup is recorded: the restore test is the one step left"


def test_a_failed_restore_test_fails_with_the_reason(lb: Logbook, clock: datetime) -> None:
    _restore_test(lb, "failed", NOW - timedelta(days=1), "the copy does not verify: line 2 hash mismatch")
    check = _run(lb)["restore-test"]
    assert check.status == "fail"
    assert (
        check.detail
        == "failed 2026-10-07 (2026-10-03T030000Z): the copy does not verify: line 2 hash mismatch"
    )


def test_a_skipped_restore_test_warns_with_how_to_enable_it(lb: Logbook, clock: datetime) -> None:
    _restore_test(lb, "skipped", NOW - timedelta(days=1), backup.NO_IDENTITY.format(path="/keys/owner.txt"))
    check = _run(lb)["restore-test"]
    assert check.status == "warn" and "LOGBOOK_IDENTITY_FILE" in check.detail and "sync.env" in check.detail


def test_a_restore_test_file_that_is_not_the_shape_is_a_warning_naming_it(
    lb: Logbook, clock: datetime
) -> None:
    path = lb.root / "state" / "last-restore-test.json"
    path.write_text('{"status": "maybe"}', encoding="utf-8")
    check = _run(lb)["restore-test"]
    assert check.status == "warn" and str(path) in check.detail


# -- the serve service ----------------------------------------------------------------------------------


def _install(system: str, port: int = 8765, system_wide: bool = False) -> Path:
    """What `serve --install-service` leaves on this machine: the file where the service manager
    reads it (for a system service, as the owner's `sudo cp` put it there)."""
    svc = service.plan(
        system,
        Path.home(),
        "/opt/logbook/venv/bin/python3",
        port=port,
        system_wide=system_wide,
        user="ines" if system_wide else None,
    )
    [text] = svc.plan.files.values()
    svc.path.parent.mkdir(parents=True, exist_ok=True)
    svc.path.write_text(text, encoding="utf-8")
    return svc.path


def test_no_serve_service_passes_and_says_how_to_install_one(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "system", lambda: "linux")
    monkeypatch.setattr(service, "answering", lambda port: pytest.fail("nothing installed, nothing asked"))
    check = _run(lb)["serve"]
    assert check.status == "pass"
    assert "no serve service" in check.detail and "logbook serve --install-service" in check.detail


def test_a_serve_service_that_answers_passes(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "system", lambda: "linux")
    _install("linux", port=8080)
    asked: list[int] = []
    monkeypatch.setattr(service, "answering", lambda port: asked.append(port) is None)
    check = _run(lb)["serve"]
    assert check.status == "pass" and asked == [8080]
    assert "systemd user service" in check.detail and "answering at http://127.0.0.1:8080/" in check.detail


def test_a_serve_service_that_does_not_answer_warns_with_its_log(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "system", lambda: "darwin")
    _install("darwin", system_wide=True)
    monkeypatch.setattr(service, "answering", lambda port: False)
    check = _run(lb)["serve"]
    assert check.status == "warn"
    assert "launchd daemon" in check.detail and "nothing answers at http://127.0.0.1:8765/" in check.detail
    assert "~/Library/Logs/logbook-serve.log" in check.detail


def test_two_serve_services_on_one_port_warn(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "system", lambda: "darwin")
    _install("darwin")
    _install("darwin", system_wide=True)
    monkeypatch.setattr(service, "answering", lambda port: True)
    check = _run(lb)["serve"]
    assert check.status == "warn"
    assert "launchd agent" in check.detail and "launchd daemon" in check.detail and "one port" in check.detail


def test_the_serve_line_prints_between_the_restore_test_and_the_disk(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "disk_usage", _usage(200 * GIB))
    _status, out = _cli(capsys)
    names = [line.split()[1] for line in out.splitlines()[:-1]]
    assert names.index("restore-test") + 1 == names.index("serve") == names.index("disk") - 1


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
    assert (
        "No record yet: run `logbook demo --out ~/Demo/Logbook` to try one,"
        " or `logbook setup` to start yours." in out
    )
    assert "no logbook found" not in out


def test_the_report_never_prints_an_environment_value(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_DAWARICH_KEY", "sentinel-key-value")
    _status, out = _cli(capsys)
    assert "sentinel-key-value" not in out
    assert "LOGBOOK_DAWARICH_URL" in out


# -- the machine that runs the schedule, the record's home (ADR 0022) ------------------------------------


def _set_home(lb: Logbook, host: str) -> None:
    _write(lb.root / "state" / "home.json", {"host": host, "since": "2026-10-09"})


def test_no_home_set_passes_and_says_how_to_set_one(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(home, "hostname", lambda: "laptop-of-ines")
    check = _run(lb)["schedule"]
    assert check.status == "pass"
    assert check.detail == (
        "no machine runs the scheduled syncs yet: `logbook sync --install-schedule` on the one that keeps"
        " the record makes it that machine (ADR 0022)"
    ), "the stranger test: `home` beside a Home place named in setup read as that place"
    assert "home" not in check.detail.casefold()


def test_the_home_machine_passes(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_home(lb, "nordlys-home")
    monkeypatch.setattr(home, "hostname", lambda: "nordlys-home")
    check = _run(lb)["schedule"]
    assert check.status == "pass"
    assert check.detail == "this machine (nordlys-home) runs the scheduled syncs, since 2026-10-09"


def test_the_home_matches_by_short_name_and_case(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_home(lb, "Nordlys-Home.local")
    monkeypatch.setattr(home, "hostname", lambda: "nordlys-home")
    assert _run(lb)["schedule"].status == "pass"


def test_another_machine_warns_that_writers_belong_on_the_home(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_home(lb, "nordlys-home")
    monkeypatch.setattr(home, "hostname", lambda: "laptop-of-ines")
    check = _run(lb)["schedule"]
    assert check.status == "warn"
    assert check.detail == (
        "the scheduled syncs run on nordlys-home, not on this machine; writers belong on that one"
    )


def test_a_home_file_that_is_not_the_shape_fails_naming_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(home, "hostname", lambda: "nordlys-home")
    path = lb.root / "state" / "home.json"
    _write(path, {"machine": "nordlys-home"})
    check = _run(lb)["schedule"]
    assert check.status == "fail" and "home.json" in check.detail
    path.write_text("{", encoding="utf-8")
    assert _run(lb)["schedule"].status == "fail"


# -- the crossing ceilings (ADR 0016, ADR 0022) ----------------------------------------------------------


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 9))


def test_the_default_policy_passes_listing_each_ceiling(lb: Logbook, today: None) -> None:
    check = _run(lb)["crossing"]
    assert check.status == "pass"
    assert check.detail == "mcp 1", "a new record names the door at tier 1 and no one else"
    _write(policy.policy_path(lb.root), {"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}})
    check = _run(lb)["crossing"]
    assert check.status == "pass"
    assert "hermes 2" in check.detail and "mcp 1" in check.detail


def test_no_policy_file_passes_with_the_defaults(lb: Logbook, today: None) -> None:
    policy.policy_path(lb.root).unlink()
    check = _run(lb)["crossing"]
    assert check.status == "pass"
    assert "no policy/crossing.json" in check.detail and check.detail.endswith(": mcp 1")
    assert "hermes" not in check.detail


def test_an_entry_with_a_date_passes_showing_the_date(lb: Logbook, today: None) -> None:
    _write(
        policy.policy_path(lb.root),
        {"mcp": {"max_tier": 1}, "cloud-model": {"max_tier": 2, "until": "2026-12-31"}},
    )
    check = _run(lb)["crossing"]
    assert check.status == "pass"
    assert "cloud-model 2 until 2026-12-31" in check.detail


def test_an_expired_entry_warns_naming_it(lb: Logbook, today: None) -> None:
    _write(
        policy.policy_path(lb.root),
        {"hermes": {"max_tier": 2}, "cloud-model": {"max_tier": 2, "until": "2026-09-30"}},
    )
    check = _run(lb)["crossing"]
    assert check.status == "warn"
    assert "cloud-model expired on 2026-09-30" in check.detail
    assert "tier 0" in check.detail and "hermes 2" in check.detail


def test_a_policy_that_is_not_the_shape_fails_naming_the_file(lb: Logbook, today: None) -> None:
    path = policy.policy_path(lb.root)
    _write(path, {"cloud-model": {"max_tier": 2, "until": "soon"}})
    check = _run(lb)["crossing"]
    assert check.status == "fail" and "crossing.json" in check.detail
    _write(path, {"cloud-model": {"max_tier": 7}})
    assert _run(lb)["crossing"].status == "fail"
    path.write_text("[", encoding="utf-8")
    assert _run(lb)["crossing"].status == "fail"


# -- the commands the hints name ------------------------------------------------------------------------

HINT_SOURCES = ("doctor.py", "first_run.py", "synthesis.py")  # doctor's lines carry the text of all three
HINT = re.compile(r"`logbook ([^`]+)`")


def _strings(source: str) -> Iterator[str]:
    """Every string literal in `source`, an f-string with `{x}` where each value goes (implicit
    concatenation is one literal to the parser already)."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.JoinedStr):
            yield "".join(
                v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{x}"
                for v in node.values
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _words(hint: str) -> list[str]:
    """A hint's words as a command line: a placeholder (`LAT`, `<seq>`, `{x}`, `…`) stands as `1`."""
    text = hint.split("|")[0].replace("[", " ").replace("]", " ")
    try:
        words = shlex.split(text)
    except ValueError:
        words = text.split()
    return [
        "1" if w.startswith(("<", "{")) or w in ("…", "...") or (w.isupper() and w.isalpha()) else w
        for w in words
    ]


def test_every_command_a_hint_names_is_a_current_command(capsys: pytest.CaptureFixture[str]) -> None:
    """#334: doctor told a newcomer to run `logbook index` and `logbook places add`, names the 22-command
    rename (#215) retired; an old name still runs, but says "is now" first. Every `logbook …` a hint names
    is a command and options today's parser has (a placeholder's type is not checked), never an old name."""
    from logbook.commands.aliases import ALIASES
    from logbook.commands.parser import build_parser

    contrib = Path(doctor.__file__).parent
    hints = {
        h
        for name in HINT_SOURCES
        for text in _strings((contrib / name).read_text(encoding="utf-8"))
        for h in HINT.findall(text)
    }
    assert any(h.startswith("repair index") for h in hints), "the hints are read"
    stale: list[str] = []
    for hint in sorted(hints):
        words = _words(hint)
        if not words or words[0] in ALIASES:
            stale.append(hint)
            continue
        try:
            build_parser().parse_args(words)
        except SystemExit:
            err = capsys.readouterr().err
            if "invalid choice" in err or "unrecognized arguments" in err:
                stale.append(hint)
    assert stale == []
