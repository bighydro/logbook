"""Doctor's install hint in a clone is the short `uv sync --extra <name>` when that line syncs the
environment doctor runs in as it is (the desk, after the tag; #431 dropped `--python` and
`--no-default-groups` from it everywhere). Where it would not, the line says what it needs and no more:
`--python` when what uv would ask for (`UV_PYTHON`, a `.python-version` in the clone or above it) is
not this interpreter's version, since uv would make the venv again with another Python; and
`--no-default-groups` when a default group is not installed here, since uv would add it. A
`pyproject.toml` that does not read is no line. The slow test runs the line in a copy of this checkout
whose venv runs another Python and has no dev group, and finds the extra installed in that venv, its
Python and its groups as they were. No real path: the clone is a temporary folder."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from logbook.contrib import doctor

PYPROJECT = (
    "[project]\nname = 'openlogbook'\n\n[dependency-groups]\ndev = ['pytest>=8', 'openlogbook[crypto]']\n"
)
HERE = doctor.Here(
    executable="",  # set per clone: its venv's python
    base="/usr/bin/python3.13",
    python=(3, 13, 1),
    version="1.0.0",
    pip=False,
    venv=True,
    version_of={"pytest": "9.1.1"}.get,
)


def _clone(tmp_path: Path, pin: str | None = "3.13", pyproject: str = PYPROJECT) -> Path:
    checkout = tmp_path / "src" / "logbook"
    (checkout / ".venv" / "bin").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    if pin is not None:
        (checkout / ".python-version").write_text(pin + "\n", encoding="utf-8")
    return checkout


def _found(checkout: Path, **changes: object) -> doctor.Install:
    here = dataclasses.replace(
        HERE,
        executable=str(checkout / ".venv" / "bin" / "python"),
        direct_url=json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}}),
        **changes,  # type: ignore[arg-type]
    )
    return doctor.install_of(checkout / ".venv", here)


def test_the_short_line_where_it_syncs_this_environment_as_it_is(tmp_path: Path) -> None:
    checkout = _clone(tmp_path)
    assert doctor.install_line(_found(checkout), {"ais"}) == "uv sync --extra ais"
    assert doctor.install_line(_found(checkout, python=(3, 13, 9)), {"ais"}) == "uv sync --extra ais"
    unpinned = _clone(tmp_path / "unpinned", pin=None)
    assert doctor.install_line(_found(unpinned), {"ais"}) == "uv sync --extra ais", "requires-python is met"


def test_another_python_pinned_names_this_one(tmp_path: Path) -> None:
    """The clone pins 3.12 and doctor runs on 3.13: a bare `uv sync` makes `.venv` again on 3.12."""
    for pin in ("3.12", "3.12.3", "cpython-3.12", "pypy@3.13", "3.13t", ">=3.12"):
        checkout = _clone(tmp_path / pin.replace(">=", "ge"), pin=pin)
        line = doctor.install_line(_found(checkout), {"ais"})
        assert line == "uv sync --python /usr/bin/python3.13 --extra ais", (pin, line)
    checkout = _clone(tmp_path / "env")
    found = _found(checkout, env={"UV_PYTHON": "3.12"})
    assert doctor.install_line(found, {"ais"}) == "uv sync --python /usr/bin/python3.13 --extra ais"


def test_a_default_group_not_installed_is_kept_out(tmp_path: Path) -> None:
    checkout = _clone(tmp_path)
    found = _found(checkout, version_of=lambda name: None)
    assert doctor.install_line(found, {"ais"}) == "uv sync --no-default-groups --extra ais"
    both = _found(_clone(tmp_path / "both", pin="3.12"), version_of=lambda name: None)
    assert doctor.install_line(both, {"ais", "crypto"}) == (
        "uv sync --python /usr/bin/python3.13 --no-default-groups --extra ais --extra crypto"
    )
    groups = PYPROJECT + "\n[tool.uv]\ndefault-groups = ['docs']\n"
    docs = _clone(tmp_path / "docs", pyproject=groups.replace("dev =", "docs = ['mkdocs']\ndev ="))
    assert doctor.install_line(_found(docs), {"ais"}) == "uv sync --no-default-groups --extra ais", (
        "the groups uv installs by default are the project's"
    )


def test_a_pyproject_that_does_not_read_is_no_line(tmp_path: Path) -> None:
    checkout = _clone(tmp_path, pyproject="[project\nname = ")
    found = _found(checkout)
    assert doctor.install_line(found, {"ais"}) is None and "pyproject.toml" in found.why, found


# -- the line, run ----------------------------------------------------------------------------------------


def _other_python() -> str | None:
    """An interpreter of another minor version than the one the checkout pins, found, never downloaded."""
    pinned = (Path(__file__).parents[1] / ".python-version").read_text(encoding="utf-8").strip()
    for version in ("3.13", "3.12", "3.14"):
        if version == pinned:
            continue
        found = subprocess.run(
            ["uv", "python", "find", "--no-python-downloads", version],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    return None


@pytest.mark.slow
@pytest.mark.skipif(sys.platform == "win32", reason="the venv's layout and a shell's quoting differ")
def test_the_hinted_line_installs_the_extra_into_the_environment_doctor_runs_in(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("no uv on PATH")
    other = _other_python()
    if other is None:
        pytest.skip("no interpreter of another version than the pinned one")
    source = Path(__file__).parents[1]
    checkout = tmp_path / "logbook"
    shutil.copytree(
        source,
        checkout,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".*_cache", "site", "*.egg-info"),
    )
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "UV_PROJECT", "UV_PYTHON"))
    }
    env["LOGBOOK_HOME"] = str(tmp_path / "home")

    def run(*args: str) -> str:
        done = subprocess.run(args, cwd=checkout, env=env, capture_output=True, encoding="utf-8", check=False)
        assert done.returncode == 0, (args, done.stdout[-2000:], done.stderr[-2000:])
        return done.stdout

    run("uv", "sync", "--python", other, "--no-default-groups")
    python = checkout / ".venv" / "bin" / "python"
    asked = "import sys; print(sys.version_info[:2])"
    before = run(str(python), "-c", asked)
    hint = run(
        str(python),
        "-c",
        "from logbook.contrib import doctor; print(doctor.install_line(doctor.detect_install(), {'ais'}))",
    ).strip()
    assert hint.startswith("uv sync") and "--extra ais" in hint, hint
    run(*hint.split())  # in the clone, as the hint says; no value in it needs quoting here
    assert run(str(python), "-c", asked) == before, "the same Python: the venv was not made again"
    run(str(python), "-c", "import websockets")
    gone = subprocess.run([str(python), "-c", "import pytest"], capture_output=True, check=False)
    assert gone.returncode != 0, "no group was added: the dev group is still not installed"


def test_uv_s_global_pin_is_a_request_and_a_folder_above_the_clone_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review: `uv python pin --global` writes `<config>/uv/.python-version`, and a bare `uv sync`
    makes the venv again on it; uv reads no `.python-version` above the project, so that one asks
    nothing and the line stays short."""
    config = tmp_path / "config"
    (config / "uv").mkdir(parents=True)
    (config / "uv" / ".python-version").write_text("3.11\n", encoding="utf-8")
    checkout = _clone(tmp_path / "global", pin=None)
    found = _found(checkout, env={"XDG_CONFIG_HOME": str(config)})
    assert doctor.install_line(found, {"ais"}) == "uv sync --python /usr/bin/python3.13 --extra ais"
    assert doctor.install_line(_found(checkout, env={}), {"ais"}) == "uv sync --extra ais"
    above = tmp_path / "above"
    nested = _clone(above, pin=None)
    (above / ".python-version").write_text("3.12\n", encoding="utf-8")
    assert doctor.install_line(_found(nested, env={}), {"ais"}) == "uv sync --extra ais"


def test_a_shell_that_drops_the_dev_group_is_no_line(tmp_path: Path) -> None:
    """The review: with `UV_NO_DEV` or `UV_NO_DEFAULT_GROUPS` set, `uv sync` removes the dev group the
    venv has: the short line would not keep the environment as it is, and doctor proves none."""
    checkout = _clone(tmp_path)
    for variable in ("UV_NO_DEV", "UV_NO_DEFAULT_GROUPS"):
        found = _found(checkout, env={variable: "1"})
        assert doctor.install_line(found, {"ais"}) is None and variable in found.why, found
